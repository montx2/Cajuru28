"""
Pente-fino da competência + termômetro de fechamento.

O que nenhum concorrente faz: em vez de só listar as notas capturadas, o
sistema cruza o mês contra o histórico e diz o que falta, o que destoa e
se o mês pode ser fechado — tudo em leitura, sem gastar cota da SEFAZ.
"""

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services.pente_fino import auditar_competencia, termometro

EMITENTE = "11111111000111"
OUTUBRO = date(2026, 10, 1)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    db.add(escritorio)
    db.flush()
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Administrador Teste",
        email="admin@teste.local",
        senha_hash="nao-usado-no-teste",
        papel="admin",
        ativo=True,
    )
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="Empresa Teste Ltda",
        cnpj_cpf="12345678000199",
        uf="SP",
    )
    db.add_all([usuario, empresa])
    db.commit()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    yield {"client": TestClient(app), "db": db, "empresa_id": empresa.id, "escritorio_id": escritorio.id}
    app.dependency_overrides.clear()
    db.close()


_contador_chave = {"n": 0}


def _doc(db, empresa_id, dia, numero, *, mes=10, ano=2026, emitente=EMITENTE,
         nome="Emitente Teste Ltda", serie="1", valor=100.0, hora=10,
         leiaute="completo", cstat=None, tipo=TipoDocumentoFiscal.NFE):
    _contador_chave["n"] += 1
    doc = DocumentoFiscal(
        empresa_id=empresa_id,
        tipo=tipo,
        direcao=DirecaoDocumento.TOMADA,
        chave_acesso=f"99{_contador_chave['n']:042d}"[:44],
        nsu=str(_contador_chave["n"]),
        data_emissao=datetime(ano, mes, dia, hora, 0),
        competencia=date(ano, mes, dia),
        valor_total=valor,
        xml_path="/tmp/inexistente-pente-fino.xml",
        leiaute=leiaute,
        numero=str(numero),
        serie=serie,
        emitente_nome=nome,
        emitente_documento=emitente,
        manifestacao_cstat=cstat,
    )
    db.add(doc)
    return doc


def _codigos(resposta):
    return [achado.codigo for achado in resposta.achados]


def test_salto_sequencia_aponta_notas_faltantes(cliente):
    db = cliente["db"]
    _doc(db, cliente["empresa_id"], 8, 12717)
    _doc(db, cliente["empresa_id"], 9, 12739)
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    saltos = [a for a in resposta.achados if a.codigo == "salto_sequencia"]
    assert len(saltos) == 1
    assert "12718–12738" in saltos[0].titulo
    assert resposta.pronta_para_fechar is False
    sequencia = next(item for item in resposta.checklist if item.codigo == "sequencia_sem_saltos")
    assert sequencia.ok is False


def test_mes_limpo_passa_no_pente_fino(cliente):
    db = cliente["db"]
    _doc(db, cliente["empresa_id"], 20, 99, mes=9)  # histórico: não é estreante
    _doc(db, cliente["empresa_id"], 5, 100)
    _doc(db, cliente["empresa_id"], 12, 101)
    _doc(db, cliente["empresa_id"], 19, 102)
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    assert resposta.total_documentos == 3
    assert resposta.achados == []
    assert resposta.pronta_para_fechar is True


def test_resumo_e_596_viram_achado_com_saida(cliente):
    db = cliente["db"]
    _doc(db, cliente["empresa_id"], 20, 50, mes=9)
    _doc(db, cliente["empresa_id"], 5, 51, leiaute="resumo")
    _doc(db, cliente["empresa_id"], 6, 52, leiaute="resumo", cstat="596")
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    assert "sem_xml" in _codigos(resposta)
    erro_596 = next(a for a in resposta.achados if a.codigo == "erro_596")
    assert erro_596.severidade == "alta"
    assert "conclusiva" in erro_596.detalhe
    xmls = next(item for item in resposta.checklist if item.codigo == "xmls_completos")
    assert xmls.ok is False


def test_valor_anomalo_compara_com_historico_do_emitente(cliente):
    db = cliente["db"]
    for dia in (3, 8, 13, 18, 23, 28):
        _doc(db, cliente["empresa_id"], dia, 200 + dia, mes=9, valor=100.0)
    _doc(db, cliente["empresa_id"], 10, 300, valor=5000.0)
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    anomalos = [a for a in resposta.achados if a.codigo == "valor_anomalo"]
    assert len(anomalos) == 1
    assert "50,0×" in anomalos[0].detalhe


def test_emissao_de_domingo_vira_horario_atipico(cliente):
    db = cliente["db"]
    _doc(db, cliente["empresa_id"], 4, 400)  # 04/10/2026 = domingo
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    atipicos = [a for a in resposta.achados if a.codigo == "horario_atipico"]
    assert len(atipicos) == 1
    assert "domingo" in atipicos[0].titulo


def test_emitente_recorrente_que_some_vira_achado(cliente):
    db = cliente["db"]
    # 3 notas nos 90 dias antes de outubro, nenhuma dentro do mês.
    _doc(db, cliente["empresa_id"], 10, 501, mes=8)
    _doc(db, cliente["empresa_id"], 11, 502, mes=9)
    _doc(db, cliente["empresa_id"], 12, 503, mes=9)
    db.commit()

    resposta = auditar_competencia(db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]])

    sumidos = [a for a in resposta.achados if a.codigo == "emitente_sumido"]
    assert len(sumidos) == 1
    assert "Emitente Teste Ltda" in sumidos[0].titulo
    assert resposta.pronta_para_fechar is False


def test_termometro_projeta_o_mes_pelo_historico(cliente):
    db = cliente["db"]
    volumes = {4: 8, 5: 9, 6: 10, 7: 11, 8: 12, 9: 10}
    for mes, total in volumes.items():
        for i in range(total):
            _doc(db, cliente["empresa_id"], 10, 600 + mes * 100 + i, mes=mes)
    for i in range(5):
        _doc(db, cliente["empresa_id"], 5 + i, 900 + i)
    db.commit()

    resposta = termometro(
        db, cliente["escritorio_id"], OUTUBRO, [cliente["empresa_id"]], hoje=date(2026, 10, 13)
    )

    nfe = next(item for item in resposta.tipos if item.tipo == "nfe")
    assert nfe.capturadas == 5
    assert nfe.esperadas_min == 3  # 8 × 13/31
    assert nfe.esperadas_max == 5  # 12 × 13/31
    assert nfe.percentual == pytest.approx(119.2, abs=0.1)
    assert nfe.estado == "no_ritmo"
    cte = next(item for item in resposta.tipos if item.tipo == "cte")
    assert cte.estado == "sem_historico"


def test_endpoint_pente_fino(cliente):
    db = cliente["db"]
    _doc(db, cliente["empresa_id"], 8, 12717)
    _doc(db, cliente["empresa_id"], 9, 12739)
    db.commit()

    resposta = cliente["client"].get("/documentos/pente-fino", params={"competencia": "10/2026"})

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total_documentos"] == 2
    assert corpo["pronta_para_fechar"] is False
    assert any(a["codigo"] == "salto_sequencia" for a in corpo["achados"])
    assert len(corpo["checklist"]) == 5


def test_endpoint_termometro_competencia_invalida(cliente):
    resposta = cliente["client"].get("/documentos/termometro", params={"competencia": "outubro"})

    assert resposta.status_code == 422
