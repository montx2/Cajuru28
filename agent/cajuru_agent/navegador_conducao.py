"""
Condução automática pelo navegador — o "ajudante local" do escritório.

Este módulo é o coração da automação assistida pedida pelo escritório. Ele
implementa exatamente a mesma interface de :class:`~cajuru_agent.roteiro.ConducaoConsole`
(``cabecalho``, ``conduzir_etapa``, ``pedir_confirmacao_final``, ``avisar`` e,
agora, ``finalizar_ordem``), de modo que o :class:`~cajuru_agent.executor.Agente`
não precisa saber se está falando com uma pessoa no terminal ou com o navegador.

O que ele faz, na ordem e com o cuidado que o negócio exige:

1. **entra com o certificado do cliente automaticamente** — antes de abrir o
   portal, garante a política ``AutoSelectCertificateForUrls`` do navegador para
   o documento/thumbprint daquele job, para o Chrome/Edge escolher o A1 certo
   sem abrir o seletor;
2. **vai clicando nos caminhos certos** — as etapas marcadas como ``sistema``
   (navegação) são percorridas sozinhas; as etapas do ``operador`` (o ato de
   outorga em si) **nunca** são clicadas pelo ajudante: quem pratica o ato é a
   pessoa, com o certificado dela, no ambiente oficial (IN RFB nº 2.320/2026,
   art. 13);
3. **recarrega a página só quando o portal acusa automação** — "detectamos um
   acesso automatizado", desafios anti-robô de WAF (Cloudflare/Incapsula/etc.).
   CAPTCHA, 2FA, PIN e seletor de certificado **não** provocam recarga: são
   entregues à pessoa resolver (a recarga não some com um CAPTCHA legítimo);
4. **depois que a pessoa autoriza, limpa os cookies e vai para o próximo** —
   ``finalizar_ordem`` zera os cookies da sessão para o próximo cliente começar
   com o portal limpo, sem herdar login nem estado do cliente anterior.

Toda a lógica de decisão vive em funções puras e testáveis (``avaliar_pagina``,
``automacao_detectada``). A parte específica do Playwright fica isolada num
adaptador (:class:`PlaywrightPaginaSync`) que apenas empresta primitivos ao
motor; assim o comportamento é verificável sem abrir um navegador de verdade.
"""

from __future__ import annotations

import enum
import logging
import platform
import re
import time
from dataclasses import dataclass
from typing import Callable, Protocol, Sequence, runtime_checkable

from . import human_gate
from .roteiro import RespostaEtapa, url_permitida

log = logging.getLogger("cajuru.agent.navegador")


# ---------------------------------------------------------------------------
# 1. Detecção de bloqueio por automação (o ÚNICO gatilho de recarga)
# ---------------------------------------------------------------------------

#: Sinais de que o portal/WAF barrou o acesso por suspeita de automação. São
#: propositalmente específicos: um CAPTCHA comum de login **não** entra aqui —
#: ele é gate humano, resolvido pela pessoa, e recarregar só o faria reaparecer.
_PADROES_AUTOMACAO: tuple[re.Pattern[str], ...] = (
    re.compile(r"automa[cç][aã]o\s+detectada", re.I),
    re.compile(r"acesso\s+automatizado", re.I),
    re.compile(r"comportamento\s+automatizado", re.I),
    re.compile(r"atividade\s+automatizada", re.I),
    re.compile(r"requisi[cç][oõ]es\s+automatizadas", re.I),
    re.compile(r"tr[aá]fego\s+incomum", re.I),
    re.compile(r"unusual\s+traffic", re.I),
    re.compile(r"automated\s+(access|traffic|requests|queries)", re.I),
    re.compile(r"\bbot\s+detect(ado|ed)\b", re.I),
    re.compile(r"(voc[eê]\s+foi|foi)\s+bloquead", re.I),
    re.compile(r"you\s+have\s+been\s+blocked", re.I),
    re.compile(r"request\s+unsuccessful", re.I),  # Incapsula/Imperva
    re.compile(r"incapsula\s+incident", re.I),
    re.compile(r"checking\s+your\s+browser", re.I),  # Cloudflare
    re.compile(r"attention\s+required", re.I),  # Cloudflare
    re.compile(r"perimeterx|px-captcha", re.I),
    re.compile(r"acesso\s+negado.*rob[oô]", re.I | re.S),
)


