"""Serviço de geração inteligente de senhas, leitura de planilhas e abertura de certificados A1.

Suporta:
- Padrões comuns de contabilidade e empresas:
  EMPRESA + ANO (ex: CAJURU2026, CAJURU26, APX2026, APX26, ACESSORIA26, CAJURU25, etc.) em maiúsculas
  Variações com separadores (@, #), minúsculas e capitalizadas
- Extração de tokens e nomes a partir do nome do arquivo, da razão social e de planilhas
- Leitura flexível de planilhas nos formatos .xlsx, .xlsm, .xls, .csv, .txt
- Combinação de senhas declaradas, senhas por CNPJ, senhas por similaridade de nome,
  senhas padrão heurísticas e senhas comuns de mercado.
"""

from __future__ import annotations

import csv
import datetime
import io
import re
import unicodedata
from typing import TYPE_CHECKING, Any

from rapidfuzz import fuzz

from app.core.documentos import (
    normalizar_documento,
    validar_documento,
)

if TYPE_CHECKING:
    from app.services.certificados import IdentidadeCertificado

LEGAL_SUFFIXES = {
    "LTDA", "ME", "EPP", "EIRELI", "MEI", "SA", "S A", "SS", "SLU",
    "SOCIEDADE UNIPESSOAL", "ASSOCIACAO", "FUNDACAO", "INSTITUTO",
    "S/A", "S.A.", "LTDA-ME", "LTDA - ME", "EPP - ME",
}

STOP_WORDS = {
    "E", "DE", "DA", "DO", "DAS", "DOS", "EM", "NA", "NO", "THE", "A", "O",
    "PARA", "COM", "POR", "SEM", "SOB", "SOBRE",
}

GENERIC_WORDS_TO_EXPAND = {
    "ASSESSORIA": "ACESSORIA",
    "ACESSORIA": "ASSESSORIA",
    "SERVICOS": "SERVICO",
    "SERVICO": "SERVICOS",
    "COMERCIO": "COMERCIAL",
    "COMERCIAL": "COMERCIO",
}

COMMON_DEFAULTS = [
    "123456",
    "12345678",
    "1234",
    "12345",
    "123456789",
    "123",
    "1234567890",
    "cert2026",
    "cert26",
    "cajuru2026",
    "cajuru26",
    "cajuru25",
    "cajuru24",
    "admin",
    "mudar123",
]


def remover_acentos(texto: str | None) -> str:
    if not texto:
        return ""
    normalizado = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", str(texto)))
    return "".join(c for c in normalizado if not unicodedata.combining(c))


def normalizar_nome(texto: str | None) -> str:
    if not texto:
        return ""
    valor = remover_acentos(texto).casefold().upper().replace("&", " E ").replace("+", " E ")
    valor = re.sub(r"[^A-Z0-9]+", " ", valor)
    palavras = re.sub(r"\s+", " ", valor).strip().split()
    while palavras and palavras[-1] in LEGAL_SUFFIXES:
        palavras.pop()
    if len(palavras) >= 2 and " ".join(palavras[-2:]) in LEGAL_SUFFIXES:
        words = palavras[:-2]
        palavras = words
    return " ".join(palavras)


def tokens_significativos(texto: str | None) -> list[str]:
    nome = normalizar_nome(texto)
    return [t for t in nome.split() if t and t not in STOP_WORDS]


def stems_de_texto(texto: str | None) -> list[str]:
    """Extrai os termos principais (marcas/palavras) para geração de senhas."""
    tokens = tokens_significativos(texto)
    stems: list[str] = []

    def adicionar(termo: str) -> None:
        t = termo.strip().upper()
        if len(t) >= 2 and t not in stems and not t.isdigit():
            stems.append(t)
            variante = GENERIC_WORDS_TO_EXPAND.get(t)
            if variante and variante not in stems:
                stems.append(variante)

        # Se o termo terminar com ano (ex: ACESSORIA26 ou CAJURU2026), extrai a raiz
        match_ano = re.match(r"^([A-Z]{2,})(\d{2}|\d{4})$", t)
        if match_ano:
            raiz = match_ano.group(1)
            if raiz not in stems:
                stems.append(raiz)
                variante_raiz = GENERIC_WORDS_TO_EXPAND.get(raiz)
                if variante_raiz and variante_raiz not in stems:
                    stems.append(variante_raiz)

    for t in tokens:
        adicionar(t)

    # Primeira palavra composta (ex.: "BIO3" + "SERVICOS" -> "BIO3SERVICOS")
    if len(tokens) >= 2:
        adicionar("".join(tokens[:2]))

    return stems


