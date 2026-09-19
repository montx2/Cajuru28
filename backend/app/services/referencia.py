"""A data que decide se um documento está *dentro do período pedido*.

A regra é única e explícita: vale a data de emissão do documento, interpretada
no fuso operacional brasileiro. Isso evita que um documento emitido depois das
21h seja deslocado para o dia seguinte apenas porque PostgreSQL roda em UTC.
"""

from __future__ import annotations

from datetime import date, datetime

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
    """Expressão SQL portável da data fiscal de emissão."""
    return _DataFiscalSql(DocumentoFiscal.data_emissao)


def data_referencia(documento: DocumentoFiscal) -> date | None:
    """Versão Python da mesma regra — usada quando o objeto já está em mãos."""
    valor = getattr(documento, "data_emissao", None)
    return data_operacional(valor)
