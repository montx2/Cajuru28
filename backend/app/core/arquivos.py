"""Escrita atômica de evidências: nunca truncar um XML fiscal já existente."""

import os
import tempfile
from pathlib import Path


def gravar_bytes_atomicamente(caminho: str | Path, conteudo: bytes) -> None:
    destino = Path(caminho)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, temporario = tempfile.mkstemp(prefix=".xml-", dir=destino.parent)
    try:
        with os.fdopen(fd, "wb") as arquivo:
            arquivo.write(conteudo)
            arquivo.flush()
            os.fsync(arquivo.fileno())
        os.replace(temporario, destino)
    finally:
        if os.path.exists(temporario):
            os.unlink(temporario)
