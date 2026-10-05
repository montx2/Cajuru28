"""
Pré-voo do lote, relatório consolidado e métricas.

O contrato que estes testes protegem:

- o pré-voo **não tem efeito colateral** (rodar duas vezes não cria nada);
- ele concorda com a fila: o que o pré-voo diz APTO, `criar_job` aceita; o que
  ele diz BLOQUEADO, `criar_job` recusa. Divergência aqui tornaria o pré-voo
  pior que inútil, porque daria falsa confiança antes de um ato jurídico;
- "já autorizada" é DISPENSADO, não erro — misturar as duas coisas faz o
  operador caçar problema que não existe;
- o relatório exportado sai com documento mascarado por padrão;
- a métrica separa espera humana de processamento.
"""

from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models import Empresa, Escritorio, Usuario
from app.procuracoes import modelos as m  # noqa: F401  (registra as tabelas)
from app.procuracoes.estados import StatusAutorizacao, StatusJob
from app.procuracoes.modelos import (
    Agente,
    Autorizacao,
    JobEvento,
    JobProcuracao,
    ModeloAutorizacao,
    ModeloAutorizacaoServico,
    ProcuracaoConfiguracao,
)
from app.procuracoes.servicos import agentes as srv_agentes
from app.procuracoes.servicos import certificados as srv_cert
from app.procuracoes.servicos import configuracao as srv_config
from app.procuracoes.servicos import fila as srv_fila
from app.procuracoes.servicos import prevoo as srv_prevoo
from app.procuracoes.servicos import relatorio as srv_relatorio

OUTORGADO = "11222333000181"
CLIENTE_A = "12345678000195"
CLIENTE_B = "98765432000110"


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


def _agente(db, escritorio_id: int, *, online=True, assinador=True) -> Agente:
    credencial = srv_agentes.registrar_agente(
        db, escritorio_id, nome="Estação 1", identificador="a" * 32
    )
    agente = credencial.agente
    if online:
        agente.ultimo_heartbeat_em = datetime.now(timezone.utc)
    agente.assinador_ok = assinador
    db.commit()
    return agente


def _inventariar(db, agente, itens: list[tuple[str, str, int]]):
    """Sincroniza o inventário da estação de uma vez só.

    Em uma chamada, e não uma por certificado: `sincronizar_inventario` marca
    como `indisponivel` todo thumbprint ausente do lote enviado — que é o
    comportamento correto (o Agent manda a foto completa da máquina), mas
    transforma duas chamadas seguidas em "o primeiro certificado sumiu".
    """
    agora = datetime.now(timezone.utc)
    srv_cert.sincronizar_inventario(
        db,
        agente,
        [
            {
                "thumbprint": thumbprint,
                "documento": documento,
                "titular_nome": f"TITULAR {documento}",
                "valido_de": (agora - timedelta(days=10)).isoformat(),
                "valido_ate": (agora + timedelta(days=dias)).isoformat(),
                "referencia_local": f"win:{thumbprint[:8]}",
            }
            for documento, thumbprint, dias in itens
        ],
    )
    db.commit()


def _pronto(ambiente):
    """Ambiente feliz: estação online, assinador ok, certificados presentes."""
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    _inventariar(
        db, agente, [(CLIENTE_A, "a" * 64, 200), (CLIENTE_B, "b" * 64, 200)]
    )
    return agente


# ---------------------------------------------------------------------------
# Ambiente
# ---------------------------------------------------------------------------


def test_sem_outorgado_bloqueia_o_lote_inteiro(ambiente):
    db = ambiente["db"]
    ambiente["config"].outorgado_documento = ""
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    assert relatorio.bloqueio_de_ambiente is True
    assert relatorio.pode_iniciar is False
    assert any(a.codigo == "OUTORGADO_AUSENTE" for a in relatorio.ambiente)
    # Não adianta listar 137 empresas todas com o mesmo motivo.
    assert relatorio.linhas == []


