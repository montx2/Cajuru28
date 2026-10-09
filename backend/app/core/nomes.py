"""Razão social aproveitável — o que é nome de empresa e o que é ruído.

Três fontes de nome convivem na importação em massa: o subject do `.pfx`, a
planilha de inventário e o cadastro do escritório (Acessórias / Receita). As
duas primeiras trazem junto a cadeia emissora do certificado (`ICP-Brasil`,
`AC Soluti`) e rótulos de coluna (`Razão social:`, `Nome empresarial:`). Um
lote de 203 certificados lidos por essa régua cria 203 empresas com o mesmo
nome — e o pior não é a estética: a tela de atenção deixa de dizer *qual*
cliente é, e nada depois corrigia o cadastro.

Estas funções são a régua única:

- `nome_usavel` limpa rótulo/marca de cadeia e devolve `""` quando sobra ruído;
- `precisa_completar_nome` diz quando o valor gravado não identifica a empresa
  (vazio, ruído ou placeholder `Empresa <CNPJ>`) e vale consultar o cadastro.
"""

from __future__ import annotations

import re
import unicodedata

from app.core.documentos import normalizar_documento

# Marcas de cadeia e de autoridade certificadoras. Comparadas por `_compacto`
# (sem acento, sem pontuação, maiúsculas), então "ICP-Brasil", "icp brasil" e
# "ICPBrasil" são a mesma chave. Servem também na leitura de planilha, em que a
# coluna "emissor" não pode virar senha nem razão social.
AUTORIDADES_CERTIFICADORAS = {
    "ICPBRASIL",
    "ACRAIZ",
    "AC",
    "AUTORIDADECERTIFICADORA",
    "AUTORIDADECERTIFICADORADOBRASIL",
    "SERPRO",
    "SRF",
    "RECEITAFEDERAL",
    "SECRETARIADARECEITAFEDERAL",
    "CERTISIGN",
    "SOLUTI",
    "SOLUTICERTIFICADORA",
    "SAFEWEB",
    "VALID",
    "VALIDCERTIFICADORA",
    "BOAVISTA",
    "BOAVISTASCD",
    "IMPRENSAOFICIAL",
    "IMPRENSAOFICIALSP",
    "FENACON",
    "FENACOR",
    "SESCON",
    "SESCONSP",
    "SESCONMG",
    "SESCONRJ",
    "SESCONSC",
    "SESCONRS",
    "CDL",
    "OAB",
    "SINCOR",
    "ACNOTARIAL",
    "NOTARIAL",
    "ACJUS",
    "CERTIFICA",
    "CERTIFICAMINAS",
    "CASADASMOEDAS",
    "SERASA",
    "AMPRSP",
    "DIGITALSIGN",
    "DIGITALSIGNID",
    "PRESIDENCIA",
}

# Rótulos de coluna/subject que costumam vir ANTES do nome real. A ordem
# importa: o mais específico primeiro, para "Razão social do contribuinte" não
# perder só o começo e deixar "do contribuinte" como se fosse a empresa.
_ROTULOS = (
    "razao social do contribuinte",
    "razao social da empresa",
    "razao social",
    "razao economica",
    "nome empresarial",
    "razao",
    "nome",
    "empresa",
    "cliente",
    "contribuinte",
    "titular",
    "e-cnpj",
    "e-cpf",
    "cnpj/cpf",
    "cnpj",
    "cpf",
    "documento",
)

# Valores que sozinhos não dizem nada: cabeçalho comido como linha de dado,
# coluna repetida em todo o lote, sigla do tipo de certificado.
_OBSTACULOS = {
    "RAZAOSOCIAL",
    "RAZAOSOCIALECONOMICA",
    "NOMEEMPRESARIAL",
    "NOME",
    "EMPRESA",
    "EMPRESAS",
    "CLIENTE",
    "TITULAR",
    "CONTRIBUINTE",
    "DOCUMENTO",
    "CERTIFICADODIGITAL",
    "CERTIFICADO",
    "CERTIFICADOA",
    "A1",
    "A3",
    "S",
    "N",
    "NA",
    "INDEFINIDO",
    "SIGLA",
    "ESTADO",
    "UF",
    "PENDENTE",
    "INFORME",
    "TOTAL",
    "SUBTOTAL",
    "OBS",
    "OBSERVACAO",
}


def sem_acento(texto: str | None) -> str:
    if not texto:
        return ""
    normalizado = unicodedata.normalize("NFKD", unicodedata.normalize("NFKC", str(texto)))
    return "".join(caractere for caractere in normalizado if not unicodedata.combining(caractere))


