"""Jettax Morfeu 360: somente GET, token puro, contrato verificado em diagnóstico.

Downloads não seguem redirects, não recebem token e são ligados a um IP público
resolvido previamente (Host e SNI originais preservados). Links nunca são salvos.
"""
from __future__ import annotations

import contextvars
import ipaddress
import logging
import re
import socket
import time
from xml.parsers import expat
from contextlib import closing, contextmanager
from typing import Any, Iterator
from urllib.parse import urlsplit

import httpx

HOST_OFICIAL = "morfeu.jettax360.com.br"
BASE_URL_PADRAO = "https://morfeu.jettax360.com.br"
_sigiloso = contextvars.ContextVar("jettax_http_sigiloso", default=False)


class _SemLogsSigilosos(logging.Filter):
    def filter(self, record):
        # httpx INFO inclui a URL e httpcore DEBUG pode incluir headers.
        return not _sigiloso.get()


for _nome in ("httpx", "httpcore", "httpcore.connection", "httpcore.connection_pool",
              "httpcore.http11", "httpcore.http2", "httpcore.proxy", "httpcore.socks"):
    logging.getLogger(_nome).addFilter(_SemLogsSigilosos())


@contextmanager
def _sem_logs_http():
    contexto = _sigiloso.set(True)
    try:
        yield
    finally:
        _sigiloso.reset(contexto)


class JettaxErro(RuntimeError):
    def __init__(self, mensagem: str, status_code: int = 502):
        super().__init__(mensagem)
        self.status_code = status_code


def _cnpj(valor: str) -> str:
    documento = re.sub(r"[. /-]", "", valor).upper()
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", documento):
        raise JettaxErro("Informe um CNPJ válido para consultar o Jettax.", 422)
    return documento


def _destino_publico(url: str) -> tuple[httpx.URL, str]:
    """Valida e fixa o IP: uma segunda resolução DNS não pode trocar o destino."""
    try:
        destino = httpx.URL(url)
        if (destino.scheme != "https" or not destino.host or destino.userinfo
                or destino.port not in (None, 443) or destino.fragment):
            raise ValueError
        respostas = socket.getaddrinfo(destino.host, 443, type=socket.SOCK_STREAM)
        ips = [item[4][0] for item in respostas]
        if not ips or not all(ipaddress.ip_address(ip).is_global for ip in ips):
            raise ValueError
        return destino.copy_with(host=ips[0]), destino.host
    except (ValueError, OSError, httpx.InvalidURL):
        raise JettaxErro("Link de XML inválido ou com destino não permitido.", 422) from None