def automacao_detectada(texto: str) -> bool:
    """Verdadeiro só quando a página acusa bloqueio por automação/robô."""
    conteudo = texto or ""
    return any(padrao.search(conteudo) for padrao in _PADROES_AUTOMACAO)


# ---------------------------------------------------------------------------
# 2. Avaliação pura de uma página observada
# ---------------------------------------------------------------------------


class Acao(str, enum.Enum):
    SEGUIR = "seguir"
    RECARREGAR = "recarregar"
    INTERVIR = "intervir"
    PORTAL_ALTERADO = "portal_alterado"


@dataclass(frozen=True)
class Decisao:
    acao: Acao
    codigo: str = ""
    detalhe: str = ""


def avaliar_pagina(texto: str, ancoras_esperadas: Sequence[str] = ()) -> Decisao:
    """Decide o que fazer diante do texto visível de uma página.

    Ordem de prioridade (importa muito):

    1. **automação detectada** → recarregar (único gatilho de recarga);
    2. **gate humano** (CAPTCHA/2FA/PIN/seletor de certificado) → intervir,
       sem recarregar;
    3. **âncoras esperadas ausentes** → portal alterado (não clicar às cegas);
    4. caso contrário → seguir.
    """
    conteudo = texto or ""

    if automacao_detectada(conteudo):
        return Decisao(Acao.RECARREGAR, codigo="AUTOMACAO_DETECTADA",
                       detalhe="Portal acusou acesso automatizado.")

    gate = human_gate.detectar_gate(conteudo)
    if gate is not None:
        return Decisao(Acao.INTERVIR, codigo=gate.codigo_erro, detalhe=gate.mensagem)

    ausentes = [a for a in ancoras_esperadas if a and a.lower() not in conteudo.lower()]
    if ancoras_esperadas and ausentes:
        return Decisao(Acao.PORTAL_ALTERADO, codigo="PORTAL_ALTERADO",
                       detalhe="; ".join(ausentes))

    return Decisao(Acao.SEGUIR)


# ---------------------------------------------------------------------------
# 3. Contrato mínimo de página (implementado pelo Playwright em produção)
# ---------------------------------------------------------------------------


@runtime_checkable
class PaginaControlada(Protocol):
    """O que a condução precisa de um navegador — nada além disso."""

    def abrir(self, url: str) -> None: ...
    def url_atual(self) -> str: ...
    def texto_visivel(self) -> str: ...
    def recarregar(self) -> None: ...
    def clicar(self, alvo: str) -> bool: ...
    def esperar(self, ms: int) -> None: ...
    def limpar_cookies(self) -> None: ...
    def capturar_evidencia(self, etapa: str, prefixo: str) -> None: ...


# ---------------------------------------------------------------------------
# 4. Política padrão de seleção automática de certificado
# ---------------------------------------------------------------------------


def aplicar_politica_padrao(documento: str, thumbprint: str, *, navegador: str = "") -> str:
    """Garante o ``AutoSelectCertificateForUrls`` do documento no navegador.

    No Windows aplica no HKCU (idempotente, sem apagar regras existentes). Fora
    do Windows apenas descreve o que seria feito — é ambiente de desenvolvimento.
    Falha fechado: se houver ambiguidade de certificado, devolve o aviso e não
    inventa uma seleção.
    """
    from . import politicas_navegador as pol

    alvo = (navegador or "edge").lower()
    try:
        certificado, politicas = pol.gerar_para_documento(
            documento, navegadores=(alvo,), thumbprint=thumbprint or ""
        )
    except pol.PoliticaNavegadorError as exc:
        return f"seleção automática não configurada: {exc}"

    if platform.system() != "Windows":
        return (
            f"(dev) política pronta para {certificado.titular_nome or documento}; "
            "no Windows ela seria aplicada automaticamente."
        )
    aplicadas = 0
    for politica in politicas:
        try:
            aplicadas += pol.aplicar_politica(
                politica,
                substituir_padroes=True,
            ).adicionadas
        except pol.PoliticaNavegadorError as exc:  # pragma: no cover - específico do SO
            return f"não foi possível aplicar a política: {exc}"
    return f"certificado de {certificado.titular_nome or documento} selecionado automaticamente ({aplicadas} regra(s) nova(s))"


