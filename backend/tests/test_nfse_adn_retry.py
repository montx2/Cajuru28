import base64
import gzip

import httpx
import pytest
import respx

from app.services.importadores.base import (
    AmbienteIndisponivel,
    ConsumoIndevido,
)
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


def _xml_nfse_fake(cnpj_prestador: str = "99999999000188", valor: str = "100.50") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS35260112345678000199550010000000011234567890">
    <DPS>
      <infDPS>
        <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
        <prest><CNPJ>{cnpj_prestador}</CNPJ></prest>
        <valores><vLiq>{valor}</vLiq></valores>
      </infDPS>
    </DPS>
  </infNFSe>
</NFSe>"""


def _item_lote(nsu: int, chave: str, xml: str) -> dict:
    compactado = base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode()
    return {
        "NSU": nsu,
        "ChaveAcesso": chave,
        "ArquivoXml": compactado,
        "TipoDocumento": "NFSE",
    }


# URL oficial: DFe com D e F maiúsculos (manual ADN + fórum ACBr)
URL_PADRAO = "https://adn.nfse.gov.br/contribuintes/DFe/0"


@respx.mock
def test_429_e_tratado_como_bloqueio_e_nao_retentado(monkeypatch, tmp_path):
    """
    HTTP 429 no ADN é limite de consumo, não instabilidade: a regra oficial é
    esperar ~1h. Retentar dentro da task é o que gera o efeito "loop de
    consumo indevido", então o importador sobe `ConsumoIndevido` (com o NSU
    intacto) e quem decide a próxima tentativa é o governor.
    """
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    rota = respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(429)
    )

    importador = ImportadorNFSeADN()
    with pytest.raises(ConsumoIndevido, match="429") as exc:
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
        )

    assert rota.call_count == 1  # uma chamada, não três
    # Sem header Retry-After: a exceção não fixa duração (cai no cooldown de 1h).
    assert exc.value.bloqueio is None or exc.value.bloqueio.total_seconds() > 0


@respx.mock
def test_429_com_retry_after_em_segundos_define_o_tempo_exato(monkeypatch, tmp_path):
    """O ADN pode mandar `Retry-After` — aí o tempo de bloqueio é o exato dele."""
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "120"})
    )

    importador = ImportadorNFSeADN()
    with pytest.raises(ConsumoIndevido) as exc:
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
        )

    # 120 segundos exatos vieram do servidor — não a estimativa de 1h.
    assert exc.value.bloqueio is not None
    assert exc.value.bloqueio.total_seconds() == 120


def test_ler_retry_after_aceita_segundos_e_data_http():
    from datetime import timedelta

    from app.services.importadores.nfse_adn import _ler_retry_after

    assert _ler_retry_after(None) is None
    assert _ler_retry_after("") is None
    assert _ler_retry_after("lixo") is None
    assert _ler_retry_after("300") == timedelta(seconds=300)
    # teto de segurança: nunca bloqueia mais que 24h por um header maluco
    assert _ler_retry_after("999999") == timedelta(seconds=24 * 3600)


@respx.mock
def test_5xx_retenta_e_vira_ambiente_indisponivel(monkeypatch, tmp_path):
    """Queda de ambiente (5xx) é o oposto: retenta e, se persistir, avisa."""
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    rota = respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(503)
    )

    importador = ImportadorNFSeADN()
    with pytest.raises(AmbienteIndisponivel):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
        )
    assert rota.call_count == 3


@respx.mock
def test_erro_401_nao_retenta(monkeypatch, tmp_path):
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    rota = respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(401)
    )

    importador = ImportadorNFSeADN()
    with pytest.raises(httpx.HTTPStatusError):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
        )

    assert rota.call_count == 1


@respx.mock
def test_404_nenhum_documento_nao_e_erro(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(
            404, json={"StatusProcessamento": "NENHUM_DOCUMENTO_LOCALIZADO"}
        )
    )

    importador = ImportadorNFSeADN()
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )
    assert lote.documentos == []
    assert lote.ha_mais_documentos is False


@respx.mock
def test_converte_documento_e_direcao(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    cnpj = "12345678000199"
    xml = _xml_nfse_fake(cnpj_prestador="99999999000188", valor="250.00")
    item = _item_lote(42, "35260112345678000199550010000000011234567890", xml)

    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(
            200, json={"LoteDFe": [item], "UltNSU": 42, "MaxNSU": 42}
        )
    )

    importador = ImportadorNFSeADN()
    lote = importador.buscar_lote(
        cnpj=cnpj, cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )

    assert len(lote.documentos) == 1
    doc = lote.documentos[0]
    assert doc.nsu == "42"
    assert doc.valor_total == 250.0
    assert doc.direcao == "tomada"  # prestador ≠ cnpj consultado
    assert lote.ha_mais_documentos is False


@respx.mock
def test_url_usa_DFe_maiusculo(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    rota = respx.get(URL_PADRAO).mock(return_value=httpx.Response(200, json={"LoteDFe": []}))

    importador = ImportadorNFSeADN()
    importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )
    assert rota.called
    # confere query params oficiais
    request = rota.calls.last.request
    assert "cnpjConsulta=12345678000199" in str(request.url)
    assert "lote=true" in str(request.url)
