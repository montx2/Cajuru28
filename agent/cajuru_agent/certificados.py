"""
Descoberta de certificados A1 na estação.

**Invariante desta camada:** nada que saia daqui contém chave privada, senha
ou o conteúdo do arquivo PFX. O que é enviado ao servidor são metadados
públicos do X.509 — os mesmos que qualquer navegador exibe ao clicar no
cadeado — mais uma `referencia_local` opaca que só esta máquina sabe resolver.

Duas fontes, na ordem de preferência:

1. **Repositório de certificados do Windows** (`CurrentUser\\My`). É onde o A1
   fica depois de instalado e é o repositório que o Assinador SERPRO consulta.
   A chave privada continua sob proteção do CryptoAPI/CNG — nem o Agent nem o
   Cajuru28 a tocam. Lida via PowerShell, porque é a interface suportada pela
   Microsoft e não exige dependência binária extra.
2. **Pasta de arquivos `.pfx`/`.p12`**, para escritórios que ainda guardam os
   arquivos em disco. Aqui o Agent lê **somente a parte pública**: nenhuma
   senha é pedida, e por isso a maioria dos campos vem vazia até que o
   certificado seja importado no repositório do Windows. Essa limitação é
   deliberada: pedir senha para inventariar seria criar um cofre paralelo.

O CNPJ do titular sai do **OID 2.16.76.1.3.3** (pessoa jurídica) ou
**2.16.76.1.3.1** (pessoa física) do padrão ICP-Brasil, não de heurística em
cima do CN. É esse campo que ancora a associação determinística
cliente → certificado exigida pelo módulo.
"""

from __future__ import annotations

import json
import logging
import platform
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("cajuru.agent.certificados")

#: OIDs ICP-Brasil que carregam o documento do titular (DOC-ICP-04).
OID_PESSOA_JURIDICA = "2.16.76.1.3.3"
OID_PESSOA_FISICA = "2.16.76.1.3.1"

_SO_DIGITOS = re.compile(r"\D+")


@dataclass
class CertificadoLocal:
    """Metadados públicos de um A1 visível nesta máquina."""

    thumbprint: str
    documento: str = ""
    titular_nome: str = ""
    subject: str = ""
    issuer: str = ""
    numero_serie: str = ""
    valido_de: str = ""
    valido_ate: str = ""
    origem: str = "windows_store"
    referencia_local: str = ""
    tem_chave_privada: bool = True
    senha_disponivel: bool = False
    tipo: str = "cliente"
    erro: str = ""

    def para_envio(self) -> dict:
        """Payload do inventário. Note o que não existe aqui: nada secreto."""
        return {
            "thumbprint": self.thumbprint,
            "documento": self.documento,
            "titular_nome": self.titular_nome,
            "subject": self.subject,
            "issuer": self.issuer,
            "numero_serie": self.numero_serie,
            "valido_de": self.valido_de,
            "valido_ate": self.valido_ate,
            "origem": self.origem,
            "referencia_local": self.referencia_local,
            "tem_chave_privada": self.tem_chave_privada,
            "senha_disponivel": self.senha_disponivel,
            "tipo": self.tipo,
            "erro": self.erro,
        }


def documento_do_oid(valor: str) -> str:
    """Extrai CNPJ (14) ou CPF (11) do conteúdo do OID ICP-Brasil.

    O campo é uma concatenação posicional. Para pessoa jurídica
    (2.16.76.1.3.3) o CNPJ são os 14 primeiros dígitos; para pessoa física
    (2.16.76.1.3.1) o CPF ocupa as posições 9 a 19 da string de dígitos.
    """
    digitos = _SO_DIGITOS.sub("", valor or "")
    if len(digitos) >= 14:
        return digitos[:14]
    if len(digitos) == 11:
        return digitos
    return ""


def documento_de_pessoa_fisica(valor: str) -> str:
    digitos = _SO_DIGITOS.sub("", valor or "")
    # DDMMAAAA (8) + CPF (11) + NIS (11) + RG (15)
    if len(digitos) >= 19:
        return digitos[8:19]
    if len(digitos) == 11:
        return digitos
    return ""


# ---------------------------------------------------------------------------
# Windows
# ---------------------------------------------------------------------------

_SCRIPT_POWERSHELL = r"""
$ErrorActionPreference = 'Stop'
$saida = @()
foreach ($loja in @('CurrentUser\My','LocalMachine\My')) {
    try { $itens = Get-ChildItem -Path "Cert:\$loja" -ErrorAction Stop } catch { continue }
    foreach ($c in $itens) {
        $oids = @()
        foreach ($ext in $c.Extensions) {
            if ($ext.Oid.Value -eq '2.5.29.17') {
                try { $oids += $ext.Format($true) } catch { }
            }
        }
        $saida += [PSCustomObject]@{
            thumbprint   = $c.Thumbprint
            subject      = $c.Subject
            issuer       = $c.Issuer
            serial       = $c.SerialNumber
            notBefore    = $c.NotBefore.ToUniversalTime().ToString('o')
            notAfter     = $c.NotAfter.ToUniversalTime().ToString('o')
            hasPrivateKey= $c.HasPrivateKey
            store        = $loja
            san          = ($oids -join ' | ')
        }
    }
}
$saida | ConvertTo-Json -Depth 4 -Compress
"""


