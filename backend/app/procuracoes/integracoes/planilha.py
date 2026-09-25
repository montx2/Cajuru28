"""
Fonte por planilha — o caminho que funciona no primeiro dia.

Enquanto o contrato de API da Jettax360 (ou o do Integra Contador) não estiver
disponível, o escritório já exporta a relação de clientes e a situação das
procurações em CSV/XLSX. Esta fonte transforma esse arquivo em dado
governado, com as mesmas regras de idempotência e histórico das demais.

Não é um atalho descartável: é a fonte que mantém o módulo utilizável sem
depender de terceiro, e continua servindo de plano B quando a API cair.

Formato aceito (cabeçalho obrigatório, ordem livre, acentos e maiúsculas
irrelevantes)::

    cnpj;razao_social;situacao;data_inicio;data_validade;protocolo;servicos

`situacao` aceita o vocabulário do portal (`ativa`, `em análise`,
`aguardando aceite`, `expirada`, `cancelada`, `sem autorização`) ou vazio —
vazio com validade futura vira `ativa`, vazio sem validade vira
`sem_autorizacao`.
"""

from __future__ import annotations

import csv
import io
import unicodedata
from datetime import date, datetime
from typing import Iterable

from app.procuracoes.estados import StatusAutorizacao
from app.procuracoes.integracoes.base import (
    FonteError,
    RegistroProcuracao,
    ServicoAutorizado,
    situacao_por_validade,
)

LIMITE_BYTES = 8 * 1024 * 1024
LIMITE_LINHAS = 20000

_ALIAS_COLUNAS: dict[str, str] = {
    "cnpj": "documento",
    "cpf": "documento",
    "cnpj_cpf": "documento",
    "documento": "documento",
    "identificador": "documento",
    "razao_social": "razao_social",
    "razao": "razao_social",
    "nome": "razao_social",
    "cliente": "razao_social",
    "situacao": "situacao",
    "status": "situacao",
    "situacao_procuracao": "situacao",
    "status_da_procuracao": "situacao",
    "data_inicio": "data_inicio",
    "inicio": "data_inicio",
    "data_validade": "data_validade",
    "validade": "data_validade",
    "vencimento": "data_validade",
    "protocolo": "protocolo",
    "servicos": "servicos",
}

_ALIAS_SITUACAO: dict[str, StatusAutorizacao] = {
    "ativa": StatusAutorizacao.ATIVA,
    "ativo": StatusAutorizacao.ATIVA,
    "vigente": StatusAutorizacao.ATIVA,
    "em analise": StatusAutorizacao.EM_ANALISE,
    "analise": StatusAutorizacao.EM_ANALISE,
    "aguardando aceite": StatusAutorizacao.AGUARDANDO_ACEITE,
    "aguardando validacao": StatusAutorizacao.AGUARDANDO_ACEITE,
    "expirada": StatusAutorizacao.EXPIRADA,
    "expirado": StatusAutorizacao.EXPIRADA,
    "vencida": StatusAutorizacao.EXPIRADA,
    "cancelada": StatusAutorizacao.CANCELADA,
    "cancelado": StatusAutorizacao.CANCELADA,
    "rejeitada": StatusAutorizacao.REJEITADA,
    "sem autorizacao": StatusAutorizacao.SEM_AUTORIZACAO,
    "sem procuracao": StatusAutorizacao.SEM_AUTORIZACAO,
    "nao possui": StatusAutorizacao.SEM_AUTORIZACAO,
}


def _chave(texto: str) -> str:
    sem_acento = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", str(texto or ""))
        if not unicodedata.combining(ch)
    )
    return "_".join(sem_acento.strip().lower().replace("-", " ").replace("/", " ").split())


