"""
O caso do bug real: cStat 656 ("Consumo Indevido") no meio de uma varredura.

Antes, a importação morria em vermelho, o operador via "SEFAZ retornou
cStat=656: Rejeicao: Consumo Indevido…" e a única saída era clicar de novo — o
que, pela regra oficial, *zera o cronômetro do bloqueio*. O sistema entrava em
loop e o CNPJ ficava travado cada vez mais tempo.

O contrato novo (testado aqui):

- 656 vira estado **aguardando**, não erro;
- o bloqueio é registrado e a **continuação é reagendada sozinha**, depois da
  hora inteira (nunca antes);
- o `ultNSU`/`maxNSU` que veio **junto** na resposta é adotado (é assim que se
  destrava o caso "outro sistema consultou este CNPJ");
- nada é perdido: o checkpoint do lote anterior continua gravado;
- enquanto bloqueada, a empresa **não faz nenhuma requisição** — nem por
  clique manual, nem pelo agendador.
"""

from datetime import datetime, timedelta, timezone

import base64
import gzip

import httpx
import pytest
import respx
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import NoEncryption, PrivateFormat, pkcs12
from cryptography.x509.oid import NameOID
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import config
from app.core.vault import cifrar_segredo
from app.db.base import Base
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    Escritorio,
    ExecucaoImportacao,
    SincronizacaoDFe,
    StatusExecucao,
    TipoDocumentoFiscal,
)
from app.services import sincronizacao
from app.worker import tasks

URL_NFE = "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx"
CNPJ = "12345678000199"
SENHA = "senha-fake"


def _cert_key(tmp_path):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CNPJ)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "c.pem", tmp_path / "k.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        chave.private_bytes(
            serialization.Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
        )
    )
    return str(cert_path), str(key_path)


def _pfx(tmp_path):
    chave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    nome = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CNPJ)])
    agora = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(nome)
        .issuer_name(nome)
        .public_key(chave.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(agora - timedelta(days=1))
        .not_valid_after(agora + timedelta(days=365))
        .sign(chave, hashes.SHA256())
    )
    caminho = tmp_path / "a1.pfx"
    caminho.write_bytes(
        pkcs12.serialize_key_and_certificates(
            name=b"empresa",
            key=chave,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.BestAvailableEncryption(SENHA.encode()),
        )
    )
    return caminho


def _doc_zip(xml: str) -> str:
    return base64.b64encode(gzip.compress(xml.encode())).decode()


def _soap(cstat: str, motivo: str, ult: str, maxn: str, docs: str = "") -> bytes:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://www.w3.org/2003/05/soap-envelope">
  <soap:Body>
    <nfeDistDFeInteresseResponse xmlns="http://www.portalfiscal.inf.br/nfe/wsdl/NFeDistribuicaoDFe">
      <nfeDistDFeInteresseResult>
        <retDistDFeInt versao="1.01" xmlns="http://www.portalfiscal.inf.br/nfe">
          <tpAmb>1</tpAmb>
          <verAplic>SVRS202401</verAplic>
          <cStat>{cstat}</cStat>
          <xMotivo>{motivo}</xMotivo>
          <dhResp>2026-09-10T10:00:00-03:00</dhResp>
          <ultNSU>{ult}</ultNSU>
          <maxNSU>{maxn}</maxNSU>
          {"<loteDistDFeInt>" + docs + "</loteDistDFeInt>" if docs else ""}
        </retDistDFeInt>
      </nfeDistDFeInteresseResult>
    </nfeDistDFeInteresseResponse>
  </soap:Body>
