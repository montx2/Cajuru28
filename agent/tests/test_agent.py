"""
Testes do Cajuru Agent.

Rodam em qualquer sistema: as partes específicas do Windows são isoladas em
funções que os testes substituem. O que está sob teste aqui é o contrato — o
que o Agent envia, o que ele se recusa a fazer e como ele reage a falha.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cajuru_agent import assinador, certificados, roteiro  # noqa: E402
from cajuru_agent.config import Configuracao  # noqa: E402
from cajuru_agent.executor import Agente  # noqa: E402
from cajuru_agent.protocolo import ClienteCajuru, ProtocoloError, assinar  # noqa: E402


# ---------------------------------------------------------------------------
# Protocolo
# ---------------------------------------------------------------------------


def test_assinatura_cobre_metodo_caminho_e_corpo():
    chave = "chave-de-teste"
    a = assinar(chave, "POST", "/x", "2026-01-01T00:00:00+00:00", "n1", b'{"a":1}')
    b = assinar(chave, "POST", "/x", "2026-01-01T00:00:00+00:00", "n1", b'{"a":2}')
    c = assinar(chave, "GET", "/x", "2026-01-01T00:00:00+00:00", "n1", b'{"a":1}')
    d = assinar(chave, "POST", "/y", "2026-01-01T00:00:00+00:00", "n1", b'{"a":1}')
    assert len({a, b, c, d}) == 4, "cada componente precisa alterar a assinatura"


def test_servidor_http_e_recusado():
    with pytest.raises(ProtocoloError) as erro:
        ClienteCajuru("http://cajuru.exemplo.com", "id", "segredo")
    assert "HTTPS" in str(erro.value)


class _Transporte(httpx.BaseTransport):
    """Servidor falso que confere a assinatura de cada requisição."""

    def __init__(self):
        self.chave = "chave-de-sessao-do-teste"
        self.recebidas: list[httpx.Request] = []
        self.nonces: set[str] = set()
        self.respostas: dict[str, httpx.Response] = {}
        self.falhar_uma_vez_com_401 = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        caminho = request.url.path
        if caminho == "/procuracoes/agente/sessao" and request.method == "POST":
            return httpx.Response(
                200, json={"chave_sessao": self.chave, "expira_em_segundos": 43200}
            )

        self.recebidas.append(request)
        if self.falhar_uma_vez_com_401:
            self.falhar_uma_vez_com_401 = False
            return httpx.Response(401, json={"detail": "sessão expirada"})

        nonce = request.headers.get("X-Cajuru-Nonce", "")
        if nonce in self.nonces:
            return httpx.Response(409, json={"detail": {"codigo": "REPLAY"}})
        self.nonces.add(nonce)

        esperada = assinar(
            self.chave,
            request.method,
            caminho,
            request.headers.get("X-Cajuru-Timestamp", ""),
            nonce,
            request.content,
        )
        if not hmac.compare_digest(esperada, request.headers.get("X-Cajuru-Assinatura", "")):
            return httpx.Response(401, json={"detail": "assinatura inválida"})

        return self.respostas.get(caminho, httpx.Response(200, json={"ok": True}))


@pytest.fixture
def cliente():
    transporte = _Transporte()
    http = httpx.Client(transport=transporte, base_url="https://cajuru.teste")
    return ClienteCajuru(
        "https://cajuru.teste", "estacao-01", "segredo", cliente_http=http
    ), transporte


def test_requisicao_vai_assinada_e_com_nonce_unico(cliente):
    api, transporte = cliente
    api.heartbeat({"versao_agente": "1.0.0"})
    api.heartbeat({"versao_agente": "1.0.0"})
    assert len(transporte.recebidas) == 2
    nonces = {r.headers["X-Cajuru-Nonce"] for r in transporte.recebidas}
    assert len(nonces) == 2, "nonce repetido abriria a porta para replay"
    assert all(r.headers["X-Cajuru-Assinatura"] for r in transporte.recebidas)


def test_sessao_expirada_e_renovada_sozinha(cliente):
    api, transporte = cliente
    api.heartbeat({"versao_agente": "1.0.0"})
    transporte.falhar_uma_vez_com_401 = True
    resposta = api.heartbeat({"versao_agente": "1.0.0"})
    assert resposta == {"ok": True}, "o Agent deve reabrir a sessão e repetir"


def test_evidencia_manda_lease_em_cabecalho_e_nao_na_url(cliente):
    api, transporte = cliente
    api.enviar_evidencia(1, "lease-xyz-123", b"\x89PNG", tipo="image/png", etapa="assinatura")
    requisicao = transporte.recebidas[-1]
    assert requisicao.headers["X-Cajuru-Lease"] == "lease-xyz-123"
    assert "lease" not in str(requisicao.url.query.decode())


def test_erro_de_rede_e_marcado_como_recuperavel():
    assert ProtocoloError("x", status=503).recuperavel
    assert ProtocoloError("x", status=429).recuperavel
    assert ProtocoloError("x").recuperavel
    assert not ProtocoloError("x", status=403).recuperavel
    assert not ProtocoloError("x", status=409).recuperavel


# ---------------------------------------------------------------------------
# Certificados
# ---------------------------------------------------------------------------


def test_cnpj_sai_do_oid_icp_brasil():
    # OID 2.16.76.1.3.3 = CNPJ do titular, 14 dígitos no início.
    assert certificados.documento_do_oid("12345678000195") == "12345678000195"
    assert certificados.documento_do_oid("12.345.678/0001-95") == "12345678000195"
    assert certificados.documento_do_oid("abc") == ""


def test_cpf_sai_da_posicao_correta_do_oid():
    # DDMMAAAA + CPF(11) + NIS(11) + RG
    valor = "01011990" + "12345678901" + "00000000000" + "000000000000000"
    assert certificados.documento_de_pessoa_fisica(valor) == "12345678901"


def test_documento_tambem_e_lido_do_cn_quando_o_san_falta():
    subject = "CN=EMPRESA EXEMPLO LTDA:12345678000195, OU=RFB e-CNPJ A1, O=ICP-Brasil, C=BR"
    assert certificados._documento_do_subject(subject) == "12345678000195"
    assert certificados._nome_do_subject(subject) == "EMPRESA EXEMPLO LTDA"


#: Tudo que o Agent tem permissão de enviar sobre um certificado. Qualquer
#: campo novo precisa entrar aqui conscientemente — é o que impede alguém de
#: acrescentar "senha" ou "conteudo_pfx" ao payload sem perceber.
CAMPOS_PERMITIDOS = {
    "thumbprint",
    "documento",
    "titular_nome",
    "subject",
    "issuer",
    "numero_serie",
    "valido_de",
    "valido_ate",
    "origem",
    "referencia_local",
    "tem_chave_privada",
    "senha_disponivel",
    "tipo",
    "erro",
}


def test_payload_do_inventario_so_tem_campos_permitidos():
    item = certificados.CertificadoLocal(
        thumbprint="a" * 64, documento="12345678000195", referencia_local="CurrentUser\\My:aaa"
    )
    enviado = item.para_envio()
    assert set(enviado) == CAMPOS_PERMITIDOS
    # `senha_disponivel` é um booleano de diagnóstico, nunca a senha em si.
    assert isinstance(enviado["senha_disponivel"], bool)
    assert isinstance(enviado["tem_chave_privada"], bool)


def test_referencia_local_e_opaca_e_nao_expoe_caminho_de_arquivo(tmp_path):
    (tmp_path / "cliente-super-secreto.pfx").write_bytes(b"x")
    achado = certificados.listar_arquivos(tmp_path)[0]
    assert str(tmp_path) not in achado.referencia_local
    assert achado.referencia_local == "arquivo:cliente-super-secreto.pfx"


def test_arquivo_pfx_entra_como_pendencia_e_nao_e_aberto(tmp_path):
    (tmp_path / "cliente.pfx").write_bytes(b"conteudo-binario-qualquer")
    achados = certificados.listar_arquivos(tmp_path)
    assert len(achados) == 1
    assert achados[0].origem == "arquivo"
    assert not achados[0].senha_disponivel
    assert "importe" in achados[0].erro.lower()


def test_vigencia_considera_a_data_de_expiracao():
    futuro = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    passado = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    assert certificados.vigente(certificados.CertificadoLocal("a", valido_ate=futuro))
    assert not certificados.vigente(certificados.CertificadoLocal("a", valido_ate=passado))
    assert not certificados.vigente(certificados.CertificadoLocal("a"))


# ---------------------------------------------------------------------------
# Assinador
# ---------------------------------------------------------------------------


def test_diagnostico_fora_do_windows_nao_mente(monkeypatch):
    monkeypatch.setattr(assinador.platform, "system", lambda: "Linux")
    monkeypatch.setattr(assinador, "_porta_aberta", lambda **_: False)
    resultado = assinador.diagnosticar()
    assert not resultado.instalado
    assert not resultado.porta_local
    assert any("Windows" in obs for obs in resultado.observacoes)


def test_diagnostico_reporta_porta_fechada(monkeypatch):
    monkeypatch.setattr(assinador.platform, "system", lambda: "Windows")
    monkeypatch.setattr(assinador, "_instalado", lambda: (True, "4.3.3"))
    monkeypatch.setattr(assinador, "_processo_em_execucao", lambda: (True, "4.3.3"))
    monkeypatch.setattr(assinador, "_hosts_mapeado", lambda: True)
    monkeypatch.setattr(assinador, "_porta_aberta", lambda **_: False)
    resultado = assinador.diagnosticar(tem_certificado=True)
    assert resultado.instalado and resultado.em_execucao
    assert not resultado.porta_local
    assert not resultado.permissao_navegador
    assert any("65156" in obs for obs in resultado.observacoes)


# ---------------------------------------------------------------------------
# Roteiro
# ---------------------------------------------------------------------------


def test_so_abre_dominio_oficial(monkeypatch):
    abertas: list[str] = []
    monkeypatch.setattr(roteiro.webbrowser, "open", lambda url, new=0: abertas.append(url) or True)
    assert roteiro.abrir_navegador("https://servicos.receitafederal.gov.br/x")
    assert not roteiro.abrir_navegador("https://servicos.receitafederal.gov.br.evil.com")
    assert not roteiro.abrir_navegador("http://servicos.receitafederal.gov.br")
    assert not roteiro.abrir_navegador("https://intranet.local/portal")
    assert abertas == ["https://servicos.receitafederal.gov.br/x"]


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class _ClienteFalso:
    def __init__(self, ordens=None, assinador_apto=True):
        self.ordens = ordens or []
        self.assinador_apto = assinador_apto
        self.chamadas: list[tuple] = []

    def enviar_inventario(self, itens):
        self.chamadas.append(("inventario", len(itens)))
        return {}

    def heartbeat(self, payload):
        self.chamadas.append(("heartbeat", payload))
        return {"assinador_apto": self.assinador_apto, "assinador_detalhe": "sem assinador"}

    def reivindicar(self, capacidade):
        self.chamadas.append(("reivindicar", capacidade))
        entrega, self.ordens = self.ordens, []
        return {"ordens": entrega, "intervalo_busca_segundos": 1}

    def progresso(self, job_id, lease, etapa, **kwargs):
        self.chamadas.append(("progresso", etapa))
        return {}

    def renovar_lease(self, job_id, lease):
        self.chamadas.append(("lease", job_id))
        return {}

    def resultado(self, job_id, lease, **campos):
        self.chamadas.append(("resultado", campos))
        return {"status": "aguardando_validacao"}

    def portal_alterado(self, job_id, lease, etapa, ausentes, url):
        self.chamadas.append(("portal_alterado", etapa, tuple(ausentes)))
        return {}

    def encerrar_sessao(self):
        self.chamadas.append(("encerrar", None))


class _ConducaoFalsa:
    def __init__(self, respostas, protocolo="PROT-1", confirmacao="Em Análise"):
        self._respostas = list(respostas)
        self._protocolo = protocolo
        self._confirmacao = confirmacao
        self.avisos: list[str] = []

    def cabecalho(self, ordem):
        pass

    def conduzir_etapa(self, passo, indice, total):
        return self._respostas.pop(0) if self._respostas else roteiro.RespostaEtapa(True)

    def pedir_confirmacao_final(self, fase):
        return self._protocolo, self._confirmacao

    def avisar(self, mensagem):
        self.avisos.append(mensagem)


ORDEM = {
    "job_id": 7,
    "lease_token": "lease-1",
    "fase": "outorga",
    "empresa_nome": "CLIENTE LTDA",
    "empresa_documento": "12345678000195",
    "outorgado_nome": "CONTABILIDADE",
    "outorgado_documento": "11222333000181",
    "certificado_thumbprint": "a" * 64,
    "roteiro": [
        {"etapa": "pre_requisitos", "titulo": "Checar", "executor": "sistema", "url": ""},
        {"etapa": "acesso_portal", "titulo": "Entrar", "executor": "operador", "url": ""},
        {"etapa": "assinatura", "titulo": "Assinar", "executor": "operador", "url": ""},
    ],
}


def _agente(cliente, conducao):
    return Agente(Configuracao(servidor_url="https://x", identificador="e1"), cliente, conducao=conducao)


def test_ordem_conduzida_ate_o_registro(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    cliente = _ClienteFalso()
    conducao = _ConducaoFalsa([])
    _agente(cliente, conducao).executar_ordem(ORDEM)

    etapas = [c[1] for c in cliente.chamadas if c[0] == "progresso"]
    assert etapas == ["acesso_portal", "assinatura"], "etapa do sistema não gera progresso"
    resultado = next(c[1] for c in cliente.chamadas if c[0] == "resultado")
    assert resultado["resultado"] == "outorga_registrada"
    assert resultado["protocolo"] == "PROT-1"


def test_sem_confirmacao_o_job_nao_e_concluido(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    cliente = _ClienteFalso()
    conducao = _ConducaoFalsa([], protocolo="", confirmacao="")
    _agente(cliente, conducao).executar_ordem(ORDEM)
    resultado = next(c[1] for c in cliente.chamadas if c[0] == "resultado")
    assert resultado["resultado"] == "intervencao"
    assert resultado["codigo_erro"] == "CONFIRMACAO_AUSENTE"


def test_item_ausente_na_tela_vira_portal_alterado(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    cliente = _ClienteFalso()
    conducao = _ConducaoFalsa(
        [
            roteiro.RespostaEtapa(True),
            roteiro.RespostaEtapa(False, portal_alterado=True, texto="Nova Autorização"),
        ]
    )
    _agente(cliente, conducao).executar_ordem(ORDEM)
    aviso = next(c for c in cliente.chamadas if c[0] == "portal_alterado")
    assert aviso[1] == "acesso_portal"
    assert aviso[2] == ("Nova Autorização",)
    assert not any(c[0] == "resultado" for c in cliente.chamadas), "nada é concluído às cegas"


def test_desafio_de_seguranca_vira_intervencao(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    cliente = _ClienteFalso()
    conducao = _ConducaoFalsa(
        [roteiro.RespostaEtapa(False, intervencao=True, texto="Apareceu um captcha")]
    )
    _agente(cliente, conducao).executar_ordem(ORDEM)
    resultado = next(c[1] for c in cliente.chamadas if c[0] == "resultado")
    assert resultado["codigo_erro"] == "DESAFIO_DE_SEGURANCA"
    assert "captcha" in resultado["mensagem"].lower()


def test_sem_assinador_o_agent_nao_pede_trabalho(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    monkeypatch.setattr(
        "cajuru_agent.executor.diag_assinador.diagnosticar",
        lambda **_: assinador.Diagnostico(),
    )
    cliente = _ClienteFalso(assinador_apto=False)
    agente = _agente(cliente, _ConducaoFalsa([]))
    agente.config.intervalo_heartbeat_segundos = 1
    agente.rodar(ciclos=1)
    assert not any(c[0] == "reivindicar" for c in cliente.chamadas)


def test_erro_permanente_encerra_com_codigo_de_saida(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    monkeypatch.setattr(
        "cajuru_agent.executor.diag_assinador.diagnosticar",
        lambda **_: assinador.Diagnostico(),
    )

    class _Explode(_ClienteFalso):
        def heartbeat(self, payload):
            raise ProtocoloError("credencial revogada", status=403)

    agente = _agente(_Explode(), _ConducaoFalsa([]))
    assert agente.rodar(ciclos=1) == 2
