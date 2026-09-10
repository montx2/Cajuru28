#!/usr/bin/env python3
"""
Empacota o NotasFlow em um programa instalável para Windows.

Um comando faz tudo:

    python scripts/empacotar.py

E o que ele faz, na ordem — porque a ordem importa:

1. lê a **versão** de `versao.txt` (a única fonte de verdade; o `--versao` do
   programa, o nome do instalador e o `latest.json` saem daqui);
2. compila o **painel** (`npm run build:desktop`) e copia `frontend/out` para
   `backend/web` — o `.exe` serve a interface, não existe Node no computador do
   contador;
3. roda o **PyInstaller** com `backend/notasflow.spec`;
4. grava `versao.txt` ao lado do `.exe` (é o que o atualizador compara);
5. compacta em **ZIP portátil** e, se o Inno Setup estiver instalado, compila o
   **instalador** `NotasFlow-Setup-<versao>.exe`;
6. calcula o **SHA-256** e escreve `dist/latest.json` — o manifesto que todos os
   programas instalados consultam.

## Opções

    --sem-frontend      reaproveita `frontend/out` (build do painel já feito)
    --sem-instalador    só o ZIP portátil, mesmo com o Inno instalado
    --portatil          não compila o instalador (equivalente a --sem-instalador)
    --versao 1.2.3      publica com outra versão sem editar o arquivo
    --limpar            apaga `build/`, `dist/` e `backend/web/` antes de começar

## Onde o build tem de rodar

No **Windows**. O PyInstaller não faz compilação cruzada: o `.exe` que o
contador baixa precisa ser montado em uma máquina Windows (ou em um runner
`windows-latest` do GitHub Actions — é o que `.github/workflows/release.yml`
faz). Este script roda também no Linux/macOS para teste, mas o que sai é um
programa daquele sistema, não um `.exe`.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND = RAIZ / "backend"
FRONTEND = RAIZ / "frontend"
DIST = RAIZ / "dist"
WEB_EMPACOTADA = BACKEND / "web"
VERSAO_ARQUIVO = RAIZ / "versao.txt"

NOME_APP = "NotasFlow"
REPO_PADRAO = "montx2/Cajuru28"


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------


def log(mensagem: str) -> None:
    print(f"[empacotar] {mensagem}", flush=True)


def falhar(mensagem: str, codigo: int = 1) -> None:
    print(f"[empacotar] ERRO: {mensagem}", file=sys.stderr, flush=True)
    raise SystemExit(codigo)


def rodar(comando: list[str], *, cwd: Path | None = None) -> None:
    log(" ".join(comando))
    resultado = subprocess.run(comando, cwd=cwd or RAIZ)
    if resultado.returncode != 0:
        falhar(f"comando terminou com código {resultado.returncode}: {' '.join(comando)}")


def ler_versao(explicita: str | None) -> str:
    """
    Versão do build.

    Formato `MAIOR.MENOR.CORRECAO` — o atualizador compara número por número
    (`1.10.0` é mais novo que `1.9.0`), o que só funciona se o formato for
    respeitado. Publicar `1.2` e depois `1.2.1` também funciona: as partes que
    faltam valem zero.
    """
    if explicita:
        versao = explicita.strip().lstrip("vV")
    elif VERSAO_ARQUIVO.is_file():
        versao = VERSAO_ARQUIVO.read_text(encoding="utf-8").strip()
    else:
        versao = "0.0.0"

    if not versao or not all(parte.isdigit() for parte in versao.split(".") if parte != ""):
        falhar(f"versão inválida: {versao!r} (use números separados por ponto, ex.: 1.2.0)")
    return versao


def sha256_arquivo(caminho: Path) -> str:
    digestor = hashlib.sha256()
    with caminho.open("rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(1024 * 1024), b""):
            digestor.update(bloco)
    return digestor.hexdigest()


def limpar() -> None:
    for pasta in (DIST, RAIZ / "build", WEB_EMPACOTADA):
        if pasta.exists():
            log(f"removendo {pasta.relative_to(RAIZ)}")
            shutil.rmtree(pasta, ignore_errors=True)


# ---------------------------------------------------------------------------
# 1. Painel web
# ---------------------------------------------------------------------------


def compilar_painel(pular: bool) -> None:
    """
    Compila o painel e o coloca em `backend/web`.

    O painel é o que o `.exe` mostra. Compilar aqui — e não no computador do
    contador — é o que permite que o programa instalado não precise de Node,
    de servidor web separado nem de internet.
    """
    saida = FRONTEND / "out"
    if pular:
        if not (saida / "index.html").is_file():
            falhar("--sem-frontend foi usado, mas frontend/out não existe (rode o build antes)")
        log("usando o painel já compilado em frontend/out")
    else:
        if not (FRONTEND / "node_modules").is_dir():
            falhar("frontend/node_modules não existe — rode `npm ci` na pasta frontend")
        if shutil.which("npm") is None:
            falhar("npm não encontrado no PATH — instale o Node.js 20+ para compilar o painel")
        rodar(["npm", "run", "build:desktop"], cwd=FRONTEND)
        if not (saida / "index.html").is_file():
            falhar("o build do painel não gerou frontend/out/index.html")

    if WEB_EMPACOTADA.exists():
        shutil.rmtree(WEB_EMPACOTADA)
    shutil.copytree(saida, WEB_EMPACOTADA)

    # O `.gitignore` ignora `backend/web`: é artefato de build, não código.
    arquivos = sum(1 for _ in WEB_EMPACOTADA.rglob("*") if _.is_file())
    tamanho = sum(arquivo.stat().st_size for arquivo in WEB_EMPACOTADA.rglob("*") if arquivo.is_file())
    log(f"painel copiado para backend/web ({arquivos} arquivos, {tamanho / 1024 / 1024:.1f} MB)")


# ---------------------------------------------------------------------------
# 2. PyInstaller
# ---------------------------------------------------------------------------


def escrever_info_de_versao(versao: str) -> Path:
    """
    Metadados que o Windows mostra em Propriedades → Detalhes do `.exe`.

    Vale o esforço porque é o que um suporte técnico — ou o próprio Windows
    Defender — lê para identificar o arquivo. Um `.exe` sem versão nem nome de
    empresa é exatamente o perfil que antivírus tratam com desconfiança.
    """
    partes = [int(p) if p.isdigit() else 0 for p in versao.split(".")]
    while len(partes) < 4:
        partes.append(0)
    tupla = ", ".join(str(parte) for parte in partes[:4])
    texto = f"""VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({tupla}),
    prodvers=({tupla}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '040904B0',
        [StringStruct('CompanyName', 'NotasFlow'),
         StringStruct('FileDescription', 'NotasFlow - importacao automatica de notas fiscais'),
         StringStruct('FileVersion', '{versao}'),
         StringStruct('InternalName', 'NotasFlow'),
         StringStruct('LegalCopyright', 'NotasFlow'),
         StringStruct('OriginalFilename', 'NotasFlow.exe'),
         StringStruct('ProductName', 'NotasFlow'),
         StringStruct('ProductVersion', '{versao}')])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""
    destino = BACKEND / "versao_do_exe.txt"
    destino.write_text(texto, encoding="utf-8")
    return destino