def stems_de_nome_arquivo(nome_arquivo: str | None) -> list[str]:
    """Extrai palavras do nome do arquivo .pfx removendo extensões, CNPJs e datas."""
    if not nome_arquivo:
        return []
    stem = re.sub(r"\.(pfx|p12|enc|tmp)$", "", nome_arquivo, flags=re.IGNORECASE)
    # Remove CNPJs formatados ou sequências de 14 dígitos
    stem = re.sub(r"(?<!\d)\d{2}[.\s]?\d{3}[.\s]?\d{3}\s*[/\\]\s*\d{4}\s*[-–]\s*\d{2}(?!\d)", " ", stem)
    stem = re.sub(r"(?<!\d)\d{14}(?!\d)", " ", stem)
    # Remove datas comuns como 2026-05-12, 20260512
    stem = re.sub(r"\b(20\d{2}[-_/]?\d{2}[-_/]?\d{2})\b", " ", stem)
    # Remove palavras puramente técnicas
    stem = re.sub(r"\b(PFX|P12|CERT|CERTIFICADO|A1|DIGITAL|NOVO|ANTIGO|ATUAL)\b", " ", stem, flags=re.IGNORECASE)

    # Separa letras grudadas em números quando for separador (ex: CAJURU_2026 ou ACESSORIA26)
    # mas preservando a palavra original também
    stems = stems_de_texto(stem)

    # Adiciona também a raiz direta se o nome do arquivo for algo como "CAJURU2026"
    nome_limpo = re.sub(r"[^A-Z0-9]+", "", remover_acentos(nome_arquivo).upper())
    for ext in ("PFX", "P12"):
        if nome_limpo.endswith(ext):
            nome_limpo = nome_limpo[:-len(ext)]
    if nome_limpo and nome_limpo not in stems and not nome_limpo.isdigit():
        match = re.match(r"^([A-Z]{2,})(\d{2}|\d{4})$", nome_limpo)
        if match:
            raiz = match.group(1)
            if raiz not in stems:
                stems.insert(0, raiz)

    return stems


def sufixos_anos(ano_base: int | None = None) -> list[str]:
    """Gera anos com 4 e 2 dígitos priorizando o ano atual e anos adjacentes."""
    agora = ano_base or datetime.datetime.now(datetime.timezone.utc).year
    # Anos prioritários: ano atual, ano anterior, 2 anos atrás, próximo ano, etc.
    sequencia_anos = [
        agora,
        agora - 1,
        agora - 2,
        agora + 1,
        agora + 2,
        agora - 3,
        agora - 4,
        agora - 5,
        agora + 3,
        agora + 4,
        agora - 6,
        agora - 7,
    ]
    sufixos: list[str] = []
    for ano in sequencia_anos:
        s4 = str(ano)
        s2 = s4[-2:]
        if s4 not in sufixos:
            sufixos.append(s4)
        if s2 not in sufixos:
            sufixos.append(s2)
    return sufixos


def gerar_senhas_padrao(stems: list[str], anos: list[str] | None = None) -> list[str]:
    """Gera combinações de padrão EMPRESA+ANO (ex: CAJURU2026, CAJURU26, APX2026, ACESSORIA26)."""
    if not stems:
        return []
    sufixos = anos or sufixos_anos()
    senhas: list[str] = []
    vistos: set[str] = set()

    def adicionar(senha: str) -> None:
        if senha and senha not in vistos:
            vistos.add(senha)
            senhas.append(senha)

    # 1. Prioridade máxima: STEM + ANO em MAIÚSCULAS (ex: CAJURU2026, CAJURU26, CAJURU2025, CAJURU25)
    for s in stems:
        for y in sufixos:
            adicionar(f"{s}{y}")

    # 2. STEM + @ ou # + ANO (ex: CAJURU@2026, CAJURU@26, CAJURU#2026)
    for s in stems:
        for y in sufixos[:8]:
            adicionar(f"{s}@{y}")
            adicionar(f"{s}#{y}")
            adicionar(f"{s}!{y}")

    # 3. Apenas o STEM em maiúsculas (ex: CAJURU, APX, ACESSORIA)
    for s in stems:
        adicionar(s)

    # 4. STEM em minúsculas + ANO (ex: cajuru2026, cajuru26, cajuru25)
    for s in stems:
        for y in sufixos[:6]:
            adicionar(f"{s.lower()}{y}")
            adicionar(f"{s.capitalize()}{y}")

    # 5. STEM em minúsculas + @ + ANO (ex: cajuru@2026, cajuru@26)
    for s in stems:
        for y in sufixos[:6]:
            adicionar(f"{s.lower()}@{y}")

    # 6. ANO + STEM (ex: 2026CAJURU, 26CAJURU)
    for s in stems:
        for y in sufixos[:6]:
            adicionar(f"{y}{s}")

    return senhas


