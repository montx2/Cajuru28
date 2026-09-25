"""
Diagnóstico do Assinador Digital SERPRO Desktop.

O Assinador é o componente **oficial** que o Portal de Serviços da Receita
aciona para autenticação e assinatura com certificado digital. Este módulo
apenas **verifica** se ele está pronto; em nenhum momento o Cajuru Agent
assina em seu lugar nem manipula chave privada.

Como a verificação é feita, e por quê:

- o Assinador expõe um servidor local em ``https://127.0.0.1:65156``;
- o navegador o alcança pelo nome ``assinador-desktop.serpro.gov.br``, que o
  instalador aponta para 127.0.0.1 no arquivo ``hosts`` — se esse mapeamento
  sumir (antivírus, GPO, reinstalação do sistema), o portal simplesmente não
  encontra o assinador e o erro que o operador vê é genérico;
- o certificado TLS desse servidor é local, então a verificação de cadeia é
  desligada **apenas** para esta checagem de disponibilidade em 127.0.0.1.
  Não há troca de dados sensíveis nesta requisição: ela existe para responder
  "a porta está viva?".

O veredito final (apto / não apto) é do servidor: este módulo só coleta fatos.
Falha fechada — qualquer incerteza vira "não apto".
"""

from __future__ import annotations

import logging
import platform
import re
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("cajuru.agent.assinador")

HOST_LOCAL = "127.0.0.1"
PORTA_LOCAL = 65156
URL_LOCAL = f"https://{HOST_LOCAL}:{PORTA_LOCAL}"
HOST_MAPEADO = "assinador-desktop.serpro.gov.br"
ARQUIVO_HOSTS = Path(r"C:\Windows\System32\drivers\etc\hosts")
URL_MANUAL_OFICIAL = (
    "https://artefatos-assinador.serpro.gov.br/downloads/Manual_Usuario_Assinador_Desktop.pdf"
)
URL_VERIFICACAO_OFICIAL = "https://www.frameworkdemoiselle.gov.br/v3/signer/demo/"

_NOMES_PROCESSO = ("assinador", "serpro")
_VERSAO = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


@dataclass
class Diagnostico:
    """Fatos observados na estação. Sem julgamento — quem julga é o servidor."""

    instalado: bool = False
    em_execucao: bool = False
    hosts_mapeado: bool = False
    porta_local: bool = False
    certificado_visivel: bool = False
    permissao_navegador: bool = False
    versao: str = ""
    observacoes: list[str] = field(default_factory=list)

    def para_envio(self) -> dict:
        return {
            "instalado": self.instalado,
            "em_execucao": self.em_execucao,
            "hosts_mapeado": self.hosts_mapeado,
            "porta_local": self.porta_local,
            "certificado_visivel": self.certificado_visivel,
            "permissao_navegador": self.permissao_navegador,
            "versao": self.versao,
        }


def _porta_aberta(host: str = HOST_LOCAL, porta: int = PORTA_LOCAL, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            return True
    except OSError:
        return False


def _responde_https() -> bool:
    """Confirma que quem atende na porta fala HTTPS (e não outro serviço)."""
    try:
        # verify=False restrito a 127.0.0.1: o certificado é autoassinado por
        # natureza e nenhum dado sensível trafega nesta checagem.
        with httpx.Client(verify=False, timeout=3.0) as http:  # noqa: S501
            resposta = http.get(URL_LOCAL)
        return resposta.status_code < 500
    except httpx.HTTPError:
        return False


def _hosts_mapeado() -> bool:
    if platform.system() != "Windows":
        return False
    try:
        conteudo = ARQUIVO_HOSTS.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    for linha in conteudo.splitlines():
        limpa = linha.strip()
        if not limpa or limpa.startswith("#"):
            continue
        if HOST_MAPEADO in limpa and limpa.split()[0] in {"127.0.0.1", "::1"}:
            return True
    return False


def _processo_em_execucao() -> tuple[bool, str]:
    """Procura o processo do Assinador e tenta descobrir a versão instalada."""
    if platform.system() != "Windows":
        return False, ""
    script = (
        "Get-Process | Where-Object { $_.ProcessName -match 'assinador|serpro' } | "
        "Select-Object -First 1 ProcessName,"
        "@{n='Versao';e={$_.MainModule.FileVersionInfo.ProductVersion}} | "
        "ConvertTo-Json -Compress"
    )
    try:
        processo = subprocess.run(  # noqa: S603
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    saida = (processo.stdout or "").strip()
    if not saida or saida == "null":
        return False, ""
    encontrado = _VERSAO.search(saida)
    return True, encontrado.group(1) if encontrado else ""


def _instalado() -> tuple[bool, str]:
    """Procura o Assinador na lista de programas instalados."""
    if platform.system() != "Windows":
        return False, ""
    script = (
        "$p=@('HKLM:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKLM:\\Software\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*',"
        "'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*');"
        "Get-ItemProperty $p -ErrorAction SilentlyContinue | "
        "Where-Object { $_.DisplayName -match 'Assinador' } | "
        "Select-Object -First 1 DisplayName,DisplayVersion | ConvertTo-Json -Compress"
    )
    try:
        processo = subprocess.run(  # noqa: S603
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except (OSError, subprocess.SubprocessError):
        return False, ""
    saida = (processo.stdout or "").strip()
    if not saida or saida == "null":
        return False, ""
    encontrado = _VERSAO.search(saida)
    return True, encontrado.group(1) if encontrado else ""


def diagnosticar(*, tem_certificado: bool = False) -> Diagnostico:
    """Coleta o estado do ambiente de assinatura desta estação."""
    resultado = Diagnostico(certificado_visivel=bool(tem_certificado))

    instalado, versao_instalada = _instalado()
    em_execucao, versao_processo = _processo_em_execucao()
    resultado.instalado = instalado or em_execucao
    resultado.em_execucao = em_execucao
    resultado.versao = versao_processo or versao_instalada

    resultado.hosts_mapeado = _hosts_mapeado()
    resultado.porta_local = _porta_aberta() and _responde_https()

    # "Permissão do navegador" não é inspecionável de fora sem abrir o
    # navegador do usuário. O sinal honesto: se a porta local responde e o
    # host está mapeado, o caminho técnico existe. A confirmação definitiva é
    # o teste oficial do SERPRO, oferecido no roteiro de instalação.
    resultado.permissao_navegador = resultado.porta_local and resultado.hosts_mapeado

    if not resultado.instalado:
        resultado.observacoes.append(
            "Assinador Digital SERPRO não encontrado nesta estação."
        )
    elif not resultado.em_execucao:
        resultado.observacoes.append(
            "Assinador instalado, porém fora de execução (ele fica na área de notificação)."
        )
    if resultado.instalado and not resultado.hosts_mapeado:
        resultado.observacoes.append(
            f"Falta a linha '127.0.0.1 {HOST_MAPEADO}' no arquivo hosts."
        )
    if resultado.em_execucao and not resultado.porta_local:
        resultado.observacoes.append(
            f"Porta {PORTA_LOCAL} não respondeu — verifique firewall ou antivírus."
        )
    if platform.system() != "Windows":
        resultado.observacoes.append(
            "Diagnóstico executado fora do Windows: o Assinador SERPRO Desktop "
            "só é homologado para Windows neste fluxo."
        )
    return resultado
