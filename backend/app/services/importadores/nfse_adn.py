"""
Importador de NFS-e via Ambiente de Dados Nacional (ADN).

Fontes oficiais / código validado em produção:
- Manual dos Contribuintes — APIs do ADN (gov.br/nfse), método GET /DFe/{NSU}
- Swagger oficial: https://adn.nfse.gov.br/contribuintes/docs/index.html
- Repositório original Importarnotas (montx2/Importarnotas) — nfse_lote/adn.py
  (já rodava em produção com o mesmo contrato)

Contrato:
    GET https://adn.nfse.gov.br/contribuintes/DFe/{NSU}
        ?cnpjConsulta=...&lote=true
        autenticação mTLS com o certificado A1 da empresa

    200 -> { LoteDFe: [...], StatusProcessamento, MaxNSU, UltNSU, Alertas, Erros }
    404 -> { StatusProcessamento: "NENHUM_DOCUMENTO_LOCALIZADO" }

Regras oficiais respeitadas:
- lote de no máximo 50 documentos por chamada;
- após o ambiente indicar que não há mais documentos, aguardar 1h
  (cooldown na orquestração: app/api/routers/importacoes.py + worker).
"""

from __future__ import annotations

import base64
import binascii
import gzip
import io
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import httpx

from app.services.importadores.base import DocumentoBaixado, ImportadorFiscal, LoteImportado

ADN_URL_PRODUCAO = "https://adn.nfse.gov.br/contribuintes/DFe/{nsu}"
ADN_URL_HOMOLOGACAO = "https://adn.producaorestrita.nfse.gov.br/contribuintes/DFe/{nsu}"

_MAX_TENTATIVAS = 3
_ESPERA_BASE_SEGUNDOS = 5
_TAMANHO_LOTE = 50


