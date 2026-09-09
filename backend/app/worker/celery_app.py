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
    worker_prefetch_multiplier=1,
)
