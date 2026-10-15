import httpx
import pytest

from app.services.jettax import BASE_URL_PADRAO, ClienteJettax, JettaxErro


def test_token_puro_sem_redirecionamento(caplog):
    def responder(request):
        assert request.headers["Authorization"] == "segredo-teste"
        return httpx.Response(200, json={"data": []})
    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        ClienteJettax(token="segredo-teste", client=client).testar()
    assert "segredo-teste" not in caplog.text


@pytest.mark.parametrize("status,codigo", [(401, 401), (403, 401), (429, 429), (302, 502)])
def test_erros_sem_expor_corpo_ou_token(status, codigo, caplog):
    chamadas = []
    def responder(request):
        chamadas.append(request)
        return httpx.Response(status, text="segredo-teste", headers={"Location": "https://outro.invalid"})
    with httpx.Client(transport=httpx.MockTransport(responder), follow_redirects=True) as client:
        with pytest.raises(JettaxErro) as erro:
            ClienteJettax(token="segredo-teste", client=client).testar()
    assert erro.value.status_code == codigo
    assert len(chamadas) == 1
    assert "segredo-teste" not in str(erro.value) + caplog.text


@pytest.mark.parametrize("url", ["http://morfeu.jettax360.com.br", BASE_URL_PADRAO + "/api", BASE_URL_PADRAO + "?x=1", "https://outro.invalid"])
def test_host_fixo(url):
    with pytest.raises(JettaxErro):
        ClienteJettax(url, "token")


def test_retry_apenas_transitorio(monkeypatch):
    monkeypatch.setattr("app.services.jettax.time.sleep", lambda _: None)
    chamadas = []
    def responder(request):
        chamadas.append(request)
        return httpx.Response(503 if len(chamadas) < 3 else 200, json={"data": []})
    with httpx.Client(transport=httpx.MockTransport(responder)) as client:
        ClienteJettax(token="token", client=client).testar()
    assert len(chamadas) == 3


@pytest.fixture(autouse=True)
def sem_espera_jettax(monkeypatch):
    monkeypatch.setattr("app.services.jettax.time.sleep", lambda _: None)


@pytest.mark.parametrize("falha", [httpx.ReadTimeout, httpx.ConnectError])
def test_rede_retry_limitado_sem_expor_excecao(falha):
    chamadas = []
    def responder(request):
        chamadas.append(request)
        raise falha("TOKEN_NAO_EXPOR")
    with httpx.Client(transport=httpx.MockTransport(responder)) as http, pytest.raises(JettaxErro) as erro:
        ClienteJettax(token="TOKEN_NAO_EXPOR", client=http).testar()
    assert len(chamadas) == 3
    assert "TOKEN_NAO_EXPOR" not in str(erro.value)
    assert erro.value.__suppress_context__


@pytest.mark.parametrize("destino", ["http://example.com/x", "https://usuario:senha@example.com/x", "https://127.0.0.1/x", "https://169.254.169.254/x", "https://example.com:8443/x"])
def test_download_recusa_ssrf(destino, monkeypatch):
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(JettaxErro):
        ClienteJettax(token="t").baixar_xml(destino)


def test_storage_nunca_herda_credenciais_e_nao_log_url(monkeypatch, caplog):
    import logging
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    caplog.set_level(logging.DEBUG)
    def responder(req):
        assert "authorization" not in req.headers
        assert "cookie" not in req.headers
        return httpx.Response(200, content=b"<NFSe/>")
    with httpx.Client(transport=httpx.MockTransport(responder), headers={"Authorization": "TOKEN_PRIVADO", "Cookie": "SESSAO_PRIVADA"}, auth=("usuario", "senha")) as http:
        assert ClienteJettax(token="TOKEN_PRIVADO", client=http).baixar_xml("https://storage.test/a?token=LINK_PRIVADO") == b"<NFSe/>"
    assert "LINK_PRIVADO" not in caplog.text and "TOKEN_PRIVADO" not in caplog.text


@pytest.mark.parametrize("corpo", [b'<!DOCTYPE x [<!ENTITY x "texto">]><x/>', b"x" * (2 * 1024 * 1024 + 1)])
def test_download_limites_e_dtd(corpo, monkeypatch):
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=corpo))) as http:
        with pytest.raises(JettaxErro):
            ClienteJettax(token="t", client=http).baixar_xml("https://storage.test/xml")


def test_dtd_utf16_tambem_recusado(monkeypatch):
    monkeypatch.setattr("app.services.jettax.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    corpo = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x><x/>'.encode("utf-16")
    with httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=corpo))) as http, pytest.raises(JettaxErro):
        ClienteJettax(token="t", client=http).baixar_xml("https://storage.test/xml")