def _campo(dicionario: dict, *nomes: str) -> Any:
    """Busca um campo ignorando PascalCase vs camelCase (o ADN já variou)."""
    if not isinstance(dicionario, dict):
        return None
    for nome in nomes:
        if nome in dicionario:
            return dicionario[nome]
    minusculos = {str(k).lower(): v for k, v in dicionario.items()}
    for nome in nomes:
        if nome.lower() in minusculos:
            return minusculos[nome.lower()]
    return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def decodificar_xml_adn(conteudo: str | bytes) -> bytes:
    """
    Converte o ArquivoXml (base64 + gzip, às vezes zip ou XML puro) em bytes
    do XML. Portado do Importarnotas original — formatos reais variam.
    """
    if isinstance(conteudo, str):
        conteudo = conteudo.strip()
        if conteudo.startswith("<"):
            return conteudo.encode("utf-8")
        try:
            bruto = base64.b64decode(conteudo)
        except (binascii.Error, ValueError) as erro:
            raise ValueError("Conteúdo do ArquivoXml não é base64 nem XML") from erro
    else:
        bruto = conteudo

    if bruto[:2] == b"\x1f\x8b":
        try:
            bruto = gzip.decompress(bruto)
        except OSError as erro:
            raise ValueError("Falha ao descompactar o ArquivoXml (gzip)") from erro

    if bruto[:1] == b"<":
        return bruto

    if bruto[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(bruto)) as pacote:
            nomes = pacote.namelist()
            if nomes:
                return pacote.read(nomes[0])

    try:
        return base64.b64decode(bruto)
    except (binascii.Error, ValueError) as erro:
        raise ValueError("Formato de ArquivoXml não reconhecido") from erro


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
        nsu_consulta = int(ultimo_nsu or "0")
        url = self.base_url.format(nsu=nsu_consulta)
        status_http, payload = self._chamar_com_retentativa(url, cnpj, cert_path, key_path)

        # 404 com NENHUM_DOCUMENTO_LOCALIZADO = resposta válida de "nada novo"
        if status_http == 404:
            processamento = str(
                _campo(payload, "StatusProcessamento", "statusProcessamento") or ""
            )
            if "NENHUM" in processamento.upper().replace("_", " "):
                return LoteImportado(
                    documentos=[],
                    proximo_nsu=str(nsu_consulta),
                    ha_mais_documentos=False,
                )
            raise ConnectionError(
                f"ADN retornou HTTP 404: {_texto_de_erros(payload) or payload}"
            )

        brutos = _campo(payload, "LoteDFe", "loteDFe", "loteDfe", "Documentos", "documentos") or []
        if isinstance(brutos, dict):
            brutos = [brutos]

        documentos: list[DocumentoBaixado] = []
        for item in brutos:
            if not isinstance(item, dict):
                continue
            try:
                documentos.append(self._converter_documento(item, cnpj))
            except Exception:
                # Um documento corrompido não pode derrubar o lote inteiro
                # (mesmo princípio do Importarnotas original).
                continue

        max_nsu_raw = _campo(payload, "MaxNSU", "maxNSU", "maxNsu")
        ult_nsu_raw = _campo(payload, "UltNSU", "ultNSU", "ultimoNSU")

        if documentos:
            proximo = max(int(d.nsu) for d in documentos)
        else:
            proximo = nsu_consulta

        if ult_nsu_raw is not None:
            try:
                proximo = int(ult_nsu_raw)
            except (TypeError, ValueError):
                pass

        max_nsu: int | None = None
        if max_nsu_raw is not None:
            try:
                max_nsu = int(max_nsu_raw)
            except (TypeError, ValueError):
                max_nsu = None

        # Fim da distribuição: lote incompleto, maxNSU atingido, ou NSU não avançou
        if not documentos:
            ha_mais = False
        elif len(documentos) < _TAMANHO_LOTE:
            ha_mais = False
        elif max_nsu is not None and proximo >= max_nsu:
            ha_mais = False
        elif proximo <= nsu_consulta and documentos:
            # ADN devolveu docs mas não avançou o cursor — evita loop infinito.
            # Ainda assim entregamos os docs (idempotência por chave no worker).
            ha_mais = False
        else:
            ha_mais = True

        return LoteImportado(
            documentos=documentos,
            proximo_nsu=str(proximo),
            ha_mais_documentos=ha_mais,
        )

    def _chamar_com_retentativa(
        self, url: str, cnpj: str, cert_path: str, key_path: str
    ) -> tuple[int, dict]:
        """
        Até 3 tentativas com espera crescente para 429 e 5xx.
        404 é resposta de negócio (nada novo) — devolve sem retentar.
        401/403 sobem na hora (certificado sem permissão).
        """
        digitos = "".join(c for c in cnpj if c.isdigit())
        if len(digitos) == 11:
            params = {"cpfConsulta": digitos, "lote": "true"}
        else:
            params = {"cnpjConsulta": digitos, "lote": "true"}

        ultimo_erro: Exception | None = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                with httpx.Client(cert=(cert_path, key_path), timeout=60.0) as client:
                    resposta = client.get(
                        url,
                        params=params,
                        headers={"Accept": "application/json", "User-Agent": "NotasFlow/0.1"},
                    )
                    if resposta.status_code == 404:
                        try:
                            corpo = resposta.json()
                        except ValueError:
                            corpo = {"texto": resposta.text[:2000]}
                        return 404, corpo if isinstance(corpo, dict) else {"texto": str(corpo)}

                    if resposta.status_code == 429 or resposta.status_code >= 500:
                        ultimo_erro = httpx.HTTPStatusError(
                            f"HTTP {resposta.status_code}",
                            request=resposta.request,
                            response=resposta,
                        )
                        if tentativa < _MAX_TENTATIVAS:
                            time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))
                            continue
                        raise ultimo_erro

                    if resposta.status_code >= 400:
                        resposta.raise_for_status()

                    try:
                        corpo = resposta.json()
                    except ValueError:
                        corpo = {"texto": resposta.text[:2000]}
                    return resposta.status_code, corpo if isinstance(corpo, dict) else {"texto": str(corpo)}

            except httpx.TransportError as exc:
                ultimo_erro = exc
                if tentativa < _MAX_TENTATIVAS:
                    time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))
                    continue

        raise ConnectionError(
            f"ADN indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
        ) from ultimo_erro

    def _converter_documento(self, item: dict, cnpj_consultado: str) -> DocumentoBaixado:
        conteudo = _campo(item, "ArquivoXml", "arquivoXml", "XML", "xml", "ConteudoXml")
        if not conteudo:
            raise ValueError("Item do lote sem ArquivoXml")

        xml_bytes = decodificar_xml_adn(conteudo)
        chave = str(_campo(item, "ChaveAcesso", "chaveAcesso", "Chave", "chave") or "")
        nsu_item = str(_campo(item, "NSU", "nsu") or "0")

        data_emissao, valor_total, direcao, chave_xml = self._extrair_dados_xml(
            xml_bytes, cnpj_consultado
        )
        if not chave:
            chave = chave_xml

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=nsu_item,
            xml=xml_bytes,
            data_emissao=data_emissao,
            valor_total=valor_total,
            direcao=direcao,
        )

    def _extrair_dados_xml(
        self, xml_bytes: bytes, cnpj_consultado: str
    ) -> tuple[str, float, str, str]:
        """
        Extração resiliente (namespace-agnóstica) do leiaute nacional de NFS-e.
        Campos ausentes ficam vazios — nunca derruba a importação.
        """
        try:
            raiz = ET.fromstring(xml_bytes)
        except ET.ParseError:
            return "", 0.0, "tomada", ""

        planos: dict[str, str] = {}
        self._achatar(raiz, "", planos)

        def valor(*sufixos: str) -> str:
            for sufixo in sufixos:
                for caminho, conteudo in planos.items():
                    if caminho == sufixo or caminho.endswith("/" + sufixo):
                        return conteudo
            return ""

        data_emissao = valor("dhEmi", "dCompet", "DataHoraGeracao") or ""
        valor_texto = (
            valor("vLiq", "vServ", "vServPrest", "vBC") or "0"
        ).replace(",", ".")
        try:
            valor_total = float(valor_texto or 0)
        except ValueError:
            valor_total = 0.0

        prestador = "".join(
            c for c in (valor("prest/CNPJ", "prest/CPF", "emit/CNPJ", "emit/CPF") or "") if c.isdigit()
        )
        # Fallback: procura CNPJ sob caminho que contenha prest/emit
        if not prestador:
            for caminho, conteudo in planos.items():
                if ("/prest/" in f"/{caminho}/" or caminho.startswith("prest/")) and (
                    caminho.endswith("/CNPJ") or caminho.endswith("/CPF")
                ):
                    prestador = "".join(c for c in conteudo if c.isdigit())
                    if prestador:
                        break
            if not prestador:
                for caminho, conteudo in planos.items():
                    if ("/emit/" in f"/{caminho}/" or caminho.startswith("emit/")) and (
                        caminho.endswith("/CNPJ") or caminho.endswith("/CPF")
                    ):
                        prestador = "".join(c for c in conteudo if c.isdigit())
                        if prestador:
                            break

        cnpj_limpo = "".join(c for c in cnpj_consultado if c.isdigit())
        direcao = "prestada" if prestador and prestador == cnpj_limpo else "tomada"

        chave = ""
        for elemento in raiz.iter():
            if _local(elemento.tag) == "infNFSe":
                for nome, val in elemento.attrib.items():
                    if _local(nome).lower() == "id":
                        digitos = "".join(c for c in val if c.isdigit())
                        if len(digitos) >= 44:
                            chave = digitos
                            break
            if chave:
                break
        if not chave:
            chave = "".join(c for c in (valor("chNFSe", "chaveAcesso", "chave") or "") if c.isdigit())

        return data_emissao, valor_total, direcao, chave

    def _achatar(
        self, elemento: ET.Element, prefixo: str = "", saida: dict[str, str] | None = None
    ) -> dict[str, str]:
        saida = {} if saida is None else saida
        for filho in elemento:
            nome = _local(filho.tag)
            caminho = f"{prefixo}/{nome}" if prefixo else nome
            if len(filho) == 0:
                texto = (filho.text or "").strip()
                if texto:
                    saida.setdefault(caminho, texto)
            else:
                self._achatar(filho, caminho, saida)
        return saida


def _texto_de_erros(dados: dict) -> str | None:
    erros = _campo(dados, "Erros", "erros") or []
    if isinstance(erros, dict):
        erros = [erros]
    mensagens = []
    for erro in erros:
        if isinstance(erro, str):
            mensagens.append(erro)
            continue
        if isinstance(erro, dict):
            codigo = _campo(erro, "Codigo", "codigo", "Code")
            descricao = _campo(erro, "Descricao", "descricao", "Mensagem", "message")
            mensagens.append(f"{codigo} - {descricao}" if codigo else str(descricao))
    return "; ".join(m for m in mensagens if m) or None
