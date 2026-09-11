"""Painel operacional: a tela que responde 'está tudo funcionando?'."""

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
from app.models import (
    BatimentoSistema,
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    TipoDocumentoFiscal,
    Usuario,
)


@pytest.fixture
def cliente():
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


def _empresa(db, escritorio_id, razao, ativa=True, automatico=True):
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social=razao,
        cnpj_cpf=f"{len(db.query(Empresa).all()) + 1:014d}",
        uf="SP",
        ativa=ativa,
        sincronizar_automaticamente=automatico,
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


def _certificado(db, empresa, dias_para_vencer):
    validade = datetime.now(timezone.utc) + timedelta(days=dias_para_vencer)
    certificado = Certificado(
        empresa_id=empresa.id,
        arquivo_path="/tmp/fake.pfx",
        senha_cifrada="cifrada",
        validade=validade,
        ativo=True,
    )
    db.add(certificado)
    db.commit()
    return certificado


def _execucao(
    db,
    empresa,
    status,
    *,
    tipo=TipoDocumentoFiscal.NFE,
    finalizado=True,
    iniciado=None,
    documentos=0,
    duracao_minutos=2,
):
    agora = datetime.now(timezone.utc)
    execucao = ExecucaoImportacao(
        empresa_id=empresa.id,
        tipo=tipo,
        status=status,
        documentos_importados=documentos,
        iniciado_em=iniciado or (agora - timedelta(minutes=duracao_minutos)),
        finalizado_em=agora if finalizado else None,
    )
    db.add(execucao)
    db.commit()
    db.refresh(execucao)
    return execucao


def test_painel_operacional_retrato_completo(cliente):
    client, db, escritorio_id = cliente

    saudavel = _empresa(db, escritorio_id, "SAUDAVEL LTDA")
    quebrada = _empresa(db, escritorio_id, "QUEBRADA LTDA")
    _empresa(db, escritorio_id, "ARQUIVADA LTDA", ativa=False)

    _certificado(db, saudavel, dias_para_vencer=200)
    _certificado(db, quebrada, dias_para_vencer=-3)  # vencido

    # Uma varredura concluída hoje + uma em andamento (saudável)
    _execucao(db, saudavel, StatusExecucao.CONCLUIDA, documentos=7)
    _execucao(db, saudavel, StatusExecucao.EM_ANDAMENTO, finalizado=False)
    # Erro nas últimas 24h (quebrada)
    _execucao(db, quebrada, StatusExecucao.ERRO, documentos=0)

    # Documento importado hoje
    db.add(
        DocumentoFiscal(
            empresa_id=saudavel.id,
            tipo=TipoDocumentoFiscal.NFE,
            direcao=DirecaoDocumento.TOMADA,
            chave_acesso="c" * 44,
            nsu="1",
            data_emissao=datetime.now(timezone.utc),
            valor_total=100.0,
            xml_path="/tmp/x.xml",
            importado_em=datetime.now(timezone.utc),
        )
    )
    # Estado com próxima consulta no futuro → "aguardando janela"
    db.add(
        SincronizacaoDFe(
            empresa_id=saudavel.id,
            tipo=TipoDocumentoFiscal.NFE,
            ultimo_nsu="10",
            max_nsu="10",
            proxima_consulta_em=datetime.now(timezone.utc) + timedelta(minutes=40),
        )
    )
    db.commit()

    resposta = client.get("/painel/operacional")
    assert resposta.status_code == 200
    corpo = resposta.json()

    # O certificado vencido gera alerta crítico → semáforo vermelho no topo.
    assert corpo["status_geral"] == "critico"
    assert corpo["alertas"]["criticos"] >= 1

    assert corpo["empresas"]["cadastradas"] == 3
    assert corpo["empresas"]["ativas"] == 2
    assert corpo["empresas"]["habilitadas_sincronizacao"] == 2
    assert corpo["empresas"]["sincronizadas_hoje"] == 1
    assert corpo["empresas"]["com_erro_24h"] == 1
    assert corpo["empresas"]["sem_certificado"] == 0
    assert corpo["empresas"]["aguardando_janela"] >= 1

    assert corpo["certificados"]["vencidos"] == 1
    assert corpo["certificados"]["validos"] == 1

    assert corpo["execucoes"]["em_andamento"] == 1
    assert corpo["execucoes"]["erros_24h"] == 1
    assert corpo["execucoes"]["concluidas_hoje"] == 1
    assert corpo["execucoes"]["duracao_media_minutos"] == 2.0

    assert corpo["documentos"]["hoje"] == 1
    assert corpo["documentos"]["total"] == 1

    # Componentes: API e banco sempre presentes; worker/agendador no mínimo informados.
    nomes = {c["nome"] for c in corpo["componentes"]}
    assert {"api", "banco", "fila", "worker", "agendador"} <= nomes

    # Últimas sincronizações trazem o resultado mais recente.
    assert any(u["status"] == "erro" for u in corpo["ultimas_sincronizacoes"])


