"""Relógio operacional e interpretação explícita do fuso fiscal brasileiro.

Datas fiscais sem offset (por exemplo, ``2026-09-19T08:30:00``) representam o
horário informado pelo emissor no Brasil; elas não podem ser silenciosamente
reinterpretadas como UTC. Já os instantes internos (leases, filas e auditoria)
continuam em UTC.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

FUSO_HORARIO_OPERACIONAL = ZoneInfo("America/Sao_Paulo")


def agora_operacional() -> datetime:
    """Agora no fuso usado pelo operador e pelos fechamentos fiscais."""
    return datetime.now(FUSO_HORARIO_OPERACIONAL)


def hoje_operacional() -> date:
    """Data de hoje em Brasília, nunca no fuso implícito do container."""
    return agora_operacional().date()


def inicio_do_dia_operacional_utc(referencia: datetime | None = None) -> datetime:
    """Meia-noite de Brasília convertida para UTC, útil em filtros SQL."""
    local = (referencia or agora_operacional()).astimezone(FUSO_HORARIO_OPERACIONAL)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def tornar_data_hora_fiscal_consciente(valor: datetime) -> datetime:
    """Preserva o relógio fiscal quando o XML não informou offset.

    Um timestamp já consciente é retornado sem alteração. Para os raros XMLs
    legados sem offset, o contrato operacional é America/Sao_Paulo, e não UTC.
    """
    return valor if valor.tzinfo is not None else valor.replace(tzinfo=FUSO_HORARIO_OPERACIONAL)


def data_operacional(valor: datetime | date | None) -> date | None:
    """Extrai a data civil brasileira de uma emissão persistida."""
    if isinstance(valor, datetime):
        if valor.tzinfo is not None:
            return valor.astimezone(FUSO_HORARIO_OPERACIONAL).date()
        # SQLite histórico não preserva o offset da coluna; manter a data que
        # foi gravada evita deslocar retroativamente documentos antigos.
        return valor.date()
    return valor if isinstance(valor, date) else None
