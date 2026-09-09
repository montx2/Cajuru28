import os
from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.services.mtls import obter_validade_certificado, sessao_mtls

SENHA_TESTE = "senha-do-certificado-fake"


@pytest.fixture
def pfx_fake() -> bytes:
    """
    Gera um certificado autoassinado + chave em memória e empacota como
    .pfx — o mesmo princípio do 'modo simulação' do Importarnotas original:
    testa o fluxo real sem depender de um certificado A1 verdadeiro.
    """
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "12345678000199")])
    agora = datetime.now(timezone.utc)

    certificado = (
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
        cert=certificado,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(SENHA_TESTE.encode()),
    )


def test_obter_validade_le_a_data_correta_do_certificado(pfx_fake):
    validade = obter_validade_certificado(pfx_fake, SENHA_TESTE)
    dias_restantes = (validade - datetime.now(timezone.utc)).days
    assert 360 <= dias_restantes <= 366


def test_sessao_mtls_gera_e_depois_remove_os_arquivos_temporarios(pfx_fake):
    caminhos_capturados = {}

    with sessao_mtls(pfx_fake, SENHA_TESTE) as (cert_path, key_path):
        caminhos_capturados["cert"] = cert_path
        caminhos_capturados["key"] = key_path
        assert os.path.exists(cert_path)
        assert os.path.exists(key_path)

    # depois do 'with', nada pode sobrar em disco — nem a pasta temporária
    assert not os.path.exists(caminhos_capturados["cert"])
    assert not os.path.exists(caminhos_capturados["key"])
    assert not os.path.exists(os.path.dirname(caminhos_capturados["cert"]))


def test_sessao_mtls_com_senha_errada_levanta_erro_claro(pfx_fake):
    with pytest.raises(ValueError):
        with sessao_mtls(pfx_fake, "senha-errada"):
            pass
