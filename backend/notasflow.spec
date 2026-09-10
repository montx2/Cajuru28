# -*- mode: python ; coding: utf-8 -*-
"""
Receita do PyInstaller para gerar o NotasFlow.exe.

Por que um `.spec` versionado em vez de uma linha de `pyinstaller` no README:
o comando na linha de comando não cabe em um arquivo, e o que não cabe no
arquivo são justamente as partes que quebram na máquina do cliente —
`hiddenimports`, `datas`, exclusões. Um `.spec` é reproduzível: o `.exe` que
sai do meu computador é o mesmo que sai do runner do GitHub Actions.

## Decisões que este arquivo toma

**`--onedir`, não `--onefile`.** O `--onefile` extrai todo o Python, o
SQLAlchemy e a criptografia para uma pasta temporária a **cada** abertura —
num programa que o contador abre todos os dias, isso é vários segundos de
espera e uma pasta `_MEIxxxx` que antivírus gostam de escanear. O `--onedir`
abre rápido, o instalador (Inno Setup) entrega o mesmo "um arquivo para
baixar", e a atualização troca a pasta inteira sem surpresa.

**`console=False`.** Este é um programa de mesa: janela sem terminal preto
atrás. O log continua existindo em `%APPDATA%\\NotasFlow\\logs` e aparece na
tela de Configurações — só não é escrito numa tela preta que fecha sozinha e
que ninguém consegue copiar.

**Sem UPX.** Compactar os binários economiza alguns MB e custa falsos
positivos de antivírus em máquina de escritório — um programa fiscal que o
Windows Defender coloca em quarentena é um programa que não existe.

**Sem Celery, Redis e PostgreSQL.** No modo desktop a fila é em processo
(`app/desktop/fila_local.py`) e o banco é SQLite. As três bibliotecas somam
dezenas de MB que nunca seriam importadas; por isso estão em `excludes`.
"""

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

RAIZ = Path(SPECPATH).resolve()  # backend/
REPO = RAIZ.parent


def _versao() -> str:
    arquivo = REPO / "versao.txt"
    if arquivo.is_file():
        return arquivo.read_text(encoding="utf-8").strip() or "0.0.0"
    return os.environ.get("NOTASFLOW_VERSAO", "0.0.0")


VERSAO = _versao()

# ---------------------------------------------------------------------------
# Arquivos empacotados junto com o programa
# ---------------------------------------------------------------------------
# A pasta `web/` é o painel compilado (export estático do Next.js). Ela é
# copiada para cá por `scripts/empacotar.py` antes de chamar o PyInstaller —
# e é por isso que o `.exe` não precisa de Node instalado para servir a tela.
datas = [
    (str(RAIZ / "web"), "web"),
    (str(REPO / "versao.txt"), "."),
    (str(RAIZ / "icone.png"), "."),
]

# O ícone do `.exe` no Windows. Sem ele o programa aparece com o ícone genérico
# na barra de tarefas e no menu Iniciar — e é isso que faz um sistema parecer
# provisório.
icone = REPO / "installer" / "notasflow.ico"

# ---------------------------------------------------------------------------
# Imports que a análise estática não vê
# ---------------------------------------------------------------------------
# Todos abaixo são carregados por **nome em tempo de execução** (uvicorn escolhe
# o protocolo por string, o SQLAlchemy escolhe o dialeto por URL, o passlib
# carrega handlers por lazy-loader). Sem esta lista, o programa abre e só falha
# no primeiro clique — o pior tipo de falha para depurar no cliente.
hiddenimports = [
    # uvicorn monta o servidor por string de configuração
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    "uvicorn.lifespan.off",
    # banco: SQLite é o banco do modo desktop
    "sqlalchemy.dialects.sqlite",
    "sqlalchemy.dialects.sqlite.pysqlite",
    "sqlite3",
    # o passlib resolve `bcrypt` por nome na primeira autenticação
    "passlib.handlers.bcrypt",
    "passlib.handlers.pbkdf2",
    # assinatura/leitura de certificado A1
    "jose.backends.cryptography_backend",
    "cryptography.hazmat.backends.openssl",
    # o agendador procura as tarefas por nome
    "app.worker.tasks",
    # bandeja do sistema (Windows) e ícone
    "app.desktop.bandeja",
    "pystray",
    "PIL.Image",
    "PIL.ImageDraw",
    "PIL._tkinter_finder",
]

# Toda a árvore do projeto entra: são poucos arquivos e assim nenhum módulo
# novo deixa de ser empacotado por esquecimento de lista.
hiddenimports += collect_submodules("app")

excludes = [
    # modo servidor — não existem no programa instalado
    "celery",
    "kombu",
    "billiard",
    "amqp",
    "vine",
    "redis",
    "psycopg2",
    # interface gráfica alternativa: a janela é o navegador do sistema
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "wx",
    # ferramentas de desenvolvimento que acabam dentro de builds por descuido
    "pytest",
    "IPython",
    "notebook",
    "matplotlib",
    "numpy",
    "pandas",
    "scipy",
    "sqlite3.test",
]

a = Analysis(
    [str(RAIZ / "desktop_main.py")],
    pathex=[str(RAIZ)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NotasFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # ver comentário no topo: UPX ⇒ antivírus ⇒ chamado de suporte
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(icone) if icone.is_file() else None,
    version=str(RAIZ / "versao_do_exe.txt") if (RAIZ / "versao_do_exe.txt").is_file() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NotasFlow",
)

# A versão também é gravada ao lado do `.exe` — fora do pacote — porque
# `caminhos.versao_do_pacote()` procura primeiro na pasta do programa. Isso é
# feito por `scripts/empacotar.py` depois do PyInstaller terminar: aqui, dentro
# do `.spec`, a pasta `dist/` ainda não existe.
print(f"[notasflow.spec] empacotando a versão {VERSAO}")
