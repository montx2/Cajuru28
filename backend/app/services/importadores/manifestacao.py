"""Manifestação do Destinatário (evento 210210 — Ciência da Operação).

## Por que este módulo existe

Quando a empresa é **destinatária** de uma NF-e, o Ambiente Nacional distribui
apenas o **resumo** (`resNFe`): chave, emitente, valor — sem o XML fiscal.
Enquanto o destinatário não se manifesta, o XML completo não é liberado, e a
consulta pontual pela chave (`consChNFe`) também volta vazia.

Esse é exatamente o sintoma de "o sistema vê a nota mas não consegue pegar":
não é falha de rede, de certificado nem de cota, e **esperar não resolve** —
sem o evento de Ciência o documento fica em `leiaute="resumo"` para sempre.

Registrar a Ciência da Operação (210210) é o passo oficial que destrava o
download. Depois dele, `consChNFe` passa a devolver o `procNFe` inteiro.

## Fontes

- Manifestação do Destinatário — leiaute do evento e respostas (guia NFe_Util)
- NT 2020.007 / NT 2021.001 — webservice **único** do Ambiente Nacional:
  https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx
- nfephp-org/sped-nfe — prática validada em produção

## Regras que este módulo respeita

1. **Assinatura obrigatória.** Diferente da distribuição DFe (que usa só mTLS),
   o evento precisa de assinatura XML-DSig enveloped sobre a tag `infEvento`,
   com C14N **inclusiva** (`REC-xml-c14n-20010315`), SHA-1 + RSA. O XSD oficial
   (`xmldsig-core-schema_v1.01.xsd`) fixa esse algoritmo: C14N *exclusiva*
   (`xml-exc-c14n#`) é rejeitada com falha de schema (cStat 215).
2. **`Id` no formato canônico:** `ID` + tipoEvento(6) + chave(44) + seq(2).
3. **Idempotência:** `cStat=573` ("Duplicidade de Evento") **é sucesso** — o
   evento já estava registrado. Tratar como erro faria o worker repetir para
   sempre uma nota que já está manifestada.
4. **Ato jurídico:** a Ciência é irreversível e dispara o prazo legal de
   manifestação conclusiva. Por isso o disparo automático é **opt-in por
   empresa** (`Empresa.manifestar_automaticamente`), desligado por padrão.

## O que este módulo deliberadamente NÃO faz

Não registra as manifestações **conclusivas** (210200 Confirmação, 210220
Desconhecimento, 210240 Operação não Realizada). Essas exigem decisão de
negócio sobre a operação em si e nunca devem ser automatizadas por um robô.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

from lxml import etree

from app.core.documentos import normalizar_documento
from app.services.importadores._distribuicao_dfe import (
    CODIGO_IBGE_POR_UF,
    buscar,
    chamar_com_retentativa,
    texto,
)

# Webservice ÚNICO do Ambiente Nacional para eventos (NT 2020.007 §2.1).
# A manifestação não vai para a SEFAZ da UF: vai sempre para o AN.
RECEPCAO_EVENTO_URL_PRODUCAO = (
    "https://www.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx"
)
RECEPCAO_EVENTO_URL_HOMOLOGACAO = (
    "https://hom.nfe.fazenda.gov.br/NFeRecepcaoEvento4/NFeRecepcaoEvento4.asmx"
)
RECEPCAO_EVENTO_SOAP_ACTION = (
    "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4/nfeRecepcaoEvento"
)

NS_PORTAL = "http://www.portalfiscal.inf.br/nfe"
NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeRecepcaoEvento4"
NS_DSIG = "http://www.w3.org/2000/09/xmldsig#"
# Único algoritmo de canonicalização aceito pelo XSD da NF-e (C14N 1.0 inclusiva).
ALG_C14N = "http://www.w3.org/TR/2001/REC-xml-c14n-20010315"

# Evento de Ciência da Operação.
TIPO_EVENTO_CIENCIA = "210210"
DESCRICAO_CIENCIA = "Ciencia da Operacao"
VERSAO_EVENTO = "1.00"

# cStat de sucesso: 135 (registrado), 136 (vinculado) e 573 (duplicidade).
# 573 significa "já manifestado" — para o nosso objetivo (liberar o XML) o
# resultado é idêntico ao sucesso, e repetir não adianta.
CSTAT_EVENTO_REGISTRADO = {"135", "136"}
CSTAT_EVENTO_DUPLICADO = {"573"}
CSTAT_LOTE_PROCESSADO = {"128"}


class ManifestacaoRecusada(Exception):
    """A SEFAZ recebeu o evento e o rejeitou de forma definitiva.

    Distinta de falha de transporte: repetir o mesmo envio não muda o
    resultado (ex.: chave inexistente, destinatário não autorizado). O
    chamador deve registrar o motivo e seguir para o próximo documento.
    """

    def __init__(self, motivo: str, *, cstat: str = "") -> None:
        self.cstat = cstat
        self.motivo = motivo or "Evento rejeitado"
        super().__init__(f"Manifestação rejeitada (cStat={cstat}): {self.motivo}")


@dataclass
class ResultadoManifestacao:
    """Desfecho de uma tentativa de manifestação, pronto para auditoria."""

    sucesso: bool
    cstat: str
    motivo: str
    protocolo: str = ""
    ja_estava_manifestada: bool = False


def _agora_fiscal() -> str:
    """Timestamp no formato exigido pelo XSD, com offset explícito.

    O ambiente recusa `dhEvento` sem fuso. Usamos UTC (`+00:00`) porque é
    inequívoco e sempre válido, evitando depender do relógio local do host.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")


