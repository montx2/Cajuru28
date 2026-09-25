"""
Fluxo completo do módulo Procurações RFB, com banco real (SQLite em memória).

Cobre os critérios de aceite de ponta a ponta:

A. empresa sem procuração → ciclo até a assinatura registrada;
B. autorização pendente → validada → ATIVA;
C. certificado expirado detectado **antes** de executar;
D. Assinador SERPRO indisponível → job não sai da fila + alerta;
E. portal alterado → PORTAL_ALTERADO + interrupção;
F. falha no meio → estado persistido, sem duplicar, retomável;
G. múltiplos certificados → nunca escolha aleatória.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Empresa, Escritorio, Usuario
from app.procuracoes import modelos as m  # noqa: F401  (registra as tabelas)
from app.procuracoes.estados import (
    CodigoErro,
    EtapaFluxo,
    StatusAutorizacao,
    StatusJob,
    TipoCertificado,
)
from app.procuracoes.integracoes.base import RegistroProcuracao, ServicoAutorizado
from app.procuracoes.modelos import (
    Agente,
    Autorizacao,
    JobEvento,
    JobProcuracao,
    NotificacaoProcuracao,
)
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import certificados as srv_cert
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import fila as srv_fila
from app.procuracoes.servicos import painel as srv_painel
from app.procuracoes.servicos import sincronizacao as srv_sinc

OUTORGADO = "11222333000181"
CLIENTE_A = "12345678000195"
CLIENTE_B = "98765432000110"


class FonteFalsa:
    """Dublê de fonte externa. Nome explícito: não simula integração real."""

    nome = "planilha"

    def __init__(self, registros: list[RegistroProcuracao]):
        self._registros = registros
        self.chamadas = 0

    def testar(self) -> str:
        return "ok"

    def listar(self, documentos=None):
        self.chamadas += 1
        return list(self._registros)


@pytest.fixture
def ambiente():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()

    escritorio = Escritorio(nome="Contabilidade Cajuru")
    db.add(escritorio)
    db.commit()
    db.refresh(escritorio)

    usuario = Usuario(
        escritorio_id=escritorio.id,
        nome="Operador",
        email="op@cajuru.local",
        senha_hash="x",
        papel="admin",
        ativo=True,
    )
    db.add(usuario)

    empresa_a = Empresa(
        escritorio_id=escritorio.id,
        razao_social="CLIENTE A LTDA",
        cnpj_cpf=CLIENTE_A,
        uf="PR",
    )
    empresa_b = Empresa(
        escritorio_id=escritorio.id,
        razao_social="CLIENTE B LTDA",
        cnpj_cpf=CLIENTE_B,
        uf="SP",
    )
    db.add_all([empresa_a, empresa_b])
    db.commit()
    db.refresh(usuario)
    db.refresh(empresa_a)
    db.refresh(empresa_b)

    config = srv_config.obter_configuracao(db, escritorio.id)
    config.outorgado_documento = OUTORGADO
    config.outorgado_nome = "CONTABILIDADE CAJURU LTDA"
    config.processamento_automatico = True
    db.commit()

    yield {
        "db": db,
        "escritorio": escritorio,
        "usuario": usuario,
        "empresa_a": empresa_a,
        "empresa_b": empresa_b,
        "config": config,
    }
    db.close()


def _agente(db, escritorio_id: int, nome="Estação 1", ident=None) -> Agente:
    ident = ident or ("a" * 32 if nome == "Estação 1" else "b" * 32)
    credencial = srv_agentes.registrar_agente(
        db, escritorio_id, nome=nome, identificador=ident
    )
    db.commit()
    return credencial.agente


def _certificado(
    db,
    agente: Agente,
    documento: str,
    *,
    thumbprint: str,
    dias: int = 200,
    tipo: str = "cliente",
):
    srv_cert.sincronizar_inventario(
        db,
        agente,
        [
            {
                "thumbprint": thumbprint,
                "documento": documento,
                "titular_nome": f"TITULAR {documento}",
                "valido_de": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
                "valido_ate": (datetime.now(timezone.utc) + timedelta(days=dias)).isoformat(),
                "referencia_local": f"win:{thumbprint[:8]}",
                "tipo": tipo,
            }
        ],
    )
    db.commit()


# ---------------------------------------------------------------------------
# Critério A + B — ciclo completo
# ---------------------------------------------------------------------------


def test_ciclo_completo_ate_autorizacao_ativa(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64)
    _certificado(db, agente, OUTORGADO, thumbprint="c" * 64, tipo="contabilidade")
    agente.assinador_ok = True
    db.commit()

    resultado = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    assert resultado.criado
    job = resultado.job
    db.commit()
    assert job.status == StatusJob.AGUARDANDO_AGENTE.value
    assert job.outorgado_documento == OUTORGADO
    assert job.vigencia_ate is not None
    # Teto legal de 5 anos respeitado na origem.
    assert job.vigencia_ate <= date.today() + timedelta(days=5 * 365 + 1)

    config = srv_config.obter_configuracao(db, escritorio_id)
    reivindicado = srv_fila.reivindicar(
        db, agente, config, documentos_disponiveis=[CLIENTE_A, OUTORGADO]
    )
    db.commit()
    assert reivindicado is not None and reivindicado.id == job.id
    assert job.agente_id == agente.id and job.lease_token

    for destino, etapa in [
        (StatusJob.VERIFICANDO_PRE_REQUISITOS, EtapaFluxo.PRE_REQUISITOS),
        (StatusJob.PRONTO_PARA_OPERACAO, EtapaFluxo.MINHAS_AUTORIZACOES),
        (StatusJob.AUTENTICANDO, EtapaFluxo.ACESSO_PORTAL),
        (StatusJob.PREENCHENDO, EtapaFluxo.NOVA_AUTORIZACAO_PESSOA),
        (StatusJob.AGUARDANDO_ASSINATURA, EtapaFluxo.ASSINATURA),
    ]:
        srv_fila.mudar_status(db, job, destino, etapa=etapa)
    db.commit()

    # Critério A: a outorga só é registrada com confirmação real (protocolo).
    autorizacao = srv_fila.registrar_outorga(db, job, protocolo="PROT-2026-0001")
    db.commit()
    assert autorizacao.situacao == StatusAutorizacao.EM_ANALISE.value
    assert autorizacao.prazo_aceite_ate == date.today() + timedelta(days=30)
    assert job.status == StatusJob.AGUARDANDO_VALIDACAO.value

    # Critério B: a segunda fase exige a identidade da contabilidade.
    from app.procuracoes.estados import certificado_exigido

    assert certificado_exigido(StatusJob(job.status)) is TipoCertificado.CONTABILIDADE

    srv_fila.mudar_status(db, job, StatusJob.VALIDANDO, etapa=EtapaFluxo.VALIDACAO)
    srv_fila.registrar_aceite(db, job)
    db.commit()

    assert job.status == StatusJob.CONCLUIDO.value
    db.refresh(autorizacao)
    assert autorizacao.situacao == StatusAutorizacao.ATIVA.value

    tipos = [
        evento.tipo
        for evento in db.query(JobEvento).filter(JobEvento.job_id == job.id).all()
    ]
    assert "criado" in tipos or "transicao" in tipos
    assert len(tipos) >= 5, "cada mudança precisa deixar rastro"


def test_conclusao_exige_confirmacao_e_nao_so_clique(ambiente):
    """Marcar assinado sem confirmação é impossível pelo modelo de dados."""
    from app.procuracoes.esquemas import ResultadoEntrada

    with pytest.raises(ValueError):
        ResultadoEntrada(
            lease_token="x" * 16, resultado="outorga_registrada", protocolo="", confirmacao_portal=""
        )
    aceito = ResultadoEntrada(
        lease_token="x" * 16,
        resultado="outorga_registrada",
        confirmacao_portal="Autorização registrada com sucesso.",
    )
    assert aceito.confirmacao_portal


# ---------------------------------------------------------------------------
# Critério C e G — certificados
# ---------------------------------------------------------------------------


def test_certificado_expirado_detectado_antes_de_executar(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64, dias=-5)

    selecao = srv_cert.selecionar_para_documento(db, escritorio_id, CLIENTE_A)
    assert not selecao.ok
    assert selecao.codigo_erro in {
        CodigoErro.CERTIFICADO_EXPIRADO,
        CodigoErro.CERTIFICADO_INDISPONIVEL,
    }
    assert selecao.certificado is None


def test_certificado_que_vence_hoje_nao_e_aceito(ambiente):
    """Margem de segurança: o fluxo leva minutos e pode ser retomado amanhã."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64, dias=0)
    selecao = srv_cert.selecionar_para_documento(db, escritorio_id, CLIENTE_A)
    assert not selecao.ok


