"""Concordância de número nas frases que o operador lê.

O backend escrevia `f"{total} documento(s)"` — o mesmo vício que o frontend
tinha em `plural()`. A tela mostrava "1 documento(s)": parênteses de
programador no meio de uma frase em português. Aqui a frase sai certa e o
número aparece uma vez só.
"""

from __future__ import annotations


def plural(quantidade: int, singular: str, plurals: str | None = None) -> str:
    """Só a palavra: "documento" / "documentos"."""
    return singular if quantidade == 1 else (plurals or singular + "s")


def contagem(quantidade: int, singular: str, plurals: str | None = None) -> str:
    """Número + palavra: "1 documento" / "12 documentos"."""
    return f"{quantidade} {plural(quantidade, singular, plurals)}"
