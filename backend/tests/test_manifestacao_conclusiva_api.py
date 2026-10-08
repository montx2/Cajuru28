"""
`POST /documentos/manifestar-conclusiva` — o caminho da nota que passou de 10 dias.

O sistema registra a Ciência da Operação sozinho, mas ela só é aceita até 10
dias da autorização da NF-e. Depois disso a SEFAZ recusa com cStat 596 e o XML
completo só sai com um evento **conclusivo** — que diz à SEFAZ o que aconteceu
com a operação. Por ser ato de negócio (e irreversível), ele passa pela mão do
operador: este endpoint é a porta, e o que ele valida é o que a SEFAZ cobra.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import DirecaoDocumento, DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal, Usuario

CHAVE = "31260907485646000155550010000602201187626989"


@pytest.fixture
def cliente():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.commit()
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Operador Teste",
        email="operador@teste.local",
        senha_hash="nao-usado",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)
    db.commit()

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    client = TestClient(app)
    yield client, db, escritorio.id
    app.dependency_overrides.clear()
    db.close()


def _empresa(db, escritorio_id, nome="Empresa Teste"):
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social=nome,
        cnpj_cpf=f"{len(db.query(Empresa).all()) + 1:014d}",
        uf="MG",
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


def _resumo(db, empresa, tipo=TipoDocumentoFiscal.NFE, cstat="596"):
    documento = DocumentoFiscal(
        empresa_id=empresa.id,
        tipo=tipo,
        direcao=DirecaoDocumento.TOMADA,
        chave_acesso=CHAVE if tipo == TipoDocumentoFiscal.NFE else "1" * 44,
        nsu="42",
        data_emissao=datetime.now(timezone.utc) - timedelta(days=30),
        valor_total=2261.84,
        xml_path="/tmp/nota.xml",
        leiaute="resumo",
        manifestacao_cstat=cstat,
        manifestacao_erro="Ciência da Operação fora do prazo",
    )
    db.add(documento)
    db.commit()
    db.refresh(documento)
    return documento


@pytest.fixture
def lote(monkeypatch):
    """Intercepta a chamada à SEFAZ: o teste é do contrato da API."""
    from app.worker import tasks

    chamadas = {}

    def falso(db, documentos, *, tipo_evento, justificativa=""):
        chamadas.update(
            {
                "ids": [documento.id for documento in documentos],
                "tipo_evento": tipo_evento,
                "justificativa": justificativa,
            }
        )
        for documento in documentos:
            documento.manifestado_em = datetime.now(timezone.utc)
            documento.manifestacao_erro = None
            documento.manifestacao_cstat = None
        return [
            {
                "documento_id": documento.id,
                "chave_acesso": documento.chave_acesso,
                "ok": True,
                "mensagem": "Evento registrado e vinculado a NF-e",
            }
            for documento in documentos
        ]

    monkeypatch.setattr(tasks, "manifestar_conclusiva_lote", falso)
    return chamadas


def test_confirmacao_da_operacao_registra_o_evento_e_devolve_o_resultado(cliente, lote):
    client, db, escritorio_id = cliente
    documento = _resumo(db, _empresa(db, escritorio_id))

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": "confirmacao"},
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo == [
        {
            "documento_id": documento.id,
            "chave_acesso": CHAVE,
            "ok": True,
            "mensagem": "Evento registrado e vinculado a NF-e",
        }
    ]
    assert lote["tipo_evento"] == "210200"
    assert lote["justificativa"] == ""
    db.refresh(documento)
    assert documento.manifestado_em is not None
    assert documento.manifestacao_cstat is None


@pytest.mark.parametrize(
    ("tipo", "evento"),
    [("desconhecimento", "210220"), ("nao_realizada", "210240")],
)
def test_eventos_que_exigem_justificativa_chegam_com_ela(cliente, lote, tipo, evento):
    client, db, escritorio_id = cliente
    documento = _resumo(db, _empresa(db, escritorio_id))
    justificativa = "Mercadoria devolvida ao emitente no dia 20"

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": tipo, "justificativa": justificativa},
    )

    assert resposta.status_code == 200
    assert lote["tipo_evento"] == evento
    assert lote["justificativa"] == justificativa


def test_justificativa_curta_e_recusada_antes_de_gastar_a_consulta(cliente, lote):
    """A SEFAZ exige 15 caracteres (xJust do leiaute); barrar aqui é mais barato."""
    client, db, escritorio_id = cliente
    documento = _resumo(db, _empresa(db, escritorio_id))

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": "nao_realizada", "justificativa": "curta"},
    )

    assert resposta.status_code == 422
    # A barreira é dupla: o schema (formato do xJust) e o endpoint (xJust
    # obrigatório nos eventos que a SEFAZ exige).
    assert "15" in str(resposta.json()["detail"])
    assert lote == {}, "nada foi enviado à SEFAZ"


def test_tipo_invalido_e_recusado_pelo_schema(cliente, lote):
    client, db, escritorio_id = cliente
    documento = _resumo(db, _empresa(db, escritorio_id))

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": "ciencia"},
    )

    assert resposta.status_code == 422
    assert lote == {}


def test_documento_de_outro_escritorio_nao_e_alcancavel(cliente, lote):
    client, db, escritorio_id = cliente
    outro = Escritorio(nome="Outro Escritório")
    db.add(outro)
    db.commit()
    documento = _resumo(db, _empresa(db, outro.id, "Empresa do outro"))

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": "confirmacao"},
    )

    assert resposta.status_code == 404
    assert lote == {}


def test_selecao_sem_nfe_diz_por_que_nao_faz_nada(cliente, lote):
    """CT-e/NFS-e não têm manifestação do destinatário — silêncio seria pior."""
    client, db, escritorio_id = cliente
    cte = _resumo(db, _empresa(db, escritorio_id), tipo=TipoDocumentoFiscal.CTE, cstat=None)

    resposta = client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [cte.id], "tipo": "confirmacao"},
    )

    assert resposta.status_code == 422
    assert "apenas para NF-e" in resposta.json()["detail"]
    assert lote == {}


def test_a_decisao_fica_na_auditoria(cliente, lote):
    client, db, escritorio_id = cliente
    documento = _resumo(db, _empresa(db, escritorio_id))

    client.post(
        "/documentos/manifestar-conclusiva",
        json={"ids": [documento.id], "tipo": "confirmacao"},
    )

    from app.models import RegistroAuditoria

    registro = (
        db.query(RegistroAuditoria)
        .filter(RegistroAuditoria.acao == "manifestacao_conclusiva")
        .one()
    )
    assert "confirmacao" in registro.detalhe
    assert "1 registrada" in registro.detalhe


def test_lote_vazio_e_recusado(cliente, lote):
    client, db, escritorio_id = cliente
    _resumo(db, _empresa(db, escritorio_id))

    resposta = client.post(
        "/documentos/manifestar-conclusiva", json={"ids": [], "tipo": "confirmacao"}
    )

    assert resposta.status_code == 422
    assert lote == {}
