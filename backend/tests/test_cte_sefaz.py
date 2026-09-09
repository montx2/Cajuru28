import base64
import gzip
from pathlib import Path

import httpx
import pytest
import respx

from app.services.importadores.cte_sefaz import ImportadorCTeSEFAZ

URL_HOMOLOGACAO = (
    "https://hom1.cte.fazenda.gov.br/CTeDistribuicaoDFe/CTeDistribuicaoDFe.asmx"
)


def _cert_key_falsos(tmp_path: Path):
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


def _doc_zip(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode()


def _envelope_resposta(cstat: str, x_motivo: str, ult_nsu: str, max_nsu: str, docs_zip_xml: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <cteDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/cte/wsdl/CTeDistribuicaoDFe">
      <cteDistDFeInteresseResult>
        <retDistDFeInt versao="1.00" xmlns="http://www.portalfiscal.inf.br/cte">
          <tpAmb>2</tpAmb>
          <cStat>{cstat}</cStat>
          <xMotivo>{x_motivo}</xMotivo>
          <ultNSU>{ult_nsu}</ultNSU>
          <maxNSU>{max_nsu}</maxNSU>
          {"<loteDistDFeInt>" + docs_zip_xml + "</loteDistDFeInt>" if docs_zip_xml else ""}
        </retDistDFeInt>
      </cteDistDFeInteresseResult>
    </cteDistDFeInteresseResponse>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")


@respx.mock
def test_cte_nenhum_documento_nao_e_erro(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta(
                "137", "Nenhum documento localizado", "000000000000000", "000000000000000"
            ),
        )
    )
    importador = ImportadorCTeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )
    assert lote.documentos == []
    assert lote.ha_mais_documentos is False


@respx.mock
def test_cte_resumo_convertido(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    res_cte = """<resCTe xmlns="http://www.portalfiscal.inf.br/cte">
      <chCTe>35260112345678000199570010000001231234567890</chCTe>
      <CNPJ>99999999000188</CNPJ>
      <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
      <vTPrest>350.25</vTPrest>
    </resCTe>"""
    doc_zip_xml = (
        f'<docZip NSU="000000000000007" schema="resCTe_v1.00.xsd">'
        f"{_doc_zip(res_cte)}</docZip>"
    )
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta(
                "138", "Documento(s) localizado(s)", "000000000000007", "000000000000007", doc_zip_xml
            ),
        )
    )
    importador = ImportadorCTeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )
    assert len(lote.documentos) == 1
    doc = lote.documentos[0]
    assert doc.chave_acesso == "35260112345678000199570010000001231234567890"
    assert doc.valor_total == 350.25
    assert doc.direcao == "tomada"
    assert lote.ha_mais_documentos is False


@respx.mock
def test_cte_evento_ignorado(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    evento = '<procEventoCTe xmlns="http://www.portalfiscal.inf.br/cte"><evento>x</evento></procEventoCTe>'
    doc_zip_xml = (
        f'<docZip NSU="000000000000003" schema="procEventoCTe_v4.00.xsd">'
        f"{_doc_zip(evento)}</docZip>"
    )
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta("138", "ok", "3", "3", doc_zip_xml),
        )
    )
    importador = ImportadorCTeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="PR"
    )
    assert lote.documentos == []
    assert lote.proximo_nsu in ("3", "000000000000003")


def test_cte_uf_invalida(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    importador = ImportadorCTeSEFAZ(ambiente="homologacao")
    with pytest.raises(ValueError):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="XX"
        )
