"""Planilha de inventário de certificados A1: `arquivo;cnpj;emissor;senha;validade`.

É a planilha que o escritório já tem — exportada do controle de certificados,
quase sempre sem linha de título, com o CNPJ formatado na segunda coluna e o
nome do `.pfx` na primeira:

    21260898000107.pfx;21.260.898/0001-07;ICP-Brasil;7cs19Pfi;09/03/2027

Os testes aqui cobrem a leitura dessa planilha e a importação em massa que a
usa para abrir cada `.pfx` pelo CNPJ do nome do arquivo.
"""

from datetime import datetime, timedelta, timezone
from io import BytesIO

import openpyxl
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Certificado, Empresa, Escritorio, Usuario
from app.services.cnpj import DadosCNPJ
from app.services.senhas import fundir_planilhas_dados, indexar_por_arquivo, ler_planilha

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")

# Trecho real de uma planilha de inventário (senhas fortes, sem padrão algum).
INVENTARIO = (
    "21260898000107.pfx;21.260.898/0001-07;ICP-Brasil;7cs19Pfi;09/03/2027\n"
    "22912077000170.pfx;22.912.077/0001-70;ICP-Brasil;F R F25;29/10/2026\n"
    "34089357000100.pfx;34.089.357/0001-00;ICP-Brasil;)]uUrr7YKb{<v&zw;25/03/2027\n"
    "37333519000100.pfx;37.333.519/0001-00;ICP-Brasil;Paex2020*;18/08/2027\n"
)
CABECALHO_INVENTARIO = "Arquivo;CNPJ;Emissor;Senha;Validade\n"

SENHAS_ESPERADAS = {
    "21260898000107": "7cs19Pfi",
    "22912077000170": "F R F25",
    "34089357000100": ")]uUrr7YKb{<v&zw",
    "37333519000100": "Paex2020*",
}


def _der_octet_string(dados: bytes) -> bytes:
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx(cnpj: str, razao: str, senha: str, validade_dias: int = 365) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, razao),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{razao}:{cnpj}"),
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
        .not_valid_after(agora + timedelta(days=validade_dias))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.OtherName(OID_CNPJ, _der_octet_string(cnpj.encode()))]
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


def _xlsx(linhas: list[list[object]], com_cabecalho: bool = True) -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Certificados"
    if com_cabecalho:
        ws.append(["Arquivo", "CNPJ", "Emissor", "Senha", "Validade"])
    for linha in linhas:
        ws.append(linha)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


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


@pytest.fixture
def consulta_publica_mg(monkeypatch):
    """UF/razão social sem depender de internet durante o teste."""
    from app.api.routers import empresas as router_empresas

    def _consulta(cnpj: str):
        return DadosCNPJ(
            documento=cnpj,
            razao_social=f"EMPRESA {cnpj} LTDA",
            nome_fantasia="",
            uf="MG",
            municipio="Itauna",
            codigo_ibge="3133808",
        )

    monkeypatch.setattr(router_empresas, "consultar_cnpj", _consulta)


# ── Leitura da planilha ──────────────────────────────────────────────────────


def test_inventario_sem_cabecalho_devolve_senha_por_cnpj():
    """A planilha real: cinco colunas, sem título, CNPJ na segunda coluna."""
    lidos = ler_planilha(INVENTARIO.encode("utf-8"), "certificados_e_senhas.csv")

    assert set(lidos) == set(SENHAS_ESPERADAS)
    for cnpj, senha in SENHAS_ESPERADAS.items():
        assert lidos[cnpj]["senha"] == senha
        assert lidos[cnpj]["arquivo"] == f"{cnpj}.pfx"
    assert lidos["21260898000107"]["validade"] == "09/03/2027"
    # "ICP-Brasil" é a autoridade certificadora, não a UF nem a senha.
    assert lidos["21260898000107"]["uf"] == ""


