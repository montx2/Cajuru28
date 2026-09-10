"""
Onde vive a fila — e a escolha entre os dois modos de execução.

Este módulo é o único ponto do sistema que sabe se a fila é **Celery + Redis**
(implantação em servidor) ou uma **fila em processo** (programa instalado em
cada computador). De resto, `app/worker/tasks.py`, `app/services/fila.py` e as
rotas da API usam exatamente a mesma interface (`@app.task`, `.delay()`,
`.apply_async(countdown=...)`, `conf.beat_schedule`) — e por isso não existe
código duplicado entre "versão web" e "versão .exe".

## Os dois detalhes que fazem a fila do servidor ser segura

1. `visibility_timeout` maior que qualquer `countdown` que usamos. O broker
   Redis entrega de novo uma mensagem que ficou tempo demais "em voo": com o
   padrão (1h) um reagendamento de ~66 minutos viraria execução duplicada e,
   para a SEFAZ, duas consultas fora de sequência no mesmo CNPJ = bloqueio.

2. `acks_late` + limite de tempo de task: se o worker morrer no meio, a task
   volta para a fila e continua do checkpoint de NSU (nada é rebaixado).

## Por que o modo desktop não tem broker

A segurança da fila aqui **não vem do broker**: cursor de NSU, janela de
consumo, lease e checkpoint moram no banco (ver `app/services/sincronizacao.py`).
Uma fila que reinicia não perde nota — só para de disparar até voltar. Isso é o
que permite trocar Redis+Celery por threads quando o programa roda na máquina
do usuário, onde instalar e manter um Redis seria um absurdo operacional.
"""

from datetime import timedelta

from app.core.config import settings

# O agendador é quem torna o processo autônomo. O tick é barato (não consulta
# nada: só decide e enfileira), então pode ser frequente — quem cadencia o
# ritmo de verdade são as janelas de consumo de 1h por empresa+tipo.
#
# Fica fora do `if` de propósito: nos dois modos a agenda é a mesma, e é isto
# que garante que o programa instalado se comporte como o servidor.
AGENDA = {
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


if settings.modo_desktop:
    # ---------- Programa instalado: fila em processo ----------
    from app.desktop.fila_local import MiniCelery

    celery_app = MiniCelery(concorrencia=settings.notasflow_concorrencia)
    # `include=["app.worker.tasks"]` não existe aqui: as tarefas se registram no
    # import do módulo, e o `main.py` já o importa (via routers) antes de a fila
    # subir. O agendador espera `atraso_inicial_segundos` antes do primeiro tick.
    celery_app.conf.atraso_inicial_segundos = 20
else:
    # ---------- Servidor: Celery + Redis ----------
    from celery import Celery

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

celery_app.conf.beat_schedule = AGENDA
