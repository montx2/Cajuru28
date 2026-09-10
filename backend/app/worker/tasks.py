"""
Tasks de importação — agora são wrappers finos sobre app.worker.executor.

Mantém compatibilidade com Celery (modo Docker) e permite uso direto em
threads locais (modo Desktop .exe).
"""

import logging

from app.core.config import settings
from app.db.session import SessionLocal as _OriginalSessionLocal
from app.worker.celery_app import celery_app
from app.worker.executor import (
    executar_completar_xmls,
    executar_importacao,
    executar_sincronizacao_automatica,
    # Re-exportar funções internas para compatibilidade com testes antigos
    _gravar_documento,
    _processar_evento,
    _aplicar_eventos_pendentes,
    _normalizar_chave,
    _inserir_documento_sem_duplicar,
    _parse_data,
    _parse_data_emissao,
    _parse_data_evento,
    _resumir_avisos,
    _marcar_erro,
    _marcar_aguardando,
    _resolver_nsu_inicial,
    fila_periodo,
    tratar_consumo_indevido,
    tratar_ambiente_indisponivel,
)
from app.worker.executor import fila_reagendar as _executor_fila_reagendar

log = logging.getLogger("notasflow.worker")

# SessionLocal exposto para monkeypatch nos testes
SessionLocal = _OriginalSessionLocal

# fila_reagendar exposto para monkeypatch nos testes
def fila_reagendar(db, execucao, quando, *, motivo):
    # Se foi monkeypatched nos testes, o executor vai detectar via _get_fila_reagendar
    # Mas também precisamos de uma implementação que possa ser mockada diretamente aqui
    return _executor_fila_reagendar(db, execucao, quando, motivo=motivo)


@celery_app.task(name="importar_documentos", bind=True, max_retries=0)
def importar_documentos(self, empresa_id: int, tipo: str, execucao_id: int, tentativa: int = 0) -> None:
    executar_importacao(empresa_id, tipo, execucao_id, tentativa)


@celery_app.task(name="sincronizar_tudo", bind=True, max_retries=0)
def sincronizar_tudo(self) -> dict:
    return executar_sincronizacao_automatica()


@celery_app.task(name="completar_xmls_pendentes", bind=True, max_retries=0)
def completar_xmls_pendentes(self, empresa_id: int | None = None, limite: int | None = None) -> dict:
    return executar_completar_xmls(empresa_id=empresa_id, limite=limite)


# Aliases para uso direto sem Celery (modo desktop)
def importar_documentos_sync(empresa_id: int, tipo: str, execucao_id: int, tentativa: int = 0) -> None:
    executar_importacao(empresa_id, tipo, execucao_id, tentativa)


def sincronizar_tudo_sync() -> dict:
    return executar_sincronizacao_automatica()


def completar_xmls_pendentes_sync(empresa_id: int | None = None, limite: int | None = None) -> dict:
    return executar_completar_xmls(empresa_id=empresa_id, limite=limite)


# Manter compatibilidade: testes antigos importam diretamente de tasks
__all__ = [
    "importar_documentos",
    "sincronizar_tudo",
    "completar_xmls_pendentes",
    "_gravar_documento",
    "_processar_evento",
    "_aplicar_eventos_pendentes",
]
