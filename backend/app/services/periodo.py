"""
Interpretação de "competência" — o mês que o contador pede.

Por que isto existe separado: a competência aparece em três lugares (o pedido
de importação, a listagem de documentos e o download em massa) e os três
precisam chegar exatamente no mesmo intervalo de datas. Um `date` de mês fecha
com o último dia *real* do mês (28/29/30/31) e com bissexto corretos, sem cada
chamada reimplementando a aritmética.

Formatos aceitos (todos muito usados na prática brasileira):

    08/2026   8-2026   2026-08   2026/08   ago/2026   082026   202608
    2026-08-20 (qualquer dia puxa o mês inteiro dele)
    intervalos explícitos: data_inicio / data_fim
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date

_MESES_ABREV = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4, "mai": 5, "jun": 6,
    "jul": 7, "ago": 8, "set": 9, "out": 10, "nov": 11, "dez": 12,
}
_MESES_COMPLETO = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

FORMATO = "MM/AAAA (ex.: 08/2026)"


class PeriodoInvalido(ValueError):
    """Erro de digitação — a mensagem vai direto para o operador na tela."""


@dataclass(frozen=True)
class Periodo:
    inicio: date | None = None
    fim: date | None = None

    @property
    def definido(self) -> bool:
        return self.inicio is not None or self.fim is not None

    def rotulo(self) -> str:
        if self.inicio and self.fim:
            ultimo_dia = calendar.monthrange(self.fim.year, self.fim.month)[1]
            if (
                self.inicio.day == 1
                and self.fim.day == ultimo_dia
                and (self.inicio.year, self.inicio.month) == (self.fim.year, self.fim.month)
            ):
                return f"{self.inicio.month:02d}/{self.inicio.year:04d}"
            return f"{self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y}"
        if self.inicio:
            return f"de {self.inicio:%d/%m/%Y}"
        if self.fim:
            return f"até {self.fim:%d/%m/%Y}"
        return "todos os períodos"

    def contem(self, valor: date | None) -> bool:
        if not self.definido or valor is None:
            return True
        if self.inicio and valor < self.inicio:
            return False
        if self.fim and valor > self.fim:
            return False
        return True


def _ultimo_dia(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _mes_numero(rotulo: str) -> int:
    texto = str(rotulo or "").strip().lower()
    if texto.isdigit():
        numero = int(texto)
        if not 1 <= numero <= 12:
            raise PeriodoInvalido(
                f"Mês inválido: {rotulo}. Use 01 a 12 — o formato esperado é {FORMATO}."
            )
        return numero
    chave = texto[:3]
    if chave in _MESES_ABREV:
        return _MESES_ABREV[chave]
    if texto in _MESES_COMPLETO:
        return _MESES_COMPLETO[texto]
    raise PeriodoInvalido(
        f"Mês inválido: {rotulo!r}. Use o número (08) ou o nome (ago) — {FORMATO}."
    )


def _normalizar_ano(rotulo: str) -> int:
    texto = str(rotulo or "").strip()
    if not texto:
        raise PeriodoInvalido(f"Ano faltando em {rotulo!r}. Use {FORMATO}.")
    if not texto.isdigit():
        raise PeriodoInvalido(f"Ano inválido: {rotulo!r}. Use {FORMATO}.")
    if len(texto) == 2:
        return 2000 + int(texto)
    if len(texto) == 4:
        return int(texto)
    raise PeriodoInvalido(f"Ano inválido: {rotulo!r}. Use {FORMATO}.")


def _validar(ano: int, mes: int, dia: int = 1) -> date:
    if not 1 <= mes <= 12:
        raise PeriodoInvalido(f"Mês inválido: {mes}. Use 01 a 12 — {FORMATO}.")
    if not 1900 <= ano <= 2200:
        raise PeriodoInvalido(f"Ano implausível: {ano}.")
    try:
        return date(ano, mes, dia)
    except ValueError as exc:
        raise PeriodoInvalido(f"Data inexistente: {ano:04d}-{mes:02d}-{dia:02d} ({exc}).") from exc


def interpretar_competencia(bruto: object) -> Periodo:
    """
    Um mês-calendário fechado (08/2026 → 01/08 a 31/08).

    Aceita `08/2026`, `8-2026`, `2026-08`, `ago/2026`, `082026`, `202608` e
    qualquer data completa (o mês dela é o que vale). Erro de digitação gera
    `PeriodoInvalido` com mensagem legível — nunca "mês 0" nem o mês anterior
    em silêncio.
    """
    texto = str(bruto or "").strip()
    if not texto:
        raise PeriodoInvalido(f"Competência vazia. Use o formato {FORMATO}.")

    # data completa (AAAA-MM-DD): o dia só serve para escolher o mês
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", texto):
        ano, mes, _ = (parte.strip() for parte in re.split(r"[-/.]", texto))
        return periodo_do_mes(int(ano), _mes_numero(mes))

    partes = [parte for parte in re.split(r"[^0-9A-Za-z]+", texto) if parte]

    if len(partes) == 1:
        bloco = partes[0]
        if not bloco.isdigit():  # "ago2026", "agosto"
            mes, ano = bloco[:3], bloco[3:]
            if not ano:
                raise PeriodoInvalido(
                    f"Competência '{texto}' sem ano. Use o formato {FORMATO}."
                )
        elif len(bloco) == 6:  # MMAAAA ou AAAAMM
            if 1990 <= int(bloco[:4]) <= 2100:
                ano, mes = bloco[:4], bloco[4:]
            else:
                mes, ano = bloco[:2], bloco[2:]
        elif len(bloco) == 4:  # MM/AA
            mes, ano = bloco[:2], bloco[2:]
        elif len(bloco) == 8:  # MMAAAAADDA ou AAAAMMDD (a data veio sem separador)
            if bloco[:4] > "1900":
                mes, ano = bloco[4:6], bloco[:4]
            else:
                mes, ano = bloco[:2], bloco[4:6]
        else:
            raise PeriodoInvalido(
                f"Competência '{texto}' não reconhecida. Use {FORMATO}."
            )
    elif len(partes) == 2:
        esquerda, direita = partes
        if len(esquerda) == 4 and esquerda.isdigit():  # AAAA-MM
            ano, mes = esquerda, direita
        else:  # MM/AAAA, MM-AAAA, ago/2026
            mes, ano = esquerda, direita
    else:
        raise PeriodoInvalido(
            f"Competência '{texto}' não reconhecida. Use {FORMATO}."
        )

    return periodo_do_mes(_normalizar_ano(ano), _mes_numero(mes))


def periodo_do_mes(ano: int, mes: int) -> Periodo:
    """Mês exato, com o último dia real (bissexto incluso)."""
    inicio = _validar(ano, mes, 1)
    return Periodo(inicio=inicio, fim=_ultimo_dia(ano, mes))


def interpretar_periodo(
    competencia: str | None = None,
    data_inicio: object = None,
    data_fim: object = None,
) -> Periodo:
    """
    A porta de entrada única: `competencia` (MM/AAAA) vence quando informada;
    senão usa o intervalo explícito. Sempre devolve um `Periodo` (possivelmente
    vazio = "sem filtro").
    """
    if competencia is not None and str(competencia).strip():
        return interpretar_competencia(competencia)

    inicio = _aceitar_data(data_inicio, "data_inicio")
    fim = _aceitar_data(data_fim, "data_fim")
    if inicio and fim and inicio > fim:
        raise PeriodoInvalido(
            f"data_inicio ({inicio:%d/%m/%Y}) é depois de data_fim ({fim:%d/%m/%Y})."
        )
    return Periodo(inicio=inicio, fim=fim)


def _aceitar_data(valor: object, nome: str) -> date | None:
    """Aceita `date`, string ISO ou None (a API recebe as duas formas)."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, date) and not hasattr(valor, "hour"):
        return valor
    texto = str(valor).strip()
    partes = re.split(r"[-/.]", texto[:10])
    if len(partes) != 3 or not all(parte.isdigit() for parte in partes):
        raise PeriodoInvalido(
            f"{nome} inválida: {texto!r}. Use o formato AAAA-MM-DD (ex.: 2026-08-01)."
        )
    return _validar(int(partes[0]), int(partes[1]), int(partes[2]))


def proxima_competencia(competencia: str) -> str:
    """`08/2026` → `09/2026` — usado pelo 'rodar o mês seguinte' da UI."""
    periodo = interpretar_competencia(competencia)
    assert periodo.inicio is not None
    ano, mes = periodo.inicio.year, periodo.inicio.month + 1
    if mes > 12:
        ano, mes = ano + 1, 1
    return periodo_do_mes(ano, mes).rotulo()