def rodar_pyinstaller() -> Path:
    """Roda o PyInstaller com o `.spec` versionado."""
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        falhar(
            "PyInstaller não está instalado nesta máquina.\n"
            "         instale com: pip install -r backend/requirements-desktop.txt"
        )

    rodar(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(RAIZ / "build"),
            str(BACKEND / "notasflow.spec"),
        ],
        cwd=BACKEND,
    )

    pasta = DIST / NOME_APP
    if not (pasta / ("NotasFlow.exe" if os.name == "nt" else "NotasFlow")).exists():
        # Em Linux/macOS o executável sai sem extensão.
        candidatos = [p for p in pasta.glob("NotasFlow*") if p.is_file()] if pasta.is_dir() else []
        if not candidatos:
            falhar(f"o PyInstaller não gerou o executável em {pasta}")
    return pasta


def gravar_versao_na_pasta(pasta: Path, versao: str) -> None:
    """
    `versao.txt` fora do pacote.

    Dentro do `.exe` a versão está no `versao.txt` empacotado, mas o
    atualizador precisa poder corrigi-la em uma instalação já feita (é assim
    que se faz um "rollback de versão" sem reinstalar). Gravar ao lado do
    executável resolve os dois casos.
    """
    (pasta / "versao.txt").write_text(versao + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# 3. ZIP portátil
# ---------------------------------------------------------------------------


def gerar_zip(pasta: Path, versao: str) -> Path:
    """
    ZIP com a pasta do programa — a alternativa ao instalador.

    Serve para dois cenários reais: máquina sem permissão de administrador
    (extrai em `C:\\NotasFlow` e cria um atalho na mão) e envio por pendrive.
    """
    destino = DIST / f"{NOME_APP}-{versao}-portatil.zip"
    log(f"compactando {destino.name}")
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as pacote:
        for arquivo in sorted(pasta.rglob("*")):
            if arquivo.is_file():
                pacote.write(arquivo, Path(NOME_APP) / arquivo.relative_to(pasta))
    return destino


# ---------------------------------------------------------------------------
# 4. Instalador (Inno Setup)
# ---------------------------------------------------------------------------


def achar_inno() -> str | None:
    candidatos = [
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidato in candidatos:
        if candidato and Path(candidato).is_file():
            return str(candidato)
    return None


def compilar_instalador(versao: str, tentar: bool) -> Path | None:
    if not tentar:
        return None
    iscc = achar_inno()
    if not iscc:
        log(
            "Inno Setup não encontrado — gerando apenas o ZIP portátil.\n"
            "         para o instalador: https://jrsoftware.org/isdl.php"
        )
        return None

    rodar(
        [
            iscc,
            f"/DVersao={versao}",
            f"/DOrigem={DIST / NOME_APP}",
            f"/DSaida={DIST}",
            str(RAIZ / "installer" / "notasflow.iss"),
        ]
    )
    instalador = DIST / f"{NOME_APP}-Setup-{versao}.exe"
    if not instalador.is_file():
        falhar(f"o Inno Setup não gerou {instalador}")
    return instalador


# ---------------------------------------------------------------------------
# 5. Manifesto
# ---------------------------------------------------------------------------


def escrever_manifesto(
    versao: str,
    instalador: Path | None,
    portatil: Path,
    pasta: Path,
    *,
    notas: str,
    obrigatoria: bool,
    repo: str,
) -> Path:
    """
    Escreve `dist/latest.json` — o arquivo que faz a atualização acontecer.

    O formato tem duas formas, e as duas são aceitas pelo atualizador:

    - **com `url`** (é o que sai daqui): o download aponta para o instalador.
      É o caminho do GitHub Releases e de uma pasta de rede;
    - **sem `url`**: o programa procura o arquivo pelo *nome* ao lado do
      manifesto. Útil quando quem publica quer só jogar os dois arquivos numa
      pasta compartilhada sem editar JSON.

    O `sha256` é obrigatório na prática: é ele que garante que o arquivo
    baixado é o que foi publicado, mesmo se o download passar por um proxy
    corporativo ou por uma conexão instável.
    """
    alvo = instalador or portatil
    arquivos = {}
    if instalador is not None:
        arquivos["windows-instalador"] = {
            "url": instalador.name,
            "sha256": sha256_arquivo(instalador),
            "tamanho": instalador.stat().st_size,
            "tipo": "instalador",
        }
    arquivos["windows-portatil"] = {
        "url": portatil.name,
        "sha256": sha256_arquivo(portatil),
        "tamanho": portatil.stat().st_size,
        "tipo": "zip",
    }

    manifesto = {
        "versao": versao,
        "data": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "obrigatoria": obrigatoria,
        "notas": notas or f"Versão {versao} do NotasFlow.",
        "repositorio": repo,
        "arquivos": arquivos,
    }
    destino = DIST / "latest.json"
    destino.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    log("")
    log("=" * 68)
    log(f"  {NOME_APP} {versao} pronto")
    log("=" * 68)
    log(f"  programa    {pasta}")
    log(f"  sha256      {arquivos.get('windows-instalador', arquivos['windows-portatil'])['sha256']}")
    log(f"  instalador  {alvo.name}")
    log(f"  manifesto   {destino}")
    log("")
    log("  para publicar (todos os programas instalados passam a ver a versão):")
    log(f"      gh release create v{versao} {alvo.name} {destino.name} \\")
    log(f"          --repo {repo} --title \"{NOME_APP} {versao}\" --notes \"{manifesto['notas']}\"")
    log("=" * 68)
    return destino


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(description="Empacota o NotasFlow para distribuição.")
    analisador.add_argument("--sem-frontend", action="store_true", help="reaproveita frontend/out")
    analisador.add_argument("--sem-instalador", "--portatil", action="store_true", dest="sem_instalador")
    analisador.add_argument("--versao", help="versão do build (padrão: conteúdo de versao.txt)")
    analisador.add_argument("--limpar", action="store_true", help="apaga build/, dist/ e backend/web/")
    analisador.add_argument("--notas", default="", help="o que mudou nesta versão (aparece no aviso)")
    analisador.add_argument("--obrigatoria", action="store_true", help="atualização que não pode ser adiada")
    analisador.add_argument("--repo", default=os.environ.get("NOTASFLOW_REPO", REPO_PADRAO))
    argumentos = analisador.parse_args(argv)

    versao = ler_versao(argumentos.versao)
    log(f"empacotando {NOME_APP} {versao} em {RAIZ}")

    if argumentos.limpar:
        limpar()

    compilar_painel(argumentos.sem_frontend)
    escrever_info_de_versao(versao)
    pasta = rodar_pyinstaller()
    gravar_versao_na_pasta(pasta, versao)
    portatil = gerar_zip(pasta, versao)
    instalador = compilar_instalador(versao, tentar=not argumentos.sem_instalador)
    escrever_manifesto(
        versao,
        instalador,
        portatil,
        pasta,
        notas=argumentos.notas,
        obrigatoria=argumentos.obrigatoria,
        repo=argumentos.repo,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