# ---------------------------------------------------------------------------
# 5. Extração da confirmação real do portal (nada de "cliquei, logo assinei")
# ---------------------------------------------------------------------------

_RE_PROTOCOLO = re.compile(
    r"(?:protocolo|n[ºo°]\.?\s*(?:do)?\s*protocolo)[:\s]*([0-9][0-9.\-/]{6,})",
    re.I,
)
_RE_PROTOCOLO_SOLTO = re.compile(r"\b(\d{4}\.\d{6,})\b")
_RE_SITUACAO = re.compile(
    r"situa[cç][aã]o|em an[aá]lise|autoriza[cç][aã]o\s+(?:registrada|validada)|\bativa\b|deferid|indeferid",
    re.I,
)


def extrair_protocolo(texto: str) -> str:
    conteudo = texto or ""
    achado = _RE_PROTOCOLO.search(conteudo) or _RE_PROTOCOLO_SOLTO.search(conteudo)
    return achado.group(1).strip() if achado else ""


def extrair_confirmacao(texto: str) -> str:
    """Junta os trechos da tela que descrevem a situação da autorização."""
    conteudo = texto or ""
    segmentos = [s.strip() for s in re.split(r"[.\n\r]+", conteudo)]
    achados = [s for s in segmentos if s and _RE_SITUACAO.search(s)]
    return (" · ".join(achados))[:280]


# ---------------------------------------------------------------------------
# 6. A condução por navegador
# ---------------------------------------------------------------------------


