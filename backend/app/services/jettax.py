"""Adaptador seguro para a API pública Jettax 360 / Morfeu.

A Jettax é uma fonte de captura *a montante*, não uma variante do protocolo
ADN/SEFAZ. Por isso seus cursores (`lastId`/`ultimoId`), suas execuções e seus
resultados ficam em tabelas próprias. O documento fiscal, por outro lado,
continua único no NotasFlow: se a mesma nota também vier da fonte direta, a
proveniência é adicionada sem substituir o XML já guardado.

Este módulo só usa contratos publicados na coleção Morfeu:
- clientes: POST/PUT ``/api/clients``;
- NFS-e: GET ``/api/nfse/invoices/{cnpj}``;
- NF-e: GET ``/api/nfes/clients/{cnpj}/sales|purchases/``;
A coleção também identifica uma rota CT-e ``sales``, mas não publica uma
estrutura de resposta suficiente para importar com segurança; ela permanece
fora deste adaptador até a documentação estar completa.

Não há endpoint de download de XML de NFS-e documentado. A captura de NFS-e
persiste, portanto, somente o resumo normalizado retornado pela API e marca o
leiaute como ``metadados``. Nunca inventamos uma URL de XML/PDF.
"""

from __future__ import annotations

import base64
import gzip
import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import httpx
from dateutil import parser as date_parser
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.documentos import normalizar_cnpj, normalizar_documento
from app.models import (
    DirecaoDocumento,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    JettaxConfiguracaoEmpresa,
    JettaxExecucao,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
)
from app.services.importadores.base import DocumentoBaixado
from app.services.importadores.nfe_sefaz import ImportadorNFeSEFAZ


ORIGEM_JETTAX = "jettax"

_logger = logging.getLogger("notasflow.jettax")


def normalizar_token(valor: object) -> str:
    """Deixa o token pronto para o header ``Authorization`` da Morfeu.

    A coleção pública usa autenticação por API Key: o valor do header é o
    próprio token, **sem** o prefixo ``Bearer``. Colagens vindas de e-mail,
    PDF ou do próprio Postman costumam trazer ``Bearer `` na frente, aspas
    ou quebras de linha no meio; tudo isso é removido para o header sair
    exatamente como o fornecedor emitiu. Tokens de API não contêm espaço.
    """
    texto = str(valor or "").strip()
    if not texto:
        return ""
    for _ in range(2):  # cobre "Bearer Bearer <token>" de dupla colagem
        minusculo = texto.lower()
        if minusculo.startswith("bearer "):
            texto = texto[7:].strip()
        else:
            break
    texto = texto.strip("\"'").strip()
    return "".join(texto.split())  # remove espaços/tabs/quebras internos


# A coleção Postman da Morfeu descreve "API Key": header ``Authorization`` com
# o token puro. Na prática a API responde ``{"message":"Token inválido."}`` a
# qualquer credencial que o middleware não aceite, sem dizer se o problema é o
# valor ou o *formato* do header. Como existem instalações Morfeu atrás de
# middleware estilo Laravel/Passport (que exige ``Bearer``), o conector tenta o
# formato documentado primeiro e, só diante de 401/403, repete a mesma
# requisição com o prefixo ``Bearer`` no mesmo host HTTPS. Um 401 significa que
# nada foi executado do outro lado, então a repetição é segura inclusive em
# POST/PUT.
ESQUEMA_PURO = "puro"
ESQUEMA_BEARER = "bearer"
ESQUEMAS_AUTENTICACAO = (ESQUEMA_PURO, ESQUEMA_BEARER)

# Hosts oficiais da Morfeu. O token só pode ser enviado para a Jettax: qualquer
# diagnóstico automático fica restrito a este domínio.
_DOMINIO_JETTAX = ".jettax.com.br"
HOSTS_OFICIAIS_JETTAX = (
    "https://morfeu-api.jettax.com.br",
    "https://morfeu.jettax.com.br",
)

_FLUXO_NFSE = "nfse"
_FLUXO_NFE_SAIDA = "sales"
_FLUXO_NFE_ENTRADA = "purchases"
_FLUXOS_DFE = {_FLUXO_NFE_SAIDA, _FLUXO_NFE_ENTRADA}
_MAX_TEXTO_ERRO = 500
# Evita que um clique repetido, um tick do agendador e a retomada pós-656
# criem várias consultas iguais na Jettax antes da primeira terminar/aparecer.
_JANELA_REPETICAO_AUTOMATICA = timedelta(minutes=30)


@dataclass(slots=True)
class TentativaJettax:
    """Resultado de uma sondagem endereço + formato de header."""

    base_url: str
    esquema: str
    status_code: int | None
    ok: bool
    mensagem: str

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc

    @property
    def rotulo_esquema(self) -> str:
        return "Bearer <token>" if self.esquema == ESQUEMA_BEARER else "token puro"


@dataclass(slots=True)
class ResultadoFallbackJettax:
    """Resultado seguro de uma tentativa automática de acionar a Jettax."""

    status: str
    mensagem: str
    execucao_id: int | None = None
    fluxo: str | None = None
    origem: str | None = None

    @property
    def enfileirada(self) -> bool:
        return self.status == "enfileirada"


class JettaxErro(RuntimeError):
    """Erro seguro para a API/UI, sem corpo de resposta ou segredo remoto."""

    def __init__(self, mensagem: str, *, categoria: str = "indisponivel", status_code: int | None = None):
        super().__init__(mensagem)
        self.categoria = categoria
        self.status_code = status_code

    def anexar_contexto(self, *, host: str, status_code: int | None = None) -> None:
        """Acrescenta status HTTP e host tentado à mensagem, uma única vez.

        Sem isso é impossível distinguir, na UI, um 401 de um 403, nem saber
        para qual endereço da Jettax o token foi de fato enviado.
        """
        if getattr(self, "_contexto_anexado", False):
            return
        self._contexto_anexado = True
        if status_code:
            self.status_code = status_code
        mensagem = str(self.args[0]) if self.args else ""
        partes: list[str] = []
        if status_code and f"HTTP {status_code}" not in mensagem:
            partes.append(f"HTTP {status_code}")
        if host and host not in mensagem:
            partes.append(host)
        if partes:
            self.args = (mensagem + " [" + " · ".join(partes) + "]",)


class JettaxNaoConfigurada(JettaxErro):
    def __init__(self) -> None:
        super().__init__(
            "Integração Jettax não configurada. Defina JETTAX_API_TOKEN no ambiente seguro do servidor.",
            categoria="nao_configurada",
        )


def _texto(valor: object, limite: int = 255) -> str:
    return str(valor or "").strip()[:limite]


def _digitos(valor: object) -> str:
    """Usado somente em campos que o contrato define como numéricos (ex. IBGE)."""
    return "".join(caractere for caractere in str(valor or "") if caractere.isdigit())