def test_inventario_com_cabecalho_devolve_as_mesmas_senhas():
    lidos = ler_planilha(
        (CABECALHO_INVENTARIO + INVENTARIO).encode("utf-8"),
        "certificados_e_senhas.csv",
    )

    assert set(lidos) == set(SENHAS_ESPERADAS)
    for cnpj, senha in SENHAS_ESPERADAS.items():
        assert lidos[cnpj]["senha"] == senha


def test_inventario_xlsx_com_e_sem_cabecalho():
    linhas = [
        ["21260898000107.pfx", "21.260.898/0001-07", "ICP-Brasil", "7cs19Pfi", "09/03/2027"],
        ["22912077000170.pfx", "22.912.077/0001-70", "ICP-Brasil", "F R F25", "29/10/2026"],
    ]

    com_cabecalho = ler_planilha(_xlsx(linhas), "certificados.xlsx")
    sem_cabecalho = ler_planilha(_xlsx(linhas, com_cabecalho=False), "certificados.xlsx")

    for lidos in (com_cabecalho, sem_cabecalho):
        assert lidos["21260898000107"]["senha"] == "7cs19Pfi"
        assert lidos["22912077000170"]["senha"] == "F R F25"


def test_cnpj_digitado_errado_e_recuperado_pelo_nome_do_arquivo():
    """`34.304.74/0001-33` (faltou dígito) ao lado de `34304074000133.pfx`.

    A linha não pode sumir: o nome do arquivo ainda identifica a empresa, e a
    senha dela é o que importa para abrir o certificado.
    """
    planilha = "34304074000133.pfx;34.304.74/0001-33;ICP-Brasil;LCJ2025;22/12/2026\n"

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert "34304074000133" in lidos
    assert lidos["34304074000133"]["senha"] == "LCJ2025"


def test_cnpj_da_coluna_e_cnpj_do_arquivo_valem_os_dois():
    """Certificado renomeado: a mesma senha responde pelos dois documentos."""
    planilha = "11444777000161.pfx;12.345.678/0001-95;ICP-Brasil;CAJURU2026;09/03/2027\n"

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert lidos["12345678000195"]["senha"] == "CAJURU2026"
    assert lidos["11444777000161"]["senha"] == "CAJURU2026"


def test_senha_com_ponto_e_virgula_nao_quebra_a_linha():
    """Senha `ou;tra` parte a linha em seis células; ela volta inteira."""
    planilha = (
        INVENTARIO
        + "11222333000181.pfx;11.222.333/0001-81;ICP-Brasil;ou;tra;09/03/2027\n"
    )

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert lidos["11222333000181"]["senha"] == "ou;tra"
    assert lidos["11222333000181"]["validade"] == "09/03/2027"
    # As outras linhas seguem intactas.
    assert lidos["21260898000107"]["senha"] == "7cs19Pfi"


def test_senha_com_ponto_e_virgula_em_planilha_de_uma_linha_so():
    planilha = "a.pfx;11.222.333/0001-81;ICP-Brasil;ou;tra;09/03/2027\n"

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert lidos["11222333000181"]["senha"] == "ou;tra"


def test_linhas_em_branco_e_espacos_nao_atrapalham():
    planilha = (
        "\n"
        + INVENTARIO.splitlines()[0]
        + "\n\n\n"
        + INVENTARIO.splitlines()[1]
        + "\n   \n"
    )

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert len(lidos) == 2
    assert lidos["22912077000170"]["senha"] == "F R F25"


def test_senha_numerica_curta_nao_vira_documento_nem_data():
    """`493650` e `270307` são senhas comuns — não podem ser lidas como CPF."""
    planilha = (
        "25280601000126.pfx;25.280.601/0001-26;ICP-Brasil;493650;31/10/2026\n"
        "35660953000160.pfx;35.660.953/0001-60;ICP-Brasil;270307;28/01/2027\n"
    )

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert lidos["25280601000126"]["senha"] == "493650"
    assert lidos["35660953000160"]["senha"] == "270307"


