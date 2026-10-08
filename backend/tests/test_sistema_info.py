import pytest

from app.api.routers import sistema
from app.core.config import settings


@pytest.mark.parametrize(
    ("ambiente", "database_url", "modo", "banco", "desktop", "servidor"),
    [
        ("development", "sqlite:////tmp/fluxa.db", "Desenvolvimento", "SQLite", True, False),
        ("production", "postgresql://fluxa:segredo@db/fluxa", "Produção", "PostgreSQL", False, True),
    ],
)
def test_info_retrata_ambiente_e_banco_ativos(
    monkeypatch, ambiente, database_url, modo, banco, desktop, servidor
):
    monkeypatch.setattr(settings, "app_env", ambiente)
    monkeypatch.setattr(settings, "database_url", database_url)
    monkeypatch.setattr(settings, "dados_dir", "/tmp/fluxa-dados")
    monkeypatch.setattr(settings, "alerta_webhook_url", "")
    monkeypatch.setattr(settings, "alerta_webhook_min_nivel", "atencao")
    monkeypatch.setattr(settings, "alerta_webhook_intervalo_minutos", 15)
    monkeypatch.setattr(
        sistema.celery_app.conf,
        "beat_schedule",
        {
            "varrer-alertas-webhook": {"task": "varrer_alertas_webhook"},
            "backup-diario": {"task": "backup_agendado"},
            "sincronizar-tudo": {"task": "sincronizar_tudo"},
            "completar-xmls-pendentes": {"task": "completar_xmls_pendentes"},
            "rotina-interna": {"task": "app.worker.tasks.rotina_interna"},
        },
    )

    dados = sistema.informacao_do_sistema(_usuario=None)

    assert dados["modo"] == modo
    assert dados["banco"] == banco
    assert dados["modo_desktop"] is desktop
    assert dados["modo_servidor"] is servidor
    assert set(dados["fila"]["agenda"]) == {
        "Alertas externos",
        "Backup diário",
        "Captura fiscal automática",
        "XMLs pendentes",
        "Outra rotina 5",
    }
    tarefas = [item["tarefa"] for item in dados["fila"]["agenda"].values()]
    assert "Enviar alertas configurados" in tarefas
    assert "Criar backup diário" in tarefas
    assert "Consultar documentos fiscais" in tarefas
    assert "Completar XMLs fiscais" in tarefas
    assert "app.worker.tasks.rotina_interna" not in repr(dados)
    assert "varrer_alertas_webhook" not in repr(dados)
