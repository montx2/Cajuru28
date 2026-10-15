"""Contrato real sanitizado, HTTP simulado, pipeline/conversor e banco reais SQLite."""
import logging

import httpx
import pytest

from app.core.vault import decifrar_segredo
from app.models import (DocumentoFiscal, DocumentoFiscalFonte, Empresa, Escritorio,
                        JettaxCredencial, JettaxExecucao, StatusDocumentoFiscal)
from app.services.importadores.jettax_nfse import ResultadoJettax, importar_nfse
from app.services.jettax import ClienteJettax, JettaxErro
from test_importacoes_xml import cliente, _nfse_nacional, CNPJ_EMPRESA, CNPJ_FORNECEDOR

CHAVE = "12345678901234567890123456789012345678901234567890123"
XML = _nfse_nacional(CHAVE, CNPJ_FORNECEDOR, CNPJ_EMPRESA)


@pytest.fixture(autouse=True)
def sem_espera(monkeypatch):
    monkeypatch.setattr("app.services.jettax.time.sleep", lambda _: None)
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])


def pagina(itens, atual=1, total=None, paginas=1):
    return {"data": itens, "meta": {"pagination": {
        "total": len(itens) if total is None else total, "count": len(itens),
        "current_page": atual, "per_page": 50, "total_pages": paginas,
    }}}


def nota(id="n1", situacao="autorizada", url="https://storage.exemplo.test/xml?assinatura=SEGREDO_URL"):
    return {"id": id, "url": url, "urlPDF": "", "notaSituacao": situacao}


def cliente_http(itens=None, xml=XML, situacao=None):
    def responder(req):
        if req.url.path == "/api/clients":
            assert req.headers["Authorization"] == "TOKEN_SECRETO"
            return httpx.Response(200, json=pagina([{"cnpj": CNPJ_EMPRESA}]))
        if req.url.path.startswith("/api/nfse/invoices/"):
            assert "limit" not in req.url.params
            return httpx.Response(200, json=pagina(itens if itens is not None else [nota()]))
        assert "Authorization" not in req.headers
        assert "Cookie" not in req.headers
        assert req.headers["host"] == "storage.exemplo.test"
        assert req.extensions["sni_hostname"] == "storage.exemplo.test"
        assert req.url.host == "93.184.216.34"  # conexão presa ao IP público
        return httpx.Response(situacao or 200, content=xml)
    http = httpx.Client(transport=httpx.MockTransport(responder))
    return ClienteJettax(token="TOKEN_SECRETO", client=http, intervalo=0), http


def empresa_id(db, escritorio):
    return db.query(Empresa).filter_by(escritorio_id=escritorio, cnpj_cpf=CNPJ_EMPRESA).one().id


def test_pipeline_real_idempotente_proveniencia_pdf_vazio(cliente, caplog):
    _, db, escritorio = cliente
    caplog.set_level(logging.DEBUG)
    jettax, http = cliente_http()
    with http:
        primeiro = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
        segundo = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert primeiro.importados == 1 and primeiro.consulta_completa
    assert segundo.duplicados == 1 and segundo.importados == 0
    assert db.query(DocumentoFiscal).count() == 1
    documento = db.query(DocumentoFiscal).one()
    assert documento.origem == "jettax"
    assert documento.direcao.value == "tomada"
    assert float(documento.valor_total) == 1500
    assert documento.competencia.year == 2026
    fonte = db.query(DocumentoFiscalFonte).one()
    assert fonte.origem == "jettax" and fonte.identificador_externo == "n1"
    for segredo in ("TOKEN_SECRETO", "SEGREDO_URL"):
        assert segredo not in caplog.text
        assert segredo not in str(primeiro.dados())


def test_falha_documento_nao_derruba_proximo(cliente):
    _, db, escritorio = cliente
    jettax, http = cliente_http([nota("ruim", url=""), nota("boa")])
    with http:
        resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.erros == 1 and resultado.importados == 1


def test_link_expirado_sem_retry_e_sem_gravacao(cliente):
    _, db, escritorio = cliente
    jettax, http = cliente_http(situacao=403)
    with http:
        resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.erros == 1 and resultado.importados == 0
    assert db.query(DocumentoFiscal).count() == 0


def test_cancelamento_atualiza_duplicata_sem_reautorizar(cliente):
    _, db, escritorio = cliente
    for situacao in ("autorizada", "cancelada", "autorizada"):
        jettax, http = cliente_http([nota(situacao=situacao)])
        with http:
            resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
        if situacao == "cancelada":
            assert resultado.cancelados == 1
    assert db.query(DocumentoFiscal).one().status == StatusDocumentoFiscal.CANCELADA