</soap:Envelope>""".encode()


def _resumo(chave: str, nsu: str, valor: str = "1500.00", emi: str = "99999999000188") -> str:
    """Do jeito que o SEFAZ entrega: docZip com o XML gzipado em base64."""
    interno = (
        '<resNFe xmlns="http://www.portalfiscal.inf.br/nfe">'
        f"<chNFe>{chave}</chNFe><CNPJ>{emi}</CNPJ><xNome>Fornecedor X</xNome>"
        f"<dhEmi>2026-08-05T09:00:00-03:00</dhEmi><vNF>{valor}</vNF>"
        "</resNFe>"
    )
    return (
        f'<docZip NSU="{nsu}" schema="resNFe_v1.00.xsd">{_doc_zip(interno)}</docZip>'
    )


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Banco em memória + empresa com certificado + settings apontando para o tmp."""
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "espera_entre_lotes_segundos", 0.0)
    monkeypatch.setattr(config.settings, "ambiente_fiscal", "producao")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Escritório Teste")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="ARM LOGISTICA E TRANSPORTES LTD",
        cnpj_cpf=CNPJ,
        uf="SP",
        sincronizar_automaticamente=True,
    )
    sessao.add(empresa)
    sessao.flush()
    pfx = _pfx(tmp_path)
    sessao.add(
        Certificado(
            empresa_id=empresa.id,
            arquivo_path=str(pfx),
            senha_cifrada=cifrar_segredo(SENHA),
            validade=datetime.now(timezone.utc) + timedelta(days=300),
            ativo=True,
        )
    )
    execucao = ExecucaoImportacao(
        empresa_id=empresa.id, tipo=TipoDocumentoFiscal.NFE, status=StatusExecucao.EM_ANDAMENTO
    )
    sessao.add(execucao)
    sessao.commit()

    monkeypatch.setattr(tasks, "SessionLocal", sessionmaker(bind=engine))
    # nada de dormir em teste: os backoffs de transporte e o intervalo entre
    # páginas são reais em produção e irrelevantes aqui.
    monkeypatch.setattr(
        "app.services.importadores._distribuicao_dfe.time.sleep", lambda _: None
    )

    reagendamentos: list[tuple[int, datetime, int | None]] = []

    def _falso_reagendar(db, execucao, quando, *, motivo, tentativa=None):
        reagendamentos.append((execucao.id, quando, tentativa))
        return True

    monkeypatch.setattr(tasks, "fila_reagendar", _falso_reagendar)

    dados = {
        "sessao": sessao,
        "empresa_id": empresa.id,
        "execucao_id": execucao.id,
        "reagendamentos": reagendamentos,
        "cert_key": _cert_key(tmp_path),
    }
    yield dados
    sessao.close()


@respx.mock
def test_656_vira_aguardando_e_reagenda_para_depois_da_janela(ambiente):
    sessao = ambiente["sessao"]
    rota = respx.post(URL_NFE).mock(
        return_value=httpx.Response(
            200,
            content=_soap(
                "656",
                "Rejeicao: Consumo Indevido (Deve ser aguardado 1 hora para efetuar nova solicitacao)",
                "000000000000777",
                "000000000000800",
            ),
        )
    )

    tasks.importar_documentos(
        empresa_id=ambiente["empresa_id"], tipo="nfe", execucao_id=ambiente["execucao_id"]
    )
    # A task grava por outra Session no mesmo connection pool: sem expirar o
    # identity map, o teste leria o estado anterior ao commit do worker.
    sessao.expire_all()

    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    estado = sessao.query(SincronizacaoDFe).one()

    assert execucao.status == StatusExecucao.AGUARDANDO
    assert rota.call_count == 1
    assert "Consumo Indevido" in (execucao.mensagem_erro or "")
    # agendado para ~1h à frente (e não para "agora", que renovaria o bloqueio)
    assert len(ambiente["reagendamentos"]) == 1
    quando = ambiente["reagendamentos"][0][1]
    restante = (quando - datetime.now(timezone.utc)).total_seconds()
    assert 55 * 60 <= restante <= 70 * 60
    assert estado.bloqueado_ate is not None
    assert estado.bloqueios_seguidos == 1
    # e o cursor veio da própria resposta: nada de voltar ao zero
    assert estado.ultimo_nsu == "777"
    assert estado.max_nsu == "800"


@respx.mock
def test_enquanto_bloqueada_nenhuma_requisicao_e_feita(ambiente):
    sessao = ambiente["sessao"]
    estado = sincronizacao.obter_estado(sessao, ambiente["empresa_id"], TipoDocumentoFiscal.NFE)
    sincronizacao.marcar_consumo_indevido(sessao, estado, motivo="teste")
    sessao.commit()

    rota = respx.post(URL_NFE).mock(return_value=httpx.Response(200, content=_soap("138", "ok", "1", "1")))

    tasks.importar_documentos(
        empresa_id=ambiente["empresa_id"], tipo="nfe", execucao_id=ambiente["execucao_id"]
    )
    # A task grava por outra Session no mesmo connection pool: sem expirar o
    # identity map, o teste leria o estado anterior ao commit do worker.
    sessao.expire_all()

    assert rota.call_count == 0
    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    assert execucao.status == StatusExecucao.AGUARDANDO