def _cnpj_jettax(valor: object) -> str:
    """Evita transmitir CNPJ alfa a um contrato Morfeu ainda não verificado."""
    try:
        cnpj = normalizar_cnpj(str(valor or ""))
    except ValueError as exc:
        raise JettaxErro("CNPJ inválido para a integração Jettax.", categoria="cadastro") from exc
    if not cnpj.isdigit():
        raise JettaxErro(
            "O suporte da Jettax a CNPJ alfanumérico ainda não foi confirmado no contrato público; "
            "a empresa foi preservada localmente e não será transmitida até essa validação.",
            categoria="contrato",
        )
    return cnpj


def _documento_preservado(valor: object) -> str:
    try:
        return normalizar_documento(str(valor or ""))
    except ValueError:
        return ""


def _campo(item: dict[str, Any], *nomes: str, padrao: Any = None) -> Any:
    """Lê campos sem confiar em maiúsculas/minúsculas do fornecedor."""
    normalizado = {str(chave).lower(): valor for chave, valor in item.items()}
    for nome in nomes:
        if nome in item:
            return item[nome]
        valor = normalizado.get(nome.lower())
        if valor is not None:
            return valor
    return padrao


def _dicionario(valor: object) -> dict[str, Any]:
    return valor if isinstance(valor, dict) else {}


def _data_hora(valor: object) -> datetime:
    if isinstance(valor, datetime):
        return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)
    texto = _texto(valor)
    if not texto:
        return datetime.now(timezone.utc)
    try:
        resultado = date_parser.isoparse(texto)
    except (ValueError, TypeError, OverflowError):
        try:
            resultado = date_parser.parse(texto)
        except (ValueError, TypeError, OverflowError):
            return datetime.now(timezone.utc)
    return resultado if resultado.tzinfo else resultado.replace(tzinfo=timezone.utc)


def _para_data(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return date_parser.isoparse(texto).date()
    except (ValueError, TypeError, OverflowError):
        return None


def _competencia(valor: object, fallback: datetime) -> date | None:
    texto = _texto(valor)
    if texto:
        try:
            return date_parser.parse(texto, default=datetime(2000, 1, 1)).date().replace(day=1)
        except (ValueError, TypeError, OverflowError):
            pass
    return fallback.date().replace(day=1) if fallback else None


def _decimal(valor: object) -> float:
    original = _texto(valor)
    if "," in original and "." in original:
        # O último separador normalmente é o decimal: aceita tanto
        # 1.234,56 (pt-BR) quanto 1,234.56 (formato internacional).
        if original.rfind(",") > original.rfind("."):
            texto = original.replace(".", "").replace(",", ".")
        else:
            texto = original.replace(",", "")
    elif "," in original:
        texto = original.replace(",", ".")
    else:
        texto = original
    try:
        return float(Decimal(texto or "0"))
    except (InvalidOperation, ValueError):
        return 0.0


def _normalizar_chave(chave: str) -> str:
    return _texto(chave, 60)


def _mensagem_remota(resposta: httpx.Response, limite: int = 160) -> str:
    """Extrai a mensagem curta de erro do fornecedor, sem vazar segredo.

    A Morfeu responde ``{"message": "..."}``. Esse texto é essencial para o
    diagnóstico, mas pode ecoar o próprio token enviado; por isso qualquer
    palavra longa demais para ser linguagem natural é redigida antes de a
    mensagem chegar à UI/auditoria.
    """
    try:
        corpo = resposta.json()
    except ValueError:
        return ""
    if not isinstance(corpo, dict):
        return ""
    bruto = corpo.get("message") or corpo.get("error") or corpo.get("detail") or ""
    if isinstance(bruto, dict):
        bruto = bruto.get("message") or ""
    texto = " ".join(str(bruto or "").split())
    if not texto:
        return ""
    # Redige qualquer sequência longa sem espaço (formato típico de token/JWT).
    seguro = " ".join("[redigido]" if len(palavra.strip(".,;:\"'")) > 24 else palavra for palavra in texto.split())
    return seguro[:limite]


def cliente_jettax_para(db: Session, escritorio_id: int) -> "ClienteJettax":
    """Usa a credencial cifrada do painel; mantém variável de ambiente como fallback."""
    from app.core.vault import decifrar_segredo
    from app.models import JettaxCredencial

    credencial = db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).first()
    if credencial is None:
        return ClienteJettax()
    return ClienteJettax(
        base_url=credencial.base_url,
        token=decifrar_segredo(credencial.token_cifrado),
        esquema_autenticacao=getattr(credencial, "esquema_autenticacao", None) or ESQUEMA_PURO,
    )


def diagnosticar_credencial(token: str, base_url: str) -> tuple[TentativaJettax | None, list[TentativaJettax]]:
    """Descobre qual endereço + formato de header a Jettax aceita para o token.

    A Morfeu publica dois endereços de produção e responde a mesma mensagem
    genérica ("Token inválido.") para credencial errada e para formato de
    header inesperado. Em vez de deixar o operador adivinhando, sondamos as
    combinações plausíveis — sempre com GET de leitura, sempre dentro do
    domínio da Jettax — e devolvemos a que funcionou (ou o mapa das recusas).
    """
    token_limpo = normalizar_token(token)
    if not token_limpo:
        raise JettaxNaoConfigurada()

    candidatos: list[str] = []
    for url in [base_url, *HOSTS_OFICIAIS_JETTAX]:
        normalizada = (url or "").strip().rstrip("/")
        partes = urlparse(normalizada)
        # O token nunca é oferecido a um host fora da Jettax.
        if not normalizada or partes.scheme != "https" or not partes.hostname:
            continue
        if not partes.hostname.endswith(_DOMINIO_JETTAX):
            continue
        if normalizada not in candidatos:
            candidatos.append(normalizada)

    tentativas: list[TentativaJettax] = []
    for url in candidatos:
        for esquema in ESQUEMAS_AUTENTICACAO:
            cliente = ClienteJettax(base_url=url, token=token_limpo, esquema_autenticacao=esquema)
            tentativa = cliente.sondar(esquema)
            tentativas.append(tentativa)
            if tentativa.ok:
                return tentativa, tentativas
    return None, tentativas


def explicar_diagnostico(tentativas: list[TentativaJettax]) -> str:
    """Transforma as sondagens em uma orientação objetiva para o operador."""
    if not tentativas:
        return "Não foi possível testar a credencial Jettax."

    status = {t.status_code for t in tentativas if t.status_code is not None}
    hosts = sorted({t.host for t in tentativas})
    detalhe = next((t.mensagem for t in tentativas if t.mensagem), "")

    if not status:
        return (
            "Nenhum endereço da Jettax respondeu ao servidor. Verifique a saída de internet/DNS do "
            f"servidor (tentado: {', '.join(hosts)}). Detalhe: {detalhe}"
        )

    resumo = "; ".join(
        f"{t.host} com {t.rotulo_esquema} → {('HTTP ' + str(t.status_code)) if t.status_code else 'sem resposta'}"
        + (f' "{t.mensagem}"' if t.mensagem and t.status_code else "")
        for t in tentativas
    )

    if status <= {401, 403}:
        return (
            "A Jettax recusou este token em todos os endereços e formatos testados, ou seja, o problema "
            "está na credencial e não no conector: o token não existe, foi revogado, pertence a outro "
            "ambiente ou a conta não tem a API liberada. Peça à Jettax um token de API ativo para a URL "
            f"em uso e confirme se o acesso à API Morfeu está habilitado. Tentativas: {resumo}."
        )
    return f"A Jettax não concluiu o teste de leitura. Tentativas: {resumo}."


