"""Configuração da fila Celery e do agendador executados pelo Docker Compose."""

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

AGENDA = {
    "sincronizar-tudo": {
        "task": "sincronizar_tudo",
        "schedule": timedelta(minutes=max(1, int(settings.sincronismo_intervalo_minutos))),
        "options": {"expires": int(settings.sincronismo_intervalo_minutos * 60)},
    },
    "completar-xmls-pendentes": {
        "task": "completar_xmls_pendentes",
        "schedule": timedelta(hours=max(1, int(settings.completar_xmls_a_cada_horas))),
        "options": {"expires": int(settings.completar_xmls_a_cada_horas * 3600)},
    },
    "varrer-alertas-webhook": {
        "task": "varrer_alertas_webhook",
        "schedule": timedelta(minutes=max(1, int(settings.alerta_webhook_intervalo_minutos))),
        "options": {"expires": int(settings.alerta_webhook_intervalo_minutos * 60)},
    },
    # Backup diário no horário morto (fuso do beat = America/Sao_Paulo).
    "backup-diario": {
        "task": "backup_agendado",
        "schedule": crontab(hour=int(settings.backup_hora), minute=0),
    },
}

celery_app = Celery(
    "notasflow",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.worker.tasks"],
)
celery_app.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    broker_transport_options={
        "visibility_timeout": int(settings.broker_visibility_timeout_segundos)
    },
    task_soft_time_limit=int(settings.limite_tempo_task_segundos),
    task_time_limit=int(settings.limite_tempo_task_segundos) + 60,
    result_expires=int(timedelta(days=7).total_seconds()),
    timezone="America/Sao_Paulo",
    enable_utc=True,
    beat_schedule=AGENDA,
)
