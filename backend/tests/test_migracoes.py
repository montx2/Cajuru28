"""Migrações leves: colunas novas são adicionadas em banco já existente."""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.db import migracoes


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

    # Rodar de novo não quebra nem duplica
    migracoes.aplicar_migracoes()
    colunas_docs2 = {c["name"] for c in inspect(engine).get_columns("documentos_fiscais")}
    assert colunas_docs2 == colunas_docs
