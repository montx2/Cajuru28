"""Exclusão de empresa pela API: limpeza de dados, arquivos e isolamento.

Os FKs do SQLite só são aplicados com `PRAGMA foreign_keys=ON` — sem isso o
teste não pegaria a ordem errada dos DELETEs (foi o que quebrava em produção
no PostgreSQL).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    Escritorio,
    EventoFiscalPendente,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    TipoDocumentoFiscal,
    Usuario,
)
from app.procuracoes.modelos import (
    Agente,
    Autorizacao,
    AutorizacaoPermissao,
    CertificadoInventario,
    JobEvento,
    JobProcuracao,
    NotificacaoProcuracao,
)
from app.services import lotes_recebidos


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    # Sem FK ligado, um DELETE fora de ordem passa despercebido.
    event.listens_for(engine, "connect")(
        lambda conexao, _: conexao.execute("PRAGMA foreign_keys=ON")
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    outro_escritorio = Escritorio(nome="Outro Escritório")
    db.add_all([escritorio, outro_escritorio])
    db.flush()

    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Administrador Teste",
        email="admin@teste.local",
        senha_hash="nao-usado-no-teste",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)
    db.flush()

    def _empresa(escritorio_id: int, razao: str, cnpj: str) -> Empresa:
        empresa = Empresa(
            escritorio_id=escritorio_id, razao_social=razao, cnpj_cpf=cnpj, uf="SP"
        )
        db.add(empresa)
        db.flush()
        return empresa

    empresa = _empresa(escritorio.id, "Empresa Alvo", "12345678000195")
    empresa_alheia = _empresa(outro_escritorio.id, "Empresa Do Outro", "11444777000161")

    # Arquivos em disco que precisam sumir junto com a empresa.
    pfx = tmp_path / "alvo.pfx"
    pfx.write_bytes(b"conteudo-cifrado")
    xml = tmp_path / "alvo.xml"
    xml.write_text("<nfe/>", encoding="utf-8")
    pfx_alheio = tmp_path / "alheio.pfx"
    pfx_alheio.write_bytes(b"nao-deve-sumir")

    certificado = Certificado(
        empresa_id=empresa.id,
        arquivo_path=str(pfx),
        senha_cifrada="cifrada",
        validade=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    certificado_alheio = Certificado(
        empresa_id=empresa_alheia.id,
        arquivo_path=str(pfx_alheio),
        senha_cifrada="cifrada",
        validade=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    db.add_all([certificado, certificado_alheio])
    db.flush()

    documento = DocumentoFiscal(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFE,
        direcao=DirecaoDocumento.TOMADA,
        chave_acesso="1" * 44,
        nsu="1",
        data_emissao=datetime(2026, 8, 1, tzinfo=timezone.utc),
        valor_total=10.0,
        xml_path=str(xml),
    )
    db.add(documento)
    db.flush()
    # Proveniência não tem arquivo próprio: o XML é o do documento.
    db.add_all(
        [
            DocumentoFiscalFonte(
                documento_id=documento.id, origem="sefaz", identificador_externo="NSU-1"
            ),
            DocumentoFiscalFonte(
                documento_id=documento.id, origem="adn", identificador_externo="nota-1"
            ),
            EventoFiscalPendente(
                empresa_id=empresa.id,
                tipo=TipoDocumentoFiscal.NFE,
                chave_acesso="1" * 44,
                tipo_evento="cancelamento",
                nsu="2",
            ),
            SincronizacaoDFe(
                empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFE, ultimo_nsu="2"
            ),
        ]
    )
    db.commit()

    # Procurações RFB apontando para a empresa — FKs sem ON DELETE.
    agente = Agente(
        escritorio_id=escritorio.id,
        identificador="estacao-teste",
        nome="Estação de teste",
        segredo_hash="hash",
    )
    db.add(agente)
    db.flush()

    autorizacao = Autorizacao(
        escritorio_id=escritorio.id,
        empresa_id=empresa.id,
        outorgante_documento="12345678000195",
        outorgado_documento="99887766000155",
        situacao="autorizada",
    )
    db.add(autorizacao)
    db.flush()
    db.add(
        AutorizacaoPermissao(
            autorizacao_id=autorizacao.id, codigo="RFB-CAIXA-POSTAL"
        )
    )

    job = JobProcuracao(
        escritorio_id=escritorio.id,
        empresa_id=empresa.id,
        autorizacao_id=autorizacao.id,
        chave_idempotencia="job-alvo",
    )
    db.add(job)
    db.flush()
    db.add(JobEvento(job_id=job.id, tipo="criado", status_novo="pendente"))

    db.add_all(
        [
            CertificadoInventario(
                escritorio_id=escritorio.id,
                agente_id=agente.id,
                empresa_id=empresa.id,
                thumbprint="a" * 64,
            ),
            NotificacaoProcuracao(
                escritorio_id=escritorio.id,
                chave="job_concluido:alvo",
                tipo="job",
                titulo="Job concluído",
                empresa_id=empresa.id,
                job_id=job.id,
            ),
            # Notificação sem `empresa_id`, mas que aponta para um job da
            # empresa — o FK de job_id continua bloqueando o DELETE.
            NotificacaoProcuracao(
                escritorio_id=escritorio.id,
                chave="job_concluido:alvo-sem-empresa",
                tipo="job",
                titulo="Sem empresa",
                empresa_id=None,
                job_id=job.id,
            ),
        ]
    )
    # Dados do outro escritório que não podem ser tocados.
    job_alheio = JobProcuracao(
        escritorio_id=outro_escritorio.id,
        empresa_id=empresa_alheia.id,
        chave_idempotencia="job-alheio",
    )
    db.add(job_alheio)
    db.commit()

    lote = lotes_recebidos.salvar(
        empresa.id, TipoDocumentoFiscal.NFE, "12345678000195", "2", b"<nfe/>"
    )
    lote_alheio = lotes_recebidos.salvar(
        empresa_alheia.id, TipoDocumentoFiscal.NFE, "11444777000161", "2", b"<nfe/>"
    )
    assert lote is not None and lote.exists()
    assert lote_alheio is not None and lote_alheio.exists()

    def _get_db():
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    client = TestClient(app)
    yield {
        "client": client,
        "db": db,
        "empresa": empresa,
        "empresa_alheia": empresa_alheia,
        "job_alheio": job_alheio,
        "pfx": pfx,
        "xml": xml,
        "pfx_alheio": pfx_alheio,
        "lote": lote,
        "lote_alheio": lote_alheio,
    }

    app.dependency_overrides.clear()
    db.close()


def test_excluir_empresa_apaga_dados_e_arquivos(ambiente):
    db, client = ambiente["db"], ambiente["client"]
    empresa_id = ambiente["empresa"].id

    resposta = client.delete(f"/empresas/{empresa_id}")

    assert resposta.status_code == 204
    assert db.get(Empresa, empresa_id) is None
    assert db.query(Certificado).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(DocumentoFiscal).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(DocumentoFiscalFonte).count() == 0
    assert db.query(EventoFiscalPendente).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(SincronizacaoDFe).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(ExecucaoImportacao).filter_by(empresa_id=empresa_id).count() == 0

    # Procurações da empresa (e dependentes com ON DELETE CASCADE).
    assert db.query(Autorizacao).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(AutorizacaoPermissao).count() == 0
    assert db.query(JobProcuracao).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(JobEvento).count() == 0
    assert db.query(CertificadoInventario).filter_by(empresa_id=empresa_id).count() == 0
    assert db.query(NotificacaoProcuracao).count() == 0

    for chave in ("pfx", "xml", "lote"):
        assert not ambiente[chave].exists(), f"{chave} deveria ter sido removido"

    # A empresa do outro escritório continua intacta, com certificado e lote.
    assert db.get(Empresa, ambiente["empresa_alheia"].id) is not None
    assert db.get(JobProcuracao, ambiente["job_alheio"].id) is not None
    assert ambiente["pfx_alheio"].exists()
    assert ambiente["lote_alheio"].exists()


def test_excluir_empresa_bloqueia_com_importacao_em_andamento(ambiente):
    db, client = ambiente["db"], ambiente["client"]
    empresa_id = ambiente["empresa"].id
    db.add(
        ExecucaoImportacao(
            empresa_id=empresa_id,
            tipo=TipoDocumentoFiscal.NFE,
            status=StatusExecucao.EM_ANDAMENTO,
        )
    )
    db.commit()

    resposta = client.delete(f"/empresas/{empresa_id}")

    assert resposta.status_code == 409
    assert "importação em andamento" in resposta.json()["detail"]
    assert db.get(Empresa, empresa_id) is not None
    assert ambiente["pfx"].exists()
    assert ambiente["lote"].exists()


def test_excluir_empresa_de_outro_escritorio_nao_apaga_nada(ambiente):
    db, client = ambiente["db"], ambiente["client"]
    alheia_id = ambiente["empresa_alheia"].id

    resposta = client.delete(f"/empresas/{alheia_id}")

    assert resposta.status_code == 404
    assert db.get(Empresa, alheia_id) is not None
    assert ambiente["pfx_alheio"].exists()
    assert ambiente["lote_alheio"].exists()
