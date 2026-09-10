"""
Abrir o painel — em janela de programa, não em aba de navegador.

O detalhe que separa "parece um sistema" de "parece um site": abrir o painel em
**modo aplicativo** dos navegadores Chromium (`--app=URL`), que cria uma janela
sem barra de endereço, sem abas e com ícone próprio na barra de tarefas.

Por que usar o navegador do sistema em vez de embutir um motor de renderização
(Electron, WebView2)?

- **tamanho**: Electron adiciona ~150 MB a um programa que já tem que caber num
  download de balcão; o navegador que já está na máquina custa zero;
- **atualização**: o motor de renderização atualiza sozinho pelo Windows
  Update — nenhuma vulnerabilidade de navegador fica congelada dentro do
  programa;
- **risco**: um motor embutido é mais uma peça que pode falhar no computador do
  cliente, e ninguém no escritório vai saber diagnosticar.

E existe sempre o caminho de baixo: se nada disso funcionar, abre no navegador
padrão. Um sistema que não abre é pior que um sistema que abre numa aba.
"""

from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from app.desktop import caminhos

log = logging.getLogger("notasflow.janela")

# Caminhos usuais dos navegadores Chromium no Windows. O Edge vem instalado em
# qualquer Windows 10/11 — na prática é o que será usado.
_CAMINHOS_WINDOWS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def _navegador_chromium() -> str | None:
    """Encontra um navegador que aceite `--app`."""
    sistema = platform.system()
    if sistema == "Windows":
        for caminho in _CAMINHOS_WINDOWS:
            if Path(caminho).is_file():
                return caminho
        for nome in ("msedge.exe", "chrome.exe", "brave.exe"):
            achado = shutil.which(nome)
            if achado:
                return achado
        return None

    if sistema == "Darwin":
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            if Path(f"/Applications/{app}.app").exists():
                return app
        return None

    for nome in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge", "brave-browser"):
        achado = shutil.which(nome)
        if achado:
            return achado
    return None


def _pasta_do_perfil() -> Path:
    """
    Perfil de navegador exclusivo do NotasFlow.

    Parece exagero, mas é o que faz a janela se comportar como programa: ícone
    próprio, não fecha quando o usuário fecha as outras janelas do navegador, e
    nenhuma extensão do usuário interfere no painel.
    """
    pasta = caminhos.pasta_dados() / "janela"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def abrir_painel(url: str) -> bool:
    """Abre o painel. Devolve True se conseguiu abrir de alguma forma."""
    navegador = _navegador_chromium()

    if navegador:
        argumentos = [
            f"--app={url}",
            f"--user-data-dir={_pasta_do_perfil()}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,ChromeWhatsNewUI",
            "--window-size=1400,900",
        ]
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", navegador, "--args", *argumentos])
            else:
                subprocess.Popen(
                    [navegador, *argumentos],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                )
            log.info("Painel aberto em modo aplicativo (%s).", Path(navegador).name)
            return True
        except OSError as exc:
            log.warning("Falha ao abrir %s em modo aplicativo: %s", navegador, exc)

    return _abrir_no_navegador_padrao(url)


def _abrir_no_navegador_padrao(url: str) -> bool:
    try:
        import webbrowser

        if webbrowser.open(url, new=1):
            log.info("Painel aberto no navegador padrão.")
            return True
    except Exception as exc:  # noqa: BLE001
        log.warning("Não foi possível abrir o navegador padrão: %s", exc)
    return False


def abrir_caminho(caminho: Path) -> bool:
    """Abre uma pasta ou arquivo no programa padrão do sistema."""
    try:
        caminho = Path(caminho)
        if not caminho.exists():
            caminho = caminho.parent
        if platform.system() == "Windows":
            os.startfile(str(caminho))  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(caminho)])
        else:
            subprocess.Popen(["xdg-open", str(caminho)])
        return True
    except Exception as exc:  # noqa: BLE001
        log.info("Não foi possível abrir %s: %s", caminho, exc)
        return False
