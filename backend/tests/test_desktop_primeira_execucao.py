"""
Primeira abertura do programa instalado — o momento mais frágil do modo desktop.

Tudo o que o contador faz é dar dois cliques no `.exe` num computador onde não
existe Python, PostgreSQL, Redis nem nada do ambiente de desenvolvimento. A
primeira abertura precisa, sozinha:

- criar a pasta de dados do usuário, fora da pasta do programa;
- gerar o `.env` com banco SQLite local, `SECRET_KEY` e `VAULT_MASTER_KEY`;
- criar o usuário administrador e escrever a senha em `CREDENCIAIS.txt`;
- **nunca** tocar no banco do servidor (`...@db:5432/...`) — que é o valor
  padrão do código e não existe na máquina do cliente.

Os dois primeiros testes existem por causa de um erro real: o padrão do
`database_url` é o PostgreSQL do `docker-compose`, e uma instalação nova que não
gerasse o `.env` antes de carregar a configuração morria no startup com
`could not translate host name "db"` — uma mensagem que não diz nada a quem está
olhando. Se alguém mexer no `desktop_main.py` ou no `config.py`, é aqui que o
erro aparece: no teste, não no computador do cliente.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

RAIZ_BACKEND = Path(__file__).resolve().parent.parent


def test_modo_desktop_sem_env_cai_para_sqlite_local(monkeypatch, tmp_path):
    """Sem `.env` nenhum, o modo desktop não pode apontar para o banco do Docker."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DADOS_DIR", raising=False)
    monkeypatch.setenv("MODO_DESKTOP", "true")
    monkeypatch.setenv("NOTASFLOW_DATA_DIR", str(tmp_path))

    from app.core.config import Settings

    configuracao = Settings(_env_file=None)

    assert configuracao.database_url.startswith("sqlite:///")
    assert str(tmp_path) in configuracao.database_url
    assert configuracao.dados_dir.startswith(str(tmp_path))
    assert configuracao.usando_sqlite is True


def test_modo_servidor_mantem_postgresql(monkeypatch, tmp_path):
    """A rede de segurança não pode atrapalhar a implantação em servidor."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("MODO_DESKTOP", "false")

    from app.core.config import Settings

    configuracao = Settings(_env_file=None)
    assert configuracao.database_url.startswith("postgresql")


def test_primeira_execucao_do_programa(tmp_path):
    """
    Roda o `desktop_main.py --diagnostico` de verdade, com a pasta de dados
    vazia, do jeito que o `.exe` roda na primeira abertura.

    É o teste mais próximo do "baixei o programa e abri": se ele passa, a
    primeira abertura funciona em um computador sem nada instalado.
    """
    pasta_dados = tmp_path / "NotasFlow"
    ambiente = {
        chave: valor
        for chave, valor in os.environ.items()
        if chave
        not in {
            # Nada do ambiente de desenvolvimento pode vazar para o teste: o
            # objetivo é justamente provar que a instalação limpa se configura.
            "DATABASE_URL",
            "DADOS_DIR",
            "MODO_DESKTOP",
            "NOTASFLOW_ENV_FILE",
            "VAULT_MASTER_KEY",
            "SECRET_KEY",
            "BOOTSTRAP_EMAIL",
            "BOOTSTRAP_SENHA",
        }
    }
    ambiente["NOTASFLOW_DATA_DIR"] = str(pasta_dados)
    ambiente["PYTHONPATH"] = str(RAIZ_BACKEND)

    resultado = subprocess.run(
        [sys.executable, "desktop_main.py", "--diagnostico"],
        cwd=RAIZ_BACKEND,
        env=ambiente,
        capture_output=True,
        text=True,
        timeout=170,
    )

    assert resultado.returncode == 0, resultado.stderr[-2000:]
    assert "Banco: OK" in resultado.stdout

    relatorio = json.loads(resultado.stdout.split("Banco: OK")[0])
    assert relatorio["modo_desktop"] is True
    assert relatorio["banco"].startswith("sqlite")
    assert str(pasta_dados) in relatorio["banco"]
    assert relatorio["painel_web_presente"] is True

    # Os arquivos que o contador precisa (ou precisa poder apagar) existem.
    assert (pasta_dados / ".env").is_file()
    assert (pasta_dados / "notasflow.db").is_file()

    credenciais = (pasta_dados / "CREDENCIAIS.txt").read_text(encoding="utf-8")
    assert "E-mail:" in credenciais and "Senha:" in credenciais

    configuracao = (pasta_dados / ".env").read_text(encoding="utf-8")
    assert "VAULT_MASTER_KEY=" in configuracao
    assert "SQLite" in configuracao or "sqlite" in configuracao


def test_segunda_execucao_respeita_a_configuracao_existente(tmp_path):
    """
    Rodar de novo não pode gerar chave nova.

    Trocar a `VAULT_MASTER_KEY` tornaria indecifráveis as senhas dos
    certificados A1 já cadastrados — o usuário teria que reenviar todos.
    """
    from app.desktop import ambiente

    pasta = tmp_path / "dados"
    os.environ["NOTASFLOW_DATA_DIR"] = str(pasta)
    os.environ["NOTASFLOW_ENV_FILE"] = str(pasta / ".env")
    try:
        primeira = ambiente.preparar_primeira_execucao(silencioso=True)
        assert primeira["criado_agora"] is True
        conteudo = (pasta / ".env").read_text(encoding="utf-8")

        segunda = ambiente.preparar_primeira_execucao(silencioso=True)
        assert segunda["criado_agora"] is False
        assert (pasta / ".env").read_text(encoding="utf-8") == conteudo
    finally:
        os.environ.pop("NOTASFLOW_DATA_DIR", None)
        os.environ.pop("NOTASFLOW_ENV_FILE", None)


# ---------------------------------------------------------------------------
# Porta do painel
# ---------------------------------------------------------------------------


def _ocupar(porta: int) -> socket.socket:
    soquete = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soquete.bind(("127.0.0.1", porta))
    soquete.listen(5)
    return soquete


def test_porta_preferida_e_usada_quando_esta_livre():
    """
    O endereço do painel tem de ser sempre o mesmo.

    Antes, esta função só devolvia a porta preferida quando ela estava
    **ocupada** por outro programa — ou seja: em computador limpo ela nunca era
    usada, e o endereço mudava a cada abertura. Pior: duas instâncias abertas em
    momentos diferentes escolhiam portas aleatórias diferentes, cada uma se
    achando a única, e as duas consultariam a SEFAZ com o mesmo certificado.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sonda:
        sonda.bind(("127.0.0.1", 0))
        livre = int(sonda.getsockname()[1])

    from app.desktop.servidor import escolher_porta

    porta, ja_rodando = escolher_porta(livre)
    assert (porta, ja_rodando) == (livre, False)


def test_porta_seguinte_quando_outro_programa_ocupou():
    from app.desktop.servidor import escolher_porta

    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sonda:
        sonda.bind(("127.0.0.1", 0))
        ocupada = int(sonda.getsockname()[1])

    soquete = _ocupar(ocupada)
    try:
        porta, ja_rodando = escolher_porta(ocupada)
        assert porta != ocupada
        assert ja_rodando is False  # é outro programa, não outro NotasFlow
    finally:
        soquete.close()
