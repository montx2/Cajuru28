"""
Constantes e helpers compartilhados por NFe e CT-e — ambos usam o webservice
nacional de Distribuição DFe (mesmo padrão SOAP 1.2 + mTLS + docZip gzip).

Fontes:
- Nota Técnica 2014.002 v1.12 (NFe) — NFeDistribuicaoDFe / nfeDistDFeInteresse
  e XSD oficial distDFeInt_v1.01.xsd / retDistDFeInt_v1.01.xsd
- Nota Técnica 2015.002 v1.10 (CT-e) — CTeDistribuicaoDFe / cteDistDFeInteresse
  e distDFeInt_v1.00.xsd
- nfephp-org/sped-nfe (docs/metodos/DistDFe.md) + sped-cte — prática validada

O que o XSD garante (e o código precisa respeitar):

    distDFeInt := tpAmb, cUFAutor?, (CNPJ|CPF), ( distNSU(ultNSU)
                                                 | consNSU(NSU)
                                                 | consChNFe(chNFe) )   <- só NFe
    retDistDFeInt := tpAmb, verAplic, cStat, xMotivo, dhResp,
                     ultNSU, maxNSU, loteDistDFeInt?[ docZip*50 ]

`ultNSU` e `maxNSU` são **obrigatórios** na resposta — inclusive no cStat=656.
É por isso que um bloqueio também serve para realinhar o cursor: o ambiente
acaba de nos dizer qual era o NSU que ele esperava.
"""

from __future__ import annotations

import base64
import gzip
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

import httpx

_MAX_TENTATIVAS = 3
_ESPERA_BASE_SEGUNDOS = 5

# Intervalo mínimo entre requisições dentro do loop de paginação. Recomendado
# explicitamente pelo sped-nfe ("o tempo entre cada busca no LOOP deve ser de
# pelo menos 2 segundos") — paginar o mais rápido possível é o caminho mais
# curto para o cStat=656.
INTERVALO_MINIMO_ENTRE_LOTES_SEGUNDOS = 2.0

CODIGO_IBGE_POR_UF = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16",
    "TO": "17", "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25",
    "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
    "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50",
    "MT": "51", "GO": "52", "DF": "53",
}

# --- NFe (Ambiente Nacional) ---
NFE_DISTRIBUICAO_URL_PRODUCAO = (
    "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
)
NFE_DISTRIBUICAO_URL_HOMOLOGACAO = (
    "https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
)
NFE_SOAP_ACTION = (
    "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"
)
NFE_NS_WSDL = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe"
NFE_NS_PORTAL = "http://www.portalfiscal.inf.br/nfe"
NFE_OPERACAO = "nfeDistDFeInteresse"
NFE_DADOS_MSG = "nfeDadosMsg"
NFE_VERSAO_DIST = "1.01"

# --- CT-e (Ambiente Nacional) ---
# Fontes: sped-cte storage/wscte_4.00_mod57.xml + PyNFe webservices.py
CTE_DISTRIBUICAO_URL_PRODUCAO = (
    "https://www1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"
)
CTE_DISTRIBUICAO_URL_HOMOLOGACAO = (
    "https://hom1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"
)
CTE_SOAP_ACTION = (
    "http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe/cteDistDFeInteresse"
)
CTE_NS_WSDL = "http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe"
CTE_NS_PORTAL = "http://www.portalfiscal.inf.br/cte"
CTE_OPERACAO = "cteDistDFeInteresse"
CTE_DADOS_MSG = "cteDadosMsg"
CTE_VERSAO_DIST = "1.00"

# Aliases legados (nfe_sefaz.py antigo)
DISTRIBUICAO_DFE_URL_PRODUCAO = NFE_DISTRIBUICAO_URL_PRODUCAO
DISTRIBUICAO_DFE_URL_HOMOLOGACAO = NFE_DISTRIBUICAO_URL_HOMOLOGACAO
SOAP_ACTION = NFE_SOAP_ACTION

