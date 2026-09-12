"""Migrações leves: colunas novas são adicionadas em banco já existente."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.db import migracoes


def test_defaults_booleanos_sao_validos_no_postgresql():
    """PostgreSQL não converte DEFAULT 0/1 implicitamente para BOOLEAN."""
    tipos = dict(migracoes._COLUNAS_POR_TABELA["execucoes_importacao"])
    tipos.update(migracoes._COLUNAS_POR_TABELA["empresas"])

    assert tipos["forcar"].endswith("DEFAULT FALSE")
    assert tipos["sincronizar_automaticamente"].endswith("DEFAULT TRUE")


def test_adiciona_colunas_faltantes_e_e_idempotente(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "CREATE TABLE documentos_fiscais ("
                "id INTEGER PRIMARY KEY, chave_acesso TEXT)"
            )
        )
        conexao.execute(
            text(
                "CREATE TABLE execucoes_importacao ("
                "id INTEGER PRIMARY KEY, documentos_importados INTEGER)"
            )
        )
        conexao.execute(
            text("CREATE TABLE empresas (id INTEGER PRIMARY KEY, razao_social TEXT)")
        )

    monkeypatch.setattr(migracoes, "engine", engine)
    migracoes.aplicar_migracoes()

    colunas_docs = {c["name"] for c in inspect(engine).get_columns("documentos_fiscais")}
    assert {"status", "motivo_cancelamento", "cancelado_em"} <= colunas_docs

    colunas_exec = {c["name"] for c in inspect(engine).get_columns("execucoes_importacao")}
    assert {
        "documentos_cancelados",
        "eventos_nao_reconhecidos",
        "aviso",
    } <= colunas_exec
    colunas_empresas = {c["name"] for c in inspect(engine).get_columns("empresas")}
    assert {"codigo_ibge", "inscricao_municipal"} <= colunas_empresas

    # Rodar de novo não quebra nem duplica
    migracoes.aplicar_migracoes()
    colunas_docs2 = {c["name"] for c in inspect(engine).get_columns("documentos_fiscais")}
    assert colunas_docs2 == colunas_docs