class ConducaoNavegador:
    """Conduz um job pelo navegador, respeitando o limite legal do ato humano."""

    def __init__(
        self,
        pagina: PaginaControlada,
        *,
        navegador: str = "",
        max_recargas: int = 3,
        espera_recarga_ms: int = 2_000,
        espera_humano_ms: int = 15 * 60 * 1_000,
        intervalo_espera_ms: int = 1_000,
        aplicar_politica: Callable[..., str] | None = None,
        relogio: Callable[[], float] = time.monotonic,
        esperar_gates: bool = False,
    ):
        self.pagina = pagina
        self.navegador = navegador
        self.max_recargas = max(0, int(max_recargas))
        self.espera_recarga_ms = int(espera_recarga_ms)
        self.espera_humano_ms = int(espera_humano_ms)
        self.intervalo_espera_ms = max(1, int(intervalo_espera_ms))
        self._aplicar_politica = aplicar_politica or aplicar_politica_padrao
        self._relogio = relogio
        # O modo de produção fica aguardando na mesma janela quando o portal
        # mostra hCaptcha/2FA/PIN. Assim o operador resolve a proteção oficial
        # e o fluxo continua sem perder a sessão nem precisar clicar em
        # "Retomar" no painel. O padrão falso mantém o contrato síncrono dos
        # testes e do modo console.
        self.esperar_gates = bool(esperar_gates)

    # -- apresentação / preparação ----------------------------------------

    def cabecalho(self, ordem: dict) -> None:
        fase = str(ordem.get("fase") or "outorga")
        documento, titulo = self._alvo_do_certificado(ordem, fase)
        self.avisar(
            f"Job #{ordem.get('job_id')} · {'OUTORGA (certificado do cliente)' if fase == 'outorga' else 'ACEITE (certificado da contabilidade)'}"
        )
        self.avisar(f"Empresa: {ordem.get('empresa_nome')} ({ordem.get('empresa_documento')})")
        if documento:
            try:
                mensagem = self._aplicar_politica(
                    documento, str(ordem.get("certificado_thumbprint") or ""), navegador=self.navegador
                )
                self.avisar(f"Certificado: {mensagem}")
                # Edge/Chrome carregam a política somente ao iniciar. O
                # adaptador Playwright real expõe `reiniciar`; páginas falsas e
                # a condução de testes não precisam implementá-lo.
                reiniciar = getattr(self.pagina, "reiniciar", None)
                if (
                    callable(reiniciar)
                    and "indisponível" not in mensagem.lower()
                    and "não configurada" not in mensagem.lower()
                    and "não foi possível" not in mensagem.lower()
                ):
                    reiniciar()
            except Exception as exc:  # noqa: BLE001 - preparação nunca derruba o job
                log.warning("politica_certificado_falhou: %s", exc)
                self.avisar(f"Certificado: seleção automática indisponível ({exc}).")
        self.avisar(
            "O ajudante abre e navega o portal por você; o ato de autorizar e "
            "qualquer CAPTCHA/assinatura são sempre seus, na página oficial."
        )

    @staticmethod
    def _alvo_do_certificado(ordem: dict, fase: str) -> tuple[str, str]:
        # Na outorga entra-se com o certificado do CLIENTE; no aceite, com o da
        # contabilidade (outorgado). O backend já resolve isso em
        # ``certificado_documento``; usamos o fallback só por robustez.
        documento = str(ordem.get("certificado_documento") or "")
        if not documento:
            documento = str(
                ordem.get("empresa_documento") if fase == "outorga" else ordem.get("outorgado_documento") or ""
            )
        titulo = str(ordem.get("certificado_titular") or "")
        return documento, titulo

    # -- condução de uma etapa --------------------------------------------

    def conduzir_etapa(self, passo: dict, indice: int, total: int) -> RespostaEtapa:
        self.avisar(f"[{indice}/{total}] {passo.get('titulo')}")

        url = str(passo.get("url") or "")
        if url:
            if not url_permitida(url):
                return RespostaEtapa(
                    confirmada=False,
                    intervencao=True,
                    texto=f"URL fora da allowlist oficial recusada: {url}",
                )
            self.pagina.abrir(url)

        ancoras = [str(a) for a in (passo.get("ancoras") or []) if a]
        decisao = self._estabilizar(passo, ancoras)
        if decisao.acao is Acao.INTERVIR:
            return RespostaEtapa(confirmada=False, intervencao=True, texto=decisao.detalhe or decisao.codigo)
        if decisao.acao is Acao.PORTAL_ALTERADO:
            return RespostaEtapa(confirmada=False, portal_alterado=True, texto=decisao.detalhe)

        if str(passo.get("executor")) == "sistema":
            alvo = passo.get("acao") or passo.get("alvo")
            if alvo:
                if not self.pagina.clicar(str(alvo)):
                    # Não achar o caminho é sinal de portal mudado, não de erro
                    # transitório: interromper é mais seguro que improvisar.
                    self.pagina.capturar_evidencia(str(passo.get("etapa") or ""), "portal-alterado")
                    return RespostaEtapa(confirmada=False, portal_alterado=True, texto=str(alvo))
            return RespostaEtapa(confirmada=True)

        # Etapa do operador: o ATO é humano. O ajudante espera a conclusão
        # observável (a âncora de conclusão do passo), tratando automação/gate
        # que apareça durante a espera.
        return self._aguardar_humano(passo)

    def _estabilizar(self, passo: dict, ancoras: Sequence[str]) -> Decisao:
        """Resolve bloqueios transitórios sem clicar às cegas.

        Recarregar é reservado ao bloqueio que declara automação. CAPTCHA,
        2FA, PIN e seletor de certificado são gates legítimos: no modo de
        navegador aguardamos o operador resolvê-los na própria página; no modo
        console/compatibilidade devolvemos a intervenção como antes.
        """
        recargas = 0
        # Não consuma o relógio no modo compatibilidade: além de ser
        # desnecessário sem espera de gates, isso mantém a condução de console
        # determinística para chamadas que fornecem um relógio de teste.
        inicio_gate = self._relogio() if self.esperar_gates else 0.0
        avisou_gate = False
        while True:
            decisao = avaliar_pagina(self.pagina.texto_visivel(), ancoras)
            if decisao.acao is not Acao.RECARREGAR:
                if decisao.acao is Acao.INTERVIR and self.esperar_gates and decisao.codigo in {
                    "CAPTCHA_REQUIRED",
                    "TWO_FACTOR_REQUIRED",
                    "PIN_REQUIRED",
                    "CERTIFICATE_SELECTION_REQUIRED",
                }:
                    if not avisou_gate:
                        self.avisar(
                            f"{decisao.detalhe} Resolva na janela oficial; "
                            "o Agent aguardará sem recarregar."
                        )
                        avisou_gate = True
                    if (self._relogio() - inicio_gate) >= self.espera_humano_ms / 1_000:
                        return Decisao(
                            Acao.INTERVIR,
                            codigo=decisao.codigo,
                            detalhe="O desafio oficial não foi resolvido dentro do prazo.",
                        )
                    self.pagina.esperar(self.intervalo_espera_ms)
                    continue
                return decisao
            if recargas >= self.max_recargas:
                return Decisao(
                    Acao.INTERVIR,
                    codigo="AUTOMACAO_PERSISTENTE",
                    detalhe=(
                        "O portal seguiu acusando automação depois de "
                        f"{recargas} recarga(s). Resolva na página e retome."
                    ),
                )
            recargas += 1
            self.avisar(f"Portal acusou automação; recarregando ({recargas}/{self.max_recargas})…")
            self.pagina.capturar_evidencia(str(passo.get("etapa") or ""), "automacao-detectada")
            self.pagina.recarregar()
            self.pagina.esperar(self.espera_recarga_ms)
            inicio_gate = self._relogio() if self.esperar_gates else 0.0
            avisou_gate = False

    def _aguardar_humano(self, passo: dict) -> RespostaEtapa:
        # `confirmacao` é a orientação mostrada ao operador (por exemplo,
        # "confira o CNPJ"), não uma string que necessariamente exista no DOM.
        # O executor injeta a âncora da próxima tela; no último ato, pede uma
        # mudança observável de página antes de coletar o protocolo.
        conclusao = str(passo.get("ancora_conclusao") or "")
        aguardar_mudanca = bool(passo.get("aguardar_mudanca"))
        inicio = self._relogio()
        limite_s = self.espera_humano_ms / 1_000
        texto_inicial = ""
        while True:
            decisao = self._estabilizar(passo, ())
            if decisao.acao is Acao.INTERVIR:
                return RespostaEtapa(confirmada=False, intervencao=True, texto=decisao.detalhe or decisao.codigo)

            if not conclusao and not aguardar_mudanca:
                # Sem observação declarada, a prova obrigatória continua sendo
                # o protocolo/confirmação coletado no fim da fase.
                return RespostaEtapa(confirmada=True)

            texto_atual = self.pagina.texto_visivel() or ""
            if conclusao and conclusao.lower() in texto_atual.lower():
                return RespostaEtapa(confirmada=True)
            if aguardar_mudanca:
                if extrair_protocolo(texto_atual) or extrair_confirmacao(texto_atual):
                    return RespostaEtapa(confirmada=True)
                if not texto_inicial:
                    texto_inicial = texto_atual
                elif texto_atual != texto_inicial:
                    return RespostaEtapa(confirmada=True)

            if (self._relogio() - inicio) >= limite_s:
                return RespostaEtapa(
                    confirmada=False,
                    intervencao=True,
                    texto="A confirmação da ação não apareceu na página dentro do prazo.",
                )
            self.pagina.esperar(self.intervalo_espera_ms)

    # -- registro final e limpeza -----------------------------------------

    def pedir_confirmacao_final(self, fase: str) -> tuple[str, str]:
        """Lê a prova real do portal: protocolo e/ou frase de situação.

        Se nada verificável for encontrado, devolve vazio de propósito — o
        executor então marca ``CONFIRMACAO_AUSENTE`` e o job não é dado como
        concluído. É a regra que impede registrar como assinado o que não foi.
        """
        texto = self.pagina.texto_visivel()
        protocolo = extrair_protocolo(texto)
        confirmacao = extrair_confirmacao(texto)
        if protocolo or confirmacao:
            self.avisar(f"Confirmação lida do portal: protocolo={protocolo or '—'} · {confirmacao or 'sem frase de situação'}")
        else:
            self.avisar("Nenhuma confirmação verificável na tela; o job aguardará registro manual.")
        return protocolo, confirmacao

    def finalizar_ordem(self) -> None:
        """Depois que a pessoa autoriza: limpa os cookies e libera o próximo."""
        try:
            self.pagina.limpar_cookies()
            self.avisar("Cookies da sessão limpos — pronto para o próximo cliente.")
        except Exception as exc:  # noqa: BLE001 - limpeza não pode derrubar o laço
            log.warning("limpeza_cookies_falhou: %s", exc)
            self.avisar(f"Não foi possível limpar os cookies automaticamente: {exc}")

    # -- utilidades --------------------------------------------------------

    def avisar(self, mensagem: str) -> None:
        log.info("conducao: %s", mensagem)
        print(f"  → {mensagem}")