def montar_id_evento(chave: str, tipo_evento: str, sequencia: int) -> str:
    """`ID` + tipoEvento(6) + chave(44) + nSeqEvento(2) — 54 caracteres."""
    return f"ID{tipo_evento}{chave}{sequencia:02d}"


def montar_evento(
    chave: str,
    cnpj: str,
    *,
    uf: str | None,
    tp_amb: str = "1",
    sequencia: int = 1,
    tipo_evento: str = TIPO_EVENTO_CIENCIA,
    descricao: str = DESCRICAO_CIENCIA,
) -> bytes:
    """Monta o `<evento>` **sem assinatura** (a assinatura é aplicada depois).

    `cOrgao` é 91 (Ambiente Nacional) para a manifestação do destinatário —
    o evento não pertence à UF do emitente nem à do destinatário.
    """
    digitos = "".join(c for c in chave if c.isdigit())
    if len(digitos) != 44:
        raise ValueError(f"Chave de acesso deve ter 44 dígitos, veio {len(digitos)}.")

    documento = normalizar_documento(cnpj)
    tag_pessoa = (
        f"<CNPJ>{documento}</CNPJ>" if len(documento) == 14 else f"<CPF>{documento}</CPF>"
    )
    id_evento = montar_id_evento(digitos, tipo_evento, sequencia)

    # cOrgao 91 = Ambiente Nacional (obrigatório na manifestação).
    xml = (
        f'<evento xmlns="{NS_PORTAL}" versao="{VERSAO_EVENTO}">'
        f'<infEvento Id="{id_evento}">'
        f"<cOrgao>91</cOrgao>"
        f"<tpAmb>{tp_amb}</tpAmb>"
        f"{tag_pessoa}"
        f"<chNFe>{digitos}</chNFe>"
        f"<dhEvento>{_agora_fiscal()}</dhEvento>"
        f"<tpEvento>{tipo_evento}</tpEvento>"
        f"<nSeqEvento>{sequencia}</nSeqEvento>"
        f"<verEvento>{VERSAO_EVENTO}</verEvento>"
        f"<detEvento versao=\"{VERSAO_EVENTO}\">"
        f"<descEvento>{descricao}</descEvento>"
        f"</detEvento>"
        f"</infEvento>"
        f"</evento>"
    )
    return xml.encode("utf-8")


