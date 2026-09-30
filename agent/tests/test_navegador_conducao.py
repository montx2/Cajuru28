"""
Testes do ajudante local por navegador.

O que se garante aqui é o contrato do que o escritório pediu:

* recarregar **apenas** quando o portal acusa automação — nunca por CAPTCHA;
* percorrer os caminhos de navegação, mas **nunca** praticar o ato de outorga;
* entrar com o certificado do cliente (política aplicada no início do job);
* depois da autorização, limpar os cookies e liberar o próximo cliente;
* nunca dar um job como concluído sem confirmação real do portal.

Tudo roda sem abrir navegador: uma página falsa empresta os primitivos.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cajuru_agent import navegador_conducao as nc  # noqa: E402
from cajuru_agent.config import Configuracao  # noqa: E402
from cajuru_agent.executor import Agente  # noqa: E402
from cajuru_agent.navegador_conducao import Acao, ConducaoNavegador, avaliar_pagina  # noqa: E402


# ---------------------------------------------------------------------------
# Página falsa
# ---------------------------------------------------------------------------


class PaginaFalsa:
    def __init__(self, textos):
        # `textos` é consumido em ordem; o último valor se repete.
        self._textos = list(textos) or [""]
        self.abertas: list[str] = []
        self.recargas = 0
        self.cliques: list[str] = []
        self.cookies_limpos = 0
        self.evidencias: list[tuple[str, str]] = []
        self.esperas = 0
        self.clique_ok = True

    def abrir(self, url):
        self.abertas.append(url)

    def url_atual(self):
        return self.abertas[-1] if self.abertas else ""

    def texto_visivel(self):
        if len(self._textos) > 1:
            return self._textos.pop(0)
        return self._textos[0]

    def recarregar(self):
        self.recargas += 1

    def clicar(self, alvo):
        self.cliques.append(alvo)
        return self.clique_ok

    def esperar(self, ms):
        self.esperas += 1

    def limpar_cookies(self):
        self.cookies_limpos += 1

    def capturar_evidencia(self, etapa, prefixo):
        self.evidencias.append((etapa, prefixo))


def _conducao(pagina, **kwargs):
    kwargs.setdefault("aplicar_politica", lambda *a, **k: "ok")
    return ConducaoNavegador(pagina, **kwargs)


# ---------------------------------------------------------------------------
# Detecção de automação e avaliação de página
# ---------------------------------------------------------------------------


def test_automacao_detectada_reconhece_bloqueios_conhecidos():
    for texto in [
        "Detectamos um acesso automatizado a partir do seu computador.",
        "Automação detectada. Tente novamente.",
        "Request unsuccessful. Incapsula incident ID 123",
        "Checking your browser before accessing",
        "We have detected unusual traffic from your network",
        "You have been blocked",
    ]:
        assert nc.automacao_detectada(texto), texto


def test_captcha_puro_nao_e_tratado_como_automacao():
    # CAPTCHA de login é gate humano — recarregar só o faria reaparecer.
    assert not nc.automacao_detectada("Confirme que você não é um robô resolvendo o CAPTCHA abaixo.")
    assert not nc.automacao_detectada("Digite o código de verificação enviado por SMS.")


def test_avaliacao_da_pagina_segue_a_ordem_de_prioridade():
    assert avaliar_pagina("acesso automatizado detectado").acao is Acao.RECARREGAR
    # CAPTCHA -> intervir, jamais recarregar
    d = avaliar_pagina("resolva o captcha para continuar")
    assert d.acao is Acao.INTERVIR and d.codigo == "CAPTCHA_REQUIRED"
    # âncora ausente -> portal alterado
    assert avaliar_pagina("tela qualquer", ["Nova Autorização"]).acao is Acao.PORTAL_ALTERADO
    # tudo certo -> seguir
    assert avaliar_pagina("Nova Autorização disponível", ["Nova Autorização"]).acao is Acao.SEGUIR


# ---------------------------------------------------------------------------
# Recarga só em automação
# ---------------------------------------------------------------------------


def test_recarrega_uma_vez_quando_automacao_some_depois():
    pagina = PaginaFalsa(["acesso automatizado detectado", "Portal de Serviços — Nova Autorização"])
    passo = {"etapa": "acesso_portal", "executor": "sistema", "titulo": "Entrar"}
    resposta = _conducao(pagina).conduzir_etapa(passo, 1, 1)
    assert resposta.confirmada
    assert pagina.recargas == 1
    assert pagina.evidencias  # capturou evidência da automação


def test_captcha_pausa_sem_recarregar():
    pagina = PaginaFalsa(["Resolva o captcha para prosseguir"])
    passo = {"etapa": "acesso_portal", "executor": "sistema", "titulo": "Entrar"}
    resposta = _conducao(pagina).conduzir_etapa(passo, 1, 1)
    assert resposta.intervencao
    assert pagina.recargas == 0, "CAPTCHA nunca recarrega a página"


def test_modo_navegador_aguarda_gate_na_mesma_sessao():
    pagina = PaginaFalsa(["Resolva o captcha para prosseguir", "Portal pronto"])
    conducao = _conducao(
        pagina,
        esperar_gates=True,
        relogio=lambda: 0,
    )
    passo = {
        "etapa": "acesso_portal",
        "executor": "operador",
        "titulo": "Entrar",
        "confirmacao": "Portal pronto",
    }
    resposta = conducao.conduzir_etapa(passo, 1, 1)
    assert resposta.confirmada
    assert pagina.recargas == 0
    assert pagina.esperas == 1


def test_automacao_persistente_escala_para_intervencao_apos_o_teto():
    pagina = PaginaFalsa(["comportamento automatizado detectado"])
    passo = {"etapa": "acesso_portal", "executor": "sistema", "titulo": "Entrar"}
    resposta = _conducao(pagina, max_recargas=3).conduzir_etapa(passo, 1, 1)
    assert resposta.intervencao
    assert "AUTOMACAO_PERSISTENTE" in resposta.texto or "automação" in resposta.texto.lower()
    assert pagina.recargas == 3, "recarrega até o teto e então entrega ao humano"


# ---------------------------------------------------------------------------
# Caminhos de navegação x ato humano
# ---------------------------------------------------------------------------


def test_etapa_de_sistema_clica_o_caminho():
    pagina = PaginaFalsa(["Portal de Serviços"])
    passo = {"etapa": "menu", "executor": "sistema", "titulo": "Abrir menu", "acao": "Procurações"}
    resposta = _conducao(pagina).conduzir_etapa(passo, 1, 3)
    assert resposta.confirmada
    assert pagina.cliques == ["Procuracoes".replace("c", "ç") if False else "Procurações"]


def test_caminho_inexistente_vira_portal_alterado():
    pagina = PaginaFalsa(["Portal de Serviços"])
    pagina.clique_ok = False
    passo = {"etapa": "menu", "executor": "sistema", "titulo": "Abrir", "acao": "Botão que sumiu"}
    resposta = _conducao(pagina).conduzir_etapa(passo, 1, 1)
    assert resposta.portal_alterado


def test_etapa_do_operador_espera_a_conclusao_e_nao_clica_o_ato():
    pagina = PaginaFalsa(["Preencha e assine", "Autorização registrada. Situação: Em Análise."])
    passo = {
        "etapa": "assinatura",
        "executor": "operador",
        "titulo": "Assinar",
        "confirmacao": "Autorização registrada",
        "ancora_conclusao": "Autorização registrada",
    }
    resposta = _conducao(pagina).conduzir_etapa(passo, 2, 2)
    assert resposta.confirmada
    assert pagina.cliques == [], "o ajudante nunca clica no ato de outorga"


def test_etapa_do_operador_com_gate_vira_intervencao():
    pagina = PaginaFalsa(["Autenticação em duas etapas necessária para continuar"])
    passo = {"etapa": "acesso", "executor": "operador", "titulo": "Login", "confirmacao": "Bem-vindo"}
    resposta = _conducao(pagina).conduzir_etapa(passo, 1, 2)
    assert resposta.intervencao
    assert pagina.recargas == 0


def test_etapa_do_operador_estoura_prazo_sem_conclusao():
    pagina = PaginaFalsa(["ainda preenchendo"])
    passo = {
        "etapa": "assinatura",
        "executor": "operador",
        "titulo": "Assinar",
        "confirmacao": "Situação: Ativa",
        "aguardar_mudanca": True,
    }
    tempos = iter([0, 0, 999])  # inicio, checagem1 (<prazo), checagem2 (estoura)
    conducao = _conducao(pagina, espera_humano_ms=2_000, relogio=lambda: next(tempos))
    resposta = conducao.conduzir_etapa(passo, 1, 1)
    assert resposta.intervencao
    assert "prazo" in resposta.texto.lower()


# ---------------------------------------------------------------------------
# Certificado automático e limpeza entre clientes
# ---------------------------------------------------------------------------


def test_cabecalho_aplica_politica_do_certificado_do_cliente_na_outorga():
    chamadas = []
    pagina = PaginaFalsa([""])
    conducao = ConducaoNavegador(
        pagina,
        navegador="edge",
        aplicar_politica=lambda doc, thumb, navegador="": chamadas.append((doc, thumb, navegador)) or "ok",
    )
    conducao.cabecalho(
        {
            "job_id": 1,
            "fase": "outorga",
            "empresa_nome": "CLIENTE LTDA",
            "empresa_documento": "12345678000195",
            "certificado_documento": "12345678000195",
            "certificado_thumbprint": "a" * 64,
        }
    )
    assert chamadas == [("12345678000195", "a" * 64, "edge")]


def test_finalizar_ordem_limpa_os_cookies():
    pagina = PaginaFalsa([""])
    _conducao(pagina).finalizar_ordem()
    assert pagina.cookies_limpos == 1


# ---------------------------------------------------------------------------
# Confirmação real do portal
# ---------------------------------------------------------------------------


def test_extrai_protocolo_e_situacao_do_texto():
    texto = "Autorização registrada. Protocolo: 2026.0009887766 — Situação: Em Análise."
    assert nc.extrair_protocolo(texto) == "2026.0009887766"
    assert "Em Análise" in nc.extrair_confirmacao(texto)


def test_confirmacao_final_vazia_quando_nao_ha_prova():
    pagina = PaginaFalsa(["Tela inicial sem nada de protocolo"])
    protocolo, confirmacao = _conducao(pagina).pedir_confirmacao_final("outorga")
    assert protocolo == "" and confirmacao == ""


# ---------------------------------------------------------------------------
# Integração com o executor: limpa entre jobs
# ---------------------------------------------------------------------------


class _ClienteFalso:
    def __init__(self, ordens):
        self.ordens = ordens
        self.resultados: list[dict] = []

    def enviar_inventario(self, itens):
        return {}

    def heartbeat(self, payload):
        return {"assinador_apto": True}

    def reivindicar(self, capacidade):
        entrega, self.ordens = self.ordens, []
        return {"ordens": entrega, "intervalo_busca_segundos": 1}

    def progresso(self, *a, **k):
        return {}

    def renovar_lease(self, *a, **k):
        return {}

    def resultado(self, job_id, lease, **campos):
        self.resultados.append(campos)
        return {"status": "aguardando_validacao"}

    def portal_alterado(self, *a, **k):
        return {}

    def encerrar_sessao(self):
        return None


def test_executor_registra_com_a_prova_lida_e_limpa_entre_jobs(monkeypatch):
    monkeypatch.setattr("cajuru_agent.executor.inventario.inventariar", lambda *_: [])
    monkeypatch.setattr(
        "cajuru_agent.executor.diag_assinador.diagnosticar",
        lambda **_: type("D", (), {"observacoes": (), "para_envio": lambda self: {}})(),
    )
    pagina = PaginaFalsa(
        ["Portal de Serviços", "Autorização registrada. Protocolo: 2026.0001112223 — Situação: Em Análise."]
    )
    conducao = _conducao(pagina)
    ordem = {
        "job_id": 9,
        "lease_token": "l1",
        "fase": "outorga",
        "empresa_nome": "CLIENTE",
        "empresa_documento": "12345678000195",
        "certificado_documento": "12345678000195",
        "roteiro": [
            {"etapa": "acesso", "executor": "sistema", "titulo": "Abrir", "url": "https://servicos.receitafederal.gov.br/servico/autorizacoes"},
            {"etapa": "assinatura", "executor": "operador", "titulo": "Assinar", "confirmacao": "Autorização registrada"},
        ],
    }
    agente = Agente(Configuracao(servidor_url="https://x", identificador="e1"), _ClienteFalso([ordem]), conducao=conducao)
    agente.config.intervalo_busca_segundos = 1
    agente.rodar(ciclos=1)

    assert conducao.pagina.abertas == ["https://servicos.receitafederal.gov.br/servico/autorizacoes"]
    registrado = next(c for c in agente.cliente.resultados if c.get("resultado") == "outorga_registrada")
    assert registrado["protocolo"] == "2026.0001112223"
    assert pagina.cookies_limpos == 1, "cada job termina limpando os cookies"
