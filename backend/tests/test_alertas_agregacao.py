"""
Agregação dos alertas de janela SEFAZ.

Antes, cada combinação empresa×tipo em janela gerava o próprio alerta
("NFe bloqueada até 14:30 — Empresa X"): dezenas de notificações
vermelhas/âmbar para algo que se resolve sozinho. Agora a espera normal
vira UM item informativo, e só a disputa real (3+ bloqueios seguidos)
pede atenção — também num item só.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routers.alertas import computar_alertas
from app.db.base import Base
from app.models import Empresa, Escritorio, SincronizacaoDFe, TipoDocumentoFiscal


@pytest.fixture
def banco():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.commit()
    db.refresh(escritorio)
    yield db, escritorio.id
    db.close()


def _empresa(db, escritorio_id, razao, n):
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social=razao,
        cnpj_cpf=f"{n:014d}",
        uf="SP",
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


def _janela(db, empresa_id, tipo, seguidos=0):
    db.add(
        SincronizacaoDFe(
            empresa_id=empresa_id,
            tipo=tipo,
            bloqueado_ate=datetime.now(timezone.utc) + timedelta(minutes=40),
            motivo_bloqueio="Consumo indevido (cStat 656)",
            bloqueios_seguidos=seguidos,
            ultima_consulta_em=datetime.now(timezone.utc) - timedelta(hours=1),
        )
    )
    db.commit()


def test_espera_normal_vira_um_item_informativo(banco):
    db, escritorio_id = banco
    alfa = _empresa(db, escritorio_id, "Alfa Ltda", 1)
    beta = _empresa(db, escritorio_id, "Beta Ltda", 2)
    _janela(db, alfa.id, TipoDocumentoFiscal.NFE, seguidos=0)
    _janela(db, alfa.id, TipoDocumentoFiscal.CTE, seguidos=1)
    _janela(db, beta.id, TipoDocumentoFiscal.NFSE, seguidos=2)

    itens = computar_alertas(db, escritorio_id)

    assert not [a for a in itens if a.id.startswith("bloqueio-")]
    agregados = [a for a in itens if a.id == "janela-sefaz"]
    assert len(agregados) == 1
    assert agregados[0].nivel == "info"
    assert "3 combinações" in agregados[0].titulo


def test_disputa_real_vira_uma_atencao_agregada(banco):
    db, escritorio_id = banco
    alfa = _empresa(db, escritorio_id, "Alfa Ltda", 1)
    beta = _empresa(db, escritorio_id, "Beta Ltda", 2)
    _janela(db, alfa.id, TipoDocumentoFiscal.NFE, seguidos=4)
    _janela(db, beta.id, TipoDocumentoFiscal.NFE, seguidos=5)
    _janela(db, beta.id, TipoDocumentoFiscal.CTE, seguidos=0)

    itens = computar_alertas(db, escritorio_id)
    por_id = {a.id: a for a in itens}

    assert por_id["janela-disputa"].nivel == "atencao"
    assert "2 janelas disputadas" in por_id["janela-disputa"].titulo
    assert "Alfa Ltda" in por_id["janela-disputa"].detalhe
    assert "1 combinação" in por_id["janela-sefaz"].titulo


def test_cursor_parado_tambem_agrega(banco):
    db, escritorio_id = banco
    alfa = _empresa(db, escritorio_id, "Alfa Ltda", 1)
    beta = _empresa(db, escritorio_id, "Beta Ltda", 2)
    for empresa in (alfa, beta):
        db.add(
            SincronizacaoDFe(
                empresa_id=empresa.id,
                tipo=TipoDocumentoFiscal.NFE,
                ultimo_nsu="0",
                max_nsu="50",
                ultima_consulta_em=datetime.now(timezone.utc) - timedelta(days=10),
            )
        )
    db.commit()

    itens = computar_alertas(db, escritorio_id)
    por_id = {a.id: a for a in itens}

    assert not [a for a in itens if a.id.startswith("parado-")]
    assert "2 combinações" in por_id["sincronismo-parado"].titulo
