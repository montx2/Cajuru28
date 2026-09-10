"""
Alertas externos via webhook: POST JSON para Slack, Discord, n8n ou qualquer
gateway (ex.: WhatsApp).

Deduplicação: o mesmo alerta (`escritorio:id`) não é reenviado dentro da
janela de cooldown. O estado mora no Redis quando disponível, com fallback
para memória do processo (reiniciar o beat pode repetir um envio — aceitável
para um fallback).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core.config import settings

_PESO_NIVEL = {"critico": 0, "atencao": 1, "info": 2}
_memoria: dict[str, datetime] = {}


def nivel_vale(nivel: str, minimo: str) -> bool:
    """`critico` passa em qualquer mínimo; `info` só passa com mínimo `info`."""
    return _PESO_NIVEL.get((nivel or "").lower(), 9) <= _PESO_NIVEL.get(
        (minimo or "").lower(), 1
    )


def _redis():
    try:
        import redis

        cliente = redis.Redis.from_url(settings.redis_url, socket_timeout=2)
        cliente.ping()
        return cliente
    except Exception:  # noqa: BLE001 — sem Redis, usa memória
        return None


def ja_enviado_recente(chave: str, cooldown_minutos: int) -> bool:
    agora = datetime.now(timezone.utc)
    cliente = _redis()
    if cliente is not None:
        try:
            return cliente.exists(f"notasflow:{chave}") == 1
        except Exception:  # noqa: BLE001
            pass
    ultimo = _memoria.get(chave)
    if ultimo is None:
        return False
    if ultimo.tzinfo is None:
        ultimo = ultimo.replace(tzinfo=timezone.utc)
    return agora - ultimo < timedelta(minutes=max(1, cooldown_minutos))


def marcar_enviado(chave: str, cooldown_minutos: int) -> None:
    agora = datetime.now(timezone.utc)
    _memoria[chave] = agora
    cliente = _redis()
    if cliente is not None:
        try:
            cliente.set(
                f"notasflow:{chave}", agora.isoformat(),
                ex=max(60, cooldown_minutos * 60),
            )
        except Exception:  # noqa: BLE001
            pass


def montar_payload(alerta: dict, *, escritorio_id: int | None = None) -> dict:
    return {
        "origem": "notasflow",
        "id": alerta.get("id"),
        "nivel": alerta.get("nivel"),
        "categoria": alerta.get("categoria"),
        "titulo": alerta.get("titulo"),
        "detalhe": alerta.get("detalhe"),
        "empresa": alerta.get("empresa_razao_social"),
        "acao": {
            "rotulo": alerta.get("acao_rotulo"),
            "href": alerta.get("acao_href"),
        },
        "escritorio_id": escritorio_id,
        "hora": datetime.now(timezone.utc).isoformat(),
    }


def disparar(alerta: dict, *, escritorio_id: int | None = None) -> tuple[bool, str]:
    """Envia um alerta ao webhook configurado. Retorna (ok, detalhe)."""
    url = (settings.alerta_webhook_url or "").strip()
    if not url:
        return False, "Webhook não configurado (ALERTA_WEBHOOK_URL vazia)."
    try:
        import httpx

        resposta = httpx.post(
            url, json=montar_payload(alerta, escritorio_id=escritorio_id), timeout=10.0
        )
        if 200 <= resposta.status_code < 300:
            return True, f"Enviado (HTTP {resposta.status_code})."
        return False, f"Webhook respondeu HTTP {resposta.status_code}: {resposta.text[:200]}"
    except Exception as exc:  # noqa: BLE001 — diagnóstico vai para o operador
        return False, f"Falha ao enviar: {str(exc)[:200]}"
