"""
A data que decide se um documento está *dentro do período pedido*.

Por que um módulo só para isto: o recorte por período aparece em muitos
lugares (listagem, resumo, por-empresa, ZIP, CSV, fechamento, dashboard,
painel e a gravação no worker). Enquanto cada lugar tinha a sua própria
expressão, a mesma nota podia aparecer em agosto numa tela e em julho na
outra — e o operador via "o filtro não funciona", com razão.

A regra, única e explícita: **vale a data de emissão do documento**. É a data
que o contador confere, a que aparece no XML de todo tipo de documento e a
única que existe sempre (a competência declarada é opcional e vem em branco
numa parte relevante das NFS-e).
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func

from app.models import DocumentoFiscal


def data_referencia_sql():
    """
    Expressão SQL da data de referência, para filtros e agrupamentos.

    `date()` se comporta igual em PostgreSQL e SQLite, então o filtro não muda
    de resultado conforme o banco.
    """
    return func.date(DocumentoFiscal.data_emissao)


def data_referencia(documento: DocumentoFiscal) -> date | None:
    """Versão Python da mesma regra — usada quando já temos o objeto na mão."""
    valor = getattr(documento, "data_emissao", None)
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return None
