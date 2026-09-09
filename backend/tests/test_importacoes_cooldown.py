from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.routers.importacoes import _fim_do_cooldown
from app.db.base import Base
from app.models import Empresa, Escritorio, ExecucaoImportacao, StatusExecucao, TipoDocumentoFiscal


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()

    empresa = Empresa(
        escritorio_id=escritorio.id, razao_social="Empresa Teste", cnpj_cpf="12345678000199", uf="SP"
    )
    sessao.add(empresa)
    sessao.flush()

    sessao.commit()
    yield sessao, empresa.id
    sessao.close()


def test_sem_execucao_anterior_nao_ha_cooldown(db):
    sessao, empresa_id = db
    assert _fim_do_cooldown(sessao, empresa_id, TipoDocumentoFiscal.NFSE) is None


def test_execucao_que_importou_documentos_nao_gera_cooldown(db):
    sessao, empresa_id = db
    sessao.add(
        ExecucaoImportacao(
            empresa_id=empresa_id,
            tipo=TipoDocumentoFiscal.NFSE,
            status=StatusExecucao.CONCLUIDA,
            documentos_importados=5,
            finalizado_em=datetime.now(timezone.utc),
        )
    )
    sessao.commit()
    assert _fim_do_cooldown(sessao, empresa_id, TipoDocumentoFiscal.NFSE) is None


def test_execucao_recente_sem_novidade_gera_cooldown(db):
    sessao, empresa_id = db
    agora = datetime.now(timezone.utc)
    sessao.add(
        ExecucaoImportacao(
            empresa_id=empresa_id,
            tipo=TipoDocumentoFiscal.NFSE,
            status=StatusExecucao.CONCLUIDA,
            documentos_importados=0,
            finalizado_em=agora - timedelta(minutes=10),
        )
    )
    sessao.commit()

    fim = _fim_do_cooldown(sessao, empresa_id, TipoDocumentoFiscal.NFSE)
    assert fim is not None
    assert fim > agora  # ainda faltam ~50 minutos de cooldown


def test_execucao_sem_novidade_ha_mais_de_1h_nao_gera_cooldown(db):
    sessao, empresa_id = db
    sessao.add(
        ExecucaoImportacao(
            empresa_id=empresa_id,
            tipo=TipoDocumentoFiscal.NFSE,
            status=StatusExecucao.CONCLUIDA,
            documentos_importados=0,
            finalizado_em=datetime.now(timezone.utc) - timedelta(hours=2),
        )
    )
    sessao.commit()
    assert _fim_do_cooldown(sessao, empresa_id, TipoDocumentoFiscal.NFSE) is None


def test_cooldown_e_por_tipo_de_documento(db):
    """NFS-e em cooldown não deve bloquear NFe da mesma empresa."""
    sessao, empresa_id = db
    sessao.add(
        ExecucaoImportacao(
            empresa_id=empresa_id,
            tipo=TipoDocumentoFiscal.NFSE,
            status=StatusExecucao.CONCLUIDA,
            documentos_importados=0,
            finalizado_em=datetime.now(timezone.utc),
        )
    )
    sessao.commit()
    assert _fim_do_cooldown(sessao, empresa_id, TipoDocumentoFiscal.NFE) is None
