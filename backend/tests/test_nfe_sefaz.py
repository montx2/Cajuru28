import base64
import gzip

import httpx
import pytest
import respx

from app.services.importadores.nfe_sefaz import ImportadorNFeSEFAZ

URL_HOMOLOGACAO = "https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"


def _cert_key_falsos(tmp_path):
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


def _doc_zip(xml_str: str, nsu: str, schema: str) -> str:
    """Empacota um XML como o SEFAZ empacota: gzip + base64, dentro de docZip."""
    comprimido = gzip.compress(xml_str.encode("utf-8"))
    return base64.b64encode(comprimido).decode()


def _envelope_resposta(cstat: str, x_motivo: str, ult_nsu: str, max_nsu: str, docs_zip_xml: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDistDFeInteresseResult>
        <retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">
          <tpAmb>2</tpAmb>
          <verAplic>SVRS202301021</verAplic>
          <cStat>{cstat}</cStat>
          <xMotivo>{x_motivo}</xMotivo>
          <dhResp>2026-01-01T10:00:00-03:00</dhResp>
          <ultNSU>{ult_nsu}</ultNSU>
          <maxNSU>{max_nsu}</maxNSU>
          {"<loteDistDFeInt>" + docs_zip_xml + "</loteDistDFeInt>" if docs_zip_xml else ""}
        </retDistDFeInt>
      </nfeDistDFeInteresseResult>
    </nfeDistDFeInteresseResponse>
  </soap:Body>
</soap:Envelope>""".encode("utf-8")


@respx.mock
def test_nenhum_documento_localizado_nao_e_erro(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200, content=_envelope_resposta("137", "Nenhum documento localizado", "000000000000000", "000000000000000")
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )

    assert lote.documentos == []
    assert lote.ha_mais_documentos is False


@respx.mock
def test_documento_resumo_e_convertido_corretamente(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)

    res_nfe = """<resNFe xmlns="http://www.portalfiscal.inf.br/nfe">
      <chNFe>35260112345678000199550010000001231234567890</chNFe>
      <CNPJ>99999999000188</CNPJ>
      <xNome>Fornecedor Teste Ltda</xNome>
      <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
      <tpNF>1</tpNF>
      <vNF>1500.75</vNF>
    </resNFe>"""
    doc_zip_xml = f'<docZip NSU="000000000000042" schema="resNFe_v1.01.xsd">{_doc_zip(res_nfe, "42", "resNFe")}</docZip>'

    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta(
                "138", "Documento(s) localizado(s)", "000000000000042", "000000000000042", doc_zip_xml
            ),
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )

    assert len(lote.documentos) == 1
    doc = lote.documentos[0]
    assert doc.chave_acesso == "35260112345678000199550010000001231234567890"
    assert doc.valor_total == 1500.75
    assert doc.direcao == "tomada"  # CNPJ do emitente (99...) difere do CNPJ consultado (12...)
    assert lote.ha_mais_documentos is False  # ultNSU == maxNSU


@respx.mock
def test_direcao_prestada_quando_emitente_e_o_proprio_cnpj_consultado(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    cnpj_consultado = "12345678000199"

    res_nfe = f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe">
      <chNFe>35260112345678000199550010000001231234567890</chNFe>
      <CNPJ>{cnpj_consultado}</CNPJ>
      <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
      <vNF>200.00</vNF>
    </resNFe>"""
    doc_zip_xml = f'<docZip NSU="000000000000042" schema="resNFe_v1.01.xsd">{_doc_zip(res_nfe, "42", "resNFe")}</docZip>'

    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta("138", "Documento(s) localizado(s)", "42", "42", doc_zip_xml),
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj=cnpj_consultado, cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )

    assert lote.documentos[0].direcao == "prestada"


@respx.mock
def test_evento_e_ignorado_mas_nao_quebra_o_lote(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)

    evento_xml = '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento>fake</evento></procEventoNFe>'
    doc_zip_xml = (
        f'<docZip NSU="000000000000010" schema="procEventoNFe_v1.00.xsd">'
        f'{_doc_zip(evento_xml, "10", "procEventoNFe")}</docZip>'
    )

    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope_resposta("138", "Documento(s) localizado(s)", "10", "10", doc_zip_xml),
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
    )

    assert lote.documentos == []  # evento não vira DocumentoBaixado
    assert lote.proximo_nsu == "10"  # mas o checkpoint avança normalmente


def test_uf_invalida_levanta_erro_claro(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    with pytest.raises(ValueError):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="XX"
        )


@respx.mock
def test_cstat_de_erro_levanta_com_mensagem_do_sefaz(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200, content=_envelope_resposta("656", "Rejeicao: Consumo Indevido", "0", "0")
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    with pytest.raises(ConnectionError, match="656"):
        importador.buscar_lote(
            cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0", uf="SP"
        )
