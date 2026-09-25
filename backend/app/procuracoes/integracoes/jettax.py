"""
Adaptador Jettax360 — HTTP dirigido por contrato configurável.

**Situação real da integração (auditada em setembro de 2026).** A Jettax
divulga publicamente que a plataforma tem API e que o Jettax 360 monitora
pendências do e-CAC, mas **não publica** a especificação dos endpoints de
procuração/autorização: a documentação de integração é entregue ao cliente
junto com as credenciais. Inventar rota, nome de campo ou formato de resposta
aqui produziria um adaptador que compila, passa em teste de mentira e falha
no primeiro contato com o ambiente real.

A saída correta é esta: um adaptador **real e completo**, cujo contrato é
dado em configuração. O que falta é dado, não código:

===========================  ==================================================
Campo de configuração        O que preencher com a documentação da Jettax
===========================  ==================================================
``base_url``                 Host HTTPS do ambiente do escritório.
``rota_listagem``            Caminho da listagem de clientes/procurações.
``cabecalho_autenticacao``   Nome do header (ex.: ``Authorization``).
``prefixo_token``            Prefixo do valor (ex.: ``Bearer``) ou vazio.
``parametro_pagina``         Nome do parâmetro de paginação.
``caminho_itens``            Caminho do array dentro do JSON (ex.: ``data.items``).
``mapa_campos``              De → para dos campos (documento, razão, datas…).
``mapa_situacoes``           Valor remoto → situação do domínio.
===========================  ==================================================

Com isso preenchido, a sincronização funciona sem alterar uma linha de código.
Sem isso, o adaptador recusa-se a rodar — nunca devolve dado inventado.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from datetime import date, datetime
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

from app.procuracoes.estados import StatusAutorizacao
from app.procuracoes.integracoes.base import (
    FonteError,
    FonteNaoConfiguradaError,
    RegistroProcuracao,
    ServicoAutorizado,
    situacao_por_validade,
)

log = logging.getLogger("cajuru.procuracoes.jettax")

#: Mapeamento mínimo esperado. Chaves internas → nome do campo na resposta.
CAMPOS_OBRIGATORIOS = ("documento",)

MAPA_CAMPOS_SUGERIDO: dict[str, str] = {
    "documento": "cnpj",
    "razao_social": "razaoSocial",
    "situacao": "situacaoProcuracao",
    "data_inicio": "dataInicio",
    "data_validade": "dataValidade",
    "protocolo": "protocolo",
    "servicos": "servicos",
}

MAPA_SITUACOES_SUGERIDO: dict[str, str] = {
    "ativa": StatusAutorizacao.ATIVA.value,
    "vigente": StatusAutorizacao.ATIVA.value,
    "em analise": StatusAutorizacao.EM_ANALISE.value,
    "em análise": StatusAutorizacao.EM_ANALISE.value,
    "aguardando aceite": StatusAutorizacao.AGUARDANDO_ACEITE.value,
    "expirada": StatusAutorizacao.EXPIRADA.value,
    "vencida": StatusAutorizacao.EXPIRADA.value,
    "cancelada": StatusAutorizacao.CANCELADA.value,
    "sem procuracao": StatusAutorizacao.SEM_AUTORIZACAO.value,
    "sem procuração": StatusAutorizacao.SEM_AUTORIZACAO.value,
}


def validar_base_url(valor: str) -> str:
    """HTTPS, host público, sem credencial embutida. Barreira anti-SSRF."""
    texto = (valor or "").strip().rstrip("/")
    if not texto:
        raise FonteNaoConfiguradaError("Informe a URL base da API Jettax360.")
    partes = urlparse(texto)
    if partes.scheme != "https":
        raise FonteError("A URL da Jettax360 deve usar HTTPS.", status_code=422)
    if partes.username or partes.password:
        raise FonteError("Não coloque credenciais na URL.", status_code=422)
    if not partes.hostname:
        raise FonteError("URL da Jettax360 inválida.", status_code=422)
    _recusar_endereco_interno(partes.hostname)
    return texto


def _recusar_endereco_interno(hostname: str) -> None:
    """Impede que a configuração vire um canal para a rede interna."""
    try:
        infos = socket.getaddrinfo(hostname, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        # DNS indisponível no momento da validação não é motivo para recusar
        # a configuração; a chamada real falhará com erro de rede claro.
        return
    for info in infos:
        endereco = info[4][0]
        try:
            ip = ipaddress.ip_address(endereco)
        except ValueError:
            continue
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise FonteError(
                "A URL da Jettax360 aponta para um endereço de rede interna.",
                status_code=422,
            )


def _extrair(dados: Any, caminho: str) -> Any:
    """Navega `a.b.c` num dicionário aninhado sem estourar exceção."""
    atual = dados
    for parte in (caminho or "").split("."):
        if not parte:
            continue
        if isinstance(atual, dict):
            atual = atual.get(parte)
        else:
            return None
    return atual


class ClienteJettax:
    """Cliente HTTP genérico guiado pelo contrato configurado."""

    nome = "jettax360"

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        opcoes: dict[str, Any] | None = None,
        timeout: float = 45.0,
        client: httpx.Client | None = None,
    ):
        self.base_url = validar_base_url(base_url)
        self.token = (token or "").strip()
        if not self.token:
            raise FonteNaoConfiguradaError("Informe o token da API Jettax360.")

        opcoes = dict(opcoes or {})
        self.rota_listagem = str(opcoes.get("rota_listagem") or "").strip()
        if not self.rota_listagem.startswith("/"):
            raise FonteNaoConfiguradaError(
                "Informe a rota de listagem da Jettax360 (ex.: /api/v1/clientes). "
                "Ela consta na documentação entregue com as credenciais."
            )
        self.cabecalho_autenticacao = str(
            opcoes.get("cabecalho_autenticacao") or "Authorization"
        )[:60]
        self.prefixo_token = str(opcoes.get("prefixo_token") or "Bearer").strip()
        self.parametro_pagina = str(opcoes.get("parametro_pagina") or "page")[:40]
        self.parametro_tamanho = str(opcoes.get("parametro_tamanho") or "")[:40]
        self.tamanho_pagina = int(opcoes.get("tamanho_pagina") or 100)
        self.max_paginas = max(1, min(int(opcoes.get("max_paginas") or 200), 2000))
        self.caminho_itens = str(opcoes.get("caminho_itens") or "")
        self.mapa_campos = {
            **MAPA_CAMPOS_SUGERIDO,
            **dict(opcoes.get("mapa_campos") or {}),
        }
        self.mapa_situacoes = {
            **MAPA_SITUACOES_SUGERIDO,
            **{
                str(k).strip().lower(): str(v)
                for k, v in dict(opcoes.get("mapa_situacoes") or {}).items()
            },
        }
        self.parametros_fixos = dict(opcoes.get("parametros_fixos") or {})
        self.timeout = timeout
        self._client = client

        faltando = [c for c in CAMPOS_OBRIGATORIOS if not self.mapa_campos.get(c)]
        if faltando:
            raise FonteNaoConfiguradaError(
                f"Mapeamento incompleto da Jettax360: falta {', '.join(faltando)}."
            )

    # -- transporte ---------------------------------------------------------

    def _cabecalhos(self) -> dict[str, str]:
        valor = f"{self.prefixo_token} {self.token}".strip() if self.prefixo_token else self.token
        return {self.cabecalho_autenticacao: valor, "Accept": "application/json"}

    def _get(self, rota: str, params: dict[str, Any]) -> Any:
        url = f"{self.base_url}{rota}"
        try:
            if self._client is not None:
                resposta = self._client.get(url, params=params, headers=self._cabecalhos())
            else:
                with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                    resposta = client.get(url, params=params, headers=self._cabecalhos())
        except httpx.TimeoutException as exc:
            raise FonteError(
                "Tempo esgotado ao consultar a Jettax360.",
                codigo="TEMPO_ESGOTADO",
                status_code=504,
            ) from exc
        except httpx.TransportError as exc:
            raise FonteError(
                "Não foi possível comunicar com a Jettax360.",
                codigo="FALHA_DE_REDE",
            ) from exc

        if resposta.status_code in (401, 403):
            raise FonteError(
                "A Jettax360 recusou o token informado.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=401,
            )
        if resposta.status_code == 404:
            raise FonteError(
                f"A rota '{rota}' não existe na API Jettax360. Confira a documentação "
                "entregue com as credenciais e ajuste a configuração.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=422,
            )
        if resposta.status_code == 429:
            raise FonteError(
                "Limite de requisições da Jettax360 atingido.",
                codigo="INTEGRACAO_RECUSOU",
                status_code=429,
            )
        if resposta.status_code >= 400:
            raise FonteError(f"A Jettax360 respondeu {resposta.status_code}.")
        try:
            return resposta.json()
        except ValueError as exc:
            raise FonteError("A Jettax360 respondeu em formato inválido.") from exc

    # -- porta --------------------------------------------------------------

    def testar(self) -> str:
        params = dict(self.parametros_fixos)
        params[self.parametro_pagina] = 1
        if self.parametro_tamanho:
            params[self.parametro_tamanho] = 1
        bruto = self._get(self.rota_listagem, params)
        itens = self._itens(bruto)
        return (
            f"Conexão autenticada com a Jettax360 confirmada "
            f"({len(itens)} registro(s) na amostra)."
        )

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        filtro = {d for d in (documentos or []) if d}
        registros: list[RegistroProcuracao] = []
        vistos: set[str] = set()

        for pagina in range(1, self.max_paginas + 1):
            params = dict(self.parametros_fixos)
            params[self.parametro_pagina] = pagina
            if self.parametro_tamanho:
                params[self.parametro_tamanho] = self.tamanho_pagina
            bruto = self._get(self.rota_listagem, params)
            itens = self._itens(bruto)
            if not itens:
                break
            for item in itens:
                registro = self._traduzir(item)
                if registro is None:
                    continue
                if filtro and registro.documento not in filtro:
                    continue
                if registro.documento in vistos:
                    continue
                vistos.add(registro.documento)
                registros.append(registro)
            if len(itens) < max(1, self.tamanho_pagina):
                break
        else:
            raise FonteError(
                f"A sincronização atingiu o teto de {self.max_paginas} páginas. "
                "Aumente 'max_paginas' se a carteira for maior.",
                status_code=409,
            )
        return registros

    def _itens(self, bruto: Any) -> list[dict[str, Any]]:
        conteudo = _extrair(bruto, self.caminho_itens) if self.caminho_itens else bruto
        if conteudo is None and isinstance(bruto, dict):
            # Heurística explícita e limitada: o array mais longo do primeiro nível.
            candidatos = [v for v in bruto.values() if isinstance(v, list)]
            conteudo = max(candidatos, key=len) if candidatos else None
        if isinstance(conteudo, dict):
            conteudo = [conteudo]
        if not isinstance(conteudo, list):
            raise FonteError(
                "Não foi possível localizar a lista de registros na resposta da "
                "Jettax360. Configure 'caminho_itens'.",
                status_code=422,
            )
        return [item for item in conteudo if isinstance(item, dict)]

    def _traduzir(self, item: dict[str, Any]) -> RegistroProcuracao | None:
        documento = str(_extrair(item, self.mapa_campos["documento"]) or "").strip()
        if not documento:
            return None

        bruta = str(_extrair(item, self.mapa_campos.get("situacao", "")) or "").strip()
        validade = _data(_extrair(item, self.mapa_campos.get("data_validade", "")))
        inicio = _data(_extrair(item, self.mapa_campos.get("data_inicio", "")))

        situacao = self._situacao(bruta, validade)
        servicos = self._servicos(item)

        try:
            return RegistroProcuracao(
                documento=documento,
                razao_social=str(_extrair(item, self.mapa_campos.get("razao_social", "")) or ""),
                situacao=situacao,
                data_inicio=inicio,
                data_validade=validade,
                protocolo=str(_extrair(item, self.mapa_campos.get("protocolo", "")) or ""),
                servicos=servicos,
                observacao=bruta,
            ).normalizado()
        except ValueError:
            log.info("jettax_documento_invalido", extra={"documento": documento[:20]})
            return None

    def _situacao(self, bruta: str, validade: date | None) -> StatusAutorizacao:
        chave = bruta.strip().lower()
        alvo = self.mapa_situacoes.get(chave)
        if alvo:
            try:
                situacao = StatusAutorizacao(alvo)
            except ValueError:
                situacao = StatusAutorizacao.SEM_AUTORIZACAO
            # Validade vencida ganha de qualquer rótulo otimista da origem.
            if situacao is StatusAutorizacao.ATIVA and validade and validade < date.today():
                return StatusAutorizacao.EXPIRADA
            return situacao
        return situacao_por_validade(validade, ativa=bool(validade))

    def _servicos(self, item: dict[str, Any]) -> tuple[ServicoAutorizado, ...]:
        bruto = _extrair(item, self.mapa_campos.get("servicos", ""))
        if not isinstance(bruto, list):
            return ()
        saida: list[ServicoAutorizado] = []
        for elemento in bruto[:200]:
            if isinstance(elemento, str) and elemento.strip():
                saida.append(
                    ServicoAutorizado(codigo=elemento.strip()[:120], rotulo=elemento.strip()[:255])
                )
            elif isinstance(elemento, dict):
                codigo = str(
                    elemento.get("codigo") or elemento.get("nome") or elemento.get("sistema") or ""
                ).strip()
                if codigo:
                    saida.append(
                        ServicoAutorizado(
                            codigo=codigo[:120],
                            rotulo=str(elemento.get("rotulo") or codigo)[:255],
                            expira_em=_data(elemento.get("dataValidade") or elemento.get("expiracao")),
                        )
                    )
        return tuple(saida)


def _data(valor: Any) -> date | None:
    if valor in (None, ""):
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y", "%Y%m%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(texto.replace("Z", "+00:00")).date()
    except ValueError:
        return None
