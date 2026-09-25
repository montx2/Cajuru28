"""
Leitura para telas: KPIs, listagens e a visão consolidada de uma empresa.

Separado dos serviços de escrita de propósito. Consulta de painel roda a cada
carregamento de página e tem requisitos opostos aos da fila: nada de lock,
nada de efeito colateral, agregação em SQL em vez de laço em Python.

O KPI que dá sentido ao módulo é `sem_autorizacao` — é o número que aparece
como "52 empresas sem procuração" e o único que o operador precisa zerar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.models import Empresa
from app.procuracoes.estados import (
    ESTADOS_ESPERANDO_HUMANO,
    ESTADOS_TERMINAIS,
    StatusAutorizacao,
    StatusJob,
)
from app.procuracoes.modelos import (
    Agente,
    Autorizacao,
    AutorizacaoPermissao,
    CertificadoInventario,
    JobEvento,
    JobProcuracao,
    NotificacaoProcuracao,
)
from app.procuracoes.servicos import agentes as servico_agentes
from app.procuracoes.servicos.configuracao import obter_configuracao

#: Estados de job que ainda vão consumir capacidade.
_EM_FILA = tuple(
    status.value for status in StatusJob if status not in ESTADOS_TERMINAIS
)
_AGUARDANDO_HUMANO = tuple(status.value for status in ESTADOS_ESPERANDO_HUMANO)


@dataclass
class ResumoPainel:
    total_empresas: int = 0
    sem_autorizacao: int = 0
    em_analise: int = 0
    aguardando_aceite: int = 0
    ativas: int = 0
    expiradas: int = 0
    vencendo: int = 0
    canceladas: int = 0
    jobs_na_fila: int = 0
    jobs_aguardando_humano: int = 0
    jobs_com_erro: int = 0
    jobs_concluidos_24h: int = 0
    agentes_online: int = 0
    agentes_total: int = 0
    agentes_com_assinador: int = 0
    certificados_disponiveis: int = 0
    certificados_vencendo: int = 0
    notificacoes_abertas: int = 0
    duracao_media_minutos: float = 0.0
    taxa_sucesso: float = 0.0


@dataclass
class LinhaEmpresa:
    """Uma linha da tabela principal — carteira e situação lado a lado."""

    empresa_id: int
    razao_social: str
    documento: str
    uf: str
    situacao: str
    data_validade: date | None
    dias_para_vencer: int | None
    #: Relógio dos 30 dias: a Receita cancela sozinha a autorização que o
    #: outorgado não validar. É a informação mais acionável da tabela.
    prazo_aceite_ate: date | None
    dias_para_aceite: int | None
    outorgado_documento: str
    protocolo: str
    origem_dado: str
    sincronizado_em: datetime | None
    job_id: int | None
    job_status: str
    job_etapa: str
    job_modo: str
    job_atualizado_em: datetime | None
    certificado_disponivel: bool
    servicos: int = 0


def _prazo_aceite(autorizacao) -> date | None:
    """Só faz sentido enquanto o aceite está pendente.

    Depois de ativa, mostrar o prazo confundiria: o relógio parou de correr e
    o operador ficaria procurando uma ação que não existe mais.
    """
    if autorizacao is None or not autorizacao.prazo_aceite_ate:
        return None
    if autorizacao.situacao not in {
        StatusAutorizacao.EM_ANALISE.value,
        StatusAutorizacao.AGUARDANDO_ACEITE.value,
    }:
        return None
    return autorizacao.prazo_aceite_ate


@dataclass
class DetalheEmpresa:
    linha: LinhaEmpresa
    permissoes: list[dict] = field(default_factory=list)
    jobs: list[dict] = field(default_factory=list)
    eventos: list[dict] = field(default_factory=list)
    certificados: list[dict] = field(default_factory=list)


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def resumo(db: Session, escritorio_id: int, *, hoje: date | None = None) -> ResumoPainel:
    """Todos os KPIs numa passada, sem carregar entidade nenhuma."""
    referencia = hoje or date.today()
    config = obter_configuracao(db, escritorio_id)
    janela = max(config.alerta_dias_lista or [30])

    dados = ResumoPainel()
    dados.total_empresas = (
        db.query(func.count(Empresa.id))
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .scalar()
        or 0
    )

    por_situacao = dict(
        db.query(Autorizacao.situacao, func.count(Autorizacao.id))
        .filter(Autorizacao.escritorio_id == escritorio_id)
        .group_by(Autorizacao.situacao)
        .all()
    )
    dados.em_analise = int(por_situacao.get(StatusAutorizacao.EM_ANALISE.value, 0))
    dados.aguardando_aceite = int(
        por_situacao.get(StatusAutorizacao.AGUARDANDO_ACEITE.value, 0)
    )
    dados.ativas = int(por_situacao.get(StatusAutorizacao.ATIVA.value, 0))
    dados.expiradas = int(por_situacao.get(StatusAutorizacao.EXPIRADA.value, 0))
    dados.canceladas = int(
        por_situacao.get(StatusAutorizacao.CANCELADA.value, 0)
        + por_situacao.get(StatusAutorizacao.REJEITADA.value, 0)
    )

    # "Sem autorização" inclui a empresa que nunca teve registro nenhum — é
    # justamente ela que o operador precisa ver, e ela não aparece num
    # group_by de autorizações.
    com_registro_util = (
        db.query(func.count(func.distinct(Autorizacao.empresa_id)))
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.situacao.in_(
                (
                    StatusAutorizacao.ATIVA.value,
                    StatusAutorizacao.EM_ANALISE.value,
                    StatusAutorizacao.AGUARDANDO_ACEITE.value,
                )
            ),
        )
        .scalar()
        or 0
    )
    dados.sem_autorizacao = max(0, dados.total_empresas - int(com_registro_util))

    dados.vencendo = (
        db.query(func.count(Autorizacao.id))
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.situacao == StatusAutorizacao.ATIVA.value,
            Autorizacao.data_validade.isnot(None),
            Autorizacao.data_validade >= referencia,
            Autorizacao.data_validade <= referencia + timedelta(days=janela),
        )
        .scalar()
        or 0
    )

    por_job = dict(
        db.query(JobProcuracao.status, func.count(JobProcuracao.id))
        .filter(JobProcuracao.escritorio_id == escritorio_id)
        .group_by(JobProcuracao.status)
        .all()
    )
    dados.jobs_na_fila = sum(int(por_job.get(status, 0)) for status in _EM_FILA)
    dados.jobs_aguardando_humano = sum(
        int(por_job.get(status, 0)) for status in _AGUARDANDO_HUMANO
    )
    dados.jobs_com_erro = int(por_job.get(StatusJob.FALHOU.value, 0))

    limite_24h = _agora() - timedelta(hours=24)
    dados.jobs_concluidos_24h = (
        db.query(func.count(JobProcuracao.id))
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.status == StatusJob.CONCLUIDO.value,
            JobProcuracao.finalizado_em.isnot(None),
            JobProcuracao.finalizado_em >= limite_24h,
        )
        .scalar()
        or 0
    )

    finalizados = (
        db.query(JobProcuracao.status, JobProcuracao.iniciado_em, JobProcuracao.finalizado_em)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.finalizado_em.isnot(None),
            JobProcuracao.iniciado_em.isnot(None),
        )
        .order_by(JobProcuracao.finalizado_em.desc())
        .limit(200)
        .all()
    )
    if finalizados:
        duracoes = [
            (fim - inicio).total_seconds() / 60
            for _, inicio, fim in finalizados
            if inicio and fim and fim >= inicio
        ]
        if duracoes:
            dados.duracao_media_minutos = round(sum(duracoes) / len(duracoes), 1)
        sucessos = sum(1 for status, _, _ in finalizados if status == StatusJob.CONCLUIDO.value)
        dados.taxa_sucesso = round(100 * sucessos / len(finalizados), 1)

    lista_agentes = (
        db.query(Agente).filter(Agente.escritorio_id == escritorio_id).all()
    )
    dados.agentes_total = len(lista_agentes)
    dados.agentes_online = sum(
        1
        for agente in lista_agentes
        if servico_agentes.situacao(agente, config.heartbeat_tolerancia_segundos)
        in {"online", "processando"}
    )
    dados.agentes_com_assinador = sum(1 for agente in lista_agentes if agente.assinador_ok)

    agora = _agora()
    dados.certificados_disponiveis = (
        db.query(func.count(CertificadoInventario.id))
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.situacao == "disponivel",
            or_(
                CertificadoInventario.valido_ate.is_(None),
                CertificadoInventario.valido_ate > agora,
            ),
        )
        .scalar()
        or 0
    )
    dados.certificados_vencendo = (
        db.query(func.count(CertificadoInventario.id))
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.situacao == "disponivel",
            CertificadoInventario.valido_ate.isnot(None),
            CertificadoInventario.valido_ate > agora,
            CertificadoInventario.valido_ate <= agora + timedelta(days=janela),
        )
        .scalar()
        or 0
    )

    dados.notificacoes_abertas = (
        db.query(func.count(NotificacaoProcuracao.id))
        .filter(
            NotificacaoProcuracao.escritorio_id == escritorio_id,
            NotificacaoProcuracao.reconhecida_em.is_(None),
        )
        .scalar()
        or 0
    )
    return dados


def listar(
    db: Session,
    escritorio_id: int,
    *,
    situacao: str = "",
    busca: str = "",
    com_job: str = "",
    pagina: int = 1,
    tamanho: int = 50,
    hoje: date | None = None,
) -> tuple[list[LinhaEmpresa], int]:
    """Carteira + autorização + job atual, já paginada.

    LEFT JOIN em vez de N+1: com 5.000 empresas, uma consulta por linha
    transformaria a tela em timeout.
    """
    referencia = hoje or date.today()
    config = obter_configuracao(db, escritorio_id)
    outorgado = config.outorgado_documento

    consulta = (
        db.query(Empresa, Autorizacao)
        .outerjoin(
            Autorizacao,
            (Autorizacao.empresa_id == Empresa.id)
            & (Autorizacao.escritorio_id == escritorio_id)
            & (
                (Autorizacao.outorgado_documento == outorgado)
                if outorgado
                else Autorizacao.id.isnot(None)
            ),
        )
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
    )

    if busca:
        alvo = f"%{busca.strip()}%"
        consulta = consulta.filter(
            or_(Empresa.razao_social.ilike(alvo), Empresa.cnpj_cpf.ilike(alvo))
        )

    if situacao == StatusAutorizacao.SEM_AUTORIZACAO.value:
        consulta = consulta.filter(
            or_(
                Autorizacao.id.is_(None),
                Autorizacao.situacao.notin_(
                    (
                        StatusAutorizacao.ATIVA.value,
                        StatusAutorizacao.EM_ANALISE.value,
                        StatusAutorizacao.AGUARDANDO_ACEITE.value,
                    )
                ),
            )
        )
    elif situacao == "vencendo":
        janela = max(config.alerta_dias_lista or [30])
        consulta = consulta.filter(
            Autorizacao.situacao == StatusAutorizacao.ATIVA.value,
            Autorizacao.data_validade.isnot(None),
            Autorizacao.data_validade >= referencia,
            Autorizacao.data_validade <= referencia + timedelta(days=janela),
        )
    elif situacao:
        consulta = consulta.filter(Autorizacao.situacao == situacao)

    total = consulta.count()
    pagina = max(1, int(pagina))
    tamanho = max(1, min(int(tamanho), 200))
    pares = (
        consulta.order_by(Empresa.razao_social)
        .offset((pagina - 1) * tamanho)
        .limit(tamanho)
        .all()
    )

    empresa_ids = [empresa.id for empresa, _ in pares]
    jobs = _jobs_atuais(db, escritorio_id, empresa_ids)
    certificados = _documentos_com_certificado(db, escritorio_id, empresa_ids)
    contagem_servicos = _contagem_servicos(db, [a.id for _, a in pares if a is not None])

    linhas: list[LinhaEmpresa] = []
    for empresa, autorizacao in pares:
        job = jobs.get(empresa.id)
        validade = autorizacao.data_validade if autorizacao else None
        linha = LinhaEmpresa(
            empresa_id=empresa.id,
            razao_social=empresa.razao_social,
            documento=empresa.cnpj_cpf,
            uf=empresa.uf,
            situacao=(
                autorizacao.situacao if autorizacao else StatusAutorizacao.SEM_AUTORIZACAO.value
            ),
            data_validade=validade,
            dias_para_vencer=(validade - referencia).days if validade else None,
            prazo_aceite_ate=_prazo_aceite(autorizacao),
            dias_para_aceite=(
                (_prazo_aceite(autorizacao) - referencia).days
                if _prazo_aceite(autorizacao)
                else None
            ),
            outorgado_documento=autorizacao.outorgado_documento if autorizacao else outorgado,
            protocolo=autorizacao.protocolo if autorizacao else "",
            origem_dado=autorizacao.origem_dado if autorizacao else "",
            sincronizado_em=autorizacao.sincronizado_em if autorizacao else None,
            job_id=job.id if job else None,
            job_status=job.status if job else "",
            job_etapa=job.etapa_atual if job else "",
            job_modo=job.modo if job else "",
            job_atualizado_em=job.atualizado_em if job else None,
            certificado_disponivel=empresa.cnpj_cpf in certificados,
            servicos=contagem_servicos.get(autorizacao.id, 0) if autorizacao else 0,
        )
        if com_job == "sim" and linha.job_id is None:
            continue
        if com_job == "nao" and linha.job_id is not None:
            continue
        linhas.append(linha)

    return linhas, total


def _jobs_atuais(
    db: Session, escritorio_id: int, empresa_ids: list[int]
) -> dict[int, JobProcuracao]:
    if not empresa_ids:
        return {}
    jobs = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.empresa_id.in_(empresa_ids),
        )
        .order_by(JobProcuracao.empresa_id, JobProcuracao.id.desc())
        .all()
    )
    saida: dict[int, JobProcuracao] = {}
    for job in jobs:
        # O primeiro de cada empresa é o mais recente (ordenação acima).
        saida.setdefault(job.empresa_id, job)
    return saida


def _documentos_com_certificado(
    db: Session, escritorio_id: int, empresa_ids: list[int]
) -> set[str]:
    if not empresa_ids:
        return set()
    agora = _agora()
    linhas = (
        db.query(CertificadoInventario.documento)
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.situacao == "disponivel",
            CertificadoInventario.documento != "",
            or_(
                CertificadoInventario.valido_ate.is_(None),
                CertificadoInventario.valido_ate > agora,
            ),
        )
        .distinct()
        .all()
    )
    return {documento for (documento,) in linhas}


def _contagem_servicos(db: Session, autorizacao_ids: list[int]) -> dict[int, int]:
    if not autorizacao_ids:
        return {}
    linhas = (
        db.query(AutorizacaoPermissao.autorizacao_id, func.count(AutorizacaoPermissao.id))
        .filter(AutorizacaoPermissao.autorizacao_id.in_(autorizacao_ids))
        .group_by(AutorizacaoPermissao.autorizacao_id)
        .all()
    )
    return {chave: int(valor) for chave, valor in linhas}


def detalhar(
    db: Session, escritorio_id: int, empresa_id: int, *, hoje: date | None = None
) -> DetalheEmpresa | None:
    """Tudo sobre uma empresa: situação, serviços, jobs, trilha e certificados."""
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        return None

    config = obter_configuracao(db, escritorio_id)
    autorizacao = (
        db.query(Autorizacao)
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.empresa_id == empresa_id,
        )
        .order_by(Autorizacao.atualizado_em.desc())
        .first()
    )
    referencia = hoje or date.today()
    validade = autorizacao.data_validade if autorizacao else None

    jobs = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.empresa_id == empresa_id,
        )
        .order_by(JobProcuracao.id.desc())
        .limit(20)
        .all()
    )
    job_atual = jobs[0] if jobs else None

    linha = LinhaEmpresa(
        empresa_id=empresa.id,
        razao_social=empresa.razao_social,
        documento=empresa.cnpj_cpf,
        uf=empresa.uf,
        situacao=(
            autorizacao.situacao if autorizacao else StatusAutorizacao.SEM_AUTORIZACAO.value
        ),
        data_validade=validade,
        dias_para_vencer=(validade - referencia).days if validade else None,
        prazo_aceite_ate=_prazo_aceite(autorizacao),
        dias_para_aceite=(
            (_prazo_aceite(autorizacao) - referencia).days
            if _prazo_aceite(autorizacao)
            else None
        ),
        outorgado_documento=(
            autorizacao.outorgado_documento if autorizacao else config.outorgado_documento
        ),
        protocolo=autorizacao.protocolo if autorizacao else "",
        origem_dado=autorizacao.origem_dado if autorizacao else "",
        sincronizado_em=autorizacao.sincronizado_em if autorizacao else None,
        job_id=job_atual.id if job_atual else None,
        job_status=job_atual.status if job_atual else "",
        job_etapa=job_atual.etapa_atual if job_atual else "",
        job_modo=job_atual.modo if job_atual else "",
        job_atualizado_em=job_atual.atualizado_em if job_atual else None,
        certificado_disponivel=bool(
            _documentos_com_certificado(db, escritorio_id, [empresa.id]) & {empresa.cnpj_cpf}
        ),
    )

    permissoes = []
    if autorizacao is not None:
        permissoes = [
            {
                "codigo": permissao.codigo,
                "rotulo": permissao.rotulo or permissao.codigo,
                "expira_em": permissao.expira_em,
                "origem": permissao.origem,
            }
            for permissao in db.query(AutorizacaoPermissao)
            .filter(AutorizacaoPermissao.autorizacao_id == autorizacao.id)
            .order_by(AutorizacaoPermissao.codigo)
            .all()
        ]
        linha.servicos = len(permissoes)

    trilha = []
    if jobs:
        ids = [job.id for job in jobs]
        trilha = (
            db.query(JobEvento)
            .filter(JobEvento.job_id.in_(ids))
            .order_by(JobEvento.quando.desc(), JobEvento.id.desc())
            .limit(120)
            .all()
        )

    certificados = [
        {
            "id": certificado.id,
            "agente_id": certificado.agente_id,
            "thumbprint": certificado.thumbprint,
            "titular_nome": certificado.titular_nome,
            "documento": certificado.documento,
            "valido_ate": certificado.valido_ate,
            "situacao": certificado.situacao,
            "tipo": certificado.tipo,
        }
        for certificado in db.query(CertificadoInventario)
        .filter(
            CertificadoInventario.escritorio_id == escritorio_id,
            CertificadoInventario.documento == empresa.cnpj_cpf,
        )
        .order_by(CertificadoInventario.valido_ate.desc().nullslast())
        .all()
    ]

    return DetalheEmpresa(
        linha=linha,
        permissoes=permissoes,
        jobs=[
            {
                "id": job.id,
                "status": job.status,
                "fase": job.fase,
                "etapa_atual": job.etapa_atual,
                "modo": job.modo,
                "tentativas": job.tentativas,
                "codigo_erro": job.codigo_erro,
                "classe_erro": job.classe_erro,
                "mensagem_erro": job.mensagem_erro,
                "motivo_intervencao": job.motivo_intervencao,
                "criado_em": job.criado_em,
                "iniciado_em": job.iniciado_em,
                "finalizado_em": job.finalizado_em,
                "agente_id": job.agente_id,
                "vigencia_ate": job.vigencia_ate,
                "protocolo": job.protocolo,
            }
            for job in jobs
        ],
        eventos=trilha,
        certificados=certificados,
    )
