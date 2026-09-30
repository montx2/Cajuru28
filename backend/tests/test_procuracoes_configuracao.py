"""Regras do modelo padrão de Autorização de Acesso."""

from datetime import date

from app.procuracoes.servicos.configuracao import _mais_cinco_anos


def test_vigencia_de_cinco_anos_preserva_o_dia_do_mes():
    assert _mais_cinco_anos(date(2026, 9, 30)) == date(2031, 9, 30)


def test_vigencia_de_cinco_anos_trata_29_de_fevereiro():
    assert _mais_cinco_anos(date(2024, 2, 29)) == date(2029, 2, 28)