def assinar_evento(evento_xml: bytes, cert_path: str, key_path: str) -> bytes:
    """Assina `infEvento` com XML-DSig enveloped (C14N inclusiva, SHA-1/RSA).

    O leiaute de eventos da NF-e exige exatamente este perfil: referência ao
    `Id` do `infEvento`, transforms `enveloped-signature` + `c14n` (inclusiva),
    digest SHA-1 e assinatura RSA-SHA1. Não é escolha nossa — é o que o XSD
    valida e o que o ambiente aceita.

    A assinatura é aplicada sobre o XML canonicalizado do `infEvento`; um byte
    diferente na serialização invalida o digest, por isso usamos o C14N do
    lxml e nunca uma string remontada à mão.
    """
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    import base64

    raiz = etree.fromstring(evento_xml)
    inf_evento = raiz.find(f"{{{NS_PORTAL}}}infEvento")
    if inf_evento is None:
        raise ValueError("Evento sem infEvento — não é possível assinar.")
    id_evento = inf_evento.get("Id")
    if not id_evento:
        raise ValueError("infEvento sem atributo Id — assinatura impossível.")

    # 1. Digest do nó assinado, canonicalizado com C14N 1.0 (inclusiva).
    #
    # ARMADILHA do lxml: `tostring(subelemento, method="c14n", exclusive=False)`
    # injeta um `xmlns=""` espúrio em filhos de elementos que têm atributo
    # (ex.: <descEvento xmlns="">), o que gera digest errado e a SEFAZ rejeita a
    # assinatura (cStat 297). Reparsear o `infEvento` como documento próprio
    # contorna o defeito; o resultado é byte a byte o C14N 1.0 correto (o
    # namespace em escopo é só o padrão `…/nfe`, o mesmo que o verificador vê).
    inf_isolado = etree.fromstring(etree.tostring(inf_evento))
    canonicalizado = etree.tostring(
        inf_isolado, method="c14n", exclusive=False, with_comments=False
    )
    digest = hashes.Hash(hashes.SHA1())
    digest.update(canonicalizado)
    digest_valor = base64.b64encode(digest.finalize()).decode()

    # 2. SignedInfo referenciando o Id, também canonicalizado antes de assinar.
    signed_info_xml = (
        f'<SignedInfo xmlns="{NS_DSIG}">'
        f'<CanonicalizationMethod Algorithm="{ALG_C14N}"/>'
        f'<SignatureMethod Algorithm="http://www.w3.org/2000/09/xmldsig#rsa-sha1"/>'
        f'<Reference URI="#{id_evento}">'
        f"<Transforms>"
        f'<Transform Algorithm="http://www.w3.org/2000/09/xmldsig#enveloped-signature"/>'
        f'<Transform Algorithm="{ALG_C14N}"/>'
        f"</Transforms>"
        f'<DigestMethod Algorithm="http://www.w3.org/2000/09/xmldsig#sha1"/>'
        f"<DigestValue>{digest_valor}</DigestValue>"
        f"</Reference>"
        f"</SignedInfo>"
    )
    signed_info = etree.fromstring(signed_info_xml.encode())
    signed_info_c14n = etree.tostring(
        signed_info, method="c14n", exclusive=False, with_comments=False
    )

    with open(key_path, "rb") as arquivo:
        chave = serialization.load_pem_private_key(arquivo.read(), password=None)
    assinatura = base64.b64encode(
        chave.sign(signed_info_c14n, padding.PKCS1v15(), hashes.SHA1())
    ).decode()

    # 3. Certificado em base64 (sem cabeçalhos PEM), como o XSD espera.
    with open(cert_path, "rb") as arquivo:
        pem = arquivo.read().decode()
    corpo_cert = "".join(
        linha.strip() for linha in pem.splitlines() if "-----" not in linha
    )

    bloco = (
        f'<Signature xmlns="{NS_DSIG}">'
        f"{signed_info_xml}"
        f"<SignatureValue>{assinatura}</SignatureValue>"
        f"<KeyInfo><X509Data><X509Certificate>{corpo_cert}</X509Certificate></X509Data></KeyInfo>"
        f"</Signature>"
    )
    raiz.append(etree.fromstring(bloco.encode()))
    return etree.tostring(raiz, encoding="utf-8")


def _id_lote() -> str:
    """`TIdLote` do XSD: 1 a 15 dígitos. Timestamp UTC (14) + 1 dígito aleatório."""
    import secrets

    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S") + str(secrets.randbelow(10))


