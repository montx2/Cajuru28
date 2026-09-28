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


def _normalizar_cabecalho(celula: Any) -> str:
    texto = remover_acentos(str(celula or "")).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", texto).strip("_")


def _indice_coluna(cabecalho: list[str], nomes: tuple[str, ...]) -> int | None:
    for nome in nomes:
        if nome in cabecalho:
            return cabecalho.index(nome)
    # Correspondência parcial para cabeçalhos compostos
    for idx, col in enumerate(cabecalho):
        for nome in nomes:
            if nome in col:
                return idx
    return None


def ler_planilha_excel(conteudo: bytes, nome_arquivo: str = "") -> dict[str, dict]:
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

            # Localiza linha de cabeçalho nas primeiras 100 linhas
            header_row_idx = None
            indices = {}
            for row_idx, row in enumerate(linhas[:100]):
                cab = [_normalizar_cabecalho(c) for c in row if c is not None]
                idx_cnpj = _indice_coluna(cab, ("cnpj_cpf", "cnpj", "cpf", "documento", "doc", "cnpj_cpf_cliente"))
                idx_senha = _indice_coluna(cab, ("senha", "password", "senha_certificado", "senha_a1", "senha_do_certificado", "senhas"))
                if idx_cnpj is not None or idx_senha is not None:
                    header_row_idx = row_idx
                    indices = {
                        "cnpj": idx_cnpj,
                        "senha": idx_senha,
                        "razao": _indice_coluna(cab, ("razao_social", "razaosocial", "nome", "empresa", "cliente", "razao", "nome_empresarial")),
                        "uf": _indice_coluna(cab, ("uf", "estado")),
                        "validade": _indice_coluna(cab, ("validade", "data_validade", "vencimento")),
                    }
                    break

            if header_row_idx is not None and indices.get("cnpj") is not None:
                for row_num, row in enumerate(linhas[header_row_idx + 1 :], start=header_row_idx + 2):
                    if not row or all(c is None or str(c).strip() == "" for c in row):
                        continue

                    def celula(k: str) -> str:
                        pos = indices.get(k)
                        if pos is not None and pos < len(row):
                            val = row[pos]
                            if val is None:
                                return ""
                            if isinstance(val, (int, float)) and not isinstance(val, bool):
                                return str(int(val)) if float(val).is_integer() else str(val)
                            return str(val).strip()
                        return ""

                    doc_raw = celula("cnpj")
                    try:
                        cnpj = normalizar_documento(doc_raw)
                    except ValueError:
                        continue
                    if not validar_documento(cnpj) or cnpj in resultado:
                        continue

                    uf = celula("uf").upper()
                    if uf and uf not in _UFS_VALIDAS:
                        uf = ""

                    resultado[cnpj] = {
                        "cnpj": cnpj,
                        "razao_social": celula("razao"),
                        "uf": uf,
                        "senha": celula("senha"),
                        "validade": celula("validade"),
                        "origem": nome_arquivo or sheet.title,
                        "linha": row_num,
                    }
            else:
                # Tentativa de leitura sem cabeçalho (ex: Coluna A = CNPJ, Coluna B = Senha)
                for row_num, row in enumerate(linhas, start=1):
                    if not row or len(row) < 2:
                        continue
                    doc_raw = str(row[0] or "").strip()
                    try:
                        cnpj = normalizar_documento(doc_raw)
                    except ValueError:
                        continue
                    if not validar_documento(cnpj) or cnpj in resultado:
                        continue
                    senha_val = str(row[1] or "").strip() if len(row) >= 2 else ""
                    uf_val = str(row[2] or "").strip().upper() if len(row) >= 3 else ""
                    if uf_val not in _UFS_VALIDAS:
                        uf_val = ""
                    resultado[cnpj] = {
                        "cnpj": cnpj,
                        "razao_social": "",
                        "uf": uf_val,
                        "senha": senha_val,
                        "origem": nome_arquivo or sheet.title,
                        "linha": row_num,
                    }
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


