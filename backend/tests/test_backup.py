"""Backups cifrados, completos e verificáveis antes de qualquer restauração."""

from __future__ import annotations

import io
import json
import tarfile
from datetime import datetime, timezone
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
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
    """Banco + árvore fiscal + chave de backup isolados."""
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "backup_dir", "")
    monkeypatch.setattr(config.settings, "backup_s3_bucket", "")
    monkeypatch.setattr(config.settings, "backup_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(config.settings, "backup_previous_encryption_keys", "")

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
            arquivo_path=str(tmp_path / "certificados" / "c.pfx.enc"),
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

    (tmp_path / "xml" / "empresa" / "nfe").mkdir(parents=True)
    (tmp_path / "xml" / "nfe.xml").write_text("<nfe/>")
    (tmp_path / "xml" / "empresa" / "nfe" / "outra.xml").write_text("<nfe id='2'/>")
    (tmp_path / "certificados" / "empresa").mkdir(parents=True)
    (tmp_path / "certificados" / "c.pfx.enc").write_bytes(b"pfx-cifrado")
    (tmp_path / "certificados" / "empresa" / "outro.pfx.enc").write_bytes(b"outro-pfx-cifrado")

    yield db, escritorio, tmp_path
    db.close()


def _manifesto(registro) -> dict:
    """Lê teste apenas após confirmar que o pacote está de fato cifrado."""
    pacote = Path(registro.caminho)
    assert pacote.suffix == ".enc"
    bruto_cifrado = pacote.read_bytes()
    assert b'"contagens"' not in bruto_cifrado
    bruto = Fernet(config.settings.backup_encryption_key.encode()).decrypt(bruto_cifrado)
    with tarfile.open(fileobj=io.BytesIO(bruto), mode="r:gz") as tar:
        return json.loads(tar.extractfile("manifesto.json").read().decode())


def test_backup_gera_unidade_cifrada_completa_e_com_hashes(ambiente):
    db, _escritorio, tmp_path = ambiente

    registro = svc_backup.executar_backup(db, tipo="manual")

    assert registro.status == StatusBackup.OK, registro.erro
    assert registro.erro is None
    assert registro.caminho and registro.caminho.endswith(".tar.gz.enc")
    assert registro.checksum_sha256 and len(registro.checksum_sha256) == 64
    assert registro.objeto_remoto is None
    assert registro.empresas == 1
    assert registro.documentos == 1
    assert registro.arquivos_incluidos == 4
    assert Path(registro.caminho).exists()

    manifesto = _manifesto(registro)
    assert manifesto["versao"] == 2
    assert manifesto["contagens"]["empresas"] == 1
    assert manifesto["contagens"]["documentos_fiscais"] == 1
    assert manifesto["payloads"][0]["path"] == "banco.jsonl.gz"
    assert all(item["sha256"] for item in manifesto["payloads"])
    assert {item["path"] for item in manifesto["objetos"]["xml"]} == {
        "nfe.xml", "empresa/nfe/outra.xml"
    }
    assert {item["path"] for item in manifesto["objetos"]["certificados"]} == {
        "c.pfx.enc", "empresa/outro.pfx.enc"
    }


def test_restauracao_de_verdade_confere_banco_e_objetos(ambiente):
    db, _escritorio, _tmp_path = ambiente
    registro = svc_backup.executar_backup(db, tipo="agendado")
    assert registro.status == StatusBackup.OK

    ok, detalhe = svc_backup.testar_restauracao(db, registro.id)

    assert ok, detalhe
    assert "registros" in detalhe
    assert "objeto" in detalhe
    db.refresh(registro)
    assert registro.restauracao_ok is True
    assert registro.restauracao_testada_em is not None


def test_restauracao_recusa_checksum_externo_adulterado(ambiente):
    db, _escritorio, _tmp_path = ambiente
    registro = svc_backup.executar_backup(db)
    pacote = Path(registro.caminho)
    pacote.write_bytes(pacote.read_bytes() + b"adulterado")

    ok, detalhe = svc_backup.testar_restauracao(db, registro.id)

    assert not ok
    assert "Checksum" in detalhe
    db.refresh(registro)
    assert registro.restauracao_ok is False


def test_chave_anterior_abre_backup_historico_durante_rotacao(ambiente, monkeypatch):
    db, _escritorio, _tmp_path = ambiente
    chave_antiga = config.settings.backup_encryption_key
    registro = svc_backup.executar_backup(db)
    monkeypatch.setattr(config.settings, "backup_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(config.settings, "backup_previous_encryption_keys", chave_antiga)

    ok, detalhe = svc_backup.testar_restauracao(db, registro.id)

    assert ok, detalhe


def test_upload_s3_confirma_tamanho_e_checksum(ambiente, monkeypatch):
    _db, _escritorio, tmp_path = ambiente
    pacote = tmp_path / "pacote.enc"
    pacote.write_bytes(b"pacote-cifrado")
    checksum = svc_backup._sha256(pacote)
    chamadas = []

    class S3Falso:
        def upload_file(self, caminho, bucket, chave, ExtraArgs):
            chamadas.append((caminho, bucket, chave, ExtraArgs))

        def head_object(self, *, Bucket, Key):
            return {"ContentLength": pacote.stat().st_size, "Metadata": {"sha256": checksum}}

    import sys
    import types

    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *_args, **_kwargs: S3Falso()))
    monkeypatch.setattr(config.settings, "backup_s3_bucket", "bucket-privado")
    monkeypatch.setattr(config.settings, "backup_s3_prefix", "clientes/a")
    monkeypatch.setattr(config.settings, "backup_s3_kms_key_id", "alias/backups")

    remoto = svc_backup._enviar_para_s3(pacote, checksum)

    assert remoto == "s3://bucket-privado/clientes/a/pacote.enc"
    assert chamadas[0][1:3] == ("bucket-privado", "clientes/a/pacote.enc")
    assert chamadas[0][3]["Metadata"]["sha256"] == checksum
    assert chamadas[0][3]["ServerSideEncryption"] == "aws:kms"
    assert chamadas[0][3]["SSEKMSKeyId"] == "alias/backups"


