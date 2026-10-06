"""A nota baixada tem que ser a NOTA — não o resumo nem a autorização.

O sintoma que originou esta bateria: o sistema "baixava" o XML e o arquivo que
chegava às mãos do contador era o `resNFe` (chave, emitente, valor e protocolo —
nada de item, imposto ou total). Pior: a nota era marcada como `leiaute =
"completo"` e saía da fila de complemento, então nunca mais era buscada.

Causa: o Ambiente Nacional só libera a NF-e inteira para o destinatário depois
da manifestação. Sem ela, tanto a distribuição por NSU quanto o `consChNFe`
devolvem apenas o resumo. O código antigo pegava o primeiro `docZip` que
"convertia" — e o resumo converte — e gravava por cima da nota.

As garantias que estes testes travam:

1. classificamos o CONTEÚDO (não o nome do schema);
2. `buscar_por_chave`/`buscar_por_nsu` só devolvem a nota inteira;
3. `_sobrescrever_xml` recusa payload que não seja a nota (última linha);
4. o cadastro que diz "completo" com resumo no disco é corrigido;
5. o relatório de exportação não mente sobre qual XML está no pacote.
"""

import base64
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import pytest
import respx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.models import DocumentoFiscal, Empresa, Escritorio, TipoDocumentoFiscal
from app.services import xml_integridade
from app.services.importadores._distribuicao_dfe import (
    LEIAUTE_COMPLETO,
    LEIAUTE_EVENTO,
    LEIAUTE_PROTOCOLO,
    LEIAUTE_RESUMO,
    classificar_documento_dfe,
)
from app.services.importadores.base import DocumentoBaixado
from app.services.importadores.nfe_sefaz import ImportadorNFeSEFAZ
from app.services.importadores.xml_manual import classificar_xml
from app.worker.tasks import _sobrescrever_xml

URL_HOMOLOGACAO = "https://hom.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
NFE = TipoDocumentoFiscal.NFE
CHAVE = "31260907485646000155550010000602201187626989"
CNPJ_CONSULTADO = "12345678000199"

# Exatamente o XML que o usuário anexou ao relatar o problema.
RES_NFE_MADEIREIRA = f"""<resNFe xmlns="http://www.portalfiscal.inf.br/nfe" versao="1.01">
  <chNFe>{CHAVE}</chNFe>
  <CNPJ>07485646000155</CNPJ>
  <xNome>MADEIREIRA NORTE SUL LTDA</xNome>
  <IE>2234284940008</IE>
  <dhEmi>2026-09-15T00:00:00-03:00</dhEmi>
  <tpNF>1</tpNF>
  <vNF>2261.84</vNF>
  <digVal>GOp8HewYNCyDVWk7SilxUrq6JZY=</digVal>
  <dhRecbto>2026-09-15T15:08:10-03:00</dhRecbto>
  <nProt>131267911602091</nProt>
  <cSitNFe>1</cSitNFe>
</resNFe>"""


def _proc_nfe(chave: str = CHAVE) -> str:
    return f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe><infNFe Id="NFe{chave}" versao="4.00">
    <ide><cUF>31</cUF><nNF>6022</nNF><serie>1</serie><dhEmi>2026-09-15T00:00:00-03:00</dhEmi>
      <natOp>VENDA</natOp></ide>
    <emit><CNPJ>07485646000155</CNPJ><xNome>MADEIREIRA NORTE SUL LTDA</xNome></emit>
    <dest><CNPJ>{CNPJ_CONSULTADO}</CNPJ><xNome>EMPRESA CLIENTE</xNome></dest>
    <total><ICMSTot><vNF>2261.84</vNF></ICMSTot></total>
  </infNFe></NFe>
  <protNFe versao="4.00"><infProt><chNFe>{chave}</chNFe><cStat>100</cStat>
    <dhRecbto>2026-09-15T15:08:10-03:00</dhRecbto>
    <nProt>131267911602091</nProt></infProt></protNFe>
