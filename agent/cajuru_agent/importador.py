"""Importação **local** de certificados A1 para a estação Windows.

Este módulo existe para resolver o primeiro dia de operação de um escritório
que já tem uma pasta de ``.pfx/.p12`` e planilhas com cliente, senha e
validade. Ele faz somente a preparação local necessária para o Assinador
SERPRO enxergar os certificados:

* lê CSV/TXT/XLSX/XLSM localmente;
* associa cada arquivo a uma senha declarada por CNPJ ou nome do cliente;
* mostra uma prévia sem revelar senha;
* importa no repositório ``CurrentUser\\My`` apenas depois de ``--executar``;
* nunca envia PFX, senha ou chave privada ao Cajuru28.

A importação usa ``Get-PfxData``/``Import-PfxCertificate`` do Windows. A senha
e o caminho seguem pelo *stdin* do PowerShell, nunca por argumento de linha de
comando, variável de ambiente, arquivo temporário ou log. As senhas ficam em
memória apenas pelo tempo necessário para abrir o arquivo.

Não há tentativa por senhas genéricas nem "força bruta". Se uma senha não está
associada de forma inequívoca na planilha, o arquivo fica pendente para que o
operador corrija o mapeamento antes de importar.
"""

from __future__ import annotations

import csv
import io
import json
import platform
import re
import subprocess
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Iterable


class ImportacaoLocalError(RuntimeError):
    """Erro seguro para mostrar ao operador, sem ecoar senha."""


@dataclass(frozen=True)
class RegistroPlanilha:
    """Uma linha útil de uma planilha local.

    ``senha`` não entra em repr, mensagens, JSON nem logs. A classe é mantida
    pequena de propósito: estes são os únicos dados de que o importador local
    precisa para associar e abrir um PFX.
    """

    documento: str = ""
    nome: str = ""
    senha: str = field(default="", repr=False)
    validade: date | None = None
    origem: str = ""
    linha: int = 0


@dataclass(frozen=True)
class ClientePlanilha:
    """Registros de uma mesma empresa já unidos entre várias planilhas."""

    documento: str = ""
    nome: str = ""
    senhas: tuple[str, ...] = field(default_factory=tuple, repr=False)
    validade: date | None = None
    origens: tuple[str, ...] = ()

    @property
    def identificacao(self) -> str:
        return self.nome or self.documento or "Cliente não identificado"


@dataclass(frozen=True)
class ItemPlano:
    """Um arquivo encontrado e sua decisão de importação.

    A referência ao cliente fica privada porque ela inclui a(s) senha(s). Os
    demais campos são seguros para exibição e serialização.
    """

    arquivo: Path
    status: str
    mensagem: str
    cliente: str = ""
    documento: str = ""
    validade_declarada: date | None = None
    _referencia: ClientePlanilha | None = field(default=None, repr=False, compare=False)

    @property
    def pronto(self) -> bool:
        return self.status == "pronto"


@dataclass(frozen=True)
class ResultadoItem:
    """Resultado sem segredo de uma tentativa de importação local."""

    arquivo: Path
    status: str
    mensagem: str
    cliente: str = ""
    documento: str = ""
    validade_declarada: date | None = None
    validade_certificado: date | None = None
    thumbprint: str = ""
    tentativas: int = 0

    def para_saida(self) -> dict[str, str | int | None]:
        """Formato seguro para ``--json``; não há senha aqui."""
        return {
            "arquivo": self.arquivo.name,
            "status": self.status,
            "mensagem": self.mensagem,
            "cliente": self.cliente,
            "documento": self.documento,
            "validade_declarada": self.validade_declarada.isoformat() if self.validade_declarada else None,
            "validade_certificado": self.validade_certificado.isoformat() if self.validade_certificado else None,
            "thumbprint": self.thumbprint,
            "tentativas": self.tentativas,
        }


# Cabeçalhos que aparecem em planilhas reais. Tudo é normalizado sem acento e
# sem pontuação antes de consultar esta tabela.
_COLUNAS: dict[str, tuple[str, ...]] = {
    "documento": (
        "cnpj",
        "cpf",
        "cnpj_cpf",
        "cpf_cnpj",
        "documento",
        "doc",
        "inscricao",
    ),
    "nome": (
        "razao_social",
        "razaosocial",
        "razao",
        "nome",
        "cliente",
        "empresa",
        "nome_cliente",
        "nome_empresarial",
    ),
    "senha": (
        "senha",
        "senhas",
        "password",
        "senha_a1",
        "senha_certificado",
        "senha_do_certificado",
        "senha_pfx",
        "senha_p12",
    ),
    "validade": (
        "validade",
        "data_validade",
        "vencimento",
        "data_vencimento",
        "validade_certificado",
        "expira_em",
    ),
}

