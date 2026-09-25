"""
Condução assistida da operação no Portal de Serviços da Receita Federal.

Esta é a peça que materializa a decisão central do módulo: **o ato é do
humano, o controle é do sistema**. O Agent não clica em "Nova Autorização",
não preenche o formulário e não aperta "Assinar" — a IN RFB nº 2.320/2026,
art. 13, veda camada de intermediação que automatize outorga, alteração ou
revogação de autorizações de acesso.

O que o Agent faz, e que é justamente o que economiza o tempo do escritório:

- abre o **navegador real do operador** na URL oficial (nada de webview, nada
  de iframe, nada de encapsular o ambiente da Receita);
- mostra, passo a passo, o que deve ser conferido e digitado, com os dados já
  resolvidos (CNPJ do outorgado, validade, serviços do modelo);
- exige confirmação explícita a cada etapa e registra tudo no servidor;
- ao receber "esse item não existe na tela", classifica como **portal
  alterado** e interrompe o job em vez de deixar o operador improvisar;
- ao receber "apareceu um desafio de segurança", classifica como intervenção
  manual, sem nunca tentar contornar.

A interface é de console de propósito: roda em qualquer estação Windows sem
instalar runtime gráfico, funciona por área de trabalho remota e deixa
transcrição legível no log.
"""

from __future__ import annotations

import logging
import sys
import webbrowser
from dataclasses import dataclass
from typing import Callable, Sequence

log = logging.getLogger("cajuru.agent.roteiro")

#: Hosts oficiais. O Agent recusa abrir qualquer outro endereço, mesmo que o
#: servidor mande — defesa em profundidade contra um backend comprometido.
DOMINIOS_PERMITIDOS = frozenset(
    {
        "servicos.receitafederal.gov.br",
        "cav.receita.fazenda.gov.br",
        "sso.acesso.gov.br",
        "www.gov.br",
        "gov.br",
        "assinatura.gov.br",
    }
)


class OperacaoCancelada(RuntimeError):
    """O operador interrompeu a condução."""


@dataclass
class RespostaEtapa:
    """O que o operador respondeu em uma etapa do roteiro."""

    confirmada: bool
    portal_alterado: bool = False
    intervencao: bool = False
    texto: str = ""


def url_permitida(url: str) -> bool:
    from urllib.parse import urlparse

    try:
        partes = urlparse(url)
    except ValueError:
        return False
    if partes.scheme != "https":
        return False
    host = (partes.hostname or "").lower()
    return host in DOMINIOS_PERMITIDOS


def abrir_navegador(url: str, *, navegador: str = "") -> bool:
    """Abre a URL oficial no navegador do operador.

    Recusa endereço fora da allowlist. Se o servidor mandasse um link de
    phishing, ele morreria aqui.
    """
    if not url_permitida(url):
        log.error("url_recusada", extra={"url": url})
        return False
    try:
        if navegador:
            return webbrowser.get(navegador).open(url, new=2)
        return webbrowser.open(url, new=2)
    except webbrowser.Error as exc:
        log.warning("navegador_indisponivel: %s", exc)
        return False