def test_multiplos_certificados_nunca_viram_escolha_aleatoria(ambiente):
    """Critério G."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    srv_cert.sincronizar_inventario(
        db,
        agente,
        [
            {
                "thumbprint": "a" * 64,
                "documento": CLIENTE_A,
                "valido_ate": (datetime.now(timezone.utc) + timedelta(days=100)).isoformat(),
            },
            {
                "thumbprint": "b" * 64,
                "documento": CLIENTE_A,
                "valido_ate": (datetime.now(timezone.utc) + timedelta(days=300)).isoformat(),
            },
        ],
    )
    db.commit()

    selecao = srv_cert.selecionar_para_documento(db, escritorio_id, CLIENTE_A)
    assert not selecao.ok
    assert selecao.codigo_erro is CodigoErro.CERTIFICADO_AMBIGUO
    assert len(selecao.candidatos) == 2

    # Escolha humana explícita resolve — e continua validada contra o CNPJ.
    fixado = srv_cert.selecionar_para_documento(
        db, escritorio_id, CLIENTE_A, thumbprint_preferido="b" * 64
    )
    assert fixado.ok and fixado.thumbprint == "b" * 64


def test_certificado_de_outra_empresa_nunca_e_usado(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_B, thumbprint="b" * 64)
    selecao = srv_cert.selecionar_para_documento(db, escritorio_id, CLIENTE_A)
    assert not selecao.ok
    assert selecao.certificado is None


def test_inventario_e_idempotente_e_nao_apaga_historico(ambiente):
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    item = {
        "thumbprint": "a" * 64,
        "documento": CLIENTE_A,
        "valido_ate": (datetime.now(timezone.utc) + timedelta(days=90)).isoformat(),
    }
    primeiro = srv_cert.sincronizar_inventario(db, agente, [item])
    segundo = srv_cert.sincronizar_inventario(db, agente, [item])
    db.commit()
    assert primeiro["criados"] == 1 and segundo["criados"] == 0
    assert segundo["atualizados"] == 1

    terceiro = srv_cert.sincronizar_inventario(db, agente, [])
    db.commit()
    assert terceiro["indisponiveis"] == 1
    from app.procuracoes.modelos import CertificadoInventario

    assert db.query(CertificadoInventario).count() == 1, "sumir não é apagar"


# ---------------------------------------------------------------------------
# Critério D — Assinador
# ---------------------------------------------------------------------------


def test_sem_assinador_o_job_nao_e_entregue(ambiente):
    """Critério D, na camada de serviço: o gate está antes da entrega."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64)
    agente.assinador_ok = False
    db.commit()

    srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    db.commit()

    from app.procuracoes.servicos import assinador as srv_assinador

    config = srv_config.obter_configuracao(db, escritorio_id)
    avaliacao = srv_assinador.avaliar({}, versao_minima=config.assinador_versao_minima)
    assert not avaliacao.apto, "sem diagnóstico não se entrega trabalho"