</nfeProc>"""


# ---------------------------------------------------------------------------
# 1. O classificador decide pelo conteúdo
# ---------------------------------------------------------------------------


def test_classifica_resumo_protocolo_evento_e_nota():
    assert classificar_documento_dfe(RES_NFE_MADEIREIRA.encode(), "resNFe_v1.01.xsd") == LEIAUTE_RESUMO
    assert classificar_documento_dfe(_proc_nfe().encode(), "procNFe_v4.00.xsd") == LEIAUTE_COMPLETO

    prot = f'<protNFe xmlns="http://www.portalfiscal.inf.br/nfe"><infProt><chNFe>{CHAVE}</chNFe></infProt></protNFe>'
    assert classificar_documento_dfe(prot.encode(), "protNFe_v4.00.xsd") == LEIAUTE_PROTOCOLO

    evento = (
        '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento>'
        f"<infEvento><chNFe>{CHAVE}</chNFe></infEvento></evento></procEventoNFe>"
    )
    assert classificar_documento_dfe(evento.encode(), "procEventoNFe_v1.00.xsd") == LEIAUTE_EVENTO


def test_protocolo_e_evento_nunca_viram_leiaute_completo():
    """`protNFe` é a autorização, não a nota: gravar como completo some com a fila."""
    from app.services.importadores._distribuicao_dfe import leiaute_do_conteudo

    prot = f'<protNFe xmlns="http://www.portalfiscal.inf.br/nfe"><infProt><chNFe>{CHAVE}</chNFe></infProt></protNFe>'
    assert leiaute_do_conteudo(prot.encode(), "protNFe_v4.00.xsd") == "resumo"
    evento = (
        '<procEventoNFe xmlns="http://www.portalfiscal.inf.br/nfe"><evento>'
        f"<infEvento><chNFe>{CHAVE}</chNFe></infEvento></evento></procEventoNFe>"
    )
    assert leiaute_do_conteudo(evento.encode(), "procEventoNFe_v1.00.xsd") == "resumo"
    assert leiaute_do_conteudo(RES_NFE_MADEIREIRA.encode(), "resNFe_v1.01.xsd") == "resumo"
    assert leiaute_do_conteudo(_proc_nfe().encode(), "procNFe_v4.00.xsd") == "completo"


def test_schema_mentiroso_nao_engana_o_classificador():
    """Já vimos portal entregar resumo com schema de nota. O conteúdo manda."""
    assert classificar_documento_dfe(RES_NFE_MADEIREIRA.encode(), "procNFe_v4.00.xsd") == LEIAUTE_RESUMO


def test_importacao_manual_reconhece_resumo_como_resumo():
    assert classificar_xml(RES_NFE_MADEIREIRA.encode()) == "nfe_resumo"
    assert classificar_xml(_proc_nfe().encode()) == "nfe"
    assert classificar_xml(b"<protNFe/>") == "nfe_autorizacao"


# ---------------------------------------------------------------------------
# 2. consChNFe: só a nota inteira
# ---------------------------------------------------------------------------


def _cert_key_falsos(tmp_path):
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


def _doc_zip(xml_str: str, nsu: str = "1") -> str:
    return base64.b64encode(gzip.compress(xml_str.encode("utf-8"))).decode()


def _envelope(cstat: str, docs: list[tuple[str, str]] = None) -> bytes:
    """`retDistDFeInt` com os docZip (schema, xml) informados."""
    docs = docs or []
    itens = "".join(
        f'<docZip NSU="{i + 1:015d}" schema="{schema}">{_doc_zip(xml, str(i + 1))}</docZip>'
        for i, (schema, xml) in enumerate(docs)
    )
    lote = f"<loteDistDFeInt>{itens}</loteDistDFeInt>" if itens else ""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope"><soap:Body>
<nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
<nfeDistDFeInteresseResult>
<retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">
<tpAmb>2</tpAmb><verAplic>AN</verAplic><cStat>{cstat}</cStat>
<xMotivo>Documento(s) localizado(s)</xMotivo><dhResp>2026-10-01T10:00:00-03:00</dhResp>
<ultNSU>1</ultNSU><maxNSU>1</maxNSU>{lote}</retDistDFeInt>
</nfeDistDFeInteresseResult></nfeDistDFeInteresseResponse></soap:Body></soap:Envelope>""".encode()