@respx.mock
def test_forcar_ignora_a_janela_mas_o_checkpoint_continua(ambiente):
    sessao = ambiente["sessao"]
    estado = sincronizacao.obter_estado(sessao, ambiente["empresa_id"], TipoDocumentoFiscal.NFE)
    estado.ultimo_nsu = "42"
    sincronizacao.marcar_consumo_indevido(sessao, estado, motivo="teste")
    sessao.commit()

    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    execucao.forcar = True
    sessao.commit()

    rota = respx.post(URL_NFE).mock(
        return_value=httpx.Response(200, content=_soap("137", "Nenhum documento localizado", "42", "42"))
    )

    tasks.importar_documentos(
        empresa_id=ambiente["empresa_id"], tipo="nfe", execucao_id=ambiente["execucao_id"]
    )
    # A task grava por outra Session no mesmo connection pool: sem expirar o
    # identity map, o teste leria o estado anterior ao commit do worker.
    sessao.expire_all()

    assert rota.call_count == 1  # o operador pediu para forçar
    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.ultimo_nsu == "42"  # nunca rebaixou


@respx.mock
def test_paginacao_ate_maxnsu_guarda_todas_as_notas_e_fica_em_dia(ambiente):
    """
    Página 1 cheia (ult<max) → continua; página 2 chega no maxNSU → para e
    marca "em dia". É o que o painel mostra como ✔ sem clique nenhum.
    """
    sessao = ambiente["sessao"]
    respx.post(URL_NFE).mock(
        side_effect=[
            httpx.Response(
                200,
                content=_soap(
                    "138",
                    "Documento(s) localizado(s)",
                    "10",
                    "20",
                    _resumo("35260812345678000199550010000000011111111111", "10"),
                ),
            ),
            httpx.Response(
                200,
                content=_soap(
                    "138",
                    "Documento(s) localizado(s)",
                    "20",
                    "20",
                    _resumo("35260812345678000199550010000000022222222222", "20"),
                ),
            ),
        ]
    )

    tasks.importar_documentos(
        empresa_id=ambiente["empresa_id"], tipo="nfe", execucao_id=ambiente["execucao_id"]
    )
    # A task grava por outra Session no mesmo connection pool: sem expirar o
    # identity map, o teste leria o estado anterior ao commit do worker.
    sessao.expire_all()

    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    estado = sessao.query(SincronizacaoDFe).one()
    assert execucao.status == StatusExecucao.CONCLUIDA
    assert execucao.documentos_importados == 2
    assert execucao.ultimo_nsu == "20"
    assert sincronizacao.esta_em_dia(estado) is True
    assert sessao.query(DocumentoFiscal).count() == 2
    # em dia ⇒ a janela de 1h entra sozinha, sem o operador pensar nisso
    assert estado.proxima_consulta_em is not None


@respx.mock
def test_5xx_retenta_cedo_e_nao_finge_bloqueio(ambiente):
    """Queda de ambiente não queima cota: a espera é curta e crescente."""
    sessao = ambiente["sessao"]
    respx.post(URL_NFE).mock(return_value=httpx.Response(503, text="offline"))

    tasks.importar_documentos(
        empresa_id=ambiente["empresa_id"], tipo="nfe", execucao_id=ambiente["execucao_id"]
    )
    # A task grava por outra Session no mesmo connection pool: sem expirar o
    # identity map, o teste leria o estado anterior ao commit do worker.
    sessao.expire_all()

    execucao = sessao.get(ExecucaoImportacao, ambiente["execucao_id"])
    assert execucao.status == StatusExecucao.AGUARDANDO
    assert "indisponível" in (execucao.mensagem_erro or "")
    # primeira retomada em minutos, não em 1h
    quando = ambiente["reagendamentos"][0][1]
    assert (quando - datetime.now(timezone.utc)).total_seconds() < 10 * 60
    assert ambiente["reagendamentos"][0][2] == 1