class ClienteJettax:
    """Cliente HTTP síncrono com timeout, paginação limitada e logs redigidos."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float | None = None,
        client: httpx.Client | None = None,
        esquema_autenticacao: str = ESQUEMA_PURO,
    ) -> None:
        self.base_url = (base_url or settings.jettax_api_base_url).strip().rstrip("/")
        self.token = normalizar_token(token if token is not None else settings.jettax_api_token)
        self.timeout = max(1.0, float(timeout if timeout is not None else settings.jettax_timeout_segundos))
        self._client = client
        # Formato do header que será tentado primeiro. Começa no documentado
        # (token puro) e passa a refletir o que a instância de fato aceitou.
        self.esquema_autenticacao = esquema_autenticacao if esquema_autenticacao in ESQUEMAS_AUTENTICACAO else ESQUEMA_PURO
        if not self.token:
            raise JettaxNaoConfigurada()
        partes = urlparse(self.base_url)
        if partes.scheme not in {"http", "https"} or not partes.netloc:
            raise JettaxErro("JETTAX_API_BASE_URL inválida.", categoria="configuracao")

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc

    @property
    def configurado(self) -> bool:
        return bool(self.token)

    def sondar(self, esquema: str) -> "TentativaJettax":
        """Uma única chamada de leitura com exatamente um formato de header.

        Diferente de ``verificar_conexao``, não tenta o formato alternativo:
        é a peça usada pelo diagnóstico para dizer qual combinação de
        endereço + formato a Jettax realmente aceita.
        """
        try:
            resposta = self._enviar("GET", self._url_segura("/api/nfse/cities"), params=None, json=None, esquema=esquema)
        except JettaxErro as exc:
            return TentativaJettax(base_url=self.base_url, esquema=esquema, status_code=None, ok=False, mensagem=str(exc))
        detalhe = _mensagem_remota(resposta)
        if resposta.status_code < 300:
            return TentativaJettax(
                base_url=self.base_url, esquema=esquema, status_code=resposta.status_code, ok=True,
                mensagem="Token aceito.",
            )
        return TentativaJettax(
            base_url=self.base_url, esquema=esquema, status_code=resposta.status_code, ok=False,
            mensagem=detalhe or f"HTTP {resposta.status_code}",
        )

    def _url_segura(self, rota_ou_url: str) -> str:
        url = rota_ou_url if rota_ou_url.startswith(("http://", "https://")) else urljoin(self.base_url + "/", rota_ou_url.lstrip("/"))
        base = urlparse(self.base_url)
        destino = urlparse(url)
        # O link next vem do fornecedor. Nunca seguimos uma URL de outro host,
        # pois isso mandaria o header Authorization para fora da Jettax.
        if (destino.scheme, destino.netloc) != (base.scheme, base.netloc):
            raise JettaxErro("A Jettax retornou uma paginação fora do domínio configurado.", categoria="protocolo")
        return url

    def _valor_authorization(self, esquema: str) -> str:
        return f"Bearer {self.token}" if esquema == ESQUEMA_BEARER else self.token

    def _enviar(self, metodo: str, url: str, *, params: dict[str, Any] | None, json: dict[str, Any] | None, esquema: str) -> httpx.Response:
        cabecalhos = {
            "Authorization": self._valor_authorization(esquema),
            # A coleção Morfeu não publica media type versionado. Pedir um
            # "application/vnd.morfeu.v2+json" inexistente pode render 406.
            "Accept": "application/json",
        }
        if self._client is not None:
            return self._client.request(metodo, url, params=params, json=json, headers=cabecalhos)
        try:
            with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                return client.request(metodo, url, params=params, json=json, headers=cabecalhos)
        except httpx.TimeoutException as exc:
            raise JettaxErro(f"Tempo esgotado ao comunicar com a Jettax ({self.host}).") from exc
        except httpx.TransportError as exc:
            raise JettaxErro(
                f"Não foi possível comunicar com a Jettax ({self.host}); confirme a URL configurada, o DNS e a saída de internet do servidor."
            ) from exc

    def _requisitar(self, metodo: str, rota_ou_url: str, *, params: dict[str, Any] | None = None, json: dict[str, Any] | None = None) -> Any:
        url = self._url_segura(rota_ou_url)
        # Ordem: o formato que já funcionou nesta instância primeiro (evita um
        # 401 extra por chamada), depois o alternativo.
        esquemas = [self.esquema_autenticacao] + [e for e in ESQUEMAS_AUTENTICACAO if e != self.esquema_autenticacao]
        erro_final: JettaxErro | None = None
        for posicao, esquema in enumerate(esquemas):
            resposta = self._enviar(metodo, url, params=params, json=json, esquema=esquema)
            try:
                dados = self._tratar_resposta(resposta)
            except JettaxErro as exc:
                exc.anexar_contexto(host=self.host, status_code=resposta.status_code)
                _logger.warning(
                    "Jettax %s %s [auth=%s] -> HTTP %s (%s) %s",
                    metodo, rota_ou_url, esquema, resposta.status_code, exc.categoria,
                    _mensagem_remota(resposta) or "",
                )
                erro_final = exc
                # Só vale repetir quando o servidor recusou a credencial: um
                # 401/403 garante que a operação não foi aplicada do outro lado.
                if exc.categoria == "autenticacao" and posicao + 1 < len(esquemas):
                    continue
                raise
            if esquema != self.esquema_autenticacao:
                _logger.info(
                    "Jettax aceitou o token no formato '%s' em %s; formato memorizado para as próximas chamadas.",
                    esquema, self.host,
                )
                self.esquema_autenticacao = esquema
            return dados
        raise erro_final or JettaxErro("A Jettax recusou a autenticação do conector.", categoria="autenticacao")

    @staticmethod
    def _tratar_resposta(resposta: httpx.Response) -> Any:
        if resposta.status_code in (401, 403):
            # A mensagem curta do fornecedor é o dado mais valioso do
            # diagnóstico ("Token inválido." x "Token não encontrado") e não
            # contém segredo — o token é redigido por _mensagem_remota().
            detalhe = _mensagem_remota(resposta)
            texto = "A Jettax recusou a autenticação do conector."
            if detalhe:
                texto += f' Resposta da Jettax: "{detalhe}".'
            raise JettaxErro(texto, categoria="autenticacao", status_code=resposta.status_code)
        if resposta.status_code == 429 or resposta.status_code >= 500:
            raise JettaxErro("A Jettax está indisponível ou limitou temporariamente a consulta.", status_code=resposta.status_code)
        if 300 <= resposta.status_code < 400:
            # Redirecionamento não é seguido: o Authorization não pode sair do
            # host configurado, mesmo que o fornecedor responda Location.
            raise JettaxErro("A Jettax respondeu com redirecionamento inesperado.", categoria="protocolo", status_code=resposta.status_code)
        if resposta.status_code >= 400:
            # O corpo remoto continua não sendo propagado (pode conter dado
            # operacional), mas sem o status HTTP é impossível distinguir um
            # 404 de rota/CNPJ de um 422 de payload durante o diagnóstico.
            raise JettaxErro(
                f"A Jettax rejeitou a solicitação do conector (HTTP {resposta.status_code}).",
                categoria="rejeitada",
                status_code=resposta.status_code,
            )
        if not resposta.content:
            return {}
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise JettaxErro("A Jettax respondeu em um formato não reconhecido.", categoria="protocolo") from exc
        if isinstance(dados, dict) and str(dados.get("status", "")).upper() == "ERROR":
            # O corpo pode conter dado operacional/credencial municipal. A
            # semântica chega à execução, mas o texto remoto não é propagado.
            raise JettaxErro("A Jettax reportou erro ao processar a solicitação.", categoria="rejeitada")
        return dados

    def criar_cliente(self, dados: dict[str, Any]) -> Any:
        return self._requisitar("POST", "/api/clients", json=dados)

    def atualizar_cliente(self, cnpj: str, dados: dict[str, Any]) -> Any:
        return self._requisitar("PUT", f"/api/clients/{_cnpj_jettax(cnpj)}", json=dados)

    def verificar_conexao(self, codigo_ibge: str | None = None) -> Any:
        # GET /api/nfse/cities é um endpoint documentado, de leitura e que
        # exige o mesmo Authorization das demais operações.
        params: dict[str, Any] = {"ibgeCode": _digitos(codigo_ibge)} if codigo_ibge else {}
        return self._requisitar("GET", "/api/nfse/cities", params=params)

    def _listar_paginas(self, rota: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        rota_atual: str | None = rota
        parametros_atuais: dict[str, Any] | None = {chave: valor for chave, valor in params.items() if valor not in (None, "")}
        documentos: list[dict[str, Any]] = []
        visitadas: set[str] = set()
        limite = max(1, int(settings.jettax_max_paginas_por_execucao))

        for _ in range(limite):
            if not rota_atual:
                break
            url = self._url_segura(rota_atual)
            if url in visitadas:
                raise JettaxErro("A Jettax retornou paginação cíclica.", categoria="protocolo")
            visitadas.add(url)
            resposta = self._requisitar("GET", rota_atual, params=parametros_atuais)
            parametros_atuais = None  # links next já carregam a query própria
            if isinstance(resposta, list):
                pagina = resposta
                proxima = None
            elif isinstance(resposta, dict):
                pagina = resposta.get("data", [])
                meta = _dicionario(resposta.get("meta"))
                paginacao = _dicionario(meta.get("pagination"))
                links = _dicionario(paginacao.get("links"))
                proxima = links.get("next")
            else:
                raise JettaxErro("A Jettax retornou uma lista em formato não reconhecido.", categoria="protocolo")
            if not isinstance(pagina, list) or any(not isinstance(item, dict) for item in pagina):
                raise JettaxErro("A Jettax retornou documentos em formato não reconhecido.", categoria="protocolo")
            documentos.extend(pagina)
            rota_atual = str(proxima) if proxima else None
        else:
            raise JettaxErro(
                "Limite de páginas da Jettax atingido; reduza o período ou aumente JETTAX_MAX_PAGINAS_POR_EXECUCAO.",
                categoria="limite_local",
            )
        return documentos

    def listar_nfse(self, cnpj: str, *, last_id: str | None = None, numero: str | None = None, nota_situacao: str | None = None, tipo_nota: str | None = None, period: str | None = None) -> list[dict[str, Any]]:
        return self._listar_paginas(
            f"/api/nfse/invoices/{_cnpj_jettax(cnpj)}",
            {"lastId": last_id, "numero": numero, "notaSituacao": nota_situacao, "tipoNota": tipo_nota, "period": period},
        )

    def listar_nfes(self, cnpj: str, fluxo: str, *, ultimo_id: str | None = None, chave: str | None = None, data_inicial: date | None = None, data_final: date | None = None, cnpj_destinatario: str | None = None, cnpj_emitente: str | None = None) -> list[dict[str, Any]]:
        if fluxo not in _FLUXOS_DFE:
            raise JettaxErro("Fluxo NF-e não suportado pela integração.", categoria="configuracao")
        return self._listar_paginas(
            f"/api/nfes/clients/{_cnpj_jettax(cnpj)}/{fluxo}/",
            {
                "ultimoId": ultimo_id,
                "chave": chave,
                "dataInicial": data_inicial.isoformat() if data_inicial else None,
                "dataFinal": data_final.isoformat() if data_final else None,
                # O filtro também chega a uma rota Morfeu documentada somente
                # para CNPJ numérico. Não deixar letras virarem outro CNPJ.
                "cnpjDestinario": _cnpj_jettax(cnpj_destinatario) if cnpj_destinatario else None,
                "cnpjEmitente": _cnpj_jettax(cnpj_emitente) if cnpj_emitente else None,
            },
        )

def carga_cliente(empresa: Empresa, configuracao: JettaxConfiguracaoEmpresa, *, certificado_base64: str | None = None, senha_certificado: str | None = None) -> dict[str, Any]:
    """Monta o corpo publicado para Client sem jamais gravar/retornar segredos."""
    cnpj = _cnpj_jettax(empresa.cnpj_cpf)
    codigo_ibge = _digitos(empresa.codigo_ibge)
    ccm = _texto(empresa.inscricao_municipal, 100)
    faltantes = []
    if len(cnpj) != 14:
        faltantes.append("CNPJ de 14 dígitos")
    if len(codigo_ibge) != 7:
        faltantes.append("código IBGE")
    if not ccm:
        faltantes.append("inscrição municipal (CCM)")
    if not _texto(empresa.razao_social):
        faltantes.append("razão social")
    if faltantes:
        raise JettaxErro("Complete antes do registro Jettax: " + ", ".join(faltantes) + ".", categoria="cadastro")

    resultado: dict[str, Any] = {
        "razao_social": _texto(empresa.razao_social, 255),
        "codigo_ibge": codigo_ibge,
        "cnpj": cnpj,
        "ccm": ccm,
        # A coleção Morfeu documenta estes campos como inteiros 1/0
        # ("mandar 1 pra ativar a captura e 0 pra desativar"), não como
        # booleanos JSON. Enviar true/false faz a API rejeitar o cadastro.
        "baixar_nfes": 1 if configuracao.baixar_nfes else 0,
        "baixar_nfes_enviadas": 1 if configuracao.baixar_nfes_enviadas else 0,
    }
    if certificado_base64 is not None and senha_certificado is not None:
        resultado["digital_certificate"] = certificado_base64
        resultado["digital_certificate_password"] = senha_certificado
    return resultado


def cursor_para(configuracao: JettaxConfiguracaoEmpresa, tipo: TipoDocumentoFiscal, fluxo: str) -> str | None:
    campos = {
        (TipoDocumentoFiscal.NFSE, _FLUXO_NFSE): "ultimo_id_nfse",
        (TipoDocumentoFiscal.NFE, "sales"): "ultimo_id_nfe_saida",
        (TipoDocumentoFiscal.NFE, "purchases"): "ultimo_id_nfe_entrada",
    }
    campo = campos.get((tipo, fluxo))
    if campo is None:
        raise JettaxErro("Cursor Jettax não definido para este tipo/fluxo.", categoria="configuracao")
    return getattr(configuracao, campo)


def atualizar_cursor(configuracao: JettaxConfiguracaoEmpresa, tipo: TipoDocumentoFiscal, fluxo: str, cursor: str) -> None:
    campos = {
        (TipoDocumentoFiscal.NFSE, _FLUXO_NFSE): "ultimo_id_nfse",
        (TipoDocumentoFiscal.NFE, "sales"): "ultimo_id_nfe_saida",
        (TipoDocumentoFiscal.NFE, "purchases"): "ultimo_id_nfe_entrada",
    }
    campo = campos.get((tipo, fluxo))
    if campo is None:
        raise JettaxErro("Cursor Jettax não definido para este tipo/fluxo.", categoria="configuracao")
    setattr(configuracao, campo, _texto(cursor, 100) or None)


def _maior_cursor(itens: Iterable[dict[str, Any]], anterior: str | None) -> str | None:
    candidatos = [_texto(_campo(item, "id", "ultimoId", "lastId"), 100) for item in itens]
    candidatos = [valor for valor in candidatos if valor]
    if not candidatos:
        return anterior
    # IDs da Morfeu são apresentados como números. Se a forma futura não for
    # numérica, manter o último retorno é mais seguro que uma ordenação lexical.
    if all(valor.isdigit() for valor in candidatos):
        return str(max(int(valor) for valor in candidatos))
    return candidatos[-1]


def _insert_sem_duplicar(db: Session, tabela, valores: dict[str, Any], *, constraint: str | None = None, index_elements: tuple[str, ...] = ()) -> bool:
    dialeto = db.get_bind().dialect.name
    if dialeto == "postgresql":
        comando = postgresql_insert(tabela).values(**valores).on_conflict_do_nothing(constraint=constraint)
    elif dialeto == "sqlite":
        comando = sqlite_insert(tabela).values(**valores).on_conflict_do_nothing(index_elements=index_elements)
    else:
        raise RuntimeError(f"Banco não suportado para inserção idempotente: {dialeto}.")
    return db.execute(comando).rowcount == 1


def registrar_proveniencia(db: Session, documento_id: int, origem: str, identificador_externo: str | None) -> None:
    """Guarda uma confirmação de origem sem expor ou alterar o documento base."""
    _insert_sem_duplicar(
        db,
        DocumentoFiscalFonte.__table__,
        {
            "documento_id": documento_id,
            "origem": _texto(origem, 30),
            "identificador_externo": _texto(identificador_externo, 100),
        },
        constraint="uq_documento_fonte_identificador",
        index_elements=("documento_id", "origem", "identificador_externo"),
    )


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def _credencial_disponivel(db: Session, escritorio_id: int) -> bool:
    """Checagem barata: existe algum token sem descriptografá-lo nem chamá-lo."""
    from app.models import JettaxCredencial

    if (settings.jettax_api_token or "").strip():
        return True
    return db.query(JettaxCredencial.id).filter_by(escritorio_id=escritorio_id).first() is not None


def recuperar_trava_expirada(db: Session, configuracao: JettaxConfiguracaoEmpresa) -> bool:
    """Libera uma trava Jettax abandonada por queda do worker.

    A trava é por empresa porque a Morfeu mantém cursores remotos por cliente.
    Se a task morreu, as execuções antigas viram erro auditável e novas
    tentativas voltam a ser possíveis.
    """
    inicio = _aware(configuracao.travado_em)
    if inicio is None:
        return False
    limite = timedelta(seconds=max(60, int(settings.limite_tempo_task_segundos) + 60))
    if inicio > datetime.now(timezone.utc) - limite:
        return False

    agora = datetime.now(timezone.utc)
    pendentes = db.query(JettaxExecucao).filter(
        JettaxExecucao.empresa_id == configuracao.empresa_id,
        JettaxExecucao.status == "em_andamento",
    ).all()
    for pendente in pendentes:
        pendente.status = "erro"
        pendente.mensagem_erro = "Execução Jettax interrompida por timeout do worker; trava liberada."
        pendente.finalizado_em = agora
    configuracao.travado_em = None
    configuracao.ultimo_erro = "Execução Jettax anterior interrompida por timeout; nova tentativa liberada."
    return True


def _fluxo_automatico_para(tipo: TipoDocumentoFiscal, configuracao: JettaxConfiguracaoEmpresa) -> str | None:
    if tipo == TipoDocumentoFiscal.NFSE:
        return _FLUXO_NFSE
    if tipo == TipoDocumentoFiscal.NFE:
        # `baixar_nfes` é a captura de entradas/recebidas; `baixar_nfes_enviadas`
        # é a captura de saídas/emitidas no contrato Morfeu. Quando nenhuma das
        # preferências antigas foi marcada, usar entradas como caminho seguro de
        # fallback, que é o caso mais comum da distribuição DFe por destinatário.
        if configuracao.baixar_nfes:
            return _FLUXO_NFE_ENTRADA
        if configuracao.baixar_nfes_enviadas:
            return _FLUXO_NFE_SAIDA
        return _FLUXO_NFE_ENTRADA
    return None


def _filtros_automaticos(tipo: TipoDocumentoFiscal, data_inicio: date | None, data_fim: date | None) -> dict[str, Any]:
    if tipo == TipoDocumentoFiscal.NFE:
        filtros: dict[str, Any] = {}
        if data_inicio:
            filtros["data_inicial"] = data_inicio.isoformat()
        if data_fim:
            filtros["data_final"] = data_fim.isoformat()
        return filtros

    if tipo == TipoDocumentoFiscal.NFSE and data_inicio and data_fim:
        # A Morfeu documenta apenas filtro mensal `period=m-AAAA` para NFS-e.
        # Usá-lo somente quando a competência pedida é um mês fechado evita
        # inventar um contrato de data livre que o fornecedor não publicou.
        mesmo_mes = data_inicio.year == data_fim.year and data_inicio.month == data_fim.month
        if mesmo_mes and data_inicio.day == 1:
            return {"period": f"{data_inicio.month}-{data_inicio.year}"}
    return {}


def _ja_existe_automatico_recente(
    db: Session,
    *,
    empresa_id: int,
    tipo: TipoDocumentoFiscal,
    fluxo: str,
    origem: str,
    agora: datetime,
    janela: timedelta,
) -> JettaxExecucao | None:
    limite = agora - janela
    return (
        db.query(JettaxExecucao)
        .filter(
            JettaxExecucao.empresa_id == empresa_id,
            JettaxExecucao.tipo == tipo,
            JettaxExecucao.fluxo == fluxo,
            JettaxExecucao.origem == _texto(origem, 20),
            JettaxExecucao.status != "erro",
            JettaxExecucao.iniciado_em >= limite,
        )
        .order_by(JettaxExecucao.id.desc())
        .first()
    )


def acionar_fallback_automatico(
    db: Session,
    empresa: Empresa,
    tipo: TipoDocumentoFiscal | str,
    *,
    motivo: str,
    origem: str,
    data_inicio: date | None = None,
    data_fim: date | None = None,
    janela_repeticao: timedelta | None = _JANELA_REPETICAO_AUTOMATICA,
) -> ResultadoFallbackJettax:
    """Enfileira Jettax como conferência/fallback sem quebrar o fluxo oficial.

    A função é deliberadamente *best effort*: se a Jettax não estiver pronta,
    retornamos o motivo para eventual log/aviso, mas nunca levantamos erro para
    uma importação SEFAZ/ADN. O uso automático só acontece para empresas já
    ativadas e registradas na Jettax; cadastrar cliente remoto continua sendo
    uma decisão explícita do administrador.
    """
    tipo_doc = tipo if isinstance(tipo, TipoDocumentoFiscal) else TipoDocumentoFiscal(tipo)
    origem_segura = _texto(origem, 20) or "fallback"
    motivo_seguro = _texto(motivo, 350) or "verificação automática"

    if tipo_doc == TipoDocumentoFiscal.CTE:
        return ResultadoFallbackJettax(
            status="nao_suportado",
            mensagem="Jettax automática ignorada: CT-e ainda não tem contrato público seguro no conector.",
            origem=origem_segura,
        )
    if not _credencial_disponivel(db, empresa.escritorio_id):
        return ResultadoFallbackJettax(
            status="nao_configurada",
            mensagem="Jettax não configurada para este escritório.",
            origem=origem_segura,
        )

    configuracao = (
        db.query(JettaxConfiguracaoEmpresa)
        .filter(JettaxConfiguracaoEmpresa.empresa_id == empresa.id)
        .with_for_update()
        .first()
    )
    if configuracao is None:
        return ResultadoFallbackJettax(
            status="nao_configurada",
            mensagem="Empresa ainda não tem configuração Jettax.",
            origem=origem_segura,
        )
    if configuracao.status not in {"registrada", "atualizada"}:
        return ResultadoFallbackJettax(
            status="desativada",
            mensagem="Empresa ainda não foi registrada/atualizada na Jettax.",
            origem=origem_segura,
        )
    if not configuracao.ativa:
        return ResultadoFallbackJettax(
            status="desativada",
            mensagem="Integração Jettax desta empresa está desativada.",
            origem=origem_segura,
        )

    if recuperar_trava_expirada(db, configuracao):
        db.commit()

    andamento = (
        db.query(JettaxExecucao)
        .filter(
            JettaxExecucao.empresa_id == empresa.id,
            JettaxExecucao.status == "em_andamento",
        )
        .order_by(JettaxExecucao.id.desc())
        .first()
    )
    if andamento is not None or configuracao.travado_em is not None:
        return ResultadoFallbackJettax(
            status="ja_em_andamento",
            mensagem="Jettax já está verificando esta empresa; não foi criada uma segunda execução.",
            execucao_id=andamento.id if andamento else None,
            fluxo=andamento.fluxo if andamento else None,
            origem=origem_segura,
        )

    fluxo = _fluxo_automatico_para(tipo_doc, configuracao)
    if fluxo is None:
        return ResultadoFallbackJettax(
            status="nao_suportado",
            mensagem="Tipo fiscal sem fluxo Jettax automático.",
            origem=origem_segura,
        )

    agora = datetime.now(timezone.utc)
    if janela_repeticao:
        recente = _ja_existe_automatico_recente(
            db,
            empresa_id=empresa.id,
            tipo=tipo_doc,
            fluxo=fluxo,
            origem=origem_segura,
            agora=agora,
            janela=janela_repeticao,
        )
        if recente is not None:
            return ResultadoFallbackJettax(
                status="recente",
                mensagem="Jettax automática já foi acionada recentemente para este mesmo motivo.",
                execucao_id=recente.id,
                fluxo=fluxo,
                origem=origem_segura,
            )

    filtros = _filtros_automaticos(tipo_doc, data_inicio, data_fim)
    avancar_cursor = not bool(filtros)
    cursor = cursor_para(configuracao, tipo_doc, fluxo)
    execucao = JettaxExecucao(
        empresa_id=empresa.id,
        tipo=tipo_doc,
        fluxo=fluxo,
        status="em_andamento",
        avancar_cursor=avancar_cursor,
        cursor_antes=cursor,
        aviso=f"Acionada automaticamente: {motivo_seguro}",
        origem=origem_segura,
        iniciado_em=agora,
    )
    db.add(execucao)
    configuracao.travado_em = agora
    configuracao.ultimo_erro = None
    from app.services import auditoria

    auditoria.registrar(
        db,
        None,
        "jettax_fallback_automatico",
        entidade="empresa",
        entidade_id=empresa.id,
        escritorio_id=empresa.escritorio_id,
        email="sistema",
        detalhe=f"{tipo_doc.value}/{fluxo}; {motivo_seguro}; origem={origem_segura}",
    )
    db.commit()
    db.refresh(execucao)

    try:
        from app.worker.tasks import importar_documentos_jettax

        importar_documentos_jettax.delay(execucao_id=execucao.id, filtros=filtros)
    except Exception:  # noqa: BLE001 -- broker fora do ar não pode deixar trava zumbi
        execucao.status = "erro"
        execucao.mensagem_erro = "Não foi possível enfileirar a verificação automática Jettax."
        execucao.finalizado_em = datetime.now(timezone.utc)
        configuracao.travado_em = None
        configuracao.ultimo_erro = execucao.mensagem_erro
        db.commit()
        return ResultadoFallbackJettax(
            status="fila_indisponivel",
            mensagem=execucao.mensagem_erro,
            execucao_id=execucao.id,
            fluxo=fluxo,
            origem=origem_segura,
        )

    return ResultadoFallbackJettax(
        status="enfileirada",
        mensagem=f"Jettax acionada automaticamente ({tipo_doc.value}/{fluxo}) para conferir: {motivo_seguro}.",
        execucao_id=execucao.id,
        fluxo=fluxo,
        origem=origem_segura,
    )


def _texto_documento(doc: DocumentoBaixado, campo: str, limite: int) -> str | None:
    return _texto(getattr(doc, campo, ""), limite) or None


def _persistir_xml(db: Session, empresa_id: int, tipo: TipoDocumentoFiscal, doc: DocumentoBaixado, *, identificador_externo: str) -> bool:
    chave = _normalizar_chave(doc.chave_acesso)
    if not chave or not doc.xml:
        raise ValueError("Documento Jettax sem chave fiscal ou XML.")
    pasta = os.path.join(settings.dados_dir, "xml", str(empresa_id), tipo.value)
    nome = "".join(caractere for caractere in chave if caractere.isalnum() or caractere in "-_") or f"jettax_{identificador_externo}"
    caminho = os.path.join(pasta, f"{nome}.xml")
    direcao = doc.direcao if doc.direcao in {"tomada", "prestada"} else "tomada"
    criado = _insert_sem_duplicar(
        db,
        DocumentoFiscal.__table__,
        {
            "empresa_id": empresa_id,
            "tipo": tipo,
            "direcao": DirecaoDocumento(direcao),
            "chave_acesso": chave,
            "nsu": _texto(doc.nsu, 20) or "0",
            "data_emissao": _data_hora(doc.data_emissao),
            "competencia": _competencia(doc.competencia, _data_hora(doc.data_emissao)),
            "valor_total": float(doc.valor_total or 0),
            "xml_path": caminho,
            "status": StatusDocumentoFiscal.NORMAL,
            "leiaute": _texto(doc.leiaute, 12) or "completo",
            "numero": _texto_documento(doc, "numero", 20),
            "serie": _texto_documento(doc, "serie", 10),
            "emitente_documento": _texto_documento(doc, "emitente_documento", 18),
            "emitente_nome": _texto_documento(doc, "emitente_nome", 255),
            "destinatario_documento": _texto_documento(doc, "destinatario_documento", 18),
            "destinatario_nome": _texto_documento(doc, "destinatario_nome", 255),
            "situacao": _texto_documento(doc, "status_autorizacao", 255),
            "origem": ORIGEM_JETTAX,
        },
        constraint="uq_documento_por_empresa",
        index_elements=("empresa_id", "chave_acesso"),
    )
    documento = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa_id, DocumentoFiscal.chave_acesso == chave
    ).first()
    if documento is None:
        raise RuntimeError("Não foi possível localizar o documento Jettax recém-gravado.")
    registrar_proveniencia(db, documento.id, ORIGEM_JETTAX, identificador_externo)
    if criado:
        os.makedirs(pasta, exist_ok=True)
        with open(caminho, "wb") as arquivo:
            arquivo.write(doc.xml)
    return criado


def _direcao_nfse(item: dict[str, Any], empresa: Empresa) -> str:
    tipo = _texto(_campo(item, "tipoNota")).lower()
    if tipo in {"emitida", "enviada", "prestada", "saida", "saída"}:
        return "prestada"
    if tipo in {"recebida", "tomada", "nfts"}:
        return "tomada"
    prestador = _dicionario(_campo(item, "prestadorServico", "prestador_servico"))
    identificacao = _dicionario(_campo(prestador, "identificacaoPrestador", "identificacao_prestador"))
    if _documento_preservado(_campo(identificacao, "cnpj", "cpfCnpj")) == _documento_preservado(empresa.cnpj_cpf):
        return "prestada"
    return "tomada"


def _persistir_nfse_metadados(db: Session, empresa: Empresa, item: dict[str, Any]) -> bool:
    identificador = _texto(_campo(item, "id"), 100)
    if not identificador:
        raise ValueError("NFS-e Jettax sem id do fornecedor.")
    chave = _normalizar_chave(f"jettax-nfse-{identificador}")
    servico = _dicionario(_campo(item, "servico"))
    valores_servico = _dicionario(_campo(servico, "valores"))
    prestador = _dicionario(_campo(item, "prestadorServico", "prestador_servico"))
    prestador_id = _dicionario(_campo(prestador, "identificacaoPrestador", "identificacao_prestador"))
    tomador = _dicionario(_campo(item, "tomadorServico", "tomador_servico"))
    tomador_id = _dicionario(_campo(tomador, "identificacaoTomador", "identificacao_tomador"))
    emissao = _data_hora(_campo(item, "dataEmissao", "data_emissao"))
    situacao = _texto(_campo(item, "notaSituacao", "situacao"), 255)
    criado = _insert_sem_duplicar(
        db,
        DocumentoFiscal.__table__,
        {
            "empresa_id": empresa.id,
            "tipo": TipoDocumentoFiscal.NFSE,
            "direcao": DirecaoDocumento(_direcao_nfse(item, empresa)),
            "chave_acesso": chave,
            "nsu": _texto(identificador, 20),
            "data_emissao": emissao,
            "competencia": _competencia(_campo(item, "dataCompetencia", "competencia"), emissao),
            "valor_total": _decimal(_campo(valores_servico, "valorLiquidoNfse", "valorServicos", "valorBase", "baseCalculo")),
            # A API documenta metadados e uma URL opcional, mas não documenta
            # contrato de download. Não gravar conteúdo não confirmado como XML.
            "xml_path": "",
            "status": StatusDocumentoFiscal.CANCELADA if situacao.lower() == "cancelada" else StatusDocumentoFiscal.NORMAL,
            "leiaute": "metadados",
            "numero": _texto(_campo(item, "numero"), 20) or None,
            "serie": _texto(_campo(item, "notaSerie", "serie"), 10) or None,
            "emitente_documento": _documento_preservado(_campo(prestador_id, "cnpj", "cpfCnpj"))[:18] or None,
            "emitente_nome": _texto(_campo(prestador, "razaoSocial", "razao_social"), 255) or None,
            "destinatario_documento": _documento_preservado(_campo(tomador_id, "cpfCnpj", "cnpj", "cpf"))[:18] or None,
            "destinatario_nome": _texto(_campo(tomador, "razaoSocial", "razao_social"), 255) or None,
            "situacao": situacao or None,
            "origem": ORIGEM_JETTAX,
        },
        constraint="uq_documento_por_empresa",
        index_elements=("empresa_id", "chave_acesso"),
    )
    documento = db.query(DocumentoFiscal).filter(
        DocumentoFiscal.empresa_id == empresa.id, DocumentoFiscal.chave_acesso == chave
    ).first()
    if documento is None:
        raise RuntimeError("Não foi possível localizar a NFS-e Jettax recém-gravada.")
    registrar_proveniencia(db, documento.id, ORIGEM_JETTAX, identificador)
    # O cancelamento pode chegar de uma fonte após a outra. Sempre preserva a
    # informação mais conservadora; não reativa documento por uma listagem velha.
    if situacao.lower() == "cancelada" and documento.status != StatusDocumentoFiscal.CANCELADA:
        documento.status = StatusDocumentoFiscal.CANCELADA
        documento.motivo_cancelamento = "Situação cancelada informada pela Jettax"
        documento.cancelado_em = emissao
    return criado


def _xml_gzip_base64(item: dict[str, Any]) -> bytes:
    conteudo = _campo(item, "xml", "XML")
    if not isinstance(conteudo, str) or not conteudo.strip():
        raise ValueError("Documento Jettax sem XML compactado.")
    try:
        return gzip.decompress(base64.b64decode(conteudo.strip(), validate=True))
    except (ValueError, OSError, EOFError) as exc:
        raise ValueError("XML compactado da Jettax é inválido.") from exc


def _converter_xml(tipo: TipoDocumentoFiscal, xml: bytes, identificador: str, cnpj: str) -> DocumentoBaixado:
    # Os conversores já consolidados do NotasFlow são namespace-agnósticos e
    # extraem chave, valor, emitente, destinatário e competência do XML. A
    # Jettax devolve o mesmo XML fiscal, apenas gzip+base64.
    if tipo == TipoDocumentoFiscal.NFE:
        resultado = ImportadorNFeSEFAZ()._converter(identificador, "procNFe", xml, cnpj)
    else:
        raise ValueError("Conversão XML Jettax indisponível para este tipo.")
    if resultado is None:
        raise ValueError("Não foi possível extrair a chave fiscal do XML Jettax.")
    return resultado


def _itens_para_execucao(cliente: ClienteJettax, empresa: Empresa, execucao: JettaxExecucao, filtros: dict[str, Any], cursor: str | None) -> list[dict[str, Any]]:
    if execucao.tipo == TipoDocumentoFiscal.NFSE:
        return cliente.listar_nfse(
            empresa.cnpj_cpf,
            last_id=cursor if execucao.avancar_cursor else None,
            numero=filtros.get("numero"),
            nota_situacao=filtros.get("nota_situacao"),
            tipo_nota=filtros.get("tipo_nota"),
            period=filtros.get("period"),
        )
    if execucao.tipo == TipoDocumentoFiscal.NFE:
        return cliente.listar_nfes(
            empresa.cnpj_cpf,
            execucao.fluxo,
            ultimo_id=cursor if execucao.avancar_cursor else None,
            chave=filtros.get("chave"),
            data_inicial=_para_data(filtros.get("data_inicial")),
            data_final=_para_data(filtros.get("data_final")),
            cnpj_destinatario=filtros.get("cnpj_destinatario"),
            cnpj_emitente=filtros.get("cnpj_emitente"),
        )
    raise JettaxErro("Tipo Jettax não suportado.", categoria="configuracao")


def executar_importacao(db: Session, execucao_id: int, filtros: dict[str, Any] | None = None) -> None:
    """Executa uma importação já enfileirada e atualiza o cursor só no commit."""
    execucao = db.get(JettaxExecucao, execucao_id)
    if execucao is None or execucao.status in {"concluida", "concluida_com_avisos"}:
        return
    empresa = db.get(Empresa, execucao.empresa_id)
    configuracao = db.query(JettaxConfiguracaoEmpresa).filter_by(empresa_id=execucao.empresa_id).first()
    agora = datetime.now(timezone.utc)
    if empresa is None or configuracao is None:
        if execucao is not None:
            execucao.status = "erro"
            execucao.mensagem_erro = "Empresa ou configuração Jettax não encontrada."
            execucao.finalizado_em = agora
            db.commit()
        return

    try:
        cursor = cursor_para(configuracao, execucao.tipo, execucao.fluxo)
        execucao.cursor_antes = cursor
        itens = _itens_para_execucao(cliente_jettax_para(db, empresa.escritorio_id), empresa, execucao, filtros or {}, cursor)
        proximo_cursor = _maior_cursor(itens, cursor)
        erros: list[str] = []
        criados = duplicados = ignorados = 0
        for item in itens:
            try:
                identificador = _texto(_campo(item, "id", "ultimoId", "lastId"), 100)
                if not identificador:
                    raise ValueError("Documento Jettax sem identificador do fornecedor.")
                if execucao.tipo == TipoDocumentoFiscal.NFSE:
                    criou = _persistir_nfse_metadados(db, empresa, item)
                else:
                    xml = _xml_gzip_base64(item)
                    documento = _converter_xml(execucao.tipo, xml, identificador, empresa.cnpj_cpf)
                    criou = _persistir_xml(
                        db, empresa.id, execucao.tipo, documento, identificador_externo=identificador
                    )
                if criou:
                    criados += 1
                else:
                    duplicados += 1
            except (ValueError, RuntimeError) as exc:
                ignorados += 1
                erros.append(_texto(str(exc), 180))

        execucao.documentos_importados = criados
        execucao.documentos_duplicados = duplicados
        execucao.documentos_ignorados = ignorados
        execucao.cursor_depois = proximo_cursor if not erros else cursor
        execucao.aviso = "\n".join(erros[:20]) or None
        # Cursor nunca avança diante de item não persistido: repetir duplicados
        # é seguro; perder uma nota por avançar um cursor quebrado não é.
        if execucao.avancar_cursor and not erros and proximo_cursor and proximo_cursor != cursor:
            atualizar_cursor(configuracao, execucao.tipo, execucao.fluxo, proximo_cursor)
        configuracao.ultima_sincronizacao_em = agora
        configuracao.ultimo_erro = None if not erros else f"{ignorados} item(ns) ignorado(s) nesta consulta."
        configuracao.falhas_seguidas = 0 if not erros else (configuracao.falhas_seguidas or 0) + 1
        configuracao.travado_em = None
        execucao.status = "concluida_com_avisos" if erros else "concluida"
        execucao.finalizado_em = agora
        db.commit()
    except JettaxErro as exc:
        execucao.status = "erro"
        execucao.mensagem_erro = _texto(str(exc), _MAX_TEXTO_ERRO)
        execucao.finalizado_em = agora
        configuracao.ultimo_erro = execucao.mensagem_erro
        configuracao.falhas_seguidas = (configuracao.falhas_seguidas or 0) + 1
        configuracao.travado_em = None
        db.commit()
    except Exception:  # noqa: BLE001 - nunca deixar uma execução/trava zumbi
        db.rollback()
        execucao = db.get(JettaxExecucao, execucao_id)
        configuracao = db.query(JettaxConfiguracaoEmpresa).filter_by(empresa_id=empresa.id).first()
        if execucao is not None:
            execucao.status = "erro"
            execucao.mensagem_erro = "Falha interna ao processar a resposta da Jettax."
            execucao.finalizado_em = datetime.now(timezone.utc)
        if configuracao is not None:
            configuracao.ultimo_erro = "Falha interna ao processar a resposta da Jettax."
            configuracao.falhas_seguidas = (configuracao.falhas_seguidas or 0) + 1
            configuracao.travado_em = None
        db.commit()
