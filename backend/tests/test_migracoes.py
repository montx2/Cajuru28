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


def test_manifestacao_automatica_e_ligada_no_sqlite_de_quem_ja_existia(monkeypatch):
    """Banco antigo (default FALSE) precisa sair do boot com a chave ligada.

    Sem isso, quem já tinha a coluna ficava com o valor antigo — e nota tomada
    nenhuma era manifestada, ou seja, o XML completo nunca era liberado.
    """
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "CREATE TABLE empresas ("
                "id INTEGER PRIMARY KEY, razao_social TEXT, "
                "manifestar_automaticamente BOOLEAN NOT NULL DEFAULT FALSE)"
            )
        )
        conexao.execute(
            text("INSERT INTO empresas (id, razao_social, manifestar_automaticamente) VALUES (1, 'A', 0)")
        )
        # Quem desligou depois da migração também está gravado como 0 — a
        # migração não tem como distinguir; é por isso que ela só roda enquanto
        # o DEFAULT da coluna ainda é o antigo.
    monkeypatch.setattr(migracoes, "engine", engine)

    migracoes._habilitar_manifestacao_automatica_padrao()

    with engine.begin() as conexao:
        assert conexao.execute(text("SELECT manifestar_automaticamente FROM empresas")).scalar() in (1, True)


def test_manifestacao_automatica_nao_atropela_default_novo(monkeypatch):
    """Coluna já com DEFAULT TRUE: a migração não toca em nada (é idempotente)."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conexao:
        conexao.execute(
            text(
                "CREATE TABLE empresas ("
                "id INTEGER PRIMARY KEY, razao_social TEXT, "
                "manifestar_automaticamente BOOLEAN NOT NULL DEFAULT TRUE)"
            )
        )
        conexao.execute(
            text("INSERT INTO empresas (id, razao_social, manifestar_automaticamente) VALUES (1, 'A', 0)")
        )
    monkeypatch.setattr(migracoes, "engine", engine)

    migracoes._habilitar_manifestacao_automatica_padrao()

    with engine.begin() as conexao:
        assert conexao.execute(text("SELECT manifestar_automaticamente FROM empresas")).scalar() in (0, False)