def montar_envelope_evento(evento_assinado: bytes, tp_amb: str = "1") -> bytes:
    """Empacota o evento assinado no `envEvento` dentro do SOAP 1.2.

    Atenção ao formato: no NFeRecepcaoEvento4 o corpo SOAP é o próprio
    `<nfeDadosMsg xmlns="…/NFeRecepcaoEvento4">` — SEM o elemento-operação
    `nfeRecepcaoEvento` em volta (esse invólucro existe só no serviço de
    *distribuição*, `nfeDistDFeInteresse`). É assim que o sped-nfe, em produção,
    fala com o Ambiente Nacional.
    """
    evento = evento_assinado.decode("utf-8")
    # Remove a declaração XML: o evento vai embutido, não é documento raiz.
    evento = re.sub(r"^<\?xml[^>]*\?>\s*", "", evento)
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">'
        "<soap12:Body>"
        f'<nfeDadosMsg xmlns="{NS_WSDL}">'
        f'<envEvento xmlns="{NS_PORTAL}" versao="{VERSAO_EVENTO}">'
        f"<idLote>{_id_lote()}</idLote>"
        f"{evento}"
        "</envEvento>"
        "</nfeDadosMsg>"
        "</soap12:Body>"
        "</soap12:Envelope>"
    )
    return xml.encode("utf-8")


def interpretar_resposta_evento(resposta_bytes: bytes) -> ResultadoManifestacao:
    """Lê o `retEnvEvento` e decide se a nota ficou manifestada.

    Trata `573` (duplicidade) como sucesso idempotente: o evento já existe, e
    é justamente isso que queríamos garantir.
    """
    from app.services.importadores.base import AmbienteIndisponivel

    try:
        raiz = ET.fromstring(resposta_bytes)
    except ET.ParseError as exc:
        raise AmbienteIndisponivel(
            f"Ambiente Nacional devolveu resposta não-XML ({resposta_bytes[:200]!r})"
        ) from exc

    fault = buscar(raiz, "Fault")
    if fault is not None:
        detalhe = texto(fault, "faultstring", "Faultstring", "Text") or "SOAP Fault"
        raise AmbienteIndisponivel(f"Ambiente Nacional respondeu SOAP Fault: {detalhe}")

    # O resultado individual mora em infEvento (dentro de retEvento); o cStat
    # de fora é só do lote ("Lote de Evento Processado").
    ret_evento = buscar(raiz, "retEvento")
    alvo = buscar(ret_evento, "infEvento") if ret_evento is not None else None
    if alvo is None:
        alvo = buscar(raiz, "retEnvEvento")
    if alvo is None:
        raise AmbienteIndisponivel(
            f"Resposta sem retEnvEvento/retEvento (primeiros 500 bytes: {resposta_bytes[:500]!r})"
        )

    cstat = texto(alvo, "cStat")
    motivo = texto(alvo, "xMotivo")
    protocolo = texto(alvo, "nProt")

    if cstat in CSTAT_EVENTO_REGISTRADO:
        return ResultadoManifestacao(True, cstat, motivo, protocolo)
    if cstat in CSTAT_EVENTO_DUPLICADO:
        return ResultadoManifestacao(True, cstat, motivo, protocolo, ja_estava_manifestada=True)
    raise ManifestacaoRecusada(motivo, cstat=cstat)


def manifestar_ciencia(
    chave: str,
    cnpj: str,
    cert_path: str,
    key_path: str,
    *,
    uf: str | None = None,
    ambiente: str = "producao",
    sequencia: int = 1,
) -> ResultadoManifestacao:
    """Registra a Ciência da Operação (210210) para uma chave de NF-e.

    Retorna o desfecho; levanta `ManifestacaoRecusada` quando a SEFAZ rejeita
    de forma definitiva e `AmbienteIndisponivel` em falha de transporte (que
    pode ser retentada sem consumir nada).
    """
    tp_amb = "1" if ambiente == "producao" else "2"
    url = (
        RECEPCAO_EVENTO_URL_PRODUCAO
        if ambiente == "producao"
        else RECEPCAO_EVENTO_URL_HOMOLOGACAO
    )
    evento = montar_evento(chave, cnpj, uf=uf, tp_amb=tp_amb, sequencia=sequencia)
    assinado = assinar_evento(evento, cert_path, key_path)
    envelope = montar_envelope_evento(assinado, tp_amb)
    resposta = chamar_com_retentativa(
        envelope, url, cert_path, key_path, soap_action=RECEPCAO_EVENTO_SOAP_ACTION
    )
    return interpretar_resposta_evento(resposta)