_SUFFIXOS_NOME = {
    "LTDA",
    "ME",
    "EPP",
    "EIRELI",
    "MEI",
    "SA",
    "S",
    "A",
    "SLU",
    "SERVICOS",
    "SERVICO",
    "COMERCIO",
    "COMERCIAL",
    "CERTIFICADO",
    "CERT",
    "A1",
    "PFX",
    "P12",
    "NOVO",
    "ATUAL",
    "ANTIGO",
}

_PADRAO_DOCUMENTO = re.compile(r"(?<![0-9])([0-9]{11}|[0-9]{14})(?![0-9])")


# ---------------------------------------------------------------------------
# Leitura local das planilhas
# ---------------------------------------------------------------------------


def _chave(texto: object) -> str:
    bruto = str(texto or "")
    sem_acento = "".join(
        parte
        for parte in unicodedata.normalize("NFKD", bruto)
        if not unicodedata.combining(parte)
    )
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def _texto(celula: object) -> str:
    if celula is None:
        return ""
    if isinstance(celula, bool):
        return ""
    if isinstance(celula, int):
        return str(celula)
    if isinstance(celula, float):
        return str(int(celula)) if celula.is_integer() else str(celula)
    if isinstance(celula, (date, datetime)):
        return celula.date().isoformat() if isinstance(celula, datetime) else celula.isoformat()
    return str(celula).strip()


def _documento(valor: object) -> str:
    digitos = re.sub(r"\D", "", _texto(valor))
    return digitos if len(digitos) in {11, 14} else ""


def _data(valor: object) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = _texto(valor)
    if not texto:
        return None
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto[:10], formato).date()
        except ValueError:
            continue
    return None


def _indices_cabecalho(linha: list[object]) -> dict[str, int]:
    chaves = [_chave(celula) for celula in linha]
    indices: dict[str, int] = {}
    for campo, aliases in _COLUNAS.items():
        for indice, chave in enumerate(chaves):
            if chave in aliases or any(alias in chave for alias in aliases):
                indices[campo] = indice
                break
    return indices


def _registros_de_linhas(
    linhas: Iterable[tuple[int, list[object]]],
    *,
    origem: str,
) -> list[RegistroPlanilha]:
    """Encontra um cabeçalho ou aceita o formato simples CNPJ;SENHA.

    Não supõe que as duas planilhas tenham o mesmo layout: uma pode ter CNPJ e
    senha, outra cliente e validade. A união acontece depois pela identidade
    que estiver disponível.
    """
    materializadas = [(numero, list(valores)) for numero, valores in linhas]
    if not materializadas:
        return []

    cabecalho: dict[str, int] = {}
    inicio = 0
    for indice, (_, linha) in enumerate(materializadas[:40]):
        candidato = _indices_cabecalho(linha)
        # A segunda planilha costuma trazer apenas CNPJ + validade. Ela é
        # complementar, não uma planilha de senha inválida; aceite cabeçalho
        # quando houver identidade e pelo menos um dado que sabemos combinar.
        if ("documento" in candidato or "nome" in candidato) and (
            "senha" in candidato or "validade" in candidato
        ):
            cabecalho = candidato
            inicio = indice + 1
            break

    if not cabecalho:
        # Formato mínimo compatível com planilhas antigas: CNPJ;senha[;validade]
        # ou nome;senha[;validade]. Não tenta adivinhar colunas além disso.
        primeira = materializadas[0][1]
        if len(primeira) < 2:
            return []
        primeiro_e_documento = bool(_documento(primeira[0]))
        cabecalho = {
            "documento": 0 if primeiro_e_documento else -1,
            "nome": -1 if primeiro_e_documento else 0,
            "senha": 1,
            "validade": 2,
        }
        inicio = 0

    def valor(linha: list[object], campo: str) -> object:
        indice = cabecalho.get(campo, -1)
        return linha[indice] if 0 <= indice < len(linha) else ""

    registros: list[RegistroPlanilha] = []
    for numero, linha in materializadas[inicio:]:
        if not any(_texto(celula) for celula in linha):
            continue
        documento = _documento(valor(linha, "documento"))
        nome = _texto(valor(linha, "nome"))[:255]
        senha = _texto(valor(linha, "senha"))
        if not documento and not nome:
            continue
        registros.append(
            RegistroPlanilha(
                documento=documento,
                nome=nome,
                senha=senha,
                validade=_data(valor(linha, "validade")),
                origem=origem,
                linha=numero,
            )
        )
    return registros