def similaridade_nomes(a: str, b: str) -> float:
    """Calcula similaridade entre nomes de empresas."""
    left, right = normalizar_nome(a), normalizar_nome(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 100.0
    token_set = float(fuzz.token_set_ratio(left, right))
    token_sort = float(fuzz.token_sort_ratio(left, right))
    ratio = float(fuzz.ratio(left, right))
    score = max(ratio, token_sort, token_set * 0.96)
    shorter, longer = sorted((left, right), key=len)
    if longer.startswith(shorter + " "):
        coverage = len(shorter) / len(longer)
        score = max(score, 88.0 + 10.0 * coverage)
    return min(100.0, score)


def construir_candidatas_pfx(
    nome_arquivo: str,
    *,
    cnpj: str = "",
    razao_social: str = "",
    senhas_declaradas: list[str] | None = None,
    senha_global: str = "",
    todas_senhas_planilha: list[str] | None = None,
    limite_maximo: int = 150,
) -> list[str]:
    """Monta a lista ordenada de candidatas a testar para um arquivo .pfx."""
    candidatas: list[str] = []
    vistos: set[str] = set()

    def adicionar(senha: str, *, permitir_vazia: bool = False) -> None:
        if senha is None:
            senha = ""
        val = senha if permitir_vazia else senha.strip()
        if (not val and not permitir_vazia) or val in vistos or len(candidatas) >= limite_maximo:
            return
        vistos.add(val)
        candidatas.append(val)

    # 1. Senha digitada no formulário (se informada)
    if senha_global:
        adicionar(senha_global)

    # 2. Senhas declaradas para o CNPJ nas planilhas anexadas
    for s in senhas_declaradas or []:
        adicionar(s)

    # 3. Padrões gerados a partir do nome do arquivo (ex.: CAJURU_2026.pfx -> CAJURU2026, CAJURU26, etc.)
    stems_arquivo = stems_de_nome_arquivo(nome_arquivo)
    for p in gerar_senhas_padrao(stems_arquivo):
        adicionar(p)

    # 4. Padrões gerados a partir da razão social conhecida
    if razao_social:
        stems_razao = stems_de_texto(razao_social)
        for p in gerar_senhas_padrao(stems_razao):
            adicionar(p)

    # 5. Se o próprio nome do arquivo (sem extensão) parece uma senha (ex: ACESSORIA26.pfx)
    nome_puro = re.sub(r"\.(pfx|p12|enc|tmp)$", "", nome_arquivo, flags=re.IGNORECASE).strip()
    if len(nome_puro) >= 3 and not nome_puro.isdigit():
        adicionar(nome_puro.upper())
        adicionar(nome_puro)

    # 6. Todas as senhas únicas das planilhas anexadas (varredura inteligente)
    for s in todas_senhas_planilha or []:
        adicionar(s)

    # 7. Senhas padrão comuns de mercado
    for s in COMMON_DEFAULTS:
        adicionar(s)

    # 8. Senha vazia / sem senha (certificados sem proteção PKCS#12)
    adicionar("", permitir_vazia=True)

    return candidatas


# ── Leitura de Planilhas (Excel .xlsx / .xlsm / .xls e CSV / TXT) ─────────────

_UFS_VALIDAS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA",
    "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN",
    "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}

# Nomes de coluna aceitos no cabeçalho, em ordem de prioridade. A planilha que
# os escritórios realmente usam para certificados A1 não segue um único modelo:
# já foi vista como `cnpj;senha`, `razao_social;cnpj_cpf;uf;senha` e também
# `arquivo;cnpj;emissor;senha;validade` (exportação do inventário de A1).
_NOMES_COLUNAS: dict[str, tuple[str, ...]] = {
    "cnpj": (
        "cnpj_cpf", "cnpj_cpf_cliente", "cnpj_cliente", "cnpj_empresa",
        "cnpj", "cpf", "documento", "doc",
    ),
    "senha": (
        "senha_certificado", "senha_do_certificado", "senha_a1", "senha_pfx",
        "senha", "password", "pass", "senhas",
    ),
    "razao": (
        "razao_social", "razaosocial", "nome_empresarial", "nome_empresa",
        "razao", "nome", "empresa", "cliente",
    ),
    "uf": ("uf", "estado", "sigla_uf"),
    "validade": (
        "data_validade", "validade_certificado", "data_expiracao", "validade",
        "vencimento", "expiracao", "venc",
    ),
    "arquivo": (
        "nome_arquivo", "nome_do_arquivo", "arquivo_certificado",
        "nome_do_certificado", "arquivo", "certificado", "filename", "file",
    ),
    "emissor": (
        "autoridade_certificadora", "emissor_certificado", "ac_emissora",
        "emissor", "padrao", "icp", "ac",
    ),
}

# Autoridades certificadoras que aparecem na coluna "emissor"/"padrão" das
# exportações de inventário A1. Servem só para descartar a coluna: nunca são
# senha.
_EMISSORES_CONHECIDOS = {
    "ICPBRASIL", "SERPRO", "CERTISIGN", "SOLUTI", "SAFEWEB", "VALID",
    "VALIDCERTIFICADORA", "BOAVISTA", "BOAVISTASCD", "IMPRENSAOFICIAL",
    "FENACON", "SESCON", "SESCONSP", "CDL", "OAB", "SINCOR", "ACNOTARIAL",
    "CERTIFICA", "CERTIFICAMINAS", "RECEITAFEDERAL", "CASADASMOEDAS",
    "SERASA", "AMPRSP", "ACJUS", "DIGITALSIGN", "DIGITALSIGNID", "NOTARIAL",
    "FENACOR", "SESCONMG", "SESCONRJ", "SESCONSC", "SESCONRS", "PRESIDENCIA",
}

_RE_ARQUIVO_CERTIFICADO = re.compile(r"\.(pfx|p12|cer|crt|pem|p7b|spc|key)$", re.IGNORECASE)
_RE_DATA_DIA_MES_ANO = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
_RE_DATA_ISO = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")
_RE_DATA_COMPACTA = re.compile(r"^\d{8}$")


def _normalizar_cabecalho(celula: Any) -> str:
    texto = remover_acentos(str(celula or "")).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def _indice_coluna(cabecalho: list[str], nomes: tuple[str, ...]) -> int | None:
    for nome in nomes:
        if nome in cabecalho:
            return cabecalho.index(nome)
    for idx, col in enumerate(cabecalho):
        pedacos = [p for p in col.split("_") if p]
        for nome in nomes:
            # Nomes curtos ("uf", "ac", "doc") só casam como palavra inteira:
            # casar "ac" dentro de qualquer texto entregaria coluna errada.
            if nome in pedacos:
                return idx
            if len(nome) >= 4 and nome in col:
                return idx
    return None


def _texto_celula(valor: Any) -> str:
    """Texto estável para qualquer célula (CSV, Excel, número, data)."""
    if valor is None:
        return ""
    if isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, (int, float)):
        numero = float(valor)
        if numero.is_integer():
            return str(int(numero))
        return str(valor)
    if isinstance(valor, datetime.datetime):
        # Data de validade vinda do Excel como datetime: 00:00 não interessa.
        if (valor.hour, valor.minute, valor.second) == (0, 0, 0):
            return valor.strftime("%d/%m/%Y")
        return valor.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(valor, datetime.date):
        return valor.strftime("%d/%m/%Y")
    return str(valor).strip()