class ClienteJettax:
    def __init__(self, base_url: str = BASE_URL_PADRAO, token: str = "", *,
                 timeout: float = 30, client: httpx.Client | None = None,
                 intervalo: float = 2, max_paginas: int = 500):
        self.base_url = (base_url or BASE_URL_PADRAO).strip().rstrip("/")
        try:
            partes = urlsplit(self.base_url)
            valido = (partes.scheme == "https" and partes.hostname == HOST_OFICIAL
                      and not partes.username and not partes.password
                      and partes.port in (None, 443) and not partes.path
                      and not partes.query and not partes.fragment)
        except ValueError:
            valido = False
        if not valido:
            raise JettaxErro("Use o endereço oficial https://morfeu.jettax360.com.br.", 422)
        self.token = token.strip()
        if not self.token or len(self.token) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in self.token):
            raise JettaxErro("Integração Jettax não configurada ou token inválido.", 409)
        self.timeout = timeout
        self._client = client
        self.intervalo = max(0, intervalo)
        self.max_paginas = max(1, max_paginas)
        self._ultima = 0.0

    def _ler(self, url: str | httpx.URL, *, params=None, arquivo=False,
             host: str | None = None) -> bytes:
        limite = 2 * 1024 * 1024 if arquivo else 8 * 1024 * 1024
        headers = {"Accept": "application/xml, text/xml, */*" if arquivo else "application/json"}
        if not arquivo:
            headers["Authorization"] = self.token
        elif host:
            headers["Host"] = host
        extensoes = {"sni_hostname": host} if host else {}
        for tentativa in range(3):
            time.sleep(max(0, self.intervalo - (time.monotonic() - self._ultima)))
            self._ultima = time.monotonic()
            with _sem_logs_http():
                try:
                    with self._sessao() as cliente:
                        pedido = cliente.build_request("GET", url, params=params, headers=headers,
                                                       extensions=extensoes, timeout=self.timeout)
                        if arquivo:
                            for nome in ("authorization", "cookie", "proxy-authorization"):
                                pedido.headers.pop(nome, None)
                        with closing(cliente.send(pedido, stream=True, auth=None, follow_redirects=False)) as resposta:
                            status = resposta.status_code
                            if status == 429:
                                raise JettaxErro("Limite de requisições do Jettax atingido. Aguarde antes de executar novamente.", 429)
                            if status in (401, 403):
                                if arquivo:
                                    raise JettaxErro("Link de XML expirado ou recusado; execute novamente para obter um link novo.", 410)
                                raise JettaxErro("O Jettax recusou o token informado.", 401)
                            if status >= 500:
                                if tentativa < 2:
                                    time.sleep(2 ** tentativa)
                                    continue
                                raise JettaxErro("Jettax indisponível após as tentativas de comunicação.")
                            if not 200 <= status < 300:
                                raise JettaxErro("Arquivo ou consulta Jettax recusado; redirecionamentos não são permitidos.")
                            conteudo = bytearray()
                            for parte in resposta.iter_bytes(chunk_size=65536):
                                conteudo.extend(parte)
                                if len(conteudo) > limite:
                                    raise JettaxErro("Resposta Jettax ultrapassou o limite de segurança.", 422)
                            return bytes(conteudo)
                except httpx.TransportError as exc:
                    if tentativa < 2:
                        time.sleep(2 ** tentativa)
                        continue
                    mensagem = "Tempo esgotado ao comunicar com o Jettax." if isinstance(exc, httpx.TimeoutException) else "Não foi possível comunicar com o Jettax."
                    raise JettaxErro(mensagem, 504 if isinstance(exc, httpx.TimeoutException) else 502) from None
        raise JettaxErro("Não foi possível comunicar com o Jettax.")

    @contextmanager
    def _sessao(self):
        if self._client is not None:
            yield self._client
        else:
            # Sem proxies do ambiente, cookies e Authorization compartilhados com storage.
            with httpx.Client(timeout=self.timeout, follow_redirects=False, trust_env=False) as cliente:
                yield cliente

    def _get_json(self, rota: str, params: dict[str, Any] | None = None):
        import json
        try:
            return json.loads(self._ler(self.base_url + rota, params=params))
        except (ValueError, UnicodeError):
            raise JettaxErro("O Jettax respondeu em formato JSON inválido.") from None

    def testar(self):
        dados = self._get_json("/api/clients")
        if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
            raise JettaxErro("Lista de clientes do Jettax em formato não reconhecido.")

    def empresa_cadastrada(self, cnpj: str) -> bool:
        cnpj = _cnpj(cnpj)
        dados = self._get_json("/api/clients", {"cnpj": cnpj})
        if not isinstance(dados, dict) or not isinstance(dados.get("data"), list):
            raise JettaxErro("Lista de clientes do Jettax em formato não reconhecido.")
        for item in dados["data"]:
            if not isinstance(item, dict) or not isinstance(item.get("cnpj"), str):
                raise JettaxErro("Cadastro de cliente Jettax sem CNPJ reconhecido.")
            if _cnpj(item["cnpj"]) == cnpj:
                return True
        meta = dados.get("meta")
        meta = meta.get("pagination") if isinstance(meta, dict) else None
        if not isinstance(meta, dict):
            raise JettaxErro("Paginação de clientes Jettax em formato não reconhecido.")
        total = meta.get("total")
        if type(total) is not int or total > len(dados["data"]):
            raise JettaxErro("Consulta de cliente Jettax incompleta; não é seguro declarar empresa ausente.")
        return False

    def paginas_nfse(self, cnpj: str, competencia: str) -> Iterator[list[dict]]:
        """Só page foi confirmado. Não envia limit nem segue links da resposta."""
        cnpj = _cnpj(cnpj)
        if not re.fullmatch(r"(0[1-9]|1[0-2])-\d{4}", competencia):
            raise JettaxErro("Competência Jettax inválida. Use MM-AAAA.", 422)
        ids_vistos: set[str] = set()
        total_inicial = paginas_iniciais = None
        quantidade = 0
        for pagina in range(1, self.max_paginas + 1):
            dados = self._get_json(f"/api/nfse/invoices/{cnpj}",
                                   {"period": competencia, "simpleResponse": "true", "page": pagina})
            try:
                itens = dados["data"]
                pag = dados["meta"]["pagination"]
                total, paginas = pag["total"], pag["total_pages"]
                atual, por_pagina, contagem = pag["current_page"], pag["per_page"], pag["count"]
                if (not isinstance(itens, list) or not all(isinstance(i, dict) for i in itens)
                        or any(type(v) is not int for v in (total, paginas, atual, por_pagina, contagem))
                        or total < 0 or paginas < 0 or por_pagina < 1
                        or atual != pagina or contagem != len(itens)
                        or len(itens) > por_pagina or (total > 0 and paginas < pagina)):
                    raise ValueError
            except (KeyError, TypeError, ValueError):
                raise JettaxErro("Paginação Jettax inconsistente; importação não foi considerada completa.") from None
            if total_inicial is None:
                total_inicial, paginas_iniciais = total, paginas
            if total != total_inicial or paginas != paginas_iniciais:
                raise JettaxErro("A listagem Jettax mudou durante a consulta. Execute novamente; o que já entrou não será duplicado.")
            if total and not itens:
                raise JettaxErro("Página Jettax vazia antes do fim; execute novamente.")
            for item in itens:
                identificador = item.get("id")
                if not isinstance(identificador, str) or not identificador or identificador in ids_vistos:
                    raise JettaxErro("Nota sem identificador ou página repetida no Jettax; consulta interrompida.")
                ids_vistos.add(identificador)
            quantidade += len(itens)
            yield itens  # Chamador baixa XMLs agora, antes de pedir a próxima página.
            if pagina >= paginas:
                if quantidade != total:
                    raise JettaxErro("Contagem Jettax não confere com o total; importação parcial.")
                return
        raise JettaxErro("Limite de páginas Jettax atingido; importação parcial. Execute novamente após ampliar JETTAX_MAX_PAGINAS.")

    def baixar_xml(self, url: str) -> bytes:
        if not isinstance(url, str) or not url:
            raise JettaxErro("Nota Jettax sem link de XML.", 422)
        destino, host = _destino_publico(url)
        conteudo = self._ler(destino, arquivo=True, host=host)
        def rejeitar_declaracao(*args):
            raise JettaxErro("XML Jettax com declaração não permitida.", 422)
        parser = expat.ParserCreate()
        parser.StartDoctypeDeclHandler = rejeitar_declaracao
        parser.EntityDeclHandler = rejeitar_declaracao
        parser.ExternalEntityRefHandler = rejeitar_declaracao
        try:
            parser.Parse(conteudo, True)
        except expat.ExpatError:
            raise JettaxErro("Arquivo Jettax não é um XML válido; TXT não é suportado nesta etapa.", 422) from None
        return conteudo
