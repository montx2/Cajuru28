"""
Ponte entre as rotas da API e o programa que está rodando.

A API não sabe (nem deve saber) se está dentro de um `uvicorn` em Docker ou
dentro do `.exe` instalado. Quando ela precisa de algo que só existe no modo
desktop — desligar a máquina toda, por exemplo — fala com este módulo, e quem
estiver rodando registra o que fazer.

Sem nada registrado, as funções não fazem nada e devolvem `False`: assim a
mesma rota responde de forma sensata no servidor, onde "encerrar o programa"
não significa nada (o contêiner é reiniciado pelo Docker).
"""

from __future__ import annotations

import logging
import threading
from typing import Callable

log = logging.getLogger("notasflow.controle")

_encerrador: Callable[[str], None] | None = None
_trava = threading.Lock()


def registrar_encerrador(funcao: Callable[[str], None]) -> None:
    global _encerrador
    with _trava:
        _encerrador = funcao


def tem_encerrador() -> bool:
    return _encerrador is not None


def encerrar(motivo: str = "") -> bool:
    """Pede o encerramento do programa. Devolve False se não há o que encerrar."""
    with _trava:
        funcao = _encerrador
    if funcao is None:
        log.info("Pedido de encerramento ignorado (modo servidor): %s", motivo)
        return False
    log.info("Encerrando o programa: %s", motivo)
    threading.Thread(target=funcao, args=(motivo,), name="notasflow-encerrar", daemon=True).start()
    return True
