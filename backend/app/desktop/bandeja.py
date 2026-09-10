"""
Ícone ao lado do relógio — o que faz o programa "ficar rodando de fundo".

Um sistema que sincroniza sozinho não pode depender de uma aba de navegador
aberta. O ícone na bandeja é o que permite ao usuário **fechar a janela e
continuar sincronizando** — como OneDrive, Dropbox e Teams fazem — e ainda
assim ter onde clicar para reabrir, ver o log ou sair de verdade.

## Quando o ícone não aparece

Se `pystray`/Pillow não estiverem disponíveis, ou se o ambiente não tiver
interface gráfica (servidor Linux, sessão remota restrita), isto não pode
derrubar o programa: o painel continua funcionando no navegador e as ações
equivalentes continuam acessíveis em **Configurações → Encerrar o programa**.
Por isso a importação é feita dentro da função, com `try/except`, e não no topo
do módulo.
"""

from __future__ import annotations

import logging
import threading

from app.desktop import caminhos

log = logging.getLogger("notasflow.bandeja")

NOME_ICONE = "NotasFlow"


def _carregar_imagem():
    """
    Carrega o ícone do pacote; se não achar, desenha um na hora.

    O fallback existe porque um ícone faltando não pode significar "programa
    não abre" — e desenhar um "NF" com o mesmo azul do painel leva dez linhas.
    """
    from PIL import Image, ImageDraw

    for candidato in (
        caminhos.pasta_recursos() / "icone.ico",
        caminhos.pasta_recursos() / "icone.png",
        caminhos.pasta_programa() / "icone.ico",
    ):
        try:
            if candidato.is_file():
                return Image.open(candidato).convert("RGBA")
        except OSError:
            continue

    tamanho = 64
    imagem = Image.new("RGBA", (tamanho, tamanho), (0, 0, 0, 0))
    desenho = ImageDraw.Draw(imagem)
    desenho.rounded_rectangle([(2, 2), (tamanho - 2, tamanho - 2)], radius=14, fill=(31, 78, 121, 255))
    desenho.text((14, 18), "NF", fill=(255, 255, 255, 255))
    return imagem


class Bandeja:
    """Ciclo de vida do ícone, com tudo o que pode falhar tratado."""

    def __init__(self, *, url: str, ao_sair, ao_verificar_atualizacao=None) -> None:
        self.url = url
        self.ao_sair = ao_sair
        self.ao_verificar_atualizacao = ao_verificar_atualizacao
        self._icone = None
        self._disponivel = False

    @property
    def disponivel(self) -> bool:
        return self._disponivel

    def iniciar(self) -> bool:
        try:
            import pystray
        except Exception as exc:  # noqa: BLE001 — sem interface gráfica, segue sem ícone
            log.info("Ícone da bandeja indisponível (%s). O painel continua funcionando.", exc)
            return False

        try:
            from app.desktop.janela import abrir_painel

            itens = [
                pystray.MenuItem(
                    "Abrir o NotasFlow",
                    lambda *_: abrir_painel(self.url),
                    default=True,
                ),
            ]
            if self.ao_verificar_atualizacao is not None:
                itens.append(
                    pystray.MenuItem("Verificar atualizações", self._verificar_atualizacao)
                )
            itens += [
                pystray.MenuItem("Abrir a pasta de dados", self._abrir_pasta),
                pystray.MenuItem("Ver o último log", self._abrir_log),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Encerrar o NotasFlow", self._sair),
            ]

            self._icone = pystray.Icon(
                NOME_ICONE,
                _carregar_imagem(),
                "NotasFlow — importação fiscal",
                pystray.Menu(*itens),
            )
            # `run_detached` é o caminho suportado para rodar o ícone fora do
            # laço principal — que aqui está ocupado pelo servidor da API.
            self._icone.run_detached()
            self._disponivel = True
            log.info("Ícone da bandeja iniciado.")
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível criar o ícone da bandeja: %s", exc)
            return False

    def parar(self) -> None:
        try:
            if self._icone is not None:
                self._icone.stop()
        except Exception:  # noqa: BLE001 — encerrar nunca pode travar o fechamento
            pass

    def notificar(self, mensagem: str, titulo: str = "NotasFlow") -> None:
        try:
            if self._icone is not None:
                self._icone.notify(mensagem, titulo)
        except Exception:  # noqa: BLE001
            pass

    # -- ações do menu ------------------------------------------------------
    def _verificar_atualizacao(self, *_args) -> None:
        if self.ao_verificar_atualizacao is not None:
            threading.Thread(target=self.ao_verificar_atualizacao, daemon=True).start()

    def _abrir_pasta(self, *_args) -> None:
        from app.desktop.janela import abrir_caminho

        abrir_caminho(caminhos.pasta_dados())

    def _abrir_log(self, *_args) -> None:
        from app.desktop.janela import abrir_caminho

        arquivo = caminhos.pasta_logs() / "notasflow.log"
        abrir_caminho(arquivo if arquivo.is_file() else caminhos.pasta_logs())

    def _sair(self, *_args) -> None:
        self.ao_sair("menu da bandeja")