class FontePlanilha:
    """Fonte de leitura única, alimentada por um arquivo já carregado."""

    nome = "planilha"

    def __init__(self, conteudo: bytes, *, nome_arquivo: str = "planilha.csv"):
        if not conteudo:
            raise FonteError("Arquivo vazio.", status_code=422)
        if len(conteudo) > LIMITE_BYTES:
            raise FonteError(
                f"Arquivo acima do limite de {LIMITE_BYTES // (1024 * 1024)} MiB.",
                status_code=413,
            )
        self.conteudo = conteudo
        self.nome_arquivo = nome_arquivo

    def testar(self) -> str:
        registros = self.listar()
        return f"{len(registros)} linha(s) válida(s) reconhecida(s) em {self.nome_arquivo}."

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        texto = self._decodificar()
        dialeto = self._dialeto(texto)
        leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)
        if not leitor.fieldnames:
            raise FonteError("A planilha não tem cabeçalho.", status_code=422)

        colunas = {}
        for original in leitor.fieldnames:
            interno = _ALIAS_COLUNAS.get(_chave(original))
            if interno and interno not in colunas:
                colunas[interno] = original
        if "documento" not in colunas:
            raise FonteError(
                "A planilha precisa de uma coluna de CNPJ/CPF "
                "(aceito: cnpj, cpf, cnpj_cpf, documento, identificador).",
                status_code=422,
            )

        filtro = {d for d in (documentos or []) if d}
        registros: list[RegistroProcuracao] = []
        vistos: set[str] = set()
        for indice, linha in enumerate(leitor):
            if indice >= LIMITE_LINHAS:
                raise FonteError(
                    f"A planilha excede {LIMITE_LINHAS} linhas.", status_code=413
                )
            bruto = str(linha.get(colunas["documento"]) or "").strip()
            if not bruto:
                continue
            validade = _data(self._valor(linha, colunas, "data_validade"))
            situacao_texto = self._valor(linha, colunas, "situacao")
            registro = RegistroProcuracao(
                documento=bruto,
                razao_social=self._valor(linha, colunas, "razao_social"),
                situacao=self._situacao(situacao_texto, validade),
                data_inicio=_data(self._valor(linha, colunas, "data_inicio")),
                data_validade=validade,
                protocolo=self._valor(linha, colunas, "protocolo"),
                servicos=self._servicos(self._valor(linha, colunas, "servicos")),
                observacao=situacao_texto,
            )
            try:
                normalizado = registro.normalizado()
            except ValueError:
                continue
            if filtro and normalizado.documento not in filtro:
                continue
            if normalizado.documento in vistos:
                continue
            vistos.add(normalizado.documento)
            registros.append(normalizado)
        return registros

    def _decodificar(self) -> str:
        for codificacao in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                return self.conteudo.decode(codificacao)
            except UnicodeDecodeError:
                continue
        raise FonteError(
            "Não foi possível ler o arquivo como texto. Exporte em CSV UTF-8.",
            status_code=422,
        )

    @staticmethod
    def _dialeto(texto: str) -> csv.Dialect:
        amostra = texto[:8192]
        try:
            return csv.Sniffer().sniff(amostra, delimiters=";,\t|")
        except csv.Error:
            class Padrao(csv.excel):
                delimiter = ";" if amostra.count(";") >= amostra.count(",") else ","

            return Padrao()

    @staticmethod
    def _valor(linha: dict, colunas: dict, campo: str) -> str:
        coluna = colunas.get(campo)
        if not coluna:
            return ""
        return str(linha.get(coluna) or "").strip()

    @staticmethod
    def _situacao(texto: str, validade: date | None) -> StatusAutorizacao:
        alvo = _ALIAS_SITUACAO.get(_chave(texto).replace("_", " "))
        if alvo is None:
            return situacao_por_validade(validade, ativa=bool(validade))
        if alvo is StatusAutorizacao.ATIVA and validade and validade < date.today():
            return StatusAutorizacao.EXPIRADA
        return alvo

    @staticmethod
    def _servicos(texto: str) -> tuple[ServicoAutorizado, ...]:
        if not texto:
            return ()
        if texto.strip().upper() in {"ALL", "TODOS", "TODOS OS SERVICOS"}:
            return (ServicoAutorizado(codigo="ALL", rotulo="Todos os serviços"),)
        partes = [p.strip() for p in texto.replace("|", ",").split(",") if p.strip()]
        return tuple(
            ServicoAutorizado(codigo=parte[:120], rotulo=parte[:255]) for parte in partes[:200]
        )


def _data(valor: str) -> date | None:
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None
