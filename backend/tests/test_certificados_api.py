"""Envio individual de certificado: senha digitada é validada NA HORA.

O cenário que motivou esta suíte: o operador digitava qualquer senha e o
envio era aceito — o backend caía silenciosamente para padrões de mercado
(EMPRESA2026 etc.) e guardava a senha do padrão, não a digitada. O erro de
digitação só aparecia depois, na captura. Agora: senha digitada que não
abre o .pfx = recusa imediata; o campo vazio mantém os padrões (lote).

Cobre também o "testar agora" do centro de certificados, que valida a senha
guardada sem esperar a próxima janela de importação.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

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

from app.api.deps import escritorio_id_atual, usuario_atual
from app.core.vault import cifrar_segredo, decifrar_segredo
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Certificado, Empresa, Escritorio, Usuario

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
SENHA = "senha-do-certificado-fake"
CNPJ = "12345678000195"


def _der_octet_string(dados: bytes) -> bytes:
    # ICP-Brasil guarda o CNPJ como OCTET STRING DER dentro do OtherName
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx(senha: str = SENHA) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ALFA SERVICOS LTDA"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"ALFA SERVICOS LTDA:{CNPJ}"),
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
                [x509.OtherName(OID_CNPJ, _der_octet_string(CNPJ.encode()))]
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
    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Administrador Teste",
        email="admin@teste.local",
        senha_hash="nao-usado-no-teste",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)
    empresa = Empresa(
        escritorio_id=escritorio.id,
        cnpj_cpf=CNPJ,
        razao_social="ALFA SERVICOS LTDA",
        uf="MG",
    )
    db.add(empresa)
    db.commit()
    db.refresh(empresa)

    def _get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    client = TestClient(app)
    yield client, db, empresa.id

    app.dependency_overrides.clear()
    db.close()


def _enviar(
    client,
    empresa_id: int,
    senha: str,
    senha_real: str = SENHA,
    *,
    nome_arquivo: str = "alfa.pfx",
    conteudo: bytes | None = None,
):
    return client.post(
        "/certificados",
        data={"empresa_id": empresa_id, "senha": senha},
        files={
            "arquivo": (
                nome_arquivo,
                conteudo if conteudo is not None else _pfx(senha_real),
                "application/octet-stream",
            )
        },
    )


@pytest.mark.parametrize("nome_arquivo", ["alfa.pfx", "alfa.p12"])
def test_senha_errada_e_recusada_na_hora(cliente, nome_arquivo):
    client, db, empresa_id = cliente

    resposta = _enviar(client, empresa_id, senha="senha-errada", nome_arquivo=nome_arquivo)

    assert resposta.status_code == 400, resposta.text
    assert "não abre este certificado" in resposta.json()["detail"]
    # Nada foi gravado: nem certificado, nem arquivo no volume.
    assert db.query(Certificado).count() == 0


@pytest.mark.parametrize("nome_arquivo", ["invalido.pfx", "invalido.p12"])
def test_arquivo_pkcs12_invalido_e_recusado_sem_gravar(cliente, nome_arquivo):
    client, db, empresa_id = cliente

    resposta = _enviar(
        client,
        empresa_id,
        senha=SENHA,
        nome_arquivo=nome_arquivo,
        conteudo=b"isso nao e um arquivo PKCS12 valido",
    )

    assert resposta.status_code == 400, resposta.text
    assert "não abre este certificado" in resposta.json()["detail"]
    assert db.query(Certificado).count() == 0


def test_p12_sintetico_valido_e_aceito_com_senha_certa(cliente):
    client, db, empresa_id = cliente

    resposta = _enviar(client, empresa_id, senha=SENHA, nome_arquivo="alfa.p12")

    assert resposta.status_code == 201, resposta.text
    certificado = db.query(Certificado).one()
    assert decifrar_segredo(certificado.senha_cifrada) == SENHA
    bruto = Path(certificado.arquivo_path).read_bytes()
    assert bruto.startswith(b"NOTASFLOW-PFX-FERNET-V1\n")


def test_senha_certa_passa_e_fica_cifrada(cliente):
    client, db, empresa_id = cliente

    resposta = _enviar(client, empresa_id, senha=SENHA)

    assert resposta.status_code == 201, resposta.text
    certificado = db.query(Certificado).one()
    assert decifrar_segredo(certificado.senha_cifrada) == SENHA
    assert SENHA not in certificado.senha_cifrada
    bruto = Path(certificado.arquivo_path).read_bytes()
    assert bruto.startswith(b"NOTASFLOW-PFX-FERNET-V1\n")


def test_campo_de_senha_vazio_mantem_os_padroes(cliente):
    """Lote/planilha: sem senha digitada, os padrões conhecidos continuam."""
    client, db, empresa_id = cliente
    # O primeiro padrão gerado é STEM do nome do arquivo + ano corrente
    # (ex.: alfa.pfx -> ALFA2026) — determinístico, valendo em qualquer ano.
    senha_padrao = f"ALFA{datetime.now(timezone.utc).year}"

    resposta = _enviar(client, empresa_id, senha="", senha_real=senha_padrao)

    assert resposta.status_code == 201, resposta.text
    certificado = db.query(Certificado).one()
    assert decifrar_segredo(certificado.senha_cifrada) == senha_padrao


def test_validar_certificado_abre_com_a_senha_guardada(cliente):
    client, db, empresa_id = cliente
    assert _enviar(client, empresa_id, senha=SENHA).status_code == 201

    resposta = client.post(f"/certificados/empresa/{empresa_id}/validar")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["valido"] is True
    certificado = db.query(Certificado).one()
    assert certificado.ultima_validacao_em is not None
    assert certificado.ultimo_erro is None


def test_validar_certificado_denuncia_senha_guardada_que_nao_abre(cliente):
    client, db, empresa_id = cliente
    assert _enviar(client, empresa_id, senha=SENHA).status_code == 201

    # Simula o mundo real em que a senha guardada deixou de valer: arquivo
    # trocado/corrompido ou senha alterada na renovação.
    certificado = db.query(Certificado).one()
    certificado.senha_cifrada = cifrar_segredo("senha-que-nao-abre-mais")
    db.commit()

    resposta = client.post(f"/certificados/empresa/{empresa_id}/validar")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["valido"] is False
    assert "não abre" in corpo["detalhe"]
    db.refresh(certificado)
    assert certificado.ultimo_erro is not None
    assert certificado.ultimo_erro.startswith("Abertura do .pfx falhou")
    assert certificado.ultima_validacao_em is not None


def test_validar_empresa_sem_certificado_ativo(cliente):
    client, _, empresa_id = cliente

    resposta = client.post(f"/certificados/empresa/{empresa_id}/validar")

    assert resposta.status_code == 404


def test_validar_certificado_ausente_no_disco_nao_culpa_a_senha(cliente, tmp_path):
    """Arquivo ausente ≠ senha errada.

    Volume de dados não montado (ou restauração sem a pasta de certificados)
    deixava a mensagem "a senha guardada não abre este certificado" — mandava o
    operador reenviar o A1 para consertar o que não estava quebrado, e escondia
    a montagem faltando.
    """
    client, db, empresa_id = cliente
    assert _enviar(client, empresa_id, senha=SENHA).status_code == 201
    certificado = db.query(Certificado).one()
    Path(certificado.arquivo_path).unlink()

    resposta = client.post(f"/certificados/empresa/{empresa_id}/validar")

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["valido"] is False
    assert "não está no volume de dados" in corpo["detalhe"]
    assert "senha" not in corpo["detalhe"]
    db.refresh(certificado)
    assert certificado.ultimo_erro is not None
    assert certificado.ultimo_erro.startswith("Arquivo do certificado não encontrado")