def test_outorgado_com_documento_invalido_bloqueia(ambiente):
    db = ambiente["db"]
    ambiente["config"].outorgado_documento = "11111111111111"
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    assert any(a.codigo == "OUTORGADO_INVALIDO" for a in relatorio.ambiente)
    assert relatorio.pode_iniciar is False


def test_sem_estacao_e_atencao_e_nao_bloqueio(ambiente):
    """Sem estação o lote entra na fila e espera — é ressalva, não impedimento."""
    db = ambiente["db"]
    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    codigos = {a.codigo for a in relatorio.ambiente}
    assert "SEM_ESTACAO" in codigos
    assert relatorio.bloqueio_de_ambiente is False


def test_estacao_offline_e_sinalizada(ambiente):
    db = ambiente["db"]
    _agente(db, ambiente["escritorio"].id, online=False)
    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    assert any(a.codigo == "ESTACAO_OFFLINE" for a in relatorio.ambiente)


def test_assinador_nao_apto_e_sinalizado(ambiente):
    db = ambiente["db"]
    _agente(db, ambiente["escritorio"].id, assinador=False)
    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    assert any(a.codigo == "ASSINADOR_INDISPONIVEL" for a in relatorio.ambiente)


# ---------------------------------------------------------------------------
# Por empresa
# ---------------------------------------------------------------------------


def test_empresa_pronta_fica_apta(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.APTO
    assert linha.vigencia_prevista is not None


def test_sem_certificado_bloqueia_a_empresa(ambiente):
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    _inventariar(db, agente, [(CLIENTE_A, "a" * 64, 200)])  # B fica sem

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_b"].id)
    assert linha.situacao is srv_prevoo.Situacao.BLOQUEADO


def test_certificado_vencido_bloqueia_antes_de_qualquer_sessao(ambiente):
    """Critério C do módulo, agora aplicado ao lote inteiro de uma vez."""
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    _inventariar(db, agente, [(CLIENTE_A, "a" * 64, -3)])

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.BLOQUEADO


def test_certificado_vencendo_e_atencao_e_continua_operavel(ambiente):
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    _inventariar(db, agente, [(CLIENTE_A, "a" * 64, 12), (CLIENTE_B, "b" * 64, 200)])

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.ATENCAO
    assert any(a.codigo == "CERTIFICADO_VENCENDO" for a in linha.achados)


def test_autorizacao_ativa_e_dispensada_nao_bloqueada(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=900),
        )
    )
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.DISPENSADO
    assert relatorio.contagem()["dispensado"] == 1


def test_autorizacao_ativa_sem_certificado_nao_bloqueia(ambiente):
    """A fila dispensa autorização ativa antes de exigir certificado novo."""
    db = ambiente["db"]
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=900),
        )
    )
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.DISPENSADO
    assert not any(a.codigo == "CERTIFICADO_INDISPONIVEL" for a in linha.achados)


def test_autorizacao_perto_de_vencer_entra_como_renovacao(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=15),
        )
    )
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert linha.situacao is srv_prevoo.Situacao.ATENCAO
    assert any(a.codigo == "RENOVACAO" for a in linha.achados)


def test_prazo_de_aceite_vencido_e_sinalizado(ambiente):
    """Os 30 dias que a Receita cancela sozinha — o alerta mais acionável."""
    db = ambiente["db"]
    _pronto(ambiente)
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.AGUARDANDO_ACEITE.value,
            prazo_aceite_ate=date.today() - timedelta(days=1),
        )
    )
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert any(a.codigo == "PRAZO_ACEITE_VENCIDO" for a in linha.achados)


def test_empresa_com_documento_igual_ao_outorgado_e_bloqueada(ambiente):
    """Outorgar para si mesmo não existe; o portal recusaria no passo 1."""
    db = ambiente["db"]
    _pronto(ambiente)
    ambiente["empresa_b"].cnpj_cpf = OUTORGADO
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_b"].id)
    assert any(a.codigo == "OUTORGA_PARA_SI" for a in linha.achados)
    assert linha.situacao is srv_prevoo.Situacao.BLOQUEADO


