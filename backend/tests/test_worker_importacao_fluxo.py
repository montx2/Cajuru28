"""Fluxo completo do worker de importação (sem Celery/Redis): pfx → mTLS → ADN → banco."""

import base64
import gzip
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import config
from app.core.vault import cifrar_segredo
from app.db.base import Base
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.worker import tasks

SENHA = "senha-do-certificado-fake"
CNPJ = "12345678000199"


def _gerar_pfx() -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CNPJ)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"empresa-teste",
        key=chave,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(SENHA.encode()),
    )


def _xml_nfse() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS35260112345678000199550010000000011234567890">
    <DPS><infDPS>
      <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
      <prest><CNPJ>99999999000188</CNPJ></prest>
      <valores><vLiq>100.50</vLiq></valores>
    </infDPS></DPS>
  </infNFSe>
</NFSe>"""


@respx.mock
def test_worker_importa_nota_do_adn_e_grava_xml(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="KR SERVICOS MEDICOS LTDA",
        cnpj_cpf=CNPJ,
        uf="SP",
    )
    sessao.add(empresa)
    sessao.flush()

    pfx = _gerar_pfx()
    caminho_pfx = tmp_path / "certificado.pfx"
    caminho_pfx.write_bytes(pfx)

    certificado = Certificado(
        empresa_id=empresa.id,
        arquivo_path=str(caminho_pfx),
        senha_cifrada=cifrar_segredo(SENHA),
        validade=datetime.now(timezone.utc) + timedelta(days=365),
        ativo=True,
    )
    sessao.add(certificado)
    sessao.flush()

    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFSE
    )
    sessao.add(execucao)
    sessao.commit()

    # Worker usa SessionLocal global — aponta para o banco de teste
    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=engine))

    item = {
        "NSU": 42,
        "ChaveAcesso": "35260112345678000199550010000000011234567890",
        "ArquivoXml": base64.b64encode(gzip.compress(_xml_nfse().encode())).decode(),
        "TipoDocumento": "NFSE",
    }
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(
            200, json={"LoteDFe": [item], "UltNSU": 42, "MaxNSU": 42}
        )
    )

    tasks.importar_documentos(empresa.id, "nfse", execucao.id)

    sessao.refresh(execucao)
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.documentos_importados == 1
    assert execucao.ultimo_nsu == "42"

    documento = sessao.query(DocumentoFiscal).one()
    assert documento.chave_acesso == "35260112345678000199550010000000011234567890"
    assert (tmp_path / "xml" / str(empresa.id) / "nfse" / f"{documento.chave_acesso}.xml").exists()
    sessao.close()
