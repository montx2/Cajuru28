"""
Políticas de seleção automática de certificado para navegadores Chromium.

Objetivo operacional: quando o portal/gov.br solicitar certificado cliente, o
navegador deve escolher o A1 **exato** do cliente em vez de abrir o seletor para
o operador centenas de vezes. A seleção é feita por política corporativa
``AutoSelectCertificateForUrls`` (Chrome/Chromium/Edge), nunca por coordenada,
janela nativa ou clique em popup.

O módulo é deliberadamente conservador:

* só gera regras a partir de metadados públicos do certificado instalado;
* nunca lê PFX, senha ou chave privada;
* usa filtros por ``SUBJECT`` e ``ISSUER`` quando disponíveis;
* não remove políticas existentes; ao aplicar, apenas acrescenta uma regra que
  ainda não exista;
* falha fechado quando houver mais de um certificado possível para o documento.

Referência técnica: navegadores Chromium aceitam uma lista de strings JSON no
formato ``{"pattern":"$URL_PATTERN","filter":{...}}``. O filtro restringe
emissor e/ou titular, e o próprio servidor ainda precisa aceitar o certificado
na requisição TLS.
"""

from __future__ import annotations

import json
import platform
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

from .certificados import CertificadoLocal, inventariar, vigente

_BROWSER_REGISTRY_PATHS = {
    "chrome": r"Software\Policies\Google\Chrome\AutoSelectCertificateForUrls",
    "chromium": r"Software\Policies\Chromium\AutoSelectCertificateForUrls",
    "edge": r"Software\Policies\Microsoft\Edge\AutoSelectCertificateForUrls",
}

# Portal de Serviços, e-CAC, gov.br e Assinatura gov.br. O padrão usa origem ou
# domínio exato com wildcard de subdomínio do formato de políticas Chromium.
PADROES_RFB_PADRAO = (
    "https://servicos.receitafederal.gov.br",
    "https://cav.receita.fazenda.gov.br",
    "https://sso.acesso.gov.br",
    "https://assinatura.gov.br",
    "https://www.gov.br",
)

_DN_SEPARADOR = re.compile(r"(?<!\\),")
_DOC = re.compile(r"\D+")


class PoliticaNavegadorError(RuntimeError):
    """Falha segura ao montar/aplicar política de navegador."""


