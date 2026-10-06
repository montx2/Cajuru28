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
4. **Ato jurídico:** a Ciência é irreversível e faz o destinatário dever a
   manifestação conclusiva (que, sem evento, é presumida pelo Ajuste
   SINIEF 14/2026). Como é ela que destrava o XML completo — e sem ela a nota
   fica presa em `resNFe` para sempre —, o disparo automático vem **ligado por
   padrão** e é uma chave por empresa (`Empresa.manifestar_automaticamente`),
   que o operador pode desligar na tela da empresa.

## As manifestações conclusivas (e por que só a pedido do operador)

A Ciência da Operação só é aceita **até 10 dias** contados da autorização da
NF-e (Ajuste SINIEF 44/20, tabela da NT 2020.001). Depois disso a SEFAZ devolve
`cStat 596` e a nota fica presa em resumo — sem XML completo para escriturar.
A saída prevista na norma é a manifestação **conclusiva**: Confirmação da
Operação (210200), Desconhecimento (210220) ou Operação não Realizada (210240),
aceitas por 90 dias (Ajuste SINIEF 14/2026; eram 180). Elas também fazem o Ambiente Nacional liberar a
NF-e — exceto o Desconhecimento, que por regra não devolve o XML.

Esses três eventos dizem à SEFAZ o que aconteceu com a operação (e a
Confirmação impede o emitente de cancelar a nota). Por isso o robô **não os
dispara sozinho**: `manifestar_conclusiva` existe para o operador decidir na
tela, com a justificativa obrigatória (15 a 255 caracteres) quando o evento
exige.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as escapar_xml
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

# Eventos de manifestação do destinatário (leiaute ConfRecebto).
TIPO_EVENTO_CIENCIA = "210210"
TIPO_EVENTO_CONFIRMACAO = "210200"
TIPO_EVENTO_DESCONHECIMENTO = "210220"
TIPO_EVENTO_NAO_REALIZADA = "210240"
DESCRICAO_CIENCIA = "Ciencia da Operacao"
VERSAO_EVENTO = "1.00"

# Descrição exata de cada evento — o XSD valida por enumeração, não por
# semelhança. "Confirmacao da Operacao" e "Ciencia da Operacao" convivem aqui
# porque agora o sistema sabe registrar as duas.
DESCRICOES = {
    TIPO_EVENTO_CONFIRMACAO: "Confirmacao da Operacao",
    TIPO_EVENTO_CIENCIA: DESCRICAO_CIENCIA,
    TIPO_EVENTO_DESCONHECIMENTO: "Desconhecimento da Operacao",
    TIPO_EVENTO_NAO_REALIZADA: "Operacao nao Realizada",
}

# Manifestações conclusivas: encerram a análise da nota e liberam o XML
# completo no Ambiente Nacional — TODAS, exceto o Desconhecimento, que por
# regra do manual não devolve a NF-e (a operação está sendo negada; não há
# documento a escriturar).
EVENTOS_CONCLUSIVOS = {
    TIPO_EVENTO_CONFIRMACAO,
    TIPO_EVENTO_DESCONHECIMENTO,
    TIPO_EVENTO_NAO_REALIZADA,
}
# Eventos que exigem justificativa (xJust, 15 a 255 caracteres).
EVENTOS_COM_JUSTIFICATIVA = {TIPO_EVENTO_DESCONHECIMENTO, TIPO_EVENTO_NAO_REALIZADA}

# Prazo legal da Ciência da Operação: 10 dias contados da AUTORIZAÇÃO da NF-e
# (Ajuste SINIEF 44/20, tabela da NT 2020.001). Depois disso a SEFAZ devolve
# `cStat 596` e a única saída para liberar o XML é uma manifestação conclusiva.
PRAZO_CIENCIA_DIAS = 10

