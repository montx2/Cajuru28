"""
O programa instalado: sobe a API, abre a janela, fica no relógio, sabe sair.

Este módulo é o ponto de entrada do `.exe`. Ele junta as peças que no modo
servidor são contêineres separados (API, worker, beat, painel web) em **um
processo**, na ordem certa, com desligamento limpo.

A ordem importa e é esta:

1. configura logging **antes** de qualquer coisa (se algo falhar no meio do
   caminho, o usuário precisa conseguir achar o motivo em um arquivo);
2. descobre a porta — e, se já existe um NotasFlow rodando, só abre a janela
   dele em vez de subir um segundo (dois programas com o mesmo certificado
   consultando a SEFAZ é exatamente o que trava o CNPJ);
3. sobe a API;
4. espera `/saude` responder (abrir a janela antes disso dá "não é possível
   conectar", que é o pior primeiro contato possível);
5. abre a janela e o ícone da bandeja;
6. fica no laço até alguém pedir para sair — pela tela, pela bandeja ou por
   Ctrl+C.
"""

from __future__ import annotations

import logging
import logging.handlers
import platform
import socket
import sys
import threading
import time
from contextlib import closing
from pathlib import Path

import httpx

from app.core.config import settings
from app.desktop import caminhos, controle

log = logging.getLogger("notasflow.servidor")

TIMEOUT_SAUDE = 60.0


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def configurar_logging() -> Path:
    """
    Log em arquivo com rotação — a única janela para dentro de um programa sem
    console.

    `--noconsole` no PyInstaller significa que `sys.stdout` é `None`: um
    `StreamHandler` ali derrubaria o programa na primeira linha de log. Por
    isso o handler de tela só entra quando existe tela de verdade (rodando do
    código-fonte), e o arquivo entra sempre.
    """
    pasta = caminhos.pasta_logs()
    arquivo = pasta / "notasflow.log"

    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)
    for antigo in list(raiz.handlers):
        raiz.removeHandler(antigo)

    formato = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%d/%m/%Y %H:%M:%S"
    )

    manipulador = logging.handlers.RotatingFileHandler(
        arquivo, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    manipulador.setFormatter(formato)
    raiz.addHandler(manipulador)

    if sys.stdout is not None:
        tela = logging.StreamHandler(sys.stdout)
        tela.setFormatter(formato)
        raiz.addHandler(tela)

    # O uvicorn tem os loggers dele; todos apontam para a raiz (o arquivo).
    for nome in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(nome)
        logger.handlers = []
        logger.propagate = True

    log.info("=" * 70)
    log.info(
        "NotasFlow %s iniciando (%s, Python %s)",
        caminhos.versao_do_pacote(),
        "empacotado" if caminhos.esta_empacotado() else "código-fonte",
        platform.python_version(),
    )
    log.info("Dados em %s", caminhos.pasta_dados())
    return arquivo


# ---------------------------------------------------------------------------
# Porta e instância única
# ---------------------------------------------------------------------------


def _porta_livre(porta: int) -> bool:
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", porta))
            return True
        except OSError:
            return False


def _e_o_nosso(porta: int) -> bool:
    """Confere se quem está na porta é outro NotasFlow (e não outro programa)."""
    try:
        resposta = httpx.get(f"http://127.0.0.1:{porta}/saude", timeout=2.0)
        return resposta.status_code == 200 and resposta.json().get("app") == "NotasFlow"
    except Exception:  # noqa: BLE001 — porta ocupada por outra coisa
        return False


def escolher_porta(preferida: int) -> tuple[int, bool]:
    """
    Devolve `(porta, ja_rodando)`.

    `ja_rodando=True` significa que existe outro NotasFlow nesta máquina: a
    resposta certa é abrir a janela dele e encerrar este processo. Subir um
    segundo seria pior que inútil — dois processos com os mesmos certificados
    consultariam a SEFAZ em paralelo e um travaria o CNPJ do outro.
    """
    # A primeira porta livre é a resposta: com 8765 livre, o programa sobe em
    # 8765 — e é isso que faz o endereço do painel ser sempre o mesmo (atalho,
    # favorito, log de suporte, `CREDENCIAIS.txt`).
    #
    # O erro que morava aqui era sutil e caro: a repetição só *continuava*
    # quando a porta não estava livre, e caía no sorteio de porta aleatória
    # quando todas estavam. Resultado: máquina limpa nunca usava a porta
    # configurada, o endereço mudava a cada abertura e duas instâncias não se
    # encontravam (cada uma pegava uma porta aleatória livre) — dois programas
    # consultando a SEFAZ com o mesmo certificado, que é justamente o que o
    # `ja_rodando` existe para impedir.
    for porta in range(preferida, preferida + 20):
        if _porta_livre(porta):
            return porta, False
        if _e_o_nosso(porta):
            return porta, True
        log.info("Porta %s ocupada por outro programa; tentando a próxima.", porta)

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1]), False


