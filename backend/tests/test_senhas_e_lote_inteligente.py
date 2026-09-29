"""Testes da geração inteligente de senhas e importação de certificados com padrões heurísticos."""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import openpyxl
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import BestAvailableEncryption, pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Certificado, Empresa, Escritorio, Usuario
from app.services.senhas import (
    buscar_senhas_por_nome,
    construir_candidatas_pfx,
    fundir_planilhas_dados,
    gerar_senhas_padrao,
    ler_planilha,
    stems_de_nome_arquivo,
    stems_de_texto,
)

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
CNPJ_1 = "12345678000195"
CNPJ_2 = "11444777000161"
CNPJ_3 = "65375901000103"


def _der_octet_string(dados: bytes) -> bytes:
    return b"\x04" + bytes([len(dados)]) + dados


def _criar_pfx(cnpj: str, razao: str, senha: str) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([
        x509.NameAttribute(x509.NameOID.ORGANIZATION_NAME, razao),
        x509.NameAttribute(x509.NameOID.COMMON_NAME, f"{razao}:{cnpj}"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(1)
        .not_valid_before(datetime.now(timezone.utc) - timedelta(days=1))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(OID_CNPJ, _der_octet_string(cnpj.encode()))]
            ),
            critical=False,
        )
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        b"cert", chave, cert, None, BestAvailableEncryption(senha.encode("utf-8"))
    )


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from app.core import config

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
        nome="Administrador Teste",
        email="admin@teste.local",
        senha_hash="nao-usado-no-teste",
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


def test_extracao_stems_e_variacoes_padrao():
    # Testa CAJURU, APX, ACESSORIA
    stems_cajuru = stems_de_texto("CAJURU CONTABILIDADE LTDA")
    assert "CAJURU" in stems_cajuru

    stems_apx = stems_de_texto("APX SERVICOS ME")
    assert "APX" in stems_apx

    stems_acessoria = stems_de_texto("ACESSORIA CONTABIL EIRELI")
    assert "ACESSORIA" in stems_acessoria
    assert "ASSESSORIA" in stems_acessoria

    # Testa senhas geradas
    senhas_cajuru = gerar_senhas_padrao(stems_cajuru)
    assert "CAJURU2026" in senhas_cajuru
    assert "CAJURU26" in senhas_cajuru
    assert "CAJURU25" in senhas_cajuru
    assert "CAJURU2025" in senhas_cajuru
    assert "CAJURU24" in senhas_cajuru

    senhas_apx = gerar_senhas_padrao(stems_apx)
    assert "APX2026" in senhas_apx
    assert "APX26" in senhas_apx

    senhas_acessoria = gerar_senhas_padrao(stems_acessoria)
    assert "ACESSORIA26" in senhas_acessoria
    assert "ACESSORIA2026" in senhas_acessoria


def test_stems_de_nomes_de_arquivos():
    assert "CAJURU" in stems_de_nome_arquivo("CAJURU_2026.pfx")
    assert "CAJURU" in stems_de_nome_arquivo("12345678000195 - CAJURU CONTABIL.p12")
    assert "APX" in stems_de_nome_arquivo("APX2026.pfx")
    assert "ACESSORIA" in stems_de_nome_arquivo("ACESSORIA26.pfx")


def test_leitura_planilha_excel_xlsx():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Certificados"
    ws.append(["CNPJ", "Razao Social", "Senha", "UF"])
    ws.append(["12.345.678/0001-95", "CAJURU CONTABILIDADE", "CAJURU2026", "SP"])
    ws.append(["11.444.777/0001-61", "APX ASSESSORIA", "APX26", "MG"])

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    conteudo = buf.getvalue()

    resultado = ler_planilha(conteudo, "senhas.xlsx")
    assert CNPJ_1 in resultado
    assert resultado[CNPJ_1]["senha"] == "CAJURU2026"
    assert resultado[CNPJ_1]["uf"] == "SP"
    assert CNPJ_2 in resultado
    assert resultado[CNPJ_2]["senha"] == "APX26"
    assert resultado[CNPJ_2]["uf"] == "MG"


