"""
Login precisa aceitar o e-mail como a pessoa realmente digita.

O cadastro grava sempre minúsculo e sem espaços (bootstrap e UsuarioCriar),
mas a tela de login mandava o texto cru. Resultado: quem digitava
"Admin@NotasFlow.local", deixava um espaço no fim, ou colava a senha do
CREDENCIAIS.txt junto com a quebra de linha, tomava "Email ou senha
incorretos" com a credencial certa.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.security import gerar_hash_senha
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Escritorio, Usuario

SENHA = "SenhaDeTeste123"
EMAIL = "admin@notasflow.local"


@pytest.fixture
def contexto():
    """Cliente HTTP + sessão, com um admin já cadastrado."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.flush()
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Administrador",
        email=EMAIL,
        senha_hash=gerar_hash_senha(SENHA),
        papel="admin",
        ativo=True,
    )
    db.add(usuario)
    db.commit()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    # Sem `with`: o lifespan da app roda criar_tabelas()/bootstrap contra o
    # Postgres real, que não existe no ambiente de teste. O override do
    # get_db já entrega o SQLite em memória para os endpoints.
    yield TestClient(app), db, usuario
    app.dependency_overrides.clear()
    db.close()


@pytest.mark.parametrize(
    "email_digitado",
    [
        EMAIL,
        "Admin@NotasFlow.local",
        "ADMIN@NOTASFLOW.LOCAL",
        "  admin@notasflow.local  ",
        "\tadmin@notasflow.local\n",
    ],
)
def test_login_aceita_variacoes_de_caixa_e_espaco(contexto, email_digitado):
    cliente, _, _ = contexto
    resposta = cliente.post("/auth/login", json={"email": email_digitado, "senha": SENHA})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["access_token"]


def test_login_aceita_senha_colada_com_espacos_nas_pontas(contexto):
    """Copiar do CREDENCIAIS.txt costuma trazer espaço/quebra de linha junto."""
    cliente, _, _ = contexto
    resposta = cliente.post("/auth/login", json={"email": EMAIL, "senha": f"  {SENHA}\n"})
    assert resposta.status_code == 200, resposta.text


def test_login_continua_recusando_senha_errada(contexto):
    """A normalização não pode afrouxar a checagem de senha."""
    cliente, _, _ = contexto
    resposta = cliente.post("/auth/login", json={"email": EMAIL, "senha": "senha-errada"})
    assert resposta.status_code == 401


def test_login_recusa_espaco_no_meio_da_senha(contexto):
    """Só as pontas são aparadas — espaço interno é parte da senha."""
    cliente, _, _ = contexto
    resposta = cliente.post("/auth/login", json={"email": EMAIL, "senha": "Senha De Teste123"})
    assert resposta.status_code == 401


def test_login_recusa_usuario_inativo(contexto):
    cliente, db, usuario = contexto
    usuario.ativo = False
    db.commit()
    resposta = cliente.post("/auth/login", json={"email": EMAIL, "senha": SENHA})
    assert resposta.status_code == 403
