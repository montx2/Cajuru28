"""
Constantes compartilhadas por NFe e CT-e — ambos usam o mesmo webservice
nacional de Distribuição DFe (NFeDistribuicaoDFe), só muda o schema do
documento de dentro do docZip.
"""

import time

import httpx

_MAX_TENTATIVAS = 3
_ESPERA_BASE_SEGUNDOS = 5

# Código IBGE de cada UF — usado no campo cUFAutor da consulta. Dado público
# e estável (não muda), por isso não é um problema hardcodear.
CODIGO_IBGE_POR_UF = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16",
    "TO": "17", "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25",
    "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
    "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50",
    "MT": "51", "GO": "52", "DF": "53",
}

# Endpoints do webservice nacional de Distribuição DFe (SOAP 1.2). É
# centralizado — ao contrário dos serviços de autorização/emissão, não há
# um endpoint por UF para este serviço específico.
DISTRIBUICAO_DFE_URL_PRODUCAO = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
DISTRIBUICAO_DFE_URL_HOMOLOGACAO = "https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"

SOAP_ACTION = "http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe/nfeDistDFeInteresse"


def montar_envelope(cnpj: str, cuf_autor: str, tp_amb: str, ultimo_nsu: str) -> bytes:
    """
    Monta o envelope SOAP 1.2 de consulta por NSU (distNSU/ultNSU) —
    estrutura confirmada contra exemplos reais de produção (ver
    nfe_sefaz.py para as fontes). Sem assinatura XML: a autenticação é só
    pelo certificado A1 usado no TLS da chamada (mTLS), não uma assinatura
    dentro do XML — diferente dos serviços de emissão/autorização de NFe.
    """
    ultimo_nsu_preenchido = ultimo_nsu.zfill(15)
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<soap12:Envelope xmlns:soap12="http://www.w3.org/2003/05/soap-envelope">
  <soap12:Body>
    <nfeDistDFeInteresse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDadosMsg>
        <distDFeInt xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
          <tpAmb>{tp_amb}</tpAmb>
          <cUFAutor>{cuf_autor}</cUFAutor>
          <CNPJ>{cnpj}</CNPJ>
          <distNSU>
            <ultNSU>{ultimo_nsu_preenchido}</ultNSU>
          </distNSU>
        </distDFeInt>
      </nfeDadosMsg>
    </nfeDistDFeInteresse>
  </soap12:Body>
</soap12:Envelope>"""
    return xml.encode("utf-8")


def buscar(elemento, nome_local: str):
    """
    Procura o primeiro descendente cujo nome local (sem o namespace, que
    varia entre soap12/wsdl/portalfiscal) bate com `nome_local`. Menos
    frágil que casar o namespace exato em cada nível do envelope.
    """
    for e in elemento.iter():
        if e.tag.split("}")[-1] == nome_local:
            return e
    return None


def buscar_todos(elemento, nome_local: str):
    return [e for e in elemento.iter() if e.tag.split("}")[-1] == nome_local]


def chamar_com_retentativa(envelope: bytes, url: str, cert_path: str, key_path: str) -> bytes:
    """
    Mesmo padrão de retentativa do importador de NFS-e (nfse_adn.py): até 3
    tentativas com espera crescente para erro 5xx/transporte. O SEFAZ não
    costuma usar HTTP 429 como o ADN — limite de consumo aqui normalmente
    vem como um cStat de negócio dentro de uma resposta 200 OK, que quem
    chama esta função trata separadamente (ver nfe_sefaz.py).
    """
    ultimo_erro: Exception | None = None
    for tentativa in range(1, _MAX_TENTATIVAS + 1):
        try:
            with httpx.Client(cert=(cert_path, key_path), timeout=60.0) as client:
                resposta = client.post(
                    url,
                    content=envelope,
                    headers={
                        "Content-Type": f'application/soap+xml; charset=utf-8; action="{SOAP_ACTION}"',
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

    raise ConnectionError(f"SEFAZ indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}") from ultimo_erro
