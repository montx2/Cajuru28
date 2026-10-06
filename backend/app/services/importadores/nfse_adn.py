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
- lote de no máximo 50 documentos por chamada, tamanho máximo do lote 1 MB;
- depois de "nenhum documento localizado", aguardar 1 hora antes de perguntar
  de novo (o cooldown mora em app/services/sincronizacao.py + worker);
- o NSU da próxima chamada é SEMPRE o UltNSU devolvido pelo ambiente;
- GET /NFSe/{ChaveAcesso}/Eventos para eventos de um documento específico.

O ADN também aplica limite de consumo: um HTTP 429 é tratado como bloqueio
temporário (mesma política do cStat 656 da SEFAZ), não como erro comum.
"""

from __future__ import annotations

import base64
import binascii
import gzip
import io
import json
import time
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

import httpx

from app.core.documentos import normalizar_documento
from app.services.importadores._distribuicao_dfe import competencia_de_texto, leiaute_do_conteudo
from app.services.importadores.base import (
    AmbienteIndisponivel,
    DocumentoBaixado,
    ImportadorFiscal,
    LoteImportado,
    ConsumoIndevido,
)
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml

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


def _documento_xml(valor: object) -> str:
    try:
        return normalizar_documento(str(valor or ""))
    except ValueError:
        return ""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ler_retry_after(valor: str | None):
    """
    Converte o header HTTP `Retry-After` num `timedelta`, quando presente.

    Aceita os dois formatos do RFC 7231: segundos ("3600") ou data HTTP
    ("Wed, 21 Oct 2026 07:28:00 GMT"). Retorna None se ausente/ilegível —
    aí o chamador cai na espera padrão de 1h. É o único jeito de a API
    devolver um tempo EXATO de desbloqueio; a SEFAZ (NFe/CT-e) não manda isso.
    """
    if not valor:
        return None
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    from email.utils import parsedate_to_datetime

    texto = str(valor).strip()
    if texto.isdigit():
        return _td(seconds=min(int(texto), 24 * 3600))
    try:
        quando = parsedate_to_datetime(texto)
    except (TypeError, ValueError):
        return None
    if quando is None:
        return None
    if quando.tzinfo is None:
        quando = quando.replace(tzinfo=_tz.utc)
    delta = quando - _dt.now(_tz.utc)
    return delta if delta.total_seconds() > 0 else None


# Raízes de DOCUMENTO fiscal distribuídas pelo ADN/SEFAZ. Um ZIP de provedor
# pode vir com mais de um membro (DANFSe, recibo, protocolo) — só um deles é
# a nota. Pegar "o primeiro" às cegas já entregou protocolo/auxiliar ao
# contador no lugar do XML fiscal.
_RAIZES_DOCUMENTO_FISCAL = {"NFSe", "DPS", "NFe", "procNFe", "CTe", "procCTe"}


def _e_documento_fiscal(dados: bytes) -> bool:
    try:
        return _local(ET.fromstring(dados).tag) in _RAIZES_DOCUMENTO_FISCAL
    except ET.ParseError:
        return False


def decodificar_xml_adn(conteudo: str | bytes) -> bytes:
    """
    Converte o ArquivoXml (base64 + gzip, às vezes zip ou XML puro) em bytes
    do XML. Portado do Importarnotas original — formatos reais variam.

    Quando o conteúdo é um ZIP com vários membros, devolve o membro que é o
    DOCUMENTO fiscal (NFSe/DPS/NFe/CTe), não o primeiro da lista: provedores
    já empacotaram recibo/protocolo antes da nota e o "primeiro arquivo"
    virava o XML entregue ao escritório.
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
            membros = [nome for nome in pacote.namelist() if not nome.endswith("/")]
            if not membros:
                raise ValueError("ArquivoXml ZIP vazio")
            conteudos = [(nome, pacote.read(nome)) for nome in membros]
            for _, dados in conteudos:
                if _e_documento_fiscal(dados):
                    return dados
            # Nenhum membro com raiz conhecida: mantém o primeiro — o erro
            # de leitura acontece depois, no conversor, com o item apontado.
            return conteudos[0][1]

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

        return self._interpretar(payload, cnpj, ultimo_nsu, status_http=status_http)

    def interpretar_lote(self, conteudo: bytes, cnpj: str, ultimo_nsu: str) -> LoteImportado:
        return self._interpretar(json.loads(conteudo), cnpj, ultimo_nsu)

    def _interpretar(self, payload: dict, cnpj: str, ultimo_nsu: str, *, status_http: int = 200) -> LoteImportado:
        nsu_consulta = int(ultimo_nsu or "0")
        bruto = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        # 404 com NENHUM_DOCUMENTO_LOCALIZADO = resposta válida de "nada novo".
        # É literalmente o sinal oficial para esperar 1h — ver docstring.
        if status_http == 404:
            processamento = str(
                _campo(payload, "StatusProcessamento", "statusProcessamento") or ""
            )
            if "NENHUM" in processamento.upper().replace("_", " "):
                max_nsu_adn = _campo(payload, "MaxNSU", "maxNSU", "maxNsu")
                return LoteImportado(
                    documentos=[],
                    proximo_nsu=str(nsu_consulta),
                    ha_mais_documentos=False,
                    max_nsu=_para_inteiro(max_nsu_adn, nsu_consulta),
                    sem_novidade=True,
                    resposta_bruta=bruto,
                )
            raise AmbienteIndisponivel(
                f"ADN retornou HTTP 404: {_texto_de_erros(payload) or payload}"
            )

        brutos = _campo(payload, "LoteDFe", "loteDFe", "loteDfe", "Documentos", "documentos")
        if brutos is None or not isinstance(brutos, (list, dict)):
            return LoteImportado(
                documentos=[], proximo_nsu=str(nsu_consulta), ha_mais_documentos=False,
                erros=["ADN devolveu resposta sem um lote de documentos válido; não é confirmação de acervo vazio."],
                resposta_bruta=bruto,
            )
        if isinstance(brutos, dict):
            brutos = [brutos]

        documentos: list[DocumentoBaixado] = []
        eventos: list[EventoFiscal] = []
        erros: list[str] = []
        eventos_nao_reconhecidos = 0
        nsus_brutos: list[int] = []

        for item in brutos:
            if not isinstance(item, dict):
                erros.append("ADN devolveu item de lote em formato inválido.")
                continue

            nsu_item = str(_campo(item, "NSU", "nsu") or "0")
            try:
                nsus_brutos.append(int(nsu_item))
            except (TypeError, ValueError):
                pass

            tipo_item = str(
                _campo(item, "TipoDocumento", "tipoDocumento", "tipoDoc", "Tipo") or ""
            )
            try:
                xml_bytes = decodificar_xml_adn(
                    _campo(item, "ArquivoXml", "arquivoXml", "XML", "xml", "ConteudoXml")
                    or ""
                )
            except Exception as exc:  # noqa: BLE001 — item corrompido não derruba o lote
                erros.append(f"NSU {nsu_item}: não foi possível decodificar o XML ({exc})")
                continue

            # Eventos (cancelamento, CC-e…) não viram documento fiscal, mas
            # NUNCA podem sumir: são devolvidos no lote para o worker aplicar.
            chave_item = str(
                _campo(item, "ChaveAcesso", "chaveAcesso", "Chave", "chave") or ""
            )
            evento = classificar_evento_xml(
                xml_bytes,
                tipo_hint=tipo_item,
                nsu=nsu_item,
                schema=tipo_item,
                chave_hint=chave_item,
            )
            if evento is not None:
                eventos.append(evento)
                if not evento.eh_cancelamento:
                    eventos_nao_reconhecidos += 1
                continue

            try:
                documento = self._converter_documento(item, cnpj, xml_bytes)
            except Exception as exc:  # noqa: BLE001
                erros.append(f"NSU {nsu_item}: {exc}")
                continue
            if not documento.chave_acesso:
                erros.append(
                    f"NSU {nsu_item}: documento sem chave de acesso — não pode ser gravado"
                )
                continue
            documentos.append(documento)

        max_nsu_raw = _campo(payload, "MaxNSU", "maxNSU", "maxNsu")
        ult_nsu_raw = _campo(payload, "UltNSU", "ultNSU", "ultimoNSU")

        # O cursor NUNCA regride nem fica atrás de um item já recebido —
        # inclusive eventos. Antes calculava-se só sobre documentos válidos,
        # o que podia fazer a importação repetir (ou pior, parar) ao encontrar
        # um cancelamento no meio do lote.
        if ult_nsu_raw is not None:
            try:
                proximo = int(ult_nsu_raw)
            except (TypeError, ValueError):
                proximo = max(nsus_brutos, default=nsu_consulta)
        else:
            proximo = max(nsus_brutos, default=nsu_consulta)
        proximo = max(proximo, nsu_consulta, max(nsus_brutos, default=nsu_consulta))

        max_nsu: int | None = None
        if max_nsu_raw is not None:
            try:
                max_nsu = int(max_nsu_raw)
            except (TypeError, ValueError):
                max_nsu = None

        # Uma página com menos de 50 itens não prova que acabou. O ADN
        # pode paginar eventos/notas em lotes menores; maxNSU é prioritário.
        # Sem maxNSU, continue enquanto houver itens e progresso, até a
        # resposta explícita de "nada novo".
        ha_mais = bool(brutos) and proximo > nsu_consulta and (max_nsu is None or proximo < max_nsu)

        return LoteImportado(
            documentos=documentos,
            proximo_nsu=str(proximo),
            ha_mais_documentos=ha_mais,
            eventos=eventos,
            eventos_nao_reconhecidos=eventos_nao_reconhecidos,
            erros=erros,
            max_nsu=str(max_nsu) if max_nsu is not None else None,
            sem_novidade=not brutos,
            resposta_bruta=bruto,
        )

    def buscar_por_nsu(
        self, cnpj: str, cert_path: str, key_path: str, nsu: str, uf: str | None = None
    ) -> DocumentoBaixado | None:
        """
        `GET /DFe/{NSU}` com `lote=false`: o DF-e daquele NSU específico.

        Serve para fechar lacuna — o caso clássico é o NSU que veio faltando
        entre dois lotes. Não confundir com varredura: o limite oficial é de
        20 consultas pontuais por hora, então isto é chamado um a um, nunca em
        loop sobre a base inteira.
        """
        numero = "".join(c for c in str(nsu) if c.isdigit())
        if not numero:
            raise ValueError("NSU inválido para consulta pontual.")
        url = self.base_url.format(nsu=int(numero))
        status_http, payload = self._chamar_com_retentativa(
            url, cnpj, cert_path, key_path, lote=False
        )
        if status_http == 404:
            return None

        brutos = _campo(payload, "LoteDFe", "loteDFe", "loteDfe", "DFe", "dFe") or []
        if isinstance(brutos, dict):
            brutos = [brutos]
        for item in brutos:
            if not isinstance(item, dict):
                continue
            try:
                return self._converter_documento(
                    item,
                    cnpj,
                    decodificar_xml_adn(
                        _campo(item, "ArquivoXml", "arquivoXml", "XML", "xml", "ConteudoXml") or ""
                    ),
                )
            except Exception:  # noqa: BLE001 — documento ilegível não é erro de sistema
                continue
        return None

    def _chamar_com_retentativa(
        self, url: str, cnpj: str, cert_path: str, key_path: str, *, lote: bool = True
    ) -> tuple[int, dict]:
        """
        Até 3 tentativas com espera crescente para 5xx/rede.
        404 é resposta de negócio (nada novo) — devolve sem retentar.
        429 é bloqueio de consumo — também não retenta, para não renovar a espera.
        401/403 sobem na hora (certificado sem permissão).
        """
        documento = normalizar_documento(cnpj)
        # `lote=true` = distribuição em lote a partir do NSU; `lote=false` = o
        # DF-e daquele NSU (manual dos contribuintes, GET /DFe/{NSU}).
        flag_lote = "true" if lote else "false"
        if len(documento) == 11:
            params = {"cpfConsulta": documento, "lote": flag_lote}
        else:
            params = {"cnpjConsulta": documento, "lote": flag_lote}

        ultimo_erro: Exception | None = None
        for tentativa in range(1, _MAX_TENTATIVAS + 1):
            try:
                with httpx.Client(cert=(cert_path, key_path), timeout=60.0) as client:
                    resposta = client.get(
                        url,
                        params=params,
                        headers={"Accept": "application/json", "User-Agent": "Fluxa/0.1"},
                    )
                    if resposta.status_code == 404:
                        try:
                            corpo = resposta.json()
                        except ValueError:
                            corpo = {"texto": resposta.text[:2000]}
                        return 404, corpo if isinstance(corpo, dict) else {"texto": str(corpo)}

                    if resposta.status_code == 429:
                        # "muitas requisições" é bloqueio, não falha de rede:
                        # retentar já só renova o bloqueio (é a regra do ADN:
                        # 1h de espera depois de "nada novo").
                        corpo = resposta.text[:500] if hasattr(resposta, "text") else ""
                        # Diferente da SEFAZ, o ADN PODE mandar o tempo exato de
                        # espera no header `Retry-After` (segundos ou data HTTP).
                        # Quando vier, é a fonte da verdade — usamos em vez da
                        # estimativa de 1h.
                        bloqueio = _ler_retry_after(resposta.headers.get("Retry-After"))
                        raise ConsumoIndevido(
                            f"HTTP 429 — limite de requisições do ADN atingido. {corpo}".strip(),
                            cstat="429",
                            ambiente="ADN",
                            bloqueio=bloqueio,
                        )

                    if resposta.status_code >= 500:
                        ultimo_erro = httpx.HTTPStatusError(
                            f"HTTP {resposta.status_code}",
                            request=resposta.request,
                            response=resposta,
                        )
                        if tentativa < _MAX_TENTATIVAS:
                            time.sleep(_ESPERA_BASE_SEGUNDOS * (2 ** (tentativa - 1)))
                            continue
                        raise AmbienteIndisponivel(
                            f"ADN indisponível (HTTP {resposta.status_code}) após "
                            f"{_MAX_TENTATIVAS} tentativas"
                        ) from ultimo_erro

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

        raise AmbienteIndisponivel(
            f"ADN indisponível após {_MAX_TENTATIVAS} tentativas: {ultimo_erro}"
        ) from ultimo_erro

    def _converter_documento(
        self,
        item: dict,
        cnpj_consultado: str,
        xml_bytes: bytes | None = None,
        schema: str = "",
    ) -> DocumentoBaixado:
        chave = str(_campo(item, "ChaveAcesso", "chaveAcesso", "Chave", "chave") or "")
        nsu_item = str(_campo(item, "NSU", "nsu") or "0")

        if xml_bytes is None:
            conteudo = _campo(item, "ArquivoXml", "arquivoXml", "XML", "xml", "ConteudoXml")
            if not conteudo:
                raise ValueError("Item do lote sem ArquivoXml")
            xml_bytes = decodificar_xml_adn(conteudo)

        extraido = self._extrair_dados_xml(xml_bytes, cnpj_consultado)
        if not extraido["data_emissao"]:
            raise ValueError("XML de NFS-e sem data de emissão: resposta preservada, não será criada nota com data inventada.")
        if not chave:
            chave = extraido["chave"]
        # NFS-e do leiaute nacional sempre chega com o documento inteiro (o
        # ADN não distribui "resumo" como o Ambiente Nacional da NFe), mas o
        # tipo declarado no lote pode dizer o contrário — respeita se vier.
        # Mesma regra do lado NF-e/CT-e: o que decide é o CONTEÚDO do XML. O
        # nome do schema já veio trocado mais de uma vez, e um resumo gravado
        # como documento inteiro sai da fila de complemento para sempre.
        leiaute = leiaute_do_conteudo(xml_bytes, schema)

        return DocumentoBaixado(
            chave_acesso=chave,
            nsu=nsu_item,
            xml=xml_bytes,
            data_emissao=extraido["data_emissao"],
            valor_total=extraido["valor_total"],
            direcao=extraido["direcao"],
            competencia=competencia_de_texto(
                extraido["competencia"], extraido["data_emissao"]
            ),
            leiaute=leiaute,
            numero=extraido["numero"],
            serie=extraido["serie"],
            emitente_documento=extraido["prestador"],
            emitente_nome=extraido["prestador_nome"],
            destinatario_documento=extraido["tomador"],
            destinatario_nome=extraido["tomador_nome"],
            status_autorizacao=extraido["situacao"],
        )

    def _extrair_dados_xml(self, xml_bytes: bytes, cnpj_consultado: str) -> dict:
        """
        Extração resiliente (namespace-agnóstica) do leiaute nacional de NFS-e.

        Campos ausentes ficam vazios — nunca derruba a importação. Além do que
        já era lido, saem daqui os dados que a tela e o relatório do contador
        precisam: competência (dCompet/PeriodoRef), número, série, prestador,
        tomador e situação de autorização.
        """
        try:
            raiz = ET.fromstring(xml_bytes)
        except ET.ParseError as exc:
            raise ValueError("XML de NFS-e malformado: não pode virar uma nota vazia.") from exc

        planos: dict[str, str] = {}
        self._achatar(raiz, "", planos)

        def valor(*sufixos: str) -> str:
            for sufixo in sufixos:
                sufixo_clean = sufixo.strip().lower()
                for caminho, conteudo in planos.items():
                    caminho_clean = caminho.strip().lower()
                    if caminho_clean == sufixo_clean or caminho_clean.endswith("/" + sufixo_clean):
                        return conteudo
            return ""

        data_emissao = (
            valor("dhProc", "dhEmi", "DataHoraGeracao", "DataEmissao", "dhGer", "dEmi")
            or valor("dCompet", "dComp")
            or ""
        )
        competencia = (
            valor("dCompet", "dComp", "competencia", "PeriodoRef/apuracao", "periodoApuracao", "PeriodoCompetencia", "cPerCont")
            or ""
        )
        valor_texto = (
            valor("vLiq", "vServ", "vServPrest", "vBC", "vNF", "vTotal")
            or "0"
        ).replace(",", ".")
        try:
            valor_total = float(valor_texto or 0)
        except ValueError:
            valor_total = 0.0

        prestador = ""
        for caminho, conteudo in planos.items():
            caminho_lower = f"/{caminho.lower()}/"
            if "/prest/" in caminho_lower or "/emit/" in caminho_lower:
                if caminho_lower.endswith("/cnpj/") or caminho_lower.endswith("/cpf/"):
                    prestador = _documento_xml(conteudo)
                    if prestador:
                        break
        if not prestador:
            prestador = _documento_xml(valor("prest/CNPJ", "prest/CPF", "emit/CNPJ", "emit/CPF"))

        tomador = ""
        for caminho, conteudo in planos.items():
            caminho_lower = f"/{caminho.lower()}/"
            if "/toma/" in caminho_lower or "/dest/" in caminho_lower:
                if caminho_lower.endswith("/cnpj/") or caminho_lower.endswith("/cpf/"):
                    tomador = _documento_xml(conteudo)
                    if tomador:
                        break

        cnpj_canonico = _documento_xml(cnpj_consultado)
        direcao = "prestada" if prestador and prestador == cnpj_canonico else "tomada"

        chave = ""
        for elemento in raiz.iter():
            if _local(elemento.tag).lower() == "infnfse":
                for nome, val in elemento.attrib.items():
                    if _local(nome).lower() == "id":
                        chave_id = val[3:] if val.upper().startswith("NFS") else val
                        if len(chave_id.strip()) >= 44:
                            chave = chave_id.strip()
                            break
            if chave:
                break
        if not chave:
            chave = (valor("chNFSe", "chaveAcesso", "chave") or "").strip()

        return {
            "data_emissao": data_emissao,
            "competencia": competencia,
            "valor_total": valor_total,
            "direcao": direcao,
            "chave": chave,
            "numero": valor("nNFSe", "nInscri", "numNFSe"),
            "serie": valor("serie"),
            "prestador": prestador,
            "prestador_nome": valor("prest/xNome", "emit/xNome", "xNome"),
            "tomador": tomador,
            "tomador_nome": valor("toma/xNome", "dest/xNome"),
            "situacao": valor("xSit", "descSit"),
        }

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


def _para_inteiro(valor: object, padrao: int | str) -> str:
    """Normaliza NSU para inteiro em string (o ADN devolve com zeros à esquerda)."""
    digitos = "".join(c for c in str(valor if valor not in (None, "") else padrao) if c.isdigit())
    return str(int(digitos)) if digitos else str(padrao)


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
