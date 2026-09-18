"""Contrato e segurança do adaptador Jettax/Morfeu."""

from __future__ import annotations

import base64
import gzip
import json
from datetime import date, datetime, timezone

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
    JettaxCredencial,
    JettaxExecucao,
    Usuario,
    TipoDocumentoFiscal,
)
from app.services.jettax import (
    ClienteJettax,
    TentativaJettax,
    acionar_fallback_automatico,
    diagnosticar_credencial,
    executar_importacao,
    explicar_diagnostico,
)
from app.worker import tasks as worker_tasks

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


@respx.mock
def test_cliente_nfe_usa_nomes_de_filtros_exatos_da_colecao_publica():
    rota = respx.get(f"{BASE}/api/nfes/clients/{CNPJ}/purchases/").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    assert ClienteJettax(token=TOKEN).listar_nfes(
        CNPJ,
        "purchases",
        ultimo_id="81",
        chave="351234",
        data_inicial=date(2026, 8, 1),
        data_final=date(2026, 8, 31),
        cnpj_destinatario="99888777000166",
        cnpj_emitente=CNPJ,
    ) == []

    requisicao = rota.calls[0].request
    assert requisicao.headers["Authorization"] == TOKEN
    assert requisicao.headers["Content-Type"] == "application/json"
    assert requisicao.url.params["ultimoId"] == "81"
    assert requisicao.url.params["dataInicial"] == "2026-08-01"
    assert requisicao.url.params["dataFinal"] == "2026-08-31"
    assert requisicao.url.params["cnpjDestinario"] == "99888777000166"
    assert requisicao.url.params["cnpjEmitente"] == CNPJ
    assert "cnpjDestinatario" not in requisicao.url.params


@respx.mock
def test_execucao_vazia_informa_consulta_bem_sucedida_e_preserva_motivo_do_fallback(db):
    sessao, empresa, _configuracao, _ = db
    execucao = JettaxExecucao(
        empresa_id=empresa.id,
        tipo=TipoDocumentoFiscal.NFSE,
        fluxo="nfse",
        avancar_cursor=True,
        origem="fallback_check",
        aviso="Acionada automaticamente: conferência pós-consulta oficial",
    )
    sessao.add(execucao)
    sessao.commit()
    respx.get(f"{BASE}/api/nfse/invoices/{CNPJ}").mock(return_value=httpx.Response(200, json={"data": []}))

    executar_importacao(sessao, execucao.id)
    sessao.refresh(execucao)

    assert execucao.status == "concluida"
    assert execucao.documentos_importados == 0
    assert "Acionada automaticamente" in (execucao.aviso or "")
    assert "sem documentos novos" in (execucao.aviso or "")


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
    consulta = respx.get(f"{BASE}/api/clients/{CNPJ}").mock(return_value=httpx.Response(404, json={"message": "Não encontrado"}))
    rota = respx.post(f"{BASE}/api/clients").mock(return_value=httpx.Response(201, json={"id": "ok"}))

    resposta = client.post(f"/integracoes/jettax/empresas/{empresa.id}/registrar", json={})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "registrada"
    assert consulta.called
    enviado = rota.calls[0].request
    assert enviado.headers["Authorization"] == TOKEN
    assert enviado.headers["Content-Type"] == "application/json"
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
def test_registro_reconcilia_cliente_remoto_existente_sem_repetir_post(cliente_api):
    """Status local novo não deve causar erro de unicidade para CNPJ já remoto."""
    client, _db, empresa = cliente_api
    assert client.patch(
        f"/empresas/{empresa.id}",
        json={"codigo_ibge": "3133808", "inscricao_municipal": "CCM-42"},
    ).status_code == 200
    assert client.put(
        f"/integracoes/jettax/empresas/{empresa.id}",
        json={"ativa": True, "baixar_nfes": True},
    ).status_code == 200
    consulta = respx.get(f"{BASE}/api/clients/{CNPJ}").mock(
        return_value=httpx.Response(200, json={"data": {"cnpj": CNPJ, "razao_social": "CADASTRO ANTIGO"}})
    )
    atualizacao = respx.put(f"{BASE}/api/clients/{CNPJ}").mock(
        return_value=httpx.Response(200, json={"data": {"cnpj": CNPJ}})
    )
    criacao = respx.post(f"{BASE}/api/clients").mock(return_value=httpx.Response(409, json={"message": "Não deveria chamar"}))

    resposta = client.post(f"/integracoes/jettax/empresas/{empresa.id}/registrar", json={})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "atualizada"
    assert consulta.call_count == 1
    assert atualizacao.call_count == 1
    assert criacao.call_count == 0
    corpo = json.loads(atualizacao.calls[0].request.content)
    assert corpo["cnpj"] == CNPJ
    assert corpo["baixar_nfes"] == 1


