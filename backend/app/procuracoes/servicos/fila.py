"""
Fila operacional de procurações: criação idempotente, lock distribuído,
transições validadas, retry classificado e retomada.

Três invariantes que o resto do módulo pode assumir como verdadeiras:

1. **Nunca dois jobs ativos para a mesma empresa+outorgado.** Garantido por
   consulta-guarda na criação e pelo `UNIQUE(escritorio_id, chave_idempotencia)`.
2. **Nunca dois Agents no mesmo job.** A reivindicação é um `UPDATE ... WHERE
   agente_id IS NULL AND status = ...` com verificação de `rowcount`; quem
   perde a corrida recebe `None`, não uma exceção.
3. **Nenhuma mudança de status sem evento.** `mudar_status` é a única porta.

O lease existe porque a estação é um computador de escritório: ela reinicia,
perde rede, o operador desliga no fim do expediente. Lease vencido devolve o
job para a fila sem intervenção — e sem deixar a empresa presa.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Empresa, Usuario
from app.procuracoes.estados import (
    ESTADOS_TERMINAIS,
    TRANSICOES,
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
from app.procuracoes.estados import TransicaoInvalidaError
from app.procuracoes.modelos import (
    Agente,
    Autorizacao,
    JobProcuracao,
    ProcuracaoConfiguracao,
)
from app.procuracoes.servicos import configuracao as cfg
from app.procuracoes.servicos import eventos

log = logging.getLogger("cajuru.procuracoes.fila")

#: Estados nos quais o job ainda pode evoluir sozinho ou com o operador.
ESTADOS_ATIVOS = tuple(
    status.value for status in StatusJob if status not in ESTADOS_TERMINAIS
)

#: Estados que um Agent pode reivindicar.
ESTADOS_REIVINDICAVEIS = (
    StatusJob.AGUARDANDO_AGENTE.value,
    StatusJob.AGUARDANDO_VALIDACAO.value,
)


class FilaError(RuntimeError):
    """Erro de regra da fila, com código estável para a API traduzir."""

    def __init__(self, codigo: CodigoErro, mensagem: str, status_code: int = 409):
        super().__init__(mensagem)
        self.codigo = codigo
        self.status_code = status_code


@dataclass(frozen=True)
class ResultadoCriacao:
    job: JobProcuracao | None
    criado: bool
    motivo: str = ""
    codigo: CodigoErro | None = None


def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _aware(valor: datetime | None) -> datetime | None:
    if valor is None:
        return None
    return valor if valor.tzinfo else valor.replace(tzinfo=timezone.utc)


def chave_idempotencia(empresa_id: int, outorgado: str, ciclo: int) -> str:
    """Chave curta e estável. Ciclo distingue reprocessamentos legítimos."""
    bruto = f"procuracao|{empresa_id}|{outorgado}|{ciclo}"
    return hashlib.sha256(bruto.encode("utf-8")).hexdigest()[:40]


def job_ativo_da_empresa(
    db: Session, escritorio_id: int, empresa_id: int
) -> JobProcuracao | None:
    """O job que hoje 'possui' a empresa, se houver."""
    return (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.empresa_id == empresa_id,
            JobProcuracao.status.in_(ESTADOS_ATIVOS),
        )
        .order_by(JobProcuracao.id.desc())
        .first()
    )


def _autorizacao(
    db: Session, escritorio_id: int, empresa_id: int, outorgado: str
) -> Autorizacao | None:
    return (
        db.query(Autorizacao)
        .filter(
            Autorizacao.escritorio_id == escritorio_id,
            Autorizacao.empresa_id == empresa_id,
            Autorizacao.outorgado_documento == outorgado,
        )
        .first()
    )


def criar_job(
    db: Session,
    escritorio_id: int,
    empresa: Empresa,
    *,
    usuario: Usuario | None = None,
    origem: str = "manual",
    forcar_nova_outorga: bool = False,
    prioridade: int = 100,
    modelo_id: int | None = None,
) -> ResultadoCriacao:
    """Cria o job de uma empresa, se e somente se fizer sentido criar.

    A sequência de verificações é a especificada pela operação:
    consulta o estado atual → verifica autorização existente → verifica job
    concluído → verifica operação pendente → só então cria.
    """
    config = cfg.obter_configuracao(db, escritorio_id)
    outorgado = (config.outorgado_documento or "").strip()
    if not outorgado:
        return ResultadoCriacao(
            None,
            False,
            "Configure o CNPJ/CPF da contabilidade (outorgado) antes de montar a fila.",
            CodigoErro.DADOS_INSUFICIENTES,
        )

    # 1) operação pendente para esta empresa?
    existente = job_ativo_da_empresa(db, escritorio_id, empresa.id)
    if existente is not None:
        return ResultadoCriacao(
            existente,
            False,
            f"Já existe o job #{existente.id} em andamento para esta empresa.",
            CodigoErro.JOB_DUPLICADO,
        )

    # 2) autorização já resolvida?
    autorizacao = _autorizacao(db, escritorio_id, empresa.id, outorgado)
    if autorizacao is not None and not forcar_nova_outorga:
        situacao = autorizacao.situacao
        if situacao == StatusAutorizacao.ATIVA.value and not _perto_de_vencer(
            autorizacao, config
        ):
            return ResultadoCriacao(
                None,
                False,
                "A empresa já possui autorização ativa e fora da janela de renovação.",
                CodigoErro.AUTORIZACAO_JA_EXISTE,
            )

    modelo = None
    if modelo_id:
        from app.procuracoes.modelos import ModeloAutorizacao

        modelo = (
            db.query(ModeloAutorizacao)
            .filter(
                ModeloAutorizacao.id == modelo_id,
                ModeloAutorizacao.escritorio_id == escritorio_id,
            )
            .first()
        )
        if modelo is None:
            return ResultadoCriacao(
                None, False, "Modelo de autorização inexistente.", CodigoErro.DADOS_INSUFICIENTES
            )
    try:
        plano = cfg.montar_plano(db, escritorio_id, modelo=modelo)
    except ValueError as exc:
        return ResultadoCriacao(None, False, str(exc), CodigoErro.DADOS_INSUFICIENTES)

    # 3) a política de conformidade decide o modo antes de qualquer execução.
    avaliacao = avaliar_modo(
        cfg.modo_padrao(config),
        autorizacao_formal_rfb=bool(config.autorizacao_formal_rfb),
    )
    modo = avaliacao.modo_efetivo

    ciclo = (
        db.query(func.count(JobProcuracao.id))
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.empresa_id == empresa.id,
        )
        .scalar()
        or 0
    )

    # A fase inicial depende do ponto em que a autorização parou: se o cliente
    # já assinou e o que falta é o aceite, não se cria outra outorga.
    fase_inicial = FaseJob.OUTORGA
    status_inicial = StatusJob.PENDENTE
    etapa_inicial = EtapaFluxo.PRE_REQUISITOS
    if (
        autorizacao is not None
        and autorizacao.situacao
        in {StatusAutorizacao.EM_ANALISE.value, StatusAutorizacao.AGUARDANDO_ACEITE.value}
        and not forcar_nova_outorga
    ):
        fase_inicial = FaseJob.ACEITE
        etapa_inicial = EtapaFluxo.AUTORIZACOES_RECEBIDAS

    job = JobProcuracao(
        escritorio_id=escritorio_id,
        empresa_id=empresa.id,
        autorizacao_id=autorizacao.id if autorizacao else None,
        modelo_id=plano.modelo_id,
        chave_idempotencia=chave_idempotencia(empresa.id, outorgado, ciclo),
        status=status_inicial.value,
        fase=fase_inicial.value,
        etapa_atual=etapa_inicial.value,
        modo=modo.value,
        prioridade=max(0, min(int(prioridade), 1000)),
        outorgado_documento=outorgado,
        outorgado_nome=config.outorgado_nome or "",
        vigencia_ate=plano.vigencia_ate,
        escopo_servicos=plano.escopo_servicos,
        servicos_json=plano.servicos_json,
        criado_por_usuario_id=usuario.id if usuario else None,
        origem=origem[:20],
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return ResultadoCriacao(
            None,
            False,
            "Outro processo criou este job ao mesmo tempo. Nada foi duplicado.",
            CodigoErro.JOB_DUPLICADO,
        )

    eventos.registrar_evento(
        db,
        job,
        "job_criado",
        mensagem=(
            f"Job criado para {empresa.razao_social} — outorgado {outorgado}, "
            f"vigência até {plano.vigencia_ate.isoformat()}, "
            f"serviços: {'todos' if plano.todos_os_servicos else len(plano.servicos)}."
        ),
        status_novo=job.status,
        ator=f"operador:{usuario.id}" if usuario else "agendador",
        usuario_id=usuario.id if usuario else None,
        detalhe={
            "modo": modo.value,
            "modelo": plano.modelo_nome,
            "politica": avaliacao.motivo,
            "fase": fase_inicial.value,
        },
    )
    mudar_status(
        db,
        job,
        StatusJob.AGUARDANDO_AGENTE,
        mensagem="Aguardando estação disponível.",
        ator="sistema",
    )
    return ResultadoCriacao(job, True)


def _perto_de_vencer(autorizacao: Autorizacao, config: ProcuracaoConfiguracao) -> bool:
    if autorizacao.data_validade is None:
        return False
    limite = max(config.alerta_dias_lista or [30])
    return autorizacao.data_validade <= date.today() + timedelta(days=limite)


def enfileirar_pendencias(
    db: Session,
    escritorio_id: int,
    *,
    usuario: Usuario | None = None,
    empresa_ids: list[int] | None = None,
    origem: str = "manual",
    limite: int = 500,
) -> dict:
    """Monta a fila a partir das empresas sem autorização utilizável.

    O resultado é um relatório — a tela mostra exatamente quantas entraram,
    quantas já estavam na fila e quantas foram puladas e por quê.
    """
    config = cfg.obter_configuracao(db, escritorio_id)
    outorgado = (config.outorgado_documento or "").strip()
    if not outorgado:
        raise FilaError(
            CodigoErro.DADOS_INSUFICIENTES,
            "Configure o CNPJ/CPF da contabilidade antes de processar pendências.",
            422,
        )

    consulta = db.query(Empresa).filter(
        Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True)
    )
    if empresa_ids:
        consulta = consulta.filter(Empresa.id.in_(empresa_ids[:limite]))
    empresas = consulta.order_by(Empresa.razao_social).limit(limite).all()

    criados: list[int] = []
    ja_na_fila = 0
    ignoradas: list[dict] = []

    for empresa in empresas:
        resultado = criar_job(
            db, escritorio_id, empresa, usuario=usuario, origem=origem
        )
        if resultado.criado and resultado.job is not None:
            criados.append(resultado.job.id)
        elif resultado.codigo is CodigoErro.JOB_DUPLICADO:
            ja_na_fila += 1
        else:
            ignoradas.append(
                {
                    "empresa_id": empresa.id,
                    "razao_social": empresa.razao_social,
                    "motivo": resultado.motivo,
                    "codigo": resultado.codigo.value if resultado.codigo else "",
                }
            )
    return {
        "avaliadas": len(empresas),
        "criados": len(criados),
        "job_ids": criados,
        "ja_na_fila": ja_na_fila,
        "ignoradas": ignoradas[:200],
        "total_ignoradas": len(ignoradas),
    }


# ---------------------------------------------------------------------------
# Transições
# ---------------------------------------------------------------------------


def mudar_status(
    db: Session,
    job: JobProcuracao,
    destino: StatusJob,
    *,
    mensagem: str = "",
    etapa: EtapaFluxo | str | None = None,
    ator: str = "sistema",
    agente_id: int | None = None,
    usuario_id: int | None = None,
    codigo_erro: str = "",
    detalhe: dict | None = None,
) -> JobProcuracao:
    """Única porta de mudança de estado. Valida o grafo e emite evento."""
    origem = StatusJob(job.status)
    exigir_transicao(origem, destino)

    job.status = destino.value
    if etapa is not None:
        job.etapa_atual = etapa.value if isinstance(etapa, EtapaFluxo) else str(etapa)[:40]
    job.fase = fase_do_status(destino).value

    agora = _agora()
    if job.iniciado_em is None and destino not in {
        StatusJob.PENDENTE,
        StatusJob.AGUARDANDO_AGENTE,
    }:
        job.iniciado_em = agora
    if destino in ESTADOS_TERMINAIS:
        job.finalizado_em = agora
        job.agente_id = None
        job.lease_ate = None
        job.lease_token = ""

    eventos.registrar_evento(
        db,
        job,
        "transicao",
        mensagem=mensagem,
        etapa=job.etapa_atual,
        status_anterior=origem.value,
        status_novo=destino.value,
        codigo_erro=codigo_erro,
        ator=ator,
        agente_id=agente_id,
        usuario_id=usuario_id,
        detalhe=detalhe,
    )
    db.flush()
    return job


# ---------------------------------------------------------------------------
# Lock distribuído (lease)
# ---------------------------------------------------------------------------


def reivindicar(
    db: Session,
    agente: Agente,
    config: ProcuracaoConfiguracao,
    *,
    documentos_disponiveis: list[str] | None = None,
    agora: datetime | None = None,
) -> JobProcuracao | None:
    """Entrega no máximo **um** job para a estação, de forma atômica.

    A atomicidade não depende de `SELECT FOR UPDATE`: o `UPDATE` condicional
    com verificação de `rowcount` funciona igual em PostgreSQL e SQLite e é
    imune a duas estações pedindo trabalho no mesmo milissegundo.
    """
    agora = agora or _agora()
    if not agente.ativo or agente.revogado_em is not None:
        return None

    ocupados = (
        db.query(func.count(JobProcuracao.id))
        .filter(
            JobProcuracao.agente_id == agente.id,
            JobProcuracao.status.in_(ESTADOS_ATIVOS),
            JobProcuracao.lease_ate.isnot(None),
            JobProcuracao.lease_ate > agora,
        )
        .scalar()
        or 0
    )
    if ocupados >= max(1, int(config.max_jobs_por_agente or 1)):
        return None

    em_execucao_global = (
        db.query(func.count(JobProcuracao.id))
        .filter(
            JobProcuracao.escritorio_id == agente.escritorio_id,
            JobProcuracao.lease_ate.isnot(None),
            JobProcuracao.lease_ate > agora,
        )
        .scalar()
        or 0
    )
    if em_execucao_global >= max(1, int(config.max_jobs_simultaneos or 1)):
        return None

    candidatos = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == agente.escritorio_id,
            JobProcuracao.status.in_(ESTADOS_REIVINDICAVEIS),
            or_(JobProcuracao.lease_ate.is_(None), JobProcuracao.lease_ate <= agora),
            or_(
                JobProcuracao.proxima_tentativa_em.is_(None),
                JobProcuracao.proxima_tentativa_em <= agora,
            ),
        )
        .order_by(JobProcuracao.prioridade, JobProcuracao.criado_em, JobProcuracao.id)
        .limit(25)
        .all()
    )

    disponiveis = {d for d in (documentos_disponiveis or []) if d}
    duracao = timedelta(seconds=max(60, int(config.timeout_etapa_segundos or 900)))

    for candidato in candidatos:
        # Roteamento por certificado: só entrega o job para a estação que tem
        # a identidade necessária. Sem isso o job viaja para a máquina errada
        # e só descobre no pré-voo.
        if disponiveis:
            exigido = _documento_exigido(db, candidato)
            if exigido and exigido not in disponiveis:
                continue

        token = secrets.token_hex(16)
        resultado = db.execute(
            update(JobProcuracao)
            .where(
                JobProcuracao.id == candidato.id,
                JobProcuracao.status == candidato.status,
                or_(
                    JobProcuracao.lease_ate.is_(None),
                    JobProcuracao.lease_ate <= agora,
                ),
            )
            .values(
                agente_id=agente.id,
                lease_ate=agora + duracao,
                lease_token=token,
                atualizado_em=agora,
            )
        )
        if resultado.rowcount != 1:
            continue  # outra estação levou; tenta o próximo

        db.flush()
        db.refresh(candidato)
        mudar_status(
            db,
            candidato,
            StatusJob.ATRIBUIDO
            if candidato.status == StatusJob.AGUARDANDO_AGENTE.value
            else StatusJob.VALIDANDO,
            mensagem=f"Atribuído à estação {agente.nome}.",
            ator=f"agente:{agente.id}",
            agente_id=agente.id,
        )
        return candidato
    return None


def _documento_exigido(db: Session, job: JobProcuracao) -> str:
    """CNPJ/CPF cuja identidade o job precisa neste exato estado."""
    if certificado_exigido(StatusJob(job.status)) is TipoCertificado.CONTABILIDADE:
        return job.outorgado_documento or ""
    empresa = db.get(Empresa, job.empresa_id)
    return empresa.cnpj_cpf if empresa else ""


def renovar_lease(
    db: Session, job: JobProcuracao, agente: Agente, config: ProcuracaoConfiguracao
) -> bool:
    """Estende o lease enquanto a estação estiver de fato trabalhando."""
    if job.agente_id != agente.id:
        return False
    job.lease_ate = _agora() + timedelta(
        seconds=max(60, int(config.timeout_etapa_segundos or 900))
    )
    db.flush()
    return True


def liberar_lease(db: Session, job: JobProcuracao) -> None:
    job.agente_id = None
    job.lease_ate = None
    job.lease_token = ""
    db.flush()


def recuperar_leases_expirados(
    db: Session, escritorio_id: int | None = None, *, agora: datetime | None = None
) -> int:
    """Devolve para a fila o que uma estação abandonou.

    Não é falha do job: é falha de ambiente. O job volta para o estado de
    espera correspondente à fase em que estava, preservando tudo que já foi
    feito — nada é refeito do zero.
    """
    agora = agora or _agora()
    consulta = db.query(JobProcuracao).filter(
        JobProcuracao.lease_ate.isnot(None),
        JobProcuracao.lease_ate <= agora,
        JobProcuracao.status.in_(ESTADOS_ATIVOS),
    )
    if escritorio_id is not None:
        consulta = consulta.filter(JobProcuracao.escritorio_id == escritorio_id)

    recuperados = 0
    for job in consulta.limit(200).all():
        atual = StatusJob(job.status)
        if atual in {
            StatusJob.PRONTO_PARA_OPERACAO,
            StatusJob.AGUARDANDO_ASSINATURA,
            StatusJob.INTERVENCAO_MANUAL,
        }:
            # Estes esperam uma pessoa, não a máquina: só solta o lease.
            liberar_lease(db, job)
            continue
        destino = (
            StatusJob.AGUARDANDO_VALIDACAO
            if fase_do_status(atual) is FaseJob.ACEITE
            else StatusJob.AGUARDANDO_AGENTE
        )
        liberar_lease(db, job)
        try:
            mudar_status(
                db,
                job,
                destino,
                mensagem="Estação deixou de responder; job devolvido à fila sem perder o progresso.",
                ator="sistema",
                codigo_erro=CodigoErro.AGENTE_SEM_RESPOSTA.value,
            )
        except ValueError:
            registrar_falha(
                db, job, CodigoErro.AGENTE_SEM_RESPOSTA, "Estação deixou de responder."
            )
        recuperados += 1
    return recuperados


# ---------------------------------------------------------------------------
# Falhas, retry e intervenção
# ---------------------------------------------------------------------------


def registrar_falha(
    db: Session,
    job: JobProcuracao,
    codigo: CodigoErro | str,
    mensagem: str = "",
    *,
    agente_id: int | None = None,
    usuario_id: int | None = None,
    detalhe: dict | None = None,
    config: ProcuracaoConfiguracao | None = None,
) -> JobProcuracao:
    """Aplica a taxonomia de erro: decide retry, espera e destino."""
    regra = regra_do_erro(codigo)
    codigo_texto = codigo.value if isinstance(codigo, CodigoErro) else str(codigo)[:60]
    texto = (mensagem or regra.explicacao)[:2000]

    job.codigo_erro = codigo_texto
    job.classe_erro = regra.classe.value
    job.mensagem_erro = texto
    job.tentativas = int(job.tentativas or 0) + 1

    teto = int((config.max_tentativas if config else 3) or 3)
    max_regra = min(regra.max_tentativas, teto)
    pode_retentar = job.tentativas <= max_regra and deve_retentar(
        codigo_texto, job.tentativas - 1
    )

    liberar_lease(db, job)

    if pode_retentar:
        espera = espera_do_retry(codigo_texto, job.tentativas - 1)
        job.proxima_tentativa_em = _agora() + timedelta(seconds=espera)
        destino = (
            StatusJob.AGUARDANDO_VALIDACAO
            if fase_do_status(StatusJob(job.status)) is FaseJob.ACEITE
            else StatusJob.AGUARDANDO_AGENTE
        )
        if not _tentar_transicao(
            db,
            job,
            destino,
            mensagem=f"{texto} Nova tentativa em {espera}s ({job.tentativas}/{max_regra}).",
            codigo_erro=codigo_texto,
            agente_id=agente_id,
            usuario_id=usuario_id,
            detalhe=detalhe,
        ):
            _forcar_intervencao(db, job, texto, codigo_texto, agente_id, usuario_id, detalhe)
        return job

    job.proxima_tentativa_em = None
    destino = regra.destino_apos_esgotar
    if destino is StatusJob.INTERVENCAO_MANUAL:
        job.motivo_intervencao = texto
    if not _tentar_transicao(
        db,
        job,
        destino,
        mensagem=texto,
        codigo_erro=codigo_texto,
        agente_id=agente_id,
        usuario_id=usuario_id,
        detalhe=detalhe,
    ):
        _forcar_intervencao(db, job, texto, codigo_texto, agente_id, usuario_id, detalhe)
    return job


def _tentar_transicao(db: Session, job: JobProcuracao, destino: StatusJob, **kwargs) -> bool:
    try:
        mudar_status(db, job, destino, **kwargs)
        return True
    except ValueError:
        return False


def _forcar_intervencao(
    db: Session,
    job: JobProcuracao,
    mensagem: str,
    codigo: str,
    agente_id: int | None,
    usuario_id: int | None,
    detalhe: dict | None,
) -> None:
    """Rede de segurança: estado inesperado nunca vira job perdido."""
    job.status = StatusJob.INTERVENCAO_MANUAL.value
    job.motivo_intervencao = mensagem
    eventos.registrar_evento(
        db,
        job,
        "intervencao_forcada",
        mensagem=mensagem,
        status_novo=job.status,
        codigo_erro=codigo,
        ator="sistema",
        agente_id=agente_id,
        usuario_id=usuario_id,
        detalhe=detalhe,
    )
    db.flush()


def pedir_intervencao(
    db: Session,
    job: JobProcuracao,
    motivo: str,
    *,
    codigo: CodigoErro | str = CodigoErro.PORTAL_DESAFIO_ADICIONAL,
    agente_id: int | None = None,
    detalhe: dict | None = None,
) -> JobProcuracao:
    """O Agent encontrou algo que só uma pessoa pode resolver."""
    job.motivo_intervencao = (motivo or "")[:2000]
    liberar_lease(db, job)
    codigo_texto = codigo.value if isinstance(codigo, CodigoErro) else str(codigo)[:60]
    job.codigo_erro = codigo_texto
    job.classe_erro = regra_do_erro(codigo_texto).classe.value
    if not _tentar_transicao(
        db,
        job,
        StatusJob.INTERVENCAO_MANUAL,
        mensagem=motivo,
        codigo_erro=codigo_texto,
        ator=f"agente:{agente_id}" if agente_id else "sistema",
        agente_id=agente_id,
        detalhe=detalhe,
    ):
        _forcar_intervencao(db, job, motivo, codigo_texto, agente_id, None, detalhe)
    return job


#: De qual etapa o job retoma quando o operador clica em "Continuar".
#: Retomar não pode significar "refazer a outorga".
RETOMADA_POR_ETAPA: dict[str, StatusJob] = {
    EtapaFluxo.PRE_REQUISITOS.value: StatusJob.AGUARDANDO_AGENTE,
    EtapaFluxo.ACESSO_PORTAL.value: StatusJob.AGUARDANDO_AGENTE,
    EtapaFluxo.MINHAS_AUTORIZACOES.value: StatusJob.AGUARDANDO_AGENTE,
    EtapaFluxo.NOVA_AUTORIZACAO_PESSOA.value: StatusJob.PRONTO_PARA_OPERACAO,
    EtapaFluxo.NOVA_AUTORIZACAO_SERVICOS.value: StatusJob.PRONTO_PARA_OPERACAO,
    EtapaFluxo.NOVA_AUTORIZACAO_REVISAO.value: StatusJob.PRONTO_PARA_OPERACAO,
    EtapaFluxo.ASSINATURA.value: StatusJob.AGUARDANDO_ASSINATURA,
    EtapaFluxo.REGISTRO_OUTORGA.value: StatusJob.AGUARDANDO_VALIDACAO,
    EtapaFluxo.ACESSO_PORTAL_CONTABILIDADE.value: StatusJob.AGUARDANDO_VALIDACAO,
    EtapaFluxo.AUTORIZACOES_RECEBIDAS.value: StatusJob.AGUARDANDO_VALIDACAO,
    EtapaFluxo.VALIDACAO.value: StatusJob.AGUARDANDO_VALIDACAO,
}


def retomar(
    db: Session, job: JobProcuracao, usuario: Usuario | None, *, zerar_tentativas: bool = True
) -> JobProcuracao:
    """Continua do ponto em que parou, após intervenção humana."""
    if StatusJob(job.status) is not StatusJob.INTERVENCAO_MANUAL:
        raise FilaError(
            CodigoErro.JOB_DUPLICADO,
            "Só é possível continuar um job que está em intervenção manual.",
            409,
        )
    destino = RETOMADA_POR_ETAPA.get(job.etapa_atual, StatusJob.AGUARDANDO_AGENTE)
    if zerar_tentativas:
        job.tentativas = 0
    job.proxima_tentativa_em = None
    job.codigo_erro = ""
    job.mensagem_erro = ""
    job.motivo_intervencao = ""
    return mudar_status(
        db,
        job,
        destino,
        mensagem=f"Retomado pelo operador a partir da etapa '{job.etapa_atual}'.",
        ator=f"operador:{usuario.id}" if usuario else "operador",
        usuario_id=usuario.id if usuario else None,
    )


def cancelar(
    db: Session, job: JobProcuracao, usuario: Usuario | None, motivo: str = ""
) -> JobProcuracao:
    liberar_lease(db, job)
    texto = motivo or "Cancelado pelo operador."
    if not _tentar_transicao(
        db,
        job,
        StatusJob.CANCELADO,
        mensagem=texto,
        codigo_erro=CodigoErro.OPERACAO_CANCELADA_PELO_OPERADOR.value,
        ator=f"operador:{usuario.id}" if usuario else "operador",
        usuario_id=usuario.id if usuario else None,
    ):
        raise FilaError(
            CodigoErro.JOB_DUPLICADO,
            f"Um job em '{job.status}' não pode ser cancelado.",
            409,
        )
    return job


def reprocessar(
    db: Session, job: JobProcuracao, usuario: Usuario | None
) -> ResultadoCriacao:
    """Cria um **novo** job a partir de um terminal. Nunca reabre o antigo.

    Reabrir um job concluído destruiria a evidência do que aconteceu. O novo
    job nasce com ciclo seguinte, então a chave idempotente é outra.
    """
    if StatusJob(job.status) not in ESTADOS_TERMINAIS:
        raise FilaError(
            CodigoErro.JOB_DUPLICADO,
            "Este job ainda está ativo; use Continuar ou Cancelar.",
            409,
        )
    empresa = db.get(Empresa, job.empresa_id)
    if empresa is None:
        raise FilaError(CodigoErro.DADOS_INSUFICIENTES, "Empresa não encontrada.", 404)
    return criar_job(
        db,
        job.escritorio_id,
        empresa,
        usuario=usuario,
        origem="reprocessamento",
        forcar_nova_outorga=True,
        modelo_id=job.modelo_id,
    )


# ---------------------------------------------------------------------------
# Conclusão das duas fases
# ---------------------------------------------------------------------------


def registrar_outorga(
    db: Session,
    job: JobProcuracao,
    *,
    protocolo: str = "",
    agente_id: int | None = None,
    usuario_id: int | None = None,
    confirmada_em: datetime | None = None,
) -> Autorizacao:
    """Fase 1 concluída: a autorização existe no portal e está *em análise*.

    Só é chamada com confirmação efetiva da assinatura. Cria/atualiza a
    autorização e arma o relógio de 30 dias do aceite.
    """
    quando = confirmada_em or _agora()
    empresa = db.get(Empresa, job.empresa_id)
    autorizacao = _autorizacao(
        db, job.escritorio_id, job.empresa_id, job.outorgado_documento
    )
    if autorizacao is None:
        autorizacao = Autorizacao(
            escritorio_id=job.escritorio_id,
            empresa_id=job.empresa_id,
            outorgante_documento=empresa.cnpj_cpf if empresa else "",
            outorgante_nome=empresa.razao_social if empresa else "",
            outorgado_documento=job.outorgado_documento,
            outorgado_nome=job.outorgado_nome,
        )
        db.add(autorizacao)

    autorizacao.situacao = StatusAutorizacao.EM_ANALISE.value
    autorizacao.data_inicio = quando.date()
    autorizacao.data_validade = job.vigencia_ate
    autorizacao.prazo_aceite_ate = quando.date() + timedelta(days=30)
    autorizacao.escopo_servicos = job.escopo_servicos
    autorizacao.origem_dado = "operacao"
    autorizacao.ultimo_erro = ""
    if protocolo:
        autorizacao.protocolo = protocolo[:120]
    db.flush()

    job.autorizacao_id = autorizacao.id
    if protocolo:
        job.protocolo = protocolo[:120]
    mudar_status(
        db,
        job,
        StatusJob.ASSINADO,
        mensagem="Assinatura confirmada no portal. Autorização criada e em análise.",
        etapa=EtapaFluxo.REGISTRO_OUTORGA,
        ator=f"agente:{agente_id}" if agente_id else "operador",
        agente_id=agente_id,
        usuario_id=usuario_id,
        detalhe={"protocolo": protocolo or None},
    )
    mudar_status(
        db,
        job,
        StatusJob.AGUARDANDO_VALIDACAO,
        mensagem=(
            "Aguardando o aceite da contabilidade. Prazo legal: "
            f"{autorizacao.prazo_aceite_ate.isoformat()}."
        ),
        etapa=EtapaFluxo.AUTORIZACOES_RECEBIDAS,
        ator="sistema",
    )
    # A fase 2 é outro ato, com outra identidade, e pode acontecer noutro dia
    # ou noutra estação: segurar o lease aqui prenderia a máquina do operador
    # (e a cota de concorrência do escritório) sem nada a fazer.
    liberar_lease(db, job)
    eventos.notificar(
        db,
        job.escritorio_id,
        chave=f"aceite_pendente:{autorizacao.id}",
        tipo="aceite_pendente",
        nivel="atencao",
        titulo=f"Autorização aguardando aceite — {autorizacao.outorgante_nome or autorizacao.outorgante_documento}",
        detalhe=(
            "A contabilidade precisa validar a autorização recebida até "
            f"{autorizacao.prazo_aceite_ate.isoformat()}, ou a Receita a cancela."
        ),
        empresa_id=job.empresa_id,
        job_id=job.id,
    )
    return autorizacao


def registrar_aceite(
    db: Session,
    job: JobProcuracao,
    *,
    agente_id: int | None = None,
    usuario_id: int | None = None,
    confirmada_em: datetime | None = None,
) -> Autorizacao | None:
    """Fase 2 concluída: a autorização está ATIVA e produz efeitos."""
    quando = confirmada_em or _agora()
    autorizacao = (
        db.get(Autorizacao, job.autorizacao_id) if job.autorizacao_id else None
    )
    if autorizacao is None:
        autorizacao = _autorizacao(
            db, job.escritorio_id, job.empresa_id, job.outorgado_documento
        )
    if autorizacao is not None:
        autorizacao.situacao = StatusAutorizacao.ATIVA.value
        autorizacao.confirmado_em = quando
        autorizacao.ultimo_erro = ""
        db.flush()

    mudar_status(
        db,
        job,
        StatusJob.CONCLUIDO,
        mensagem="Autorização validada pela contabilidade. Situação: ATIVA.",
        etapa=EtapaFluxo.REGISTRO_CONCLUSAO,
        ator=f"agente:{agente_id}" if agente_id else "operador",
        agente_id=agente_id,
        usuario_id=usuario_id,
    )
    eventos.notificar(
        db,
        job.escritorio_id,
        chave=f"autorizacao_ativa:{job.empresa_id}:{job.outorgado_documento}",
        tipo="autorizacao_ativa",
        nivel="ok",
        titulo="Autorização ativa",
        detalhe="A contabilidade já pode operar em nome desta empresa.",
        empresa_id=job.empresa_id,
        job_id=job.id,
    )
    return autorizacao


def triar_por_certificado(
    db: Session,
    escritorio_id: int,
    *,
    limite: int = 200,
) -> dict[str, int]:
    """Explica por que um job não anda, antes que o operador precise perguntar.

    Um job pode ficar em `aguardando_agente` para sempre sem que nada esteja
    "errado" do ponto de vista da fila: simplesmente não existe, em nenhuma
    estação ativa, um A1 vigente daquele CNPJ. Sem esta triagem o painel
    mostraria "na fila" indefinidamente — o pior resultado possível, porque o
    operador só descobre quando cobra o cliente.

    A triagem responde uma pergunta por job: *existe exatamente um certificado
    vigente da identidade exigida, em alguma estação ativa?*

    - **Sim** → nada a fazer, o job segue esperando a vez.
    - **Não** → o job recebe o código do erro (vencido, ausente, ambíguo) e
      passa a aparecer na tela com o motivo e o caminho da correção.

    Idempotente: reavaliar um job já triado não cria evento novo enquanto o
    código não mudar.
    """
    from app.procuracoes.servicos import certificados as srv_certificados

    jobs = (
        db.query(JobProcuracao)
        .filter(
            JobProcuracao.escritorio_id == escritorio_id,
            JobProcuracao.status.in_(ESTADOS_REIVINDICAVEIS),
            JobProcuracao.agente_id.is_(None),
        )
        .order_by(JobProcuracao.id)
        .limit(max(1, limite))
        .all()
    )

    relatorio = {"avaliados": len(jobs), "bloqueados": 0, "liberados": 0}
    for job in jobs:
        documento = _documento_exigido(db, job)
        tipo = certificado_exigido(StatusJob(job.status))
        # Ver nota em `_certificado_do_job`: o thumbprint fixado só vale para
        # a fase cuja identidade é a do cliente.
        preferido = job.certificado_thumbprint if tipo is TipoCertificado.CLIENTE else ""
        selecao = srv_certificados.selecionar_para_documento(
            db,
            escritorio_id,
            documento,
            tipo=tipo,
            thumbprint_preferido=preferido or "",
        )
        if selecao.ok:
            if job.codigo_erro and job.codigo_erro.startswith("CERTIFICADO_"):
                # O certificado apareceu (renovado, reinstalado): limpa o
                # motivo antigo para não assombrar a tela.
                job.codigo_erro = ""
                job.ultimo_erro = ""
                eventos.registrar_evento(
                    db,
                    job,
                    "certificado_regularizado",
                    mensagem="Certificado válido encontrado; o job voltou a ficar elegível.",
                )
                relatorio["liberados"] += 1
            continue

        codigo = selecao.codigo_erro or CodigoErro.CERTIFICADO_INDISPONIVEL
        if job.codigo_erro == codigo.value:
            continue  # já explicado; não repetir evento nem notificação
        relatorio["bloqueados"] += 1
        registrar_falha(db, job, codigo, selecao.mensagem)
        eventos.notificar(
            db,
            escritorio_id,
            chave=f"certificado_job:{job.id}:{codigo.value}",
            tipo="certificado_bloqueado",
            nivel="alerta",
            titulo=f"Job #{job.id} parado por certificado",
            detalhe=selecao.mensagem,
            empresa_id=job.empresa_id,
            job_id=job.id,
        )

    db.flush()
    return relatorio


#: Marcos que só podem ser alcançados com confirmação real do portal. Nunca
#: são atravessados automaticamente — ver `avancar_para`.
MARCOS_COM_CONFIRMACAO = frozenset({StatusJob.ASSINADO, StatusJob.CONCLUIDO})


def avancar_para(
    db: Session,
    job: JobProcuracao,
    destino: StatusJob,
    **kwargs,
) -> JobProcuracao:
    """Move o job até `destino`, atravessando no máximo um estado intermediário.

    Por que existe: a estação relata **etapas do roteiro** ("estou na tela
    Minhas Autorizações"), não estados internos. Entre duas etapas visíveis
    pode haver um estado de controle que ninguém vê na tela — por exemplo
    `pronto_para_operacao`, que marca "pré-requisitos aprovados, navegador
    aberto, aguardando o operador".

    Duas alternativas foram descartadas:

    - **relaxar o grafo** — perderíamos a garantia de que nenhuma fase é
      pulada, que é a razão de a máquina de estados existir;
    - **fazer a estação conhecer o grafo** — colocaria regra de negócio no
      cliente e qualquer Agent desatualizado passaria a mentir sobre o estado.

    Aqui cada salto continua sendo validado individualmente e gera seu próprio
    evento na trilha. Marcos que dependem de confirmação real do portal
    (`assinado`, `concluido`) **nunca** são usados como ponte: chegar neles
    exige passar por `registrar_outorga`/`registrar_aceite`, com protocolo ou
    texto do portal em mãos.
    """
    origem = StatusJob(job.status)
    if origem == destino:
        job.etapa_atual = (
            kwargs["etapa"].value if hasattr(kwargs.get("etapa"), "value") else job.etapa_atual
        )
        db.flush()
        return job

    if transicao_valida(origem, destino):
        return mudar_status(db, job, destino, **kwargs)

    caminho = _rota_ate(origem, destino)
    if caminho is None:
        raise TransicaoInvalidaError(origem, destino)

    for intermediario in caminho[:-1]:
        mudar_status(
            db,
            job,
            intermediario,
            mensagem=kwargs.get("mensagem", ""),
            ator=kwargs.get("ator", ""),
            agente_id=kwargs.get("agente_id"),
        )
    return mudar_status(db, job, destino, **kwargs)


#: Profundidade máxima da ponte. Três saltos cobrem o maior vão real do fluxo
#: (`atribuido → verificando → pronto → autenticando`). Mais que isso seria
#: pular fase demais para caber num único relato da estação.
MAX_SALTOS_PONTE = 3


def _rota_ate(origem: StatusJob, destino: StatusJob) -> list[StatusJob] | None:
    """Menor sequência de estados válidos entre `origem` e `destino`.

    Busca em largura no grafo real, excluindo marcos de confirmação, estados
    terminais e a intervenção manual como pontes — atravessar qualquer um
    desses automaticamente seria mentir sobre o que aconteceu.
    """
    from collections import deque

    fila_busca: deque[list[StatusJob]] = deque([[origem]])
    visitados = {origem}
    while fila_busca:
        caminho = fila_busca.popleft()
        if len(caminho) > MAX_SALTOS_PONTE:
            continue
        atual = caminho[-1]
        for proximo in TRANSICOES.get(atual, frozenset()):
            if proximo == destino:
                return caminho[1:] + [destino]
            if proximo in visitados:
                continue
            if (
                proximo in MARCOS_COM_CONFIRMACAO
                or proximo in ESTADOS_TERMINAIS
                or proximo is StatusJob.INTERVENCAO_MANUAL
            ):
                continue
            visitados.add(proximo)
            fila_busca.append(caminho + [proximo])
    return None