class ConducaoConsole:
    """Conduz o operador pelo roteiro, no terminal."""

    def __init__(
        self,
        *,
        entrada: Callable[[str], str] = input,
        saida=sys.stdout,
        navegador: str = "",
    ):
        self._perguntar = entrada
        self._saida = saida
        self._navegador = navegador

    # -- apresentação ------------------------------------------------------

    def _escrever(self, texto: str = "") -> None:
        print(texto, file=self._saida)

    def cabecalho(self, ordem: dict) -> None:
        fase = "OUTORGA (certificado do cliente)" if ordem.get("fase") == "outorga" else (
            "ACEITE (certificado da contabilidade)"
        )
        self._escrever()
        self._escrever("═" * 72)
        self._escrever(f"  JOB #{ordem['job_id']} · {fase}")
        self._escrever("═" * 72)
        self._escrever(f"  Empresa    : {ordem.get('empresa_nome')} ({ordem.get('empresa_documento')})")
        self._escrever(f"  Outorgado  : {ordem.get('outorgado_nome')} ({ordem.get('outorgado_documento')})")
        self._escrever(f"  Validade   : {ordem.get('vigencia_ate') or 'conforme modelo'}")
        escopo = ordem.get("escopo_servicos")
        servicos = ordem.get("servicos") or []
        if escopo == "ALL" or not servicos:
            self._escrever("  Serviços   : todos os serviços")
        else:
            nomes = ", ".join(str(s.get("rotulo") or s.get("codigo")) for s in servicos)
            self._escrever(f"  Serviços   : {nomes}")
        self._escrever(
            f"  Certificado: {ordem.get('certificado_titular') or ordem.get('certificado_documento')}"
        )
        self._escrever(f"               thumbprint {ordem.get('certificado_thumbprint', '')[:16]}…")
        self._escrever("─" * 72)
        self._escrever(
            "  Este assistente NÃO preenche nem assina nada por você. Ele abre a\n"
            "  página oficial, mostra o que conferir e registra o que você confirmar."
        )
        self._escrever("═" * 72)

    # -- condução ----------------------------------------------------------

    def conduzir_etapa(self, passo: dict, indice: int, total: int) -> RespostaEtapa:
        self._escrever()
        self._escrever(f"[{indice}/{total}] {passo.get('titulo')}")
        self._escrever("-" * 72)
        for linha in _quebrar(str(passo.get("instrucao") or ""), 70):
            self._escrever(f"  {linha}")
        if passo.get("url"):
            self._escrever()
            self._escrever(f"  Abrindo: {passo['url']}")
            if not abrir_navegador(str(passo["url"]), navegador=self._navegador):
                self._escrever("  !! Não foi possível abrir o navegador. Acesse o endereço acima.")
        if passo.get("confirmacao"):
            self._escrever()
            self._escrever(f"  Confirme: {passo['confirmacao']}")

        if str(passo.get("executor")) == "sistema":
            return RespostaEtapa(confirmada=True)

        self._escrever()
        self._escrever("  [c] confirmar e seguir   [n] item não existe na tela")
        self._escrever("  [d] apareceu desafio/erro de segurança   [x] parar por aqui")
        while True:
            escolha = (self._perguntar("  > ") or "").strip().lower()
            if escolha in {"c", "s", ""}:
                return RespostaEtapa(confirmada=True)
            if escolha == "n":
                faltando = (self._perguntar("  Qual texto você não encontrou? ") or "").strip()
                return RespostaEtapa(
                    confirmada=False, portal_alterado=True, texto=faltando or str(passo.get("titulo"))
                )
            if escolha == "d":
                detalhe = (self._perguntar("  Descreva o que apareceu: ") or "").strip()
                return RespostaEtapa(confirmada=False, intervencao=True, texto=detalhe)
            if escolha == "x":
                raise OperacaoCancelada("Condução interrompida pelo operador.")
            self._escrever("  Opção inválida. Use c, n, d ou x.")

    def pedir_confirmacao_final(self, fase: str) -> tuple[str, str]:
        """Coleta protocolo e/ou texto de confirmação exibido pelo portal.

        Sem um dos dois, o servidor recusa concluir a fase. É a regra que
        impede "cliquei, logo está assinado".
        """
        self._escrever()
        self._escrever("─" * 72)
        if fase == "outorga":
            self._escrever("  Registro da OUTORGA")
            self._escrever("  O portal exibiu número de protocolo? Informe abaixo.")
        else:
            self._escrever("  Registro do ACEITE")
            self._escrever("  Cole a confirmação exibida pelo portal (ex.: 'Situação: Ativa').")
        protocolo = (self._perguntar("  Protocolo (Enter para pular): ") or "").strip()
        confirmacao = (self._perguntar("  Texto de confirmação: ") or "").strip()
        return protocolo, confirmacao

    def avisar(self, mensagem: str) -> None:
        self._escrever(f"  → {mensagem}")


def _quebrar(texto: str, largura: int) -> Sequence[str]:
    palavras = texto.split()
    linhas: list[str] = []
    atual = ""
    for palavra in palavras:
        if len(atual) + len(palavra) + 1 > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = f"{atual} {palavra}".strip()
    if atual:
        linhas.append(atual)
    return linhas or [""]
