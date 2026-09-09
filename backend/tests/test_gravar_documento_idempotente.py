from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal
from app.worker.tasks import _gravar_documento


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="KR SERVICOS MEDICOS LTDA",
        cnpj_cpf="12345678000199",
        uf="SP",
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa.id
    sessao.close()


def _doc(chave: str, nsu: str = "1") -> SimpleNamespace:
    return SimpleNamespace(
        chave_acesso=chave,
        nsu=nsu,
        xml=b"<xml/>",
        data_emissao="2026-09-09T14:00:00Z",
        valor_total=10.0,
        direcao="tomada",
    )


def test_mesmo_lote_com_chave_duplicada_nao_quebra(db):
    sessao, empresa_id = db
    chave = "35260112345678000199550010000001231234567890"
    assert _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFSE, _doc(chave, "1"))
    assert not _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFSE, _doc(chave, "2"))
    sessao.commit()
    qtd = sessao.query(DocumentoFiscal).filter(DocumentoFiscal.empresa_id == empresa_id).count()
    assert qtd == 1


def test_reimportar_apos_commit_e_idempotente(db):
    sessao, empresa_id = db
    chave = "35260112345678000199550010000001231234567891"
    assert _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFE, _doc(chave))
    sessao.commit()
    assert not _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFE, _doc(chave, "99"))
    sessao.commit()
    assert sessao.query(DocumentoFiscal).count() == 1
