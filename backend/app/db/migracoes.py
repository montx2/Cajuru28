"""
Migrações leves para bancos criados antes deste schema.

O projeto usa `create_all` (sem Alembic): tabelas NOVAS são criadas
automaticamente, mas colunas novas em tabelas existentes não. Este módulo
adiciona essas colunas com `ALTER TABLE ... ADD COLUMN` de forma idempotente
para PostgreSQL e SQLite, e é chamado no startup (`app.db.base.criar_tabelas`)
— assim quem já tem dados não precisa rodar SQL manual nem recriar o banco.

Ele também cuida de duas coisas que `create_all` nunca faria sozinho:

1. **valor novo de enum no PostgreSQL** (`StatusExecucao.AGUARDANDO`): no PG o
   enum é um tipo próprio, então é preciso `ALTER TYPE ... ADD VALUE`.
2. **carregar o estado de sincronização** a partir do histórico de execuções,
   para que quem já vinha importando não volte ao NSU zero — voltar ao zero é
   justamente o que faz a SEFAZ responder "Consumo Indevido".
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
        ("competencia", "DATE"),
        ("leiaute", "VARCHAR(12) NOT NULL DEFAULT 'completo'"),
        ("numero", "VARCHAR(20)"),
        ("serie", "VARCHAR(10)"),
        ("emitente_documento", "VARCHAR(18)"),
        ("emitente_nome", "VARCHAR(255)"),
        ("destinatario_documento", "VARCHAR(18)"),
        ("destinatario_nome", "VARCHAR(255)"),
        ("situacao", "VARCHAR(255)"),
        ("origem", "VARCHAR(20)"),
    ],
    "execucoes_importacao": [
        ("documentos_cancelados", "INTEGER NOT NULL DEFAULT 0"),
        ("eventos_nao_reconhecidos", "INTEGER NOT NULL DEFAULT 0"),
        ("aviso", "TEXT"),
        ("data_inicio", "DATE"),
        ("data_fim", "DATE"),
        ("documentos_no_periodo", "INTEGER NOT NULL DEFAULT 0"),
        ("tentativas", "INTEGER NOT NULL DEFAULT 0"),
        ("bloqueado_ate", "TIMESTAMP WITH TIME ZONE"),
        ("origem", "VARCHAR(20) NOT NULL DEFAULT 'manual'"),
        # PostgreSQL não aceita inteiros como valor padrão de BOOLEAN
        # (`DEFAULT 0` derruba o startup em bancos de versões anteriores).
        # TRUE/FALSE também são compreendidos pelo SQLite.
        ("forcar", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ],
    "empresas": [
        ("sincronizar_automaticamente", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("quais_tipos_sincronizar", "VARCHAR(30) NOT NULL DEFAULT 'nfse,nfe,cte'"),
        ("codigo_ibge", "VARCHAR(7)"),
        ("inscricao_municipal", "VARCHAR(100)"),
    ],
    "usuarios": [
        ("papel", "VARCHAR(20) NOT NULL DEFAULT 'admin'"),
    ],
    "certificados": [
        # Telemetria de uso do A1 — alimenta o centro de certificados.
        ("ultima_utilizacao_em", "TIMESTAMP WITH TIME ZONE"),
        ("ultima_validacao_em", "TIMESTAMP WITH TIME ZONE"),
        ("ultimo_erro", "TEXT"),
    ],
}

# Índices que as telas de filtro por competência/download em massa usam.
_INDICES: list[tuple[str, str]] = [
    ("ix_documentos_competencia", "CREATE INDEX IF NOT EXISTS ix_documentos_competencia ON documentos_fiscais (competencia)"),
    ("ix_documentos_empresa_competencia", "CREATE INDEX IF NOT EXISTS ix_documentos_empresa_competencia ON documentos_fiscais (empresa_id, competencia)"),
    ("ix_documentos_tipo_competencia", "CREATE INDEX IF NOT EXISTS ix_documentos_tipo_competencia ON documentos_fiscais (tipo, competencia)"),
    ("ix_documentos_empresa_tipo", "CREATE INDEX IF NOT EXISTS ix_documentos_empresa_tipo ON documentos_fiscais (empresa_id, tipo)"),
    ("ix_documentos_emitente", "CREATE INDEX IF NOT EXISTS ix_documentos_emitente ON documentos_fiscais (emitente_documento)"),
    ("ix_execucoes_empresa_tipo_status", "CREATE INDEX IF NOT EXISTS ix_execucoes_empresa_tipo_status ON execucoes_importacao (empresa_id, tipo, status)"),
    ("ix_sincronizacao_empresa_tipo", "CREATE UNIQUE INDEX IF NOT EXISTS ix_sincronizacao_empresa_tipo ON sincronizacoes_dfe (empresa_id, tipo)"),
    ("ix_jettax_execucao_empresa_status", "CREATE INDEX IF NOT EXISTS ix_jettax_execucao_empresa_status ON jettax_execucoes (empresa_id, status)"),
    ("ix_jettax_webhook_ticket", "CREATE INDEX IF NOT EXISTS ix_jettax_webhook_ticket ON jettax_webhook_eventos (ticket)"),
]

# `ALTER TYPE` só faz sentido no PostgreSQL (SQLite guarda enum como texto).
#
# IMPORTANTE: o valor aqui precisa ser o *nome* do membro do Enum Python
# (ex.: "AGUARDANDO"), não o `.value` ("aguardando"). O SQLAlchemy, ao mapear
# um `enum.Enum` para uma coluna `Enum` nativa do PostgreSQL, grava e lê pelo
# `.name` do membro por padrão (a menos que `values_callable` seja usado, o
# que este projeto não faz). Usar o `.value` minúsculo aqui criava um rótulo
# que o SQLAlchemy nunca consultava, e toda leitura/escrita de
# `StatusExecucao.AGUARDANDO` falhava com
# `invalid input value for enum statusexecucao: "AGUARDANDO"`.
_TIPOS_ENUM_POR_TABELA: dict[str, str] = {
    "statusexecucao": "AGUARDANDO",
}


def _colunas_existentes(tabela: str) -> set[str]:
    inspetor = inspect(engine)
    if inspetor.has_table(tabela):
        return {coluna["name"] for coluna in inspetor.get_columns(tabela)}
    return set()


def _tipo_para_dialeto(tipo_sql: str) -> str:
    if engine.dialect.name == "sqlite":
        return (
            tipo_sql.replace("TIMESTAMP WITH TIME ZONE", "DATETIME")
            .replace(" DATE", " DATE")
        )
    return tipo_sql


def aplicar_migracoes() -> None:
    """Adiciona colunas, valores de enum, índices e semeadora de estado (idempotente)."""
    _garantir_valores_enum()

    for tabela, colunas in _COLUNAS_POR_TABELA.items():
        existentes = _colunas_existentes(tabela)
        if not existentes:
            continue
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

    _criar_indices()
    _preencher_competencia_faltante()
    _semear_sincronizacoes()


def _garantir_valores_enum() -> None:
    """
    PostgreSQL: enums são tipos próprios, e um valor novo no modelo não aparece
    sozinho no banco. `ALTER TYPE ... ADD VALUE IF NOT EXISTS` resolve.

    Roda em conexão dedicada e fora de transação: no PG, adicionar valor de
    enum e *usá-lo* na mesma transação é proibido, e a API e os workers podem
    subir exatamente quando isso é necessário.
    """
    if engine.dialect.name != "postgresql":
        return
    for tipo, valor in _TIPOS_ENUM_POR_TABELA.items():
        try:
            with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conexao:
                conexao.execute(
                    text(f"ALTER TYPE {tipo} ADD VALUE IF NOT EXISTS '{valor}'")
                )
            log.info("Migração: valor '%s' garantido no tipo %s", valor, tipo)
        except Exception as exc:  # noqa: BLE001 — tipo pode não existir ainda
            log.info("Migração: ALTER TYPE %s ignorado (%s)", tipo, exc)


def _criar_indices() -> None:
    for nome, comando in _INDICES:
        try:
            with engine.begin() as conexao:
                conexao.execute(text(comando))
        except Exception as exc:  # noqa: BLE001 — índice existente/sem tabela
            log.info("Migração: índice %s ignorado (%s)", nome, exc)


def _preencher_competencia_faltante() -> None:
    """
    Documentos anteriores a esta versão têm `competencia` nula. Sem backfill, o
    filtro "08/2026" deixaria justamente as notas antigas de fora — o pior
    resultado possível para quem atualiza um sistema já em uso.

    Fallback: a data de emissão é a melhor estimativa de competência que
    existe, e é o que o próprio leiaute nacional usa quando o documento não
    declara `dComp`/`PeriodoRef`. Um único UPDATE no banco, sem passar por
    Python — a tabela pode ter centenas de milhares de linhas.
    """
    existentes = _colunas_existentes("documentos_fiscais")
    if not {"competencia", "data_emissao"} <= existentes:
        return

    if engine.dialect.name == "postgresql":
        comando = text(
            "UPDATE documentos_fiscais "
            "SET competencia = date_trunc('month', data_emissao)::date "
            "WHERE competencia IS NULL AND data_emissao IS NOT NULL"
        )
    elif engine.dialect.name == "sqlite":
        comando = text(
            "UPDATE documentos_fiscais "
            "SET competencia = date(substr(data_emissao, 1, 7) || '-01') "
            "WHERE competencia IS NULL AND data_emissao IS NOT NULL"
        )
    else:
        return

    try:
        with engine.begin() as conexao:
            resultado = conexao.execute(comando)
        if resultado.rowcount:
            log.info("Migração: competência preenchida em %d documento(s)", resultado.rowcount)
    except Exception as exc:  # noqa: BLE001 — backfill não pode derrubar o startup
        log.warning("Migração: backfill de competência pulado (%s)", exc)


def _semear_sincronizacoes() -> None:
    """
    Cria o estado de sincronização das empresas que já importavam, carregando o
    maior NSU já visto por empresa+tipo.

    Sem isso, a primeira execução depois do upgrade consultaria a partir do 0 —
    e consultar fora da sequência é a regra nº 2 de uso indevido da SEFAZ.

    Usa a ORM (e não INSERT cru) de propósito: os `default=` do modelo e a
    conversão do enum `tipo` só acontecem por esse caminho.
    """
    from sqlalchemy.orm import sessionmaker

    from app.models import Empresa, ExecucaoImportacao, SincronizacaoDFe

    if not _colunas_existentes("sincronizacoes_dfe"):
        return  # tabela criada no mesmo boot: nada a semear ainda
    if not {"empresa_id", "tipo", "ultimo_nsu"} <= _colunas_existentes("execucoes_importacao"):
        return

    sessao = sessionmaker(bind=engine)()
    criados = 0
    try:
        empresas = {linha[0] for linha in sessao.query(Empresa.id).all()}
        existentes = {
            (estado.empresa_id, estado.tipo)
            for estado in sessao.query(SincronizacaoDFe).all()
        }

        maiores: dict[tuple[int, object], int] = {}
        consulta = sessao.query(
            ExecucaoImportacao.empresa_id,
            ExecucaoImportacao.tipo,
            ExecucaoImportacao.ultimo_nsu,
        ).filter(ExecucaoImportacao.ultimo_nsu.isnot(None))
        for empresa_id, tipo, ultimo_nsu in consulta.all():
            if empresa_id not in empresas:
                continue
            digitos = "".join(c for c in str(ultimo_nsu or "") if c.isdigit())
            if not digitos:
                continue
            chave = (empresa_id, tipo)
            maiores[chave] = max(maiores.get(chave, 0), int(digitos))

        for (empresa_id, tipo), nsu in maiores.items():
            if (empresa_id, tipo) in existentes:
                continue
            sessao.add(
                SincronizacaoDFe(empresa_id=empresa_id, tipo=tipo, ultimo_nsu=str(nsu))
            )
            criados += 1
        sessao.commit()
    except Exception as exc:  # noqa: BLE001 — semeadura não pode derrubar o startup
        sessao.rollback()
        log.warning("Migração: semeadura de sincronização pulada (%s)", exc)
    finally:
        sessao.close()

    if criados:
        log.info(
            "Migração: %d estado(s) de sincronização criado(s) a partir do histórico", criados
        )
