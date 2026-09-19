"""Logging estruturado, com correlação por requisição sem registrar segredos."""

from __future__ import annotations

import contextvars
import json
import logging
import logging.config
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings

request_id_atual: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id_atual", default=""
)


class FormatadorJson(logging.Formatter):
    """Linha JSON estável para API, worker e agregadores de log."""

    def format(self, record: logging.LogRecord) -> str:
        evento: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "nivel": record.levelname,
            "logger": record.name,
            "mensagem": record.getMessage(),
        }
        correlacao = request_id_atual.get()
        if correlacao:
            evento["request_id"] = correlacao
        if record.exc_info:
            evento["excecao"] = self.formatException(record.exc_info)
        return json.dumps(evento, ensure_ascii=False, default=str)


def configurar_logging() -> None:
    """Configura handlers uma vez por processo, preservando loggers de libs."""
    nivel = (settings.log_level or "INFO").upper()
    formato = "json" if settings.log_json else "texto"
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "json": {"()": "app.core.logging.FormatadorJson"},
                "texto": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": formato,
                    "stream": "ext://sys.stdout",
                },
            },
            "root": {"handlers": ["console"], "level": nivel},
            "loggers": {
                "uvicorn.access": {"handlers": ["console"], "level": "INFO", "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": nivel, "propagate": False},
                "celery": {"handlers": ["console"], "level": nivel, "propagate": False},
            },
        }
    )
