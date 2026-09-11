"""
Batimentos e saúde dos componentes: agendador, worker, fila e banco.

O sistema foi desenhado para trabalhar sozinho por horas — o que significa
que a pergunta mais importante da tela inicial não é "quantas notas tenho?",
e sim **"tem alguém lá dentro trabalhando?"**. Este módulo responde isso a
partir de duas fontes:

1. `batimentos_sistema` (tabela): tasks periódicas marcam o próprio passo;
   o envelhecimento do batimento do agendador revela um beat parado;
2. introspecção do Celery/Redis (quando acessível): responde se há algum
   worker respondendo `ping` agora.

Tudo degrada sem exceção: num ambiente de testes (sem Redis/Celery) o
componente volta como "desconhecido" — nunca derruba a tela do operador.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import BatimentoSistema

log = logging.getLogger("notasflow.batimento")

# Idade máxima aceitável para o batimento do agendador, em intervalos de
# varredura. O beat dispara a cada `sincronismo_intervalo_minutos`; três
# intervalos sem sinal = quase certamente parado (um atraso de fila é normal,
# três seguidos não).
_TOLERANCIA_INTERVALOS = 3

# Cache do ping do Redis: o painel inteiro é uma chamada só e atualiza a cada
# 30 s — dois pings por render seria desperdício, e um broker fora do ar
# responderia "Connection refused" devagar JUSTO quando a tela é mais urgente.
_CACHE_PING = {"quando": 0.0, "ok": False}
_CACHE_SEGUNDOS = 10.0


def registrar(db: Session, componente: str, detalhe: str | None = None) -> None:
    """Marca o passo de um componente (idempotente: uma linha por componente)."""
    try:
        batimento = db.get(BatimentoSistema, componente)
        agora = datetime.now(timezone.utc)
        if batimento is None:
            db.add(
                BatimentoSistema(componente=componente, visto_em=agora, detalhe=detalhe)
            )
        else:
            batimento.visto_em = agora
            batimento.detalhe = detalhe
        db.commit()
    except Exception as exc:  # noqa: BLE001 — batimento nunca pode derrubar a task
        db.rollback()
        log.warning("Não foi possível registrar batimento de %s: %s", componente, exc)


def ultimo(db: Session, componente: str) -> datetime | None:
    batimento = db.get(BatimentoSistema, componente)
    if batimento is None or batimento.visto_em is None:
        return None
    visto = batimento.visto_em
    if visto.tzinfo is None:
        visto = visto.replace(tzinfo=timezone.utc)
    return visto


def _ping_redis() -> bool:
    agora = time.monotonic()
    if agora - _CACHE_PING["quando"] < _CACHE_SEGUNDOS:
        return _CACHE_PING["ok"]
    ok = False
    try:
        import redis

        cliente = redis.Redis.from_url(settings.redis_url, socket_timeout=1.5)
        try:
            ok = bool(cliente.ping())
        finally:
            cliente.close()
    except Exception:  # noqa: BLE001
        ok = False
    _CACHE_PING.update(quando=agora, ok=ok)
    return ok


def _ping_workers() -> bool:
    """True se algum worker Celery responder ao ping (via broker Redis).

    Só vale a pena quando o broker responde: com o Redis fora do ar, o
    `control.ping` gasta segundos tentando conectar — e o estado do worker
    cai no batimento da última task, que é informação suficiente.
    """
    if not _ping_redis():
        return False
    try:
        from app.worker.celery_app import celery_app

        respostas = celery_app.control.ping(timeout=1.5)
        return bool(respostas)
    except Exception:  # noqa: BLE001
        return False


def situacao_agendador(db: Session) -> tuple[str, str]:
    """
    ("ok"|"atencao"|"erro"|"desligado"|"desconhecido", explicação).

    O agendador é o coração da automação: sem ele, nenhuma empresa é
    consultada e o operador só descobre quando nota que "nada novo chegou".
    """
    if not settings.sincronismo_automatico:
        return "desligado", "Sincronismo automático desligado nas configurações"

    visto = ultimo(db, "agendador")
    if visto is None:
        return "desconhecido", "Nenhuma varredura automática registrada ainda"

    idade = datetime.now(timezone.utc) - visto
    limite = timedelta(
        minutes=max(10, settings.sincronismo_intervalo_minutos * _TOLERANCIA_INTERVALOS)
    )
    if idade > limite:
        horas = idade.total_seconds() / 3600
        return (
            "erro",
            f"Sem varredura automática há {horas:.1f} h — verifique o contêiner do beat",
        )
    return "ok", f"Última varredura automática há {int(idade.total_seconds() // 60)} min"


def situacao_worker(db: Session) -> tuple[str, str]:
    """
    ("ok"|"erro"|"desconhecido", explicação).

    Prefere o ping ao vivo no broker (responde "tem worker agora"); se o
    broker não estiver acessível a partir da API (ex.: testes), usa o
    batimento da última task executada.
    """
    if _ping_workers():
        return "ok", "Respondendo no broker"
    visto = ultimo(db, "worker")
    if visto is None:
        return "desconhecido", "Sem contato com workers ainda"
    idade = datetime.now(timezone.utc) - visto
    if idade > timedelta(minutes=30):
        horas = idade.total_seconds() / 3600
        return "erro", f"Nenhum worker responde; última task há {horas:.1f} h"
    return "ok", f"Última task há {int(idade.total_seconds() // 60)} min"


def situacao_fila() -> tuple[str, str]:
    if _ping_redis():
        return "ok", "Fila Redis acessível"
    return "erro", "Redis não responde — filas e agendamentos parados"