@respx.mock
def test_atualizacao_recria_cliente_remoto_ausente(cliente_api):
    """Mesmo botão de atualização se recupera quando o cliente foi apagado remotamente."""
    client, _db, empresa = cliente_api
    assert client.patch(
        f"/empresas/{empresa.id}",
        json={"codigo_ibge": "3133808", "inscricao_municipal": "CCM-42"},
    ).status_code == 200
    assert client.put(
        f"/integracoes/jettax/empresas/{empresa.id}",
        json={"ativa": True},
    ).status_code == 200
    consulta = respx.get(f"{BASE}/api/clients/{CNPJ}").mock(return_value=httpx.Response(404, json={"message": "Não encontrado"}))
    criacao = respx.post(f"{BASE}/api/clients").mock(return_value=httpx.Response(201, json={"data": {"cnpj": CNPJ}}))

    resposta = client.put(f"/integracoes/jettax/empresas/{empresa.id}/registrar", json={})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "registrada"
    assert consulta.call_count == 1
    assert criacao.call_count == 1


@respx.mock
def test_registro_corrige_credencial_legada_antes_de_reconciliar_cliente(cliente_api):
    """Falha de autenticação no GET não deve executar POST/PUT antes do diagnóstico."""
    from app.core.vault import cifrar_segredo
    from app.models import Escritorio

    client, db, empresa = cliente_api
    assert client.patch(
        f"/empresas/{empresa.id}",
        json={"codigo_ibge": "3133808", "inscricao_municipal": "CCM-42"},
    ).status_code == 200
    escritorio = db.query(Escritorio).one()
    db.add(
        JettaxCredencial(
            escritorio_id=escritorio.id,
            base_url=BASE,
            token_cifrado=cifrar_segredo(TOKEN),
            esquema_autenticacao="puro",
        )
    )
    db.commit()

    # A credencial antiga aponta para o primeiro host: as duas tentativas de
    # header falham antes de qualquer alteração do cliente remoto.
    respx.get(f"{BASE}/api/clients/{CNPJ}").mock(
        side_effect=[
            httpx.Response(401, json={"message": "Token inválido."}),
            httpx.Response(401, json={"message": "Token inválido."}),
        ]
    )
    respx.get(f"{BASE}/api/nfse/cities").mock(
        side_effect=[
            httpx.Response(401, json={"message": "Token inválido."}),
            httpx.Response(401, json={"message": "Token inválido."}),
        ]
    )
    respx.get(f"{BASE_ALTERNATIVA}/api/nfse/cities").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{BASE_ALTERNATIVA}/api/clients/{CNPJ}").mock(return_value=httpx.Response(404, json={"message": "Não encontrado"}))
    criacao = respx.post(f"{BASE_ALTERNATIVA}/api/clients").mock(return_value=httpx.Response(201, json={"data": {"cnpj": CNPJ}}))

    resposta = client.post(f"/integracoes/jettax/empresas/{empresa.id}/registrar", json={})

    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["status"] == "registrada"
    assert criacao.call_count == 1
    assert db.query(JettaxCredencial).one().base_url == BASE_ALTERNATIVA


@respx.mock
def test_erro_remoto_nao_ecoha_corpo_nem_token(monkeypatch):
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": f"token {TOKEN} inválido"})
    )
    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).verificar_conexao()
    assert TOKEN not in str(erro.value)
    assert "autenticação" in str(erro.value)