def _linhas_csv(caminho: Path) -> list[tuple[int, list[object]]]:
    try:
        texto = caminho.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        texto = caminho.read_text(encoding="latin-1")
    except OSError as exc:
        raise ImportacaoLocalError(f"Não foi possível ler a planilha '{caminho.name}'.") from exc

    try:
        dialecto = csv.Sniffer().sniff(texto[:8192], delimiters=";,\t|")
    except csv.Error:
        class Padrao(csv.excel):
            delimiter = ";" if texto.count(";") >= texto.count(",") else ","

        dialecto = Padrao()
    try:
        leitor = csv.reader(io.StringIO(texto, newline=""), dialect=dialecto)
        return [(numero, linha) for numero, linha in enumerate(leitor, start=1)]
    except csv.Error as exc:
        raise ImportacaoLocalError(
            f"A planilha '{caminho.name}' não está em CSV válido. Exporte novamente em UTF-8."
        ) from exc


def _registros_excel(caminho: Path) -> list[RegistroPlanilha]:
    try:
        import openpyxl
    except ImportError as exc:  # pragma: no cover - coberto pela dependência do Agent
        raise ImportacaoLocalError(
            "Leitura de Excel indisponível. Reinstale o Cajuru Agent ou exporte a planilha em CSV."
        ) from exc
    try:
        pasta = openpyxl.load_workbook(caminho, read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - arquivo externo pode estar corrompido
        raise ImportacaoLocalError(
            f"Não foi possível abrir '{caminho.name}' como Excel. Salve uma cópia em .xlsx ou CSV."
        ) from exc

    registros: list[RegistroPlanilha] = []
    try:
        # Cada aba recebe seu próprio cabeçalho. Concatenar as linhas antes de
        # identificar o cabeçalho faria a aba seguinte parecer dados da primeira.
        for aba in pasta.worksheets:
            linhas = [
                (numero, list(valores))
                for numero, valores in enumerate(aba.iter_rows(values_only=True), start=1)
            ]
            registros.extend(_registros_de_linhas(linhas, origem=f"{caminho.name} · {aba.title}"))
    finally:
        pasta.close()
    return registros


def ler_planilha(caminho: Path) -> list[RegistroPlanilha]:
    """Lê uma planilha local suportada, preservando a senha apenas em memória."""
    if not caminho.exists() or not caminho.is_file():
        raise ImportacaoLocalError(f"Planilha não encontrada: '{caminho}'.")
    extensao = caminho.suffix.lower()
    if extensao in {".xlsx", ".xlsm"}:
        return _registros_excel(caminho)
    if extensao in {".csv", ".txt", ".tsv"}:
        linhas = _linhas_csv(caminho)
    elif extensao == ".xls":
        raise ImportacaoLocalError(
            f"'{caminho.name}' está no formato .xls antigo. Abra e salve como .xlsx ou CSV antes de importar."
        )
    else:
        raise ImportacaoLocalError(
            f"Formato de planilha não suportado: '{caminho.name}'. Use .xlsx, .xlsm, .csv, .txt ou .tsv."
        )
    return _registros_de_linhas(linhas, origem=caminho.name)


# ---------------------------------------------------------------------------
# União e associação determinística PFX → planilha
# ---------------------------------------------------------------------------


def _nome_chave(valor: str) -> str:
    """Chave conservadora para unir linhas sem CNPJ entre duas planilhas.

    Aqui não removemos ``LTDA``/``ME``: duas linhas sem documento e com nomes
    parecidos nunca podem acabar no mesmo conjunto de senhas por conveniência.
    """
    texto = "".join(
        parte
        for parte in unicodedata.normalize("NFKD", str(valor or ""))
        if not unicodedata.combining(parte)
    ).upper()
    return " ".join(parte for parte in re.split(r"[^A-Z0-9]+", texto) if parte)


def _nome_normalizado(valor: str) -> str:
    texto = _nome_chave(valor)
    texto = re.sub(r"\b(PFX|P12)\b", " ", texto)
    texto = _PADRAO_DOCUMENTO.sub(" ", texto)
    texto = re.sub(r"\b20\d{2}\b", " ", texto)
    partes = [parte for parte in texto.split() if parte and parte not in _SUFFIXOS_NOME]
    return " ".join(partes)


def _pontuar_nome(nome_arquivo: str, nome_cliente: str) -> float:
    alvo = _nome_normalizado(nome_cliente)
    arquivo = _nome_normalizado(nome_arquivo)
    if not alvo or not arquivo:
        return 0.0
    if alvo == arquivo or alvo in arquivo:
        return 100.0
    tokens_alvo = set(alvo.split())
    tokens_arquivo = set(arquivo.split())
    cobertura = len(tokens_alvo & tokens_arquivo) / max(1, len(tokens_alvo))
    sequencia = SequenceMatcher(None, alvo, arquivo).ratio()
    return max(100 * cobertura, 100 * sequencia)


def unir_registros(registros: Iterable[RegistroPlanilha]) -> list[ClientePlanilha]:
    """Une planilhas complementares por documento, caindo para nome exato.

    Nunca usa similaridade nesta fase: duas empresas com nomes parecidos não
    podem compartilhar senha. Similaridade só escolhe o *arquivo* depois que
    cada registro já é um cliente independente.
    """
    acumulados: list[dict] = []
    por_documento: dict[str, dict] = {}
    por_nome: dict[str, dict] = {}

    for registro in registros:
        chave_nome = _nome_chave(registro.nome)
        atual = (
            por_documento.get(registro.documento)
            if registro.documento
            else None
        ) or (por_nome.get(chave_nome) if chave_nome else None)
        if atual is None:
            atual = {
                "documento": registro.documento,
                "nome": registro.nome,
                "senhas": [],
                "validade": registro.validade,
                "origens": [],
            }
            acumulados.append(atual)
        if registro.documento and not atual["documento"]:
            atual["documento"] = registro.documento
        if registro.nome and not atual["nome"]:
            atual["nome"] = registro.nome
        if registro.senha and registro.senha not in atual["senhas"]:
            atual["senhas"].append(registro.senha)
        if registro.validade and (atual["validade"] is None or registro.validade > atual["validade"]):
            atual["validade"] = registro.validade
        origem_linha = f"{registro.origem}:{registro.linha}"
        if origem_linha not in atual["origens"]:
            atual["origens"].append(origem_linha)
        if atual["documento"]:
            por_documento[atual["documento"]] = atual
        nome_atual = _nome_chave(atual["nome"])
        if nome_atual:
            por_nome[nome_atual] = atual

    return [
        ClientePlanilha(
            documento=item["documento"],
            nome=item["nome"],
            senhas=tuple(item["senhas"]),
            validade=item["validade"],
            origens=tuple(item["origens"]),
        )
        for item in acumulados
    ]


def _arquivos_pfx(pasta: Path) -> list[Path]:
    if not pasta.exists() or not pasta.is_dir():
        raise ImportacaoLocalError(f"Pasta de certificados não encontrada: '{pasta}'.")
    arquivos = sorted(
        arquivo
        for arquivo in pasta.rglob("*")
        if arquivo.is_file() and arquivo.suffix.lower() in {".pfx", ".p12"}
    )
    if len(arquivos) > 2_000:
        raise ImportacaoLocalError(
            "A pasta tem mais de 2.000 certificados. Separe em lotes menores para conferir a prévia com segurança."
        )
    return arquivos


def _escolher_cliente(arquivo: Path, clientes: list[ClientePlanilha]) -> tuple[ClientePlanilha | None, str]:
    bruto = arquivo.stem
    # Trocar tudo que não é dígito por espaço conserva as fronteiras do CNPJ:
    # `CLIENTE_12345678000195_2026` tem dois blocos distintos, em vez de uma
    # sequência artificial de 18 dígitos.
    documentos = set(_PADRAO_DOCUMENTO.findall(re.sub(r"[^0-9]", " ", bruto)))
    # CNPJ no nome é associação exata e vence qualquer semelhança de texto.
    por_documento = [cliente for cliente in clientes if cliente.documento and cliente.documento in documentos]
    if len(por_documento) == 1:
        return por_documento[0], ""
    if len(por_documento) > 1:
        return None, "Há mais de uma linha de planilha com o documento do arquivo."

    pontuados = sorted(
        ((_pontuar_nome(bruto, cliente.nome), cliente) for cliente in clientes if cliente.nome),
        key=lambda item: item[0],
        reverse=True,
    )
    if not pontuados or pontuados[0][0] < 72:
        return None, "Não foi possível associar o arquivo a uma linha de planilha. Renomeie-o com o CNPJ ou complete o nome do cliente."
    maior, escolhido = pontuados[0]
    # Nomes parecidos não podem decidir a senha: empate é pendência, não chute.
    if len(pontuados) > 1 and pontuados[1][0] >= maior - 3:
        return None, "Mais de um cliente tem nome semelhante a este arquivo. Renomeie o PFX com o CNPJ para desambiguar."
    return escolhido, ""


def montar_plano(pasta: Path, planilhas: Iterable[Path]) -> list[ItemPlano]:
    """Monta uma prévia completa sem importar nem enviar dado algum."""
    registros: list[RegistroPlanilha] = []
    for planilha in planilhas:
        registros.extend(ler_planilha(Path(planilha)))
    clientes = unir_registros(registros)
    if not clientes:
        raise ImportacaoLocalError(
            "Nenhuma linha com cliente/CNPJ e senha foi reconhecida nas planilhas. Confira os cabeçalhos."
        )

    plano: list[ItemPlano] = []
    for arquivo in _arquivos_pfx(Path(pasta)):
        cliente, motivo = _escolher_cliente(arquivo, clientes)
        if cliente is None:
            plano.append(ItemPlano(arquivo, "sem_associacao", motivo))
            continue
        if not cliente.senhas:
            plano.append(
                ItemPlano(
                    arquivo,
                    "sem_senha",
                    "A empresa foi encontrada, mas não há senha preenchida nas planilhas associadas.",
                    cliente=cliente.identificacao,
                    documento=cliente.documento,
                    validade_declarada=cliente.validade,
                )
            )
            continue
        plano.append(
            ItemPlano(
                arquivo,
                "pronto",
                "Associado de forma determinística; pronto para importar localmente.",
                cliente=cliente.identificacao,
                documento=cliente.documento,
                validade_declarada=cliente.validade,
                _referencia=cliente,
            )
        )
    return plano


# ---------------------------------------------------------------------------
# Importação no CurrentUser\My (Windows)
# ---------------------------------------------------------------------------

# O script é constante; caminho e senha seguem somente como JSON no stdin.
# Assim, a senha não fica visível na lista de processos, em um .ps1 temporário
# ou no ambiente do processo filho.
_SCRIPT_IMPORTAR_PFX = r"""
$ErrorActionPreference = 'Stop'
# Caminhos e titulares podem ter acento. Fixa UTF-8 nos dois lados do pipe;
# a senha continua fora de argumento, arquivo e variável de ambiente.
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$entrada = $null
$senhaSegura = $null
try {
    $entrada = [Console]::In.ReadToEnd() | ConvertFrom-Json
    if ($null -eq $entrada -or [string]::IsNullOrWhiteSpace([string]$entrada.caminho)) {
        throw 'Entrada de importação inválida.'
    }
    $senhaSegura = ConvertTo-SecureString -String ([string]$entrada.senha) -AsPlainText -Force
    $dados = Get-PfxData -FilePath ([string]$entrada.caminho) -Password $senhaSegura
    $certificado = @($dados.EndEntityCertificates)[0]
    if ($null -eq $certificado) { throw 'O arquivo não contém certificado final.' }
    $thumbprint = [string]$certificado.Thumbprint
    $existente = Get-ChildItem -Path 'Cert:\CurrentUser\My' |
        Where-Object { $_.Thumbprint -eq $thumbprint } |
        Select-Object -First 1
    $resultado = 'ja_instalado'
    if ($null -eq $existente) {
        $existente = Import-PfxCertificate -FilePath ([string]$entrada.caminho) `
            -CertStoreLocation 'Cert:\CurrentUser\My' -Password $senhaSegura -Exportable:$false
        $resultado = 'importado'
    }
    [PSCustomObject]@{
        resultado = $resultado
        thumbprint = [string]$existente.Thumbprint
        titular = [string]$existente.Subject
        valido_ate = $existente.NotAfter.ToUniversalTime().ToString('o')
    } | ConvertTo-Json -Compress
}
finally {
    Remove-Variable senhaSegura,entrada,dados,certificado -ErrorAction SilentlyContinue
}
"""


def importar_pfx_no_windows(arquivo: Path, senha: str) -> dict[str, str]:
    """Importa um PFX usando APIs do Windows sem expor a senha na CLI."""
    if platform.system() != "Windows":
        raise ImportacaoLocalError(
            "A instalação de certificados só pode ser executada em uma estação Windows. Use --simular aqui e rode --executar no PC que usará o Assinador SERPRO."
        )
    carga = json.dumps({"caminho": str(arquivo.resolve()), "senha": senha}, ensure_ascii=False)
    try:
        processo = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                _SCRIPT_IMPORTAR_PFX,
            ],
            input=carga,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=120,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ImportacaoLocalError(
            f"Não foi possível chamar o PowerShell para '{arquivo.name}'. Confira o Windows e tente novamente."
        ) from exc
    if processo.returncode != 0:
        # O stderr poderia conter detalhes do provedor criptográfico. Não o
        # ecoamos: para o operador a ação é a mesma e a senha nunca aparece.
        raise ImportacaoLocalError("O Windows recusou abrir este PFX com a senha declarada.")
    try:
        retorno = json.loads(processo.stdout)
    except ValueError as exc:
        raise ImportacaoLocalError(
            f"O Windows não devolveu a confirmação esperada para '{arquivo.name}'."
        ) from exc
    if not isinstance(retorno, dict) or not retorno.get("thumbprint"):
        raise ImportacaoLocalError(
            f"O Windows não confirmou a instalação de '{arquivo.name}'."
        )
    return {chave: str(valor or "") for chave, valor in retorno.items()}


