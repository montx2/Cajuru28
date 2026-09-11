"""Backup real: pacote, espelho, retenção e o teste de restauração."""

import json
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.core import config
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    StatusBackup,
    TipoDocumentoFiscal,
    Usuario,
)
from app.services import backup as svc_backup


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Banco + pasta de dados isolados para o serviço de backup."""
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

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
        nome="Operador",
        email="op@teste.local",
        senha_hash="x",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)

    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="EMPRESA COM XML LTDA",
        cnpj_cpf="12345678000195",
        uf="SP",
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)

    db.add(
        Certificado(
            empresa_id=empresa.id,
            arquivo_path=str(tmp_path / "cert" / "c.pfx"),
            senha_cifrada="cifrada",
            validade=datetime.now(timezone.utc),
            ativo=True,
        )
    )
    db.add(
        DocumentoFiscal(
            empresa_id=empresa.id,
            tipo=TipoDocumentoFiscal.NFE,
            direcao=DirecaoDocumento.TOMADA,
            chave_acesso="c" * 44,
            nsu="1",
            data_emissao=datetime.now(timezone.utc),
            valor_total=42.0,
            xml_path=str(tmp_path / "xml" / "nfe.xml"),
        )
    )
    db.commit()

    # Os arquivos que o espelho deve copiar
    (tmp_path / "xml").mkdir(exist_ok=True)
    (tmp_path / "xml" / "nfe.xml").write_text("<nfe/>")
    (tmp_path / "certificados").mkdir(exist_ok=True)
    (tmp_path / "certificados" / "c.pfx").write_bytes(b"pfx-fake")

    yield db, escritorio, tmp_path
    db.close()


def test_backup_gera_pacote_com_manifesto_e_espelho(ambiente):
    db, _escritorio, tmp_path = ambiente

    registro = svc_backup.executar_backup(db, tipo="manual")

    assert registro.status == StatusBackup.OK, registro.erro
    assert registro.erro is None
    assert registro.caminho and registro.caminho.endswith(".tar.gz")
    assert registro.empresas == 1
    assert registro.documentos == 1
    from pathlib import Path
    assert Path(registro.caminho).exists()

    # Espelho carregou os arquivos vivos
    espelho_xml = tmp_path / "backups" / "espelho-xml" / "nfe.xml"
    espelho_cert = tmp_path / "backups" / "espelho-certificados" / "c.pfx"
    assert espelho_xml.read_text() == "<nfe/>"
    assert espelho_cert.read_bytes() == b"pfx-fake"


def test_restauracao_de_verdade_confere_contagens(ambiente):
    """Extração + recriação de schema + recarga + contagens = restauração provada."""
    import tarfile

    db, _escritorio, tmp_path = ambiente
    registro = svc_backup.executar_backup(db, tipo="agendado")
    assert registro.status == StatusBackup.OK

    ok, detalhe = svc_backup.testar_restauracao(db, registro.id)
    assert ok, detalhe
    assert "registros" in detalhe

    db.refresh(registro)
    assert registro.restauracao_ok is True
    assert registro.restauracao_testada_em is not None

    # O pacote tem manifesto com as contagens das tabelas de negócio
    with tarfile.open(registro.caminho, "r:gz") as tar:
        manifesto = json.loads(tar.extractfile("manifesto.json").read().decode())
    assert manifesto["contagens"]["empresas"] == 1
    assert manifesto["contagens"]["documentos_fiscais"] == 1


def test_backup_com_falha_registra_erro_visivel(ambiente, monkeypatch):
    """Falha de backup vira registro com status=erro — nunca silêncio."""
    db, _escritorio, _tmp = ambiente

    def _estourar(*_args, **_kwargs):
        raise OSError("simulando disco cheio")

    monkeypatch.setattr(svc_backup, "_dump_logico", _estourar)
    registro = svc_backup.executar_backup(db, tipo="agendado")

    assert registro.status == StatusBackup.ERRO
    assert "disco cheio" in registro.erro


def test_retencao_apaga_pacotes_antigos(ambiente, monkeypatch):
    db, _escritorio, tmp_path = ambiente
    monkeypatch.setattr(config.settings, "backup_retencao", 2)

    for _ in range(4):
        registro = svc_backup.executar_backup(db, tipo="agendado")
        assert registro.status == StatusBackup.OK

    pacotes = list((tmp_path / "backups").glob("backup-*.tar.gz"))
    assert len(pacotes) == 2


def test_saude_do_backup(ambiente):
    db, _escritorio, _tmp = ambiente

    # Sem nenhum backup e com dados: atrasado (o operador precisa saber)
    saude = svc_backup.saude_do_backup(db)
    assert saude["ativo"] is True
    assert saude["atrasado"] is True
    assert saude["ultimo_ok_em"] is None

    svc_backup.executar_backup(db, tipo="agendado")
    saude = svc_backup.saude_do_backup(db)
    assert saude["atrasado"] is False
    assert saude["ultimo_ok_em"] is not None
    assert saude["horas_desde_ultimo_ok"] < 1
    assert saude["proximo_previsto_em"] is not None
    assert saude["ultimo_teste_ok"] is None  # ainda não foi testado


def test_endpoint_lista_backups_e_saude(ambiente):
    db, escritorio, _tmp = ambiente
    usuario = db.query(Usuario).first()

    svc_backup.executar_backup(db, tipo="agendado")

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id
    try:
        client = TestClient(app)
        resposta = client.get("/sistema/backups")
        assert resposta.status_code == 200
        corpo = resposta.json()
        assert corpo["saude"]["ativo"] is True
        assert len(corpo["registros"]) == 1
        assert corpo["registros"][0]["status"] == "ok"

        # O teste de restauração pelo endpoint
        id_backup = corpo["registros"][0]["id"]
        teste = client.post(f"/sistema/backups/{id_backup}/testar")
        assert teste.status_code == 200
        assert teste.json()["ok"] is True
    finally:
        app.dependency_overrides.clear()
