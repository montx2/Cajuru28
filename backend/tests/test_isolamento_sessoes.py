"""Testes adversariais para identidade imutável, tenant e cookies de sessão."""

from __future__ import annotations

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.security import criar_token_acesso, gerar_hash_senha
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Empresa, Escritorio, Usuario

SENHA_A = "Senha-tenant-A-123"
SENHA_B = "Senha-tenant-B-123"


@pytest.fixture
def ambiente():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    escritorio_a = Escritorio(nome="Tenant A")
    escritorio_b = Escritorio(nome="Tenant B")
    db.add_all([escritorio_a, escritorio_b])
    db.flush()
    usuario_a = Usuario(
        escritorio_id=escritorio_a.id,
        nome="Alice",
        email="alice@tenant-a.test",
        senha_hash=gerar_hash_senha(SENHA_A),
        ativo=True,
        papel="admin",
    )
    usuario_b = Usuario(
        escritorio_id=escritorio_b.id,
        nome="Bruno",
        email="bruno@tenant-b.test",
        senha_hash=gerar_hash_senha(SENHA_B),
        ativo=True,
        papel="admin",
    )
    empresa_b = Empresa(
        escritorio_id=escritorio_b.id,
        razao_social="Empresa Privada B",
        cnpj_cpf="12345678000195",
        uf="MG",
    )
    db.add_all([usuario_a, usuario_b, empresa_b])
    db.commit()

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app), db, usuario_a, usuario_b, empresa_b
    finally:
        app.dependency_overrides.clear()
        db.close()


def test_cookie_de_tenant_a_nao_enxerga_empresa_de_b(ambiente):
    cliente, _db, _a, _b, empresa_b = ambiente
    assert cliente.post("/auth/login", json={"email": "alice@tenant-a.test", "senha": SENHA_A}).status_code == 200

    empresas = cliente.get("/empresas")
    assert empresas.status_code == 200
    assert empresas.json() == []
    assert cliente.get(f"/empresas/{empresa_b.id}").status_code == 404


def test_jwt_assinado_com_tenant_de_outro_usuario_e_recusado(ambiente):
    cliente, _db, usuario_a, usuario_b, _empresa_b = ambiente
    # Simula um atacante que conhece seu próprio segredo de teste e tenta mudar
    # apenas a claim de tenant. A API carrega o usuário por `sub` e compara os
    # dois valores, não confia na claim isolada.
    token_legitimo = criar_token_acesso(usuario_a.id, usuario_a.escritorio_id, usuario_a.versao_sessao)
    payload = jwt.decode(
        token_legitimo,
        settings.secret_key,
        algorithms=[settings.algorithm],
        options={"verify_signature": False},
    )
    payload["escritorio_id"] = usuario_b.escritorio_id
    token_forjado = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)

    resposta = cliente.get("/auth/me", headers={"Authorization": f"Bearer {token_forjado}"})
    assert resposta.status_code == 401


def test_mesmo_email_legado_em_dois_tenants_nao_escolhe_uma_conta(ambiente):
    cliente, db, _a, usuario_b, _empresa_b = ambiente
    db.add(
        Usuario(
            escritorio_id=usuario_b.escritorio_id,
            nome="Cópia",
            email="alice@tenant-a.test",
            senha_hash=gerar_hash_senha(SENHA_A),
            ativo=True,
            papel="admin",
        )
    )
    db.commit()

    resposta = cliente.post("/auth/login", json={"email": "alice@tenant-a.test", "senha": SENHA_A})
    assert resposta.status_code == 401
    assert "set-cookie" not in resposta.headers
