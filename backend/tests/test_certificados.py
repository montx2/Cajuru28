"""Extração de identidade (CNPJ/razão social) de certificados A1."""

from datetime import datetime, timedelta, timezone

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier

from app.services.certificados import (
    cnpj_de_nome_arquivo,
    extrair_identidade,
    validar_cnpj,
    validar_cpf,
    validar_documento,
)

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
SENHA = "senha-do-certificado-fake"
CNPJ = "12345678000195"
RAZAO = "KR SERVICOS MEDICOS LTDA"


def _der_octet_string(dados: bytes) -> bytes:
    # ICP-Brasil guarda o CNPJ como OCTET STRING DER dentro do OtherName
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx_com_identidade(cnpj: str = CNPJ, nome_cert: str = RAZAO, senha: str = SENHA) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, nome_cert),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{nome_cert}:{cnpj}"),
        ]
    )
    agora = datetime.now(timezone.utc)
    san = x509.SubjectAlternativeName(
        [x509.OtherName(OID_CNPJ, _der_octet_string(cnpj.encode("utf-8")))]
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .add_extension(san, critical=False)
        .sign(chave, hashes.SHA256())
    )
    return pkcs12.serialize_key_and_certificates(
        name=b"empresa-teste",
        key=chave,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(senha.encode()),
    )


def test_extrai_cnpj_e_razao_do_certificado():
    identidade = extrair_identidade(_pfx_com_identidade(), SENHA)
    assert identidade.documento == CNPJ
    # o sufixo ":CNPJ" do commonName é limpo — não vira ruído na razão social
    assert CNPJ not in identidade.razao_social
    assert identidade.razao_social == "KR SERVICOS MEDICOS LTDA"
    assert identidade.validade_utc.tzinfo is not None


def test_senha_errada_levanta_mensagem_clara():
    with pytest.raises(ValueError, match="senha informada"):
        extrair_identidade(_pfx_com_identidade(), "senha-errada")


def test_cnpj_do_nome_do_arquivo():
    assert cnpj_de_nome_arquivo("certificado_12345678000195_mimetais.pfx") == CNPJ
    assert cnpj_de_nome_arquivo("sem-numero.pfx") == ""
    assert cnpj_de_nome_arquivo("nome_com_cpf_52998224725.pfx") == ""


def test_validadores_de_documento():
    assert validar_cnpj("11.222.333/0001-81")
    assert not validar_cnpj("12345678000199")  # dígito verificador errado
    assert validar_cpf("529.982.247-25")
    assert not validar_cpf("111.111.111-11")
    assert validar_documento("11222333000181")


def test_certificado_com_cnpj_alfanumerico_preserva_identidade():
    # CNPJ alfanumérico com DVs válidos pela regra RFB (A=17, B=18 etc.).
    cnpj_alfa = "ABCDEF12345680"
    identidade = extrair_identidade(_pfx_com_identidade(cnpj_alfa), SENHA)
    assert identidade.documento == cnpj_alfa
    assert validar_cnpj(identidade.documento)
    # Barra não é válida em nome de arquivo; pontos/hífens são preservados como máscara.
    assert cnpj_de_nome_arquivo("certificado-AB.CD-EF12345680.pfx") == cnpj_alfa
