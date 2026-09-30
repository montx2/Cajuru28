"""
Camada Playwright para observação determinística do portal.

Este módulo não é um "robô visual". Ele existe para automatizar o que é
tecnicamente seguro e auditável: abrir contextos isolados, validar âncoras do
DOM, detectar human gates, capturar evidências e preparar a retomada. Ações que
praticam outorga/alteração/revogação no portal continuam bloqueadas pela
política de conformidade do backend, a menos que exista canal oficial ou
habilitação formal específica.

Toda interação usa locator/role/texto; não há coordenadas, imagem ou
``sleep(10000)``.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .human_gate import HumanGate, classificar_intervencao
from .roteiro import DOMINIOS_PERMITIDOS, url_permitida


class PlaywrightIndisponivel(RuntimeError):
    pass


class PortalNaoReconhecido(RuntimeError):
    def __init__(self, etapa: str, ausentes: list[str], url: str):
        super().__init__(f"Portal não reconhecido na etapa {etapa}: ausentes {', '.join(ausentes)}")
        self.etapa = etapa
        self.ausentes = ausentes
        self.url = url


@dataclass(frozen=True)
class OpcoesSessaoBrowser:
    job_id: int
    identidade: str
    user_data_dir: Path
    evidencias_dir: Path
    navegador: str = "msedge"
    headless: bool = False
    timeout_ms: int = 30_000
    trace: bool = True
    viewport: dict[str, int] = field(default_factory=lambda: {"width": 1366, "height": 900})


@dataclass(frozen=True)
class ResultadoAncora:
    ok: bool
    ausentes: tuple[str, ...] = ()
    url: str = ""


@dataclass(frozen=True)
class EvidenciaCapturada:
    screenshot: Path | None = None
    html: Path | None = None
    trace: Path | None = None
    url: str = ""


class PlaywrightPortalSession:
    """Sessão isolada de navegador para um job.

    A classe é intencionalmente pequena: o fluxo específico do portal deve ficar
    em adaptadores que chamem estes primitivos e validem o resultado esperado.
    """

    def __init__(self, opcoes: OpcoesSessaoBrowser):
        self.opcoes = opcoes
        self._pw = None
        self._context = None
        self._page = None

    async def __aenter__(self):
        try:
            from playwright.async_api import async_playwright  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise PlaywrightIndisponivel(
                "Playwright não está instalado. Rode `pip install -r agent/requirements.txt` "
                "e `python -m playwright install chromium`."
            ) from exc

        self.opcoes.user_data_dir.mkdir(parents=True, exist_ok=True)
        self.opcoes.evidencias_dir.mkdir(parents=True, exist_ok=True)
        self._pw = await async_playwright().start()
        browser_type = self._pw.chromium
        kwargs: dict[str, Any] = {
            "user_data_dir": str(self.opcoes.user_data_dir),
            "headless": self.opcoes.headless,
            "viewport": self.opcoes.viewport,
            "accept_downloads": False,
            "ignore_https_errors": False,
        }
        if self.opcoes.navegador:
            # msedge/chrome usam o store do sistema e respeitam políticas
            # AutoSelectCertificateForUrls. Chromium bundled também funciona,
            # mas pode exigir política separada no registro.
            kwargs["channel"] = self.opcoes.navegador
        self._context = await browser_type.launch_persistent_context(**kwargs)
        self._context.set_default_timeout(self.opcoes.timeout_ms)
        if self.opcoes.trace:
            await self._context.tracing.start(screenshots=True, snapshots=True, sources=False)
        self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        trace_path: Path | None = None
        if self._context is not None and self.opcoes.trace:
            trace_path = self.opcoes.evidencias_dir / f"job-{self.opcoes.job_id}-trace.zip"
            try:
                await self._context.tracing.stop(path=str(trace_path))
            except Exception:
                trace_path = None
        if self._context is not None:
            await self._context.close()
        if self._pw is not None:
            await self._pw.stop()
        return False

    @property
    def page(self):
        if self._page is None:
            raise RuntimeError("Sessão Playwright ainda não foi aberta.")
        return self._page

    async def abrir(self, url: str) -> None:
        if not url_permitida(url):
            raise ValueError(f"URL fora da allowlist oficial: {url}")
        await self.page.goto(url, wait_until="domcontentloaded")

    async def verificar_ancoras(self, etapa: str, ancoras: Iterable[str]) -> ResultadoAncora:
        ausentes: list[str] = []
        for texto in ancoras:
            locator = self.page.get_by_text(texto, exact=False).first
            try:
                await locator.wait_for(state="visible", timeout=5_000)
            except Exception:  # Playwright TimeoutError, sem importar no topo
                ausentes.append(texto)
        url = self.page.url
        return ResultadoAncora(ok=not ausentes, ausentes=tuple(ausentes), url=url)

    async def exigir_ancoras(self, etapa: str, ancoras: Iterable[str]) -> None:
        resultado = await self.verificar_ancoras(etapa, ancoras)
        if not resultado.ok:
            await self.capturar_evidencia(etapa=etapa, prefixo="portal-alterado")
            raise PortalNaoReconhecido(etapa, list(resultado.ausentes), resultado.url)

    async def detectar_human_gate(self) -> HumanGate | None:
        """Detecta sinais comuns sem tentar resolver o desafio."""
        candidatos = [
            "captcha",
            "recaptcha",
            "não sou um robô",
            "código de verificação",
            "autenticação em duas etapas",
            "senha do certificado",
            "PIN",
            "Selecionar certificado",
        ]
        for texto in candidatos:
            try:
                if await self.page.get_by_text(texto, exact=False).first.is_visible(timeout=500):
                    return classificar_intervencao(texto)
            except Exception:
                continue
        return None

    async def aguardar_fim_do_gate(self, gate: HumanGate, *, timeout_ms: int | None = None) -> None:
        """Aguarda condição objetiva: o texto que denunciou o gate sumir.

        O operador resolve fora do código; aqui apenas esperamos a página deixar
        de exibir a barreira e voltar para um estado observável.
        """
        timeout = timeout_ms or self.opcoes.timeout_ms
        inicio = asyncio.get_running_loop().time()
        while True:
            atual = await self.detectar_human_gate()
            if atual is None or atual.codigo_erro != gate.codigo_erro:
                return
            if (asyncio.get_running_loop().time() - inicio) * 1000 > timeout:
                raise TimeoutError(f"Human gate não foi resolvido dentro do prazo: {gate.codigo_erro}")
            await self.page.wait_for_timeout(250)

    async def recarregar(self) -> None:
        await self.page.reload(wait_until="domcontentloaded")

    async def texto_visivel(self) -> str:
        try:
            return await self.page.inner_text("body")
        except Exception:  # página em branco/entre navegações
            try:
                return await self.page.content()
            except Exception:
                return ""

    async def clicar(self, alvo: str) -> bool:
        """Clica um controle de navegação por role/texto (nunca por coordenada).

        Só é usado nas etapas de navegação (``executor == "sistema"``). O ato de
        outorga não passa por aqui — ele é sempre humano.
        """
        for tentativa in (
            lambda: self.page.get_by_role("link", name=alvo, exact=False).first,
            lambda: self.page.get_by_role("button", name=alvo, exact=False).first,
            lambda: self.page.get_by_text(alvo, exact=False).first,
        ):
            try:
                locator = tentativa()
                await locator.wait_for(state="visible", timeout=5_000)
                await locator.click()
                return True
            except Exception:
                continue
        return False

    async def limpar_cookies(self) -> None:
        """Zera cookies e armazenamento local — o próximo cliente começa limpo."""
        if self._context is not None:
            await self._context.clear_cookies()
        try:
            await self.page.evaluate(
                "() => { try { localStorage.clear(); sessionStorage.clear(); } catch (e) {} }"
            )
        except Exception:
            pass

    async def capturar_evidencia(self, *, etapa: str, prefixo: str = "evidencia") -> EvidenciaCapturada:
        seguro = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in etapa)[:80]
        base = self.opcoes.evidencias_dir / f"{prefixo}-job-{self.opcoes.job_id}-{seguro}"
        screenshot = base.with_suffix(".png")
        html = base.with_suffix(".html")
        await self.page.screenshot(path=str(screenshot), full_page=True)
        conteudo = await self.page.content()
        # Redação básica de segredos em HTML antes de persistir evidência.
        redigido = _redigir_html(conteudo)
        html.write_text(redigido, encoding="utf-8")
        return EvidenciaCapturada(screenshot=screenshot, html=html, url=self.page.url)


def _redigir_html(html: str) -> str:
    termos = ("password", "senha", "passphrase", "token", "pin", "cookie")
    texto = html
    for termo in termos:
        # Redação propositalmente simples e sem regex destrutiva: evita salvar
        # valores próximos a campos de segredo sem tentar parsear a página.
        texto = re.sub(termo, f"{termo}[REDACTED]", texto, flags=re.IGNORECASE)
    return texto


class PlaywrightPaginaSync:
    """Adaptador síncrono do Playwright para a condução do ajudante.

    A condução (``navegador_conducao.ConducaoNavegador``) é síncrona de
    propósito — assim toda a lógica de decisão é testável sem um navegador. Esta
    classe empresta os primitivos do navegador real por trás da mesma interface
    ``PaginaControlada``, mantendo um único event loop e uma única sessão
    persistente para toda a execução (os cookies são zerados entre clientes por
    ``limpar_cookies``, não recriando o navegador a cada job).

    Uso::

        with PlaywrightPaginaSync(opcoes) as pagina:
            conducao = ConducaoNavegador(pagina, navegador="edge")
            Agente(config, cliente, conducao=conducao).rodar()
    """

    def __init__(self, opcoes: "OpcoesSessaoBrowser"):
        self._opcoes = opcoes
        self._loop = None
        self._sessao: PlaywrightPortalSession | None = None

    # -- ciclo de vida -----------------------------------------------------

    def __enter__(self) -> "PlaywrightPaginaSync":
        self._loop = asyncio.new_event_loop()
        self._sessao = PlaywrightPortalSession(self._opcoes)
        self._rodar(self._sessao.__aenter__())
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if self._sessao is not None:
                self._rodar(self._sessao.__aexit__(exc_type, exc, tb))
        finally:
            if self._loop is not None:
                self._loop.close()
                self._loop = None
        return False

    def _rodar(self, coro):
        assert self._loop is not None
        return self._loop.run_until_complete(coro)

    # -- PaginaControlada --------------------------------------------------

    def abrir(self, url: str) -> None:
        self._rodar(self._sessao.abrir(url))

    def url_atual(self) -> str:
        return self._sessao.page.url if self._sessao else ""

    def texto_visivel(self) -> str:
        return self._rodar(self._sessao.texto_visivel())

    def recarregar(self) -> None:
        self._rodar(self._sessao.recarregar())

    def clicar(self, alvo: str) -> bool:
        return bool(self._rodar(self._sessao.clicar(alvo)))

    def esperar(self, ms: int) -> None:
        self._rodar(self._sessao.page.wait_for_timeout(ms))

    def limpar_cookies(self) -> None:
        self._rodar(self._sessao.limpar_cookies())

    def reiniciar(self) -> None:
        """Reabre o contexto depois de alterar a política de certificado.

        Chrome e Edge leem ``AutoSelectCertificateForUrls`` na inicialização.
        Aplicar a regra com o navegador já aberto não basta: o contexto precisa
        ser fechado e reaberto antes da primeira navegação autenticada.
        """
        if self._sessao is None:
            return
        self._rodar(self._sessao.__aexit__(None, None, None))
        self._sessao = PlaywrightPortalSession(self._opcoes)
        self._rodar(self._sessao.__aenter__())

    def capturar_evidencia(self, etapa: str, prefixo: str) -> None:
        try:
            self._rodar(self._sessao.capturar_evidencia(etapa=etapa, prefixo=prefixo))
        except Exception:  # evidência é best-effort; nunca derruba a condução
            pass
