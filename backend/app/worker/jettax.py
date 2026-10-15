"""Uma tarefa por empresa; nenhum token ou link é enviado ao broker."""
from datetime import datetime, timezone
import time

import redis
from billiard.exceptions import SoftTimeLimitExceeded

from app.core.config import settings
from app.core.vault import decifrar_segredo
from app.db.session import SessionLocal
from app.models import JettaxCredencial, JettaxExecucao
from app.services.importadores.jettax_nfse import ResultadoJettax, importar_nfse
from app.services.jettax import ClienteJettax, JettaxErro
from app.worker.celery_app import celery_app


def _agora():
    return datetime.now(timezone.utc)


@celery_app.task(name="importar_jettax_nfse", bind=True, max_retries=0)
def importar_jettax_nfse(self, execucao_id: int, escritorio_id: int):
    db = SessionLocal()
    trava = None
    adquirida = False
    iniciada = False
    resultado = ResultadoJettax()
    try:
        execucao = db.query(JettaxExecucao).filter_by(id=execucao_id, escritorio_id=escritorio_id).first()
        if execucao is None or execucao.status != "pendente":
            return
        redis_cliente = redis.Redis.from_url(settings.redis_url, socket_timeout=3, socket_connect_timeout=3)
        chave_espera = f"jettax:espera:{escritorio_id}"
        if redis_cliente.exists(chave_espera):
            raise JettaxErro("Jettax em pausa após limite de requisições; aguarde uma hora antes de executar novamente.", 429)
        # Todos os lotes do mesmo escritório compartilham a cadência do token.
        trava = redis_cliente.lock(f"jettax:escritorio:{escritorio_id}",
                                   timeout=settings.limite_tempo_task_segundos + 90, blocking_timeout=0)
        adquirida = trava.acquire(blocking=False)
        if not adquirida:
            self.apply_async(kwargs={"execucao_id": execucao_id, "escritorio_id": escritorio_id}, countdown=30, retry=False)
            return
        if redis_cliente.exists(chave_espera):
            raise JettaxErro("Jettax em pausa após limite de requisições; aguarde uma hora antes de executar novamente.", 429)
        # Compare-and-set evita redelivery da mesma execução em dois workers.
        iniciada = db.query(JettaxExecucao).filter_by(id=execucao_id, escritorio_id=escritorio_id, status="pendente").update(
            {"status": "em_andamento", "iniciado_em": _agora()}, synchronize_session=False) == 1
        db.commit()
        if not iniciada:
            return
        credencial = db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).first()
        if credencial is None:
            raise JettaxErro("Configure o token Jettax antes de importar.", 409)
        cliente = ClienteJettax(credencial.base_url, decifrar_segredo(credencial.token_cifrado),
                               timeout=settings.jettax_timeout_segundos,
                               intervalo=max(0.5, settings.jettax_intervalo_segundos),
                               max_paginas=settings.jettax_max_paginas)
        def progresso(atual):
            db.query(JettaxExecucao).filter_by(id=execucao_id, escritorio_id=escritorio_id).update(
                {"resultado": atual.dados()}, synchronize_session=False)
            db.commit()
        importar_nfse(db, cliente, escritorio_id, execucao.empresa_id, execucao.competencia, resultado, progresso)
        if resultado.empresa_ausente_jettax:
            status, mensagem = "ignorada", "Empresa não cadastrada no Jettax: nenhuma nota consultada."
        elif resultado.erros or resultado.sem_empresa:
            status, mensagem = "parcial", "Consulta terminou com documentos pendentes. Confira as contagens e execute novamente."
        else:
            status, mensagem = "concluida", "Consulta Jettax concluída. As contagens se referem às cópias por empresa, não garantem completude da captura na origem."
        db.query(JettaxCredencial).filter_by(escritorio_id=escritorio_id).update(
            {"ultima_sincronizacao_em": _agora()}, synchronize_session=False)
        _finalizar(db, execucao_id, escritorio_id, status, mensagem, resultado)
    except JettaxErro as exc:
        db.rollback()
        if exc.status_code == 429 and iniciada:
            try:
                redis_cliente.setex(f"jettax:espera:{escritorio_id}", 3600, "1")
            except Exception:
                pass
        _finalizar(db, execucao_id, escritorio_id, "parcial" if resultado.recebidos else "erro", str(exc), resultado)
    except SoftTimeLimitExceeded:
        db.rollback()
        _finalizar(db, execucao_id, escritorio_id, "parcial", "Tempo máximo atingido. Execute novamente para retomar sem duplicar notas.", resultado)
    except Exception:
        db.rollback()
        _finalizar(db, execucao_id, escritorio_id, "erro", "Falha local ao importar Jettax. Verifique cofre, banco, fila e worker; execute novamente.", resultado)
    finally:
        if adquirida and trava is not None:
            try:
                if iniciada:
                    time.sleep(max(0.5, settings.jettax_intervalo_segundos))
                trava.release()
            except Exception:
                pass
        db.close()


def _finalizar(db, execucao_id, escritorio_id, status, mensagem, resultado):
    db.query(JettaxExecucao).filter_by(id=execucao_id, escritorio_id=escritorio_id).update(
        {"status": status, "mensagem": mensagem, "resultado": resultado.dados(), "finalizado_em": _agora()},
        synchronize_session=False,
    )
    db.commit()