@respx.mock
def test_token_colado_com_bearer_aspas_e_quebras_sai_puro_no_header():
    """A Morfeu espera API Key (token puro); colagens com 'Bearer' são limpas."""
    rota = respx.get(f"{BASE}/api/nfse/cities").mock(return_value=httpx.Response(200, json=[]))

    ClienteJettax(token='  Bearer   "tok-en\ncom quebra"\n ').verificar_conexao()

    assert rota.called
    assert rota.calls[0].request.headers["Authorization"] == "tok-encomquebra"


@respx.mock
def test_erro_autenticacao_indica_status_e_host_da_url_configurada():
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(403, json={"message": f"{TOKEN} não encontrado"})
    )
    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).verificar_conexao()

    assert TOKEN not in str(erro.value)
    assert "403" in str(erro.value)
    assert "morfeu-api.jettax.com.br" in str(erro.value)


@respx.mock
def test_painel_salva_token_normalizado_e_o_teste_envia_puro(cliente_api):
    client, _db, _empresa = cliente_api
    rota = respx.get(f"{BASE}/api/nfse/cities").mock(return_value=httpx.Response(200, json=[]))

    salvamento = client.put(
        "/integracoes/jettax/credencial",
        json={"token": "Bearer  token-do-painel \ncom-quebra ", "base_url": BASE},
    )
    assert salvamento.status_code == 200, salvamento.text

    teste = client.post("/integracoes/jettax/testar")
    assert teste.status_code == 200, teste.text

    assert rota.called
    assert rota.calls[0].request.headers["Authorization"] == "token-do-painelcom-quebra"


def test_painel_recusa_token_que_fica_vazio_apos_limpeza(cliente_api):
    client, _db, _empresa = cliente_api
    resposta = client.put(
        "/integracoes/jettax/credencial",
        json={"token": "Bearer   ", "base_url": BASE},
    )
    assert resposta.status_code == 422
    assert "limpeza" in resposta.json()["detail"]


def test_fallback_automatico_enfileira_jettax_com_filtros_do_periodo(db, monkeypatch):
    sessao, empresa, configuracao, _ = db
    configuracao.ativa = True
    configuracao.baixar_nfes = True
    configuracao.status = "registrada"
    sessao.commit()
    chamadas: list[dict] = []

    def _delay(**kwargs):
        chamadas.append(kwargs)

    monkeypatch.setattr(worker_tasks.importar_documentos_jettax, "delay", _delay)

    resultado = acionar_fallback_automatico(
        sessao,
        empresa,
        TipoDocumentoFiscal.NFE,
        origem="fallback_656",
        motivo="cStat 656 na SEFAZ",
        data_inicio=date(2026, 8, 1),
        data_fim=date(2026, 8, 31),
    )

    assert resultado.status == "enfileirada"
    assert resultado.fluxo == "purchases"
    assert chamadas == [
        {
            "execucao_id": resultado.execucao_id,
            "filtros": {"data_inicial": "2026-08-01", "data_final": "2026-08-31"},
        }
    ]
    execucao = sessao.get(JettaxExecucao, resultado.execucao_id)
    assert execucao.origem == "fallback_656"
    assert execucao.avancar_cursor is False
    assert execucao.aviso == "Acionada automaticamente: cStat 656 na SEFAZ"
    assert configuracao.travado_em is not None


def test_fallback_automatico_nao_exige_importacao_manual_e_nao_duplica(db, monkeypatch):
    sessao, empresa, configuracao, _ = db
    configuracao.ativa = True
    configuracao.status = "registrada"
    sessao.commit()
    chamadas: list[dict] = []
    monkeypatch.setattr(worker_tasks.importar_documentos_jettax, "delay", lambda **kwargs: chamadas.append(kwargs))

    primeiro = acionar_fallback_automatico(
        sessao,
        empresa,
        TipoDocumentoFiscal.NFSE,
        origem="fallback_check",
        motivo="conferência pós-consulta oficial",
    )
    segundo = acionar_fallback_automatico(
        sessao,
        empresa,
        TipoDocumentoFiscal.NFSE,
        origem="fallback_check",
        motivo="conferência pós-consulta oficial",
    )

    assert primeiro.status == "enfileirada"
    assert segundo.status == "ja_em_andamento"
    assert segundo.execucao_id == primeiro.execucao_id
    assert len(chamadas) == 1
    execucao = sessao.get(JettaxExecucao, primeiro.execucao_id)
    assert execucao.fluxo == "nfse"
    assert execucao.origem == "fallback_check"
    assert execucao.avancar_cursor is True