def test_linha_curta_no_meio_da_planilha_larga_nao_quebra_nada():
    """Linha incompleta (faltam colunas) não derruba a leitura das outras."""
    planilha = (
        INVENTARIO
        + "11222333000181.pfx;11.222.333/0001-81\n"
        + "44555666000181.pfx;44.555.666/0001-81;ICP-Brasil;SenhaBoa26;01/02/2027\n"
    )

    lidos = ler_planilha(planilha.encode("utf-8"), "certificados_e_senhas.csv")

    assert lidos["21260898000107"]["senha"] == "7cs19Pfi"
    assert lidos["44555666000181"]["senha"] == "SenhaBoa26"
    # A linha incompleta entrou sem senha: o certificado segue para os padrões.
    assert lidos["11222333000181"]["senha"] == ""


def test_planilha_sem_documento_nem_arquivoContinua_sem_inventar():
    lidos = ler_planilha(b"ALFA;ALFA SERVICOS;2020\n", "senhas.csv")

    assert lidos == {}


def test_indice_por_nome_de_arquivo_inclui_linha_sem_cnpj():
    """`certificado-novo.pfx;MinhaSenha@2026`: sem CNPJ, mas com nome e senha."""
    fundido, todas_senhas, lista = fundir_planilhas_dados(
        [("senhas.csv", "certificado-novo.pfx;MinhaSenha@2026\n".encode("utf-8"))]
    )

    assert fundido == {}
    assert "MinhaSenha@2026" in todas_senhas

    indice = indexar_por_arquivo(lista)
    # A chave ignora a extensão: `certificado-novo.pfx` acha `certificado-novo`.
    assert indice["certificado-novo"]["senha"] == "MinhaSenha@2026"


# ── Importação em massa usando a planilha ────────────────────────────────────


def test_lote_abre_certificados_com_as_senhas_do_inventario(cliente, consulta_publica_mg):
    """Ponta a ponta: .pfx com nome de CNPJ + planilha de inventário."""
    client, db, _ = cliente
    arquivos = [
        (
            "arquivos",
            (f"{cnpj}.pfx", _pfx(cnpj, f"EMPRESA {cnpj} LTDA", senha), "application/octet-stream"),
        )
        for cnpj, senha in SENHAS_ESPERADAS.items()
    ]
    arquivos.append(
        ("csv_arquivos", ("certificados_e_senhas.csv", INVENTARIO.encode("utf-8"), "text/csv"))
    )

    resposta = client.post("/empresas/lote", data={"senha": "", "uf_padrao": ""}, files=arquivos)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert corpo["criadas"] == len(SENHAS_ESPERADAS)
    assert db.query(Empresa).count() == len(SENHAS_ESPERADAS)
    assert db.query(Certificado).filter(Certificado.ativo.is_(True)).count() == len(SENHAS_ESPERADAS)
    for empresa in db.query(Empresa).all():
        assert empresa.uf == "MG"


def test_lote_devolve_quantas_linhas_a_planilha_rendeu(cliente, consulta_publica_mg):
    """O resultado diz o que a planilha rendeu — planilha mal lida não passa em silêncio."""
    client, db, _ = cliente
    cnpj, senha = "21260898000107", "7cs19Pfi"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{cnpj}.pfx", _pfx(cnpj, "EMPRESA LTDA", senha), "application/octet-stream")),
            ("csv_arquivos", ("certificados_e_senhas.csv", INVENTARIO.encode("utf-8"), "text/csv")),
        ],
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["linhas_da_planilha"] == 4
    assert corpo["senhas_da_planilha"] == 4


