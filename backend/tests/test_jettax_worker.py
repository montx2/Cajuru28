from sqlalchemy.orm import sessionmaker
import pytest

from app.core.vault import cifrar_segredo
from app.models import Empresa, JettaxCredencial, JettaxExecucao, DocumentoFiscal
from app.services.jettax import JettaxErro
from app.worker import jettax as worker
from test_importacoes_xml import cliente, CNPJ_EMPRESA
from test_jettax_importacao import cliente_http


class Trava:
    def __init__(self, livre=True): self.livre = livre; self.liberada = False
    def acquire(self, **kw): return self.livre
    def release(self): self.liberada = True


class RedisFake:
    def __init__(self): self.trava = Trava(); self.espera = False
    def exists(self, chave): return self.espera
    def lock(self, *a, **kw): return self.trava
    def setex(self, *a): self.espera = True


@pytest.fixture
def contexto(cliente, monkeypatch):
    _, db, escritorio = cliente
    empresa = db.query(Empresa).filter_by(escritorio_id=escritorio, cnpj_cpf=CNPJ_EMPRESA).one()
    execucao = JettaxExecucao(escritorio_id=escritorio, empresa_id=empresa.id, competencia="08-2026", status="pendente", resultado={})
    db.add_all([execucao, JettaxCredencial(escritorio_id=escritorio, token_cifrado=cifrar_segredo("t"), base_url="https://morfeu.jettax360.com.br")]); db.commit()
    monkeypatch.setattr(worker, "SessionLocal", sessionmaker(bind=db.get_bind()))
    redis = RedisFake()
    monkeypatch.setattr(worker.redis.Redis, "from_url", lambda *a, **kw: redis)
    monkeypatch.setattr("app.services.jettax.time.sleep", lambda _: None)
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    return db, escritorio, execucao.id, redis


def ler(db, id):
    db.expire_all()
    return db.get(JettaxExecucao, id)


def test_worker_importa_e_redelivery_nao_consulta(contexto, monkeypatch):
    db, escritorio, id, redis = contexto
    cliente, http = cliente_http()
    monkeypatch.setattr(worker, "ClienteJettax", lambda *a, **kw: cliente)
    with http:
        worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio)
        assert ler(db, id).status == "concluida"
        assert ler(db, id).resultado["importados"] == 1
        worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio)
    assert db.query(DocumentoFiscal).count() == 1
    assert redis.trava.liberada


def test_worker_erro_isolado_e_sem_expor_excecao(contexto, monkeypatch):
    db, escritorio, id, redis = contexto
    def falhar(*a, **kw): raise RuntimeError("TOKEN_E_URL_PRIVADOS")
    monkeypatch.setattr(worker, "importar_nfse", falhar)
    worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio)
    item = ler(db, id)
    assert item.status == "erro" and item.finalizado_em
    assert "TOKEN_E_URL_PRIVADOS" not in item.mensagem
    assert redis.trava.liberada


def test_429_pausa_escritorio_sem_loop(contexto, monkeypatch):
    db, escritorio, id, redis = contexto
    chamadas = []
    def limite(*a, **kw): chamadas.append(1); raise JettaxErro("Limite Jettax atingido.", 429)
    monkeypatch.setattr(worker, "importar_nfse", limite)
    worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio)
    assert ler(db, id).status == "erro" and redis.espera
    novo = JettaxExecucao(escritorio_id=escritorio, empresa_id=ler(db, id).empresa_id, competencia="09-2026", status="pendente", resultado={})
    db.add(novo); db.commit()
    worker.importar_jettax_nfse.run(execucao_id=novo.id, escritorio_id=escritorio)
    assert ler(db, novo.id).status == "erro"
    assert len(chamadas) == 1


def test_trava_por_escritorio_reagenda_sem_consultar(contexto, monkeypatch):
    db, escritorio, id, redis = contexto
    redis.trava.livre = False
    enviados = []
    monkeypatch.setattr(worker.importar_jettax_nfse, "apply_async", lambda **kw: enviados.append(kw))
    worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio)
    assert ler(db, id).status == "pendente"
    assert enviados[0]["kwargs"] == {"execucao_id": id, "escritorio_id": escritorio}


def test_task_de_outro_tenant_nao_executa(contexto, monkeypatch):
    db, escritorio, id, redis = contexto
    worker.importar_jettax_nfse.run(execucao_id=id, escritorio_id=escritorio + 100)
    assert ler(db, id).status == "pendente"
    assert db.query(DocumentoFiscal).count() == 0