def ler_planilha_csv(conteudo: bytes, nome_arquivo: str = "") -> dict[str, dict]:
    """Lê arquivo CSV ou TXT."""
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError:
        texto = conteudo.decode("latin-1", errors="replace")

    sep = _separador_csv(texto)
    leitor = csv.reader(io.StringIO(texto), delimiter=sep)
    linhas = [linha for linha in leitor if any(c.strip() for c in linha)]
    if not linhas:
        return {}

    cabecalho = [_normalizar_cabecalho(celula) for celula in linhas[0]]
    indice = {
        "cnpj": _indice_coluna(cabecalho, ("cnpj_cpf", "cnpj", "cpf", "documento", "doc", "cnpj_cpf_cliente")),
        "senha": _indice_coluna(cabecalho, ("senha", "password", "senha_certificado", "senha_a1", "senhas")),
        "razao": _indice_coluna(cabecalho, ("razao_social", "razaosocial", "nome", "empresa", "cliente", "razao", "nome_empresarial")),
        "uf": _indice_coluna(cabecalho, ("uf", "estado")),
        "validade": _indice_coluna(cabecalho, ("validade", "data_validade", "vencimento")),
    }

    resultado: dict[str, dict] = {}
    if indice["cnpj"] is not None:
        for numero, linha in enumerate(linhas[1:], start=2):
            def valor(chave: str) -> str:
                i = indice[chave]
                return linha[i].strip() if i is not None and i < len(linha) else ""

            try:
                cnpj = normalizar_documento(valor("cnpj"))
            except ValueError:
                continue
            if not validar_documento(cnpj) or cnpj in resultado:
                continue
            uf = valor("uf").upper()
            if uf and uf not in _UFS_VALIDAS:
                uf = ""
            resultado[cnpj] = {
                "cnpj": cnpj,
                "razao_social": valor("razao"),
                "uf": uf,
                "senha": valor("senha"),
                "validade": valor("validade"),
                "origem": nome_arquivo,
                "linha": numero,
            }
    else:
        # Sem cabeçalho: formato documento;senha (ou documento;senha;uf)
        for numero, linha in enumerate(linhas, start=1):
            if len(linha) < 2:
                continue
            try:
                cnpj = normalizar_documento(linha[0])
            except ValueError:
                continue
            if not validar_documento(cnpj) or cnpj in resultado:
                continue
            uf = linha[2].strip().upper() if len(linha) >= 3 else ""
            if uf not in _UFS_VALIDAS:
                uf = ""
            resultado[cnpj] = {
                "cnpj": cnpj,
                "razao_social": "",
                "uf": uf,
                "senha": linha[1].strip(),
                "origem": nome_arquivo,
                "linha": numero,
            }

    return resultado


def ler_planilha(conteudo: bytes, nome_arquivo: str = "") -> dict[str, dict]:
    """Detecta automaticamente formato Excel ou CSV e devolve dicionário por CNPJ."""
    nome = (nome_arquivo or "").lower()
    # Assinatura mágica do ZIP (PK\x03\x04) para arquivos .xlsx / .xlsm
    if nome.endswith((".xlsx", ".xlsm", ".xls")) or conteudo.startswith(b"PK\x03\x04"):
        resultado = ler_planilha_excel(conteudo, nome_arquivo)
        if resultado:
            return resultado
    return ler_planilha_csv(conteudo, nome_arquivo)


def fundir_planilhas_dados(
    planilhas_bytes: list[tuple[str, bytes]],
) -> tuple[dict[str, dict], list[str], list[dict]]:
    """Funde múltiplas planilhas em (por_cnpj, todas_senhas, lista_completa)."""
    fundido: dict[str, dict] = {}
    todas_senhas: list[str] = []
    lista_completa: list[dict] = []

    for nome_arquivo, conteudo in planilhas_bytes:
        lidos = ler_planilha(conteudo, nome_arquivo)
        for cnpj, linha in lidos.items():
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
                    "linha_csv": linha.get("linha"),
                }
            atual = fundido[cnpj]
            for chave in ("razao_social", "uf"):
                if not atual.get(chave) and linha.get(chave):
                    atual[chave] = linha[chave]
            if senha and senha not in atual["senhas"]:
                atual["senhas"].append(senha)

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
