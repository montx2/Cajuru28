"""
A atualização automática é a única forma de corrigir um erro em 5 computadores.

O modo de distribuição escolhido (programa instalado em cada máquina, em vez de
site único) tem um único preço: **publicar não atualiza ninguém**. Quem atualiza
é o próprio programa, e é isso que estes testes cobrem.

O que precisa ser verdade:

1. versão se compara por número, não por texto (`1.10.0` > `1.9.0`);
2. manifesto publicado no GitHub é lido pelo caminho que não gasta cota de API;
3. o arquivo baixado é conferido por SHA-256 — uma conexão que corrompeu o
   download não pode virar instalação;
4. ficar sem internet nunca impede o programa de abrir;
5. o instalador é chamado silencioso e por cima, e o programa sai antes disso
   (senão o Windows não deixa o instalador trocar os arquivos).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.desktop import atualizador


# ---------------------------------------------------------------------------
# Comparação de versões
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("publicada", "instalada", "esperado"),
    [
        ("1.0.1", "1.0.0", True),
        ("1.0.0", "1.0.0", False),
        ("1.9.0", "1.10.0", False),  # comparar como texto daria True
        ("1.10.0", "1.9.0", True),
        ("2.0", "1.99.99", True),
        ("v1.2.3", "1.2.2", True),  # tag do Git costuma vir com "v"
        ("0.0.0", "1.0.0", False),
    ],
)
def test_versao_comparada_por_numero(publicada, instalada, esperado):
    assert atualizador.versao_mais_nova(publicada, instalada) is esperado


def test_url_do_manifesto_usa_o_caminho_sem_cota_da_api(monkeypatch):
    """
    `api.github.com` limita 60 consultas/hora por IP — e um escritório inteiro
    sai pelo mesmo IP. O caminho `releases/latest/download/` é um
    redirecionamento estático, sem esse limite.
    """
    monkeypatch.setattr(atualizador.settings, "notasflow_update_manifest", "")
    monkeypatch.setattr(atualizador.settings, "notasflow_repo", "montx2/Cajuru28")
    assert atualizador.url_do_manifesto() == (
        "https://github.com/montx2/Cajuru28/releases/latest/download/latest.json"
    )


def test_manifesto_pode_ser_pasta_de_rede(monkeypatch, tmp_path):
    """Escritório sem internet publica numa pasta compartilhada — e funciona."""
    monkeypatch.setattr(atualizador.settings, "notasflow_update_manifest", str(tmp_path))
    url = atualizador.url_do_manifesto()
    assert url.endswith("latest.json")
    assert not url.startswith("http")


# ---------------------------------------------------------------------------
# Leitura do manifesto e verificação de versão
# ---------------------------------------------------------------------------


def _manifesto(pasta: Path, versao: str = "1.1.0", *, com_arquivo: bool = True) -> dict:
    dados: dict = {"versao": versao, "notas": "Corrige o cancelamento de NFS-e.", "obrigatoria": False}
    if com_arquivo:
        instalador = pasta / f"NotasFlow-Setup-{versao}.exe"
        instalador.write_bytes(b"conteudo do instalador de teste" * 10)
        dados["arquivos"] = {
            "windows-instalador": {
                "url": instalador.name,
                "sha256": hashlib.sha256(instalador.read_bytes()).hexdigest(),
                "tamanho": instalador.stat().st_size,
            }
        }
    (pasta / "latest.json").write_text(json.dumps(dados), encoding="utf-8")
    return dados


@pytest.fixture
def pasta_publicada(monkeypatch, tmp_path):
    monkeypatch.setattr(atualizador.settings, "notasflow_update_manifest", str(tmp_path))
    return tmp_path


@pytest.fixture
def como_windows(monkeypatch):
    """
    Faz a escolha de arquivo se comportar como no computador do contador.

    O manifesto publicado tem um arquivo por sistema (`windows-instalador`,
    `macos`, `linux`). Rodando a suíte no Linux, sem este ajuste, o teste veria
    "versão publicada mas sem arquivo para este sistema" — que é o comportamento
    certo da função e o errado para o que se quer testar aqui: o caminho que
    roda na máquina do usuário.
    """
    monkeypatch.setattr(atualizador.platform, "system", lambda: "Windows")


def test_verificar_encontra_versao_nova(pasta_publicada, como_windows, monkeypatch):
    _manifesto(pasta_publicada, "1.1.0")
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")

    progresso = atualizador.Progresso()
    atualizacao = atualizador.verificar(progresso)

    assert atualizacao is not None
    assert atualizacao.versao == "1.1.0"
    assert atualizacao.notas.startswith("Corrige")
    # O caminho relativo do manifesto vira caminho completo na pasta publicada
    assert Path(atualizacao.arquivo.url).name == "NotasFlow-Setup-1.1.0.exe"


def test_verificar_ignora_versao_igual_ou_antiga(pasta_publicada, como_windows, monkeypatch):
    _manifesto(pasta_publicada, "1.0.0")
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")
    assert atualizador.verificar() is None


def test_verificar_sem_internet_nao_derruba_o_programa(monkeypatch, tmp_path):
    """
    O caso real: o contador abre o programa no avião, no cliente ou com o
    roteador caído. A verificação falha em silêncio e o programa abre igual.
    """
    monkeypatch.setattr(atualizador.settings, "notasflow_update_manifest", str(tmp_path / "inexistente"))
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")
    assert atualizador.verificar() is None


def test_manifesto_sem_arquivo_para_windows_nao_promete_atualizacao(pasta_publicada, como_windows, monkeypatch):
    """Publicar só para macOS: aqui não pode aparecer "versão disponível"."""
    _manifesto(pasta_publicada, "1.1.0", com_arquivo=False)
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")
    assert atualizador.verificar() is None


# ---------------------------------------------------------------------------
# Download e conferência
# ---------------------------------------------------------------------------


def test_download_confere_o_sha256(pasta_publicada, como_windows, monkeypatch):
    _manifesto(pasta_publicada, "1.1.0")
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")
    atualizacao = atualizador.verificar()
    destino = atualizador.baixar(atualizacao)
    assert destino.is_file()
    assert destino.stat().st_size == atualizacao.arquivo.tamanho


def test_download_com_hash_diferente_e_recusado(pasta_publicada, como_windows, monkeypatch):
    """
    Este é o teste que protege o escritório inteiro: se o arquivo publicado for
    trocado (inclusive por um ataque no meio do caminho), a instalação para.
    """
    dados = _manifesto(pasta_publicada, "1.1.0")
    dados["arquivos"]["windows-instalador"]["sha256"] = "0" * 64
    (pasta_publicada / "latest.json").write_text(json.dumps(dados), encoding="utf-8")
    monkeypatch.setattr(atualizador, "versao_atual", lambda: "1.0.0")

    atualizacao = atualizador.verificar()
    with pytest.raises(atualizador.ErroDeAtualizacao):
        atualizador.baixar(atualizacao)


def test_download_por_http_simples_e_recusado(monkeypatch):
    arquivo = atualizador.ArquivoAtualizacao(url="http://exemplo.invalido/setup.exe")
    with pytest.raises(atualizador.ErroDeAtualizacao):
        atualizador.baixar(atualizador.Atualizacao(versao="1.1.0", arquivo=arquivo))


# ---------------------------------------------------------------------------
# Aplicação (o que roda no Windows)
# ---------------------------------------------------------------------------


def test_aplicar_fora_do_windows_explica_em_vez_de_falhar_sem_avisar(monkeypatch):
    """
    Off-Windows o instalador não existe. O correto é **dizer isso** e não
    deixar o usuário esperando um botão que não faz nada — foi o que motivou
    este comportamento.
    """
    if atualizador.platform.system() == "Windows":  # pragma: no cover
        pytest.skip("comportamento específico de outros sistemas")

    pasta = Path("/tmp/nao-usado")
    atualizacao = atualizador.Atualizacao(
        versao="1.1.0",
        arquivo=atualizador.ArquivoAtualizacao(url=str(pasta / "setup.exe")),
    )
    with pytest.raises(atualizador.ErroDeAtualizacao):
        atualizador.aplicar(atualizacao)


def test_caminho_do_instalador_silencioso():
    """
    As bandeiras do Inno Setup que fazem a atualização não pedir nada a
    ninguém. Se alguém "limpar" esta lista, a atualização automática passa a
    abrir uma janela no meio do expediente — e a falhar em computador sem
    ninguém olhando.
    """
    assert atualizador.FLAGS_SILENCIOSAS.startswith("/VERYSILENT")
    for bandeira in ("/SUPPRESSMSGBOXES", "/NORESTART", "/NOCANCEL"):
        assert bandeira in atualizador.FLAGS_SILENCIOSAS