# --- cStat ---
CSTAT_DOCUMENTOS_LOCALIZADOS = "138"
CSTAT_SEM_DOCUMENTOS = {"137"}
CSTAT_CONSUMO_INDEVIDO = {"656"}
# Textos que o ambiente usa para "não achei / não posso te mostrar" numa
# consulta pontual. Não são erro: são resposta.
_MARCADORES_INEXISTENTE = (
    "NENHUM_DOCUMENTO_LOCALIZADO",
    "NENHUM DOCUMENTO LOCALIZADO",
    "NAO POSSUI PERMISSAO",
    "NÃO POSSUI PERMISSÃO",
    "NSU INEXISTENTE",
    "NENHUM DOCUMENTO ENCONTRADO",
)


def montar_envelope(
    cnpj: str,
    cuf_autor: str,
    tp_amb: str,
    ultimo_nsu: str,
    *,
    ns_wsdl: str = NFE_NS_WSDL,
    ns_portal: str = NFE_NS_PORTAL,
    operacao: str = NFE_OPERACAO,
    dados_msg: str = NFE_DADOS_MSG,
    versao: str = NFE_VERSAO_DIST,
    consulta_especifica: tuple[str, str] | None = None,
) -> bytes:
    """
    Monta o envelope SOAP 1.2 de consulta por NSU (distNSU/ultNSU).

    `consulta_especifica` troca o bloco `distNSU` por uma consulta pontual
    permitida pelo XSD: `("consNSU", "<NSU>…</NSU>")` ou
    `("consChNFe", "<chNFe>…</chNFe>")`.

    Sem assinatura XML: autenticação é só mTLS do certificado A1.
    """
    digitos = "".join(c for c in cnpj if c.isdigit())
    tag_pessoa = f"<CNPJ>{digitos}</CNPJ>" if len(digitos) == 14 else f"<CPF>{digitos}</CPF>"

    if consulta_especifica is None:
        ultimo_nsu_preenchido = str(ultimo_nsu or "0").zfill(15)
        bloco = f"<distNSU>\n            <ultNSU>{ultimo_nsu_preenchido}</ultNSU>\n          </distNSU>"
    else:
        nome, conteudo = consulta_especifica
        bloco = f"<{nome}>\n            {conteudo}\n          </{nome}>"

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <{operacao} xmlns="{ns_wsdl}">
      <{dados_msg}>
        <distDFeInt xmlns="{ns_portal}" versao="{versao}">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{cuf_autor}</cUFAutor>
          {tag_pessoa}
          {bloco}
        </distDFeInt>
      </{dados_msg}>
    </{operacao}>
  </soap12:Body>
