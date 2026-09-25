"""
Adaptador do Portal de Serviços da RFB — **um único lugar** para tudo que
depende de como a Receita apresenta a tela.

Por que existe um módulo só para isso: o portal muda. Quando mudar, a
manutenção tem que ser uma edição neste arquivo, não uma caçada por strings
espalhadas pelo Agent, pelo backend e pela interface.

O que está aqui:

- as **URLs oficiais** do fluxo (nada de endpoint inferido ou inventado);
- as **âncoras de verificação** de cada etapa — trechos de texto visíveis que
  comprovam que a página certa está aberta;
- o **roteiro assistido**, que é o contrato entre backend, Agent e tela: o
  que o operador faz, o que o sistema confere e o que precisa ser confirmado
  para a etapa avançar;
- `PortalAlteradoError`, levantado quando a âncora não aparece.

O que **não** está aqui, por decisão consciente: seletores CSS/XPath de
clique automatizado nas telas de outorga, alteração e revogação de
autorizações. A IN RFB nº 2.320/2026, art. 13, veda sistema que, por
automação ou encapsulamento do ambiente digital da RFB, possibilite esses
atos. O módulo navega até a tela, valida o ambiente e confere o resultado —
quem executa o ato é a pessoa, com o certificado dela.

Âncoras são **texto visível**, e não `div:nth-child(3) > button`: o rótulo
"Nova Autorização de Acesso" é estável porque é vocabulário legal; a estrutura
do DOM não é.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from app.procuracoes.estados import EtapaFluxo, FaseJob

# ---------------------------------------------------------------------------
# Endereços oficiais
# ---------------------------------------------------------------------------

#: Portal de Serviços da RFB — casa das "Autorizações de Acesso" desde a
#: substituição da "Procuração Eletrônica" (dez/2025).
PORTAL_SERVICOS = "https://servicos.receitafederal.gov.br"

#: Centro Virtual de Atendimento. Continua sendo caminho válido de entrada.
ECAC = "https://cav.receita.fazenda.gov.br/autenticacao/login"

#: Login unificado do Governo Federal.
GOVBR = "https://sso.acesso.gov.br"

#: Domínios que o Agent pode abrir para este módulo. Qualquer outro host é
#: recusado — é a barreira contra uma configuração apontar a operação para um
#: site de phishing com a mesma aparência.
DOMINIOS_PERMITIDOS: frozenset[str] = frozenset(
    {
        "servicos.receitafederal.gov.br",
        "cav.receita.fazenda.gov.br",
        "sso.acesso.gov.br",
        "assinatura.gov.br",
        "www.gov.br",
        "gov.br",
    }
)


class PortalAlteradoError(RuntimeError):
    """A página aberta não é a esperada para a etapa.

    Levantada quando as âncoras não batem. A resposta correta **nunca** é
    tentar outro seletor ou clicar em algo parecido: é parar o job e avisar
    que o adaptador precisa de manutenção.
    """

    def __init__(self, etapa: str, ausentes: tuple[str, ...], url: str = ""):
        self.etapa = etapa
        self.ausentes = ausentes
        self.url = url
        super().__init__(
            f"A tela da etapa '{etapa}' não corresponde ao esperado. "
            f"Não foi localizado: {', '.join(ausentes)}. "
            "O adaptador do Portal da RFB precisa de manutenção antes de continuar."
        )


@dataclass(frozen=True)
class PassoRoteiro:
    """Um passo do roteiro assistido."""

    etapa: EtapaFluxo
    fase: FaseJob
    titulo: str
    instrucao: str
    url: str = ""
    #: Texto que precisa aparecer na tela para o passo ser considerado aberto.
    ancoras: tuple[str, ...] = field(default_factory=tuple)
    #: O que o operador precisa conferir antes de dizer "feito".
    confirmacao: str = ""
    #: Quem executa: `operador` (ato pessoal) ou `sistema` (verificação).
    executor: str = "operador"
    #: Identidade exigida na etapa.
    certificado: str = "cliente"


#: Roteiro completo das duas fases, na ordem oficial do fluxo.
#: Fase 1 (outorga) usa o certificado do **cliente**; fase 2 (aceite), o da
#: **contabilidade**. Trocar as duas coisas é o erro mais caro possível aqui,
#: por isso a identidade está explícita em cada passo.
ROTEIRO: tuple[PassoRoteiro, ...] = (
    PassoRoteiro(
        etapa=EtapaFluxo.PRE_REQUISITOS,
        fase=FaseJob.OUTORGA,
        titulo="Conferir pré-requisitos da estação",
        instrucao=(
            "O Cajuru Agent verifica o certificado do cliente, o Assinador Digital "
            "SERPRO e o navegador. Nada é aberto enquanto algum item estiver pendente."
        ),
        confirmacao="Certificado válido localizado e Assinador respondendo na estação.",
        executor="sistema",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.ACESSO_PORTAL,
        fase=FaseJob.OUTORGA,
        titulo="Entrar no Portal de Serviços como o cliente",
        instrucao=(
            "O Agent abre o navegador na página oficial. Autentique-se com o "
            "certificado digital do cliente (o Assinador é acionado pelo próprio "
            "portal). Nenhuma credencial é digitada pelo sistema."
        ),
        url=PORTAL_SERVICOS,
        ancoras=("Receita Federal",),
        confirmacao="Sessão aberta com o CNPJ do cliente exibido no topo da página.",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.MINHAS_AUTORIZACOES,
        fase=FaseJob.OUTORGA,
        titulo="Abrir Autorizações de Acesso → Minhas Autorizações",
        instrucao=(
            "No Portal de Serviços, acesse 'Autorizações de Acesso' e depois "
            "'Minhas Autorizações de Acesso'. Confira a aba 'Concedidas' antes de "
            "criar qualquer coisa: se já houver autorização vigente para a "
            "contabilidade, o job é encerrado sem duplicar."
        ),
        ancoras=("Autoriza", "Acesso"),
        confirmacao="Lista de autorizações concedidas visível.",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.NOVA_AUTORIZACAO_PESSOA,
        fase=FaseJob.OUTORGA,
        titulo="Nova Autorização — passo 1: pessoa e validade",
        instrucao=(
            "Clique em 'Nova Autorização de Acesso' e informe o CNPJ/CPF da "
            "contabilidade e a data de validade indicados no painel lateral. "
            "A validade máxima aceita pela Receita é de 5 anos."
        ),
        ancoras=("Nova Autoriza",),
        confirmacao="CNPJ do outorgado e validade conferem com os dados do job.",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS,
        fase=FaseJob.OUTORGA,
        titulo="Nova Autorização — passo 2: serviços",
        instrucao=(
            "Selecione os serviços conforme o modelo configurado. Quando o modelo "
            "é 'Todos os serviços', marque a opção que concede acesso integral."
        ),
        ancoras=("Servi",),
        confirmacao="Conjunto de serviços igual ao do modelo aplicado ao job.",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.NOVA_AUTORIZACAO_REVISAO,
        fase=FaseJob.OUTORGA,
        titulo="Nova Autorização — revisão",
        instrucao=(
            "Revise o resumo apresentado pelo portal. Divergência em qualquer "
            "campo deve interromper o processo, não ser corrigida no impulso."
        ),
        ancoras=("Revis",),
        confirmacao="Resumo confere integralmente com a ordem de trabalho.",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.ASSINATURA,
        fase=FaseJob.OUTORGA,
        titulo="Assinar com o certificado do cliente",
        instrucao=(
            "O portal abre o ambiente oficial de assinatura do Governo Federal. "
            "Conclua a assinatura com o certificado do cliente. O sistema não "
            "assina em seu lugar e não manipula a chave privada."
        ),
        ancoras=("Assin",),
        confirmacao=(
            "Mensagem de sucesso do portal e/ou número de protocolo exibido. "
            "Sem essa confirmação o job NÃO avança."
        ),
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.REGISTRO_OUTORGA,
        fase=FaseJob.OUTORGA,
        titulo="Registrar a outorga no Cajuru28",
        instrucao=(
            "Informe o protocolo ou cole o texto de confirmação exibido pelo "
            "portal. O sistema grava a autorização como 'Em análise' e inicia a "
            "contagem dos 30 dias do aceite."
        ),
        confirmacao="Protocolo ou confirmação textual registrados.",
        executor="sistema",
        certificado="cliente",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.ACESSO_PORTAL_CONTABILIDADE,
        fase=FaseJob.ACEITE,
        titulo="Entrar no portal como a contabilidade",
        instrucao=(
            "Agora a identidade muda: autentique-se com o certificado da "
            "contabilidade (outorgado). O Agent só libera esta etapa se o "
            "certificado do escritório estiver disponível na estação."
        ),
        url=PORTAL_SERVICOS,
        ancoras=("Receita Federal",),
        confirmacao="Sessão aberta com o CNPJ da contabilidade.",
        certificado="contabilidade",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.AUTORIZACOES_RECEBIDAS,
        fase=FaseJob.ACEITE,
        titulo="Abrir a aba 'Recebidas'",
        instrucao=(
            "Em 'Minhas Autorizações de Acesso', vá até a aba 'Recebidas' e "
            "localize a autorização do cliente com situação 'Em análise'."
        ),
        ancoras=("Recebid",),
        confirmacao="Autorização do cliente localizada na lista.",
        certificado="contabilidade",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.VALIDACAO,
        fase=FaseJob.ACEITE,
        titulo="Validar a autorização",
        instrucao=(
            "Use a ação 'Validar' para aceitar a autorização recebida. Sem esse "
            "aceite em 30 dias a Receita cancela a autorização automaticamente."
        ),
        ancoras=("Validar",),
        confirmacao="Situação da autorização passou para 'Ativa' na própria tela.",
        certificado="contabilidade",
    ),
    PassoRoteiro(
        etapa=EtapaFluxo.REGISTRO_CONCLUSAO,
        fase=FaseJob.ACEITE,
        titulo="Registrar a conclusão",
        instrucao=(
            "Confirme no Cajuru28 que a autorização está ativa. O job é encerrado "
            "e a empresa sai da lista de pendências."
        ),
        confirmacao="Situação 'Ativa' confirmada no portal.",
        executor="sistema",
        certificado="contabilidade",
    ),
)

_POR_ETAPA: dict[str, PassoRoteiro] = {passo.etapa.value: passo for passo in ROTEIRO}


def passo(etapa: EtapaFluxo | str) -> PassoRoteiro | None:
    chave = etapa.value if isinstance(etapa, EtapaFluxo) else str(etapa)
    return _POR_ETAPA.get(chave)


def roteiro_da_fase(fase: FaseJob | str) -> list[PassoRoteiro]:
    alvo = fase.value if isinstance(fase, FaseJob) else str(fase)
    return [item for item in ROTEIRO if item.fase.value == alvo]


def roteiro_serializado(fase: FaseJob | str | None = None) -> list[dict]:
    """Forma consumível por API/Agent/tela — um roteiro, três consumidores."""
    itens = roteiro_da_fase(fase) if fase else list(ROTEIRO)
    return [
        {
            "etapa": item.etapa.value,
            "fase": item.fase.value,
            "titulo": item.titulo,
            "instrucao": item.instrucao,
            "url": item.url,
            "confirmacao": item.confirmacao,
            "executor": item.executor,
            "certificado": item.certificado,
        }
        for item in itens
    ]


def url_permitida(url: str) -> bool:
    """Só domínios oficiais. Vale para o Agent e para a tela."""
    texto = (url or "").strip().lower()
    if not texto.startswith("https://"):
        return False
    host = texto.split("://", 1)[1].split("/", 1)[0].split(":")[0]
    return host in DOMINIOS_PERMITIDOS


def _dobrar(texto: str) -> str:
    """Minúsculas sem acento — comparação imune a 'Autorizações' vs 'AUTORIZACOES'."""
    sem_acento = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", str(texto or ""))
        if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def verificar_ancoras(etapa: EtapaFluxo | str, texto_da_pagina: str, url: str = "") -> None:
    """Confere as âncoras da etapa. Levanta `PortalAlteradoError` se faltarem.

    Chamada pelo Agent com o texto visível da página. Recebe texto, não HTML
    bruto, porque é o texto que o usuário vê — e é o que a Receita mantém
    estável entre releases de front-end.
    """
    passo_atual = passo(etapa)
    if passo_atual is None or not passo_atual.ancoras:
        return
    conteudo = _dobrar(texto_da_pagina)
    ausentes = tuple(
        ancora for ancora in passo_atual.ancoras if _dobrar(ancora) not in conteudo
    )
    if ausentes:
        raise PortalAlteradoError(passo_atual.etapa.value, ausentes, url)


def descrever_mudanca(erro: PortalAlteradoError) -> dict:
    """Payload de manutenção — vira evento, notificação e item de troubleshooting."""
    return {
        "etapa": erro.etapa,
        "ancoras_ausentes": list(erro.ausentes),
        "url": erro.url,
        "acao": (
            "Abrir docs/PROCURACOES_RFB.md, conferir a tela atual do Portal de "
            "Serviços e atualizar as âncoras em app/procuracoes/portal.py. "
            "Nenhum job deve ser retomado antes disso."
        ),
    }