def test_job_em_andamento_evita_duplicidade(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa_a"])
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert any(a.codigo == "JOB_EM_ANDAMENTO" for a in linha.achados)


def test_job_ativo_sem_certificado_nao_sugere_novo_lote(ambiente):
    db = ambiente["db"]
    srv_fila.criar_job(db, ambiente["escritorio"].id, ambiente["empresa_a"])
    db.commit()

    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    linha = next(x for x in relatorio.linhas if x.empresa_id == ambiente["empresa_a"].id)
    assert any(a.codigo == "JOB_EM_ANDAMENTO" for a in linha.achados)
    assert not any(a.codigo == "CERTIFICADO_INDISPONIVEL" for a in linha.achados)
    assert relatorio.pode_iniciar is False


def test_filtro_por_empresa_restringe_o_lote(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    relatorio = srv_prevoo.executar(
        db, ambiente["escritorio"].id, empresa_ids=[ambiente["empresa_a"].id]
    )
    assert len(relatorio.linhas) == 1


# ---------------------------------------------------------------------------
# Propriedades estruturais
# ---------------------------------------------------------------------------


def test_prevoo_nao_tem_efeito_colateral(ambiente):
    """Rodar o pré-voo não pode criar jobs, modelos, config ou eventos."""
    db = ambiente["db"]
    _pronto(ambiente)
    escritorio_id = ambiente["escritorio"].id

    tabelas = (
        JobProcuracao,
        JobEvento,
        Autorizacao,
        ProcuracaoConfiguracao,
        ModeloAutorizacao,
        ModeloAutorizacaoServico,
    )
    antes = tuple(db.query(modelo).count() for modelo in tabelas)
    srv_prevoo.executar(db, escritorio_id)
    srv_prevoo.executar(db, escritorio_id)
    depois = tuple(db.query(modelo).count() for modelo in tabelas)

    assert antes == depois
    assert antes == (0, 0, 0, 1, 0, 0)
    assert not db.new
    assert not db.dirty
    assert not db.deleted


def test_prevoo_sem_configuracao_avalia_defaults_sem_gravar(ambiente):
    db = ambiente["db"]
    escritorio_id = ambiente["escritorio"].id
    db.query(ProcuracaoConfiguracao).filter(
        ProcuracaoConfiguracao.escritorio_id == escritorio_id
    ).delete()
    db.commit()

    relatorio = srv_prevoo.executar(db, escritorio_id)

    assert relatorio.bloqueio_de_ambiente is True
    assert any(a.codigo == "OUTORGADO_AUSENTE" for a in relatorio.ambiente)
    assert db.query(ProcuracaoConfiguracao).filter(
        ProcuracaoConfiguracao.escritorio_id == escritorio_id
    ).count() == 0
    assert db.query(ModeloAutorizacao).filter(
        ModeloAutorizacao.escritorio_id == escritorio_id
    ).count() == 0
    assert not db.new
    assert not db.dirty
    assert not db.deleted


def test_prevoo_e_a_fila_concordam(ambiente):
    """Se o pré-voo aprova, `criar_job` aceita. Se bloqueia, recusa.

    É a propriedade que dá sentido ao pré-voo: prometer no relatório algo que
    a fila depois recusa seria pior do que não ter pré-voo nenhum.
    """
    db = ambiente["db"]
    agente = _agente(db, ambiente["escritorio"].id)
    _inventariar(db, agente, [(CLIENTE_A, "a" * 64, 200)])  # B sem certificado
    escritorio_id = ambiente["escritorio"].id

    relatorio = srv_prevoo.executar(db, escritorio_id)
    por_empresa = {linha.empresa_id: linha for linha in relatorio.linhas}

    for empresa in (ambiente["empresa_a"], ambiente["empresa_b"]):
        linha = por_empresa[empresa.id]
        resultado = srv_fila.criar_job(db, escritorio_id, empresa)
        db.commit()
        if linha.situacao is srv_prevoo.Situacao.APTO:
            assert resultado.criado, f"{empresa.razao_social} foi aprovada mas recusada"
        # Empresa sem certificado entra na fila e trava na triagem; o pré-voo
        # antecipa isso, que é exatamente o ponto.
        if linha.situacao is srv_prevoo.Situacao.BLOQUEADO:
            triagem = srv_fila.triar_por_certificado(db, escritorio_id)
            assert triagem["bloqueados"] >= 1


def test_por_codigo_agrupa_motivos_para_plano_de_acao(ambiente):
    db = ambiente["db"]
    _agente(db, ambiente["escritorio"].id)  # nenhum certificado
    relatorio = srv_prevoo.executar(db, ambiente["escritorio"].id)
    agrupado = relatorio.por_codigo()
    assert sum(agrupado.values()) >= 2


# ---------------------------------------------------------------------------
# Relatório
# ---------------------------------------------------------------------------


def test_relatorio_lista_todas_as_empresas(ambiente):
    db = ambiente["db"]
    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    assert len(registros) == 2
    assert {r.cliente for r in registros} == {"CLIENTE A LTDA", "CLIENTE B LTDA"}
    assert all(r.situacao == StatusAutorizacao.SEM_AUTORIZACAO.value for r in registros)


def test_csv_mascara_documento_por_padrao(ambiente):
    db = ambiente["db"]
    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    texto = srv_relatorio.para_csv(registros)
    assert CLIENTE_A not in texto
    assert "12.***.***/0001-95" in texto


def test_csv_completo_quando_pedido_explicitamente(ambiente):
    db = ambiente["db"]
    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    texto = srv_relatorio.para_csv(registros, mascarar=False)
    assert CLIENTE_A in texto


def test_csv_neutraliza_formula_em_campos_textuais():
    registro = srv_relatorio.LinhaRelatorio(
        cliente='=HYPERLINK("https://example.invalid","abrir")',
        documento=CLIENTE_A,
        situacao=StatusAutorizacao.SEM_AUTORIZACAO.value,
        validade=None,
        dias_para_vencer=-1,
        procurador=OUTORGADO,
        prazo_aceite=None,
        job_id=1,
        job_status="+cmd|' /C calc'!A0",
        etapa="-1+1",
        erro="\t@SUM(1+1)",
        atualizado_em=None,
    )

    texto = srv_relatorio.para_csv([registro], mascarar=False)
    linhas = list(
        csv.DictReader(io.StringIO(texto.removeprefix("\ufeff")), delimiter=";")
    )

    assert linhas[0]["cliente"].startswith("'=")
    assert linhas[0]["job_status"].startswith("'+")
    assert linhas[0]["etapa"].startswith("'-")
    assert linhas[0]["erro"].startswith("\'\t@")
    assert linhas[0]["dias_para_vencer"] == "-1"


def test_csv_abre_no_excel_brasileiro(ambiente):
    """BOM + `;`: sem isso o Excel pt-BR quebra acento e não separa coluna."""
    db = ambiente["db"]
    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    texto = srv_relatorio.para_csv(registros)
    assert texto.startswith("\ufeff")
    cabecalho = texto.splitlines()[0]
    assert cabecalho.count(";") == len(srv_relatorio.COLUNAS) - 1


def test_relatorio_traz_validade_e_procurador(ambiente):
    db = ambiente["db"]
    validade = date.today() + timedelta(days=1800)
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=validade,
        )
    )
    db.commit()

    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    linha = next(r for r in registros if r.cliente == "CLIENTE A LTDA")
    assert linha.validade == validade
    assert linha.dias_para_vencer == 1800
    assert linha.para_dict()["situacao"] == "Ativa"
    assert linha.para_dict()["procurador"] == "11.***.***/0001-81"