def _eh_arquivo_certificado(texto: str) -> bool:
    return bool(_RE_ARQUIVO_CERTIFICADO.search((texto or "").strip()))


def _eh_data(texto: str) -> bool:
    valor = (texto or "").strip()
    if not valor:
        return False
    return bool(
        _RE_DATA_DIA_MES_ANO.match(valor)
        or _RE_DATA_ISO.match(valor)
        or _RE_DATA_COMPACTA.match(valor)
    )


def _eh_uf(texto: str) -> bool:
    return (texto or "").strip().upper() in _UFS_VALIDAS


def _eh_emissor(texto: str) -> bool:
    """Coluna 'ICP-Brasil' / 'AC Soluti' / 'Certisign' — nunca é senha."""
    bruto = (texto or "").strip()
    if not bruto:
        return False
    normalizado = re.sub(r"[^A-Z0-9]+", " ", remover_acentos(bruto).upper()).strip()
    pedacos = normalizado.split()
    if not pedacos:
        return False
    if pedacos[0] in {"AC", "ICP"}:
        return True
    return normalizado.replace(" ", "") in _EMISSORES_CONHECIDOS


def _celula_documento(texto: str) -> str:
    """CNPJ/CPF válido da célula, ou "" — nome de arquivo nunca é documento."""
    valor = (texto or "").strip()
    if not valor or _eh_arquivo_certificado(valor):
        return ""
    try:
        documento = normalizar_documento(valor)
    except ValueError:
        return ""
    return documento if validar_documento(documento) else ""


def _documento_de_nome_arquivo(nome: str) -> str:
    """CNPJ/CPF embutido no nome do arquivo (`00585041000197.pfx`)."""
    base = _RE_ARQUIVO_CERTIFICADO.sub("", (nome or "").strip())
    base = re.sub(r"[^A-Za-z0-9]+", " ", base)
    for trecho in base.split():
        documento = _celula_documento(trecho)
        if documento:
            return documento
    return ""


def _parece_senha(texto: str) -> float:
    """Pontua o quanto uma célula parece senha (e não razão social/UF/data)."""
    valor = (texto or "").strip()
    if not valor:
        return -10.0
    pontos = 0.0
    tem_digito = any(c.isdigit() for c in valor)
    tem_letra = any(c.isalpha() for c in valor)
    if tem_digito and tem_letra:
        pontos += 2.0
    if any(not c.isalnum() and c != " " for c in valor):
        pontos += 1.5
    if len(valor) <= 24:
        pontos += 0.5
    if len(valor) > 40:
        pontos -= 2.0
    palavras = valor.split()
    if len(palavras) >= 2:
        pontos -= 1.0
    if len(palavras) >= 2 and all(p.isalpha() for p in palavras):
        # "CAJURU CONTABILIDADE LTDA" é razão social, não senha.
        pontos -= 2.0
    return pontos


def _parece_razao_social(texto: str) -> bool:
    valor = (texto or "").strip()
    palavras = [p for p in re.split(r"\s+", remover_acentos(valor)) if p]
    if len(palavras) < 2 or len(valor) < 5:
        return False
    return all(p.isalpha() or p in {"&", "E"} for p in palavras)


def _largura(linhas: list[list[str]]) -> int:
    return max((len(linha) for linha in linhas), default=0)


