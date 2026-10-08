"""Guarda contra regressões de autorização em rotas de mutação."""

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, requer_escrita, usuario_atual
from app.api.routers import (
    acessorias,
    alertas,
    auditoria,
    auth,
    certificados,
    dashboard,
    documentos,
    empresas,
    importacoes,
    metricas,
    painel,
    relatorios,
    sistema,
    usuarios,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Escritorio, Usuario


@pytest.fixture
def cliente_com_papel(request):
    papel = request.param
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório de permissões")
    db.add(escritorio)
    db.flush()
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Usuário de teste",
        email=f"{papel}@teste.local",
        senha_hash="não usado",
        papel=papel,
        ativo=True,
    )
    db.add(usuario)
    db.commit()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id
    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
    db.close()
    engine.dispose()


def _dependencias_recursivas(dependant):
    for dependencia in dependant.dependencies:
        yield dependencia.call
        yield from _dependencias_recursivas(dependencia)


def _e_guarda_de_papel(call) -> bool:
    nome = getattr(call, "__qualname__", "")
    return call is requer_escrita or nome.startswith("requer_papel.<locals>.verificar")


def test_todas_as_rotas_de_mutacao_declaram_guarda_ou_excecao_explicita():
    routers = (
        auth.router,
        acessorias.router,
        usuarios.router,
        auditoria.router,
        metricas.router,
        empresas.router,
        certificados.router,
        documentos.router,
        importacoes.router,
        dashboard.router,
        painel.router,
        alertas.router,
        relatorios.router,
        sistema.router,
    )
    # Operações de sessão, consulta via POST e ações explicitamente desativadas
    # não alteram dados de negócio. Manter a lista explícita faz novas rotas
    # falharem aqui até receberem uma classificação e uma guarda adequadas.
    sem_guarda_de_papel = {
        ("POST", "/auth/login"),
        ("POST", "/auth/logout"),
        ("POST", "/auth/renovar"),
        ("POST", "/importacoes/selecionadas/previa"),
        ("POST", "/sistema/atualizacao/verificar"),
        ("POST", "/sistema/iniciar-com-windows"),
        ("POST", "/sistema/encerrar"),
        ("POST", "/sistema/abrir-pasta"),
    }
    sem_guarda_encontradas = set()
    sem_guarda_inesperadas = []

    for router in routers:
        for rota in router.routes:
            metodos = set(rota.methods or ()) & {"POST", "PUT", "PATCH", "DELETE"}
            for metodo in metodos:
                chave = (metodo, rota.path)
                if any(_e_guarda_de_papel(call) for call in _dependencias_recursivas(rota.dependant)):
                    continue
                if chave in sem_guarda_de_papel:
                    sem_guarda_encontradas.add(chave)
                else:
                    sem_guarda_inesperadas.append(chave)

    assert sem_guarda_inesperadas == []
    assert sem_guarda_encontradas == sem_guarda_de_papel


@pytest.mark.parametrize("cliente_com_papel", ["leitura"], indirect=True)
def test_perfil_leitura_e_bloqueado_em_mutacoes_representativas(cliente_com_papel):
    # Empresa é uma escrita permitida ao operador, mas vedada à leitura.
    resposta_empresa = cliente_com_papel.post("/empresas", json={})
    assert resposta_empresa.status_code == 403

    # Ações administrativas permanecem restritas a admin, mesmo quando são
    # atualmente indisponíveis neste modo de instalação.
    resposta_atualizacao = cliente_com_papel.post("/sistema/atualizacao/aplicar")
    assert resposta_atualizacao.status_code == 403

    resposta_usuarios = cliente_com_papel.post("/usuarios", json={})
    assert resposta_usuarios.status_code == 403


@pytest.mark.parametrize("cliente_com_papel", ["operador"], indirect=True)
def test_operador_passar_pela_guarda_de_escrita(cliente_com_papel):
    # O corpo incompleto deve falhar na validação da entrada, não na autorização.
    resposta = cliente_com_papel.post("/empresas", json={})
    assert resposta.status_code == 422


def test_guard_escrita_bloqueia_leitura_sem_bloquear_operador_ou_admin():
    leitura = Usuario(papel="leitura")
    operador = Usuario(papel="operador")
    admin = Usuario(papel="admin")

    with pytest.raises(HTTPException) as erro:
        requer_escrita(leitura)
    assert erro.value.status_code == 403
    assert requer_escrita(operador) is operador
    assert requer_escrita(admin) is admin