def test_somente_pendentes_exclui_as_ativas(ambiente):
    db = ambiente["db"]
    db.add(
        Autorizacao(
            escritorio_id=ambiente["escritorio"].id,
            empresa_id=ambiente["empresa_a"].id,
            outorgante_documento=CLIENTE_A,
            outorgado_documento=OUTORGADO,
            situacao=StatusAutorizacao.ATIVA.value,
            data_validade=date.today() + timedelta(days=900),
        )
    )
    db.commit()

    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id, somente_pendentes=True)
    assert [r.cliente for r in registros] == ["CLIENTE B LTDA"]


def test_json_do_relatorio_tem_cabecalho_e_linhas(ambiente):
    db = ambiente["db"]
    registros = srv_relatorio.linhas(db, ambiente["escritorio"].id)
    saida = srv_relatorio.para_json(registros)
    assert saida["total"] == 2
    assert saida["colunas"] == list(srv_relatorio.COLUNAS)


# ---------------------------------------------------------------------------
# Métricas
# ---------------------------------------------------------------------------


def test_metricas_sem_jobs_nao_quebra(ambiente):
    dados = srv_relatorio.metricas(ambiente["db"], ambiente["escritorio"].id)
    assert dados.jobs_considerados == 0
    assert dados.taxa_sucesso == 0.0