def test_fallback_automatico_respeita_configuracao_desativada(db, monkeypatch):
    sessao, empresa, configuracao, _ = db
    configuracao.ativa = False
    configuracao.status = "registrada"
    sessao.commit()
    chamadas: list[dict] = []
    monkeypatch.setattr(worker_tasks.importar_documentos_jettax, "delay", lambda **kwargs: chamadas.append(kwargs))

    resultado = acionar_fallback_automatico(
        sessao,
        empresa,
        TipoDocumentoFiscal.NFE,
        origem="fallback_656",
        motivo="teste",
    )

    assert resultado.status == "desativada"
    assert chamadas == []
    assert sessao.query(JettaxExecucao).count() == 0


# --------------------------------------------------------------------------
# Autenticação: formato do header, mensagem do fornecedor e autodiagnóstico.
#
# A Morfeu responde a MESMA mensagem genérica ("Token inválido.") para token
# errado e para header em formato inesperado, e mantém dois endereços de
# produção. Estes testes travam o comportamento que torna esse cenário
# diagnosticável em vez de um 502 mudo.
# --------------------------------------------------------------------------

BASE_ALTERNATIVA = "https://morfeu.jettax.com.br"


@respx.mock
def test_401_no_formato_documentado_repete_com_bearer_e_conclui():
    """Instâncias atrás de middleware Bearer não podem derrubar a integração."""
    rota = respx.get(f"{BASE}/api/nfse/cities").mock(
        side_effect=[
            httpx.Response(401, json={"message": "Token inválido."}),
            httpx.Response(200, json=[{"id": 1}]),
        ]
    )

    cliente = ClienteJettax(token=TOKEN)
    assert cliente.verificar_conexao() == [{"id": 1}]

    assert rota.call_count == 2
    assert rota.calls[0].request.headers["Authorization"] == TOKEN
    assert rota.calls[1].request.headers["Authorization"] == f"Bearer {TOKEN}"
    # O formato que funcionou é memorizado: a chamada seguinte não paga outro 401.
    assert cliente.esquema_autenticacao == "bearer"


@respx.mock
def test_mensagem_da_jettax_chega_ao_operador_sem_vazar_token():
    """Sem o texto do fornecedor, o operador fica sem diagnóstico."""
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": "Token inválido."})
    )

    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).verificar_conexao()

    assert "Token inválido." in str(erro.value)
    assert TOKEN not in str(erro.value)


@respx.mock
def test_mensagem_remota_que_ecoa_o_token_e_redigida():
    """O fornecedor pode devolver o token na mensagem; ele não pode vazar."""
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(403, json={"message": f"Token {TOKEN} não encontrado"})
    )

    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).verificar_conexao()

    assert TOKEN not in str(erro.value)
    assert "[redigido]" in str(erro.value)


@respx.mock
def test_diagnostico_encontra_o_endereco_correto_da_jettax():
    """O token emitido para o outro host é a causa clássica do 401 eterno."""
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": "Token inválido."})
    )
    respx.get(f"{BASE_ALTERNATIVA}/api/nfse/cities").mock(return_value=httpx.Response(200, json=[]))

    sucesso, tentativas = diagnosticar_credencial(TOKEN, BASE)

    assert sucesso is not None
    assert sucesso.base_url == BASE_ALTERNATIVA
    assert len(tentativas) >= 2


@respx.mock
def test_diagnostico_nunca_envia_o_token_para_fora_do_dominio_jettax():
    externo = respx.get("https://exemplo-invasor.test/api/nfse/cities").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": "Token inválido."})
    )
    respx.get(f"{BASE_ALTERNATIVA}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": "Token inválido."})
    )

    sucesso, _tentativas = diagnosticar_credencial(TOKEN, "https://exemplo-invasor.test")

    assert sucesso is None
    assert not externo.called