def test_ambas_partes_recebem_copia_sem_atravessar_escritorio(cliente):
    _, db, escritorio = cliente
    outro = Escritorio(nome="Outro")
    db.add(outro); db.flush()
    db.add_all([
        Empresa(escritorio_id=escritorio, cnpj_cpf=CNPJ_FORNECEDOR, razao_social="Prestador", uf="SP"),
        Empresa(escritorio_id=outro.id, cnpj_cpf=CNPJ_EMPRESA, razao_social="Outra", uf="SP"),
    ])
    db.commit()
    jettax, http = cliente_http()
    with http:
        resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.importados == 2
    assert db.query(DocumentoFiscal).join(Empresa).filter(Empresa.escritorio_id == outro.id).count() == 0


def test_xml_sem_empresa_correspondente_nao_grava(cliente):
    _, db, escritorio = cliente
    xml = _nfse_nacional(CHAVE, "11111111000111", "22222222000122")
    jettax, http = cliente_http(xml=xml)
    with http:
        resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.sem_empresa == 1
    assert db.query(DocumentoFiscal).count() == 0


def test_empresa_de_outro_tenant_nem_chama_http(cliente):
    _, db, escritorio = cliente
    jettax, http = cliente_http()
    with http, pytest.raises(JettaxErro):
        importar_nfse(db, jettax, escritorio + 100, empresa_id(db, escritorio), "08-2026")


def test_paginacao_page_sem_limit_e_checkpoint():
    pedidos = []
    def responder(req):
        pedidos.append(dict(req.url.params))
        atual = int(req.url.params["page"])
        return httpx.Response(200, json=pagina([nota(str(atual))], atual=atual, total=2, paginas=2))
    with httpx.Client(transport=httpx.MockTransport(responder)) as http:
        paginas = list(ClienteJettax(token="t", client=http, intervalo=0).paginas_nfse(CNPJ_EMPRESA, "08-2026"))
    assert len(paginas) == 2
    assert all("limit" not in pedido for pedido in pedidos)
    assert [p["page"] for p in pedidos] == ["1", "2"]


@pytest.mark.parametrize("alteracao", ["repetida", "total_muda", "count_errado", "vazia", "incompleta"])
def test_paginacao_inconsistente_nunca_declara_sucesso(alteracao):
    def responder(req):
        atual = int(req.url.params["page"])
        dados = pagina([nota("mesma" if alteracao == "repetida" else str(atual))], atual=atual, total=2, paginas=2)
        if atual == 2:
            if alteracao == "total_muda": dados["meta"]["pagination"]["total"] = 3
            if alteracao == "count_errado": dados["meta"]["pagination"]["count"] = 99
            if alteracao == "vazia": dados["data"] = []; dados["meta"]["pagination"]["count"] = 0
        if alteracao == "incompleta": dados = pagina([nota()], total=2)
        return httpx.Response(200, json=dados)
    with httpx.Client(transport=httpx.MockTransport(responder)) as http, pytest.raises(JettaxErro):
        list(ClienteJettax(token="t", client=http, intervalo=0).paginas_nfse(CNPJ_EMPRESA, "08-2026"))


def test_cliente_ausente_e_formato_nao_inventado(cliente):
    _, db, escritorio = cliente
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=pagina([])))) as http:
        resultado = importar_nfse(db, ClienteJettax(token="t", client=http), escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.empresa_ausente_jettax and resultado.recebidos == 0
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, json={"clientes": []}))) as http:
        with pytest.raises(JettaxErro):
            ClienteJettax(token="t", client=http).empresa_cadastrada(CNPJ_EMPRESA)


def test_rota_credencial_cofre_e_isolamento(cliente, monkeypatch):
    client, db, escritorio = cliente
    monkeypatch.setattr(ClienteJettax, "testar", lambda self: None)
    assert client.put("/integracoes/jettax/credencial", json={"token": "TOKEN_SECRETO"}).status_code == 200
    cred = db.query(JettaxCredencial).one()
    assert cred.escritorio_id == escritorio and cred.token_cifrado != "TOKEN_SECRETO"
    assert decifrar_segredo(cred.token_cifrado) == "TOKEN_SECRETO"
    assert "TOKEN_SECRETO" not in client.get("/integracoes/jettax").text
    assert client.delete("/integracoes/jettax/credencial").status_code == 204
    assert db.query(JettaxCredencial).count() == 0


def preparar_token(client, monkeypatch):
    monkeypatch.setattr(ClienteJettax, "testar", lambda self: None)
    assert client.put("/integracoes/jettax/credencial", json={"token": "TOKEN_SECRETO"}).status_code == 200