# ---------------------------------------------------------------------------
# Iniciar / parar a API
# ---------------------------------------------------------------------------


def _host_para_escutar() -> str:
    """
    `127.0.0.1` por padrão; `0.0.0.0` quando o usuário autoriza acesso na rede.

    A diferença não é detalhe: em `0.0.0.0` qualquer máquina da rede alcança o
    painel, que guarda senha de certificado. Por isso é opt-in explícito
    (`NOTASFLOW_PERMITIR_REDE=true`) e está documentado.
    """
    if settings.notasflow_permitir_rede:
        return "0.0.0.0"
    return settings.notasflow_host or "127.0.0.1"


def iniciar_api(host: str, porta: int):
    """Sobe o uvicorn e devolve o `Server` para poder desligá-lo depois."""
    import uvicorn

    configuracao = uvicorn.Config(
        "app.main:app",
        host=host,
        port=porta,
        log_config=None,  # usamos o logging configurado acima (arquivo)
        access_log=False,  # ruído: o painel fala por si
        loop="asyncio",
    )
    servidor = uvicorn.Server(configuracao)
    servidor.install_signal_handlers = lambda: None  # quem manda no ciclo é este módulo
    return servidor


def esperar_api(porta: int, limite: float = TIMEOUT_SAUDE) -> bool:
    inicio = time.monotonic()
    while time.monotonic() - inicio < limite:
        try:
            resposta = httpx.get(f"http://127.0.0.1:{porta}/saude", timeout=1.5)
            if resposta.status_code == 200:
                return True
        except Exception:  # noqa: BLE001 — ainda subindo
            pass
        time.sleep(0.4)
    return False


# ---------------------------------------------------------------------------
# Iniciar com o Windows
# ---------------------------------------------------------------------------


def _chave_registro():
    import winreg

    return winreg.OpenKey(
        winreg.HKEY_CURRENT_USER,
        r"Software\Microsoft\Windows\CurrentVersion\Run",
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    )


def iniciar_com_windows_ativo() -> bool:
    if platform.system() != "Windows" or not caminhos.esta_empacotado():
        return False
    try:
        import winreg

        chave = _chave_registro()
        try:
            valor, _ = winreg.QueryValueEx(chave, "NotasFlow")
            return bool(valor)
        finally:
            chave.Close()
    except OSError:
        return False


def definir_iniciar_com_windows(ativar: bool) -> bool:
    """
    Liga/desliga a inicialização automática (chave `Run` do usuário).

    Escolhida em vez da pasta Inicializar porque não exige administrador, não
    deixa um `.cmd` piscando uma janela preta no login e é o que
    desinstaladores esperam encontrar.
    """
    if platform.system() != "Windows":
        return False
    import winreg

    chave = _chave_registro()
    try:
        if ativar:
            winreg.SetValueEx(
                chave, "NotasFlow", 0, winreg.REG_SZ, f'"{sys.executable}" --minimizado'
            )
        else:
            try:
                winreg.DeleteValue(chave, "NotasFlow")
            except FileNotFoundError:
                pass
        return ativar
    finally:
        chave.Close()


