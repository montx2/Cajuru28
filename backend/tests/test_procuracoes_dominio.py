"""
Domínio do módulo Procurações RFB: máquina de estados, taxonomia de erros,
política de conformidade, seleção de certificado e roteiro do portal.

São testes de unidade puros — sem banco, sem rede. É aqui que as regras que
não podem quebrar ficam presas por um teste rápido.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from app.procuracoes import portal
from app.procuracoes.estados import (
    ESTADOS_TERMINAIS,
    ClasseErro,
    CodigoErro,
    EtapaFluxo,
    FaseJob,
    ModoOperacao,
    StatusAutorizacao,
    StatusJob,
    TipoCertificado,
    avaliar_modo,
    certificado_exigido,
    deve_retentar,
    espera_do_retry,
    exigir_transicao,
    fase_do_status,
    regra_do_erro,
    transicao_valida,
)
from app.procuracoes.integracoes.base import RegistroProcuracao, situacao_por_validade
from app.procuracoes.integracoes.planilha import FontePlanilha
from app.procuracoes.servicos import assinador


# ---------------------------------------------------------------------------
# Máquina de estados
# ---------------------------------------------------------------------------


def test_fluxo_feliz_completo_e_valido():
    """Critério A + B: o caminho do zero até ATIVA é uma sequência legal."""
    caminho = [
        StatusJob.PENDENTE,
        StatusJob.AGUARDANDO_AGENTE,
        StatusJob.ATRIBUIDO,
        StatusJob.VERIFICANDO_PRE_REQUISITOS,
        StatusJob.PRONTO_PARA_OPERACAO,
        StatusJob.AUTENTICANDO,
        StatusJob.PREENCHENDO,
        StatusJob.AGUARDANDO_ASSINATURA,
        StatusJob.ASSINADO,
        StatusJob.AGUARDANDO_VALIDACAO,
        StatusJob.VALIDANDO,
        StatusJob.CONCLUIDO,
    ]
    for origem, destino in zip(caminho, caminho[1:]):
        assert transicao_valida(origem, destino), f"{origem} -> {destino} deveria valer"


def test_terminal_nao_reabre():
    """Reabrir um terminal destruiria a evidência; reprocessar cria outro job."""
    for terminal in ESTADOS_TERMINAIS:
        for destino in StatusJob:
            if destino is terminal:
                continue  # transição para si mesmo é no-op
            assert not transicao_valida(terminal, destino), (
                f"{terminal} não pode ir para {destino}"
            )


def test_transicao_invalida_explica_o_motivo():
    with pytest.raises(ValueError) as erro:
        exigir_transicao(StatusJob.PENDENTE, StatusJob.CONCLUIDO)
    assert "pendente" in str(erro.value).lower()


def test_nunca_pula_da_assinatura_para_concluido():
    """Nada de 'cliquei, logo está ativo': o aceite é uma fase separada."""
    assert not transicao_valida(StatusJob.AGUARDANDO_ASSINATURA, StatusJob.CONCLUIDO)
    assert not transicao_valida(StatusJob.ASSINADO, StatusJob.CONCLUIDO)


def test_identidade_por_fase_nao_se_confunde():
    """Critério: CLIENT_CERTIFICATE vs ACCOUNTING_CERTIFICATE."""
    assert fase_do_status(StatusJob.PREENCHENDO) is FaseJob.OUTORGA
    assert certificado_exigido(StatusJob.PREENCHENDO) is TipoCertificado.CLIENTE
    assert fase_do_status(StatusJob.VALIDANDO) is FaseJob.ACEITE
    assert certificado_exigido(StatusJob.VALIDANDO) is TipoCertificado.CONTABILIDADE


# ---------------------------------------------------------------------------
# Taxonomia de erros
# ---------------------------------------------------------------------------


def test_erro_de_certificado_nunca_faz_retry_cego():
    """Critério C: certificado expirado não se resolve tentando de novo."""
    regra = regra_do_erro(CodigoErro.CERTIFICADO_EXPIRADO)
    assert regra.classe is ClasseErro.CERTIFICADO
    assert regra.max_tentativas == 0
    assert not deve_retentar(CodigoErro.CERTIFICADO_EXPIRADO, 0)
    # Vencido não é "tente de novo": é renovar o A1 e reprocessar.
    assert regra.destino_apos_esgotar is StatusJob.FALHOU


def test_portal_alterado_interrompe_em_vez_de_insistir():
    """Critério E."""
    regra = regra_do_erro(CodigoErro.PORTAL_ALTERADO)
    assert regra.classe is ClasseErro.PORTAL_ALTERADO
    assert not deve_retentar(CodigoErro.PORTAL_ALTERADO, 0)
    assert regra.destino_apos_esgotar is StatusJob.INTERVENCAO_MANUAL


def test_erro_transiente_retenta_com_backoff_limitado():
    assert deve_retentar(CodigoErro.FALHA_DE_REDE, 0)
    esperas = [espera_do_retry(CodigoErro.FALHA_DE_REDE, n) for n in range(8)]
    assert esperas == sorted(esperas), "o backoff precisa ser monotônico"
    assert max(esperas) <= 1800, "espera não pode crescer indefinidamente"


def test_codigo_desconhecido_falha_fechado():
    """Erro que ninguém previu vira intervenção, nunca retry infinito."""
    regra = regra_do_erro("CODIGO_QUE_NAO_EXISTE")
    assert regra.destino_apos_esgotar is StatusJob.INTERVENCAO_MANUAL
    assert not deve_retentar("CODIGO_QUE_NAO_EXISTE", 0)


def test_todo_codigo_tem_explicacao_util():
    for codigo in CodigoErro:
        regra = regra_do_erro(codigo)
        assert len(regra.explicacao) > 20, f"{codigo} sem explicação acionável"


# ---------------------------------------------------------------------------
# Conformidade (IN RFB nº 2.320/2026)
# ---------------------------------------------------------------------------


def test_modo_nao_assistido_e_rebaixado_sem_autorizacao_formal():
    avaliacao = avaliar_modo(ModoOperacao.NAO_ASSISTIDO, autorizacao_formal_rfb=False)
    assert avaliacao.modo_efetivo is ModoOperacao.ASSISTIDO
    assert not avaliacao.permitido
    assert "2.320" in avaliacao.fundamento


def test_modo_assistido_e_sempre_permitido():
    avaliacao = avaliar_modo(ModoOperacao.ASSISTIDO, autorizacao_formal_rfb=False)
    assert avaliacao.modo_efetivo is ModoOperacao.ASSISTIDO
    assert avaliacao.permitido


def test_consulta_api_e_permitida_por_ser_canal_oficial():
    avaliacao = avaliar_modo(ModoOperacao.CONSULTA_API, autorizacao_formal_rfb=False)
    assert avaliacao.modo_efetivo is ModoOperacao.CONSULTA_API
    assert avaliacao.permitido


# ---------------------------------------------------------------------------
# Assinador SERPRO
# ---------------------------------------------------------------------------


def test_diagnostico_ausente_reprova():
    """Critério D: silêncio não é aprovação."""
    avaliacao = assinador.avaliar(None, versao_minima="4.0.0", exigido=True)
    assert not avaliacao.apto
    assert "diagnostico_ausente" in avaliacao.pendencias


def test_assinador_parado_reprova_com_conserto():
    avaliacao = assinador.avaliar(
        {
            "instalado": True,
            "em_execucao": False,
            "hosts_mapeado": True,
            "porta_local": False,
            "certificado_visivel": True,
            "versao": "4.3.3",
        },
        versao_minima="4.0.0",
    )
    assert not avaliacao.apto
    assert "em_execucao" in avaliacao.pendencias
    assert avaliacao.consertos, "toda pendência precisa vir com o que fazer"


def test_versao_incompativel_reprova():
    avaliacao = assinador.avaliar(
        {
            "instalado": True,
            "em_execucao": True,
            "hosts_mapeado": True,
            "porta_local": True,
            "certificado_visivel": True,
            "permissao_navegador": True,
            "versao": "3.9.1",
        },
        versao_minima="4.0.0",
    )
    assert not avaliacao.apto
    assert "versao_compativel" in avaliacao.pendencias


def test_ambiente_completo_aprova():
    avaliacao = assinador.avaliar(
        {
            "instalado": True,
            "em_execucao": True,
            "hosts_mapeado": True,
            "porta_local": True,
            "certificado_visivel": True,
            "permissao_navegador": True,
            "versao": "4.3.3",
        },
        versao_minima="4.0.0",
    )
    assert avaliacao.apto
    assert "4.3.3" in avaliacao.resumo


@pytest.mark.parametrize(
    "atual,minima,esperado",
    [
        ("4.3.3", "4.0.0", True),
        ("4.0.0", "4.0.0", True),
        ("3.9.9", "4.0.0", False),
        ("4.10.0", "4.9.0", True),
        ("", "4.0.0", False),
    ],
)
def test_comparacao_de_versao(atual, minima, esperado):
    assert assinador.comparar_versao(atual, minima) is esperado


# ---------------------------------------------------------------------------
# Portal
# ---------------------------------------------------------------------------


def test_ancoras_presentes_nao_levantam_erro():
    portal.verificar_ancoras(
        EtapaFluxo.MINHAS_AUTORIZACOES,
        "Minhas Autorizações de Acesso — Concedidas e Recebidas",
    )


def test_ancora_ausente_vira_portal_alterado():
    """Critério E: portal mudou → para, não improvisa."""
    with pytest.raises(portal.PortalAlteradoError) as erro:
        portal.verificar_ancoras(
            EtapaFluxo.NOVA_AUTORIZACAO_PESSOA, "Página em manutenção", url="https://x"
        )
    assert erro.value.ausentes
    detalhe = portal.descrever_mudanca(erro.value)
    assert detalhe["etapa"] == EtapaFluxo.NOVA_AUTORIZACAO_PESSOA.value
    assert "portal.py" in detalhe["acao"]


def test_comparacao_de_ancora_ignora_acento_e_caixa():
    portal.verificar_ancoras(EtapaFluxo.VALIDACAO, "clique em VALIDAR para aceitar")


def test_so_dominios_oficiais_sao_aceitos():
    assert portal.url_permitida("https://servicos.receitafederal.gov.br/autorizacoes")
    assert portal.url_permitida("https://cav.receita.fazenda.gov.br/autenticacao/login")
    assert not portal.url_permitida("http://servicos.receitafederal.gov.br")
    assert not portal.url_permitida("https://servicos.receitafederal.gov.br.evil.com")
    assert not portal.url_permitida("https://localhost:8080")


def test_roteiro_cobre_as_duas_fases_com_identidade_correta():
    outorga = portal.roteiro_da_fase(FaseJob.OUTORGA)
    aceite = portal.roteiro_da_fase(FaseJob.ACEITE)
    assert outorga and aceite
    assert all(passo.certificado == "cliente" for passo in outorga)
    assert all(passo.certificado == "contabilidade" for passo in aceite)


def test_roteiro_serializado_tem_tudo_que_a_tela_precisa():
    for item in portal.roteiro_serializado():
        assert item["titulo"] and item["instrucao"]
        assert item["executor"] in {"operador", "sistema"}


# ---------------------------------------------------------------------------
# Normalização de fontes
# ---------------------------------------------------------------------------


def test_validade_vencida_vence_rotulo_otimista():
    ontem = date.today() - timedelta(days=1)
    assert situacao_por_validade(ontem) is StatusAutorizacao.EXPIRADA
    amanha = date.today() + timedelta(days=1)
    assert situacao_por_validade(amanha) is StatusAutorizacao.ATIVA
    assert situacao_por_validade(None) is StatusAutorizacao.SEM_AUTORIZACAO


def test_registro_normaliza_documento():
    registro = RegistroProcuracao(documento="12.345.678/0001-95").normalizado()
    assert registro.documento == "12345678000195"


def test_registro_com_documento_invalido_falha():
    with pytest.raises(ValueError):
        RegistroProcuracao(documento="abc").normalizado()


def test_planilha_le_csv_com_ponto_e_virgula():
    conteudo = (
        "cnpj;razao_social;situacao;data_validade;servicos\n"
        "12.345.678/0001-95;EMPRESA A LTDA;ativa;31/12/2030;ALL\n"
        "98.765.432/0001-10;EMPRESA B LTDA;sem procuração;;\n"
    ).encode("utf-8")
    registros = FontePlanilha(conteudo).listar()
    assert len(registros) == 2
    assert registros[0].documento == "12345678000195"
    assert registros[0].situacao is StatusAutorizacao.ATIVA
    assert registros[0].servicos[0].codigo == "ALL"
    assert registros[1].situacao is StatusAutorizacao.SEM_AUTORIZACAO


def test_planilha_marca_expirada_mesmo_com_rotulo_ativa():
    conteudo = (
        "cnpj;situacao;data_validade\n12345678000195;ativa;01/01/2020\n"
    ).encode("utf-8")
    registros = FontePlanilha(conteudo).listar()
    assert registros[0].situacao is StatusAutorizacao.EXPIRADA


def test_planilha_sem_coluna_de_documento_e_recusada():
    from app.procuracoes.integracoes.base import FonteError

    with pytest.raises(FonteError):
        FontePlanilha(b"nome;situacao\nEmpresa;ativa\n").listar()


def test_intervencao_manual_e_alcancavel_de_todo_estado_nao_terminal():
    """Regressão do job da R10: `pendente` e `aguardando_agente` recusavam
    intervenção — o grafo foi escrito do ponto de vista do Agent, que só
    relata problema depois de assumir. A pessoa pode precisar assumir antes."""
    for status in StatusJob:
        if status in ESTADOS_TERMINAIS:
            continue
        assert transicao_valida(status, StatusJob.INTERVENCAO_MANUAL), (
            f"{status.value} → intervencao_manual deveria ser permitido"
        )


def test_fechamento_manual_de_fase_passa_pelo_grafo():
    """O caminho manual (sem estação) atravessa os mesmos marcos, do mesmo
    jeito: intervenção → assinado e aguardando_validacao → concluído."""
    assert transicao_valida(StatusJob.INTERVENCAO_MANUAL, StatusJob.ASSINADO)
    assert transicao_valida(StatusJob.AGUARDANDO_VALIDACAO, StatusJob.CONCLUIDO)
    # E o salto impossível continua impossível: ninguém "conclui" sem a fase
    # de aceite ter sido registrada.
    assert not transicao_valida(StatusJob.ASSINADO, StatusJob.CONCLUIDO)


def test_codigo_de_intervencao_solicitada_tem_texto_honesto():
    regra = regra_do_erro(CodigoErro.INTERVENCAO_SOLICITADA)
    assert regra.classe is ClasseErro.MANUAL
    assert "pessoa" in regra.explicacao
    # A frase nega o desafio em vez de afirmar um que não houve.
    assert "nenhum desafio do portal foi detectado" in regra.explicacao
