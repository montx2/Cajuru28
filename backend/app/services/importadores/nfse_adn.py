"""
Importador de NFS-e via Ambiente de Dados Nacional (ADN).

Porta a lógica já validada do repositório Importarnotas original:
- endpoint oficial de distribuição de DF-e (não é scraping do portal);
- autenticação mTLS com o certificado A1 da empresa;
- paginação por NSU, lotes de até 50 documentos por chamada;
- respeita o intervalo de 1h do ADN quando não há mais documento novo
  (regra do próprio manual do ADN — existe para não bloquear o CNPJ por
  consumo indevido, então "não travar" aqui significa seguir essa regra,
  não burlar limite nenhum).
"""

import base64
import gzip
import time
import xml.etree.ElementTree as ET

import httpx

from app.services.importadores.base import DocumentoBaixado, ImportadorFiscal, LoteImportado

ADN_URL_PRODUCAO = "https://adn.nfse.gov.br/contribuintes/dfe/{nsu}"
ADN_URL_HOMOLOGACAO = "https://adn.producaorestrita.nfse.gov.br/contribuintes/dfe/{nsu}"

# Namespace do XML de NFS-e nacional — usado para extrair valor/data sem
# depender de parser externo.
_NS = {"nfse": "http://www.sped.fazenda.gov.br/nfse"}

_MAX_TENTATIVAS = 3
_ESPERA_BASE_SEGUNDOS = 5  # 5s, 10s, 20s — espera crescente, igual ao Importarnotas original


class ImportadorNFSeADN(ImportadorFiscal):
    def __init__(self, ambiente: str = "producao"):
        self.base_url = ADN_URL_PRODUCAO if ambiente == "producao" else ADN_URL_HOMOLOGACAO

    def buscar_lote(
        self,
        cnpj: str,
        cert_path: str,
        key_path: str,
        ultimo_nsu: str,
        uf: str | None = None,
    ) -> LoteImportado:
        url = self.base_url.format(nsu=ultimo_nsu)
        payload = self._chamar_com_retentativa(url, cnpj, cert_path, key_path)

        documentos = [
            self._converter_documento(item, cnpj) for item in payload.get("LoteDFe", [])
        ]
        # O ADN não devolve "tem mais" explicitamente em todo payload — na
        # prática, lote com menos de 50 itens costuma indicar fim do
        # histórico disponível até este NSU; a regra de "aguardar 1h" fica
        # na orquestração do worker (app/worker/tasks.py), porque depende
        # de estado (execução anterior) que este importador não guarda.
        ha_mais = len(documentos) >= 50
        proximo_nsu = documentos[-1].nsu if documentos else ultimo_nsu

        return LoteImportado(
            documentos=documentos, proximo_nsu=proximo_nsu, ha_mais_documentos=ha_mais
        )

    def _chamar_com_retentativa(self, url: str, cnpj: str, cert_path: str, key_path: str) -> dict:
        """
        Até 3 tentativas com espera crescente para 429 (rate limit) e erros
        5xx/transporte — mesmo padrão de resiliência do Importarnotas
        original. Erros 4xx que não sejam 429 (ex.: 401/403, certificado
        sem permissão) não adianta tentar de novo — sobem na hora.
        """
        ultimo_erro: Exception | None = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                with httpx.Client(cert=(cert_path, key_path), timeout=60.0) as client:
                    resposta = client.get(url, params={"cnpjConsulta": cnpj, "lote": "true"})
                    resposta.raise_for_status()
                    return resposta.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                codigo = getattr(exc, "response", None) and exc.response.status_code
                # 4xx que não seja 429 não é transitório — não vale retentar.
                if codigo and codigo < 500 and codigo != 429:
                    raise
                ultimo_erro = exc
                if tentativa < _MAX_TENTATIVAS:
                    time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))

        raise ConnectionError(
            f"ADN indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
        ) from ultimo_erro

    def _converter_documento(self, item: dict, cnpj_consultado: str) -> DocumentoBaixado:
        xml_bytes = gzip.decompress(base64.b64decode(item["ArquivoXml"]))
        data_emissao, valor_total, direcao = self._extrair_dados_xml(xml_bytes, cnpj_consultado)

        return DocumentoBaixado(
            chave_acesso=item["ChaveAcesso"],
            nsu=str(item["NSU"]),
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
        )

    def _extrair_dados_xml(self, xml_bytes: bytes, cnpj_consultado: str) -> tuple[str, float, str]:
        """
        Extração mínima (data, valor, direção tomada/prestada) para não
        depender de biblioteca externa de parse de NFS-e nacional. Se o
        volume de campos precisados crescer (Fase de relatórios/exportação),
        trocar por uma lib dedicada de schema NFS-e é o próximo passo.
        """
        raiz = ET.fromstring(xml_bytes)
        data_emissao = raiz.findtext(".//nfse:dhEmi", default="", namespaces=_NS)
        valor_texto = raiz.findtext(".//nfse:vLiq", default="0", namespaces=_NS)
        prestador_cnpj = raiz.findtext(".//nfse:prest/nfse:CNPJ", default="", namespaces=_NS)

        direcao = "prestada" if prestador_cnpj == cnpj_consultado else "tomada"
        return data_emissao, float(valor_texto or 0), direcao
