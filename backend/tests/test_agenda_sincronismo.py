"""SINCRONISMO_AUTOMATICO=false desagenda de verdade as tasks de consulta à SEFAZ.

O escritório que deixa outro sistema capturando (mesmo certificado = 656,
consumo indevido) precisa de um desligamento real: task rodando e retornando
cedo ainda aparece no log e ainda compete pela janela de consumo.
"""

import importlib

from app.core import config


def _agenda():
    from app.worker import celery_app as modulo

    return modulo, importlib.reload(modulo)


def test_desligado_as_tasks_da_sefaz_saiem_da_agenda(monkeypatch):
    monkeypatch.setattr(config.settings, "sincronismo_automatico", False)
    modulo, agenda = _agenda()
    try:
        assert "sincronizar-tudo" not in agenda.AGENDA
        assert "completar-xmls-pendentes" not in agenda.AGENDA
        # O que não é SEFAZ continua no ar.
        assert "varrer-alertas-webhook" in agenda.AGENDA
        assert "backup-diario" in agenda.AGENDA
    finally:
        monkeypatch.undo()
        importlib.reload(modulo)


def test_ligado_as_tasks_da_sefaz_estao_na_agenda():
    modulo, agenda = _agenda()
    importlib.reload(modulo)  # devolve o estado padrão aos demais testes
    assert "sincronizar-tudo" in modulo.AGENDA
    assert "completar-xmls-pendentes" in modulo.AGENDA
