"""Contrato e segurança do adaptador Jettax/Morfeu."""

from __future__ import annotations

import base64
import gzip
import json
from datetime import datetime, timezone

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import escritorio_id_atual, usuario_atual
from app.core import config
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models import (
    DocumentoFiscal,
    DocumentoFiscalFonte,
    Empresa,
    Escritorio,
    JettaxConfiguracaoEmpresa,
    JettaxExecucao,
    Usuario,
    TipoDocumentoFiscal,
)
from app.services.jettax import ClienteJettax, executar_importacao

BASE = "https://morfeu-api.jettax.com.br"
TOKEN = "token-autorizado-somente-teste"
CNPJ = "12345678000199"


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(config.settings, "dados_dir", str(tmp_path))
    monkeypatch.setattr(config.settings, "jettax_api_base_url", BASE)
    monkeypatch.setattr(config.settings, "jettax_api_token", TOKEN)
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    sessao = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório Jettax")
    sessao.add(escritorio)
    sessao.flush()
    empresa = Empresa(
        escritorio_id=escritorio.id,
        razao_social="EMPRESA JETTAX LTDA",
        cnpj_cpf=CNPJ,
        uf="MG",
        codigo_ibge="3133808",
        inscricao_municipal="123456",
    )
    sessao.add(empresa)
    sessao.flush()
    configuracao = JettaxConfiguracaoEmpresa(empresa_id=empresa.id, status="registrada")
    sessao.add(configuracao)
    sessao.commit()
    yield sessao, empresa, configuracao, tmp_path
    sessao.close()


@respx.mock
def test_cliente_usa_header_authorization_filtros_documentados_e_paginacao(monkeypatch):
    monkeypatch.setattr(config.settings, "jettax_max_paginas_por_execucao", 3)
    primeira = respx.get(
        f"{BASE}/api/nfse/invoices/{CNPJ}",
        params={"lastId": "9", "numero": "1", "notaSituacao": "autorizada", "tipoNota": "enviada", "period": "8-2026"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{"id": "10", "numero": "1"}],
                "meta": {"pagination": {"links": {"next": f"{BASE}/api/nfse/invoices/{CNPJ}?page=2"}}},
            },
        )
    )
    segunda = respx.get(f"{BASE}/api/nfse/invoices/{CNPJ}?page=2").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "11", "numero": "2"}]})
    )

    notas = ClienteJettax(token=TOKEN).listar_nfse(
        CNPJ, last_id="9", numero="1", nota_situacao="autorizada", tipo_nota="enviada", period="8-2026"
    )

    assert [nota["id"] for nota in notas] == ["10", "11"]
    assert primeira.called and segunda.called
    requisicao = primeira.calls[0].request
    assert requisicao.headers["Authorization"] == TOKEN
    assert requisicao.url.params["lastId"] == "9"
    assert requisicao.url.params["notaSituacao"] == "autorizada"
    assert requisicao.url.params["tipoNota"] == "enviada"
    assert requisicao.url.params["period"] == "8-2026"


@respx.mock
def test_execucao_nfse_persiste_metadados_sem_inventar_xml_e_so_entao_avanca_cursor(db):
    sessao, empresa, configuracao, _ = db
    execucao = JettaxExecucao(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFSE,
        fluxo="nfse",
        avancar_cursor=True,
        cursor_antes=None,
    )
    sessao.add(execucao)
    sessao.commit()
    respx.get(f"{BASE}/api/nfse/invoices/{CNPJ}").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [{
                    "id": "101",
                    "numero": "42",
                    "codigoVerificacao": "ABC",
                    "dataEmissao": "2026-08-10",
                    "dataCompetencia": "2026-08",
                    "tipoNota": "emitida",
                    "notaSituacao": "autorizada",
                    "servico": {"valores": {"valorLiquidoNfse": "123.45"}},
                    "prestadorServico": {
                        "identificacaoPrestador": {"cnpj": CNPJ},
                        "razaoSocial": "EMPRESA JETTAX LTDA",
                    },
                    "tomadorServico": {
                        "identificacaoTomador": {"cpfCnpj": "99888777000166"},
                        "razaoSocial": "TOMADOR LTDA",
                    },
                    "url": "https://exemplo.invalido/nao-usar",
                }]}
        )
    )

    executar_importacao(sessao, execucao.id)
    sessao.refresh(execucao)
    sessao.refresh(configuracao)
    documento = sessao.query(DocumentoFiscal).one()

    assert execucao.status == "concluida"
    assert execucao.documentos_importados == 1
    assert configuracao.ultimo_id_nfse == "101"
    assert documento.chave_acesso == "jettax-nfse-101"
    assert documento.leiaute == "metadados"
    assert documento.xml_path == ""
    assert documento.numero == "42"
    assert documento.valor_total == 123.45
    assert documento.direcao.value == "prestada"
    fonte = sessao.query(DocumentoFiscalFonte).one()
    assert fonte.origem == "jettax"
    assert fonte.identificador_externo == "101"


