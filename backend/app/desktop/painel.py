"""
Serve o painel web já compilado a partir da própria API.

No modo servidor, quem entrega o painel é um contêiner Node (Next.js). No
programa instalado isso seria absurdo: obrigaria cada computador a ter Node.js
instalado, mais um processo para cuidar, mais uma porta para vigiar. Então o
build **estático** do mesmo painel é empacotado junto com o `.exe` e servido
pela própria API — uma porta só, uma origem só (o que também elimina CORS como
fonte de problema).

O roteamento do export estático do Next não é "arquivo por caminho": a rota
`/dashboard/empresas` vira o arquivo `dashboard/empresas/index.html`, e o
usuário digita (ou o atalho do navegador aponta para) `/dashboard/empresas` sem
a barra final. Este módulo resolve essa diferença — e devolve `index.html` para
qualquer rota desconhecida, que é o que faz um clique no menu não dar 404.
"""

from __future__ import annotations

import mimetypes
import posixpath
from pathlib import Path

from starlette.responses import FileResponse, PlainTextResponse, Response
from starlette.types import Scope

# Pastas que não devem cair no "fallback de SPA": são arquivos com hash no nome
# (imutáveis). Devolver HTML onde o navegador pediu JavaScript quebra a tela de
# um jeito difícil de diagnosticar.
PREFIXOS_DE_ARQUIVO = ("_next/", "static/", "favicon", "icone", "logo")

CABECALHOS_IMUTAVEIS = {"Cache-Control": "public, max-age=31536000, immutable"}
CABECALHOS_HTML = {"Cache-Control": "no-cache, must-revalidate"}


class PainelEstatico:
    """
    Aplicação ASGI mínima: resolve o caminho pedido para um arquivo do build.

    Escrita à mão (em vez de `StaticFiles`) porque o objetivo é *não* dar 404
    em rota de cliente — e `StaticFiles` faz exatamente isso.
    """

    def __init__(self, raiz: Path) -> None:
        self.raiz = Path(raiz).resolve()

    def _dentro_da_raiz(self, relativo: str) -> Path | None:
        """
        Converte uma URL em caminho de disco **sem permitir escapar da pasta**.

        `../../etc/passwd` não é paranoia: é a primeira coisa que qualquer
        varredura automatizada tenta quando encontra um servidor local.
        """
        limpo = posixpath.normpath("/" + (relativo or "")).lstrip("/")
        if limpo in ("", "."):
            limpo = ""
        alvo = (self.raiz / limpo).resolve()
        try:
            alvo.relative_to(self.raiz)
        except ValueError:
            return None
        return alvo

    def _resolver(self, caminho: str) -> Path | None:
        alvo = self._dentro_da_raiz(caminho)
        if alvo is None:
            return None
        if alvo.is_file():
            return alvo
        if alvo.is_dir():
            indice = alvo / "index.html"
            if indice.is_file():
                return indice
            return None
        # `/dashboard/empresas` → `dashboard/empresas.html`
        html = alvo.with_suffix(".html") if alvo.suffix == "" else alvo.parent / (alvo.name + ".html")
        if html.is_file():
            return html
        return None

    def _parece_arquivo(self, caminho: str) -> bool:
        final = posixpath.basename(caminho)
        return "." in final or caminho.startswith(PREFIXOS_DE_ARQUIVO)

    def _resposta_arquivo(self, arquivo: Path) -> Response:
        tipo = mimetypes.guess_type(arquivo.name)[0] or "application/octet-stream"
        if tipo.startswith("text/") or tipo in ("application/javascript", "application/json"):
            # O Next grava os nomes com charset nas URLs de assets; o
            # `mimetypes` do Python não conhece `.mjs`.
            if arquivo.suffix == ".mjs":
                tipo = "text/javascript"
            tipo = f"{tipo}; charset=utf-8"
        imutavel = "_next" in arquivo.parts and "static" in arquivo.parts
        return FileResponse(
            arquivo,
            media_type=tipo,
            headers=CABECALHOS_IMUTAVEIS if imutavel else CABECALHOS_HTML,
        )

    async def __call__(self, scope: Scope, receive, send) -> None:
        if scope["type"] != "http":
            return

        caminho = scope.get("path", "/").lstrip("/")
        arquivo = self._resolver(caminho)

        if arquivo is None:
            if self._parece_arquivo(caminho):
                resposta: Response = PlainTextResponse("Arquivo não encontrado", status_code=404)
            else:
                indice = self.raiz / "index.html"
                resposta = (
                    self._resposta_arquivo(indice)
                    if indice.is_file()
                    else PlainTextResponse("Painel não compilado", status_code=503)
                )
        else:
            resposta = self._resposta_arquivo(arquivo)

        await resposta(scope, receive, send)
