"""
Onde cada arquivo mora quando o NotasFlow roda como programa instalado.

Existem três "mundos" diferentes e misturar os três é a causa número um de
programa empacotado que funciona na máquina do desenvolvedor e não funciona na
do cliente:

1. **código-fonte** (`python -m desktop_main`) — tudo é relativo ao repositório;
2. **programa empacotado** (PyInstaller, `sys.frozen`) — os arquivos do pacote
   ficam em `sys._MEIPASS` (temporário, somente leitura, some quando fecha);
3. **dados do usuário** — banco, certificados, XMLs, `.env`, logs. Estes
   *nunca* podem ficar dentro do pacote: instalar uma versão nova apaga a pasta
   do programa, e apagar a pasta de dados significa perder certificado e nota.

Este módulo é a única fonte de verdade para esses três lugares. Todo o resto do
sistema pergunta para cá.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOME_APP = "NotasFlow"


def esta_empacotado() -> bool:
    """True quando rodando de dentro do `.exe` gerado pelo PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def pasta_recursos() -> Path:
    """
    Onde estão os arquivos empacotados junto com o programa
    (o build estático do painel web, ícones, a versão).

    - empacotado: `sys._MEIPASS` (a pasta temporária que o PyInstaller cria);
    - código-fonte: `backend/` — a pasta que contém o pacote `app`.

    Não é "a raiz do repositório": rodando do fonte, `backend/web` é o mesmo
    lugar onde o pacote espera encontrar o painel compilado — e é para lá que
    `scripts/empacotar.py` copia `frontend/out`. Manter os dois casos iguais é o
    que faz um bug de caminho aparecer no teste, e não no `.exe`.
    """
    if esta_empacotado():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


def raiz_do_repositorio() -> Path | None:
    """
    A raiz do checkout — só existe rodando do código-fonte.

    Serve para achar coisas que **não** fazem parte do pacote e que só
    interessam a quem está desenvolvendo: a versão do build (`versao.txt` na
    raiz) e o painel recém-compilado (`frontend/out`).
    """
    if esta_empacotado():
        return None
    candidato = Path(__file__).resolve().parents[3]
    return candidato if (candidato / "versao.txt").is_file() or (candidato / "frontend").is_dir() else None


def pasta_programa() -> Path:
    """
    Onde o `.exe` (ou o módulo) está instalado de verdade.

    Diferente de `pasta_recursos()`: num build "onedir" do PyInstaller esta é a
    pasta que o instalador cria/atualiza. É o que o atualizador precisa saber.
    """
    if esta_empacotado():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _pasta_dados_padrao() -> Path:
    """Pasta de dados por sistema operacional, seguindo a convenção de cada um."""
    explicito = os.environ.get("NOTASFLOW_DATA_DIR")
    if explicito:
        return Path(explicito).expanduser()

    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / NOME_APP
        return Path.home() / "AppData" / "Roaming" / NOME_APP

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / NOME_APP

    base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
    return Path(base) / "notasflow"


def pasta_dados() -> Path:
    """
    Pasta de dados do usuário (criada se não existir).

    Sobrevive a atualização, desinstalação e reinstalação. É o que o contador
    precisa fazer backup.
    """
    pasta = _pasta_dados_padrao()
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_logs() -> Path:
    pasta = pasta_dados() / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def pasta_backups() -> Path:
    pasta = pasta_dados() / "backups"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def arquivo_env() -> Path:
    """O `.env` do modo desktop — dentro da pasta de dados, não do programa."""
    explicito = os.environ.get("NOTASFLOW_ENV_FILE")
    if explicito:
        return Path(explicito).expanduser()
    return pasta_dados() / ".env"


def caminho_banco() -> Path:
    return pasta_dados() / "notasflow.db"


def pasta_web() -> Path:
    """
    O painel web já compilado (build estático do Next.js).

    Procura em alguns lugares porque o layout muda entre "rodando do fonte"
    (onde o build sai em `frontend/out`) e "empacotado" (onde o PyInstaller
    copia para `web/` na raiz do pacote).
    """
    candidatos = [
        pasta_recursos() / "web",  # pacote empacotado (PyInstaller) e `backend/web`
        pasta_programa() / "web",  # pacote "onedir"
    ]
    raiz = raiz_do_repositorio()
    if raiz is not None:
        # Desenvolvimento: o painel compilado pelo Next.js fica em frontend/out.
        candidatos.append(raiz / "frontend" / "out")

    for candidato in candidatos:
        if (candidato / "index.html").is_file():
            return candidato
    # Devolve o primeiro candidato mesmo sem o build: quem chamou decide o que
    # fazer (avisar na tela é melhor que estourar uma exceção de caminho).
    return candidatos[0]


def tem_painel_web() -> bool:
    return (pasta_web() / "index.html").is_file()


def versao_do_pacote() -> str:
    """
    Versão do programa instalado.

    A fonte é o arquivo `versao.txt` gravado no pacote pelo build: dentro do
    `.exe` não existe `pyproject.toml` nem metadados confiáveis, e a versão
    precisa ser a mesma que o atualizador compara com o servidor.
    """
    raiz = raiz_do_repositorio()
    candidatos = [
        pasta_recursos() / "versao.txt",
        pasta_programa() / "versao.txt",
        # Rodando do fonte, a versão é a do `versao.txt` do repositório — a
        # mesma que o build usa para nomear o instalador. Sem isso, todo teste
        # local veria "0.0.0".
        *( [raiz / "versao.txt"] if raiz is not None else [] ),
    ]
    for candidato in candidatos:
        try:
            if candidato.is_file():
                return candidato.read_text(encoding="utf-8").strip() or "0.0.0"
        except OSError:
            continue
    return os.environ.get("NOTASFLOW_VERSAO", "0.0.0")


def descricao_ambiente() -> dict[str, object]:
    """Diagnóstico: o que a tela de "Sobre" mostra para o suporte."""
    return {
        "empacotado": esta_empacotado(),
        "pasta_programa": str(pasta_programa()),
        "pasta_dados": str(pasta_dados()),
        "pasta_logs": str(pasta_logs()),
        "pasta_web": str(pasta_web()),
        "painel_web_presente": tem_painel_web(),
        "python": sys.version.split()[0],
        "sistema": sys.platform,
        "versao": versao_do_pacote(),
    }
