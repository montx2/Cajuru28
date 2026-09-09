"""
Migrações leves para bancos criados antes deste schema.

O projeto usa `create_all` (sem Alembic): tabelas NOVAS são criadas
automaticamente, mas colunas novas em tabelas existentes não. Este módulo
adiciona essas colunas com `ALTER TABLE ... ADD COLUMN` de forma idempotente
para PostgreSQL e SQLite, e é chamado no startup (`app.db.base.criar_tabelas`)
— assim quem já tem dados não precisa rodar SQL manual nem recriar o banco.
"""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

from app.db.session import engine

log = logging.getLogger("notasflow.migracoes")

# Colunas novas por tabela: (nome, tipo SQL)
_COLUNAS_POR_TABELA: dict[str, list[tuple[str, str]]] = {
    "documentos_fiscais": [
        ("status", "VARCHAR(20) NOT NULL DEFAULT 'normal'"),
        ("motivo_cancelamento", "TEXT"),
        ("cancelado_em", "TIMESTAMP WITH TIME ZONE"),
    ],
    "execucoes_importacao": [
        ("documentos_cancelados", "INTEGER NOT NULL DEFAULT 0"),
        ("eventos_nao_reconhecidos", "INTEGER NOT NULL DEFAULT 0"),
        ("aviso", "TEXT"),
    ],
}


def _colunas_existentes(tabela: str) -> set[str]:
    inspetor = inspect(engine)
    if inspetor.has_table(tabela):
        return {coluna["name"] for coluna in inspetor.get_columns(tabela)}
    return set()


def _tipo_para_dialeto(tipo_sql: str) -> str:
    if engine.dialect.name == "sqlite":
        return tipo_sql.replace("TIMESTAMP WITH TIME ZONE", "DATETIME")
    return tipo_sql


def aplicar_migracoes() -> None:
    """Adiciona colunas faltantes nas tabelas existentes (idempotente)."""
    for tabela, colunas in _COLUNAS_POR_TABELA.items():
        existentes = _colunas_existentes(tabela)
        for nome, tipo_sql in colunas:
            if nome in existentes:
                continue
            tipo = _tipo_para_dialeto(tipo_sql)
            if engine.dialect.name in ("postgresql",):
                try:
                    with engine.begin() as conexao:
                        conexao.execute(
                            text(f"ALTER TABLE {tabela} ADD COLUMN IF NOT EXISTS {nome} {tipo}")
                        )
                except Exception as exc:  # noqa: BLE001
                    log.warning("Migração: falha ao adicionar %s.%s — %s", tabela, nome, exc)
                    raise
                log.info("Migração: coluna %s.%s adicionada", tabela, nome)
                continue

            # SQLite: ALTER TABLE ADD COLUMN simples; a existência já foi
            # checada acima, e dois workers subindo juntos são inofensivos
            # (a segunda tentativa apenas vê a coluna já criada).
            try:
                with engine.begin() as conexao:
                    conexao.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {nome} {tipo}"))
                log.info("Migração: coluna %s.%s adicionada", tabela, nome)
            except Exception:  # noqa: BLE001
                if nome not in _colunas_existentes(tabela):
                    raise