def test_rota_fila_reutiliza_execucao_sem_token_broker(cliente, monkeypatch):
    client, db, escritorio = cliente
    preparar_token(client, monkeypatch)
    from app.worker.jettax import importar_jettax_nfse
    enviados = []
    monkeypatch.setattr(importar_jettax_nfse, "apply_async", lambda **kw: enviados.append(kw))
    pedido = {"empresa_ids": [empresa_id(db, escritorio)], "competencia": "08/2026"}
    resposta = client.post("/integracoes/jettax/importar", json=pedido)
    assert resposta.status_code == 202
    assert resposta.json()[0]["competencia"] == "08-2026"
    assert client.post("/integracoes/jettax/importar", json=pedido).json()[0]["id"] == resposta.json()[0]["id"]
    assert len(enviados) == 1 and "TOKEN_SECRETO" not in str(enviados)
    assert db.query(JettaxExecucao).count() == 1
    assert client.get("/integracoes/jettax/execucoes").json()[0]["id"] == resposta.json()[0]["id"]


def test_rota_rejeita_empresa_alheia_e_fila_fora(cliente, monkeypatch):
    client, db, escritorio = cliente
    preparar_token(client, monkeypatch)
    outro = Escritorio(nome="Outro"); db.add(outro); db.flush()
    empresa = Empresa(escritorio_id=outro.id, cnpj_cpf=CNPJ_EMPRESA, razao_social="Outra", uf="SP")
    db.add(empresa); db.commit()
    assert client.post("/integracoes/jettax/importar", json={"empresa_ids": [empresa.id], "competencia": "08/2026"}).status_code == 404
    from app.services import fila
    monkeypatch.setattr(fila, "fila_respondendo", lambda: False)
    assert client.post("/integracoes/jettax/importar", json={"empresa_ids": [empresa_id(db, escritorio)], "competencia": "08/2026"}).status_code == 503
    assert db.query(JettaxExecucao).count() == 0


def test_rota_falha_publicacao_por_empresa_e_perfil_leitura(cliente, monkeypatch):
    client, db, escritorio = cliente
    preparar_token(client, monkeypatch)
    from app.worker.jettax import importar_jettax_nfse
    def falhar(**kw): raise RuntimeError("conteudo-privado-nao-expor")
    monkeypatch.setattr(importar_jettax_nfse, "apply_async", falhar)
    resposta = client.post("/integracoes/jettax/importar", json={"empresa_ids": [empresa_id(db, escritorio)], "competencia": "08/2026"})
    assert resposta.json()[0]["status"] == "erro"
    assert "conteudo-privado" not in resposta.text
    from app.models import Usuario
    db.query(Usuario).one().papel = "leitura"; db.commit()
    assert client.post("/integracoes/jettax/importar", json={"empresa_ids": [empresa_id(db, escritorio)], "competencia": "08/2026"}).status_code == 403
    assert client.put("/integracoes/jettax/credencial", json={"token": "t"}).status_code == 403


def test_listagem_e_credencial_nao_atravessam_tenant(cliente, monkeypatch):
    client, db, escritorio = cliente
    preparar_token(client, monkeypatch)
    id_empresa = empresa_id(db, escritorio)
    db.add(JettaxExecucao(escritorio_id=escritorio, empresa_id=id_empresa, competencia="08-2026", status="concluida", resultado={}))
    outro = Escritorio(nome="Outro"); db.add(outro); db.commit()
    from app.api.deps import escritorio_id_atual
    from app.main import app
    app.dependency_overrides[escritorio_id_atual] = lambda: outro.id
    assert client.get("/integracoes/jettax/execucoes").json() == []
    assert client.get("/integracoes/jettax").json()["configurado"] is False
    assert client.post("/integracoes/jettax/testar").status_code == 409


def test_erro_na_segunda_copia_desfaz_primeira(cliente, monkeypatch):
    _, db, escritorio = cliente
    db.add(Empresa(escritorio_id=escritorio, cnpj_cpf=CNPJ_FORNECEDOR, razao_social="Prestador", uf="SP")); db.commit()
    from app.services.importadores import jettax_nfse
    gravar = jettax_nfse.gravar_documento
    chamadas = []
    def falhar_segunda(*args, **kwargs):
        chamadas.append(1)
        if len(chamadas) == 2:
            raise RuntimeError("XML_NAO_DEVE_APARECER")
        return gravar(*args, **kwargs)
    monkeypatch.setattr(jettax_nfse, "gravar_documento", falhar_segunda)
    jettax, http = cliente_http()
    with http:
        resultado = importar_nfse(db, jettax, escritorio, empresa_id(db, escritorio), "08-2026")
    assert resultado.erros == 1 and resultado.importados == 0
    assert db.query(DocumentoFiscal).count() == 0
    assert "XML_NAO_DEVE_APARECER" not in str(resultado.dados())
