"""Testes locais do diagnóstico independente, sem qualquer acesso à rede."""
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("diagnostico_independente", Path(__file__).resolve().parents[2] / "diagnostico_jettax.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_estrutura_nao_exporta_valores():
    saida = json.dumps(mod.estrutura({"data": [{"document": "12345678901234", "url": "https://storage.invalid/segredo", "name": "CLIENTE PRIVADO"}], "12345678901234": "token-privado"}))
    for privado in ("12345678901234", "segredo", "CLIENTE PRIVADO", "token-privado"):
        assert privado not in saida
    assert "document" in saida


def test_sem_redirecionamento():
    assert mod.SemRedirecionamento().redirect_request(None, None, 302, "", {}, "https://outro.invalid") is None


@pytest.mark.parametrize("url", ["http://example.com/x", "https://user:password@example.com/x", "https://example.com:8443/x", "https://127.0.0.1/x", "https://169.254.169.254/x"])
def test_download_recusa_destinos_inseguros(url, monkeypatch):
    monkeypatch.setattr(mod.socket, "getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("127.0.0.1", 443))])
    assert not mod.link_publico(url)


def test_fluxo_inteiro_mock_sem_dados_privados_no_relatorio(monkeypatch):
    chamadas = []
    diag = mod.Diagnostico("token-privado")
    monkeypatch.setattr(mod, "link_publico", lambda _: True)
    def consulta(nome, url, **kwargs):
        chamadas.append((nome, url, kwargs))
        if kwargs.get("json_esperado") is False:
            assert not kwargs.get("autenticado")
            return b'<NFSe><infNFSe><CNPJ>12345678901234</CNPJ></infNFSe></NFSe>'
        if "clients" in url:
            return {"data": [{"document": "12345678901234"}]}
        return {"data": [{"url": "https://storage.invalid/privado", "urlPDF": ""}], "meta": {"pagination": {"current_page": 1, "per_page": 1}}}
    monkeypatch.setattr(diag, "consultar", consulta)
    mod.executar(diag, "12345678901234", "10-2026")
    assert len(chamadas) <= 11
    saida = json.dumps(diag.resultados)
    assert "12345678901234" not in saida
    assert "token-privado" not in saida
    assert "storage.invalid" not in saida
    assert any(item.get("xml_valido") for item in diag.resultados)