@respx.mock
def test_consulta_por_chave_de_nota_nao_manifestada_devolve_nada(tmp_path):
    """Sem manifestação a SEFAZ devolve o resumo — e resumo não é a nota.

    Devolver esse XML aqui era o bug: ele sobrescrevia o arquivo da nota e o
    registro era marcado como completo, saindo da fila para sempre.
    """
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200, content=_envelope("138", [("resNFe_v1.01.xsd", RES_NFE_MADEIREIRA)])
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    assert (
        importador.buscar_por_chave(
            cnpj=CNPJ_CONSULTADO, cert_path=cert_path, key_path=key_path, chave_acesso=CHAVE, uf="MG"
        )
        is None
    )


@respx.mock
def test_consulta_por_chave_prefere_a_nota_quando_vem_resumo_junto(tmp_path):
    """O ambiente pode devolver resumo + nota: quem vale é a nota."""
    cert_path, key_path = _cert_key_falsos(tmp_path)
    respx.post(URL_HOMOLOGACAO).mock(
        return_value=httpx.Response(
            200,
            content=_envelope(
                "138",
                [
                    ("resNFe_v1.01.xsd", RES_NFE_MADEIREIRA),
                    ("procNFe_v4.00.xsd", _proc_nfe()),
                ],
            ),
        )
    )

    importador = ImportadorNFeSEFAZ(ambiente="homologacao")
    documento = importador.buscar_por_chave(
        cnpj=CNPJ_CONSULTADO, cert_path=cert_path, key_path=key_path, chave_acesso=CHAVE, uf="MG"
    )
    assert documento is not None
    assert documento.leiaute == "completo"
    assert b"infNFe" in documento.xml


# ---------------------------------------------------------------------------
# 3. Última linha de defesa: não sobrescrever a nota com resumo
# ---------------------------------------------------------------------------


def test_sobrescrever_recusa_payload_que_nao_e_a_nota(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    arquivo = tmp_path / "nota.xml"
    arquivo.write_bytes(b"")

    documento = SimpleNamespace(
        chave_acesso=CHAVE,
        xml_path=str(arquivo),
        leiaute="resumo",
        manifestacao_erro=None,
        manifestacao_cstat=None,
        tentativas_completar=3,
        ultima_tentativa_completar_em=None,
        valor_total=0.0,
        data_emissao=None,
        competencia=None,
        numero=None,
        serie=None,
        emitente_nome=None,
        emitente_documento=None,
        destinatario_documento=None,
        destinatario_nome=None,
        situacao=None,
    )
    resumo = DocumentoBaixado(
        chave_acesso=CHAVE,
        nsu="1",
        xml=RES_NFE_MADEIREIRA.encode(),
        # Rotulado como completo de propósito: é o cenário do bug.
        leiaute="completo",
        valor_total=2261.84,
        data_emissao="2026-09-15T00:00:00-03:00",
        direcao="tomada",
        competencia="2026-09-01",
    )
    assert _sobrescrever_xml(documento, resumo) is False
    assert documento.leiaute == "resumo"  # continua na fila
    assert arquivo.read_bytes() == b""  # e o arquivo não foi tocado

    nota = DocumentoBaixado(
        chave_acesso=CHAVE,
        nsu="9",
        xml=_proc_nfe().encode(),
        leiaute="completo",
        valor_total=2261.84,
        data_emissao="2026-09-15T00:00:00-03:00",
        direcao="tomada",
        competencia="2026-09-01",
        numero="6022",
        serie="1",
    )
    assert _sobrescrever_xml(documento, nota) is True
    assert documento.leiaute == "completo"
    assert b"infNFe" in arquivo.read_bytes()


# ---------------------------------------------------------------------------
# 4. Reparo do acervo já corrompido
# ---------------------------------------------------------------------------


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
        escritorio_id=escritorio.id, razao_social="EMPRESA", cnpj_cpf=CNPJ_CONSULTADO, uf="MG"
    )
    sessao.add(empresa)
    sessao.commit()
    yield sessao, empresa
    sessao.close()