def test_lote_sem_planilha_devolve_contadores_zerados(cliente, consulta_publica_mg):
    client, db, _ = cliente
    cnpj, senha = "21260898000107", "7cs19Pfi"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": senha, "uf_padrao": ""},
        files=[("arquivos", (f"{cnpj}.pfx", _pfx(cnpj, "EMPRESA LTDA", senha), "application/octet-stream"))],
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["linhas_da_planilha"] == 0
    assert corpo["senhas_da_planilha"] == 0


def test_lote_abre_certificados_com_planilha_xlsx(cliente, consulta_publica_mg):
    client, db, _ = cliente
    linhas = [
        [f"{cnpj}.pfx", cnpj, "ICP-Brasil", senha, "09/03/2027"]
        for cnpj, senha in SENHAS_ESPERADAS.items()
    ]
    arquivos = [
        (
            "arquivos",
            (f"{cnpj}.pfx", _pfx(cnpj, f"EMPRESA {cnpj} LTDA", senha), "application/octet-stream"),
        )
        for cnpj, senha in SENHAS_ESPERADAS.items()
    ]
    arquivos.append(("csv_arquivos", ("certificados.xlsx", _xlsx(linhas), "application/vnd.ms-excel")))

    resposta = client.post("/empresas/lote", data={"senha": "", "uf_padrao": ""}, files=arquivos)

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert corpo["criadas"] == len(SENHAS_ESPERADAS)


def test_lote_usa_a_senha_da_linha_mesmo_com_cnpj_digitado_errado(cliente, consulta_publica_mg):
    """O .pfx abre pela senha da linha cujo CNPJ veio torto na planilha."""
    client, db, _ = cliente
    cnpj = "34304074000133"
    senha = "LCJ2025"
    planilha = f"{cnpj}.pfx;34.304.74/0001-33;ICP-Brasil;{senha};22/12/2026\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{cnpj}.pfx", _pfx(cnpj, "LCJ COMERCIO LTDA", senha), "application/octet-stream")),
            ("csv_arquivos", ("certificados_e_senhas.csv", planilha.encode("utf-8"), "text/csv")),
        ],
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert corpo["criadas"] == 1
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == cnpj).one()


def test_lote_acha_senha_pelo_nome_quando_o_pfx_nao_tem_cnpj(cliente, consulta_publica_mg):
    """`certificado-novo.pfx` sem CNPJ no nome: a planilha diz de quem é."""
    client, db, _ = cliente
    cnpj = "21260898000107"
    senha = "7cs19Pfi"
    planilha = f"certificado-novo.pfx;{cnpj};ICP-Brasil;{senha};09/03/2027\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", ("certificado-novo.pfx", _pfx(cnpj, "EMPRESA NOVA LTDA", senha), "application/octet-stream")),
            ("csv_arquivos", ("certificados_e_senhas.csv", planilha.encode("utf-8"), "text/csv")),
        ],
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert corpo["criadas"] == 1
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == cnpj).one()
    assert empresa.uf == "MG"


def test_lote_com_uf_na_planilha_nao_depende_de_consulta_publica(cliente, monkeypatch):
    """Lotes grandes: a coluna UF na planilha dispensa uma consulta por CNPJ."""
    client, db, _ = cliente
    from app.api.routers import empresas as router_empresas

    def _explodiu(cnpj: str):  # pragma: no cover - não deve ser chamada
        raise AssertionError("consulta pública chamada mesmo com UF na planilha")

    monkeypatch.setattr(router_empresas, "consultar_cnpj", _explodiu)

    cnpj = "21260898000107"
    senha = "7cs19Pfi"
    planilha = f"Arquivo;CNPJ;Emissor;Senha;UF;Validade\n{cnpj}.pfx;{cnpj};ICP-Brasil;{senha};MG;09/03/2027\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{cnpj}.pfx", _pfx(cnpj, "EMPRESA MG LTDA", senha), "application/octet-stream")),
            ("csv_arquivos", ("certificados_e_senhas.csv", planilha.encode("utf-8"), "text/csv")),
        ],
    )

    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == cnpj).one().uf == "MG"