@dataclass(frozen=True)
class RegraAutoSelecao:
    """Uma entrada de ``AutoSelectCertificateForUrls``.

    ``filtro`` segue exatamente a estrutura esperada por Chrome/Edge. Exemplo:

    ``{"ISSUER":{"CN":"AC SERPRO RFB v5"},"SUBJECT":{"CN":"EMPRESA:123..."}}``
    """

    pattern: str
    filtro: Mapping[str, Mapping[str, str]] = field(default_factory=dict)

    def para_json(self) -> str:
        return json.dumps(
            {"pattern": self.pattern, "filter": self.filtro},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


@dataclass(frozen=True)
class PoliticaGerada:
    navegador: str
    caminho_registro_hkcu: str
    regras: tuple[RegraAutoSelecao, ...]

    def valores_registro(self, inicio: int = 1) -> dict[str, str]:
        return {str(indice): regra.para_json() for indice, regra in enumerate(self.regras, start=inicio)}


@dataclass(frozen=True)
class ResultadoAplicacaoPolitica:
    navegador: str
    adicionadas: int
    existentes: int
    caminho_registro_hkcu: str
    mensagens: tuple[str, ...] = ()


@dataclass(frozen=True)
class DiagnosticoPoliticas:
    windows: bool
    navegadores: dict[str, dict[str, str]]
    observacoes: tuple[str, ...] = ()


def normalizar_documento(valor: str) -> str:
    return _DOC.sub("", valor or "")


def atributos_dn(dn: str) -> dict[str, str]:
    """Extrai atributos simples de um Distinguished Name X.509.

    O PowerShell entrega subjects no formato ``CN=..., OU=..., O=...``. Para a
    política basta CN/O/OU/L; se houver atributos repetidos preservamos o
    primeiro, que é o que os navegadores também costumam exibir ao operador.
    """
    atributos: dict[str, str] = {}
    for parte in _DN_SEPARADOR.split(dn or ""):
        if "=" not in parte:
            continue
        chave, valor = parte.split("=", 1)
        chave = chave.strip().upper()
        valor = valor.replace(r"\,", ",").strip()
        if chave and valor and chave not in atributos:
            atributos[chave] = valor
    return atributos


def filtro_para_certificado(certificado: CertificadoLocal) -> dict[str, dict[str, str]]:
    """Monta filtro de seleção com subject e issuer, sem depender de ordem.

    Não filtra por thumbprint porque a política Chromium não oferece esse campo.
    O thumbprint continua sendo usado pelo Cajuru para escolher o certificado;
    a política reduz o seletor do navegador usando os atributos estáveis que o
    navegador aceita.
    """
    subject = atributos_dn(certificado.subject)
    issuer = atributos_dn(certificado.issuer)
    filtro: dict[str, dict[str, str]] = {}

    subject_filter: dict[str, str] = {}
    # O CN ICP-Brasil normalmente contém "NOME:documento" e é o melhor filtro
    # aceito pelo navegador para diferenciar clientes com o mesmo emissor.
    if subject.get("CN"):
        subject_filter["CN"] = subject["CN"]
    if subject.get("O"):
        subject_filter["O"] = subject["O"]
    if subject.get("OU"):
        subject_filter["OU"] = subject["OU"]
    if subject_filter:
        filtro["SUBJECT"] = subject_filter

    issuer_filter: dict[str, str] = {}
    if issuer.get("CN"):
        issuer_filter["CN"] = issuer["CN"]
    if issuer.get("O"):
        issuer_filter["O"] = issuer["O"]
    if issuer.get("OU"):
        issuer_filter["OU"] = issuer["OU"]
    if issuer_filter:
        filtro["ISSUER"] = issuer_filter

    if not filtro:
        raise PoliticaNavegadorError(
            "O certificado não possui Subject/Issuer suficientes para gerar filtro seguro."
        )
    return filtro


def selecionar_certificado_unico(
    certificados: Iterable[CertificadoLocal], documento: str, *, thumbprint: str = ""
) -> CertificadoLocal:
    alvo = normalizar_documento(documento)
    if not alvo:
        raise PoliticaNavegadorError("Informe CPF/CNPJ válido para gerar a política.")
    candidatos = [
        c
        for c in certificados
        if normalizar_documento(c.documento) == alvo and c.tem_chave_privada and vigente(c)
    ]
    if thumbprint:
        desejado = thumbprint.lower().strip()
        candidatos = [c for c in candidatos if c.thumbprint.lower() == desejado]
    if not candidatos:
        raise PoliticaNavegadorError(
            f"Nenhum certificado vigente com chave privada foi encontrado para {alvo}."
        )
    distintos = {c.thumbprint.lower() for c in candidatos}
    if len(distintos) > 1:
        thumbs = ", ".join(sorted(t[:16] for t in distintos))
        raise PoliticaNavegadorError(
            "Mais de um certificado vigente atende ao documento. Fixe o thumbprint "
            f"explicitamente antes de configurar auto-seleção ({thumbs})."
        )
    return candidatos[0]


def gerar_politica(
    certificado: CertificadoLocal,
    *,
    navegador: str,
    padroes: Iterable[str] = PADROES_RFB_PADRAO,
) -> PoliticaGerada:
    navegador_norm = navegador.lower().strip()
    if navegador_norm not in _BROWSER_REGISTRY_PATHS:
        suportados = ", ".join(sorted(_BROWSER_REGISTRY_PATHS))
        raise PoliticaNavegadorError(f"Navegador '{navegador}' não suportado. Use: {suportados}.")
    filtro = filtro_para_certificado(certificado)
    regras = tuple(RegraAutoSelecao(pattern=str(padrao), filtro=filtro) for padrao in padroes)
    return PoliticaGerada(
        navegador=navegador_norm,
        caminho_registro_hkcu=_BROWSER_REGISTRY_PATHS[navegador_norm],
        regras=regras,
    )


def script_powershell(politicas: Iterable[PoliticaGerada]) -> str:
    """Gera script idempotente para revisão/aplicação pelo operador/TI.

    O script escreve em HKCU (usuário atual), não exige admin e não apaga regras
    existentes. Valores iguais são reaproveitados; regras novas entram na
    próxima posição numérica.
    """
    blocos = [
        "$ErrorActionPreference = 'Stop'",
        "# Gerado pelo Cajuru Agent. Revise antes de executar em produção.",
    ]
    for politica in politicas:
        path = "HKCU:\\" + politica.caminho_registro_hkcu
        blocos.append(f"$path = {json.dumps(path)}")
        blocos.append("New-Item -Path $path -Force | Out-Null")
        blocos.append("$existentes = @{}")
        blocos.append("try { (Get-ItemProperty -Path $path).PSObject.Properties | Where-Object { $_.Name -match '^[0-9]+$' } | ForEach-Object { $existentes[$_.Name] = [string]$_.Value } } catch { }")
        blocos.append("$proximo = 1")
        blocos.append("if ($existentes.Keys.Count -gt 0) { $proximo = (($existentes.Keys | ForEach-Object {[int]$_} | Measure-Object -Maximum).Maximum + 1) }")
        for regra in politica.regras:
            valor = regra.para_json()
            blocos.append(f"$valor = {json.dumps(valor)}")
            blocos.append("if (-not ($existentes.Values -contains $valor)) { New-ItemProperty -Path $path -Name ([string]$proximo) -Value $valor -PropertyType String -Force | Out-Null; $proximo++ }")
        blocos.append(f"Write-Host 'Política {politica.navegador}: verifique em chrome://policy ou edge://policy após reiniciar.'")
    return "\n".join(blocos) + "\n"


def _reg_query(path: str) -> dict[str, str]:
    if platform.system() != "Windows":
        return {}
    processo = subprocess.run(  # noqa: S603 — comando fixo, path controlado por tabela interna
        ["reg", "query", rf"HKCU\{path}"],
        capture_output=True,
        text=True,
        timeout=20,
    )
    if processo.returncode != 0:
        return {}
    valores: dict[str, str] = {}
    for linha in (processo.stdout or "").splitlines():
        partes = linha.strip().split(None, 2)
        if len(partes) == 3 and partes[0].isdigit() and partes[1] == "REG_SZ":
            valores[partes[0]] = partes[2]
    return valores


def diagnosticar_politicas() -> DiagnosticoPoliticas:
    """Lê políticas atuais de Chrome/Chromium/Edge para o usuário atual."""
    windows = platform.system() == "Windows"
    navegadores: dict[str, dict[str, str]] = {}
    observacoes: list[str] = []
    if not windows:
        observacoes.append("Política de registro só é aplicável no Windows; em Linux/macOS use políticas gerenciadas equivalentes.")
    for nome, path in _BROWSER_REGISTRY_PATHS.items():
        navegadores[nome] = _reg_query(path) if windows else {}
    return DiagnosticoPoliticas(windows=windows, navegadores=navegadores, observacoes=tuple(observacoes))


def aplicar_politica(politica: PoliticaGerada) -> ResultadoAplicacaoPolitica:
    """Aplica a política no HKCU do Windows sem sobrescrever valores existentes."""
    if platform.system() != "Windows":
        raise PoliticaNavegadorError("Aplicação automática de política só está disponível no Windows.")

    existentes = _reg_query(politica.caminho_registro_hkcu)
    valores_existentes = set(existentes.values())
    proximo = (max([int(k) for k in existentes.keys()] or [0]) + 1)
    adicionadas = 0
    mensagens: list[str] = []

    # Garante a chave antes de adicionar valores.
    subprocess.run(  # noqa: S603
        ["reg", "add", rf"HKCU\{politica.caminho_registro_hkcu}", "/f"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    for regra in politica.regras:
        valor = regra.para_json()
        if valor in valores_existentes:
            continue
        subprocess.run(  # noqa: S603
            [
                "reg",
                "add",
                rf"HKCU\{politica.caminho_registro_hkcu}",
                "/v",
                str(proximo),
                "/t",
                "REG_SZ",
                "/d",
                valor,
                "/f",
            ],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        adicionadas += 1
        proximo += 1
    if adicionadas:
        mensagens.append("Reinicie o navegador e confira chrome://policy ou edge://policy.")
    return ResultadoAplicacaoPolitica(
        navegador=politica.navegador,
        adicionadas=adicionadas,
        existentes=len(politica.regras) - adicionadas,
        caminho_registro_hkcu=politica.caminho_registro_hkcu,
        mensagens=tuple(mensagens),
    )


def gerar_para_documento(
    documento: str,
    *,
    navegadores: Iterable[str] = ("edge", "chrome"),
    padroes: Iterable[str] = PADROES_RFB_PADRAO,
    thumbprint: str = "",
    pasta_pfx: Path | None = None,
) -> tuple[CertificadoLocal, tuple[PoliticaGerada, ...]]:
    certificados = inventariar(pasta_pfx)
    certificado = selecionar_certificado_unico(certificados, documento, thumbprint=thumbprint)
    politicas = tuple(
        gerar_politica(certificado, navegador=navegador, padroes=padroes)
        for navegador in navegadores
    )
    return certificado, politicas
