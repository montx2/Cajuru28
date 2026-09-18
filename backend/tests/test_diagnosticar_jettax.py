"""Contrato do script de diagnóstico Jettax (scripts/diagnosticar_jettax.py).

O script roda no servidor, fora do pytest; o que estes testes garantem é o
essencial para um operador confiar nele:

- as conclusões certas para token recusado x aceito;
- o token (do cofre ou devolvido pelo login) e a senha nunca aparecem na saída;
- ``--revelar`` é o único modo de exibir o valor retornado pelo login.
"""

from __future__ import annotations

import importlib.util
import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

import respx
from cryptography.fernet import Fernet
from httpx import Response
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.vault import cifrar_segredo
from app.db.base import Base
from app.models import Escritorio, JettaxCredencial

_CAMINHO_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "diagnosticar_jettax.py"


def _carregar_script():
    especificacao = importlib.util.spec_from_file_location("diagnosticar_jettax", _CAMINHO_SCRIPT)
    modulo = importlib.util.module_from_spec(especificacao)
    especificacao.loader.exec_module(modulo)
    return modulo


def _banco(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path}/diag_jettax.db",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    sessao = sessionmaker(bind=engine)
    db = sessao()
    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.flush()
    db.add(
        JettaxCredencial(
            escritorio_id=escritorio.id,
            base_url="https://morfeu-api.jettax.com.br",
            token_cifrado=cifrar_segredo("valor-que-o-servidor-nao-conhece"),
        )
    )
    db.commit()
    db.close()
    return sessao


def _executar(modulo, argv: list[str]) -> tuple[int, str]:
    sys.argv = ["diagnosticar_jettax.py", *argv]
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        try:
            codigo = modulo.main()
        except SystemExit as exc:
            codigo = int(exc.code or 0)
    return codigo, buffer.getvalue()


def _rota_cidades(pedido) -> Response:
    autorizacao = pedido.headers.get("authorization", "")
    if autorizacao == "tokentestemorfeu123":
        return Response(200, json={"data": [{"ibgeCode": "3550308"}]})
    if autorizacao.startswith("Bearer "):
        return Response(401, json={"message": "Token inválido."})
    if autorizacao:
        return Response(401, json={"message": "Dados de acesso inválidos."})
    return Response(401, json={"message": "Token inválido."})


@respx.mock
def test_token_recusado_conclui_nao_reconhecido_e_nao_vaza_valor(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("app.db.session.SessionLocal", _banco(tmp_path))
    for host in ["https://morfeu-api.jettax.com.br", "https://morfeu.jettax.com.br"]:
        respx.get(f"{host}/api/nfse/cities").mock(side_effect=_rota_cidades)

    modulo = _carregar_script()
    codigo, saida = _executar(modulo, [])

    assert codigo == 1
    texto = " ".join(saida.split())
    assert "MESMA resposta" in texto  # conclusão: servidor não reconhece o valor
    assert "não existe geração autoatendimento" in texto
    assert "valor-que-o-servidor-nao-conhece" not in saida  # segredo nunca na saída
    assert "sha256" in saida  # identificador seguro do valor guardado


@respx.mock
def test_token_aceito_conclui_ok(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_MASTER_KEY", Fernet.generate_key().decode())
    sessao = _banco(tmp_path)
    monkeypatch.setattr("app.db.session.SessionLocal", sessao)
    for host in ["https://morfeu-api.jettax.com.br", "https://morfeu.jettax.com.br"]:
        respx.get(f"{host}/api/nfse/cities").mock(side_effect=_rota_cidades)
    db = sessao()
    db.query(JettaxCredencial).first().token_cifrado = cifrar_segredo("tokentestemorfeu123")
    db.commit()
    db.close()

    modulo = _carregar_script()
    codigo, saida = _executar(modulo, [])

    assert codigo == 0
    assert "aceito" in saida.lower()
    assert "tokentestemorfeu123" not in saida


@respx.mock
def test_sonda_login_redige_token_e_senha_por_padrao(tmp_path, monkeypatch):
    monkeypatch.setenv("VAULT_MASTER_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr("app.db.session.SessionLocal", _banco(tmp_path))
    token_login = "um-token-bem-longo-devolvido-pelo-login-123456"
    for host in ["https://morfeu-api.jettax.com.br", "https://morfeu.jettax.com.br"]:
        respx.get(f"{host}/api/nfse/cities").mock(side_effect=_rota_cidades)
        respx.post(f"{host}/api/login").mock(return_value=Response(200, json={"token": token_login}))

    modulo = _carregar_script()
    codigo, saida = _executar(modulo, ["--email", "a@b.com", "--senha", "segredo"])
    assert codigo == 1
    assert "ACHADO" in saida
    assert token_login not in saida  # sem --revelar, nada de valor na saída
    assert "segredo" not in saida  # a senha nunca aparece

    _, saida = _executar(modulo, ["--email", "a@b.com", "--senha", "segredo", "--revelar"])
    assert token_login in saida  # com --revelar, o valor aparece para colar no painel
