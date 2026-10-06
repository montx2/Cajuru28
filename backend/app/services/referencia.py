"""A data que decide se um documento está *dentro do período pedido*.

A regra contábil e fiscal é a competência do documento (o mês/período fiscal a que
se refere o serviço ou operação). Se a competência não estiver preenchida (por exemplo,
em documentos legados sem metadados específicos), utiliza-se como fallback a data
de emissão interpretada no fuso operacional brasileiro.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import GenericFunction
from sqlalchemy.types import Date

from app.core.tempo import data_operacional
from app.models import DocumentoFiscal


class _DataFiscalSql(GenericFunction):
    """Data civil da emissão, compilada para cada banco suportado."""

    type = Date()
    inherit_cache = True


@compiles(_DataFiscalSql, "postgresql")
def _compilar_data_fiscal_postgresql(element, compiler, **kwargs) -> str:
    coluna = compiler.process(list(element.clauses)[0], **kwargs)
    return f"DATE(timezone('America/Sao_Paulo', {coluna}))"


@compiles(_DataFiscalSql, "sqlite")
def _compilar_data_fiscal_sqlite(element, compiler, **kwargs) -> str:
    coluna = compiler.process(list(element.clauses)[0], **kwargs)
    # SQLite de testes não guarda offset de TIMESTAMP WITH TIME ZONE; os dados
    # foram gravados com a data fiscal já preservada, portanto date() é a forma
    # estável e equivalente nesta plataforma.
    return f"date({coluna})"


@compiles(_DataFiscalSql)
def _compilar_data_fiscal_generico(element, compiler, **kwargs) -> str:
    coluna = compiler.process(list(element.clauses)[0], **kwargs)
    return f"DATE({coluna})"


def data_referencia_sql():
    """Expressão SQL portável da data de referência fiscal (competência com fallback para emissão)."""
    return func.coalesce(DocumentoFiscal.competencia, _DataFiscalSql(DocumentoFiscal.data_emissao))


def data_referencia(documento: DocumentoFiscal) -> date | None:
    """Versão Python da mesma regra — usada quando o objeto já está em mãos."""
    comp = getattr(documento, "competencia", None)
    if comp is not None:
        if isinstance(comp, datetime):
            return comp.date()
        if isinstance(comp, date):
            return comp
    valor = getattr(documento, "data_emissao", None)
    return data_operacional(valor)
