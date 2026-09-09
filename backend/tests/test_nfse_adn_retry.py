import httpx
import pytest
import respx

from app.services.importadores.nfse_adn import ImportadorNFSeADN


def _cert_key_falsos(tmp_path):
    """
    httpx monta o SSLContext a partir de cert/key reais mesmo com o
    transporte mockado pelo respx — então precisa de um par PEM válido
    (não precisa ser confiável, só parseável).
    """
    from datetime import datetime, timedelta, timezone

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "teste")])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=1))
        .sign(chave, hashes.SHA256())
    )

    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


@respx.mock
def test_retenta_em_429_e_depois_funciona(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    rota = respx.get(url__regex=r".*/contribuintes/dfe/0.*").mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(200, json={"LoteDFe": []}),
        ]
    )

    importador = ImportadorNFSeADN()
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )

    assert rota.call_count == 2
    assert lote.documentos == []
    assert lote.ha_mais_documentos is False


@respx.mock
def test_erro_401_nao_retenta(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    rota = respx.get(url__regex=r".*/contribuintes/dfe/0.*").mock(
        return_value=httpx.Response(401)
    )

    importador = ImportadorNFSeADN()
    with pytest.raises(httpx.HTTPStatusError):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
        )

    assert rota.call_count == 1  # 401 não é transitório — não vale insistir