# ---------------------------------------------------------------------------
# Laço principal
# ---------------------------------------------------------------------------


class Programa:
    """Estado do programa em execução (para a tela e para o desligamento)."""

    def __init__(self, *, porta: int, url: str, host: str) -> None:
        self.porta = porta
        self.url = url
        self.host = host
        self.servidor = None
        self.bandeja = None
        self.parando = threading.Event()
        self.iniciado_em = time.time()


def executar(*, abrir_janela: bool | None = None, modo: str = "normal") -> int:
    """
    Ponto de entrada do programa instalado.

    `modo`:
    - `normal`   — sobe a API, abre a janela e fica na bandeja;
    - `bandeja`  — sobe só em segundo plano (usado no início automático com o
      Windows, para o login não abrir uma janela na cara do usuário);
    - `console`  — só a API, sem janela e sem ícone (depuração).
    """
    arquivo_log = configurar_logging()

    from app.desktop.ambiente import preparar_primeira_execucao

    primeira = preparar_primeira_execucao()
    if primeira.get("criado_agora"):
        log.info("Primeira execução configurada. Credenciais em %s", primeira["arquivo_credenciais"])

    porta, ja_rodando = escolher_porta(int(settings.notasflow_porta))
    host = _host_para_escutar()
    url = f"http://127.0.0.1:{porta}/"

    if ja_rodando:
        log.info("Já existe um NotasFlow rodando na porta %s; abrindo a janela dele.", porta)
        from app.desktop.janela import abrir_painel

        abrir_painel(url)
        return 0

    programa = Programa(porta=porta, url=url, host=host)

    if host == "0.0.0.0":
        log.warning(
            "Modo rede ligado: o painel está acessível para outras máquinas em "
            "http://%s:%s/ — use apenas dentro da rede do escritório.",
            _ip_local(),
            porta,
        )

    def encerrar(motivo: str) -> None:
        if programa.parando.is_set():
            return
        log.info("Encerrando o NotasFlow (%s)…", motivo)
        programa.parando.set()
        if programa.bandeja is not None:
            programa.bandeja.parar()
        if programa.servidor is not None:
            programa.servidor.should_exit = True

    controle.registrar_encerrador(encerrar)

    def tarefa_janela() -> None:
        if not esperar_api(porta):
            log.error(
                "A API não respondeu em %.0f s. Veja o log em %s",
                TIMEOUT_SAUDE,
                arquivo_log,
            )
            return
        log.info("API no ar em %s", url)
        from app.desktop.janela import abrir_painel

        if abrir_janela if abrir_janela is not None else settings.notasflow_abrir_janela:
            abrir_painel(url)

    if modo != "console":
        threading.Thread(target=tarefa_janela, name="notasflow-janela", daemon=True).start()

    # Ícone na bandeja: é ele que permite fechar a janela e continuar
    # sincronizando. Sem ícone, o programa continua funcionando — só não tem
    # onde clicar fora do navegador.
    if modo != "console" and settings.notasflow_bandeja:
        from app.desktop.bandeja import Bandeja

        def verificar_atualizacao() -> None:
            """
            Item "Verificar atualização" do menu do ícone.

            O trabalho vai para uma thread porque `verificar()` espera rede (até
            15 s): um menu que congela é um menu que parece travado. A resposta
            ao usuário vem depois, quando o estado já estiver resolvido — e é
            lida do **mesmo** estado que a faixa do painel usa, para o ícone e a
            tela nunca contarem histórias diferentes.
            """
            from app.api.routers.sistema import estado_da_atualizacao, verificar_em_segundo_plano

            def tarefa() -> None:
                iniciado, _ = verificar_em_segundo_plano()
                if not iniciado:
                    return
                estado = estado_da_atualizacao()
                for _ in range(60):  # até ~30 s, o mesmo teto do timeout de rede
                    if estado["etapa"] != "verificando":
                        break
                    time.sleep(0.5)
                    estado = estado_da_atualizacao()

                if programa.bandeja is None:
                    return
                disponivel = estado.get("disponivel")
                if disponivel:
                    programa.bandeja.notificar(
                        f"Versão {disponivel['versao']} disponível. Abra o painel para atualizar.",
                        titulo="NotasFlow",
                    )
                elif estado["etapa"] == "atualizado":
                    programa.bandeja.notificar(
                        f"Você está na versão mais nova ({estado['versao_atual']}).",
                        titulo="NotasFlow",
                    )
                elif estado.get("erro"):
                    programa.bandeja.notificar(
                        "Não foi possível verificar agora (sem internet?).",
                        titulo="NotasFlow",
                    )

            threading.Thread(target=tarefa, name="notasflow-update-menu", daemon=True).start()

        programa.bandeja = Bandeja(
            url=url, ao_sair=encerrar, ao_verificar_atualizacao=verificar_atualizacao
        )
        programa.bandeja.iniciar()

    if modo == "bandeja":
        # Início automático: nada de janela. O ícone fica no relógio e o
        # usuário abre quando quiser.
        log.info("Iniciado em segundo plano (início automático).")

    # Verificação de atualização: ao abrir e **de tempo em tempo**, sem bloquear
    # nada.
    #
    # O "de tempo em tempo" é o que faz a promessa valer: este programa fica
    # aberto na bandeja por semanas (é o ponto do modo desktop). Se a
    # verificação só acontecesse na abertura, uma correção publicada hoje
    # chegaria em quem reiniciar o computador — e em mais ninguém.
    if settings.notasflow_verificar_atualizacao_ao_abrir and settings.modo_desktop:
        from app.api.routers.sistema import verificar_em_segundo_plano

        def checar_periodicamente() -> None:
            from app.desktop import atualizador

            time.sleep(8)  # deixa a API e a janela subirem primeiro
            while not programa.parando.is_set():
                try:
                    iniciado, _ = verificar_em_segundo_plano()
                    if iniciado:
                        log.info("Verificação de atualização disparada em segundo plano.")
                except Exception as exc:  # noqa: BLE001 — nunca derrubar o programa por isso
                    log.info("Verificação de atualização falhou: %s", exc)
                finally:
                    atualizador.limpar_antigos()

                # Espera em fatias de 1 minuto: desligar o programa não fica
                # preso esperando 6 h de `sleep`.
                for _ in range(max(1, int(settings.notasflow_verificar_atualizacao_horas * 60))):
                    if programa.parando.is_set():
                        return
                    time.sleep(60)

        threading.Thread(target=checar_periodicamente, name="notasflow-check-update", daemon=True).start()

    programa.servidor = iniciar_api(host, porta)

    try:
        programa.servidor.run()
    except KeyboardInterrupt:  # pragma: no cover
        encerrar("Ctrl+C")
    finally:
        if programa.bandeja is not None:
            programa.bandeja.parar()
        log.info("NotasFlow encerrado.")

    return 0


def _ip_local() -> str:
    """
    IP da máquina na rede local — só para a mensagem do modo rede.

    Tenta abrir um socket UDP para fora: o sistema escolhe a interface que
    realmente tem rota, o que dá o IP certo mesmo com Wi-Fi + Ethernet + VPN
    ligados ao mesmo tempo (onde listar as interfaces erra com frequência).
    """
    try:
        with closing(socket.socket(socket.AF_INET, socket.SOCK_DGRAM)) as s:
            s.connect(("8.8.8.8", 80))
            return str(s.getsockname()[0])
    except OSError:
        return "localhost"
