"""Rate limiting compartilhado por Redis, com fallback apenas fora de produção."""

from __future__ import annotations

import hashlib
import time
from collections import defaultdict
from threading import Lock

from fastapi import HTTPException, Request, status

from app.core.config import settings

_memoria: dict[str, tuple[int, float]] = {}
_lock = Lock()
_redis = None
_redis_indisponivel = False


def _cliente_ip(request: Request) -> str:
    # A produção só expõe o Caddy; ele substitui X-Forwarded-For antes de
    # encaminhar. Em desenvolvimento o endereço direto é suficiente.
    encaminhado = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return encaminhado or (request.client.host if request.client else "desconhecido")


def _chave(escopo: str, request: Request) -> str:
    material = f"{escopo}:{_cliente_ip(request)}".encode()
    # Não persiste IP literal no Redis; a chave não precisa ser reversível.
    digest = hashlib.sha256(material).hexdigest()
    return f"notasflow:rl:{escopo}:{digest}"


def _obter_redis():
    global _redis, _redis_indisponivel
    if _redis_indisponivel:
        return None
    if _redis is None:
        try:
            import redis

            _redis = redis.Redis.from_url(
                settings.redis_url, socket_connect_timeout=0.3, socket_timeout=0.5
            )
        except Exception:  # pragma: no cover - import/configuração inválida
            _redis_indisponivel = True
            return None
    try:
        _redis.ping()
        return _redis
    except Exception:
        _redis_indisponivel = True
        return None


def _consumir_local(chave: str, limite: int, janela_segundos: int) -> bool:
    agora = time.monotonic()
    with _lock:
        usados, inicio = _memoria.get(chave, (0, agora))
        if agora - inicio >= janela_segundos:
            usados, inicio = 0, agora
        usados += 1
        _memoria[chave] = (usados, inicio)
        return usados <= limite


def consumir(request: Request, *, escopo: str, limite: int, janela_segundos: int) -> None:
    """Consome uma cota ou retorna 429; em produção Redis fora do ar = 503."""
    if not settings.rate_limit_ativo or settings.app_env == "test":
        return
    chave = _chave(escopo, request)
    cliente = _obter_redis()
    if cliente is not None:
        try:
            usados = int(cliente.incr(chave))
            if usados == 1:
                cliente.expire(chave, janela_segundos)
            permitido = usados <= limite
        except Exception:
            permitido = False
            if settings.em_producao:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Proteção de acesso temporariamente indisponível.",
                )
            permitido = _consumir_local(chave, limite, janela_segundos)
    elif settings.em_producao:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Proteção de acesso temporariamente indisponível.",
        )
    else:
        permitido = _consumir_local(chave, limite, janela_segundos)

    if not permitido:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Muitas tentativas. Aguarde antes de tentar novamente.",
            headers={"Retry-After": str(janela_segundos)},
        )


def limitar_login(request: Request) -> None:
    consumir(
        request,
        escopo="login-minuto",
        limite=max(1, settings.rate_limit_login_por_minuto),
        janela_segundos=60,
    )
    consumir(
        request,
        escopo="login-hora",
        limite=max(1, settings.rate_limit_login_por_hora),
        janela_segundos=3600,
    )


def limitar_mutacao(request: Request) -> None:
    consumir(
        request,
        escopo="mutacoes",
        limite=max(1, settings.rate_limit_mutacoes_por_minuto),
        janela_segundos=60,
    )