# cStat de sucesso: 135 (registrado), 136 (vinculado) e 573 (duplicidade).
# 573 significa "já manifestado" — para o nosso objetivo (liberar o XML) o
# resultado é idêntico ao sucesso, e repetir não adianta.
CSTAT_EVENTO_REGISTRADO = {"135", "136"}
CSTAT_EVENTO_DUPLICADO = {"573"}
CSTAT_LOTE_PROCESSADO = {"128"}
# "Evento apresentado fora do prazo" — no caso da Ciência, chegou depois dos
# 10 dias contados da autorização da NF-e. Não adianta repetir: o caminho passa
# a ser uma manifestação conclusiva.
CSTAT_EVENTO_FORA_DO_PRAZO = "596"


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
    descricao: str | None = None,
    justificativa: str = "",
) -> bytes:
    """Monta o `<evento>` **sem assinatura** (a assinatura é aplicada depois).

    `cOrgao` é 91 (Ambiente Nacional) para a manifestação do destinatário —
    o evento não pertence à UF do emitente nem à do destinatário.

    Serve para os quatro eventos da manifestação: Ciência (210210), Confirmação
    (210200), Desconhecimento (210220) e Operação não Realizada (210240). Os
    dois últimos exigem `xJust` de 15 a 255 caracteres (o XSD valida o
    tamanho; a SEFAZ recusa sem ela).
    """
    digitos = "".join(c for c in chave if c.isdigit())
    if len(digitos) != 44:
        raise ValueError(f"Chave de acesso deve ter 44 dígitos, veio {len(digitos)}.")

    descricao = descricao or DESCRICOES.get(tipo_evento, DESCRICAO_CIENCIA)
    justificativa = (justificativa or "").strip()
    if tipo_evento in EVENTOS_COM_JUSTIFICATIVA:
        if len(justificativa) < 15:
            raise ValueError(
                "A justificativa é obrigatória e deve ter de 15 a 255 caracteres "
                f"para o evento {tipo_evento}."
            )
    if len(justificativa) > 255:
        justificativa = justificativa[:255]

    documento = normalizar_documento(cnpj)
    tag_pessoa = (
        f"<CNPJ>{documento}</CNPJ>" if len(documento) == 14 else f"<CPF>{documento}</CPF>"
    )
    id_evento = montar_id_evento(digitos, tipo_evento, sequencia)

    # cOrgao 91 = Ambiente Nacional (obrigatório na manifestação).
    # `&`, `<` e `>` são permitidos pelo padrão do XSD, mas precisam sair
    # escapados para o XML continuar bem-formado (o digest da assinatura é
    # calculado sobre estes bytes).
    bloco_justificativa = f"<xJust>{escapar_xml(justificativa)}</xJust>" if justificativa else ""
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
        f"{bloco_justificativa}"
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


def enviar_evento(
    chave: str,
    cnpj: str,
    cert_path: str,
    key_path: str,
    *,
    tipo_evento: str,
    justificativa: str = "",
    uf: str | None = None,
    ambiente: str = "producao",
    sequencia: int = 1,
) -> ResultadoManifestacao:
    """Assina e envia QUALQUER evento da manifestação do destinatário.

    Retorna o desfecho; levanta `ManifestacaoRecusada` quando a SEFAZ rejeita
    de forma definitiva (o `cstat` vai junto — 596, por exemplo, é "fora do
    prazo" e indica que aquele tipo de evento não é mais aceito para a chave) e
    `AmbienteIndisponivel` em falha de transporte, que não consome nada e pode
    ser retentada.
    """
    tp_amb = "1" if ambiente == "producao" else "2"
    url = (
        RECEPCAO_EVENTO_URL_PRODUCAO
        if ambiente == "producao"
        else RECEPCAO_EVENTO_URL_HOMOLOGACAO
    )
    evento = montar_evento(
        chave,
        cnpj,
        uf=uf,
        tp_amb=tp_amb,
        sequencia=sequencia,
        tipo_evento=tipo_evento,
        justificativa=justificativa,
    )
    assinado = assinar_evento(evento, cert_path, key_path)
    envelope = montar_envelope_evento(assinado, tp_amb)
    resposta = chamar_com_retentativa(
        envelope, url, cert_path, key_path, soap_action=RECEPCAO_EVENTO_SOAP_ACTION
    )
    return interpretar_resposta_evento(resposta)


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

    É o evento que libera o XML completo (`procNFe`) para o destinatário — mas
    só dentro de 10 dias contados da autorização (Ajuste SINIEF 44/20). Fora
    disso a SEFAZ responde 596 e a saída passa a ser `manifestar_conclusiva`.
    """
    return enviar_evento(
        chave,
        cnpj,
        cert_path,
        key_path,
        tipo_evento=TIPO_EVENTO_CIENCIA,
        uf=uf,
        ambiente=ambiente,
        sequencia=sequencia,
    )


def manifestar_conclusiva(
    chave: str,
    cnpj: str,
    cert_path: str,
    key_path: str,
    *,
    tipo_evento: str,
    justificativa: str = "",
    uf: str | None = None,
    ambiente: str = "producao",
    sequencia: int = 1,
) -> ResultadoManifestacao:
    """Registra a manifestação CONCLUSIVA (Confirmação/Desconhecimento/Não realizada).

    É o caminho para a nota cujo prazo de Ciência (10 dias) já passou: a
    manifestação conclusiva também faz o Ambiente Nacional gerar o NSU com a
    NF-e completa — exceto o **Desconhecimento**, que por regra do manual não
    devolve o XML (não há operação a escriturar).

    É ato de negócio, não rotina técnica: o destinatário está declarando à
    SEFAZ o que aconteceu com a operação, e a Confirmação impede o emitente de
    cancelar a nota. Por isso nunca é disparada "sozinha" pelo robô: quem
    chama é o operador, com a justificativa quando o evento exige.
    """
    if tipo_evento not in EVENTOS_CONCLUSIVOS:
        raise ValueError(
            f"Evento {tipo_evento} não é uma manifestação conclusiva. "
            f"Use um de {sorted(EVENTOS_CONCLUSIVOS)}."
        )
    return enviar_evento(
        chave,
        cnpj,
        cert_path,
        key_path,
        tipo_evento=tipo_evento,
        justificativa=justificativa,
        uf=uf,
        ambiente=ambiente,
        sequencia=sequencia,
    )
