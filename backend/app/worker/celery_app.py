"""
Configuração do Celery — e os dois detalhes que fazem a fila ser segura.

1. `visibility_timeout` maior que qualquer `countdown` que usamos. O broker Redis
   entrega de novo uma mensagem que ficou tempo demais "em voo": com o padrão
   (1h) um reagendamento de ~66 minutos viraria execução duplicada e, para a
   SEFAZ, duas consultas fora de sequência no mesmo CNPJ = bloqueio.

2. `acks_late` + limite de tempo de task: se o worker morrer no meio, a task
   volta para a fila e continua do checkpoint de NSU (nada é rebaixado).
"""

from datetime import timedelta

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "notasflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)

celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,  # se o worker cair no meio, a task volta para a fila
    worker_prefetch_multiplier=1,  # uma empresa por vez em cada slot: nada de
    # acumular 30 varreduras numa fila local enquanto o limite de consumo é
    # por CNPJ
    broker_transport_options={
        "visibility_timeout": int(settings.broker_visibility_timeout_segundos)
    },
    task_soft_time_limit=int(settings.limite_tempo_task_segundos),
    task_time_limit=int(settings.limite_tempo_task_segundos) + 60,
    result_expires=int(timedelta(days=7).total_seconds()),
    timezone="America/Sao_Paulo",
    enable_utc=True,
)

# O agendador é quem torna o processo autônomo. O tick é barato (não consulta
# nada: só decide e enfileira), então pode ser frequente — quem cadencia o
# ritmo de verdade são as janelas de consumo de 1h por empresa+tipo.
celery_app.conf.beat_schedule = {
    "sincronizar-tudo": {
        "task": "sincronizar_tudo",
        "schedule": timedelta(minutes=max(1, int(settings.sincronismo_intervalo_minutos))),
        "options": {"expires": int(settings.sincronismo_intervalo_minutos * 60)},
    },
    # Recupera os XMLs que chegaram só em resumo (consChNFe, 20 consultas/h).
    "completar-xmls-pendentes": {
        "task": "completar_xmls_pendentes",
        "schedule": timedelta(hours=max(1, int(settings.completar_xmls_a_cada_horas))),
        "options": {"expires": int(settings.completar_xmls_a_cada_horas * 3600)},
    },
}