def _compacto(texto: str | None) -> str:
    """Chave de comparação: maiúsculas, sem acento e sem qualquer símbolo."""
    return re.sub(r"[^A-Z0-9]", "", sem_acento(texto).upper())


def _documento_compacto(valor: str | None) -> str:
    try:
        return _compacto(normalizar_documento(valor or ""))
    except ValueError:
        return ""


def _marca_valida(marca: str) -> bool:
    return _compacto(marca) in AUTORIDADES_CERTIFICADORAS


# Letras com acento que podem aparecer num rótulo escrito à mão ("Razão
# social", "Nome Empresàrial"). IGNORECASE cuida das maiúsculas.
_ACENTUADAS = {
    "a": "àáâãäå",
    "e": "èéêë",
    "i": "ìíîï",
    "o": "òóôõöø",
    "u": "ùúûü",
    "c": "ç",
    "n": "ñ",
    "y": "ýÿ",
}


def _padrao_palavra(palavra: str) -> str:
    """Uma letra com acento no texto não impede a comparação: `a` → `[aàáâãäå]`."""
    saida: list[str] = []
    for caractere in palavra:
        base = sem_acento(caractere).lower()
        if base in _ACENTUADAS:
            saida.append(f"[{re.escape(base)}{re.escape(_ACENTUADAS[base])}]")
        elif base.isalnum():
            saida.append(re.escape(base))
        else:
            saida.append(re.escape(caractere))
    return "".join(saida)


def _padrao_rotulo(rotulo: str) -> str:
    r"""`razao social` → `razao[\s\-]?social`: espaço, hífen ou nada entre as palavras."""
    return r"[\s\-]?".join(_padrao_palavra(parte) for parte in sem_acento(rotulo).split())


_ROTULOS_ALTERNATIVA = "|".join(_padrao_rotulo(rotulo) for rotulo in _ROTULOS)
# O rótulo só é descartado com separador explícito ("Razão social: X"). Sem
# isso, "EMPRESA DE ONIBUS SAO VICENTE" — nome verdadeiro — perderia o começo.
_RE_ROTULO = re.compile(rf"^(?:{_ROTULOS_ALTERNATIVA})\s*[:\-–]\s*", re.IGNORECASE)
_RE_MARCA_CABECA = re.compile(
    rf"^(?:{_padrao_palavra('icp')}[\s\-]?{_padrao_palavra('brasil')}|{_padrao_rotulo('autoridade certificadora')})[\s\-/:,]*",
    re.IGNORECASE,
)
_RE_AC_MARCA_CABECA = re.compile(r"^ac[\s\-/:,]+(?P<marca>[A-ZÀ-Ý]\w*)[\s\-/:,]*", re.IGNORECASE)
_RE_MARCA_RABO = re.compile(
    rf"[\s\-/:,]*(?:{_padrao_palavra('icp')}[\s\-]?{_padrao_palavra('brasil')}|{_padrao_rotulo('autoridade certificadora')})\s*$",
    re.IGNORECASE,
)
_RE_AC_MARCA_RABO = re.compile(r"[\s\-/:,]+ac[\s\-]+(?P<marca>[A-ZÀ-Ý]\w*)\s*$", re.IGNORECASE)
_RE_DOCUMENTO_RABO = re.compile(
    r"\s*[:\-–]?\s*(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{3}\.\d{3}\.\d{3}-\d{2}|\d{14}|\d{11})\s*$"
)
_RE_DOCUMENTO_CABECA = re.compile(
    r"^\s*(?:cnpj|cpf)?\s*[:\-]?\s*"
    r"(?:\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|\d{14}|\d{3}\.\d{3}\.\d{3}-\d{2}|\d{11})\s*[:\-–]?\s*",
    re.IGNORECASE,
)
_RE_EXTENSAO_ARQUIVO = re.compile(r"\.(pfx|p12|cer|crt|pem|key|enc|zip|pdf|txt|csv|xml)$", re.IGNORECASE)
_RE_PALAVRAS = re.compile(r"[^\W\d_]+", re.UNICODE)


def eh_marca_de_cadeia(texto: str | None) -> bool:
    """`ICP-Brasil`, `AC Soluti`, `Autoridade Certificadora …` — o emissor do A1.

    Compara o valor inteiro: `SOLUTI CONSULTORIA LTDA` é uma empresa que pode
    existir e não pode ser descartada só por começar com nome de AC. Usada aqui
    e na leitura de planilha (a coluna "emissor" nunca é senha).
    """
    bruto = (texto or "").strip()
    if not bruto:
        return False
    if _compacto(bruto) in AUTORIDADES_CERTIFICADORAS:
        return True
    palavras = [palavra for palavra in re.split(r"[^A-Za-z0-9]+", sem_acento(bruto)) if palavra]
    if palavras and palavras[0].upper() in {"AC", "ICP"}:
        # "AC Soluti", "ICP-Brasil", "ICP Brasil / AC SERPRO": o que sobra
        # precisa ser marca também (ou conector curto, como "AC"/"RAIZ").
        return all(
            _compacto(palavra) in AUTORIDADES_CERTIFICADORAS or len(palavra) <= 4
            for palavra in palavras
        )
    return False