def _xml_nfe() -> bytes:
    chave = "35260812345678000199550010000000011234567890"
    xml = f"""<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe">
    <NFe><infNFe Id="NFe{chave}">
      <ide><dhEmi>2026-08-10T09:30:00-03:00</dhEmi><nNF>1</nNF><serie>1</serie></ide>
      <emit><CNPJ>{CNPJ}</CNPJ><xNome>EMPRESA JETTAX LTDA</xNome></emit>
      <dest><CNPJ>99888777000166</CNPJ><xNome>TOMADOR LTDA</xNome></dest>
      <total><ICMSTot><vNF>77.90</vNF></ICMSTot></total>
    </infNFe></NFe></nfeProc>"""
    return base64.b64encode(gzip.compress(xml.encode())).decode()


@respx.mock
def test_execucao_nfe_descompacta_xml_gzip_base64_e_preserva_proveniencia(db):
    sessao, empresa, configuracao, dados_dir = db
    execucao = JettaxExecucao(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFE,
        fluxo="sales",
        avancar_cursor=True,
    )
    sessao.add(execucao)
    sessao.commit()
    respx.get(f"{BASE}/api/nfes/clients/{CNPJ}/sales/").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "600", "XML": _xml_nfe()}]})
    )

    executar_importacao(sessao, execucao.id)
    sessao.refresh(execucao)
    sessao.refresh(configuracao)
    documento = sessao.query(DocumentoFiscal).one()

    assert execucao.status == "concluida"
    assert configuracao.ultimo_id_nfe_saida == "600"
    assert documento.leiaute == "completo"
    assert documento.origem == "jettax"
    assert (dados_dir / "xml" / str(empresa.id) / "nfe" / f"{documento.chave_acesso}.xml").is_file()
    assert sessao.query(DocumentoFiscalFonte).one().identificador_externo == "600"


@pytest.fixture
def cliente_api(monkeypatch):
    monkeypatch.setattr(config.settings, "jettax_api_base_url", BASE)
    monkeypatch.setattr(config.settings, "jettax_api_token", TOKEN)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    escritorio = Escritorio(nome="Escritório API")
    db.add(escritorio)
    db.flush()
    usuario = Usuario(escritorio_id=escritorio.id, nome="Admin", email="admin@teste", senha_hash="x", papel="admin")
    empresa = Empresa(escritorio_id=escritorio.id, razao_social="API LTDA", cnpj_cpf=CNPJ, uf="MG")
    db.add_all([usuario, empresa])
    db.commit()

    def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[usuario_atual] = lambda: usuario
    app.dependency_overrides[escritorio_id_atual] = lambda: escritorio.id
    yield TestClient(app), db, empresa
    app.dependency_overrides.clear()
    db.close()


def test_status_da_api_nunca_expoe_token_e_empresa_aceita_metadados_jettax(cliente_api):
    client, db, empresa = cliente_api
    resposta = client.get("/integracoes/jettax")
    assert resposta.status_code == 200
    assert resposta.json()["configurado"] is True
    assert TOKEN not in resposta.text

    atualizacao = client.patch(
        f"/empresas/{empresa.id}",
        json={"codigo_ibge": "3133808", "inscricao_municipal": "CCM-42"},
    )
    assert atualizacao.status_code == 200, atualizacao.text
    assert atualizacao.json()["codigo_ibge"] == "3133808"
    assert atualizacao.json()["inscricao_municipal"] == "CCM-42"
    assert db.get(Empresa, empresa.id).codigo_ibge == "3133808"

@respx.mock
def test_registro_remoto_tem_corpo_documentado_sem_revelar_segredo(cliente_api):
    client, _db, empresa = cliente_api
    assert client.patch(
        f"/empresas/{empresa.id}",
        json={"codigo_ibge": "3133808", "inscricao_municipal": "CCM-42"},
    ).status_code == 200
    assert client.put(
        f"/integracoes/jettax/empresas/{empresa.id}",
        json={"ativa": True, "baixar_nfes": True},
    ).status_code == 200
    rota = respx.post(f"{BASE}/api/clients").mock(return_value=httpx.Response(201, json={"id": "ok"}))

    resposta = client.post(f"/integracoes/jettax/empresas/{empresa.id}/registrar", json={})

    assert resposta.status_code == 200, resposta.text
    enviado = rota.calls[0].request
    assert enviado.headers["Authorization"] == TOKEN
    corpo_enviado = json.loads(enviado.content)
    assert corpo_enviado == {
        "razao_social": "API LTDA",
        "codigo_ibge": "3133808",
        "cnpj": CNPJ,
        "ccm": "CCM-42",
        # A coleção Morfeu especifica inteiros 1/0, não booleanos JSON.
        "baixar_nfes": 1,
        "baixar_nfes_enviadas": 0,
    }
    assert corpo_enviado["baixar_nfes"] is not True
    assert isinstance(corpo_enviado["baixar_nfes"], int)
    assert TOKEN not in resposta.text
    assert "digital_certificate" not in corpo_enviado


@respx.mock
def test_erro_remoto_nao_ecoha_corpo_nem_token(monkeypatch):
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": f"token {TOKEN} inválido"})
    )
    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).verificar_conexao()
    assert TOKEN not in str(erro.value)
    assert "autenticação" in str(erro.value)
