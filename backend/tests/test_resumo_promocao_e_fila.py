"""Correções do "só vem o resumo": promoção do XML completo e fila de completar."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal
from app.worker.tasks import _gravar_documento, _pendentes_de_completar, _promover_resumo

NFE = TipoDocumentoFiscal.NFE
CHAVE = "35260812345678000199550010000001231234567890"


def _proc_nfe(chave: str = CHAVE) -> bytes:
    """`procNFe` mínimo porém REAL: é a presença de `infNFe` que diz que o XML
    é a nota (e não o resumo). Os testes de promoção dependem disso desde que o
    acervo passou a recusar payload que não seja o documento inteiro."""
    return (
        '<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe"><NFe>'
        f'<infNFe Id="NFe{chave}"><ide><nNF>777</nNF><serie>2</serie>'
        "<dhEmi>2026-08-20T14:30:00-03:00</dhEmi></ide>"
        "<total><ICMSTot><vNF>99.90</vNF></ICMSTot></total></infNFe></NFe>"
        "</nfeProc>"
    ).encode()


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

    completo = _doc(nsu="9", xml=_proc_nfe(), leiaute="completo", valor=99.9)
    # o insert idempotente continua ignorando a chave repetida...
    assert not _gravar_documento(sessao, empresa.id, NFE, completo)
    assert sessao.query(DocumentoFiscal).one().leiaute == "resumo"

    # ...e é a promoção que completa o documento
    assert _promover_resumo(sessao, empresa.id, NFE, completo)
    sessao.commit()
    documento = sessao.query(DocumentoFiscal).one()
    assert documento.leiaute == "completo"
    assert documento.valor_total == 99.9
    assert open(documento.xml_path, "rb").read() == _proc_nfe()


def test_promocao_nao_rebaixa_nem_cria_nada(db):
    sessao, empresa = db
    completo = _doc(xml=_proc_nfe(), leiaute="completo")
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
    assert empresa.manifestar_automaticamente is True
    empresa.manifestar_automaticamente = False
    for n in range(1, 25):
        _resumo_no_banco(sessao, empresa, n)  # nunca manifestadas
    _resumo_no_banco(sessao, empresa, 100, manifestado_em=datetime.now(timezone.utc))
    sessao.commit()

    assert [d.nsu for d in _pendentes_de_completar(sessao, empresa, 20)] == ["100"]


# ---------------------------------------------------------------------------
# A fila de completar: urgência, espaçamento e recusa de payload errado
# ---------------------------------------------------------------------------


def test_fila_prioriza_quem_esta_prestes_a_perder_o_prazo_da_ciencia():
    """A Ciência só vale 10 dias; ordenar por id desc deixava vencer a mais antiga."""
    sessao, empresa = _sessao_com_prazo()
    fila = _pendentes_de_completar(sessao, empresa, 20)
    # A de 40 dias não tem mais Ciência possível (vai para o ramo conclusivo);
    # entre as dentro do prazo, a mais antiga é a mais urgente.
    assert [d.numero for d in fila] == ["antiga", "recente", "antiquíssima"]


def test_fila_espaca_tentativa_repetida_da_mesma_nota():
    """20 consultas/h por CNPJ: repetir a mesma nota gastava a cota das novas."""
    sessao, empresa = _sessao_com_prazo()
    antiga = (
        sessao.query(DocumentoFiscal)
        .filter(DocumentoFiscal.chave_acesso == f"{1:044d}")
        .one()
    )
    antiga.tentativas_completar = 3
    antiga.ultima_tentativa_completar_em = datetime.now(timezone.utc) - timedelta(minutes=30)
    sessao.commit()

    fila = _pendentes_de_completar(sessao, empresa, 20)
    assert all(d.chave_acesso != antiga.chave_acesso for d in fila)

    # Passado o intervalo (3 tentativas ⇒ 4 horas), ela volta para a fila.
    antiga.ultima_tentativa_completar_em = datetime.now(timezone.utc) - timedelta(hours=5)
    sessao.commit()
    assert antiga.chave_acesso in {d.chave_acesso for d in _pendentes_de_completar(sessao, empresa, 20)}


def _sessao_com_prazo():
    from app.core import config  # noqa: F401 — o monkeypatch do fixture já aponta dados_dir

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id, razao_social="EMPRESA", cnpj_cpf="12345678000199", uf="MG"
    )
    empresa.manifestar_automaticamente = True
    sessao.add(empresa)
    sessao.flush()

    agora = datetime.now(timezone.utc)
    for indice, (dias, numero) in enumerate(
        [(1, "recente"), (9, "antiga"), (40, "antiquíssima")], start=1
    ):
        sessao.add(
            DocumentoFiscal(
                empresa_id=empresa.id,
                tipo=NFE,
                direcao="tomada",
                chave_acesso=f"{indice:044d}",
                nsu=str(indice),
                data_emissao=agora - timedelta(days=dias),
                valor_total=0.0,
                xml_path=f"/tmp/{indice}.xml",
                leiaute="resumo",
                numero=numero,
            )
        )
    sessao.commit()
    return sessao, empresa