def _detectar_cabecalho(linhas: list[list[str]]) -> tuple[int | None, dict[str, int | None]]:
    """Procura, nas primeiras linhas, um título que nomeie as colunas.

    Duas proteções para não comer a primeira linha de dados:

    - linha com documento válido é dado (`12345678000195;SenhaForte2026;BA` —
      a senha começa com "senha" e casava como título);
    - linha que cita um arquivo de certificado é dado
      (`certificado-novo.pfx;MinhaSenha@2026` — "certificado" e "senha"
      casavam como título e a planilha voltava vazia).
    """
    for idx, linha in enumerate(linhas[:20]):
        if idx >= len(linhas) - 1:
            # Título sem nenhuma linha de dados abaixo não é título: é dado.
            continue
        cabecalho = [_normalizar_cabecalho(celula) for celula in linha]
        achados = {chave: _indice_coluna(cabecalho, nomes) for chave, nomes in _NOMES_COLUNAS.items()}
        nomeados = [chave for chave, indice in achados.items() if indice is not None]
        if not nomeados:
            continue
        if any(_celula_documento(celula) or _eh_arquivo_certificado(celula) for celula in linha):
            continue
        if achados["cnpj"] is not None or len(nomeados) >= 2:
            return idx, achados
    return None, {chave: None for chave in _NOMES_COLUNAS}


def _inferir_colunas(
    linhas: list[list[str]],
    reservadas: frozenset[int] = frozenset(),
) -> dict[str, int | None]:
    """Descobre as colunas pelo conteúdo quando a planilha não tem cabeçalho.

    É o caso mais comum em escritório: o inventário de A1 é exportado como
    `21260898000107.pfx;21.260.898/0001-07;ICP-Brasil;7cs19Pfi;09/03/2027`,
    sem título nenhum. Ler "coluna A = CNPJ, coluna B = senha" nessa planilha
    devolve zero linhas — o CNPJ está na segunda coluna.

    `reservadas` são colunas que o cabeçalho já nomeou: não podem virar senha
    nem razão social por inferência.
    """
    colunas: dict[str, int | None] = {chave: None for chave in _NOMES_COLUNAS}
    largura = _largura(linhas)
    if not largura or not linhas:
        return colunas

    votos = [
        {"doc": 0, "arquivo": 0, "data": 0, "uf": 0, "emissor": 0, "cheio": 0, "senha": 0.0}
        for _ in range(largura)
    ]
    for linha in linhas:
        for indice in range(largura):
            texto = linha[indice].strip() if indice < len(linha) else ""
            if not texto:
                continue
            voto = votos[indice]
            voto["cheio"] += 1
            if _celula_documento(texto):
                voto["doc"] += 1
            elif _eh_arquivo_certificado(texto):
                voto["arquivo"] += 1
            elif _eh_data(texto):
                voto["data"] += 1
            elif _eh_uf(texto):
                voto["uf"] += 1
            elif _eh_emissor(texto):
                voto["emissor"] += 1
            else:
                voto["senha"] += _parece_senha(texto)

    def melhor(chave: str) -> int | None:
        candidato, pontos = None, 0
        for indice, voto in enumerate(votos):
            if voto[chave] > pontos:
                candidato, pontos = indice, voto[chave]
        return candidato

    def coluna_uniforme(chave: str) -> int | None:
        for indice, voto in enumerate(votos):
            if voto["cheio"] and voto[chave] == voto["cheio"]:
                return indice
        return None

    def coluna_uf() -> int | None:
        """Coluna em que toda célula é uma UF — com prova suficiente.

        Uma única célula "SE" ou "AM" pode ser um pedaço de senha partida pelo
        separador, não uma UF. Só vale com duas ou mais linhas concordando, ou
        numa planilha de uma linha em que a UF é a última coluna.
        """
        candidatas = [
            indice for indice, voto in enumerate(votos)
            if voto["cheio"] and voto["uf"] == voto["cheio"]
        ]
        if not candidatas:
            return None
        repetidas = [i for i in candidatas if votos[i]["uf"] >= 2]
        if repetidas:
            return max(repetidas, key=lambda i: votos[i]["uf"])
        unica = candidatas[0]
        if len(linhas) == 1 and unica == largura - 1:
            return unica
        return None

    colunas["cnpj"] = melhor("doc")
    colunas["arquivo"] = melhor("arquivo")
    colunas["validade"] = melhor("data")
    colunas["uf"] = coluna_uf()
    colunas["emissor"] = coluna_uniforme("emissor")
    if colunas["emissor"] == colunas["uf"]:
        colunas["emissor"] = None

    ocupadas = {i for i in colunas.values() if i is not None} | set(reservadas)
    candidatas = [
        indice for indice, voto in enumerate(votos)
        if indice not in ocupadas and voto["cheio"]
    ]
    if not candidatas:
        return colunas

    validade = colunas["validade"]
    if validade is not None and (validade - 1) in candidatas:
        # `...;senha;validade` — a senha é a célula imediatamente anterior à data.
        colunas["senha"] = validade - 1
    elif len(candidatas) == 1:
        colunas["senha"] = candidatas[0]
    else:
        colunas["senha"] = max(
            candidatas,
            key=lambda i: votos[i]["senha"] / votos[i]["cheio"],
        )

    sobrando = [i for i in candidatas if i != colunas["senha"]]
    for indice in sobrando:
        celulas = [
            linha[indice].strip() for linha in linhas
            if indice < len(linha) and linha[indice].strip()
        ]
        if celulas and sum(_parece_razao_social(c) for c in celulas) >= len(celulas) / 2:
            colunas["razao"] = indice
            break

    return colunas


