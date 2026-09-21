"""Correções do "só vem o resumo": promoção do XML completo e fila de completar."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal
from app.worker.tasks import _gravar_documento, _pendentes_de_completar, _promover_resumo

NFE = TipoDocumentoFiscal.NFE
CHAVE = "35260812345678000199550010000001231234567890"


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
        escritorio_id=escritorio.id, razao_social="EMPRESA", cnpj_cpf="12345678000199", uf="MG"
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa
    sessao.close()


def _doc(chave=CHAVE, nsu="1", xml=b"<resNFe/>", leiaute="resumo", valor=0.0):
    return SimpleNamespace(
        chave_acesso=chave, nsu=nsu, xml=xml, leiaute=leiaute, valor_total=valor,
        data_emissao="2026-08-20T09:00:00-03:00", direcao="tomada", competencia="2026-08-01",
        numero="123", serie="1", emitente_nome="FORNECEDOR LTDA",
    )


def test_completo_que_chega_depois_substitui_o_resumo(db, tmp_path):
    sessao, empresa = db
    assert _gravar_documento(sessao, empresa.id, NFE, _doc())
    sessao.commit()

    completo = _doc(nsu="9", xml=b"<nfeProc>COMPLETO</nfeProc>", leiaute="completo", valor=99.9)
    # o insert idempotente continua ignorando a chave repetida...
    assert not _gravar_documento(sessao, empresa.id, NFE, completo)
    assert sessao.query(DocumentoFiscal).one().leiaute == "resumo"

    # ...e é a promoção que completa o documento
    assert _promover_resumo(sessao, empresa.id, NFE, completo)
    sessao.commit()
    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo"
    assert documento.valor_total == 99.9
    assert open(documento.xml_path, "rb").read() == b"<nfeProc>COMPLETO</nfeProc>"


def test_promocao_nao_rebaixa_nem_cria_nada(db):
    sessao, empresa = db
    completo = _doc(xml=b"<nfeProc/>", leiaute="completo")
    assert _gravar_documento(sessao, empresa.id, NFE, completo)
    sessao.commit()

    # já completo: nada a promover; resumo tardio não sobrescreve o completo
    assert not _promover_resumo(sessao, empresa.id, NFE, completo)
    assert not _promover_resumo(sessao, empresa.id, NFE, _doc(leiaute="resumo"))
    # chave desconhecida: promoção não cria linha
    assert not _promover_resumo(sessao, empresa.id, NFE, _doc(chave="9" * 44, leiaute="completo"))
    assert sessao.query(DocumentoFiscal).count() == 1


def _resumo_no_banco(sessao, empresa, n, **extra):
    sessao.add(
        DocumentoFiscal(
            empresa_id=empresa.id, tipo=NFE, direcao="tomada", chave_acesso=f"{n:044d}",
            nsu=str(n), data_emissao=datetime(2026, 8, 20, tzinfo=timezone.utc),
            valor_total=0.0, xml_path=f"/tmp/{n}.xml", leiaute="resumo", **extra,
        )
    )


def test_fila_nao_e_bloqueada_por_notas_rejeitadas(db):
    """21 notas mais novas rejeitadas não podem esconder a nota boa mais antiga."""
    sessao, empresa = db
    empresa.manifestar_automaticamente = True
    _resumo_no_banco(sessao, empresa, 1)  # a boa, a mais antiga
    for n in range(2, 23):
        _resumo_no_banco(sessao, empresa, n, manifestacao_erro="cStat=493 rejeitada")
    sessao.commit()

    fila = _pendentes_de_completar(sessao, empresa, 20)
    assert [d.nsu for d in fila] == ["1"]


def test_sem_manifestacao_automatica_so_entram_notas_ja_manifestadas(db):
    sessao, empresa = db
    assert empresa.manifestar_automaticamente is False
    for n in range(1, 25):
        _resumo_no_banco(sessao, empresa, n)  # nunca manifestadas
    _resumo_no_banco(sessao, empresa, 100, manifestado_em=datetime.now(timezone.utc))
    sessao.commit()

    assert [d.nsu for d in _pendentes_de_completar(sessao, empresa, 20)] == ["100"]
