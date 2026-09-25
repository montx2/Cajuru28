"""
Configuração e guarda da credencial da estação.

**Onde o segredo mora.** No Windows, no *Credential Manager* — o cofre do
próprio sistema operacional, protegido por DPAPI e ligado à conta do usuário.
Foi a opção escolhida em vez de:

- *arquivo cifrado com chave do próprio Agent*: a chave teria de ficar ao lado
  do arquivo, o que é criptografia de enfeite;
- *variável de ambiente*: vaza em dump de processo, em log de tarefa agendada
  e para qualquer programa do mesmo usuário;
- *implementação própria de cofre*: é exatamente o tipo de criptografia caseira
  que este projeto se proíbe de escrever.

Fora do Windows (desenvolvimento), cai para um arquivo em `~/.cajuru-agent`
com permissão `600` — e o log diz claramente que aquele modo não é de produção.

O resto da configuração (endereço do servidor, pasta de PFX, intervalos) não é
secreto e fica em `config.json`, ao lado do arquivo de log.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("cajuru.agent.config")

NOME_COFRE = "Cajuru28:ProcuracoesRFB"


def pasta_base() -> Path:
    if platform.system() == "Windows":
        raiz = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        return raiz / "Cajuru28" / "Agent"
    return Path.home() / ".cajuru-agent"


@dataclass
class Configuracao:
    """Parâmetros não sensíveis da estação."""

    servidor_url: str = ""
    identificador: str = ""
    nome_estacao: str = ""
    pasta_pfx: str = ""
    intervalo_busca_segundos: int = 30
    intervalo_heartbeat_segundos: int = 60
    capacidade: int = 1
    verificar_tls: bool = True
    navegador: str = ""  # vazio = navegador padrão do sistema

    @property
    def arquivo(self) -> Path:
        return pasta_base() / "config.json"

    @classmethod
    def carregar(cls) -> "Configuracao":
        caminho = pasta_base() / "config.json"
        if not caminho.exists():
            return cls()
        try:
            dados = json.loads(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.warning("config_ilegivel: %s", exc)
            return cls()
        conhecidos = {campo for campo in cls().__dataclass_fields__}
        return cls(**{k: v for k, v in dados.items() if k in conhecidos})

    def salvar(self) -> None:
        destino = self.arquivo
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_suffix(".tmp")
        temporario.write_text(
            json.dumps(asdict(self), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        temporario.replace(destino)
        if platform.system() != "Windows":
            destino.chmod(0o600)


# ---------------------------------------------------------------------------
# Segredo
# ---------------------------------------------------------------------------


class CofreError(RuntimeError):
    """Não foi possível ler ou gravar a credencial no cofre do sistema."""


def _powershell(script: str) -> str:
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
    if processo.returncode != 0:
        raise CofreError((processo.stderr or "").strip()[:300] or "PowerShell falhou")
    return (processo.stdout or "").strip()


def _arquivo_segredo() -> Path:
    return pasta_base() / "credencial.json"


def guardar_segredo(identificador: str, segredo: str) -> str:
    """Grava a credencial no cofre disponível. Devolve o nome do cofre usado."""
    if platform.system() == "Windows":
        # cmdkey é a interface suportada do Credential Manager e não exige
        # módulo externo. O segredo não aparece em log nem em echo.
        try:
            _powershell(
                "cmdkey /generic:{alvo} /user:{usuario} /pass:{senha} | Out-Null".format(
                    alvo=_aspas(NOME_COFRE), usuario=_aspas(identificador), senha=_aspas(segredo)
                )
            )
            return "Windows Credential Manager"
        except CofreError as exc:
            raise CofreError(
                "Falha ao gravar no Windows Credential Manager. Execute o instalador "
                f"com o mesmo usuário que roda o Agent. Detalhe: {exc}"
            ) from exc

    destino = _arquivo_segredo()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps({"identificador": identificador, "segredo": segredo}), encoding="utf-8"
    )
    destino.chmod(0o600)
    log.warning(
        "credencial_em_arquivo: modo de desenvolvimento; em produção use Windows."
    )
    return f"arquivo {destino} (modo desenvolvimento)"


def ler_segredo(identificador: str) -> str:
    """Recupera o segredo. Levanta `CofreError` se não houver credencial."""
    if platform.system() == "Windows":
        script = (
            "$sig=@'\n"
            "using System;using System.Runtime.InteropServices;\n"
            "public class Cred{\n"
            " [DllImport(\"advapi32\",CharSet=CharSet.Unicode,SetLastError=true)]\n"
            " public static extern bool CredReadW(string t,int y,int f,out IntPtr c);\n"
            " [DllImport(\"advapi32\")] public static extern void CredFree(IntPtr b);\n"
            " [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)]\n"
            " public struct C{public int Flags;public int Type;public string TargetName;\n"
            "  public string Comment;public long LastWritten;public int CredentialBlobSize;\n"
            "  public IntPtr CredentialBlob;public int Persist;public int AttributeCount;\n"
            "  public IntPtr Attributes;public string TargetAlias;public string UserName;}\n"
            " public static string Get(string target){IntPtr p;\n"
            "  if(!CredReadW(target,1,0,out p)) return null;\n"
            "  var c=(C)Marshal.PtrToStructure(p,typeof(C));\n"
            "  var s=Marshal.PtrToStringUni(c.CredentialBlob,c.CredentialBlobSize/2);\n"
            "  CredFree(p); return s;}}\n"
            "'@\n"
            "Add-Type -TypeDefinition $sig -Language CSharp | Out-Null\n"
            f"[Cred]::Get({_aspas(NOME_COFRE)})"
        )
        try:
            valor = _powershell(script)
        except CofreError as exc:
            raise CofreError(f"Não foi possível ler a credencial: {exc}") from exc
        if not valor:
            raise CofreError(
                "Nenhuma credencial encontrada no Windows Credential Manager. "
                "Rode instalar_agent.ps1 novamente."
            )
        return valor

    caminho = _arquivo_segredo()
    if not caminho.exists():
        raise CofreError(f"Credencial não encontrada em {caminho}.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CofreError(f"Credencial ilegível em {caminho}: {exc}") from exc
    if dados.get("identificador") != identificador:
        raise CofreError(
            "A credencial guardada pertence a outra estação. Reinstale o Agent."
        )
    return str(dados.get("segredo") or "")


def remover_segredo() -> None:
    if platform.system() == "Windows":
        try:
            _powershell(f"cmdkey /delete:{_aspas(NOME_COFRE)} | Out-Null")
        except CofreError:
            pass
        return
    caminho = _arquivo_segredo()
    if caminho.exists():
        caminho.unlink()


def _aspas(valor: str) -> str:
    """Aspas simples do PowerShell, com escape — evita injeção de comando."""
    return "'" + str(valor).replace("'", "''") + "'"