def _resolver_colunas(
    dados: list[list[str]],
    do_cabecalho: dict[str, int | None],
) -> dict[str, int | None]:
    """Cabeçalho manda; o conteúdo corrige o que o cabeçalho não resolver.

    Também salva o caso inverso: cabeçalho com coluna trocada (o título diz
    CNPJ, mas a coluna não tem um documento válido enquanto outra tem 500).
    """
    colunas = dict(do_cabecalho)
    if not dados:
        return colunas

    do_titulo = {chave for chave, indice in do_cabecalho.items() if indice is not None}
    reservadas = frozenset(do_cabecalho[chave] for chave in do_titulo)
    inferidas = _inferir_colunas(dados, reservadas)

    indice_cnpj = colunas.get("cnpj")
    tem_documento_no_titulo = indice_cnpj is not None and any(
        indice_cnpj < len(linha) and _celula_documento(linha[indice_cnpj]) for linha in dados
    )
    if not tem_documento_no_titulo and inferidas.get("cnpj") is not None:
        colunas["cnpj"] = inferidas["cnpj"]

    for chave in ("senha", "razao", "uf", "validade", "arquivo", "emissor"):
        if colunas.get(chave) is None:
            colunas[chave] = inferidas.get(chave)

    # Duas chaves nunca apontam para a mesma coluna. O documento vence sempre
    # (sem ele nada é importado); depois vale o que o título nomeou; por último
    # a ordem de especificidade.
    prioridade = ["cnpj", "senha", "razao", "uf", "validade", "arquivo", "emissor"]
    for indice in {i for i in colunas.values() if i is not None}:
        concorrentes = [chave for chave in prioridade if colunas.get(chave) == indice]
        if len(concorrentes) <= 1:
            continue
        concorrentes.sort(
            key=lambda chave: (
                0 if chave == "cnpj" else 1,
                0 if chave in do_titulo else 1,
                prioridade.index(chave),
            )
        )
        for perdedora in concorrentes[1:]:
            colunas[perdedora] = None

    return colunas


def _span_senha(
    linha: list[str],
    colunas: dict[str, int | None],
    esperado: int,
) -> tuple[int, int]:
    """Intervalo de células que forma a senha desta linha.

    Duas situações saem do trivial e precisam ser cobertas:

    1. **Senha com o separador dentro** (`a;b@123`): a linha vem com mais
       células do que a planilha tem colunas. Sem juntar de volta, a senha
       chegava pela metade e o certificado não abria.
    2. **Pedaço órfão ao lado da senha**: quando a senha foi partida, um dos
       pedaços fica numa coluna que nenhum papel explicou. Ele pertence à
       senha — desde que não pareça razão social.
    """
    indice = colunas.get("senha")
    if indice is None:
        return 0, 0
    explicadas = {i for i in colunas.values() if i is not None}
    extras = max(0, len(linha) - esperado) if esperado > 0 else 0

    ancora = min([i for i in explicadas if i > indice], default=len(linha))
    fim = min(max(ancora, indice + 1) + extras, len(linha))

    inicio = min(indice, len(linha))
    while (
        inicio - 1 >= 0
        and (inicio - 1) not in explicadas
        and linha[inicio - 1].strip()
        and not _parece_razao_social(linha[inicio - 1])
    ):
        inicio -= 1

    return inicio, max(fim, min(indice + 1, len(linha)))


def _valor_senha(linha: list[str], colunas: dict[str, int | None], esperado: int, separador: str) -> str:
    inicio, fim = _span_senha(linha, colunas, esperado)
    if fim <= inicio:
        return ""
    return separador.join(linha[inicio:min(fim, len(linha))]).strip()


