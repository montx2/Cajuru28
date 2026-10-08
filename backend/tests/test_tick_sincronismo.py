from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routers import importacoes
from app.core.config import settings
from app.db.base import Base
from app.models import Escritorio


def test_tick_e_ausente_quando_varredura_automatica_esta_desligada(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório de teste")
    db.add(escritorio)
    db.commit()

    monkeypatch.setattr(settings, "sincronismo_automatico", False)
    desligado = importacoes.resumo_sincronizacao(db, escritorio.id)
    assert desligado.sincronismo_automatico is False
    assert desligado.tick_a_partir_de is None

    monkeypatch.setattr(settings, "sincronismo_automatico", True)
    ligado = importacoes.resumo_sincronizacao(db, escritorio.id)
    assert ligado.sincronismo_automatico is True
    assert ligado.tick_a_partir_de is not None
    assert ligado.tick_a_partir_de > datetime.now(timezone.utc)

    db.close()