def test_backup_com_falha_registra_erro_visivel(ambiente, monkeypatch):
    db, _escritorio, _tmp = ambiente

    def _estourar(*_args, **_kwargs):
        raise OSError("simulando disco cheio")

    monkeypatch.setattr(svc_backup, "_dump_logico", _estourar)
    registro = svc_backup.executar_backup(db, tipo="agendado")

    assert registro.status == StatusBackup.ERRO
    assert "disco cheio" in registro.erro


def test_sem_chave_nunca_gera_backup_em_claro(ambiente, monkeypatch):
    db, _escritorio, tmp_path = ambiente
    monkeypatch.setattr(config.settings, "backup_encryption_key", "")

    registro = svc_backup.executar_backup(db)

    assert registro.status == StatusBackup.ERRO
    assert "BACKUP_ENCRYPTION_KEY" in registro.erro
    assert not list((tmp_path / "backups").glob("backup-*.tar.gz"))


def test_retencao_apaga_pacotes_cifrados_antigos(ambiente, monkeypatch):
    db, _escritorio, tmp_path = ambiente
    monkeypatch.setattr(config.settings, "backup_retencao", 2)

    for _ in range(4):
        registro = svc_backup.executar_backup(db, tipo="agendado")
        assert registro.status == StatusBackup.OK

    pacotes = list((tmp_path / "backups").glob("backup-*.tar.gz.enc"))
    assert len(pacotes) == 2


def test_saude_do_backup(ambiente):
    db, _escritorio, _tmp = ambiente

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
    assert saude["ultimo_teste_ok"] is None


def test_endpoint_lista_backups_e_saude(ambiente):
    db, escritorio, _tmp = ambiente
    usuario = db.query(Usuario).first()
    svc_backup.executar_backup(db, tipo="agendado")

    def _get_db():
        yield db

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
        assert corpo["registros"][0]["checksum_sha256"]

        id_backup = corpo["registros"][0]["id"]
        teste = client.post(f"/sistema/backups/{id_backup}/testar")
        assert teste.status_code == 200
        assert teste.json()["ok"] is True
    finally:
        app.dependency_overrides.clear()