def _extrair_registros(
    linhas: list[list[Any]],
    *,
    nome_arquivo: str = "",
    origem_padrao: str = "",
    separador: str = ";",
    sem_documento: list[dict] | None = None,
) -> dict[str, dict]:
    """Converte linhas (CSV ou Excel) no dicionário por CNPJ usado no lote.

    A mesma leitura vale para as duas origens: o que muda é só como as células
    chegam aqui. Uma linha só entra no dicionário quando existe um documento
    válido — na coluna de CNPJ ou no nome do arquivo citado na linha. Linhas
    com senha e nome de arquivo, mas sem documento nenhum, vão para
    `sem_documento`: ainda servem para abrir o .pfx cujo nome bate.
    """
    texto_linhas = [[_texto_celula(celula) for celula in linha] for linha in linhas]
    numeradas = [
        (numero, linha)
        for numero, linha in enumerate(texto_linhas, start=1)
        if any(celula.strip() for celula in linha)
    ]
    if not numeradas:
        return {}

    indice_cabecalho, do_cabecalho = _detectar_cabecalho([linha for _, linha in numeradas])
    if indice_cabecalho is not None:
        numeradas = numeradas[indice_cabecalho + 1:]

    dados = [linha for _, linha in numeradas]
    colunas = _resolver_colunas(dados, do_cabecalho)

    if colunas.get("cnpj") is None and colunas.get("arquivo") is None:
        # Nem documento nem nome de arquivo: não há o que importar daqui, e
        # inventar coluna transformaria razão social em CNPJ.
        return {}

    # Largura esperada do layout: o comprimento mais comum entre as linhas de
    # dados, nunca menor que a última coluna identificada. Uma linha mais larga
    # que isso tem o separador dentro da senha.
    comprimentos = [len(linha) for linha in dados if linha]
    modal = max(set(comprimentos), key=comprimentos.count) if comprimentos else 0
    maior_indice = max([i for i in colunas.values() if i is not None], default=-1)
    esperado = max(modal, maior_indice + 1)

    def celula(linha: list[str], chave: str) -> str:
        indice = colunas.get(chave)
        if indice is None:
            return ""
        # Linha mais larga que o layout: o separador estava dentro da senha, então
        # tudo que vem depois dela está deslocado para a direita nesta linha.
        indice_senha = colunas.get("senha")
        if (
            indice_senha is not None
            and indice > indice_senha
            and esperado > 0
            and len(linha) > esperado
        ):
            indice += len(linha) - esperado
        if indice >= len(linha):
            return ""
        return linha[indice].strip()

    resultado: dict[str, dict] = {}
    for numero, linha in numeradas:
        arquivo = celula(linha, "arquivo")
        documento = _celula_documento(celula(linha, "cnpj"))
        documento_do_arquivo = _documento_de_nome_arquivo(arquivo) if arquivo else ""

        uf = celula(linha, "uf").upper()
        if uf not in _UFS_VALIDAS:
            uf = ""

        registro = {
            "cnpj": documento or documento_do_arquivo,
            "razao_social": celula(linha, "razao"),
            "uf": uf,
            "senha": _valor_senha(linha, colunas, esperado, separador),
            "validade": celula(linha, "validade"),
            "arquivo": arquivo,
            "origem": nome_arquivo or origem_padrao,
            "linha": numero,
        }

        if not documento and not documento_do_arquivo:
            # Sem documento a linha não cria empresa nenhuma, mas a senha ainda
            # abre o .pfx cujo nome foi escrito na planilha.
            if (
                sem_documento is not None
                and registro["senha"]
                and (arquivo or registro["razao_social"])
            ):
                sem_documento.append(registro)
            continue

        # A linha vale para os dois documentos quando eles existem: o CNPJ da
        # coluna e o CNPJ do nome do arquivo. Digitação errada na coluna
        # (`34.304.74/0001-33`) deixava o certificado sem senha — o nome do
        # arquivo (`34304074000133.pfx`) ainda identifica a empresa.
        chaves = [documento] if documento else []
        if documento_do_arquivo and documento_do_arquivo not in chaves:
            chaves.append(documento_do_arquivo)
        for chave in chaves:
            resultado.setdefault(chave, registro)

    return resultado


def ler_planilha_excel(
    conteudo: bytes,
    nome_arquivo: str = "",
    sem_documento: list[dict] | None = None,
) -> dict[str, dict]:
    """Lê arquivo Excel (.xlsx / .xlsm) usando openpyxl."""
    import openpyxl

    resultado: dict[str, dict] = {}
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(conteudo), read_only=True, data_only=True)
    except Exception:
        return {}

    try:
        for sheet in workbook.worksheets:
            linhas = list(sheet.iter_rows(values_only=True))
            if not linhas:
                continue
            lidos = _extrair_registros(
                [list(linha) for linha in linhas],
                nome_arquivo=nome_arquivo,
                origem_padrao=sheet.title,
                sem_documento=sem_documento,
            )
            for cnpj, registro in lidos.items():
                resultado.setdefault(cnpj, registro)
    finally:
        workbook.close()

    return resultado


def _separador_csv(texto: str) -> str:
    primeira = next((linha for linha in texto.splitlines() if linha.strip()), "")
    contagens = {
        ";": primeira.count(";"),
        ",": primeira.count(","),
        "\t": primeira.count("\t"),
    }
    return max(contagens, key=lambda separador: contagens[separador])


def ler_planilha_csv(
    conteudo: bytes,
    nome_arquivo: str = "",
    sem_documento: list[dict] | None = None,
) -> dict[str, dict]:
    """Lê arquivo CSV ou TXT."""
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1", errors="replace")

    sep = _separador_csv(texto)
    # newline="" deixa o módulo csv tratar as quebras de linha. Com o
    # StringIO padrão, qualquer "\r" isolado (exportações antigas de Mac,
    # alguns ERPs e colagens de planilha) derrubava a importação inteira
    # com "_csv.Error: new-line character seen in unquoted field".
    try:
        leitor = csv.reader(io.StringIO(texto, newline=""), delimiter=sep)
        linhas = [linha for linha in leitor if any(c.strip() for c in linha)]
    except csv.Error as erro:
        alvo = f" {nome_arquivo}" if nome_arquivo else ""
        raise ValueError(
            f"Não foi possível ler a planilha{alvo}: o texto está fora do "
            f"formato CSV ({erro})."
        ) from erro
    if not linhas:
        return {}

    return _extrair_registros(
        linhas,
        nome_arquivo=nome_arquivo,
        separador=sep,
        sem_documento=sem_documento,
    )


