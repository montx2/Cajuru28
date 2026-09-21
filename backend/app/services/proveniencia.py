"""Proveniência de documentos fiscais: de onde cada nota veio.

Um mesmo documento pode ser confirmado por mais de uma fonte oficial (por
exemplo, chegar pela distribuição do Ambiente Nacional e ser reconfirmado por
uma consulta pontual pela chave). O documento fiscal continua **único** no
acervo: o que se acumula é a lista de fontes que o confirmaram, nunca cópias
do XML.

Este módulo é deliberadamente independente de qualquer fornecedor: ele grava
apenas `documento_id + origem + identificador externo`, de forma idempotente,
para que reprocessar um lote jamais duplique a trilha de auditoria.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import DocumentoFiscalFonte


def _texto(valor: object, limite: int) -> str:
    """Normaliza para caber na coluna sem estourar o limite do banco."""
    return str(valor or "").strip()[:limite]


def inserir_sem_duplicar(
    db: Session,
    tabela,
    valores: dict[str, Any],
    *,
    constraint: str | None = None,
    index_elements: tuple[str, ...] = (),
) -> bool:
    """`INSERT ... ON CONFLICT DO NOTHING` portátil entre PostgreSQL e SQLite.

    Deixa o banco arbitrar a corrida entre dois workers em vez de consultar
    antes de inserir — consulta + insert perde a corrida e aborta a transação.
    """
    dialeto = db.get_bind().dialect.name
    if dialeto == "postgresql":
        comando = (
            postgresql_insert(tabela)
            .values(**valores)
            .on_conflict_do_nothing(constraint=constraint)
        )
    elif dialeto == "sqlite":
        comando = (
            sqlite_insert(tabela)
            .values(**valores)
            .on_conflict_do_nothing(index_elements=index_elements)
        )
    else:
        raise RuntimeError(f"Banco não suportado para inserção idempotente: {dialeto}.")
    return db.execute(comando).rowcount == 1


def registrar_proveniencia(
    db: Session, documento_id: int, origem: str, identificador_externo: str | None
) -> None:
    """Guarda uma confirmação de origem sem expor ou alterar o documento base."""
    inserir_sem_duplicar(
        db,
        DocumentoFiscalFonte.__table__,
        {
            "documento_id": documento_id,
            "origem": _texto(origem, 30),
            "identificador_externo": _texto(identificador_externo, 100),
        },
        constraint="uq_documento_fonte_identificador",
        index_elements=("documento_id", "origem", "identificador_externo"),
    )
