from sqlalchemy.orm import DeclarativeBase

from app.db.session import engine


class Base(DeclarativeBase):
    pass


def criar_tabelas() -> None:
    """
    MVP: cria as tabelas direto do modelo (sem histórico de migração).
    Funciona bem para uso interno de um único escritório.

    Ponto de troca para Alembic (recomendado antes de produção com dado real
    de cliente, ou antes de ter mais de uma pessoa alterando o schema ao
    mesmo tempo): trocar esta função por `alembic upgrade head` no
    entrypoint, e gerar a migração inicial com
    `alembic revision --autogenerate`. Ver docs/ARQUITETURA.md.
    """
    # Import aqui (não no topo) evita import circular: os modelos importam
    # Base deste módulo.
    from app import models  # noqa: F401

    # Os modelos do módulo Procurações RFB vivem em pacote próprio (fronteira
    # de domínio), mas compartilham o mesmo metadata — precisam ser importados
    # aqui para que create_all os enxergue.
    from app.procuracoes import modelos as modelos_procuracoes  # noqa: F401

    Base.metadata.create_all(bind=engine)
    # Colunas novas em tabelas que já existiam não aparecem no create_all;
    # o ALTER TABLE idempotente abaixo cobre bancos já populados.
    from app.db.migracoes import aplicar_migracoes

    aplicar_migracoes()
