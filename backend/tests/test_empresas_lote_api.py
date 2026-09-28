"""Importação em massa de empresas (pfx + CSV) via API."""

import io
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import ExtensionOID, NameOID, ObjectIdentifier
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

OID_CNPJ = ObjectIdentifier("2.16.76.1.3.3")
SENHA = "senha-do-certificado-fake"
CNPJ_A = "12345678000195"
CNPJ_B = "11444777000161"


def _der_octet_string(dados: bytes) -> bytes:
    # ICP-Brasil guarda o CNPJ como OCTET STRING DER dentro do OtherName
    return b"\x04" + bytes([len(dados)]) + dados


def _pfx(cnpj: str, razao: str, senha: str = SENHA, validade_dias: int = 365) -> bytes:
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, razao),
            x509.NameAttribute(NameOID.COMMON_NAME, f"{razao}:{cnpj}"),
        ]
    )
    agora = datetime.now(timezone.utc)
    # Vencido (validade_dias < 0): a vigência começa antes do vencimento.
    inicio = (
        agora - timedelta(days=1)
        if validade_dias >= 0
        else agora + timedelta(days=validade_dias - 1)
    )
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(inicio)
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


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from app.core import config

    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))

    # TestClient roda a aplicação em outra thread — uma única conexão
    # compartilhada (StaticPool) garante que todas as threads vejam as
    # mesmas tabelas do banco em memória.
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


def test_consulta_cnpj_preenche_uf_e_cadastro_sem_uf(cliente, monkeypatch):
    client, db, _ = cliente
    from app.api.routers import empresas as router_empresas

    monkeypatch.setattr(
        router_empresas,
        "consultar_cnpj",
        lambda cnpj: DadosCNPJ(
            documento=cnpj,
            razao_social="ALFA SERVICOS LTDA",
            nome_fantasia="ALFA",
            uf="PR",
            municipio="Curitiba",
        ),
    )

    consulta = client.get(f"/empresas/consulta-cnpj/{CNPJ_A}")
    assert consulta.status_code == 200
    assert consulta.json()["uf"] == "PR"
    assert consulta.json()["encontrado"] is True

    resposta = client.post("/empresas", json={"cnpj_cpf": CNPJ_A})
    assert resposta.status_code == 201, resposta.text
    corpo = resposta.json()
    assert corpo["razao_social"] == "ALFA SERVICOS LTDA"
    assert corpo["uf"] == "PR"
    assert db.query(Empresa).filter(Empresa.cnpj_cpf == CNPJ_A).one().uf == "PR"