def ler_planilha(conteudo: bytes, nome_arquivo: str = "") -> dict[str, dict]:
    """Detecta automaticamente formato Excel ou CSV e devolve dicionário por CNPJ."""
    por_cnpj, _ = ler_planilha_linhas(conteudo, nome_arquivo)
    return por_cnpj


def ler_planilha_linhas(
    conteudo: bytes,
    nome_arquivo: str = "",
) -> tuple[dict[str, dict], list[dict]]:
    """Como `ler_planilha`, mais as linhas que têm senha mas nenhum documento.

    Essas linhas não criam empresa — só servem para abrir o .pfx cujo nome foi
    escrito na planilha (`certificado-novo.pfx;MinhaSenha@2026`).
    """
    sem_documento: list[dict] = []
    nome = (nome_arquivo or "").lower()
    # Assinatura mágica do ZIP (PK\x03\x04) para arquivos .xlsx / .xlsm
    if nome.endswith((".xlsx", ".xlsm", ".xls")) or conteudo.startswith(b"PK\x03\x04"):
        resultado = ler_planilha_excel(conteudo, nome_arquivo, sem_documento)
        if resultado or sem_documento:
            return resultado, sem_documento
    return ler_planilha_csv(conteudo, nome_arquivo, sem_documento), sem_documento


def chave_de_arquivo(nome: str) -> str:
    """Chave de comparação entre o .pfx enviado e o nome citado na planilha."""
    base = re.sub(r"^.*[\\/]", "", (nome or "").strip()).lower()
    return _RE_ARQUIVO_CERTIFICADO.sub("", base)


def indexar_por_arquivo(lista_linhas: list[dict] | None) -> dict[str, dict]:
    """Índice das linhas da planilha pelo nome do arquivo de certificado.

    Serve para achar a senha quando o .pfx não tem CNPJ no nome
    (`certificado-novo.pfx`) ou quando o CNPJ da coluna foi digitado errado.
    """
    indice: dict[str, dict] = {}
    for linha in lista_linhas or []:
        arquivo = (linha.get("arquivo") or "").strip()
        if not arquivo:
            continue
        chave = chave_de_arquivo(arquivo)
        if chave:
            indice.setdefault(chave, linha)
    return indice


def fundir_planilhas_dados(
    planilhas_bytes: list[tuple[str, bytes]],
) -> tuple[dict[str, dict], list[str], list[dict]]:
    """Funde múltiplas planilhas em (por_cnpj, todas_senhas, lista_completa)."""
    fundido: dict[str, dict] = {}
    todas_senhas: list[str] = []
    lista_completa: list[dict] = []

    for nome_arquivo, conteudo in planilhas_bytes:
        lidos, orfas = ler_planilha_linhas(conteudo, nome_arquivo)
        vistos_na_planilha: set[int] = set()
        for cnpj, linha in lidos.items():
            # A mesma linha pode aparecer duas vezes em `lidos` quando o CNPJ da
            # coluna e o CNPJ do nome do arquivo diferem; ela é uma linha só.
            if id(linha) not in vistos_na_planilha:
                vistos_na_planilha.add(id(linha))
                lista_completa.append(linha)

            senha = (linha.get("senha") or "").strip()
            if senha and senha not in todas_senhas:
                todas_senhas.append(senha)

            if cnpj not in fundido:
                fundido[cnpj] = {
                    "cnpj": cnpj,
                    "razao_social": (linha.get("razao_social") or "").strip(),
                    "uf": (linha.get("uf") or "").strip().upper(),
                    "senhas": [],
                    "arquivos": [],
                    "validade": (linha.get("validade") or "").strip(),
                    "linha_csv": linha.get("linha"),
                }
            atual = fundido[cnpj]
            for chave in ("razao_social", "uf", "validade"):
                if not atual.get(chave) and linha.get(chave):
                    atual[chave] = linha[chave].strip() if isinstance(linha[chave], str) else linha[chave]
            if senha and senha not in atual["senhas"]:
                atual["senhas"].append(senha)
            arquivo = (linha.get("arquivo") or "").strip()
            if arquivo and arquivo not in atual["arquivos"]:
                atual["arquivos"].append(arquivo)

        # Linhas sem documento: entram só no índice por nome de arquivo e na
        # lista de senhas conhecidas — nunca criam empresa sozinhas.
        for linha in orfas:
            lista_completa.append(linha)
            senha = (linha.get("senha") or "").strip()
            if senha and senha not in todas_senhas:
                todas_senhas.append(senha)

    return fundido, todas_senhas, lista_completa


def buscar_senhas_por_nome(
    nome_empresa: str,
    registros: list[dict],
    min_score: float = 85.0,
) -> list[str]:
    """Encontra senhas de empresas na planilha por similaridade de nome."""
    if not nome_empresa:
        return []
    encontradas: list[tuple[float, str]] = []
    for reg in registros:
        razao = reg.get("razao_social") or ""
        senha = (reg.get("senha") or "").strip()
        if not razao or not senha:
            continue
        score = similaridade_nomes(nome_empresa, razao)
        if score >= min_score:
            encontradas.append((score, senha))

    encontradas.sort(key=lambda x: x[0], reverse=True)
    senhas: list[str] = []
    for _, s in encontradas:
        if s not in senhas:
            senhas.append(s)
    return senhas