def test_metricas_contam_estado_final_e_taxa(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    escritorio_id = ambiente["escritorio"].id

    resultado = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    job = resultado.job
    job.status = StatusJob.CONCLUIDO.value
    job.finalizado_em = datetime.now(timezone.utc)
    db.commit()

    dados = srv_relatorio.metricas(db, escritorio_id)
    assert dados.concluidos == 1
    assert dados.taxa_sucesso == 100.0


def test_metricas_separam_espera_humana_de_processamento(ambiente):
    """O número que dimensiona o dia é a espera humana, não o relógio total."""
    db = ambiente["db"]
    _pronto(ambiente)
    escritorio_id = ambiente["escritorio"].id
    resultado = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    job = resultado.job
    db.commit()

    base = datetime.now(timezone.utc) - timedelta(hours=3)
    from app.procuracoes.modelos import JobEvento

    db.query(JobEvento).filter(JobEvento.job_id == job.id).delete()
    db.add_all(
        [
            # 30 min de preparo (processamento)
            JobEvento(
                job_id=job.id,
                quando=base,
                tipo="transicao",
                status_novo=StatusJob.AUTENTICANDO.value,
                etapa="acesso_portal",
            ),
            # 60 min parado esperando a pessoa assinar
            JobEvento(
                job_id=job.id,
                quando=base + timedelta(minutes=30),
                tipo="transicao",
                status_novo=StatusJob.AGUARDANDO_ASSINATURA.value,
                etapa="assinatura",
            ),
            JobEvento(
                job_id=job.id,
                quando=base + timedelta(minutes=90),
                tipo="transicao",
                status_novo=StatusJob.CONCLUIDO.value,
                etapa="registro_conclusao",
            ),
        ]
    )
    job.status = StatusJob.CONCLUIDO.value
    job.finalizado_em = base + timedelta(minutes=90)
    db.commit()

    dados = srv_relatorio.metricas(db, escritorio_id)
    assert dados.espera_humana_media_minutos == pytest.approx(60, abs=1)
    assert dados.processamento_medio_minutos == pytest.approx(30, abs=1)
    assert dados.tempo_por_etapa["assinatura"] == pytest.approx(60, abs=1)


def test_metricas_agrupam_erros_por_codigo_e_classe(ambiente):
    db = ambiente["db"]
    _pronto(ambiente)
    escritorio_id = ambiente["escritorio"].id
    resultado = srv_fila.criar_job(db, escritorio_id, ambiente["empresa_a"])
    job = resultado.job
    job.status = StatusJob.FALHOU.value
    job.codigo_erro = "certificado_expirado"
    job.finalizado_em = datetime.now(timezone.utc)
    db.commit()

    dados = srv_relatorio.metricas(db, escritorio_id)
    assert dados.erros_por_codigo["certificado_expirado"] == 1
    assert sum(dados.erros_por_classe.values()) == 1