def test_lote_sem_uf_confirmada_nao_inventa_estado(cliente, monkeypatch):
    """Sem dado público ou planilha, o lote deve pedir correção — nunca supor SP."""
    client, db, _ = cliente
    from app.api.routers import empresas as router_empresas

    monkeypatch.setattr(router_empresas, "consultar_cnpj", lambda _cnpj: None)
    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA},
        files=[
            ("arquivos", ("empresa_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
        ],
    )

    assert resposta.status_code == 200
    item = resposta.json()["itens"][0]
    assert item["status"] == "erro"
    assert "UF não identificada automaticamente" in item["mensagem"]
    assert db.query(Empresa).count() == 0


def test_lote_cria_empresas_e_vincula_certificado(cliente, tmp_path):
    client, db, escritorio_id = cliente

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", ("empresa_a_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("arquivos", ("empresa_b_11444777000161.pfx", _pfx(CNPJ_B, "BETA COMERCIO LTDA"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 2
    assert corpo["criadas"] == 2
    assert corpo["erros"] == 0

    empresas = db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id).all()
    assert len(empresas) == 2
    assert {e.cnpj_cpf for e in empresas} == {CNPJ_A, CNPJ_B}
    assert all(e.uf == "SP" for e in empresas)
    assert all(e.razao_social for e in empresas)
    # certificado gravado + senha cifrada (nunca texto puro)
    assert db.query(Certificado).count() == 2
    for certificado in db.query(Certificado).all():
        assert SENHA not in certificado.senha_cifrada
        # O arquivo no volume não contém a chave privada em claro.
        bruto = Path(certificado.arquivo_path).read_bytes()
        assert bruto.startswith(b"NOTASFLOW-PFX-FERNET-V1\n")
        assert SENHA.encode() not in bruto


def test_lote_senha_errada_reporta_erro_e_continua(cliente):
    client, db, _ = cliente
    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "MG"},
        files=[
            ("arquivos", ("boa_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("arquivos", ("ruim_11444777000161.pfx", _pfx(CNPJ_B, "BETA COMERCIO LTDA", senha="outra-senha"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 1
    assert corpo["erros"] == 1
    erros = [item for item in corpo["itens"] if item["status"] == "erro"]
    assert len(erros) == 1
    assert "senha" in erros[0]["mensagem"].lower()
    assert db.query(Empresa).count() == 1


def test_lote_nao_duplica_empresa_existente_e_atualiza_certificado(cliente):
    client, db, escritorio_id = cliente
    empresa = Empresa(
        escritorio_id=escritorio_id,
        razao_social="ALFA SERVICOS LTDA",
        cnpj_cpf=CNPJ_A,
        uf="SP",
    )
    db.add(empresa)
    db.commit()

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", ("renew_12345678000195.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
        ],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 0
    assert corpo["certificados"] == 1
    assert db.query(Empresa).count() == 1
    assert db.query(Certificado).filter(
        Certificado.empresa_id == empresa.id, Certificado.ativo.is_(True)
    ).count() == 1


def test_lote_csv_cria_empresa_sem_certificado(cliente):
    client, db, _ = cliente
    csv = bytes(
        "razao_social;cnpj_cpf;uf\nGAMA TRANSPORTES LTDA;11444777000161;PR\n",
        encoding="utf-8",
    )
    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[("csv_arquivos", ("empresas.csv", csv, "text/csv"))],
    )
    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["criadas"] == 1
    empresa = db.query(Empresa).filter(Empresa.cnpj_cpf == "11444777000161").one()
    assert empresa.uf == "PR"
    assert empresa.razao_social == "GAMA TRANSPORTES LTDA"
    assert db.query(Certificado).count() == 0


def test_lote_sem_arquivo_nem_csv_da_erro(cliente):
    client, _, _ = cliente
    resposta = client.post("/empresas/lote", data={"senha": "", "uf_padrao": "SP"})
    assert resposta.status_code == 400


def test_criacao_preenche_ibge_vindo_da_consulta_publica(monkeypatch):
    from app.api.routers.empresas import _completar_dados_empresa
    from app.schemas import EmpresaCriar
    from app.services.cnpj import DadosCNPJ

    monkeypatch.setattr(
        "app.api.routers.empresas._consulta_publica",
        lambda _cnpj: DadosCNPJ(
            documento="12345678000199",
            razao_social="Empresa da Consulta",
            uf="MG",
            municipio="Cajuru",
            codigo_ibge="3114205",
        ),
    )

    dados = _completar_dados_empresa(EmpresaCriar(cnpj_cpf="12.345.678/0001-99"))

    assert dados["codigo_ibge"] == "3114205"


def test_lote_texto_cadastra_as_pendencias_da_importacao(cliente, monkeypatch):
    """O botão 'Cadastrar estas empresas' do resultado da importação de lista.

    Nome e CNPJ vieram com a lista; a UF é descoberta pelo CNPJ. Quem a
    consulta pública não resolve volta como pendência explicando o que falta
    — nada de empresa fiscalmente incompleta por palpite.
    """
    client, db, escritorio_id = cliente
    from app.api.routers import empresas as router_empresas

    consultadas: list[str] = []

    def _consulta(cnpj: str):
        consultadas.append(cnpj)
        if cnpj == "41470879000112":
            return DadosCNPJ(documento=cnpj, uf="MG", municipio="Belo Horizonte")
        return None  # a outra não tem retorno público

    monkeypatch.setattr(router_empresas, "consultar_cnpj", _consulta)
    db.add(Empresa(escritorio_id=escritorio_id, razao_social="CLIENTE ANTIGO LTDA", cnpj_cpf="12345678000195", uf="PR"))
    db.commit()

    resposta = client.post(
        "/empresas/lote-texto",
        json={
            "empresas": [
                {"documento": "41.470.879/0001-12", "razao_social": "ACAIZIM LTDA"},
                {"documento": "65375901000103", "razao_social": "ARF PARTICIPACOES LTDA"},
                {"documento": "12345678000195", "razao_social": "JÁ EXISTE LTDA"},
                {"documento": "12.345.678/0001-00", "razao_social": "DOCUMENTO ERRADO"},
            ]
        },
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["total"] == 4
    assert corpo["criadas"] == 1
    assert corpo["ja_existiam"] == 1
    assert corpo["erros"] == 2

    por_documento = {item["cnpj_cpf"]: item for item in corpo["itens"]}
    # Mascarado ou não: a chave é o documento normalizado.
    acaizim = por_documento["41470879000112"]
    assert acaizim["status"] == "criada"
    assert acaizim["uf"] == "MG"
    # A razão social é a da lista — é assim que o operador reconhece o cliente.
    criada = db.query(Empresa).filter_by(cnpj_cpf="41470879000112").one()
    assert criada.razao_social == "ACAIZIM LTDA"
    # Sem UF confirmada: pendência, não palpite.
    arf = por_documento["65375901000103"]
    assert arf["status"] == "erro"
    assert "UF" in arf["mensagem"]
    assert db.query(Empresa).filter_by(cnpj_cpf="65375901000103").first() is None
    # A consulta pública só roda para quem precisa de UF.
    assert "41470879000112" in consultadas
    assert "65375901000103" in consultadas
    assert "12345678000195" not in consultadas


def test_lote_texto_recusa_corpo_vazio(cliente):
    client, _, _ = cliente
    assert client.post("/empresas/lote-texto", json={"empresas": []}).status_code == 422


# ---------------------------------------------------------------------------
# Planilha de senhas: o formato que existe na mesa do escritório, não o ideal
# ---------------------------------------------------------------------------


def test_planilha_de_senhas_com_virgula_e_cabecalho_acentuado(cliente):
    """Export que vem com `,` e "Razão Social" com acento também tem de valer."""
    client, db, escritorio_id = cliente
    csv_virgula = (
        "Razão Social,CNPJ,Senha\n"
        f"ALFA SERVICOS LTDA,{CNPJ_A},{SENHA}\n"
    )

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "senha-global-nao-usada", "uf_padrao": "MG"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("csv_arquivos", ("senhas.csv", csv_virgula, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["erros"] == 0
    # A senha que abriu o arquivo foi a da planilha — a global é descartável.
    assert corpo["criadas"] == 1
    empresa = db.query(Empresa).filter_by(cnpj_cpf=CNPJ_A).one()
    assert empresa.razao_social == "ALFA SERVICOS LTDA"


def test_planilha_de_senhas_sem_cabecalho_documento_ponto_e_virgula_senha(cliente):
    """A planilha mais comum que existe: duas colunas, sem título nenhum."""
    client, db, escritorio_id = cliente
    csv_seco = f"12.345.678/0001-95;{SENHA}\n11.444.777/0001-61;{SENHA}\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "PR"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("arquivos", (f"{CNPJ_B}.pfx", _pfx(CNPJ_B, "BETA COMERCIO LTDA"), "application/octet-stream")),
            ("csv_arquivos", ("senhas.csv", csv_seco, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    # Sem senha global e sem cabeçalho: as senhas da planilha abriram os dois.
    assert corpo["erros"] == 0
    assert corpo["criadas"] == 2
    assert db.query(Certificado).count() == 2


def test_planilha_de_senhas_com_terceira_coluna_uf(cliente):
    """`documento;senha;uf` sem cabeçalho: a UF da planilha vale."""
    client, db, escritorio_id = cliente
    csv_uf = f"{CNPJ_A};{SENHA};BA\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": ""},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("csv_arquivos", ("senhas.csv", csv_uf, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    assert resposta.json()["erros"] == 0
    empresa = db.query(Empresa).filter_by(cnpj_cpf=CNPJ_A).one()
    assert empresa.uf == "BA"


def test_planilha_sem_cabecalho_e_sem_documento_nao_inventa_nada(cliente):
    """Três colunas que não são documento;senha;uf = formato desconhecido: nada."""
    client, db, _ = cliente
    csv_ambiguo = "ALFA;ALFA SERVICOS;2020\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA"), "application/octet-stream")),
            ("csv_arquivos", ("senhas.csv", csv_ambiguo, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    # O certificado entrou com a senha global; a planilha virou nada.
    assert resposta.json()["criadas"] == 1

def test_lote_pasta_com_versao_antiga_e_atualizada_mantem_a_atual(cliente):
    """A pasta traz o certificado antigo e o atualizado do mesmo CNPJ: sobrevive
    o de maior validade real — não o primeiro da lista."""
    client, db, _ = cliente

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}-antigo.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA", validade_dias=30), "application/octet-stream")),
            ("arquivos", (f"{CNPJ_A}-atualizado.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA", validade_dias=400), "application/octet-stream")),
        ],
    )

    assert resposta.status_code == 200
    corpo = resposta.json()
    assert corpo["erros"] == 0
    assert corpo["criadas"] == 1

    por_origem = {item["origem"]: item for item in corpo["itens"]}
    atualizado = por_origem[f"{CNPJ_A}-atualizado.pfx"]
    assert atualizado["status"] == "criada"
    assert "válido até" in atualizado["mensagem"]

    antigo = por_origem[f"{CNPJ_A}-antigo.pfx"]
    assert antigo["status"] == "substituido"
    assert f"{CNPJ_A}-atualizado.pfx" in antigo["mensagem"]
    assert "vale até" in antigo["mensagem"]

    # Só a versão atualizada chegou ao cofre.
    certificados = db.query(Certificado).all()
    assert len(certificados) == 1
    agora_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    delta = (certificados[0].validade - agora_naive).days
    assert 398 <= delta <= 400


def test_lote_certificado_expirado_entra_com_aviso_claro(cliente):
    """Vincular um certificado vencido não é erro do lote, mas o item precisa
    dizer que ele não serve para capturar."""
    client, db, _ = cliente

    resposta = client.post(
        "/empresas/lote",
        data={"senha": SENHA, "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA", validade_dias=-10), "application/octet-stream")),
        ],
    )

    assert resposta.status_code == 200
    item = resposta.json()["itens"][0]
    assert item["status"] == "criada"
    assert "EXPIRADO" in item["mensagem"]
    assert "venceu em" in item["mensagem"]

def test_duas_planilhas_a_senha_certa_pode_estar_na_antiga(cliente):
    """A empresa trocou a senha ao renovar o certificado: a senha que abre
    está na planilha antiga — e é ela que tem que ir para o cofre."""
    from app.core.vault import decifrar_segredo

    client, db, _ = cliente
    senha_certa = "senha-nova"
    csv_atual = f"cnpj;senha\n{CNPJ_A};senha-trocada\n"
    csv_antiga = f"cnpj;senha\n{CNPJ_A};{senha_certa}\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA", senha=senha_certa), "application/octet-stream")),
            ("csv_arquivos", ("atual.csv", csv_atual, "text/csv")),
            ("csv_arquivos", ("antiga.csv", csv_antiga, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    item = resposta.json()["itens"][0]
    assert item["status"] == "criada"
    certificado = db.query(Certificado).one()
    assert decifrar_segredo(certificado.senha_cifrada) == senha_certa


def test_antigo_e_atualizado_com_senhas_de_planilhas_diferentes(cliente):
    """O caso completo do escritório: o certificado antigo abre com a senha
    da planilha antiga, o atualizado com a da planilha nova — sobrevive o de
    maior validade, com a senha dele no cofre."""
    from app.core.vault import decifrar_segredo

    client, db, _ = cliente
    pfx_antigo = _pfx(CNPJ_A, "ALFA SERVICOS LTDA", senha="senha-velha", validade_dias=30)
    pfx_atualizado = _pfx(CNPJ_A, "ALFA SERVICOS LTDA", senha="senha-nova", validade_dias=400)
    csv_antiga = f"cnpj;senha\n{CNPJ_A};senha-velha\n"
    csv_nova = f"cnpj;senha\n{CNPJ_A};senha-nova\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}-antigo.pfx", pfx_antigo, "application/octet-stream")),
            ("arquivos", (f"{CNPJ_A}-atualizado.pfx", pfx_atualizado, "application/octet-stream")),
            ("csv_arquivos", ("antiga.csv", csv_antiga, "text/csv")),
            ("csv_arquivos", ("nova.csv", csv_nova, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    por_origem = {item["origem"]: item for item in resposta.json()["itens"]}
    assert por_origem[f"{CNPJ_A}-atualizado.pfx"]["status"] == "criada"
    assert por_origem[f"{CNPJ_A}-antigo.pfx"]["status"] == "substituido"

    certificado = db.query(Certificado).one()
    assert decifrar_segredo(certificado.senha_cifrada) == "senha-nova"
    agora_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    assert (certificado.validade - agora_naive).days >= 398


def test_nenhuma_senha_das_planilhas_abre_conta_quantas_foram_testadas(cliente):
    client, db, _ = cliente
    csv_1 = f"cnpj;senha\n{CNPJ_A};errada-1\n"
    csv_2 = f"cnpj;senha\n{CNPJ_A};errada-2\n"

    resposta = client.post(
        "/empresas/lote",
        data={"senha": "", "uf_padrao": "SP"},
        files=[
            ("arquivos", (f"{CNPJ_A}.pfx", _pfx(CNPJ_A, "ALFA SERVICOS LTDA", senha="a-certa"), "application/octet-stream")),
            ("csv_arquivos", ("1.csv", csv_1, "text/csv")),
            ("csv_arquivos", ("2.csv", csv_2, "text/csv")),
        ],
    )

    assert resposta.status_code == 200
    item = resposta.json()["itens"][0]
    assert item["status"] == "erro"
    assert "Foram testadas 2 senha(s) declaradas" in item["mensagem"]