def limpar_nome(valor: str | None) -> str:
    """Tira rótulo, marca de cadeia e o documento colado — sobra o nome, se houver."""
    texto = re.sub(r"\s+", " ", str(valor or "")).strip()
    if not texto:
        return ""
    for _ in range(4):
        limpo = _RE_ROTULO.sub("", texto, count=1)
        limpo = _RE_MARCA_CABECA.sub("", limpo, count=1)
        ac_cabeca = _RE_AC_MARCA_CABECA.match(limpo)
        if ac_cabeca and _marca_valida(ac_cabeca.group("marca")):
            limpo = limpo[ac_cabeca.end() :]
        limpo = limpo.strip()
        if limpo.casefold() == texto.casefold():
            break
        texto = limpo
    texto = _RE_MARCA_RABO.sub("", texto)
    ac_rabo = _RE_AC_MARCA_RABO.search(texto)
    if ac_rabo and _marca_valida(ac_rabo.group("marca")):
        texto = texto[: ac_rabo.start()]
    texto = _RE_DOCUMENTO_RABO.sub("", texto)
    texto = _RE_DOCUMENTO_CABECA.sub("", texto)
    return re.sub(r"\s{2,}", " ", texto).strip(" -–—/:,;")


def nome_usavel(valor: str | None, *, documento: str = "") -> str:
    """Nome de empresa aproveitável, ou `""` quando sobra ruído.

    `documento` (CNPJ/CPF canônico) fecha o caso do subject cujo `CN` é só o
    próprio número: sem esse parâmetro, "12345678000195" viraria razão social.
    """
    limpo = limpar_nome(valor)
    if not limpo:
        return ""
    if _RE_EXTENSAO_ARQUIVO.search(limpo):
        return ""  # "21260898000107.pfx" é arquivo, não empresa
    chave = _compacto(limpo)
    if len(chave) < 3 or chave in _OBSTACULOS or chave in AUTORIDADES_CERTIFICADORAS:
        return ""
    palavras = [palavra for palavra in _RE_PALAVRAS.findall(sem_acento(limpo).upper()) if len(palavra) >= 2]
    if not any(
        _compacto(palavra) not in AUTORIDADES_CERTIFICADORAS and _compacto(palavra) not in _OBSTACULOS
        for palavra in palavras
    ):
        return ""  # só dígitos, só sigla de cadeia ou só rótulo
    alvo = _compacto(documento) or _documento_compacto(documento)
    if alvo and chave == alvo:
        return ""
    if eh_marca_de_cadeia(limpo):
        return ""
    original = _compacto(valor)
    comeca_com_cadeia = original.startswith(("ICPBRASIL", "AUTORIDADECERTIFICADORA")) or any(
        original.startswith(f"AC{marca}") for marca in AUTORIDADES_CERTIFICADORAS if marca != "AC"
    )
    if comeca_com_cadeia and len([p for p in palavras if len(p) >= 3]) < 2:
        # "AC Soluti Maceió" viraria "Maceió": sobrou só a cidade da AC.
        return ""
    return limpo[:255]


def nome_provisorio(documento: str) -> str:
    """Nome de espera, honesto: mostra o CNPJ e admite que falta o cadastro."""
    return f"Empresa {documento}" if documento else ""


def eh_nome_provisorio(valor: str | None, documento: str = "") -> bool:
    """True para o placeholder criado pela importação — corrigível, não definitivo."""
    chave = _compacto(valor)
    if not chave:
        return True
    if chave in {
        "EMPRESASEMTITULARIDENTIFICADO",
        "CERTIFICADOSEMTITULARIDENTIFICADO",
        "SEMTITULARIDENTIFICADO",
    }:
        return True
    alvo = _compacto(documento) or _documento_compacto(documento)
    if not alvo:
        return False
    return bool(re.fullmatch(rf"EMPRESA{re.escape(alvo)}", chave))


def precisa_completar_nome(valor: str | None, documento: str = "") -> bool:
    """O cadastro local não tem nome de verdade: ruído, vazio ou placeholder."""
    if not nome_usavel(valor, documento=documento):
        return True
    return eh_nome_provisorio(valor, documento)
