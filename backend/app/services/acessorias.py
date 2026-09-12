"""Cliente mínimo e defensivo da API oficial do Sistema Acessórias."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx


class AcessoriasErro(RuntimeError):
    def __init__(self, mensagem: str, status_code: int = 502):
        super().__init__(mensagem)
        self.status_code = status_code


class ClienteAcessorias:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30, client: httpx.Client | None = None):
        self.base_url = base_url.strip().rstrip("/")
        self.token = token.strip()
        self.timeout = timeout
        self._client = client
        partes = urlparse(self.base_url)
        if partes.scheme != "https" or partes.hostname != "api.acessorias.com" or partes.username or partes.password:
            raise AcessoriasErro("Use o endereço oficial https://api.acessorias.com.", 422)
        if not self.token:
            raise AcessoriasErro("Integração Acessórias não configurada.", 409)

    def _get(self, rota: str, params: dict[str, Any] | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        try:
            if self._client:
                resposta = self._client.get(self.base_url + rota, params=params, headers=headers)
            else:
                with httpx.Client(timeout=self.timeout, follow_redirects=False) as client:
                    resposta = client.get(self.base_url + rota, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise AcessoriasErro("Tempo esgotado ao comunicar com o Acessórias.", 504) from exc
        except httpx.TransportError as exc:
            raise AcessoriasErro("Não foi possível comunicar com o Acessórias.") from exc
        if resposta.status_code in (401, 403):
            raise AcessoriasErro("O Acessórias recusou o token informado.", 401)
        if resposta.status_code == 429:
            raise AcessoriasErro("Limite de 100 requisições por minuto do Acessórias atingido. Tente novamente em um minuto.", 429)
        if resposta.status_code >= 400:
            raise AcessoriasErro("A API Acessórias rejeitou a solicitação.", 502)
        try:
            dados = resposta.json()
        except ValueError as exc:
            raise AcessoriasErro("O Acessórias respondeu em formato inválido.") from exc
        if isinstance(dados, dict) and dados.get("Erro"):
            raise AcessoriasErro("O Acessórias recusou os parâmetros da consulta.", 422)
        return dados

    def listar_empresas(self, *, somente_ativas: bool = True, max_paginas: int = 100) -> list[dict[str, Any]]:
        empresas: list[dict[str, Any]] = []
        for pagina in range(1, max_paginas + 1):
            dados = self._get("/companies/ListAll/", {"ativa": "S" if somente_ativas else None, "Pagina": pagina})
            if not dados:
                return empresas
            itens = dados if isinstance(dados, list) else [dados]
            if not all(isinstance(item, dict) for item in itens):
                raise AcessoriasErro("Lista de empresas do Acessórias em formato inválido.")
            empresas.extend(itens)
            if len(itens) < 20:
                return empresas
        raise AcessoriasErro("A sincronização chegou ao limite de 2.000 empresas. Execute novamente após ampliar o limite configurado.", 409)

    def testar(self) -> None:
        self._get("/companies/ListAll/", {"ativa": "S", "Pagina": 1})
