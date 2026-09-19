"""Conversão única de valores monetários antes de persistência/relatórios."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

_CENTAVO = Decimal("0.01")


def valor_monetario(valor: object, *, padrao: float = 0.0) -> float:
    """Normaliza um valor para dois centavos sem cálculo binário acumulado.

    A coluna é NUMERIC(15,2), portanto este arredondamento também torna o
    comportamento idêntico entre importadores, PostgreSQL e SQLite.
    """
    if valor is None or isinstance(valor, bool):
        return padrao
    try:
        texto = str(valor).strip()
        if not texto:
            return padrao
        return float(Decimal(texto).quantize(_CENTAVO, rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return padrao
