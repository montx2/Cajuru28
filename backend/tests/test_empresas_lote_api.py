"""Importação em massa de empresas (pfx + CSV) via API."""

import io
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Certificado, Empresa, Escritorio

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
SENHA = "senha-do-certificado-fake"
CNPJ_A = "12345678000195"
CNPJ_B = "11444777000161"


def _der_octet_string(dados: bytes) -> bytes:
    # ICP-Brasil guarda o CNPJ como OCTET STRING DER dentro do OtherName
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx(cnpj: str, razao: str, senha: str = SENHA) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, razao),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{razao}:{cnpj}"),
        ]
    )
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(OID_CNPJ, _der_octet_string(cnpj.encode()))]
            ),
            critical=False,
        )
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"teste",
        key=chave,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(senha.encode()),
    )


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    # TestClient roda a aplicação em outra thread — uma única conexão
    # compartilhada (StaticPool) garante que todas as threads vejam as
    # mesmas tabelas do banco em memória.
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

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    client = TestClient(app)
    yield client, db, escritorio.id

    app.dependency_overrides.clear()
    db.close()


def test_lote_cria_empresas_e_vincula_certificado(cliente, tmp_path):
    client, db, escritorio_id = cliente

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", ("empresa_a_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("arquivos", ("empresa_b_11444777000161.pfx", _pfx(CNPJ_B, "BETA COMERCIO LTDA"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 2
    assert corpo["criadas"] == 2
    assert corpo["erros"] == 0

    empresas = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id).all()
    assert len(empresas) == 2
    assert {e.cnpj_cpf for e in empresas} == {CNPJ_A, CNPJ_B}
    assert all(e.uf == "SP" for e in empresas)
    assert all(e.razao_social for e in empresas)
    # certificado gravado + senha cifrada (nunca texto puro)
    assert db.query(Certificado).count() == 2
    for certificado in db.query(Certificado).all():
        assert SENHA not in certificado.senha_cifrada
        assert (tmp_path / "certificados" / str(certificado.empresa_id)).exists()


def test_lote_senha_errada_reporta_erro_e_continua(cliente):
    client, db, _ = cliente
    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "MG"},
        files=[
            ("arquivos", ("boa_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("arquivos", ("ruim_11444777000161.pfx", _pfx(CNPJ_B, "BETA COMERCIO LTDA", senha="outra-senha"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 1
    assert corpo["erros"] == 1
    erros = [item for item in corpo["itens"] if item["status"] == "erro"]
    assert len(erros) == 1
    assert "senha" in erros[0]["mensagem"].lower()
    assert db.query(Empresa).count() == 1


def test_lote_nao_duplica_empresa_existente_e_atualiza_certificado(cliente):
    client, db, escritorio_id = cliente
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social="ALFA SERVICOS LTDA",
        cnpj_cpf=CNPJ_A,
        uf="SP",
    )
    db.add(empresa)
    db.commit()

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", ("renew_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 0
    assert corpo["certificados"] == 1
    assert db.query(Empresa).count() == 1
    assert db.query(Certificado).filter(
        Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True)
    ).count() == 1


def test_lote_csv_cria_empresa_sem_certificado(cliente):
    client, db, _ = cliente
    csv = bytes(
        "razao_social;cnpj_cpf;uf\nGAMA TRANSPORTES LTDA;11444777000161;PR\n",
        encoding="utf-8",
    )
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[("csv_arquivo", ("empresas.csv", csv, "text/csv"))],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 1
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == "11444777000161").one()
    assert empresa.uf == "PR"
    assert empresa.razao_social == "GAMA TRANSPORTES LTDA"
    assert db.query(Certificado).count() == 0


def test_lote_sem_arquivo_nem_csv_da_erro(cliente):
    client, _, _ = cliente
    resposta = client.post("/empresas/lote", data={"senha": "", "uf_padrao": "SP"})
    assert resposta.status_code == 400