</soap12:Envelope>"""
    return xml.encode("utf-8")


def montar_envelope_nfe(cnpj: str, cuf_autor: str, tp_amb: str, ultimo_nsu: str) -> bytes:
    return montar_envelope(cnpj, cuf_autor, tp_amb, ultimo_nsu)


def montar_envelope_cte(cnpj: str, cuf_autor: str, tp_amb: str, ultimo_nsu: str) -> bytes:
    return montar_envelope(
        cnpj,
        cuf_autor,
        tp_amb,
        ultimo_nsu,
        ns_wsdl=CTE_NS_WSDL,
        ns_portal=CTE_NS_PORTAL,
        operacao=CTE_OPERACAO,
        dados_msg=CTE_DADOS_MSG,
        versao=CTE_VERSAO_DIST,
    )


def buscar(elemento, nome_local: str):
    """Primeiro descendente cujo nome local (sem namespace) bate com `nome_local`."""
    for e in elemento.iter():
        if e.tag.split("}")[-1] == nome_local:
            return e
    return None


def buscar_todos(elemento, nome_local: str):
    return [e for e in elemento.iter() if e.tag.split("}")[-1] == nome_local]


def texto(elemento, *nomes: str) -> str:
    """Texto do primeiro filho que bata com um dos nomes, ignorando namespace."""
    for nome in nomes:
        encontrado = buscar(elemento, nome)
        if encontrado is not None and (encontrado.text or "").strip():
            return encontrado.text.strip()
    return ""


@dataclass
class RespostaDistDFe:
    """
    Leitura do `retDistDFeInt`, pronta para os dois usos (lote e pontual).

    `documentos` são os `docZip` já descomprimidos: (nsu, schema, bytes).
    """

    cstat: str = ""
    x_motivo: str = ""
    ultimo_nsu: str = "0"
    max_nsu: str = "0"
    documentos: list[tuple[str, str, bytes]] = field(default_factory=list)

    @property
    def tem_documentos(self) -> bool:
        return self.cstat == CSTAT_DOCUMENTOS_LOCALIZADOS and bool(self.documentos)

    @property
    def sem_novidade(self) -> bool:
        return self.cstat in CSTAT_SEM_DOCUMENTOS

    @property
    def consumo_indevido(self) -> bool:
        return self.cstat in CSTAT_CONSUMO_INDEVIDO

    @property
    def inexistente(self) -> bool:
        """Consulta pontual que simplesmente não achou o documento."""
        motivo = self.x_motivo.upper()
        return self.cstat in CSTAT_SEM_DOCUMENTOS or any(
            marcador in motivo for marcador in _MARCADORES_INEXISTENTE
        )

    @property
    def esgotou(self) -> bool:
        """ultNSU == maxNSU ⇒ não há mais nada para consultar agora."""
        try:
            return int(self.ultimo_nsu) >= int(self.max_nsu)
        except (TypeError, ValueError):
            return False


def interpretar_resposta(resposta_bytes: bytes, *, ambiente: str = "SEFAZ") -> RespostaDistDFe:
    """
    Converte o envelope de resposta em `RespostaDistDFe`.

    Levanta `ConsumoIndevido` (656) e `ValueError` (SOAP Fault / formato
    inesperado). Os NSUs devolvidos vão junto na exceção de bloqueio, porque
    é com eles que o worker realinha o cursor para voltar sem novo 656.
    """
    from app.services.importadores.base import AmbienteIndisponivel, ConsumoIndevido

    try:
        raiz = ET.fromstring(resposta_bytes)
    except ET.ParseError as exc:
        raise AmbienteIndisponivel(
            f"{ambiente} devolveu resposta não-XML ({resposta_bytes[:200]!r})"
        ) from exc

    fault = buscar(raiz, "Fault")
    if fault is not None:
        detalhe = texto(fault, "Faultstring", "faultstring", "Reason", "Text") or resposta_bytes[
            :500
        ].decode("utf-8", "replace")
        raise ValueError(f"{ambiente} respondeu SOAP Fault: {detalhe.strip()}")

    ret = buscar(raiz, "retDistDFeInt")
    if ret is None:
        raise ValueError(
            f"Resposta do {ambiente} não trouxe retDistDFeInt — formato inesperado "
            f"(primeiros 500 bytes: {resposta_bytes[:500]!r})"
        )

    resposta = RespostaDistDFe(
        cstat=texto(ret, "cStat"),
        x_motivo=texto(ret, "xMotivo"),
        ultimo_nsu=texto(ret, "ultNSU") or "0",
        max_nsu=texto(ret, "maxNSU") or "0",
    )

    if resposta.consumo_indevido:
        raise ConsumoIndevido(
            resposta.x_motivo,
            cstat=resposta.cstat,
            ultimo_nsu=resposta.ultimo_nsu,
            max_nsu=resposta.max_nsu,
            ambiente=ambiente,
        )

    for doc_zip in buscar_todos(ret, "docZip"):
        nsu = doc_zip.get("NSU", "") or ""
        schema = doc_zip.get("schema", "") or ""
        if not (doc_zip.text or "").strip():
            continue
        try:
            xml_bytes = gzip.decompress(base64.b64decode(doc_zip.text.strip()))
        except Exception:  # noqa: BLE001 — item corrompido não derruba o lote
            resposta.documentos.append((nsu, schema, b""))
            continue
        resposta.documentos.append((nsu, schema, xml_bytes))

    return resposta


def chamar_com_retentativa(
    envelope: bytes,
    url: str,
    cert_path: str,
    key_path: str,
    soap_action: str = NFE_SOAP_ACTION,
) -> bytes:
    """
    Até 3 tentativas com espera crescente para erro 5xx/transporte.
    Limite de consumo do SEFAZ costuma vir como cStat dentro de HTTP 200
    (ex.: 656 Consumo Indevido) — quem chama trata isso.
    """
    from app.services.importadores.base import AmbienteIndisponivel

    ultimo_erro: Exception | None = None
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            with httpx.Client(cert=(cert_path, key_path), timeout=60.0) as client:
                resposta = client.post(
                    url,
                    content=envelope,
                    headers={
                        "Content-Type": (
                            f'application/soap+xml; charset=utf-8; action="{soap_action}"'
                        ),
                    },
                )
                resposta.raise_for_status()
                return resposta.content
        except (httpx.HTTPStatusError, httpx.TransportError) as exc:
            codigo = getattr(exc, "response", None) and exc.response.status_code
            if codigo and codigo < 500 and codigo != 429:
                # 4xx que não é "muitas requisições" é problema de contrato /
                # certificado — retentar não ajuda.
                raise AmbienteIndisponivel(
                    f"{url} respondeu HTTP {codigo}: {getattr(exc, 'response').text[:300]}"
                ) from exc
            ultimo_erro = exc
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))

    raise AmbienteIndisponivel(
        f"SEFAZ indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
    ) from ultimo_erro


# ---------------------------------------------------------------------------
# Extração de metadados (NFe e CT-e compartilham a forma do XML)
# ---------------------------------------------------------------------------

# Cada campo é procurado primeiro *dentro* do grupo indicado (emit/dest) e só
# depois como elemento de nível raiz. Isso é o que faz a mesma função servir
# para o documento completo (procNFe → infNFe/ide + emit + dest) e para o
# resumo (resNFe → chNFe, CNPJ, xNome, dhEmi, vNF todos soltos no nível 1).
_CAMPOS_COMUNS: dict[str, tuple[tuple[str, str], ...]] = {
    "numero": (("ide", "nNF"), ("ide", "nCTe"), ("", "nNF")),
    "serie": (("ide", "serie"), ("", "serie"), ("", "series")),
    "data_emissao": (("ide", "dhEmi"), ("ide", "dEmi"), ("", "dhEmi"), ("", "dEmi")),
    "competencia": (("", "dComp"), ("", "dCompet"), ("", "cPerCont"), ("ide", "dCompet")),
    "valor": (("", "vNF"), ("", "vTPrest"), ("", "vTRec"), ("vCarga", "vCarga")),
    # No resumo (resNFe/resCTe) o CNPJ/xNome do EMITENTE vêm soltos na raiz —
    # é o que o XSD define — então o fallback de nível raiz é o emitente, não
    # um "qualquer CNPJ" (dest/CNPJ só existe dentro do grupo dest).
    "emit_doc": (("emit", "CNPJ"), ("emit", "CPF"), ("", "CNPJ"), ("", "CPF")),
    "emit_nome": (("emit", "xNome"), ("emit", "nomeRazao"), ("", "xNome")),
    "dest_doc": (("dest", "CNPJ"), ("dest", "CPF"), ("toma3", "CNPJ"), ("toma4", "CNPJ")),
    "dest_nome": (("dest", "xNome"), ("toma3", "xNome"), ("toma4", "xNome")),
    "situacao": (("protNFe", "cStat"), ("protCTe", "cStat"), ("", "cSitNFe"), ("", "cSitCTe")),
    "protocolo": (("protNFe", "nProt"), ("protCTe", "nProt"), ("", "nProt")),
}


def _valor_flattened(planos: dict[str, str], procuras: tuple[tuple[str, str], ...]) -> str:
    """
    Procura `nome` sob o grupo `pai`; se `pai` for "", aceita só elemento de
    nível raiz (sem "/") — que é como o resumo oficial traz os campos.
    """
    for pai, nome in procuras:
        alvo = f"{pai}/{nome}" if pai else nome
        prefixo = f"/{alvo}"
        for caminho, conteudo in planos.items():
            if pai:
                if caminho == alvo or caminho.endswith(prefixo):
                    return conteudo
            else:
                if caminho == alvo:
                    return conteudo
    # Última chance para os grupos aninhados (ex.: infNFe/ide/serie).
    for pai, nome in procuras:
        if not pai:
            continue
        for caminho, conteudo in planos.items():
            if caminho.endswith(f"/{nome}") and f"/{pai}/" in f"/{caminho}":
                return conteudo
    return ""


def achatar(elemento: ET.Element, prefixo: str = "", saida: dict[str, str] | None = None) -> dict[str, str]:
    saida = {} if saida is None else saida
    for filho in elemento:
        nome = filho.tag.split("}")[-1]
        caminho = f"{prefixo}/{nome}" if prefixo else nome
        if len(filho) == 0:
            conteudo = (filho.text or "").strip()
            if conteudo:
                saida.setdefault(caminho, conteudo)
        else:
            achatar(filho, caminho, saida)
    return saida


def extrair_metadados(raiz: ET.Element) -> dict[str, str]:
    """
    Metadados comuns a resumo e documento completo, sem ligar para namespace.

    Funciona tanto para `resNFe` (chNFe/CNPJ/xNome/dhEmi/vNF no nível raiz)
    quanto para `procNFe` (infNFe/ide + emit + dest + protNFe), e o mesmo para
    CT-e (`resCTe` / `procCTe`).
    """
    planos = achatar(raiz)
    return {chave: _valor_flattened(planos, procuras) for chave, procuras in _CAMPOS_COMUNS.items()}


def metadados_da_chave(chave: str) -> dict[str, str]:
    """
    Deriva número, série, CNPJ do emitente e mês de emissão da própria chave.

    A chave de acesso tem formato fixo de 44 dígitos (Manual de Orientação do
    Contribuinte): cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) nNF(9) tpEmis(1)
    cNF(9). O `resNFe` não traz número nem série, e é exatamente o resumo que
    chega para quem ainda não manifestou — sem isso, a listagem sairia muda.
    """
    digitos = "".join(c for c in str(chave or "") if c.isdigit())
    if len(digitos) != 44:
        return {}
    ano, mes = digitos[2:4], digitos[4:6]
    serie = digitos[22:25].lstrip("0") or "0"
    numero = digitos[25:34].lstrip("0") or "0"
    mes_seguro = mes if 1 <= int(mes or 0) <= 12 else "01"
    return {
        "cUF": digitos[0:2],
        "emitente": digitos[6:20],
        "modelo": digitos[20:22],
        "serie": serie,
        "numero": numero,
        "tipo_emissao": digitos[34:35],
        # "2026-08-01" — o mês da chave é o fallback de competência quando o
        # XML não declara dComp/dCompet (e é o que o leiaute usa na DP).
        "competencia": f"20{ano}-{mes_seguro}-01",
    }


def competencia_de_texto(valor: str, data_emissao: str) -> str:
    """
    Data de competência "AAAA-MM-DD" para filtrar por mês.

    Prioridade: o que o próprio documento declara (dComp/dCompet/PeriodoRef),
    depois a data de emissão. O recorte em `YYYY-MM` é o que permite ao
    contador dizer "quero 08/2026" sem depender de fuso horário.
    """
    candidato = (valor or "").strip() or (data_emissao or "").strip()
    if len(candidato) >= 10 and candidato[4] == "-" and candidato[7] == "-":
        return candidato[:10]
    if len(candidato) >= 7 and candidato[4] == "-" and candidato[7] != "-":
        return f"{candidato}-01"
    return ""
