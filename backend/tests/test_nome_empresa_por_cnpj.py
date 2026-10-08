"""Nome da empresa pelo CNPJ: régua de razão social + cadastro (Acessórias → Receita).

Coberto aqui, na ordem em que o bug apareceu no escritório:

1. um A1 cujo subject traz a cadeia (`O = ICP-Brasil`) não pode entregar
   "ICP-Brasil" como razão social de 203 empresas;
2. a planilha que só tem CNPJ e senha não tem nome — o nome vem do cadastro;
3. o cadastro do escritório (Acessórias) é consultado antes da fonte pública,
   que é o que também entrega a UF;
4. `POST /empresas/completar-cadastros` conserta os cadastros que ficaram com
   o nome da cadeia, sem exigir reenvio de certificado.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from app.core.nomes import (
    eh_marca_de_cadeia,
    eh_nome_provisorio,
    limpar_nome,
    nome_provisorio,
    nome_usavel,
    precisa_completar_nome,
)
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import Empresa, Escritorio, Usuario
from app.services import cadastro as servico_cadastro
from app.services.certificados import extrair_identidade
from app.services.cnpj import DadosCNPJ

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
SENHA = "senha-do-certificado-fake"
CNPJ_A = "12345678000195"
CNPJ_B = "11444777000161"


def _der_octet_string(dados: bytes) -> bytes:
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx(cnpj: str, *, organizacao: str = "ICP-Brasil", comum: str = "", unidade: str = "", senha: str = SENHA) -> bytes:
    """Um A1 de verdade: O é a cadeia, CN pode ser só o número do CNPJ."""
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    atributos = [x509.NameAttribute(NameOID.COUNTRY_NAME, "BR")]
    if organizacao:
        atributos.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organizacao))
    if unidade:
        atributos.append(x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, unidade))
    atributos.append(x509.NameAttribute(NameOID.COMMON_NAME, comum or cnpj))
    nome = x509.Name(atributos)
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .add_extension(
            x509.SubjectAlternativeName([x509.OtherName(OID_CNPJ, _der_octet_string(cnpj.encode()))]),
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
        yield db

    app.dependency_overrides[get_db] = _get_db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id

    yield TestClient(app), db, escritorio.id

    app.dependency_overrides.clear()
    db.close()


class ClienteFalso:
    """Ficha do Acessórias no formato oficial (`Razao`, `Fantasia`, `UF`)."""

    def __init__(self, fichas: dict[str, dict]):
        self.fichas = fichas
        self.consultados: list[str] = []

    def obter_empresa(self, identificador: str):
        self.consultados.append(identificador)
        return self.fichas.get(identificador)


# ── régua de nome ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "valor",
    [
        "ICP-Brasil",
        "icpbrasil",
        "ICP Brasil",
        "Razão social ICP-Brasil",
        "Razão social",
        "AC Soluti",
        "AC Certisign RFB v5",
        "Autoridade Certificadora do Brasil",
        "12.345.678/0001-95",
        "21260898000107.pfx",
        "",
        None,
    ],
)
def test_ruido_de_certificado_nunca_vira_razao_social(valor):
    assert nome_usavel(valor, documento=CNPJ_A) == ""


@pytest.mark.parametrize(
    "valor,esperado",
    [
        ("ABC COMERCIO DE ALIMENTOS LTDA", "ABC COMERCIO DE ALIMENTOS LTDA"),
        ("Razão Social: ABC COMERCIO DE ALIMENTOS LTDA", "ABC COMERCIO DE ALIMENTOS LTDA"),
        ("ABC COMERCIO LTDA:12345678000195", "ABC COMERCIO LTDA"),
        ("12345678000195 - ABC COMERCIO LTDA", "ABC COMERCIO LTDA"),
        ("ABC COMERCIO LTDA ICP-Brasil", "ABC COMERCIO LTDA"),
        ("SOLUTI CONSULTORIA LTDA", "SOLUTI CONSULTORIA LTDA"),
        ("ACME INDUSTRIAL LTDA", "ACME INDUSTRIAL LTDA"),
        ("EMPRESA DE ONIBUS SAO VICENTE", "EMPRESA DE ONIBUS SAO VICENTE"),
        ("SERRARIA SÃO JOÃO LTDA", "SERRARIA SÃO JOÃO LTDA"),
    ],
)
def test_nome_de_verdade_sobrevive_a_limpeza(valor, esperado):
    assert nome_usavel(valor, documento=CNPJ_A) == esperado


def test_limpar_nome_e_marca_de_cadeia():
    assert limpar_nome("  ICP-Brasil   ") == ""
    assert eh_marca_de_cadeia("AC Soluti")
    assert not eh_marca_de_cadeia("SOLUTI CONSULTORIA LTDA")
    assert eh_nome_provisorio("Empresa 12345678000195", CNPJ_A)
    assert eh_nome_provisorio("Empresa 12.345.678/0001-95", CNPJ_A)
    assert not eh_nome_provisorio("EMPRESA DE ONIBUS SAO VICENTE", CNPJ_A)
    assert nome_provisorio(CNPJ_A) == f"Empresa {CNPJ_A}"
    # placeholder é nome "aproveitável" para a tela, mas precisa de correção
    assert nome_usavel(nome_provisorio(CNPJ_A), documento=CNPJ_A) == ""
    assert precisa_completar_nome("ABC COMERCIO LTDA", CNPJ_A) is False
    assert precisa_completar_nome("ICP-Brasil", CNPJ_A) is True


# ── certificado cujo subject só tem a cadeia ────────────────────────────────


def test_certificado_sem_nome_no_subject_devolve_placeholder():
    identidade = extrair_identidade(_pfx(CNPJ_A), SENHA)
    assert identidade.documento == CNPJ_A
    assert identidade.razao_social == f"Empresa {CNPJ_A}"
    assert "icp" not in identidade.razao_social.lower()
    assert identidade.nome_no_certificado is False


def test_certificado_com_nome_no_subject_confirma_o_nome():
    identidade = extrair_identidade(_pfx(CNPJ_A, comum="KR SERVICOS MEDICOS LTDA:12345678000195"), SENHA)
    assert identidade.razao_social == "KR SERVICOS MEDICOS LTDA"
    assert identidade.nome_no_certificado is True


def test_marca_de_cadeia_no_ou_nao_substitui_o_nome():
    identidade = extrair_identidade(
        _pfx(CNPJ_A, organizacao="ICP-Brasil", unidade="AC Certisign RFB v5", comum="PAPELARIA CENTENARIO LTDA"),
        SENHA,
    )
    assert identidade.razao_social == "PAPELARIA CENTENARIO LTDA"


# ── resolver de cadastro: Acessórias antes da fonte pública ─────────────────


def test_consultar_cadastro_prefere_acessorias_e_nao_chama_a_receita():
    chamado = {"publica": 0}

    def _publica(_cnpj):
        chamado["publica"] += 1
        return DadosCNPJ(documento=CNPJ_A, razao_social="RECEITA", uf="SP")

    falso = ClienteFalso({CNPJ_A: {"Razao": "ALFA SERVICOS LTDA", "Fantasia": "ALFA", "UF": "PR"}})
    resultado = servico_cadastro.consultar_cadastro(
        None, 7, CNPJ_A, consultar_publica=_publica, cliente=falso
    )
    assert resultado is not None
    assert resultado.razao_social == "ALFA SERVICOS LTDA"
    assert resultado.uf == "PR"
    assert resultado.fonte == "Acessórias"
    assert chamado["publica"] == 0, "com nome e UF no Acessórias não se consulta mais ninguém"
    assert falso.consultados == [CNPJ_A]


def test_consultar_cadastro_cai_na_fonte_publica_quando_nao_ha_cadastro():
    def _publica(cnpj):
        return DadosCNPJ(
            documento=cnpj, razao_social="BETA COMERCIO LTDA", uf="MG", codigo_ibge="3114205", fonte="BrasilAPI"
        )

    resultado = servico_cadastro.consultar_cadastro(
        None, 8, CNPJ_B, consultar_publica=_publica, cliente=ClienteFalso({})
    )
    assert resultado is not None
    assert resultado.razao_social == "BETA COMERCIO LTDA"
    assert resultado.uf == "MG"
    assert resultado.codigo_ibge == "3114205"
    assert resultado.fonte == "BrasilAPI"


def test_consultar_cadastro_completa_na_publica_quando_acessorias_responde_incompleto():
    """Nome do Acessórias + UF da Receita: as duas fontes se completam."""

    def _publica(cnpj):
        return DadosCNPJ(documento=cnpj, razao_social="", uf="RS", codigo_ibge="4314902", fonte="CNPJ.ws")

    falso = ClienteFalso({CNPJ_A: {"Razao": "GAMA TECNOLOGIA LTDA", "UF": ""}})
    resultado = servico_cadastro.consultar_cadastro(
        None, 9, CNPJ_A, consultar_publica=_publica, cliente=falso
    )
    assert resultado is not None
    assert resultado.razao_social == "GAMA TECNOLOGIA LTDA"
    assert resultado.uf == "RS"
    assert resultado.codigo_ibge == "4314902"
    assert resultado.fonte == "Acessórias + CNPJ.ws"


def test_consultar_cadastro_cacheia_a_ausencia():
    chamado = {"publica": 0}

    def _publica(_cnpj):
        chamado["publica"] += 1
        return None

    vazio = ClienteFalso({})
    assert servico_cadastro.consultar_cadastro(None, 10, CNPJ_A, consultar_publica=_publica, cliente=vazio) is None
    assert chamado["publica"] == 1
    assert servico_cadastro.consultar_cadastro(None, 10, CNPJ_A, consultar_publica=_publica, cliente=vazio) is None
    assert chamado["publica"] == 1, "o cache protege o limite das fontes externas"

    # `forcar=True` é a saída para "acabei de cadastrar esta empresa no Acessórias"
    recem_cadastrada = ClienteFalso({CNPJ_A: {"Razao": "TEM LTDA", "UF": "SP"}})
    resultado = servico_cadastro.consultar_cadastro(
        None, 10, CNPJ_A, consultar_publica=_publica, cliente=recem_cadastrada, forcar=True
    )
    assert resultado is not None and resultado.razao_social == "TEM LTDA"


def test_falha_do_acessorias_nao_derruba_a_importacao():
    """429 do Acessórias: segue com a fonte pública e poupa o provedor no resto da rodada."""
    from app.services.acessorias import AcessoriasErro

    class ClienteComErro:
        def __init__(self) -> None:
            self.chamadas = 0

        def obter_empresa(self, identificador: str):
            self.chamadas += 1
            raise AcessoriasErro("Limite de 100 requisições por minuto do Acessórias atingido.", 429)

    quebrado = ClienteComErro()

    def _publica(cnpj):
        return DadosCNPJ(documento=cnpj, razao_social="DELTA LTDA", uf="SP", fonte="BrasilAPI")

    resultado = servico_cadastro.consultar_cadastro(None, 11, CNPJ_A, consultar_publica=_publica, cliente=quebrado)
    assert resultado is not None and resultado.razao_social == "DELTA LTDA"
    # pausa registrada: `cliente_acessorias` devolve None no resto da rodada e
    # os próximos CNPJs do lote vão direto para a fonte pública
    assert servico_cadastro._ACESSORIAS_PAUSADO_ATE.get(11, 0) > 0
    assert quebrado.chamadas == 1


# ── importação em massa: o caso das 203 empresas ────────────────────────────


def _sem_consulta_publica(monkeypatch):
    from app.api.routers import empresas as router_empresas

    monkeypatch.setattr(router_empresas, "consultar_cnpj", lambda _cnpj: None)


def test_lote_sem_nome_na_planilha_usa_o_cadastro_por_cnpj(cliente, monkeypatch):
    """Planilha só com CNPJ+senha, .pfx sem nome: o nome vem do Acessórias."""
    client, db, _ = cliente
    _sem_consulta_publica(monkeypatch)
    falso = ClienteFalso({CNPJ_A: {"Razao": "ALFA SERVICOS LTDA", "UF": "PR"}})
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (falso, ""))

    planilha = f"{CNPJ_A}.pfx;{CNPJ_A};ICP-Brasil;{SENHA};09/03/2027\n"
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A), "application/octet-stream")),
            ("csv_arquivos", ("inventario.csv", planilha.encode(), "text/csv")),
        ],
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["erros"] == 0, corpo["itens"]
    assert corpo["empresas_sem_nome"] == 0
    assert corpo["itens"][0]["razao_social"] == "ALFA SERVICOS LTDA"
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert empresa.razao_social == "ALFA SERVICOS LTDA"
    assert empresa.uf == "PR"


def test_lote_com_icp_brasil_na_coluna_de_nome_nao_grava_icp_brasil(cliente, monkeypatch):
    """Mesmo uma planilha que repete "ICP-Brasil" na coluna de nome não grava isso."""
    client, db, _ = cliente
    _sem_consulta_publica(monkeypatch)
    monkeypatch.setattr(
        servico_cadastro,
        "cliente_acessorias",
        lambda _db, _esc: (ClienteFalso({CNPJ_A: {"Razao": "GAMA TECNOLOGIA LTDA", "UF": "SC"}}), ""),
    )

    planilha = f"Arquivo;Razão social;CNPJ;Senha\n{CNPJ_A}.pfx;ICP-Brasil;{CNPJ_A};{SENHA}\n"
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A), "application/octet-stream")),
            ("csv_arquivos", ("relacao.csv", planilha.encode(), "text/csv")),
        ],
    )
    assert resposta.status_code == 200, resposta.text
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert empresa.razao_social == "GAMA TECNOLOGIA LTDA"


def test_lote_sem_cadastro_em_lugar_nenhum_recebe_nome_provisorio(cliente, monkeypatch):
    """Nem Acessórias nem Receita: o lote não grava "ICP-Brasil"; grava o CNPJ."""
    client, db, _ = cliente
    _sem_consulta_publica(monkeypatch)
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (ClienteFalso({}), ""))

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A), "application/octet-stream"))],
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert empresa.razao_social == f"Empresa {CNPJ_A}"
    assert "icp" not in empresa.razao_social.lower()
    # o lote avisa quantas entraram sem nome, em vez de deixar a lista muda
    assert corpo["empresas_sem_nome"] == 1


def test_reimportar_corrige_o_nome_que_ficou_icp_brasil(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    db.add(
        Empresa(
            escritorio_id=escritorio_id,
            cnpj_cpf=CNPJ_A,
            razao_social="ICP-Brasil",
            uf="PR",
        )
    )
    db.commit()
    monkeypatch.setattr(
        servico_cadastro,
        "cliente_acessorias",
        lambda _db, _esc: (ClienteFalso({CNPJ_A: {"Razao": "ALFA SERVICOS LTDA", "UF": "PR"}}), ""),
    )

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": ""},
        files=[("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A), "application/octet-stream"))],
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["itens"][0]["razao_social"] == "ALFA SERVICOS LTDA"
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().razao_social == "ALFA SERVICOS LTDA"


def test_reimportar_nao_apaga_nome_verdadeiro(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    db.add(Empresa(escritorio_id=escritorio_id, cnpj_cpf=CNPJ_A, razao_social="CLIENTE ANTIGO S/A", uf="PR"))
    db.commit()
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (ClienteFalso({}), ""))

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": ""},
        files=[("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A), "application/octet-stream"))],
    )
    assert resposta.status_code == 200, resposta.text
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().razao_social == "CLIENTE ANTIGO S/A"


# ── reparo em massa dos cadastros pendentes ─────────────────────────────────


def _sem_nome_db(db, escritorio_id, cnpj: str, razao: str, uf: str = ""):
    db.add(Empresa(escritorio_id=escritorio_id, cnpj_cpf=cnpj, razao_social=razao, uf=uf or "SP"))
    db.commit()


def _credencial_acessorias(db, escritorio_id):
    """Token gravado: a resposta precisa dizer que a fonte do escritório existe."""
    from app.core.vault import cifrar_segredo
    from app.models import AcessoriasCredencial

    db.add(
        AcessoriasCredencial(
            escritorio_id=escritorio_id,
            base_url="https://api.acessorias.com",
            token_cifrado=cifrar_segredo("token-de-teste"),
        )
    )
    db.commit()


def test_completar_cadastros_conserta_os_que_ficaram_com_nome_da_cadeia(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    _credencial_acessorias(db, escritorio_id)
    _sem_nome_db(db, escritorio_id, CNPJ_A, "ICP-Brasil")
    _sem_nome_db(db, escritorio_id, CNPJ_B, "Empresa " + CNPJ_B)
    fichas = {
        CNPJ_A: {"Razao": "ALFA SERVICOS LTDA", "UF": "PR"},
        CNPJ_B: {"Razao": "BETA COMERCIO LTDA", "UF": "MG"},
    }
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (ClienteFalso(fichas), ""))

    resposta = client.post("/empresas/completar-cadastros", json={})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["analisadas"] == 2
    assert corpo["corrigidas"] == 2
    assert corpo["acessorias_configurado"] is True
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().razao_social == "ALFA SERVICOS LTDA"
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_B).one().razao_social == "BETA COMERCIO LTDA"


def test_completar_cadastros_nao_toca_em_nome_bom(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    _sem_nome_db(db, escritorio_id, CNPJ_A, "CLIENTE QUE JA TEM NOME LTDA", uf="RS")
    chamado = {"n": 0}

    def _nao_chamar(_cnpj):
        chamado["n"] += 1
        return None

    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (None, "sem token"))
    monkeypatch.setattr("app.api.routers.empresas._consulta_publica", _nao_chamar)

    resposta = client.post("/empresas/completar-cadastros", json={})
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["analisadas"] == 0
    assert chamado["n"] == 0
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().razao_social == "CLIENTE QUE JA TEM NOME LTDA"


def test_completar_cadastros_usa_a_receita_para_quem_nao_esta_no_acessorias(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_nome_db(db, escritorio_id, CNPJ_A, "ICP-Brasil")
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (None, "sem token"))
    monkeypatch.setattr(
        "app.api.routers.empresas._consulta_publica",
        lambda cnpj: DadosCNPJ(documento=cnpj, razao_social="CONSULTADA DA RECEITA LTDA", uf="CE"),
    )

    resposta = client.post("/empresas/completar-cadastros", json={})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["corrigidas"] == 1
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert empresa.razao_social == "CONSULTADA DA RECEITA LTDA"


def test_completar_cadastros_relata_quem_nao_apareceu_em_nenhuma_fonte(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    _sem_nome_db(db, escritorio_id, CNPJ_A, "ICP-Brasil")
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (ClienteFalso({}), ""))

    corpo = client.post("/empresas/completar-cadastros", json={}).json()
    assert corpo["sem_fonte"] == 1
    assert corpo["itens"][0]["status"] == "sem_fonte"
    # o nome da cadeia fica, mas o item devolvido diz o que falta
    assert corpo["itens"][0]["cnpj_cpf"] == CNPJ_A


def test_completar_cadastros_respeita_o_limite_da_rodada(cliente, monkeypatch):
    """Uma rodada não conserta o escritório inteiro de uma vez: o limite vale."""
    client, db, escritorio_id = cliente
    _sem_consulta_publica(monkeypatch)
    _sem_nome_db(db, escritorio_id, CNPJ_A, "ICP-Brasil")
    _sem_nome_db(db, escritorio_id, CNPJ_B, "ICP-Brasil")
    fichas = {
        CNPJ_A: {"Razao": "ALFA SERVICOS LTDA", "UF": "PR"},
        CNPJ_B: {"Razao": "BETA COMERCIO LTDA", "UF": "MG"},
    }
    monkeypatch.setattr(servico_cadastro, "cliente_acessorias", lambda _db, _esc: (ClienteFalso(fichas), ""))

    corpo = client.post("/empresas/completar-cadastros", json={"limite": 1}).json()
    assert corpo["analisadas"] == 1
    assert corpo["corrigidas"] == 1
    # uma rodada não conserta o escritório inteiro: a outra continua pendente
    ainda_pendentes = [
        empresa.razao_social
        for empresa in db.query(Empresa).all()
        if precisa_completar_nome(empresa.razao_social, empresa.cnpj_cpf)
    ]
    assert ainda_pendentes == ["ICP-Brasil"]


def test_limite_do_corpo_e_validado():
    from app.schemas import CompletarCadastrosEntrada

    assert CompletarCadastrosEntrada(limite=10).limite == 10
    with pytest.raises(ValueError, match="entre 1 e 2000"):
        CompletarCadastrosEntrada(limite=0)


def test_certificado_com_nome_nao_consulta_nada(cliente, monkeypatch):
    """Com nome no subject e UF na planilha, o lote dispensa consulta externa.

    É o lote grande de sempre: 203 certificados que já dizem quem são não
    podem gerar 203 requisições a serviço de terceiros.
    """
    client, db, _ = cliente

    def _proibida(_cnpj):  # pragma: no cover - não deve ser chamada
        raise AssertionError("consulta externa chamada com nome e UF conhecidos")

    monkeypatch.setattr("app.api.routers.empresas._consulta_publica", _proibida)
    monkeypatch.setattr(
        servico_cadastro,
        "cliente_acessorias",
        lambda _db, _esc: (_ for _ in ()).throw(AssertionError("Acessórias consultado sem precisar")),
    )
    planilha = (
        f"Arquivo;CNPJ;Emissor;Senha;UF;Validade\n"
        f"{CNPJ_A}.pfx;{CNPJ_A};ICP-Brasil;{SENHA};MG;09/03/2027\n"
    )
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            (
                "arquivos",
                (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, comum="ALFA SERVICOS LTDA:12345678000195"), "application/octet-stream"),
            ),
            ("csv_arquivos", ("inventario.csv", planilha.encode(), "text/csv")),
        ],
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["erros"] == 0
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert empresa.razao_social == "ALFA SERVICOS LTDA"
    assert empresa.uf == "MG"


# ── sincronização com o Acessórias: nome remoto não apaga nome verdadeiro ───


class _ListadorFalso:
    def __init__(self, remotas):
        self.remotas = remotas

    def listar_empresas(self, *, somente_ativas=True, max_paginas=100):
        return self.remotas


def test_sincronizacao_corrige_placeholder_e_preserva_nome_digitado(cliente, monkeypatch):
    client, db, escritorio_id = cliente
    _credencial_acessorias(db, escritorio_id)
    db.add_all(
        [
            Empresa(escritorio_id=escritorio_id, cnpj_cpf=CNPJ_A, razao_social="CLIENTE ANTIGO S/A", uf="SP"),
            Empresa(escritorio_id=escritorio_id, cnpj_cpf=CNPJ_B, razao_social=f"Empresa {CNPJ_B}", uf="SP"),
        ]
    )
    db.commit()
    remotas = [
        {"Identificador": CNPJ_A, "Razao": "", "Fantasia": "", "UF": "SP", "Status": "Ativa"},
        {"Identificador": CNPJ_B, "Razao": "BETA COMERCIO LTDA", "UF": "MG", "Status": "Ativa"},
    ]
    from app.api.routers import acessorias as router_acessorias

    monkeypatch.setattr(router_acessorias, "_cliente", lambda credencial: _ListadorFalso(remotas))

    resposta = client.post(
        "/integracoes/acessorias/sincronizar-empresas",
        json={"atualizar_existentes": True, "somente_ativas": True},
    )
    assert resposta.status_code == 200, resposta.text
    corpo = resposta.json()
    assert corpo["atualizadas"] == 2
    assert corpo["nomes_preservados"] == 1
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().razao_social == "CLIENTE ANTIGO S/A"
    corrigida = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_B).one()
    assert corrigida.razao_social == "BETA COMERCIO LTDA"
    assert corrigida.uf == "MG"


def test_sincronizacao_empresa_nova_sem_razao_nao_vira_o_proprio_cnpj(cliente, monkeypatch):
    """Antes, `Razao` vazio gravava o CNPJ como nome — indistinguível de dado real."""
    client, db, escritorio_id = cliente
    _credencial_acessorias(db, escritorio_id)
    from app.api.routers import acessorias as router_acessorias

    monkeypatch.setattr(
        router_acessorias,
        "_cliente",
        lambda credencial: _ListadorFalso([{"Identificador": CNPJ_A, "Razao": "", "UF": "PR", "Status": "Ativa"}]),
    )
    resposta = client.post("/integracoes/acessorias/sincronizar-empresas", json={})
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["criadas"] == 1
    criada = db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one()
    assert criada.razao_social == f"Empresa {CNPJ_A}"
    assert precisa_completar_nome(criada.razao_social, criada.cnpj_cpf) is True


# ── cliente do Acessórias: ficha por CNPJ ───────────────────────────────────


class _Resposta:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Httpx:
    def __init__(self, resposta: _Resposta):
        self.resposta = resposta
        self.chamadas: list[tuple[str, dict | None]] = []

    def get(self, url, params=None, headers=None):
        self.chamadas.append((url, headers or {}))
        return self.resposta


def _cliente(como_responder):
    from app.services.acessorias import ClienteAcessorias

    return ClienteAcessorias("https://api.acessorias.com", "token", client=como_responder)


def test_obter_empresa_usa_o_documento_sem_mascara_e_o_bearer():
    http = _Httpx(_Resposta(200, {"Identificador": CNPJ_A, "Razao": "ALFA SERVICOS LTDA", "UF": "PR"}))
    ficha = _cliente(http).obter_empresa(CNPJ_A)
    assert ficha["Razao"] == "ALFA SERVICOS LTDA"
    url, headers = http.chamadas[0]
    assert url == "https://api.acessorias.com/companies/12345678000195/"
    assert headers["Authorization"] == "Bearer token"


def test_empresa_fora_do_acessorias_e_ausencia_nao_erro():
    http = _Httpx(_Resposta(200, {"Erro": "Empresa não encontrada."}))
    assert _cliente(http).obter_empresa(CNPJ_A) is None


def test_erro_de_parametro_continua_sendo_erro():
    from app.services.acessorias import AcessoriasErro

    http = _Httpx(_Resposta(200, {"Erro": "O parâmetro ativa deve ser S (Ativo) ou N (Inativo)."}))
    with pytest.raises(AcessoriasErro):
        _cliente(http).obter_empresa(CNPJ_A)
