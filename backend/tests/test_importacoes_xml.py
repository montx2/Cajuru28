"""Importação manual de XMLs (ZIP/arquivos soltos) — POST /importacoes/xml.

O caminho de quem deixa outro sistema com a consulta à SEFAZ: as notas chegam
como arquivo, são lidas com os conversores oficiais e gravadas sem duplicar.
"""

import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import DocumentoFiscal, Empresa, Escritorio, Usuario

CNPJ_EMPRESA = "12345678000199"
CNPJ_FORNECEDOR = "99999999000188"

# cUF(2) AAMM(4) CNPJ(14) mod(2) serie(3) nNF(9) tpEmis(1) cNF(9)
CHAVE_NFE = f"352608{CNPJ_FORNECEDOR}55001000001231000000001"
CHAVE_NFE_PRESTADA = f"352608{CNPJ_EMPRESA}55001000004561000000002"
CHAVE_CTE = f"352608{CNPJ_FORNECEDOR}57001000007891000000003"


def _proc_nfe(chave: str, emitente: str, destinatario: str) -> bytes:
    return (
        '<nfeProc versao="4.00" xmlns="http://www.portalfiscal.inf.br/nfe">'
        f'<NFe><infNFe Id="NFe{chave}" versao="4.00"><ide>'
        f"<chNFe>{chave}</chNFe><dhEmi>2026-08-11T09:00:00-03:00</dhEmi>"
        "<nNF>123</nNF><serie>1</serie></ide>"
        f'<emit><CNPJ>{emitente}</CNPJ><xNome>Fornecedor X</xNome></emit>'
        f'<dest><CNPJ>{destinatario}</CNPJ><xNome>EMPRESA CLIENTE</xNome></dest>'
        "<total><ICMSTot><vNF>4321.10</vNF></ICMSTot></total>"
        "</infNFe></NFe><protNFe><infProt><cStat>100</cStat>"
        "<xMotivo>Autorizado o uso da NF-e</xMotivo>"
        f"<chNFe>{chave}</chNFe></infProt></protNFe></nfeProc>"
    ).encode()


def _proc_cte(chave: str, emitente: str, destinatario: str) -> bytes:
    return (
        '<cteProc versao="4.00" xmlns="http://www.portalfiscal.inf.br/cte">'
        f'<CTe><infCTe Id="CTe{chave}" versao="4.00"><ide>'
        f"<chCTe>{chave}</chCTe><dhEmi>2026-08-12T14:00:00-03:00</dhEmi></ide>"
        f'<emit><CNPJ>{emitente}</CNPJ><xNome>Transportadora</xNome></emit>'
        f'<toma4><CNPJ>{destinatario}</CNPJ></toma4>'
        "<vPrest><vTPrest>750.00</vTPrest></vPrest>"
        "</infCTe></CTe><protCTe><infProt><cStat>100</cStat>"
        f"<chCTe>{chave}</chCTe></infProt></protCTe></cteProc>"
    ).encode()


def _nfse_nacional(chave: str, prestador: str, tomador: str) -> bytes:
    return (
        '<Nfse xmlns="http://nfse.abrasf.org.br">'
        f'<infNFSe Id="{chave}">'
        "<dhEmi>2026-08-05T10:00:00</dhEmi><dCompet>2026-08-05</dCompet>"
        f"<prest><CNPJ>{prestador}</CNPJ><xNome>EMPRESA PRESTADORA</xNome></prest>"
        f"<toma><CNPJ>{tomador}</CNPJ><xNome>Cliente</xNome></toma>"
        "<vServ>1500.00</vServ><nNFSe>456</nNFSe>"
        "</infNFSe></Nfse>"
    ).encode()