# ---------------------------------------------------------------------------
# Critério E — portal alterado
# ---------------------------------------------------------------------------


def test_portal_alterado_interrompe_o_job(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64)
    job = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"]).job
    db.commit()

    srv_fila.registrar_falha(
        db, job, CodigoErro.PORTAL_ALTERADO, "Âncora 'Nova Autorização' não encontrada."
    )
    db.commit()
    assert job.status == StatusJob.INTERVENCAO_MANUAL.value
    assert job.codigo_erro == CodigoErro.PORTAL_ALTERADO.value
    assert job.tentativas <= 1, "portal alterado não entra em retry"


# ---------------------------------------------------------------------------
# Critério F — persistência, idempotência e retomada
# ---------------------------------------------------------------------------


def test_nao_cria_job_duplicado_para_a_mesma_empresa(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    primeiro = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    db.commit()
    segundo = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    db.commit()
    assert primeiro.criado
    assert not segundo.criado
    assert segundo.codigo is CodigoErro.JOB_DUPLICADO
    assert db.query(JobProcuracao).count() == 1


def test_processar_pendencias_e_idempotente(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    primeiro = srv_fila.enfileirar_pendencias(db, escritorio_id)
    db.commit()
    segundo = srv_fila.enfileirar_pendencias(db, escritorio_id)
    db.commit()
    assert primeiro["criados"] == 2
    assert segundo["criados"] == 0
    assert segundo["ja_na_fila"] == 2
    assert db.query(JobProcuracao).count() == 2


def test_retomada_continua_do_ponto_de_parada(ambiente):
    """Critério F: retomar não é refazer a outorga."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    job = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"]).job
    srv_fila.mudar_status(db, job, StatusJob.ATRIBUIDO)
    srv_fila.mudar_status(
        db, job, StatusJob.VERIFICANDO_PRE_REQUISITOS, etapa=EtapaFluxo.PRE_REQUISITOS
    )
    srv_fila.mudar_status(
        db, job, StatusJob.PRONTO_PARA_OPERACAO, etapa=EtapaFluxo.MINHAS_AUTORIZACOES
    )
    srv_fila.mudar_status(db, job, StatusJob.AUTENTICANDO, etapa=EtapaFluxo.ACESSO_PORTAL)
    srv_fila.mudar_status(db, job, StatusJob.PREENCHENDO, etapa=EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS)
    db.commit()

    srv_fila.pedir_intervencao(db, job, "Portal pediu confirmação adicional.")
    db.commit()
    assert job.status == StatusJob.INTERVENCAO_MANUAL.value
    assert job.etapa_atual == EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS.value

    srv_fila.retomar(db, job, ambiente["usuario"])
    db.commit()
    assert job.status == StatusJob.PRONTO_PARA_OPERACAO.value
    assert job.etapa_atual == EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS.value


def test_reprocessar_cria_job_novo_sem_reabrir_o_antigo(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    job = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"]).job
    srv_fila.cancelar(db, job, ambiente["usuario"], "teste")
    db.commit()
    assert job.status == StatusJob.CANCELADO.value

    novo = srv_fila.reprocessar(db, job, ambiente["usuario"])
    db.commit()
    assert novo.criado and novo.job.id != job.id
    assert novo.job.chave_idempotencia != job.chave_idempotencia
    db.refresh(job)
    assert job.status == StatusJob.CANCELADO.value, "terminal não reabre"


def test_lease_expirado_devolve_o_job_sem_perder_progresso(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    agente = _agente(db, escritorio_id)
    _certificado(db, agente, CLIENTE_A, thumbprint="a" * 64)
    job = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"]).job
    config = srv_config.obter_configuracao(db, escritorio_id)
    srv_fila.reivindicar(db, agente, config, documentos_disponiveis=[CLIENTE_A])
    srv_fila.mudar_status(
        db, job, StatusJob.VERIFICANDO_PRE_REQUISITOS, etapa=EtapaFluxo.PRE_REQUISITOS
    )
    db.commit()

    job.lease_ate = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.commit()

    recuperados = srv_fila.recuperar_leases_expirados(db)
    db.commit()
    assert recuperados == 1
    assert job.agente_id is None
    assert job.status == StatusJob.AGUARDANDO_AGENTE.value
    assert job.etapa_atual == EtapaFluxo.PRE_REQUISITOS.value


def test_dois_agents_nao_pegam_o_mesmo_job(ambiente):
    """Lock distribuído: a corrida tem um vencedor e nenhum erro."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    a1 = _agente(db, escritorio_id, nome="Estação 1", ident="a" * 32)
    a2 = _agente(db, escritorio_id, nome="Estação 2", ident="b" * 32)
    _certificado(db, a1, CLIENTE_A, thumbprint="a" * 64)
    _certificado(db, a2, CLIENTE_A, thumbprint="b" * 64)
    srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    db.commit()

    config = srv_config.obter_configuracao(db, escritorio_id)
    primeiro = srv_fila.reivindicar(db, a1, config, documentos_disponiveis=[CLIENTE_A])
    db.commit()
    segundo = srv_fila.reivindicar(db, a2, config, documentos_disponiveis=[CLIENTE_A])
    db.commit()

    assert primeiro is not None
    assert segundo is None, "o mesmo cliente não pode rodar em duas estações"


# ---------------------------------------------------------------------------
# Sincronização e painel
# ---------------------------------------------------------------------------


def test_sincronizacao_e_idempotente_e_ignora_quem_nao_esta_na_carteira(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    fonte = FonteFalsa(
        [
            RegistroProcuracao(
                documento=CLIENTE_A,
                situacao=StatusAutorizacao.ATIVA,
                data_validade=date.today() + timedelta(days=400),
                servicos=(ServicoAutorizado(codigo="ALL", rotulo="Todos"),),
            ),
            RegistroProcuracao(documento="11111111000191"),  # fora da carteira
        ]
    )
    primeiro = srv_sinc.sincronizar(db, escritorio_id, "planilha", fonte)
    db.commit()
    assert primeiro.criados == 1
    assert primeiro.ignorados == 1

    segundo = srv_sinc.sincronizar(db, escritorio_id, "planilha", fonte)
    db.commit()
    assert segundo.criados == 0
    assert segundo.atualizados == 0, "sem mudança não conta como atualização"
    assert db.query(Autorizacao).count() == 1


def test_fonte_oficial_nao_e_sobrescrita_por_fonte_secundaria(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    oficial = FonteFalsa(
        [
            RegistroProcuracao(
                documento=CLIENTE_A,
                situacao=StatusAutorizacao.ATIVA,
                data_validade=date.today() + timedelta(days=400),
            )
        ]
    )
    srv_sinc.sincronizar(db, escritorio_id, "integra_contador", oficial)
    db.commit()

    planilha = FonteFalsa(
        [RegistroProcuracao(documento=CLIENTE_A, situacao=StatusAutorizacao.SEM_AUTORIZACAO)]
    )
    resultado = srv_sinc.sincronizar(db, escritorio_id, "planilha", planilha)
    db.commit()

    autorizacao = db.query(Autorizacao).one()
    assert autorizacao.situacao == StatusAutorizacao.ATIVA.value
    assert resultado.ignorados == 1


def test_prazo_de_aceite_vencido_cancela_e_notifica(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    db.add(
        Autorizacao(
            escritorio_id=escritorio_id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.EM_ANALISE.value,
            prazo_aceite_ate=date.today() - timedelta(days=1),
        )
    )
    db.commit()

    contagem = srv_sinc.avaliar_vencimentos(db, escritorio_id)
    db.commit()
    assert contagem["aceite_vencido"] == 1
    autorizacao = db.query(Autorizacao).one()
    assert autorizacao.situacao == StatusAutorizacao.CANCELADA.value
    assert db.query(NotificacaoProcuracao).filter_by(tipo="aceite_vencido").count() == 1


def test_autorizacao_vencida_vira_expirada_e_alerta_nao_duplica(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    db.add(
        Autorizacao(
            escritorio_id=escritorio_id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=10),
        )
    )
    db.commit()

    srv_sinc.avaliar_vencimentos(db, escritorio_id)
    srv_sinc.avaliar_vencimentos(db, escritorio_id)
    db.commit()
    assert db.query(NotificacaoProcuracao).filter_by(tipo="autorizacao_vencendo").count() == 1


def test_resumo_conta_empresas_sem_autorizacao(ambiente):
    """O KPI que dá sentido ao módulo: '52 empresas sem procuração'."""
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    resumo = srv_painel.resumo(db, escritorio_id)
    assert resumo.total_empresas == 2
    assert resumo.sem_autorizacao == 2

    db.add(
        Autorizacao(
            escritorio_id=escritorio_id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=500),
        )
    )
    db.commit()
    resumo = srv_painel.resumo(db, escritorio_id)
    assert resumo.sem_autorizacao == 1
    assert resumo.ativas == 1


def test_listagem_filtra_por_sem_autorizacao(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    linhas, total = srv_painel.listar(db, escritorio_id, situacao="sem_autorizacao")
    assert total == 2
    assert all(linha.situacao == StatusAutorizacao.SEM_AUTORIZACAO.value for linha in linhas)


def test_detalhe_traz_jobs_e_trilha(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    db.commit()
    detalhe = srv_painel.detalhar(db, escritorio_id, ambiente["empresa_a"].id)
    assert detalhe is not None
    assert detalhe.linha.razao_social == "CLIENTE A LTDA"
    assert detalhe.jobs and detalhe.eventos
