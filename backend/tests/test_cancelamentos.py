"""Cobertura do rastreamento de cancelamento e do bug de "não importa tudo"."""

import base64
import gzip

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import (
    DocumentoFiscal,
    Empresa,
    Escritorio,
    EventoFiscalPendente,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
)
from app.services.importadores.eventos import EventoFiscal, classificar_evento_xml
from app.services.importadores.nfse_adn import ImportadorNFSeADN
from app.worker.tasks import _aplicar_eventos_pendentes, _gravar_documento, _processar_evento

URL_PADRAO = "https://adn.nfse.gov.br/contribuintes/DFe/0"


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


def _xml_nfse_fake(cnpj_prestador: str = "99999999000188") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <infNFSe Id="NFS35260112345678000199550010000000011234567890">
    <DPS>
      <infDPS>
        <dhEmi>2026-01-05T09:00:00-03:00</dhEmi>
        <prest><CNPJ>{cnpj_prestador}</CNPJ></prest>
        <valores><vLiq>100.50</vLiq></valores>
      </infDPS>
    </DPS>
  </infNFSe>
</NFSe>"""


def _xml_cancelamento_nfse(chave: str = "35260112345678000199550010000000011234567890") -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<NFSe xmlns="http://www.sped.fazenda.gov.br/nfse">
  <eventoNFS Id="ID110111{chave}">
    <tpEvento>110111</tpEvento>
    <descEvento>Cancelamento</descEvento>
    <chaveAcesso>{chave}</chaveAcesso>
    <xJust>Cancelado a pedido do contribuinte</xJust>
    <dhEvento>2026-01-10T11:00:00-03:00</dhEvento>
  </eventoNFS>
</NFSe>"""


def _item_lote(nsu: int, xml: str, tipo: str = "NFSE") -> dict:
    return {
        "NSU": nsu,
        "ChaveAcesso": "",
        "ArquivoXml": base64.b64encode(gzip.compress(xml.encode("utf-8"))).decode(),
        "TipoDocumento": tipo,
    }


@pytest.fixture
def db(tmp_path, monkeypatch):
    from app.core import config

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
        cnpj_cpf="12345678000199",
        uf="SP",
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa.id
    sessao.close()


def _doc(chave: str, nsu: str = "1") -> "object":
    from types import SimpleNamespace

    return SimpleNamespace(
        chave_acesso=chave,
        nsu=nsu,
        xml=b"<xml/>",
        data_emissao="2026-09-09T14:00:00Z",
        valor_total=10.0,
        direcao="tomada",
    )


def _evento_cancelamento(chave: str, nsu: str = "5") -> EventoFiscal:
    return EventoFiscal(
        chave_acesso=chave,
        nsu=nsu,
        tipo_evento="cancelamento",
        motivo="Cancelado a pedido do contribuinte",
        data_evento="2026-01-10T11:00:00-03:00",
    )


# ---------- Classificação ----------


def test_classifica_cancelamento_por_tp_evento():
    evento = classificar_evento_xml(_xml_cancelamento_nfse().encode(), tipo_hint="NFSE")
    assert evento is not None
    assert evento.eh_cancelamento
    assert evento.motivo == "Cancelado a pedido do contribuinte"


def test_classifica_close_e_nao_cancelamento():
    xml = b"""<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe">
      <evento><tpEvento>110110</tpEvento><descEvento>Carta de Correcao</descEvento></evento>
    </procEventoNFe>"""
    evento = classificar_evento_xml(xml, schema="procEventoNFe_v1.00.xsd")
    assert evento is not None
    assert not evento.eh_cancelamento
    assert evento.tipo_evento == "nao_reconhecido"


# ---------- Bug do lote cheio (não importa tudo) ----------