def test_leitura_csv_com_cr_isolado_nao_quebra():
    # Exports antigos (Mac/alguns ERPs) terminam linha só com "\r". Antes isso
    # derrubava a importação em massa com
    # "_csv.Error: new-line character seen in unquoted field".
    conteudo = (
        f"razao_social;cnpj_cpf;uf;senha\r"
        f"CAJURU CONTABILIDADE;{CNPJ_1};SP;CAJURU2026\r"
        f"APX ASSESSORIA;{CNPJ_2};MG;APX26\r"
    ).encode("utf-8")

    resultado = ler_planilha(conteudo, "senhas.csv")
    assert resultado[CNPJ_1]["senha"] == "CAJURU2026"
    assert resultado[CNPJ_1]["uf"] == "SP"
    assert resultado[CNPJ_2]["senha"] == "APX26"


def test_leitura_csv_com_quebras_mistas_lf_crlf_cr():
    conteudo = (
        f"razao_social;cnpj_cpf;uf;senha\r\n"
        f"CAJURU CONTABILIDADE;{CNPJ_1};SP;CAJURU2026\n"
        f"APX ASSESSORIA;{CNPJ_2};MG;APX26\r"
    ).encode("utf-8")

    resultado = ler_planilha(conteudo, "senhas.csv")
    assert resultado[CNPJ_1]["senha"] == "CAJURU2026"
    assert resultado[CNPJ_2]["uf"] == "MG"


def test_leitura_csv_invalido_vira_value_error_com_nome_do_arquivo():
    # Campo acima do limite do módulo csv (128 KiB) — texto corrompido por
    # exportação truncada — deve virar ValueError legível, não exceção _csv.
    conteudo = ("razao_social;cnpj_cpf\r" + "x" * 200000 + ";" + CNPJ_1 + "\r").encode("utf-8")
    with pytest.raises(ValueError, match="senhas-quebrada.csv"):
        ler_planilha(conteudo, "senhas-quebrada.csv")


def test_importar_lote_adivinha_senha_empresa_ano(cliente):
    client, db, escritorio_id = cliente
    cnpj = CNPJ_1
    pfx_bytes = _criar_pfx(cnpj, "CAJURU CONTABILIDADE", "CAJURU2026")

    # Envia o arquivo sem digitar senha e sem planilha
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[
            ("arquivos", ("CAJURU_CONTABILIDADE_12345678000195.pfx", pfx_bytes, "application/octet-stream")),
        ],
    )

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["total"] == 1
    assert dados["criadas"] == 1
    assert dados["erros"] == 0
    assert dados["itens"][0]["status"] == "criada"
    assert dados["itens"][0]["cnpj_cpf"] == cnpj


def test_importar_lote_adivinha_senha_acessoria26(cliente):
    client, db, escritorio_id = cliente
    cnpj = CNPJ_2
    pfx_bytes = _criar_pfx(cnpj, "ACESSORIA FISCAL", "ACESSORIA26")

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[
            ("arquivos", ("ACESSORIA_11444777000161.pfx", pfx_bytes, "application/octet-stream")),
        ],
    )

    assert resposta.status_code == 200
    dados = resposta.json()
    assert dados["total"] == 1
    assert dados["criadas"] == 1
    assert dados["erros"] == 0


def test_enviar_certificado_individual_sem_senha_adivinha(cliente):
    client, db, escritorio_id = cliente
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social="APX TRANSPORTES LTDA",
        cnpj_cpf=CNPJ_2,
        uf="SP",
    )
    db.add(empresa)
    db.commit()

    pfx_bytes = _criar_pfx(CNPJ_2, "APX TRANSPORTES LTDA", "APX2026")

    # Envia com senha vazia
    resposta = client.post(
        "/certificados",
        data={"empresa_id": str(empresa.id), "senha": ""},
        files={"arquivo": ("APX.pfx", pfx_bytes, "application/octet-stream")},
    )

    assert resposta.status_code == 201
    cert = db.query(Certificado).filter(Certificado.empresa_id == empresa.id).first()
    assert cert is not None
    assert cert.ativo is True
