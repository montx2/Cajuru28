"""
Atualização automática: você arruma o projeto uma vez, todo mundo recebe.

O problema que este módulo resolve é o inverso do deploy web: aqui não existe
"publicar e todo mundo já está na versão nova". Cada computador tem o programa
instalado, e a única forma de corrigir um erro em 5 máquinas é o próprio
programa se atualizar.

## Como funciona

1. o programa instalado lê um **manifesto** (`latest.json`) dizendo qual é a
   versão mais nova e onde está o arquivo;
2. compara com a própria versão (`versao.txt` empacotado no build);
3. se for mais nova: baixa, confere o **SHA-256** e chama o instalador em modo
   silencioso, saindo antes dele para não travar os arquivos;
4. o instalador atualiza **por cima** (mesmo `AppId`), o que preserva a pasta de
   dados — banco, certificados, XMLs e `.env` não são tocados por uma
   atualização;
5. o programa reabre sozinho na versão nova.

## De onde vem o manifesto

| Você quer | `NOTASFLOW_UPDATE_MANIFEST` |
| --- | --- |
| GitHub Releases oficial (padrão) | *(vazio)* |
| Outro repositório GitHub | `montx2/OutroRepo` |
| Pasta na rede do escritório | `\\\\SERVIDOR\\NotasFlow` (com `latest.json` e o `.exe` dentro) |
| Servidor próprio | `https://intranet/notasflow/latest.json` |

A pasta de rede é a opção que funciona **sem internet**: o servidor do
escritório guarda o instalador, e todos os computadores se atualizam dali.

## Sobre confiança

O download só é aceito de `https://` (ou de caminho local/rede explícito), e o
arquivo precisa bater com o SHA-256 publicado no manifesto. Não existe
certificado de assinatura de código aqui porque isso custa dinheiro por ano —
o que existe é: canal confiável (HTTPS do GitHub, que só o dono do repositório
publica) + hash conferido + origem restrita a domínios do GitHub para o modo
online.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import httpx

from app.core.config import settings
from app.desktop import caminhos

log = logging.getLogger("notasflow.atualizador")

TIMEOUT_MANIFESTO = 15.0
TAMANHO_MAXIMO_INSTALADOR = 800 * 1024 * 1024  # 800 MB: teto de sanidade

# Como o instalador (Inno Setup) é chamado na atualização automática.
#
# Todas estas bandeiras existem por um motivo específico:
#   /VERYSILENT        nenhuma tela, nenhum clique — é uma atualização de fundo;
#   /SUPPRESSMSGBOXES  nem a caixa de "arquivos em uso";
#   /NORESTART         reiniciar o computador do contador está fora de questão;
#   /SP-               não perguntar nada antes de começar;
#   /NOCANCEL          o usuário não pode cancelar no meio e deixar meia
#                      instalação (o botão de cancelar some);
#   /CLOSEAPPLICATIONS fecha o programa se ainda estiver aberto, em vez de
#                      falhar na troca dos arquivos.
#
# Está aqui, como constante, para ser testável: a alternativa é uma string
# dentro de um `.cmd` gerado em tempo de execução, onde ninguém confere.
FLAGS_SILENCIOSAS = "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL /CLOSEAPPLICATIONS"

# Onde o download é aceito, quando o manifesto vem de uma URL.
DOMINIOS_CONFIAVEIS = (
    "github.com",
    "objects.githubusercontent.com",
    "github-releases.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "raw.githubusercontent.com",
)


class ErroDeAtualizacao(RuntimeError):
    pass


@dataclass
class ArquivoAtualizacao:
    url: str
    sha256: str = ""
    tamanho: int = 0
    tipo: str = "instalador"  # instalador | zip


@dataclass
class Atualizacao:
    versao: str
    notas: str = ""
    obrigatoria: bool = False
    publicada_em: str = ""
    arquivo: ArquivoAtualizacao | None = None
    origem: str = ""

    @property
    def disponivel(self) -> bool:
        return bool(self.arquivo and self.arquivo.url)


@dataclass
class Progresso:
    etapa: str = "iniciando"  # verificando | baixando | verificando_hash | instalando | erro | concluido
    baixado: int = 0
    total: int = 0
    mensagem: str = ""
    erro: str | None = None
    atualizacao: Atualizacao | None = None
    historico: list[str] = field(default_factory=list)


def versao_atual() -> str:
    return caminhos.versao_do_pacote()


# ---------------------------------------------------------------------------
# Comparação de versões
# ---------------------------------------------------------------------------


def _partes(versao: str) -> tuple[int, ...]:
    """
    `1.2.10` → `(1, 2, 10)`.

    Comparar versão como texto é o erro que faz "1.10.0" parecer mais antigo
    que "1.9.0" — e faz o programa reinstalar a mesma atualização para sempre.
    """
    limpo = (versao or "").strip().lstrip("vV")
    pedacos: list[int] = []
    for parte in limpo.split("."):
        digitos = "".join(c for c in parte if c.isdigit())
        pedacos.append(int(digitos) if digitos else 0)
    return tuple(pedacos) or (0,)


def versao_mais_nova(candidata: str, atual: str) -> bool:
    a, b = _partes(candidata), _partes(atual)
    tamanho = max(len(a), len(b))
    return a + (0,) * (tamanho - len(a)) > b + (0,) * (tamanho - len(b))


# ---------------------------------------------------------------------------
# Manifesto
# ---------------------------------------------------------------------------


def url_do_manifesto() -> str:
    """
    Resolve o endereço do manifesto.

    O caminho `releases/latest/download/latest.json` é o do GitHub que **não
    consome cota da API**: ele é um redirecionamento para o arquivo publicado na
    última release. Usar `api.github.com` funcionaria, mas limitaria a 60
    consultas por hora por IP — e um escritório inteiro sai pelo mesmo IP.
    """
    explicito = (settings.notasflow_update_manifest or "").strip()
    if explicito:
        if explicito.startswith(("http://", "https://")) or "\\" in explicito or explicito.startswith("/"):
            if explicito.lower().endswith(".json"):
                return explicito
            return explicito.rstrip("/\\") + ("/latest.json" if explicito.startswith(("http", "/")) else "\\latest.json")
        # Formato "dono/repositorio"
        repo = explicito.strip("/")
        return f"https://github.com/{repo}/releases/latest/download/latest.json"

    repo = (settings.notasflow_repo or "").strip().strip("/")
    if not repo:
        return ""
    return f"https://github.com/{repo}/releases/latest/download/latest.json"


def _cabecalhos() -> dict[str, str]:
    cabecalhos = {"User-Agent": f"NotasFlow/{versao_atual()}", "Accept": "application/json, */*"}
    token = (settings.notasflow_update_token or "").strip()
    if token:
        cabecalhos["Authorization"] = f"Bearer {token}"
    return cabecalhos


def _ler_manifesto(origem: str) -> dict:
    if origem.startswith(("http://", "https://")):
        with httpx.Client(timeout=TIMEOUT_MANIFESTO, follow_redirects=True) as cliente:
            resposta = cliente.get(origem, headers=_cabecalhos())
        resposta.raise_for_status()
        return json.loads(resposta.text)

    caminho = Path(origem)
    if not caminho.is_file():
        raise ErroDeAtualizacao(f"Manifesto não encontrado: {caminho}")
    return json.loads(caminho.read_text(encoding="utf-8"))


def _escolher_arquivo(dados: dict, origem_base: str) -> ArquivoAtualizacao | None:
    """
    Escolhe o arquivo certo para este sistema.

    Aceita tanto o formato nomeado (`arquivos: {"windows-instalador": {...}}`)
    quanto um arquivo único no topo (`url`/`sha256`) — o segundo serve para
    quem publica de outra forma (pasta de rede, servidor interno).
    """
    plataforma = platform.system().lower()
    chaves: list[str] = []
    if plataforma == "windows":
        chaves = ["windows-instalador", "windows", "windows-zip", "windows-portatil"]
    elif plataforma == "darwin":
        chaves = ["macos", "darwin"]
    else:
        chaves = ["linux", "linux-tar"]

    arquivos = dados.get("arquivos") or {}
    for chave in chaves:
        if chave in arquivos:
            return _montar_arquivo(arquivos[chave], origem_base)

    # Um só arquivo, sem separar por sistema: usa se o manifesto declarar
    # explicitamente que serve para todos.
    if dados.get("universal") and dados.get("url"):
        return _montar_arquivo(dados, origem_base)
    if not arquivos and dados.get("url"):
        return _montar_arquivo(dados, origem_base)

    return None


def _montar_arquivo(dados: dict, origem_base: str) -> ArquivoAtualizacao:
    url = str(dados.get("url") or "").strip()
    if url and not url.startswith(("http://", "https://")):
        # Caminho relativo ao manifesto: é o que permite publicar tudo numa
        # pasta de rede e no mesmo diretório do instalador.
        if origem_base.startswith(("http://", "https://")):
            url = origem_base.rsplit("/", 1)[0] + "/" + url.lstrip("/")
        else:
            url = str(Path(origem_base).parent / url)
    nome = url.lower()
    tipo = "zip" if nome.endswith(".zip") or str(dados.get("tipo", "")).lower() == "zip" else "instalador"
    return ArquivoAtualizacao(
        url=url,
        sha256=str(dados.get("sha256") or "").strip().lower(),
        tamanho=int(dados.get("tamanho") or 0),
        tipo=tipo,
    )


def verificar(progresso: Progresso | None = None) -> Atualizacao | None:
    """
    Pergunta se existe versão mais nova. Nunca levanta erro para quem chamou:
    ficar sem internet não pode impedir o programa de abrir.
    """
    origem = url_do_manifesto()
    if not origem:
        return None

    if progresso is not None:
        progresso.etapa = "verificando"
        progresso.mensagem = "Verificando se existe versão nova…"

    try:
        dados = _ler_manifesto(origem)
    except Exception as exc:  # noqa: BLE001 — rede é ambiente hostil por definição
        log.info("Verificação de atualização não foi possível: %s", exc)
        if progresso is not None:
            progresso.mensagem = f"Não foi possível verificar agora ({type(exc).__name__})."
        return None

    versao_publicada = str(
        dados.get("versao") or dados.get("version") or dados.get("tag") or ""
    ).strip()
    if not versao_publicada:
        return None

    atual = versao_atual()
    if not versao_mais_nova(versao_publicada, atual):
        if progresso is not None:
            progresso.etapa = "concluido"
            progresso.mensagem = f"Você já está na versão mais nova ({atual})."
        return None

    arquivo = _escolher_arquivo(dados, origem)
    atualizacao = Atualizacao(
        versao=versao_publicada,
        notas=str(dados.get("notas") or dados.get("notes") or "").strip(),
        obrigatoria=bool(dados.get("obrigatoria") or dados.get("mandatory") or False),
        publicada_em=str(dados.get("data") or dados.get("date") or ""),
        arquivo=arquivo,
        origem=origem,
    )
    if progresso is not None:
        progresso.atualizacao = atualizacao
        progresso.mensagem = (
            f"Versão {versao_publicada} disponível (você tem {atual})."
            if atualizacao.disponivel
            else f"Versão {versao_publicada} publicada, mas sem arquivo para este sistema."
        )
    return atualizacao if atualizacao.disponivel else None


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------


def _validar_origem(url: str) -> None:
    if url.startswith("https://"):
        return
    if url.startswith("http://"):
        # Aceito só para rede interna (intranet do escritório). Nunca para a
        # internet aberta: um instalador não pode vir por canal sem TLS.
        raise ErroDeAtualizacao(
            "Download por HTTP simples não é aceito (use https:// ou uma pasta de rede)."
        )
    return  # caminho local / UNC


def baixar(
    atualizacao: Atualizacao,
    progresso: Progresso | None = None,
    *,
    ao_progredir: Callable[[int, int], None] | None = None,
) -> Path:
    """Baixa o arquivo para uma pasta temporária e devolve o caminho."""
    if not atualizacao.arquivo:
        raise ErroDeAtualizacao("Atualização sem arquivo para baixar.")
    arquivo = atualizacao.arquivo
    _validar_origem(arquivo.url)

    destino_dir = Path(tempfile.mkdtemp(prefix="notasflow-update-"))
    nome = Path(arquivo.url.split("?")[0]).name or "notasflow-atualizacao.bin"
    destino = destino_dir / nome

    if progresso is not None:
        progresso.etapa = "baixando"
        progresso.total = arquivo.tamanho
        progresso.mensagem = f"Baixando {nome}…"

    if not arquivo.url.startswith(("http://", "https://")):
        origem = Path(arquivo.url)
        if not origem.is_file():
            raise ErroDeAtualizacao(f"Arquivo de atualização não encontrado: {origem}")
        shutil.copy2(origem, destino)
        if ao_progredir:
            tamanho = destino.stat().st_size
            ao_progredir(tamanho, tamanho)
    else:
        with httpx.Client(timeout=httpx.Timeout(30.0, read=300.0), follow_redirects=True) as cliente:
            with cliente.stream("GET", arquivo.url, headers=_cabecalhos()) as resposta:
                resposta.raise_for_status()
                total = int(resposta.headers.get("content-length") or arquivo.tamanho or 0)
                if total > TAMANHO_MAXIMO_INSTALADOR:
                    raise ErroDeAtualizacao(f"Arquivo grande demais ({total} bytes) — download abortado.")
                if progresso is not None:
                    progresso.total = total
                baixado = 0
                with open(destino, "wb") as saida:
                    for pedaco in resposta.iter_bytes(1024 * 256):
                        saida.write(pedaco)
                        baixado += len(pedaco)
                        if progresso is not None:
                            progresso.baixado = baixado
                        if ao_progredir:
                            ao_progredir(baixado, total)

    if arquivo.sha256:
        if progresso is not None:
            progresso.etapa = "verificando_hash"
            progresso.mensagem = "Conferindo a integridade do arquivo…"
        calculado = _sha256(destino)
        if calculado.lower() != arquivo.sha256.lower():
            destino.unlink(missing_ok=True)
            raise ErroDeAtualizacao(
                "O arquivo baixado não confere com o publicado (SHA-256 diferente). "
                "Download cancelado por segurança — tente de novo."
            )
    return destino


def _sha256(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for pedaco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digestor.update(pedaco)
    return digestor.hexdigest()


# ---------------------------------------------------------------------------
# Instalação
# ---------------------------------------------------------------------------


def _script_de_atualizacao(arquivo: Path, tipo: str) -> str:
    """
    Gera o `.cmd` que roda **depois** que este processo morre.

    É a peça central: no Windows um programa em execução não pode substituir os
    próprios arquivos. Então quem aplica a atualização é um processo externo que
    espera o NotasFlow sair, aplica e reabre.

    Detalhes que parecem pequenos e decidem se funciona:

    - `ping -n 2` em vez de `timeout`: `timeout` falha quando a entrada padrão
      está redirecionada (é o caso de processo destacado) e a espera viraria
      um erro imediato, gerando um loop apertado de CPU;
    - `tasklist /FI "IMAGENAME eq NotasFlow.exe"` em vez de comparar PID: o nome
      do processo é estável e legível no log;
    - `/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- /NOCANCEL`: instalador sem
      clique, sem caixa de diálogo e sem reiniciar a máquina;
    - o log do que aconteceu é gravado ao lado do instalador baixado, para dar
      diagnóstico quando a atualização falhar na máquina do cliente.
    """
    executavel = Path(sys.executable)
    log_arquivo = arquivo.parent / "atualizacao.log"
    linhas = [
        "@echo off",
        "chcp 65001 >NUL",
        f'set "LOG={log_arquivo}"',
        f'set "ARQUIVO={arquivo}"',
        f'set "EXE={executavel}"',
        'echo [%DATE% %TIME%] aguardando o NotasFlow fechar >>"%LOG%"',
        ":esperar",
        'tasklist /FI "IMAGENAME eq NotasFlow.exe" /NH 2>NUL | findstr /I "NotasFlow.exe" >NUL',
        "if not errorlevel 1 (",
        "  ping -n 2 127.0.0.1 >NUL",
        "  goto esperar",
        ")",
    ]

    if tipo == "zip":
        # Modo portátil: extrai por cima da pasta do programa, movendo a antiga
        # de lado primeiro (assim dá para voltar atrás se algo der errado).
        pasta = caminhos.pasta_programa()
        linhas += [
            'echo [%DATE% %TIME%] extraindo pacote portatil >>"%LOG%"',
            f'powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath \'{arquivo}\' -DestinationPath \'{pasta}.novo\' -Force" >>"%LOG%" 2>&1',
            f'if exist "{pasta}.antigo" rmdir /S /Q "{pasta}.antigo"',
            f'move "{pasta}" "{pasta}.antigo" >>"%LOG%" 2>&1',
            f'move "{pasta}.novo" "{pasta}" >>"%LOG%" 2>&1',
        ]
    else:
        linhas += [
            'echo [%DATE% %TIME%] executando instalador silencioso >>"%LOG%"',
            f'start "" /WAIT "%ARQUIVO%" {FLAGS_SILENCIOSAS}',
            'echo [%DATE% %TIME%] instalador terminou com codigo %ERRORLEVEL% >>"%LOG%"',
        ]

    linhas += [
        'echo [%DATE% %TIME%] reabrindo >>"%LOG%"',
        'start "" "%EXE%"',
        'del "%~f0"',
    ]
    return "\r\n".join(linhas) + "\r\n"


def aplicar(atualizacao: Atualizacao, progresso: Progresso | None = None) -> None:
    """
    Baixa, confere e dispara a atualização. **Esta função não volta**: quem
    chama precisa ter avisado a tela antes, porque o processo encerra em
    seguida para liberar os arquivos.
    """
    baixado = baixar(atualizacao, progresso)
    if progresso is not None:
        progresso.etapa = "instalando"
        progresso.mensagem = "Aplicando a atualização — o programa vai reabrir sozinho…"

    tipo = atualizacao.arquivo.tipo if atualizacao.arquivo else "instalador"
    script = baixado.parent / "aplicar-atualizacao.cmd"
    script.write_text(_script_de_atualizacao(baixado, tipo), encoding="utf-8")

    log.info("Aplicando atualização %s via %s", atualizacao.versao, script)
    if sys.platform == "win32":
        subprocess.Popen(
            ["cmd", "/c", str(script)],
            creationflags=(
                getattr(subprocess, "DETACHED_PROCESS", 0)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0)
            ),
            close_fds=True,
            cwd=str(baixado.parent),
        )
    else:
        # Fora do Windows não existe instalador; o `.cmd` não roda. Só registra,
        # para o servidor de desenvolvimento não se matar por engano.
        log.warning("Atualização automática só é aplicada no Windows.")
        raise ErroDeAtualizacao("A atualização automática está disponível na versão Windows.")


def pasta_de_atualizacoes() -> Path:
    """Onde ficam os arquivos baixados pendentes (para limpeza e diagnóstico)."""
    return Path(tempfile.gettempdir()) / "notasflow-updates"


def limpar_antigos(dias: int = 7) -> int:
    """Apaga instaladores baixados há mais de N dias (disco do cliente é finito)."""
    import glob

    limite = time.time() - dias * 86400
    removidos = 0
    for padrao in ("notasflow-update-*",):
        for caminho in glob.glob(str(Path(tempfile.gettempdir()) / padrao)):
            try:
                if os.path.getmtime(caminho) < limite:
                    shutil.rmtree(caminho, ignore_errors=True)
                    removidos += 1
            except OSError:
                continue
    return removidos


def info() -> dict:
    """O que a tela de Configurações mostra sobre a versão instalada."""
    return {
        "versao": versao_atual(),
        "manifesto": url_do_manifesto(),
        "pasta_programa": str(caminhos.pasta_programa()),
        "pasta_dados": str(caminhos.pasta_dados()),
        "empacotado": caminhos.esta_empacotado(),
        "sistema": platform.system(),
        "verificado_em": datetime.now(timezone.utc).isoformat(),
    }
