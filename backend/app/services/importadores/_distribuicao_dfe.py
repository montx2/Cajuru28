"""
Constantes e helpers compartilhados por NFe e CT-e — ambos usam o webservice
nacional de Distribuição DFe (mesmo padrão SOAP 1.2 + mTLS + docZip gzip).

Fontes:
- Nota Técnica 2014.002 (NFe) — NFeDistribuicaoDFe / nfeDistDFeInteresse
- NT 2015.002 / Manual CT-e — CTeDistribuicaoDFe / cteDistDFeInteresse
- nfephp-org/sped-nfe, nfephp-org/sped-cte, TadaSoftware/PyNFe
"""

from __future__ import annotations

import time

import httpx

_MAX_TENTATIVAS = 3
_ESPERA_BASE_SEGUNDOS = 5

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
) -> bytes:
    """
    Monta o envelope SOAP 1.2 de consulta por NSU (distNSU/ultNSU).
    Sem assinatura XML: autenticação é só mTLS do certificado A1.
    """
    digitos = "".join(c for c in cnpj if c.isdigit())
    tag_pessoa = f"<CNPJ>{digitos}</CNPJ>" if len(digitos) == 14 else f"<CPF>{digitos}</CPF>"
    ultimo_nsu_preenchido = str(ultimo_nsu or "0").zfill(15)

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <{operacao} xmlns="{ns_wsdl}">
      <{dados_msg}>
        <distDFeInt xmlns="{ns_portal}" versao="{versao}">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{cuf_autor}</cUFAutor>
          {tag_pessoa}
          <distNSU>
            <ultNSU>{ultimo_nsu_preenchido}</ultNSU>
          </distNSU>
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
            if codigo and codigo < 500:
                raise
            ultimo_erro = exc
            if tentativa < _MAX_TENTATIVAS:
                time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))

    raise ConnectionError(
        f"SEFAZ indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
    ) from ultimo_erro
