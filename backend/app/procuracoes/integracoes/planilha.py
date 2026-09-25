"""
Fontes de texto — o caminho que funciona no primeiro dia, e sem credencial.

Duas entradas, o mesmo destino:

``FontePlanilha``
    CSV/TSV **com cabeçalho**. É o formato de quem exporta de um ERP ou
    monta a relação na mão.

``FonteColagem``
    Texto **colado da tela**, sem cabeçalho confiável. Nasceu do caso real do
    painel do Jettax 360 (*Prevenção → e-CAC → Procurações*), em que cada
    cliente aparece com o nome numa linha e o CNPJ/CPF logo abaixo, a lista é
    paginada (``?page=N``) e dividida em abas (``&tab=N``) — de modo que a
    importação chega em pedaços, com cabeçalho e paginação no meio.

Ambas devolvem ``RegistroProcuracao`` normalizado, então a reconciliação, a
idempotência, a precedência entre fontes e o histórico em
``procuracao_integracao_jobs`` são exatamente os mesmos das integrações por
API. Não é atalho descartável: é a fonte que mantém o módulo utilizável sem
depender de terceiro, e o plano B de quando a API cair.

Formato do CSV (cabeçalho obrigatório, ordem livre, acentos e maiúsculas
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
import re
import unicodedata
from datetime import date, datetime
from typing import Iterable

from app.core.documentos import normalizar_documento, validar_documento
from app.procuracoes.estados import StatusAutorizacao
from app.procuracoes.integracoes.base import (
    FonteError,
    RegistroProcuracao,
    ServicoAutorizado,
    situacao_por_validade,
)

LIMITE_BYTES = 8 * 1024 * 1024
LIMITE_LINHAS = 20000
#: Teto do texto colado. Uma carteira grande (milhares de linhas) cabe folgado;
#: acima disso é colagem acidental de página inteira.
LIMITE_CARACTERES_COLAGEM = 2 * 1024 * 1024

_ALIAS_COLUNAS: dict[str, str] = {
    "cnpj": "documento",
    "cpf": "documento",
    "cnpj_cpf": "documento",
    "cpf_cnpj": "documento",
    "documento": "documento",
    "identificador": "documento",
    "razao_social": "razao_social",
    "razao": "razao_social",
    "nome": "razao_social",
    "empresa": "razao_social",
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

#: Desempate quando duas colunas do arquivo apontam para o mesmo campo interno.
#: Menor peso ganha. O caso concreto: no painel do Jettax a coluna **EMPRESA**
#: é o nome do cliente e **CLIENTE** é um "Sim/Não" (se o CNPJ é cliente da
#: plataforma). Sem o desempate, um export com as duas colunas poderia gravar
#: "Sim" como razão social.
_PESO_ALIAS: dict[str, int] = {
    "razao_social": 0,
    "razao": 0,
    "empresa": 1,
    "nome": 2,
    "cliente": 9,
}

_ALIAS_SITUACAO: dict[str, StatusAutorizacao] = {
    "ativa": StatusAutorizacao.ATIVA,
    "ativo": StatusAutorizacao.ATIVA,
    "vigente": StatusAutorizacao.ATIVA,
    # Vocabulário da coluna SITUAÇÃO do painel do Jettax: "Válida" / "Expirado".
    "valida": StatusAutorizacao.ATIVA,
    "valido": StatusAutorizacao.ATIVA,
    "na validade": StatusAutorizacao.ATIVA,
    "no prazo": StatusAutorizacao.ATIVA,
    "dentro do prazo": StatusAutorizacao.ATIVA,
    "regular": StatusAutorizacao.ATIVA,
    "vencido": StatusAutorizacao.EXPIRADA,
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

    def __init__(
        self,
        conteudo: bytes,
        *,
        nome_arquivo: str = "planilha.csv",
        situacao_padrao: StatusAutorizacao | None = None,
    ):
        if not conteudo:
            raise FonteError("Arquivo vazio.", status_code=422)
        if len(conteudo) > LIMITE_BYTES:
            raise FonteError(
                f"Arquivo acima do limite de {LIMITE_BYTES // (1024 * 1024)} MiB.",
                status_code=413,
            )
        self.conteudo = conteudo
        self.nome_arquivo = nome_arquivo
        #: Aba declarada pelo operador: vale para as linhas cuja coluna
        #: situação veio vazia. A linha continua mandando mais que a declaração.
        self.situacao_padrao = situacao_padrao
    def testar(self) -> str:
        registros = self.listar()
        return f"{len(registros)} linha(s) válida(s) reconhecida(s) em {self.nome_arquivo}."

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        texto = self._decodificar()
        dialeto = self._dialeto(texto)
        leitor = csv.DictReader(io.StringIO(texto), dialect=dialeto)
        if not leitor.fieldnames:
            raise FonteError("A planilha não tem cabeçalho.", status_code=422)

        colunas: dict[str, str] = {}
        pesos: dict[str, int] = {}
        for original in leitor.fieldnames:
            chave = _chave(original)
            interno = _ALIAS_COLUNAS.get(chave)
            if not interno:
                continue
            peso = _PESO_ALIAS.get(chave, 5)
            if interno not in colunas or peso < pesos[interno]:
                colunas[interno] = original
                pesos[interno] = peso
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
        return decodificar(self.conteudo)

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

    def _situacao(self, texto: str, validade: date | None) -> StatusAutorizacao:
        alvo = _ALIAS_SITUACAO.get(_chave(texto).replace("_", " "))
        if alvo is None:
            if not texto and self.situacao_padrao is not None:
                return self.situacao_padrao
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


def decodificar(conteudo: bytes) -> str:
    """Bytes → texto, tentando as codificações que aparecem de verdade."""
    for codificacao in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return conteudo.decode(codificacao)
        except UnicodeDecodeError:
            continue
    raise FonteError(
        "Não foi possível ler o arquivo como texto. Exporte em CSV UTF-8.",
        status_code=422,
    )


# ---------------------------------------------------------------------------
# Colagem de tela
# ---------------------------------------------------------------------------

#: CNPJ (numérico ou alfanumérico, com ou sem máscara) e CPF. Os dois últimos
#: caracteres do CNPJ são sempre numéricos — é o que separa um CNPJ
#: alfanumérico de uma palavra de 14 letras.
_PADRAO_DOCUMENTO = re.compile(
    r"(?<![0-9A-Za-z./-])("
    r"\d{2}\.[0-9A-Za-z]{3}\.[0-9A-Za-z]{3}/[0-9A-Za-z]{4}-\d{2}"
    r"|\d{3}\.\d{3}\.\d{3}-\d{2}"
    r"|[0-9A-Za-z]{12}\d{2}"
    r"|\d{11}"
    r")(?![0-9A-Za-z./-])"
)

_PADRAO_DATA = re.compile(
    r"(?<![0-9/-])(\d{2}/\d{2}/\d{4}|\d{4}-\d{2}-\d{2}|\d{2}-\d{2}-\d{4})(?![0-9/-])"
)

_TEM_MASCARA = re.compile(r"[./-]")

#: Texto que aparece na tela mas não é dado: cabeçalho de coluna, paginação,
#: totalizador, rótulo de filtro, botão, nome de aba, breadcrumb. Comparado
#: depois de `_chave`. Vocabulário observado na tela real
#: (`admin.jettax360.com.br/prevention/ecac/procurations`): a coluna
#: OUTORGADO vem vazia (`-`), CLIENTE é selo Sim/Não, a aba "Sem procuração"
#: traz `Certificado do Cliente` e os filtros repetem os mesmos tokens dos
#: dados — por isso tudo isso precisa estar aqui.
_RUIDO_EXATO: frozenset[str] = frozenset(
    {
        "empresa", "empresas", "cliente", "clientes", "nome", "razao_social",
        "cnpj", "cpf", "cnpj_cpf", "cpf_cnpj", "documento", "inicio",
        "data_inicio", "vencimento", "data_vencimento", "validade", "situacao",
        "status", "acoes", "acao", "opcoes", "detalhes", "procuracao",
        "procuracoes", "sim", "nao", "s", "n", "todos", "todas", "total",
        "totalizadores", "filtros", "filtrar", "limpar", "buscar", "pesquisar",
        "exportar", "importar", "anterior", "proximo", "proxima", "primeira",
        "ultima", "pagina", "paginas", "registros", "resultados", "itens",
        "nenhum_registro_encontrado", "carregando", "e_cliente_na_jettax",
        "e_cliente", "ativas_de_clientes", "expiradas_de_clientes",
        "ativas_nao_clientes", "expiradas_nao_clientes", "prevencao", "ecac",
        "e_cac", "por_pagina", "linhas_por_pagina", "itens_por_pagina",
        # Coluna OUTORGADO (sempre vazia na tela) e cabeçalho da segunda aba.
        "outorgado", "outorgada", "outorgante", "certificado_vinculado",
        # Valores da coluna CERTIFICADO VINCULADO — não são nomes.
        "certificado_do_cliente", "certificado_principal",
        "certificado_da_empresa", "sem_certificado",
        # Barra de filtros e botões da tela atual.
        "gerar_relatorio", "gerar_relatorios", "relatorio", "procure_pela_empresa",
        "procure_pela_empresa_", "tipo", "periodo", "ordenar_por",
        # Nomes das abas e miolo do breadcrumb — anunciam tabela nova.
        "com_procuracao", "sem_procuracao", "procuracoes_e_cac",
    }
)

_RUIDO_PADRAO: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\d+$"),                                  # número de página
    re.compile(r"^\d+\s*(/|de)\s*\d+$"),                   # "3 de 12"
    re.compile(r"^pagina\s+\d+"),                           # "Página 4"
    re.compile(r"^mostrando\s+\d+"),                        # "Mostrando 1 a 20 de 132"
    re.compile(r"^exibindo\s+\d+"),
    re.compile(r"^\d+\s*(-|a)\s*\d+\s+de\s+\d+$"),
    re.compile(r"^(<|>|«|»|‹|›|\.{2,}|…)+$"),
    # Barra de paginação inteira numa linha só: "1 2 3 … Próximo".
    re.compile(r"^[\d\s…\.]+(proximo|proxima|anterior|primeira|ultima)?$"),
    re.compile(r"^(proximo|proxima|anterior|primeira|ultima)\b"),
    re.compile(r"^[^0-9A-Za-z]+$"),                         # só pontuação
)


#: Subconjunto do ruído que indica **começo de tabela, troca de aba ou troca
#: de página**. Encontrar um destes zera qualquer nome pendente **e desliga a
#: ligação com o documento anterior**: o que veio antes era cabeçalho,
#: totalizador, filtro ou título de aba — e um `Expirado` ou data solta que
#: vier depois não pode contaminar o último cliente da tabela anterior.
#: Fora daqui ficam "sim"/"não", que são *valores* da coluna CLIENTE no meio
#: da linha.
_CABECALHOS_TABELA: frozenset[str] = frozenset(
    {
        "empresa", "empresas", "cliente", "clientes", "nome", "razao_social",
        "cnpj", "cpf", "cnpj_cpf", "cpf_cnpj", "documento", "inicio",
        "data_inicio", "vencimento", "data_vencimento", "validade", "situacao",
        "status", "acoes", "acao", "e_cliente_na_jettax", "e_cliente",
        "ativas_de_clientes", "expiradas_de_clientes", "ativas_nao_clientes",
        "expiradas_nao_clientes",
        "outorgado", "outorgada", "certificado_vinculado",
        # Abas e breadcrumb: anunciam que uma tabela (outra) começa.
        "com_procuracao", "sem_procuracao", "procuracoes_e_cac",
        "prevencao", "ecac", "e_cac",
    }
)


def _eh_ruido(fragmento: str) -> bool:
    chave = _chave(fragmento)
    if not chave:
        return True
    if chave in _RUIDO_EXATO:
        return True
    # Data nunca é ruído. Sem esta guarda, "31/12/2030" vira "31 12 2030" e
    # cai no padrão de barra de paginação ("1 2 3 …") — foi assim que a
    # validade das autorizações sumiu na primeira versão deste parser.
    if _PADRAO_DATA.search(fragmento):
        return False
    return any(padrao.match(chave.replace("_", " ")) for padrao in _RUIDO_PADRAO)


def _reinicia_tabela(fragmento: str) -> bool:
    chave = _chave(fragmento)
    if chave in _CABECALHOS_TABELA:
        return True
    if _PADRAO_DATA.search(fragmento):
        return False
    texto = chave.replace("_", " ")
    return any(padrao.match(texto) for padrao in _RUIDO_PADRAO)


def _documentos_do_fragmento(fragmento: str) -> tuple[list[tuple[int, int, str]], list[str]]:
    """Documentos aceitos e candidatos recusados dentro de um fragmento.

    Regra que evita falso positivo: valor **com máscara** é aceito como
    documento pela própria máscara (é intenção explícita de quem escreveu);
    valor **sem máscara** só é aceito se os dígitos verificadores fecharem —
    senão um número de protocolo de 14 dígitos viraria empresa.

    O que não passa não some: volta como *recusado* para virar pendência com
    o valor à vista, em vez de sumir da importação sem explicação.
    """
    aceitos: list[tuple[int, int, str]] = []
    recusados: list[str] = []
    for encontro in _PADRAO_DOCUMENTO.finditer(fragmento):
        bruto = encontro.group(1)
        try:
            canonico = normalizar_documento(bruto)
        except ValueError:
            continue
        if not _TEM_MASCARA.search(bruto) and not validar_documento(canonico):
            recusados.append(bruto)
            continue
        aceitos.append((encontro.start(1), encontro.end(1), canonico))
    return aceitos, recusados


def _datas_do_fragmento(fragmento: str) -> list[date]:
    datas: list[date] = []
    for encontro in _PADRAO_DATA.finditer(fragmento):
        valor = _data(encontro.group(1))
        if valor is not None:
            datas.append(valor)
    return datas


def _situacao_do_fragmento(fragmento: str) -> StatusAutorizacao | None:
    return _ALIAS_SITUACAO.get(_chave(fragmento).replace("_", " "))


def _parece_nome(fragmento: str) -> bool:
    texto = fragmento.strip(" \t·-–—|")
    if len(texto) < 3 or len(texto) > 255:
        return False
    if _eh_ruido(texto) or _situacao_do_fragmento(texto) is not None:
        return False
    aceitos, recusados = _documentos_do_fragmento(texto)
    if _datas_do_fragmento(texto) or aceitos or recusados:
        return False
    return sum(1 for ch in texto if ch.isalpha()) >= 3


class _Bloco:
    """Um cliente em construção enquanto o texto é varrido."""

    __slots__ = ("documento", "nome", "datas", "situacao")

    def __init__(self, documento: str, nome: str):
        self.documento = documento
        self.nome = nome
        self.datas: list[date] = []
        self.situacao: StatusAutorizacao | None = None


class FonteColagem:
    """Lê a lista que o operador copiou da tela do fornecedor.

    O que o parser aguenta, porque é o que chega de verdade:

    - nome numa linha e documento na linha seguinte (colagem vertical);
    - nome e documento na mesma linha, separados por tabulação ou espaço
      (colagem de tabela HTML);
    - CNPJ e CPF misturados, com ou sem máscara, inclusive CNPJ alfanumérico;
    - cabeçalho de coluna, paginação, totalizador e rótulo de filtro no meio;
    - blocos parciais — colar página por página e aba por aba é idempotente,
      porque a chave é sempre o documento normalizado.

    O que ele **não** faz: inventar situação. Linha sem situação legível, sem
    data e sem `situacao_padrao` declarada não vira autorização — vira
    pendência com o motivo, listada para o operador resolver.
    """

    nome = "colagem"

    def __init__(
        self,
        texto: str,
        *,
        origem: str = "colagem",
        situacao_padrao: StatusAutorizacao | None = None,
    ):
        conteudo = str(texto or "")
        if len(conteudo) > LIMITE_CARACTERES_COLAGEM:
            raise FonteError(
                f"Texto colado acima do limite de "
                f"{LIMITE_CARACTERES_COLAGEM // (1024 * 1024)} MiB.",
                status_code=413,
            )
        if not conteudo.strip():
            raise FonteError("Nada foi colado.", status_code=422)
        self.texto = conteudo
        self.origem = origem
        self.situacao_padrao = situacao_padrao
        self._pendencias: list[dict[str, str]] = []
        self._linhas_ignoradas = 0

    # -- porta --------------------------------------------------------------

    def testar(self) -> str:
        registros = self.listar()
        return (
            f"{len(registros)} cliente(s) reconhecido(s) no texto colado "
            f"({len(self._pendencias)} linha(s) sem situação legível)."
        )

    def listar(self, documentos: Iterable[str] | None = None) -> list[RegistroProcuracao]:
        filtro = {d for d in (documentos or []) if d}
        self._pendencias = []
        self._linhas_ignoradas = 0

        blocos = self._varrer()
        registros: list[RegistroProcuracao] = []
        vistos: dict[str, int] = {}

        for bloco in blocos:
            situacao, inicio, validade = self._resolver(bloco)
            if situacao is None:
                self._pendencias.append(
                    {
                        "documento": bloco.documento,
                        "nome": bloco.nome,
                        "codigo": "SITUACAO_INDETERMINADA",
                        "mensagem": (
                            "A linha não trouxe situação nem data de vencimento. "
                            "Recopie incluindo as colunas SITUAÇÃO e VENCIMENTO, ou "
                            "declare a aba de origem no campo 'Situação da aba' "
                            "antes de importar."
                        ),
                    }
                )
                continue

            registro = RegistroProcuracao(
                documento=bloco.documento,
                razao_social=bloco.nome,
                situacao=situacao,
                data_inicio=inicio,
                data_validade=validade,
                observacao=f"Importado da lista {self.origem}.",
            ).normalizado()

            if filtro and registro.documento not in filtro:
                continue
            # Colar duas páginas com sobreposição é normal: a última leitura do
            # mesmo documento vence, e o total não infla.
            if registro.documento in vistos:
                registros[vistos[registro.documento]] = registro
                continue
            vistos[registro.documento] = len(registros)
            registros.append(registro)

        return registros

    # -- diagnóstico --------------------------------------------------------

    def pendencias_de_leitura(self) -> list[dict[str, str]]:
        """Linhas reconhecidas como cliente que não viraram autorização."""
        return list(self._pendencias)

    def aviso_de_leitura(self) -> str:
        partes: list[str] = []
        if self._pendencias:
            partes.append(f"{len(self._pendencias)} sem situação legível")
        if self._linhas_ignoradas:
            partes.append(f"{self._linhas_ignoradas} linha(s) sem CNPJ/CPF")
        return "; ".join(partes)

    # -- varredura ----------------------------------------------------------

    def _varrer(self) -> list[_Bloco]:
        blocos: list[_Bloco] = []
        atual: _Bloco | None = None
        nome_pendente = ""
        #: Só conta linha órfã **depois** do primeiro documento: o que vem antes
        #: é enfeite da página (título, totalizador, rótulo de filtro) e
        #: reportá-lo como perda assustaria o operador à toa.
        dentro_da_tabela = False

        for fragmento in self._fragmentos():
            documentos, recusados = _documentos_do_fragmento(fragmento)
            if not documentos and recusados and (nome_pendente or dentro_da_tabela):
                # Parece linha de cliente, mas o CNPJ/CPF sem máscara não fecha
                # o dígito verificador. Some da importação — mas não do
                # relatório: é erro de digitação ou de cópia, e o operador
                # precisa ver qual valor chegou.
                self._pendencias.append(
                    {
                        "documento": recusados[0][:30],
                        "nome": nome_pendente,
                        "codigo": "DOCUMENTO_INVALIDO",
                        "mensagem": (
                            f"'{recusados[0][:30]}' não é um CNPJ/CPF válido "
                            "(dígito verificador não confere). Confira a linha na "
                            "tela de origem e cole de novo."
                        ),
                    }
                )
                nome_pendente = ""
                continue
            if documentos:
                inicio_primeiro = documentos[0][0]
                antes = fragmento[:inicio_primeiro].strip(" \t·-–—|:")
                if _parece_nome(antes):
                    nome_pendente = antes
                for posicao, (_, fim, documento) in enumerate(documentos):
                    atual = _Bloco(documento, nome_pendente)
                    blocos.append(atual)
                    nome_pendente = ""
                    dentro_da_tabela = True
                    if posicao == len(documentos) - 1:
                        self._absorver(atual, fragmento[fim:])
                continue

            if _eh_ruido(fragmento):
                if _reinicia_tabela(fragmento):
                    # Cabeçalho de coluna, título de aba, breadcrumb ou marca
                    # de paginação: o que estava pendente era enfeite de tela
                    # (totalizador, filtro), não nome de cliente — e qualquer
                    # situação/data que vier a seguir já não pertence ao último
                    # documento lido.
                    nome_pendente = ""
                    atual = None
                continue

            situacao = _situacao_do_fragmento(fragmento)
            datas = _datas_do_fragmento(fragmento)
            # Data e situação só contam depois que um documento foi lido, e só
            # se ligam ao documento **imediatamente** anterior — nada pendente
            # no meio. Sem isto, o `Expirado` e os rótulos da barra de filtros
            # (que usa os mesmos tokens dos dados) virariam a situação do
            # último cliente da tabela anterior.
            if (situacao is not None or datas) and atual is not None and not nome_pendente:
                self._absorver(atual, fragmento)
                continue

            if _parece_nome(fragmento):
                if nome_pendente and dentro_da_tabela:
                    # Dois nomes seguidos sem documento entre eles: o primeiro
                    # ficou órfão (linha truncada na cópia). Fica registrado.
                    self._linhas_ignoradas += 1
                nome_pendente = fragmento.strip(" \t·-–—|")
                atual = None

        if nome_pendente and dentro_da_tabela:
            self._linhas_ignoradas += 1
        return blocos

    def _fragmentos(self) -> Iterable[str]:
        """Achata o texto em pedaços: cada linha, cada célula de tabulação."""
        for linha in self.texto.splitlines():
            for celula in linha.split("\t"):
                limpo = " ".join(celula.split())
                if limpo:
                    yield limpo

    @staticmethod
    def _absorver(bloco: _Bloco, trecho: str) -> None:
        bloco.datas.extend(_datas_do_fragmento(trecho))
        if bloco.situacao is None:
            # O trecho pode ser "Sim 01/02/2024 31/12/2030 Válida": procura a
            # situação palavra a palavra, não só no fragmento inteiro.
            situacao = _situacao_do_fragmento(trecho)
            if situacao is None:
                for palavra in re.split(r"[\s|·]+", trecho):
                    situacao = _situacao_do_fragmento(palavra)
                    if situacao is not None:
                        break
            bloco.situacao = situacao

    def _resolver(
        self, bloco: _Bloco
    ) -> tuple[StatusAutorizacao | None, date | None, date | None]:
        """Decide situação, início e validade de um bloco já varrido."""
        datas = bloco.datas[:2]
        inicio: date | None = None
        validade: date | None = None
        if len(datas) >= 2:
            inicio, validade = datas[0], datas[1]
            if inicio > validade:
                # A ordem das colunas é INÍCIO → VENCIMENTO; quando a cópia
                # inverte, a data menor é o início. Vencimento anterior ao
                # início não existe.
                inicio, validade = validade, inicio
        elif len(datas) == 1:
            # Coluna única numa lista de procurações é o vencimento: é o que a
            # tela destaca e o que o módulo usa para alertar.
            validade = datas[0]

        situacao = bloco.situacao or self.situacao_padrao
        if situacao is None and validade is not None:
            situacao = situacao_por_validade(validade, ativa=True)
        if situacao is None:
            return None, inicio, validade
        if situacao is StatusAutorizacao.ATIVA and validade and validade < date.today():
            situacao = StatusAutorizacao.EXPIRADA
        return situacao, inicio, validade


def _cabecalho_tem_documento(texto: str) -> bool:
    """A primeira linha útil é um cabeçalho com coluna de CNPJ/CPF?"""
    for linha in texto.splitlines():
        if not linha.strip():
            continue
        for separador in (";", "\t", ",", "|"):
            if separador in linha:
                campos = [_chave(parte) for parte in linha.split(separador)]
                if any(_ALIAS_COLUNAS.get(campo) == "documento" for campo in campos):
                    return True
        return _ALIAS_COLUNAS.get(_chave(linha)) == "documento"
    return False


def criar_fonte_texto(
    conteudo: bytes | str,
    *,
    nome_arquivo: str = "lista.txt",
    origem: str = "colagem",
    situacao_padrao: StatusAutorizacao | None = None,
):
    """Escolhe o leitor certo para o que chegou.

    CSV exportado do fornecedor tem cabeçalho com coluna de documento e vai
    para ``FontePlanilha``. Colagem de tela não tem — vai para
    ``FonteColagem``. A decisão é do conteúdo, não da extensão do arquivo:
    exportar ``.xls`` que na verdade é HTML/TSV é rotina em painel web.
    """
    texto = decodificar(conteudo) if isinstance(conteudo, (bytes, bytearray)) else str(conteudo)
    if _cabecalho_tem_documento(texto):
        return FontePlanilha(
            texto.encode("utf-8"),
            nome_arquivo=nome_arquivo,
            situacao_padrao=situacao_padrao,
        )
    return FonteColagem(texto, origem=origem, situacao_padrao=situacao_padrao)
