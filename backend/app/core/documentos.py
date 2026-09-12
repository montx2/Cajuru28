"""Identificadores fiscais brasileiros sem perda de informação.

Desde 2026 novos CNPJs podem conter letras. Um CNPJ é um identificador, não um
número: remover caracteres não numéricos transforma uma empresa em outra. As
funções deste módulo preservam o valor canônico (14 caracteres, maiúsculos e
sem máscara) e mantêm CPF como identificador estritamente numérico.
"""

from __future__ import annotations

import re

# Pontos, barras, hífens e espaços são somente máscara. Qualquer outro símbolo
# é recusado em vez de ser apagado silenciosamente.
_MASCARA = re.compile(r"[.\-/\s]")
_APENAS_ALFANUMERICO = re.compile(r"^[A-Z0-9]+$")


def normalizar_identificador(valor: str | None) -> str:
    """Remove apenas máscara visual e retorna um identificador em maiúsculas."""
    texto = _MASCARA.sub("", str(valor or "").strip()).upper()
    if not texto or not _APENAS_ALFANUMERICO.fullmatch(texto):
        raise ValueError("Documento deve conter somente letras, números e máscara de CNPJ/CPF.")
    return texto


def normalizar_cnpj(valor: str | None) -> str:
    """CNPJ canônico: 12 posições alfanuméricas seguidas de dois DVs numéricos."""
    documento = normalizar_identificador(valor)
    if len(documento) != 14 or not documento[-2:].isdigit():
        raise ValueError("CNPJ deve ter 14 caracteres, com os dois dígitos verificadores numéricos.")
    return documento


def normalizar_cpf(valor: str | None) -> str:
    documento = normalizar_identificador(valor)
    if len(documento) != 11 or not documento.isdigit():
        raise ValueError("CPF deve ter 11 dígitos.")
    return documento


def normalizar_documento(valor: str | None) -> str:
    """Normaliza CPF ou CNPJ, sem validar DV para não quebrar cadastros legados."""
    documento = normalizar_identificador(valor)
    if len(documento) == 11 and documento.isdigit():
        return documento
    if len(documento) == 14 and documento[-2:].isdigit():
        return documento
    raise ValueError("Informe CPF de 11 dígitos ou CNPJ de 14 caracteres.")


def eh_cnpj(valor: str | None) -> bool:
    try:
        normalizar_cnpj(valor)
        return True
    except ValueError:
        return False


def eh_cnpj_numerico(valor: str | None) -> bool:
    try:
        return normalizar_cnpj(valor).isdigit()
    except ValueError:
        return False


def _valor_dv(caractere: str) -> int:
    """Regra RFB: valor ASCII do caractere menos 48 (A=17, B=18 etc.)."""
    return ord(caractere) - 48


def _digito_cnpj(base: str) -> int:
    pesos = (
        [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
        if len(base) == 12
        else [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    )
    soma = sum(_valor_dv(caractere) * peso for caractere, peso in zip(base, pesos))
    resto = soma % 11
    return 0 if resto < 2 else 11 - resto


def validar_cnpj(valor: str | None) -> bool:
    try:
        cnpj = normalizar_cnpj(valor)
    except ValueError:
        return False
    # Continua recusando sequência puramente numérica artificial, sem bloquear
    # combinações alfanuméricas legítimas que possam se repetir visualmente.
    if cnpj.isdigit() and len(set(cnpj)) == 1:
        return False
    return _digito_cnpj(cnpj[:12]) == int(cnpj[12]) and _digito_cnpj(cnpj[:13]) == int(cnpj[13])


def validar_cpf(valor: str | None) -> bool:
    try:
        cpf = normalizar_cpf(valor)
    except ValueError:
        return False
    if len(set(cpf)) == 1:
        return False
    for base, digito in ((cpf[:9], cpf[9]), (cpf[:10], cpf[10])):
        soma = sum(int(d) * p for d, p in zip(base, range(len(base) + 1, 1, -1)))
        resto = soma % 11
        esperado = 0 if resto < 2 else 11 - resto
        if esperado != int(digito):
            return False
    return True


def validar_documento(valor: str | None) -> bool:
    try:
        documento = normalizar_documento(valor)
    except ValueError:
        return False
    return validar_cpf(documento) if len(documento) == 11 else validar_cnpj(documento)