@respx.mock
def test_lote_cheio_com_eventos_continua_buscando(tmp_path, monkeypatch):
    """Lote de 50 com 10 cancelamentos NÃO pode encerrar a importação."""
    monkeypatch.setattr("app.services.importadores.nfse_adn.time.sleep", lambda _: None)
    cert_path, key_path = _cert_key_falsos(tmp_path)

    itens = []
    for i in range(10):
        itens.append(_item_lote(i + 1, _xml_cancelamento_nfse(), tipo="NFSE_CANCELAMENTO"))
    for i in range(40):
        itens.append(_item_lote(i + 11, _xml_nfse_fake(), tipo="NFSE"))

    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(200, json={"LoteDFe": itens, "UltNSU": 50, "MaxNSU": 999})
    )

    importador = ImportadorNFSeADN()
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )

    assert len(lote.documentos) == 40  # as notas válidas vieram
    assert len(lote.eventos) == 10  # e os cancelamentos não sumiram
    assert lote.ha_mais_documentos is True  # lote estava cheio → continua
    assert lote.proximo_nsu == "50"


@respx.mock
def test_lote_incompleto_encerra_normalmente(tmp_path):
    cert_path, key_path = _cert_key_falsos(tmp_path)
    itens = [_item_lote(i + 1, _xml_nfse_fake(), tipo="NFSE") for i in range(39)]
    respx.get(url__regex=r".*/contribuintes/DFe/0.*").mock(
        return_value=httpx.Response(200, json={"LoteDFe": itens, "UltNSU": 39, "MaxNSU": 39})
    )

    importador = ImportadorNFSeADN()
    lote = importador.buscar_lote(
        cnpj="12345678000199", cert_path=cert_path, key_path=key_path, ultimo_nsu="0"
    )
    assert len(lote.documentos) == 39
    assert lote.ha_mais_documentos is False


# ---------- Aplicação do cancelamento ----------


def test_cancelamento_depois_da_nota_marca_documento(db):
    sessao, empresa_id = db
    chave = "35260112345678000199550010000001231234567890"
    assert _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFE, _doc(chave))

    resultado = _processar_evento(
        sessao, empresa_id, TipoDocumentoFiscal.NFE, _evento_cancelamento(chave)
    )
    sessao.commit()

    assert resultado == "aplicado"
    documento = sessao.query(DocumentoFiscal).filter_by(chave_acesso=chave).one()
    assert documento.status == StatusDocumentoFiscal.CANCELADA
    assert documento.motivo_cancelamento == "Cancelado a pedido do contribuinte"


def test_cancelamento_antes_da_nota_fica_pendente_e_e_aplicado_depois(db):
    sessao, empresa_id = db
    chave = "35260112345678000199550010000001231234567891"

    resultado = _processar_evento(
        sessao, empresa_id, TipoDocumentoFiscal.NFE, _evento_cancelamento(chave)
    )
    sessao.commit()
    assert resultado == "pendente"
    assert sessao.query(EventoFiscalPendente).count() == 1

    # A nota chega depois: o evento pendente é aplicado automaticamente
    assert _gravar_documento(sessao, empresa_id, TipoDocumentoFiscal.NFE, _doc(chave))
    assert _aplicar_eventos_pendentes(sessao, empresa_id, TipoDocumentoFiscal.NFE, chave)
    sessao.commit()

    documento = sessao.query(DocumentoFiscal).filter_by(chave_acesso=chave).one()
    assert documento.status == StatusDocumentoFiscal.CANCELADA
    pendente = sessao.query(EventoFiscalPendente).one()
    assert pendente.processado is True
    assert pendente.documento_id == documento.id


def test_evento_repetido_nao_duplica_pendente(db):
    sessao, empresa_id = db
    chave = "35260112345678000199550010000001231234567892"
    _processar_evento(sessao, empresa_id, TipoDocumentoFiscal.NFE, _evento_cancelamento(chave))
    sessao.commit()
    assert _processar_evento(
        sessao, empresa_id, TipoDocumentoFiscal.NFE, _evento_cancelamento(chave)
    ) == "duplicado"
    sessao.commit()
    assert sessao.query(EventoFiscalPendente).count() == 1


def test_evento_nao_cancelamento_e_apenas_contabilizado(db):
    sessao, empresa_id = db
    evento = EventoFiscal(nsu="7", tipo_evento="nao_reconhecido", motivo="Carta de Correção")
    assert _processar_evento(sessao, empresa_id, TipoDocumentoFiscal.NFE, evento) == "ignorado"
    assert sessao.query(EventoFiscalPendente).count() == 0