@respx.mock
def test_credencial_recusada_recebe_explicacao_acionavel(cliente_api):
    """Recusa em todas as tentativas deve orientar sem inferir a causa."""
    client, _db, _empresa = cliente_api
    for url in (BASE, BASE_ALTERNATIVA):
        respx.get(f"{url}/api/nfse/cities").mock(
            return_value=httpx.Response(401, json={"message": "Token inválido."})
        )

    assert client.put(
        "/integracoes/jettax/credencial",
        json={"token": "token-recusado-em-todo-lugar", "base_url": BASE},
    ).status_code == 200

    resposta = client.post("/integracoes/jettax/testar")

    assert resposta.status_code == 502
    detalhe = resposta.json()["detail"]
    assert "não permite identificar a causa" in detalhe
    assert "token emitido para a API Morfeu" in detalhe
    assert "morfeu-api.jettax.com.br" in detalhe and "morfeu.jettax.com.br" in detalhe
    assert "token-recusado-em-todo-lugar" not in detalhe


@respx.mock
def test_teste_do_painel_corrige_endereco_e_passa_a_funcionar(cliente_api):
    """Salvar com o host errado não pode condenar a integração a falhar sempre."""
    client, db, _empresa = cliente_api
    respx.get(f"{BASE}/api/nfse/cities").mock(
        return_value=httpx.Response(401, json={"message": "Token inválido."})
    )
    respx.get(f"{BASE_ALTERNATIVA}/api/nfse/cities").mock(return_value=httpx.Response(200, json=[]))

    assert client.put(
        "/integracoes/jettax/credencial",
        json={"token": "token-do-outro-ambiente", "base_url": BASE},
    ).status_code == 200

    teste = client.post("/integracoes/jettax/testar")

    assert teste.status_code == 200, teste.text
    credencial = db.query(JettaxCredencial).first()
    assert credencial.base_url == BASE_ALTERNATIVA


# --------------------------------------------------------------------------
# A resposta HTTP não revela a origem nem o produto que emitiu uma chave. O
# diagnóstico deve ser acionável, mas não pode converter suposições sobre
# hashes, middleware ou outros produtos Jettax em fato.
# --------------------------------------------------------------------------


def test_explicacao_de_recusa_nao_infere_a_origem_da_credencial():
    tentativas = [
        TentativaJettax(base_url=BASE, esquema="puro", status_code=401, ok=False, mensagem="Dados de acesso inválidos."),
        TentativaJettax(base_url=BASE, esquema="bearer", status_code=403, ok=False, mensagem="Token inválido."),
    ]

    texto = explicar_diagnostico(tentativas)

    assert "Morfeu" in texto
    assert "não permite identificar a causa" in texto
    assert "token emitido" in texto
    assert "outro programa" not in texto


@respx.mock
def test_paginacao_segue_link_next_entre_os_dois_hosts_oficiais():
    """Exemplo real da coleção: resposta do -api com next no host irmão."""
    respx.get(f"{BASE}/api/nfse/invoices/{CNPJ}").mock(
        return_value=httpx.Response(200, json={
            "data": [{"id": "1"}],
            "meta": {"pagination": {"links": {"next": f"{BASE_ALTERNATIVA}/api/nfse/invoices/{CNPJ}?page=2"}}},
        })
    )
    segunda = respx.get(f"{BASE_ALTERNATIVA}/api/nfse/invoices/{CNPJ}?page=2").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "2"}]})
    )

    notas = ClienteJettax(token=TOKEN).listar_nfse(CNPJ)

    assert [n["id"] for n in notas] == ["1", "2"]
    assert segunda.called


@respx.mock
def test_paginacao_para_fora_dos_hosts_oficiais_segue_recusada():
    """A exceção é só entre morfeu-api/morfeu; externo continua bloqueado."""
    respx.get(f"{BASE}/api/nfse/invoices/{CNPJ}").mock(
        return_value=httpx.Response(200, json={
            "data": [{"id": "1"}],
            "meta": {"pagination": {"links": {"next": "https://exemplo-invasor.test/api/x"}}},
        })
    )

    with pytest.raises(Exception) as erro:
        ClienteJettax(token=TOKEN).listar_nfse(CNPJ)

    assert "paginação" in str(erro.value)
