"""
Máquina de estados, taxonomia de erros e política de conformidade.

Este módulo é **puro**: sem banco, sem HTTP, sem I/O. É o coração testável do
módulo de Procurações e a única fonte de verdade sobre "o que pode virar o
quê". Qualquer transição no sistema passa por `transicao_valida()`.

Por que uma máquina de estados explícita e não `if` espalhado: o fluxo real da
Receita tem dois atos jurídicos distintos (outorga pelo cliente e aceite pela
contabilidade), separados por dias, executados por identidades diferentes, com
prazo de decadência de 30 dias no meio. Sem estado persistido e transição
validada, uma retomada após queda vira outorga duplicada.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import timedelta


class StatusAutorizacao(str, enum.Enum):
    """Situação da Autorização de Acesso — espelha o vocabulário do portal."""

    SEM_AUTORIZACAO = "sem_autorizacao"
    EM_ANALISE = "em_analise"
    AGUARDANDO_ACEITE = "aguardando_aceite"
    ATIVA = "ativa"
    EXPIRADA = "expirada"
    CANCELADA = "cancelada"
    REJEITADA = "rejeitada"
    ERRO = "erro"
    INTERVENCAO_MANUAL = "intervencao_manual"


#: Situações em que a contabilidade ainda não consegue operar em nome do cliente.
SITUACOES_PENDENTES = frozenset(
    {
        StatusAutorizacao.SEM_AUTORIZACAO,
        StatusAutorizacao.EM_ANALISE,
        StatusAutorizacao.AGUARDANDO_ACEITE,
        StatusAutorizacao.EXPIRADA,
        StatusAutorizacao.CANCELADA,
        StatusAutorizacao.REJEITADA,
        StatusAutorizacao.ERRO,
        StatusAutorizacao.INTERVENCAO_MANUAL,
    }
)

#: Prazo legal para a pessoa autorizada validar a autorização recebida.
#: Vigente desde 05/12/2025 (nova versão do sistema de procurações).
#: Passado o prazo sem validação, a Receita cancela automaticamente.
PRAZO_ACEITE = timedelta(days=30)

#: Vigência máxima admitida pelo portal para uma Autorização de Acesso.
VIGENCIA_MAXIMA = timedelta(days=5 * 365 + 1)


class StatusJob(str, enum.Enum):
    """Ciclo de vida de um job da fila operacional.

    A ordem dos membros é a ordem natural do fluxo; ela alimenta a barra de
    progresso da interface e o cálculo de "etapa atual".
    """

    # --- entrada -----------------------------------------------------------
    PENDENTE = "pendente"
    AGUARDANDO_AGENTE = "aguardando_agente"
    ATRIBUIDO = "atribuido"
    # --- verificação prévia (roda antes de qualquer acesso ao portal) ------
    VERIFICANDO_PRE_REQUISITOS = "verificando_pre_requisitos"
    # --- fase 1: outorga pelo cliente --------------------------------------
    PRONTO_PARA_OPERACAO = "pronto_para_operacao"
    AUTENTICANDO = "autenticando"
    PREENCHENDO = "preenchendo"
    AGUARDANDO_ASSINATURA = "aguardando_assinatura"
    ASSINADO = "assinado"
    # --- fase 2: aceite pela contabilidade ---------------------------------
    AGUARDANDO_VALIDACAO = "aguardando_validacao"
    VALIDANDO = "validando"
    # --- terminais ---------------------------------------------------------
    CONCLUIDO = "concluido"
    FALHOU = "falhou"
    CANCELADO = "cancelado"
    INTERVENCAO_MANUAL = "intervencao_manual"


#: Estados a partir dos quais nada mais acontece sem uma ação explícita.
ESTADOS_TERMINAIS = frozenset(
    {StatusJob.CONCLUIDO, StatusJob.FALHOU, StatusJob.CANCELADO}
)

#: Estados em que o job ocupa um Agent (contam para o limite de concorrência).
ESTADOS_OCUPANDO_AGENTE = frozenset(
    {
        StatusJob.ATRIBUIDO,
        StatusJob.VERIFICANDO_PRE_REQUISITOS,
        StatusJob.PRONTO_PARA_OPERACAO,
        StatusJob.AUTENTICANDO,
        StatusJob.PREENCHENDO,
        StatusJob.AGUARDANDO_ASSINATURA,
        StatusJob.VALIDANDO,
    }
)

#: Estados em que o operador humano é quem precisa agir.
ESTADOS_ESPERANDO_HUMANO = frozenset(
    {
        StatusJob.PRONTO_PARA_OPERACAO,
        StatusJob.AGUARDANDO_ASSINATURA,
        StatusJob.INTERVENCAO_MANUAL,
    }
)


#: Grafo de transições permitidas. Tudo que não está aqui é rejeitado.
#:
#: `INTERVENCAO_MANUAL` é alcançável de **qualquer estado não terminal** de
#: propósito: é o escape hatch quando o portal apresenta desafio, o Assinador
#: cai, a interface muda — ou quando uma pessoa quer assumir um job que
#: nenhuma estação vai pegar (fila vazia, escritório sem Agent). O grafo foi
#: escrito do ponto de vista do Agent que relata problema depois de assumir;
#: a pessoa pode precisar assumir antes disso, e isso é operação legítima.
#: Sair dele só é possível voltando para um ponto conhecido.
TRANSICOES: dict[StatusJob, frozenset[StatusJob]] = {
    StatusJob.PENDENTE: frozenset(
        {
            StatusJob.AGUARDANDO_AGENTE,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.AGUARDANDO_AGENTE: frozenset(
        {
            StatusJob.ATRIBUIDO,
            StatusJob.PENDENTE,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.ATRIBUIDO: frozenset(
        {
            StatusJob.VERIFICANDO_PRE_REQUISITOS,
            StatusJob.AGUARDANDO_AGENTE,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.VERIFICANDO_PRE_REQUISITOS: frozenset(
        {
            StatusJob.PRONTO_PARA_OPERACAO,
            StatusJob.AGUARDANDO_VALIDACAO,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.AGUARDANDO_AGENTE,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.PRONTO_PARA_OPERACAO: frozenset(
        {
            StatusJob.AUTENTICANDO,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.AUTENTICANDO: frozenset(
        {
            StatusJob.PREENCHENDO,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.PREENCHENDO: frozenset(
        {
            StatusJob.AGUARDANDO_ASSINATURA,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.AGUARDANDO_ASSINATURA: frozenset(
        {
            StatusJob.ASSINADO,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.ASSINADO: frozenset(
        {StatusJob.AGUARDANDO_VALIDACAO, StatusJob.INTERVENCAO_MANUAL, StatusJob.FALHOU}
    ),
    StatusJob.AGUARDANDO_VALIDACAO: frozenset(
        {
            StatusJob.VALIDANDO,
            StatusJob.AGUARDANDO_AGENTE,
            StatusJob.INTERVENCAO_MANUAL,
            # Fechamento manual da fase 2: a pessoa validou no portal oficial
            # e traz a confirmação (`registrar_aceite`).
            StatusJob.CONCLUIDO,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.VALIDANDO: frozenset(
        {
            StatusJob.CONCLUIDO,
            StatusJob.AGUARDANDO_VALIDACAO,
            StatusJob.INTERVENCAO_MANUAL,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    StatusJob.INTERVENCAO_MANUAL: frozenset(
        {
            # Retomada a partir do ponto em que parou — o serviço escolhe o
            # destino com base em `etapa_retomada`, nunca "começa do zero".
            StatusJob.PENDENTE,
            StatusJob.AGUARDANDO_AGENTE,
            StatusJob.PRONTO_PARA_OPERACAO,
            StatusJob.AGUARDANDO_ASSINATURA,
            StatusJob.AGUARDANDO_VALIDACAO,
            # Fechamento manual da fase 1: a pessoa fez a outorga no portal
            # oficial e traz protocolo/confirmação (`registrar_outorga`).
            # O marco continua protegido — pela exigência de confirmação,
            # não pela inalcançabilidade.
            StatusJob.ASSINADO,
            StatusJob.CONCLUIDO,
            StatusJob.CANCELADO,
            StatusJob.FALHOU,
        }
    ),
    # Terminal é terminal. Reprocessar cria um job NOVO (outro ciclo, outra
    # chave idempotente) em vez de reabrir este — reabrir apagaria a evidência
    # do que aconteceu e quebraria a leitura da trilha de auditoria.
    StatusJob.CONCLUIDO: frozenset(),
    StatusJob.FALHOU: frozenset(),
    StatusJob.CANCELADO: frozenset(),
}


class TransicaoInvalidaError(ValueError):
    """Tentativa de mover o job para um estado que o fluxo não admite."""

    def __init__(self, origem: StatusJob, destino: StatusJob):
        super().__init__(
            f"Transição não permitida: {origem.value} → {destino.value}. "
            "Isso indica reentrância de um job antigo ou bug de orquestração."
        )
        self.origem = origem
        self.destino = destino


def transicao_valida(origem: StatusJob, destino: StatusJob) -> bool:
    """`True` se o grafo admite a transição (transição para si mesmo é no-op)."""
    if origem == destino:
        return True
    return destino in TRANSICOES.get(origem, frozenset())


def exigir_transicao(origem: StatusJob, destino: StatusJob) -> None:
    """Levanta `TransicaoInvalidaError` quando o grafo não admite o movimento."""
    if not transicao_valida(origem, destino):
        raise TransicaoInvalidaError(origem, destino)


# ---------------------------------------------------------------------------
# Taxonomia de erros
# ---------------------------------------------------------------------------


class ClasseErro(str, enum.Enum):
    """Classificação que decide **se** e **como** retentar.

    Retry cego é o que transforma uma falha de cadastro em 300 tentativas
    inúteis contra o portal da Receita — exatamente o padrão de tráfego que a
    IN RFB nº 2.320/2026 trata como uso indevido.
    """

    TRANSIENTE = "transiente"
    PERMANENTE = "permanente"
    MANUAL = "manual"
    AUTENTICACAO = "autenticacao"
    CERTIFICADO = "certificado"
    PORTAL_ALTERADO = "portal_alterado"
    SERPRO = "serpro"
    TIMEOUT = "timeout"
    REDE = "rede"
    DUPLICIDADE = "duplicidade"
    CONFORMIDADE = "conformidade"


class CodigoErro(str, enum.Enum):
    """Códigos estáveis. A interface traduz; logs e métricas usam o código."""

    CERTIFICADO_EXPIRADO = "CERTIFICADO_EXPIRADO"
    CERTIFICADO_NAO_ENCONTRADO = "CERTIFICADO_NAO_ENCONTRADO"
    CERTIFICADO_INVALIDO = "CERTIFICADO_INVALIDO"
    CERTIFICADO_NAO_CORRESPONDE = "CERTIFICADO_NAO_CORRESPONDE"
    CERTIFICADO_AMBIGUO = "CERTIFICADO_AMBIGUO"
    CERTIFICADO_INDISPONIVEL = "CERTIFICADO_INDISPONIVEL"
    SENHA_INVALIDA = "SENHA_INVALIDA"

    ASSINADOR_NAO_INSTALADO = "ASSINADOR_NAO_INSTALADO"
    ASSINADOR_PARADO = "ASSINADOR_PARADO"
    ASSINADOR_VERSAO_INCOMPATIVEL = "ASSINADOR_VERSAO_INCOMPATIVEL"
    ASSINADOR_SEM_CONEXAO_LOCAL = "ASSINADOR_SEM_CONEXAO_LOCAL"
    ASSINATURA_RECUSADA = "ASSINATURA_RECUSADA"
    ASSINATURA_NAO_CONFIRMADA = "ASSINATURA_NAO_CONFIRMADA"

    PORTAL_INDISPONIVEL = "PORTAL_INDISPONIVEL"
    PORTAL_ALTERADO = "PORTAL_ALTERADO"
    PORTAL_DESAFIO_ADICIONAL = "PORTAL_DESAFIO_ADICIONAL"
    PORTAL_SESSAO_EXPIRADA = "PORTAL_SESSAO_EXPIRADA"
    PORTAL_ACESSO_NEGADO = "PORTAL_ACESSO_NEGADO"

    AGENTE_INDISPONIVEL = "AGENTE_INDISPONIVEL"
    AGENTE_SEM_RESPOSTA = "AGENTE_SEM_RESPOSTA"
    AGENTE_REVOGADO = "AGENTE_REVOGADO"

    TEMPO_ESGOTADO = "TEMPO_ESGOTADO"
    FALHA_DE_REDE = "FALHA_DE_REDE"

    AUTORIZACAO_JA_EXISTE = "AUTORIZACAO_JA_EXISTE"
    JOB_DUPLICADO = "JOB_DUPLICADO"

    INTEGRACAO_NAO_CONFIGURADA = "INTEGRACAO_NAO_CONFIGURADA"
    INTEGRACAO_RECUSOU = "INTEGRACAO_RECUSOU"

    MODO_AUTOMATICO_VEDADO = "MODO_AUTOMATICO_VEDADO"
    OPERACAO_CANCELADA_PELO_OPERADOR = "OPERACAO_CANCELADA_PELO_OPERADOR"
    DADOS_INSUFICIENTES = "DADOS_INSUFICIENTES"

    #: Intervenção pedida por uma pessoa (não pela estação). Texto honesto:
    #: nenhuma barreira do portal foi encontrada — alguém decidiu assumir.
    INTERVENCAO_SOLICITADA = "INTERVENCAO_SOLICITADA"


@dataclass(frozen=True)
class RegraErro:
    """Como o orquestrador reage a um código de erro."""

    classe: ClasseErro
    max_tentativas: int
    #: Espera base em segundos; o serviço aplica backoff exponencial + jitter.
    espera_base_segundos: int
    #: Destino quando as tentativas se esgotam (ou já na primeira, se 0).
    destino_apos_esgotar: StatusJob
    #: Frase pronta para o operador. Sem jargão de stack trace.
    explicacao: str


_MANUAL = StatusJob.INTERVENCAO_MANUAL
_FALHOU = StatusJob.FALHOU

REGRAS: dict[CodigoErro, RegraErro] = {
    # --- certificado: nunca insistir; é problema de cadastro/renovação -----
    CodigoErro.CERTIFICADO_EXPIRADO: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _FALHOU,
        "O certificado A1 desta empresa está vencido. Renove e recadastre antes de reprocessar.",
    ),
    CodigoErro.CERTIFICADO_NAO_ENCONTRADO: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _MANUAL,
        "Nenhum certificado A1 desta empresa foi encontrado na estação designada.",
    ),
    CodigoErro.CERTIFICADO_INVALIDO: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _FALHOU,
        "O arquivo não é um certificado A1 ICP-Brasil legível.",
    ),
    CodigoErro.CERTIFICADO_NAO_CORRESPONDE: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _MANUAL,
        "O certificado disponível não pertence ao CNPJ desta empresa. Operação interrompida.",
    ),
    CodigoErro.CERTIFICADO_AMBIGUO: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _MANUAL,
        "Mais de um certificado atende ao CNPJ desta empresa. Escolha explicitamente qual usar.",
    ),
    CodigoErro.CERTIFICADO_INDISPONIVEL: RegraErro(
        ClasseErro.CERTIFICADO, 2, 60, _MANUAL,
        "O certificado está cadastrado mas não pôde ser aberto na estação neste momento.",
    ),
    CodigoErro.SENHA_INVALIDA: RegraErro(
        ClasseErro.CERTIFICADO, 0, 0, _MANUAL,
        "A senha guardada para este certificado foi recusada. Regrave a senha no cofre da estação.",
    ),
    # --- Assinador SERPRO: ambiente local, tratável pelo operador ---------
    CodigoErro.ASSINADOR_NAO_INSTALADO: RegraErro(
        ClasseErro.SERPRO, 0, 0, _MANUAL,
        "O Assinador SERPRO não está instalado nesta estação.",
    ),
    CodigoErro.ASSINADOR_PARADO: RegraErro(
        ClasseErro.SERPRO, 3, 30, _MANUAL,
        "O Assinador SERPRO está instalado mas não está em execução.",
    ),
    CodigoErro.ASSINADOR_VERSAO_INCOMPATIVEL: RegraErro(
        ClasseErro.SERPRO, 0, 0, _MANUAL,
        "A versão do Assinador SERPRO nesta estação está abaixo da versão mínima configurada.",
    ),
    CodigoErro.ASSINADOR_SEM_CONEXAO_LOCAL: RegraErro(
        ClasseErro.SERPRO, 3, 20, _MANUAL,
        "O Assinador SERPRO não respondeu na porta local. Verifique firewall e a autorização do navegador.",
    ),
    CodigoErro.ASSINATURA_RECUSADA: RegraErro(
        ClasseErro.SERPRO, 0, 0, _MANUAL,
        "A assinatura foi recusada pelo Assinador. Nada foi outorgado.",
    ),
    CodigoErro.ASSINATURA_NAO_CONFIRMADA: RegraErro(
        ClasseErro.MANUAL, 0, 0, _MANUAL,
        "Não houve confirmação efetiva da assinatura. O job NÃO é marcado como assinado.",
    ),
    # --- portal -----------------------------------------------------------
    CodigoErro.PORTAL_INDISPONIVEL: RegraErro(
        ClasseErro.TRANSIENTE, 3, 300, _MANUAL,
        "O Portal de Serviços da Receita Federal não respondeu.",
    ),
    CodigoErro.PORTAL_ALTERADO: RegraErro(
        ClasseErro.PORTAL_ALTERADO, 0, 0, _MANUAL,
        "O fluxo da Receita mudou. É necessária manutenção do adaptador RFB antes de continuar.",
    ),
    CodigoErro.PORTAL_DESAFIO_ADICIONAL: RegraErro(
        ClasseErro.MANUAL, 0, 0, _MANUAL,
        "A Receita apresentou um desafio adicional de segurança. Só uma pessoa pode resolvê-lo.",
    ),
    CodigoErro.PORTAL_SESSAO_EXPIRADA: RegraErro(
        ClasseErro.AUTENTICACAO, 1, 10, _MANUAL,
        "A sessão no portal expirou antes da conclusão.",
    ),
    CodigoErro.PORTAL_ACESSO_NEGADO: RegraErro(
        ClasseErro.AUTENTICACAO, 0, 0, _MANUAL,
        "O portal negou o acesso com esta identidade. Verifique regularidade cadastral do CNPJ/CPF.",
    ),
    # --- infraestrutura ----------------------------------------------------
    CodigoErro.AGENTE_INDISPONIVEL: RegraErro(
        ClasseErro.TRANSIENTE, 5, 120, _MANUAL,
        "Nenhuma estação habilitada estava disponível para este job.",
    ),
    CodigoErro.AGENTE_SEM_RESPOSTA: RegraErro(
        ClasseErro.TRANSIENTE, 3, 60, _MANUAL,
        "A estação parou de responder no meio do job. O estado foi preservado.",
    ),
    CodigoErro.AGENTE_REVOGADO: RegraErro(
        ClasseErro.PERMANENTE, 0, 0, _FALHOU,
        "A estação que executava este job teve o acesso revogado.",
    ),
    CodigoErro.TEMPO_ESGOTADO: RegraErro(
        ClasseErro.TIMEOUT, 3, 60, _MANUAL,
        "A etapa passou do tempo limite configurado.",
    ),
    CodigoErro.FALHA_DE_REDE: RegraErro(
        ClasseErro.REDE, 3, 45, _MANUAL,
        "Falha de rede entre a estação e o destino.",
    ),
    # --- idempotência ------------------------------------------------------
    CodigoErro.AUTORIZACAO_JA_EXISTE: RegraErro(
        ClasseErro.DUPLICIDADE, 0, 0, StatusJob.CONCLUIDO,
        "Já existe autorização vigente para esta empresa. Nada foi criado — o job foi encerrado.",
    ),
    CodigoErro.JOB_DUPLICADO: RegraErro(
        ClasseErro.DUPLICIDADE, 0, 0, StatusJob.CANCELADO,
        "Já havia um job ativo para esta empresa. Este foi descartado sem efeito.",
    ),
    # --- integrações -------------------------------------------------------
    CodigoErro.INTEGRACAO_NAO_CONFIGURADA: RegraErro(
        ClasseErro.PERMANENTE, 0, 0, _FALHOU,
        "A fonte de dados de procurações não está configurada.",
    ),
    CodigoErro.INTEGRACAO_RECUSOU: RegraErro(
        ClasseErro.TRANSIENTE, 3, 120, _FALHOU,
        "A fonte externa recusou a consulta.",
    ),
    # --- conformidade ------------------------------------------------------
    CodigoErro.MODO_AUTOMATICO_VEDADO: RegraErro(
        ClasseErro.CONFORMIDADE, 0, 0, _MANUAL,
        "A execução não assistida do ato de outorga está vedada pela IN RFB nº 2.320/2026. "
        "O job segue em modo assistido, conduzido por uma pessoa.",
    ),
    CodigoErro.OPERACAO_CANCELADA_PELO_OPERADOR: RegraErro(
        ClasseErro.PERMANENTE, 0, 0, StatusJob.CANCELADO,
        "Operação cancelada pelo operador.",
    ),
    CodigoErro.INTERVENCAO_SOLICITADA: RegraErro(
        ClasseErro.MANUAL, 0, 0, _MANUAL,
        "Intervenção pedida por uma pessoa do escritório. O processo parou e "
        "aguarda ação humana — nenhum desafio do portal foi detectado.",
    ),
    CodigoErro.DADOS_INSUFICIENTES: RegraErro(
        ClasseErro.PERMANENTE, 0, 0, _MANUAL,
        "Faltam dados obrigatórios para montar a autorização (outorgado, vigência ou serviços).",
    ),
}

#: Regra usada quando um código desconhecido chega do Agent. Falha fechada:
#: desconhecido vira intervenção humana, nunca retry infinito.
REGRA_PADRAO = RegraErro(
    ClasseErro.MANUAL, 0, 0, _MANUAL,
    "Erro não classificado. O job parou e aguarda análise humana.",
)


def regra_do_erro(codigo: str | CodigoErro | None) -> RegraErro:
    """Regra de tratamento — nunca levanta, sempre devolve algo acionável."""
    if codigo is None:
        return REGRA_PADRAO
    try:
        return REGRAS[CodigoErro(codigo)]
    except (ValueError, KeyError):
        return REGRA_PADRAO


def deve_retentar(codigo: str | CodigoErro | None, tentativas_feitas: int) -> bool:
    """Decide retry olhando a classe do erro, não só o contador."""
    regra = regra_do_erro(codigo)
    return tentativas_feitas < regra.max_tentativas


def espera_do_retry(codigo: str | CodigoErro | None, tentativas_feitas: int) -> int:
    """Backoff exponencial limitado a 30 minutos (sem jitter — quem chama aplica)."""
    regra = regra_do_erro(codigo)
    if regra.espera_base_segundos <= 0:
        return 0
    return min(1800, regra.espera_base_segundos * (2 ** max(0, tentativas_feitas)))


# ---------------------------------------------------------------------------
# Política de conformidade (IN RFB nº 2.320/2026)
# ---------------------------------------------------------------------------


class ModoOperacao(str, enum.Enum):
    """Como o job interage com o Portal de Serviços da Receita Federal.

    ``ASSISTIDO`` é o único modo habilitado por padrão e o único que o produto
    considera conforme hoje. Ver `docs/PROCURACOES_CONFORMIDADE.md`.
    """

    #: A estação prepara tudo (certificado, Assinador, roteiro, dados conferidos)
    #: e abre o portal oficial no navegador do operador. A pessoa conduz a
    #: outorga/assinatura/validação. O sistema registra evidência e resultado.
    ASSISTIDO = "assistido"

    #: Leitura de situação por API oficial (SERPRO Integra Contador) ou por
    #: integração do escritório. Não toca no ato de outorga.
    CONSULTA_API = "consulta_api"

    #: Execução não assistida do ato de outorga/alteração/revogação.
    #: Mantido como valor de domínio para que o sistema saiba **recusar** e
    #: registre a recusa. Nenhum executor implementa este modo.
    NAO_ASSISTIDO = "nao_assistido"


@dataclass(frozen=True)
class AvaliacaoPolitica:
    """Resultado de uma checagem de conformidade."""

    permitido: bool
    modo_efetivo: ModoOperacao
    motivo: str
    #: Referência normativa que embasa a decisão — vai para a auditoria.
    fundamento: str = ""
    avisos: tuple[str, ...] = field(default_factory=tuple)


FUNDAMENTO_IN_2320 = (
    "IN RFB nº 2.320, de 6 de abril de 2026 — veda aplicativo, webview, iframe, "
    "camada de intermediação ou sistema próprio que, por automação ou "
    "encapsulamento do ambiente dos serviços digitais da Receita Federal, "
    "possibilite outorga, alteração ou revogação de autorizações de acesso."
)


def avaliar_modo(
    modo_solicitado: ModoOperacao | str,
    *,
    autorizacao_formal_rfb: bool = False,
) -> AvaliacaoPolitica:
    """Porta única de decisão sobre como um job pode tocar o portal.

    `autorizacao_formal_rfb` só pode ser ligado quando a contabilidade tiver
    documento formal da Receita Federal habilitando-a como intermediário
    autorizado. O registro desse documento fica em
    `procuracao_configuracoes.autorizacao_formal_referencia` e aparece na
    auditoria. Mesmo ligado, nenhum executor não assistido é embarcado: a
    flag apenas destrava o ponto de extensão documentado.
    """
    try:
        modo = ModoOperacao(modo_solicitado)
    except ValueError:
        return AvaliacaoPolitica(
            permitido=False,
            modo_efetivo=ModoOperacao.ASSISTIDO,
            motivo="Modo de operação desconhecido.",
            fundamento=FUNDAMENTO_IN_2320,
        )

    if modo in (ModoOperacao.ASSISTIDO, ModoOperacao.CONSULTA_API):
        return AvaliacaoPolitica(
            permitido=True,
            modo_efetivo=modo,
            motivo="Modo conforme: o ato jurídico é praticado por pessoa autenticada, "
            "no ambiente oficial, sem encapsulamento.",
        )

    if not autorizacao_formal_rfb:
        return AvaliacaoPolitica(
            permitido=False,
            modo_efetivo=ModoOperacao.ASSISTIDO,
            motivo=(
                "Execução não assistida da outorga está vedada. O job continua em "
                "modo assistido."
            ),
            fundamento=FUNDAMENTO_IN_2320,
        )

    return AvaliacaoPolitica(
        permitido=False,
        modo_efetivo=ModoOperacao.ASSISTIDO,
        motivo=(
            "Há registro de autorização formal, mas nenhum executor não assistido "
            "está embarcado neste produto. Ver docs/PROCURACOES_CONFORMIDADE.md, "
            "seção 'Ponto de extensão'."
        ),
        fundamento=FUNDAMENTO_IN_2320,
        avisos=("autorizacao_formal_registrada",),
    )


# ---------------------------------------------------------------------------
# Etapas do roteiro assistido — o contrato entre backend, Agent e interface
# ---------------------------------------------------------------------------


class EtapaFluxo(str, enum.Enum):
    """Etapas nomeadas do fluxo oficial, na ordem em que a Receita as apresenta."""

    PRE_REQUISITOS = "pre_requisitos"
    ACESSO_PORTAL = "acesso_portal"
    MINHAS_AUTORIZACOES = "minhas_autorizacoes"
    NOVA_AUTORIZACAO_PESSOA = "nova_autorizacao_pessoa"
    NOVA_AUTORIZACAO_SERVICOS = "nova_autorizacao_servicos"
    NOVA_AUTORIZACAO_REVISAO = "nova_autorizacao_revisao"
    ASSINATURA = "assinatura"
    REGISTRO_OUTORGA = "registro_outorga"
    ACESSO_PORTAL_CONTABILIDADE = "acesso_portal_contabilidade"
    AUTORIZACOES_RECEBIDAS = "autorizacoes_recebidas"
    VALIDACAO = "validacao"
    REGISTRO_CONCLUSAO = "registro_conclusao"


#: Etapa → estado do job quando aquela etapa está em curso. Usado na retomada:
#: o job volta para o estado da etapa em que parou, não para o começo.
ESTADO_DA_ETAPA: dict[EtapaFluxo, StatusJob] = {
    EtapaFluxo.PRE_REQUISITOS: StatusJob.VERIFICANDO_PRE_REQUISITOS,
    EtapaFluxo.ACESSO_PORTAL: StatusJob.AUTENTICANDO,
    EtapaFluxo.MINHAS_AUTORIZACOES: StatusJob.AUTENTICANDO,
    EtapaFluxo.NOVA_AUTORIZACAO_PESSOA: StatusJob.PREENCHENDO,
    EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS: StatusJob.PREENCHENDO,
    EtapaFluxo.NOVA_AUTORIZACAO_REVISAO: StatusJob.PREENCHENDO,
    EtapaFluxo.ASSINATURA: StatusJob.AGUARDANDO_ASSINATURA,
    EtapaFluxo.REGISTRO_OUTORGA: StatusJob.ASSINADO,
    EtapaFluxo.ACESSO_PORTAL_CONTABILIDADE: StatusJob.VALIDANDO,
    EtapaFluxo.AUTORIZACOES_RECEBIDAS: StatusJob.VALIDANDO,
    EtapaFluxo.VALIDACAO: StatusJob.VALIDANDO,
    EtapaFluxo.REGISTRO_CONCLUSAO: StatusJob.CONCLUIDO,
}


class FaseJob(str, enum.Enum):
    """Qual das duas identidades o job usa agora."""

    OUTORGA = "outorga"      # certificado do CLIENTE
    ACEITE = "aceite"        # certificado da CONTABILIDADE


class TipoCertificado(str, enum.Enum):
    """Nunca confundir os dois contextos."""

    CLIENTE = "cliente"
    CONTABILIDADE = "contabilidade"


def fase_do_status(status: StatusJob) -> FaseJob:
    """Qual identidade o job precisa neste estado."""
    if status in {
        StatusJob.AGUARDANDO_VALIDACAO,
        StatusJob.VALIDANDO,
    }:
        return FaseJob.ACEITE
    return FaseJob.OUTORGA


def certificado_exigido(status: StatusJob) -> TipoCertificado:
    """Tradução direta fase → tipo de certificado. Evita o bug de trocar as identidades."""
    return (
        TipoCertificado.CONTABILIDADE
        if fase_do_status(status) is FaseJob.ACEITE
        else TipoCertificado.CLIENTE
    )