def _documento(empresa, *, chave, caminho, leiaute="completo"):
    return DocumentoFiscal(
        empresa_id=empresa.id,
        tipo=NFE,
        direcao="tomada",
        chave_acesso=chave,
        nsu="1",
        data_emissao=datetime(2026, 9, 15, tzinfo=timezone.utc),
        valor_total=2261.84,
        xml_path=str(caminho),
        leiaute=leiaute,
    )


def test_reconciliar_rebaixa_registro_marcado_completo_com_resumo_no_disco(db, tmp_path):
    sessao, empresa = db
    arquivo = tmp_path / "resumo.xml"
    arquivo.write_bytes(RES_NFE_MADEIREIRA.encode())
    documento = _documento(empresa, chave=CHAVE, caminho=arquivo)
    sessao.add(documento)
    sessao.commit()

    assert xml_integridade.reconciliar(sessao, documento) == "resumo"
    sessao.commit()
    assert sessao.query(DocumentoFiscal).one().leiaute == "resumo"


def test_reconciliar_nao_mexe_no_que_esta_certo(db, tmp_path):
    sessao, empresa = db
    arquivo = tmp_path / "nota.xml"
    arquivo.write_bytes(_proc_nfe().encode())
    documento = _documento(empresa, chave=CHAVE, caminho=arquivo)
    sessao.add(documento)
    sessao.commit()

    assert xml_integridade.reconciliar(sessao, documento) is None
    assert documento.leiaute == "completo"


def test_rebaixar_divergentes_conserta_o_lote(db, tmp_path):
    sessao, empresa = db
    for indice in range(3):
        caminho = tmp_path / f"resumo_{indice}.xml"
        caminho.write_bytes(RES_NFE_MADEIREIRA.encode())
        sessao.add(_documento(empresa, chave=f"{indice:044d}", caminho=caminho))
    ok = tmp_path / "ok.xml"
    ok.write_bytes(_proc_nfe().encode())
    sessao.add(_documento(empresa, chave="9" * 44, caminho=ok))
    sessao.commit()

    assert xml_integridade.rebaixar_divergentes(sessao) == 3
    assert sessao.query(DocumentoFiscal).filter(DocumentoFiscal.leiaute == "completo").count() == 1


def test_arquivo_ausente_nao_rebaixa_o_cadastro(db, tmp_path):
    """Disco sem o arquivo é problema de backup — não é o cadastro mentindo."""
    sessao, empresa = db
    documento = _documento(empresa, chave=CHAVE, caminho=tmp_path / "sumiu.xml")
    sessao.add(documento)
    sessao.commit()

    assert xml_integridade.reconciliar(sessao, documento) is None
    assert documento.leiaute == "completo"


# ---------------------------------------------------------------------------
# 5. O relatório de exportação conta a verdade
# ---------------------------------------------------------------------------


def test_linha_do_relatorio_marca_so_resumo_quando_o_arquivo_e_resumo():
    from app.api.routers.documentos import _linha_relatorio

    empresa = SimpleNamespace(razao_social="EMPRESA", cnpj_cpf=CNPJ_CONSULTADO)
    documento = SimpleNamespace(
        id=1,
        tipo=NFE,
        direcao=SimpleNamespace(value="tomada"),
        competencia=datetime(2026, 9, 1).date(),
        data_emissao=datetime(2026, 9, 15, tzinfo=timezone.utc),
        numero="6022",
        serie="1",
        chave_acesso=CHAVE,
        emitente_documento="07485646000155",
        emitente_nome="MADEIREIRA NORTE SUL LTDA",
        destinatario_documento=CNPJ_CONSULTADO,
        destinatario_nome="EMPRESA",
        valor_total=2261.84,
        status=SimpleNamespace(value="normal"),
        xml_path="/tmp/nao-existe.xml",
        leiaute="completo",
        origem="sefaz",
        nsu="1",
    )

    # cadastro diz "completo", arquivo é o resNFe ⇒ o CSV não pode dizer "sim"
    linha = _linha_relatorio(documento, empresa, "Fluxa/E/nfe/x.xml", conteudo=RES_NFE_MADEIREIRA.encode())
    assert linha[15] == "so-resumo"

    linha_ok = _linha_relatorio(documento, empresa, "Fluxa/E/nfe/x.xml", conteudo=_proc_nfe().encode())
    assert linha_ok[15] == "sim"