def _zip_bytes(arquivos: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for nome, conteudo in arquivos.items():
            z.writestr(nome, conteudo)
    return buffer.getvalue()


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
    db.add(
        Empresa(
            escritorio_id=escritorio.id,
            cnpj_cpf=CNPJ_EMPRESA,
            razao_social="EMPRESA CLIENTE LTDA",
            uf="SP",
        )
    )
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


def test_zip_com_nfe_e_cte_importa_as_notas(cliente, tmp_path):
    client, db, _ = cliente
    zip_bytes = _zip_bytes(
        {
            "notas/nfe_123.xml": _proc_nfe(CHAVE_NFE, CNPJ_FORNECEDOR, CNPJ_EMPRESA),
            "notas/cte_789.xml": _proc_cte(CHAVE_CTE, CNPJ_FORNECEDOR, CNPJ_EMPRESA),
        }
    )

    resposta = client.post(
        "/importacoes/xml",
        files=[("arquivos", ("exportacao.zip", zip_bytes, "application/zip"))],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["importados"] == 2
    assert {item["tipo"] for item in corpo["itens"]} == {"nfe", "cte"}
    assert all(item["razao_social"] == "EMPRESA CLIENTE LTDA" for item in corpo["itens"])

    documentos = db.query(DocumentoFiscal).all()
    assert len(documentos) == 2
    por_tipo = {doc.tipo.value: doc for doc in documentos}
    assert por_tipo["nfe"].origem == "xml"
    assert por_tipo["nfe"].direcao.value == "tomada"
    assert float(por_tipo["nfe"].valor_total) == 4321.10
    assert por_tipo["nfe"].competencia is not None
    assert (tmp_path / por_tipo["nfe"].xml_path.removeprefix(str(tmp_path) + "/")).exists() or (
        por_tipo["nfe"].xml_path.startswith(str(tmp_path))
        and __import__("os").path.isfile(por_tipo["nfe"].xml_path)
    )


def test_reimportar_o_mesmo_zip_nao_duplica(cliente):
    client, db, _ = cliente
    zip_bytes = _zip_bytes({"nfe_123.xml": _proc_nfe(CHAVE_NFE, CNPJ_FORNECEDOR, CNPJ_EMPRESA)})

    for _ in range(2):
        resposta = client.post(
            "/importacoes/xml",
            files=[("arquivos", ("exportacao.zip", zip_bytes, "application/zip"))],
        )
        assert resposta.status_code == 200

    corpo = resposta.json()
    assert corpo["duplicadas"] == 1
    assert db.query(DocumentoFiscal).count() == 1


def test_nota_prestada_pela_empresa_casa_pelo_emitente(cliente):
    client, db, _ = cliente
    xml = _proc_nfe(CHAVE_NFE_PRESTADA, CNPJ_EMPRESA, CNPJ_FORNECEDOR)

    resposta = client.post(
        "/importacoes/xml",
        files=[("arquivos", ("prestada.xml", xml, "application/xml"))],
    )

    assert resposta.status_code == 200
    assert resposta.json()["importados"] == 1
    documento = db.query(DocumentoFiscal).one()
    assert documento.direcao.value == "prestada"


def test_cnpj_fora_do_cadastro_volta_sem_empresa(cliente):
    client, db, _ = cliente
    xml = _proc_nfe(CHAVE_NFE, CNPJ_FORNECEDOR, "88888888000191")

    resposta = client.post(
        "/importacoes/xml",
        files=[("arquivos", ("desconhecida.xml", xml, "application/xml"))],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["sem_empresa"] == 1
    assert "não está no cadastro" in corpo["itens"][0]["mensagem"]
    assert db.query(DocumentoFiscal).count() == 0


def test_arquivo_que_nao_e_xml_nem_zip_e_ignorado_e_leiaute_desconhecido_avisa(cliente):
    client, db, _ = cliente

    resposta = client.post(
        "/importacoes/xml",
        files=[
            ("arquivos", ("leia-me.txt", b"texto qualquer", "text/plain")),
            ("arquivos", ("sem_chave.xml", b"<html><body>nada</body></html>", "application/xml")),
        ],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    por_origem = {item["origem"]: item for item in corpo["itens"]}
    assert por_origem["leia-me.txt"]["status"] == "ignorado"
    assert por_origem["sem_chave.xml"]["status"] == "nao_reconhecido"
    assert db.query(DocumentoFiscal).count() == 0


def test_nfse_do_leiaute_nacional_importa(cliente):
    client, db, _ = cliente
    chave = "12345678901234567890123456789012345678901234567890"
    xml = _nfse_nacional(chave, CNPJ_EMPRESA, CNPJ_FORNECEDOR)

    resposta = client.post(
        "/importacoes/xml",
        files=[("arquivos", ("nfse_456.xml", xml, "application/xml"))],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    if corpo["importados"] != 1:
        pytest.fail(f"NFS-e não importada: {corpo['itens']}")
    item = corpo["itens"][0]
    assert item["tipo"] == "nfse"
    documento = db.query(DocumentoFiscal).one()
    assert documento.direcao.value == "prestada"
    assert float(documento.valor_total) == 1500.00
