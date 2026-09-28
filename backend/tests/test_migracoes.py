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


def test_migracao_apaga_credenciais_jettax_e_e_idempotente(monkeypatch):
    """A integração por API do Jettax foi removida do produto: segredo que não
    se usa não fica no cofre. A limpeza é idempotente e não toca nas demais."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "CREATE TABLE procuracao_credenciais_integracao ("
                "id INTEGER PRIMARY KEY, escritorio_id INTEGER, fonte TEXT,"
                "segredo_cifrado TEXT)"
            )
        )
        conexao.execute(
            text(
                "INSERT INTO procuracao_credenciais_integracao "
                "(escritorio_id, fonte, segredo_cifrado) VALUES "
                "(1, 'jettax360', 'segredo-antigo'),"
                "(1, 'integra_contador', 'segredo-oficial')"
            )
        )

    monkeypatch.setattr(migracoes, "engine", engine)
    migracoes.aplicar_migracoes()

    with engine.begin() as conexao:
        fontes = [
            linha[0]
            for linha in conexao.execute(
                text("SELECT fonte FROM procuracao_credenciais_integracao")
            )
        ]
    assert fontes == ["integra_contador"]

    # Rodar de novo não falha nem apaga o que ficou.
    migracoes.aplicar_migracoes()
    with engine.begin() as conexao:
        fontes = [
            linha[0]
            for linha in conexao.execute(
                text("SELECT fonte FROM procuracao_credenciais_integracao")
            )
        ]
    assert fontes == ["integra_contador"]