def _data_retorno(valor: str) -> date | None:
    try:
        return datetime.fromisoformat(str(valor).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def executar_plano(
    plano: Iterable[ItemPlano],
    *,
    importar: Callable[[Path, str], dict[str, str]] = importar_pfx_no_windows,
) -> list[ResultadoItem]:
    """Executa somente os itens aprovados na prévia.

    Quando duas planilhas trouxerem senhas diferentes da mesma empresa, tenta
    apenas esses valores declarados, em ordem, e para na primeira confirmação
    do Windows. Não registra qual senha funcionou.
    """
    resultados: list[ResultadoItem] = []
    for item in plano:
        if not item.pronto or item._referencia is None:
            resultados.append(
                ResultadoItem(
                    arquivo=item.arquivo,
                    status="ignorado",
                    mensagem=item.mensagem,
                    cliente=item.cliente,
                    documento=item.documento,
                    validade_declarada=item.validade_declarada,
                )
            )
            continue

        ultimo_erro: ImportacaoLocalError | None = None
        retorno: dict[str, str] | None = None
        tentativas = 0
        for senha in item._referencia.senhas:
            tentativas += 1
            try:
                retorno = importar(item.arquivo, senha)
                break
            except ImportacaoLocalError as exc:
                ultimo_erro = exc

        if retorno is None:
            resultados.append(
                ResultadoItem(
                    arquivo=item.arquivo,
                    status="erro",
                    mensagem=(
                        "Nenhuma das senhas declaradas para esta empresa abriu o certificado. "
                        "Confira a linha da planilha e o arquivo antes de tentar de novo."
                    ),
                    cliente=item.cliente,
                    documento=item.documento,
                    validade_declarada=item.validade_declarada,
                    tentativas=tentativas,
                )
            )
            # Solta a referência antes de seguir para o próximo arquivo.
            del ultimo_erro
            continue

        validade_certificado = _data_retorno(retorno.get("valido_ate", ""))
        mensagem = (
            "Certificado já estava no repositório CurrentUser\\My."
            if retorno.get("resultado") == "ja_instalado"
            else "Certificado instalado no repositório CurrentUser\\My."
        )
        if item.validade_declarada and validade_certificado and item.validade_declarada != validade_certificado:
            mensagem += (
                f" Atenção: a planilha informa validade {item.validade_declarada.isoformat()}, "
                f"mas o certificado informa {validade_certificado.isoformat()}; a validade do certificado prevalece."
            )
        resultados.append(
            ResultadoItem(
                arquivo=item.arquivo,
                status=retorno.get("resultado") or "importado",
                mensagem=mensagem,
                cliente=item.cliente,
                documento=item.documento,
                validade_declarada=item.validade_declarada,
                validade_certificado=validade_certificado,
                thumbprint=retorno.get("thumbprint", "").lower(),
                tentativas=tentativas,
            )
        )
    return resultados


def resumo(plano_ou_resultados: Iterable[ItemPlano | ResultadoItem]) -> dict[str, int]:
    """Contagem por status para tela de console e automação sem segredos."""
    totais: dict[str, int] = {}
    for item in plano_ou_resultados:
        totais[item.status] = totais.get(item.status, 0) + 1
    return totais