def test_painel_operacional_tudo_funcionando(cliente, monkeypatch):
    # Neste sandbox não há Redis/Celery rodando (em produção Docker, há):
    # mockamos os pings para exercitar o caminho "tudo saudável".
    from app.services import batimento, backup as svc_backup

    monkeypatch.setattr(batimento, "_ping_redis", lambda: True)
    monkeypatch.setattr(batimento, "_ping_workers", lambda: True)
    monkeypatch.setattr(
        svc_backup,
        "saude_do_backup",
        lambda _db: {"ativo": True, "atrasado": False, "erros_recentes": 0, "horas_desde_ultimo_ok": 0.5},
    )

    client, db, escritorio_id = cliente

    empresa = _empresa(db, escritorio_id, "TRANQUILA LTDA")
    _certificado(db, empresa, dias_para_vencer=200)
    _execucao(db, empresa, StatusExecucao.CONCLUIDA, documentos=3)
    # Agendador deu sinal há pouco tempo → componente saudável
    db.add(
        BatimentoSistema(
            componente="agendador", visto_em=datetime.now(timezone.utc) - timedelta(minutes=1)
        )
    )
    db.commit()

    resposta = client.get("/painel/operacional")
    corpo = resposta.json()

    # Sem críticos e sem componente em erro → semáforo verde com a frase certa.
    assert corpo["status_geral"] == "operando"
    assert "normalmente" in corpo["mensagem"]
    agendador = next(c for c in corpo["componentes"] if c["nome"] == "agendador")
    assert agendador["status"] == "ok"


def test_agendador_parado_vira_problema_visivel(cliente):
    """Batimento velho = beat parado: o operador precisa saber na primeira tela."""
    client, db, _ = cliente
    db.add(
        BatimentoSistema(
            componente="agendador", visto_em=datetime.now(timezone.utc) - timedelta(hours=5)
        )
    )
    db.commit()

    resposta = client.get("/painel/operacional")
    corpo = resposta.json()
    agendador = next(c for c in corpo["componentes"] if c["nome"] == "agendador")
    assert agendador["status"] == "erro"
    assert "sem varredura" in agendador["detalhe"].lower()
    # Componente em erro derruba o semáforo geral
    assert corpo["status_geral"] == "critico"


def test_central_de_execucoes_mostra_o_agora_e_o_proximo(cliente):
    client, db, escritorio_id = cliente

    empresa = _empresa(db, escritorio_id, "ATIVA LTDA")
    _certificado(db, empresa, dias_para_vencer=200)

    rodando = _execucao(db, empresa, StatusExecucao.EM_ANDAMENTO, finalizado=False)
    _execucao(db, empresa, StatusExecucao.CONCLUIDA, documentos=12)
    _execucao(db, empresa, StatusExecucao.ERRO)

    db.add(
        SincronizacaoDFe(
            empresa_id=empresa.id,
            tipo=TipoDocumentoFiscal.CTE,
            ultimo_nsu="5",
            proxima_consulta_em=datetime.now(timezone.utc) + timedelta(hours=1),
        )
    )
    db.commit()

    resposta = client.get("/painel/execucoes")
    assert resposta.status_code == 200
    corpo = resposta.json()

    assert len(corpo["agora"]) == 1
    assert corpo["agora"][0]["execucao_id"] == rodando.id
    assert corpo["agora"][0]["razao_social"] == "ATIVA LTDA"

    # A combinação CTE (sem execução viva) com janela futura aparece em proximas
    assert any(p["tipo"] == "cte" for p in corpo["proximas"])

    assert any(r["status"] == "concluida" for r in corpo["recentes"])
    assert len(corpo["erros"]) == 1


def test_centro_de_certificados_ordenado_por_risco(cliente):
    client, db, escritorio_id = cliente

    saudavel = _empresa(db, escritorio_id, "AAA SAUDAVEL LTDA")
    vencendo = _empresa(db, escritorio_id, "BBB VENCENDO LTDA")
    vencida = _empresa(db, escritorio_id, "CCC VENCIDA LTDA")
    sem_cert = _empresa(db, escritorio_id, "DDD SEM CERT LTDA")

    _certificado(db, saudavel, dias_para_vencer=200)
    _certificado(db, vencendo, dias_para_vencer=12)
    _certificado(db, vencida, dias_para_vencer=-1)

    resposta = client.get("/certificados/painel")
    assert resposta.status_code == 200
    corpo = resposta.json()

    # Ordem de risco: vencida → sem certificado → vencendo → saudável
    razoes = [item["razao_social"] for item in corpo]
    assert razoes == [
        "CCC VENCIDA LTDA",
        "DDD SEM CERT LTDA",
        "BBB VENCENDO LTDA",
        "AAA SAUDAVEL LTDA",
    ]

    vencida_item = corpo[0]
    assert vencida_item["vencido"] is True
    assert vencida_item["dias_para_vencer"] < 0
    assert vencida_item["cnpj_cpf"]