def _powershell(script: str, *, timeout: int = 60) -> str:
    processo = subprocess.run(  # noqa: S603 — comando fixo, sem entrada do usuário
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
        timeout=timeout,
    )
    if processo.returncode != 0:
        raise RuntimeError((processo.stderr or "").strip()[:400] or "PowerShell falhou")
    return processo.stdout


def _nome_do_subject(subject: str) -> str:
    for parte in (subject or "").split(","):
        parte = parte.strip()
        if parte.upper().startswith("CN="):
            nome = parte[3:].strip()
            # ICP-Brasil usa "NOME DA EMPRESA LTDA:12345678000195"
            return nome.split(":")[0].strip()
    return ""


def _documento_do_subject(subject: str) -> str:
    """Fallback: o CN do ICP-Brasil traz o documento após os dois-pontos."""
    for parte in (subject or "").split(","):
        parte = parte.strip()
        if parte.upper().startswith("CN=") and ":" in parte:
            return documento_do_oid(parte.split(":", 1)[1])
    return ""


def listar_windows() -> list[CertificadoLocal]:
    """Inventaria o repositório de certificados do Windows."""
    try:
        bruto = _powershell(_SCRIPT_POWERSHELL)
    except Exception as exc:  # noqa: BLE001
        log.warning("inventario_windows_falhou: %s", exc)
        return []

    try:
        dados = json.loads(bruto or "[]")
    except ValueError:
        return []
    if isinstance(dados, dict):
        dados = [dados]

    encontrados: list[CertificadoLocal] = []
    for item in dados:
        thumbprint = str(item.get("thumbprint") or "").strip().lower()
        if not thumbprint:
            continue
        subject = str(item.get("subject") or "")
        san = str(item.get("san") or "")
        documento = ""
        if OID_PESSOA_JURIDICA in san:
            documento = documento_do_oid(_trecho_apos(san, OID_PESSOA_JURIDICA))
        if not documento and OID_PESSOA_FISICA in san:
            documento = documento_de_pessoa_fisica(_trecho_apos(san, OID_PESSOA_FISICA))
        if not documento:
            documento = _documento_do_subject(subject)

        encontrados.append(
            CertificadoLocal(
                thumbprint=thumbprint,
                documento=documento,
                titular_nome=_nome_do_subject(subject),
                subject=subject,
                issuer=str(item.get("issuer") or ""),
                numero_serie=str(item.get("serial") or ""),
                valido_de=str(item.get("notBefore") or ""),
                valido_ate=str(item.get("notAfter") or ""),
                origem="windows_store",
                referencia_local="{}:{}".format(
                    item.get("store") or "CurrentUser\\My", thumbprint
                ),
                tem_chave_privada=bool(item.get("hasPrivateKey")),
                erro="" if item.get("hasPrivateKey") else "Certificado sem chave privada associada.",
            )
        )
    return encontrados


def _trecho_apos(texto: str, oid: str) -> str:
    """Recorta o valor que segue um OID dentro do SAN formatado pelo Windows."""
    pos = texto.find(oid)
    if pos < 0:
        return ""
    resto = texto[pos + len(oid) :]
    return resto.split("|")[0]


# ---------------------------------------------------------------------------
# Arquivos .pfx / .p12
# ---------------------------------------------------------------------------


def listar_arquivos(pasta: Path) -> list[CertificadoLocal]:
    """Lista arquivos PFX/P12 presentes, **sem abri-los**.

    Abrir exigiria a senha, e pedir a senha para inventariar transformaria o
    Agent num cofre de senhas — exatamente o que este projeto evita. O registro
    entra como pendência: o operador importa o certificado no Windows e, no
    próximo inventário, ele aparece completo.
    """
    if not pasta or not pasta.exists():
        return []
    achados: list[CertificadoLocal] = []
    for arquivo in sorted(pasta.glob("*")):
        if arquivo.suffix.lower() not in {".pfx", ".p12"}:
            continue
        try:
            estatisticas = arquivo.stat()
        except OSError:
            continue
        # Identificador estável e não sensível: caminho + tamanho + mtime.
        import hashlib

        semente = f"{arquivo.resolve()}|{estatisticas.st_size}|{int(estatisticas.st_mtime)}"
        thumbprint = hashlib.sha256(semente.encode("utf-8")).hexdigest()
        achados.append(
            CertificadoLocal(
                thumbprint=thumbprint,
                titular_nome=arquivo.stem,
                origem="arquivo",
                referencia_local=f"arquivo:{arquivo.name}",
                tem_chave_privada=True,
                senha_disponivel=False,
                erro=(
                    "Arquivo PFX detectado, mas não inventariado: importe-o no "
                    "repositório de certificados do Windows para que o Assinador "
                    "SERPRO e o Cajuru Agent possam usá-lo."
                ),
            )
        )
    return achados


def inventariar(pasta_pfx: Path | None = None) -> list[CertificadoLocal]:
    """Inventário completo da estação."""
    encontrados: list[CertificadoLocal] = []
    if platform.system() == "Windows":
        encontrados.extend(listar_windows())
    else:
        log.info("inventario_fora_do_windows: repositório do Windows indisponível")
    if pasta_pfx:
        encontrados.extend(listar_arquivos(Path(pasta_pfx)))
    return encontrados


def vigente(certificado: CertificadoLocal, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now(timezone.utc)
    try:
        fim = datetime.fromisoformat(certificado.valido_ate.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return False
    if fim.tzinfo is None:
        fim = fim.replace(tzinfo=timezone.utc)
    return fim > agora
