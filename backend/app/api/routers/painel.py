"""
Painel operacional: a primeira tela do operador.

Aqui não se pergunta "como está meu escritório este mês?" (isso é relatório).
Pergunta-se: **"está tudo funcionando, e existe algo que EU preciso resolver?"**

Tudo é leitura agregada de estado que já existe — nenhuma consulta à SEFAZ,
nenhum efeito colateral. Os números são os da diretriz do sistema privado:

- empresas: cadastradas, habilitadas, sincronizadas hoje, aguardando janela,
  com erro, sem certificado;
- certificados: válidos, vencendo, vencidos;
- execuções: rodando agora, aguardando, bloqueadas, erros 24h, duração média;
- documentos: encontrados hoje, aguardando XML completo, mês corrente;
- componentes: banco, fila, worker, agendador — "tem alguém trabalhando?".
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.api.routers.alertas import computar_alertas
from app.api.routers.importacoes import estados_do_escritorio
from app.core.config import settings
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    StatusExecucao,
)
from app.schemas import (
    CentralExecucoes,
    ComponenteStatus,
    ExecucaoAoVivo,
    ExecucaoImportacaoResposta,
    JanelaProximaConsulta,
    PainelCertificados,
    PainelDocumentos,
    PainelEmpresas,
    PainelExecucoes,
    PainelOperacional,
    UltimaSincronizacao,
)
from app.services import batimento

router = APIRouter(prefix="/painel", tags=["painel operacional"])

_ROTULO_TIPO = {"nfse": "NFS-e", "nfe": "NFe", "cte": "CT-e"}


def _inicio_do_dia_utc() -> datetime:
    """
    Meia-noite do dia do OPERADOR, convertida para UTC.

    "Hoje" no painel é o dia de quem olha a tela, não o dia do relógio do
    container. Um documento importado às 22h de Brasília (01:20 UTC do dia
    seguinte) continua contando no "hoje" de quem está trabalhando.
    """
    agora_local = datetime.now().astimezone()
    meia_noite_local = agora_local.replace(hour=0, minute=0, second=0, microsecond=0)
    return meia_noite_local.astimezone(timezone.utc)


def _competencia_efetiva():
    return func.coalesce(DocumentoFiscal.competencia, func.date(DocumentoFiscal.data_emissao))


def _resposta_execucao(execucao: ExecucaoImportacao) -> ExecucaoImportacaoResposta:
    resposta = ExecucaoImportacaoResposta.model_validate(execucao)
    resposta.empresa_razao_social = execucao.empresa.razao_social
    return resposta


def _status_geral(criticos: int, atencao: int, componentes_ruins: int) -> tuple[str, str]:
    """O semáforo do topo — e a frase que o acompanha."""
    if criticos > 0 or componentes_ruins > 0:
        return (
            "critico",
            f"{criticos or componentes_ruins} ponto(s) exigem ação agora — comece pela lista de atenção.",
        )
    if atencao > 0:
        return (
            "atencao",
            f"Automação em atividade com {atencao} pendência(s) — nada urgente, mas vale resolver.",
        )
    return "operando", "Todas as sincronizações estão funcionando normalmente."


@router.get("/operacional", response_model=PainelOperacional)
def painel_operacional(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """O retrato completo de 'está tudo funcionando?' em uma chamada."""
    agora = datetime.now(timezone.utc)
    inicio_hoje = _inicio_do_dia_utc()
    corte_24h = agora - timedelta(hours=24)

    # ---- Alertas (critério único de prioridade do sistema) ----------------
    alertas = computar_alertas(db, escritorio_id)
    n_criticos = sum(1 for a in alertas if a.nivel == "critico")
    n_atencao = sum(1 for a in alertas if a.nivel == "atencao")
    n_info = sum(1 for a in alertas if a.nivel == "info")

    # ---- Empresas ----------------------------------------------------------
    empresas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )
    cadastradas = (
        db.query(func.count(Empresa.id))
        .filter(Empresa.escritorio_id == escritorio_id)
        .scalar()
        or 0
    )
    ids_ativas = [e.id for e in empresas]

    estados = estados_do_escritorio(db, escritorio_id=escritorio_id)
    estados_por_empresa: dict[int, list] = {}
    for estado in estados:
        estados_por_empresa.setdefault(estado.empresa_id, []).append(estado)

    sincronizadas_hoje: set[int] = set()
    execucoes_hoje = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.CONCLUIDA,
            ExecucaoImportacao.finalizado_em >= inicio_hoje,
        )
        .all()
    )
    sincronizadas_hoje = {ex.empresa_id for ex in execucoes_hoje}

    empresas_com_erro = (
        db.query(ExecucaoImportacao.empresa_id)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.ERRO,
            ExecucaoImportacao.iniciado_em >= corte_24h,
        )
        .distinct()
        .all()
    )
    ids_com_erro = {linha[0] for linha in empresas_com_erro}

    certificados_ativos = {
        c.empresa_id: c
        for c in db.query(Certificado)
        .filter(Certificado.empresa_id.in_(ids_ativas or [-1]), Certificado.ativo.is_(True))
        .all()
    }
    validos = vencendo = vencidos = 0
    for empresa in empresas:
        cert = certificados_ativos.get(empresa.id)
        if cert is None or cert.validade is None:
            continue
        validade = cert.validade
        if validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        dias = (validade - agora).days
        if dias < 0:
            vencidos += 1
        elif dias <= 30:
            vencendo += 1
        else:
            validos += 1

    em_dia_por_empresa = {
        eid: bool(lista) and all(e.em_dia for e in lista)
        for eid, lista in estados_por_empresa.items()
    }

    painel_empresas = PainelEmpresas(
        cadastradas=cadastradas,
        ativas=len(empresas),
        habilitadas_sincronizacao=sum(1 for e in empresas if e.sincronizar_automaticamente),
        sincronizadas_hoje=len(sincronizadas_hoje & set(ids_ativas)),
        em_dia=sum(1 for v in em_dia_por_empresa.values() if v),
        aguardando_janela=len(
            {e.empresa_id for e in estados if e.proxima_consulta_em or e.bloqueado_ate}
        ),
        com_erro_24h=len(ids_com_erro & set(ids_ativas)),
        sem_certificado=sum(1 for e in empresas if e.id not in certificados_ativos),
    )

    # ---- Execuções ----------------------------------------------------------
    em_andamento = (
        db.query(func.count(ExecucaoImportacao.id))
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.EM_ANDAMENTO,
        )
        .scalar()
        or 0
    )
    aguardando = (
        db.query(func.count(ExecucaoImportacao.id))
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.AGUARDANDO,
        )
        .scalar()
        or 0
    )
    erros_24h = (
        db.query(func.count(ExecucaoImportacao.id))
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.ERRO,
            ExecucaoImportacao.iniciado_em >= corte_24h,
        )
        .scalar()
        or 0
    )
    duracoes = [
        ex for ex in execucoes_hoje if ex.finalizado_em is not None
    ]
    duracao_media = None
    if duracoes:
        total_min = sum(
            (ex.finalizado_em - ex.iniciado_em).total_seconds() / 60 for ex in duracoes
        )
        duracao_media = round(total_min / len(duracoes), 1)

    painel_execucoes = PainelExecucoes(
        em_andamento=em_andamento,
        aguardando=aguardando,
        bloqueadas=len({e.empresa_id for e in estados if e.bloqueado_ate}),
        concluidas_hoje=len(execucoes_hoje),
        erros_24h=erros_24h,
        duracao_media_minutos=duracao_media,
    )

    # ---- Documentos ---------------------------------------------------------
    base_documentos = (
        db.query(DocumentoFiscal).join(Empresa).filter(Empresa.escritorio_id == escritorio_id)
    )
    documentos_hoje = (
        base_documentos.filter(DocumentoFiscal.importado_em >= inicio_hoje).count()
    )
    cancelados_hoje = (
        base_documentos.filter(
            DocumentoFiscal.importado_em >= inicio_hoje,
            DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA,
        ).count()
    )
    total_documentos = base_documentos.count()
    aguardando_xml = base_documentos.filter(DocumentoFiscal.leiaute == "resumo").count()

    hoje = date.today()
    comp = _competencia_efetiva()
    mes_atual = date(hoje.year, hoje.month, 1)
    fim_mes = date(hoje.year + (hoje.month == 12), (hoje.month % 12) + 1, 1) - timedelta(days=1)
    do_mes = base_documentos.filter(comp >= mes_atual, comp <= fim_mes)
    documentos_mes = do_mes.count()
    valor_mes = float(
        do_mes.with_entities(
            func.coalesce(
                func.sum(
                    case(
                        (DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA, DocumentoFiscal.valor_total),
                        else_=0.0,
                    )
                ),
                0.0,
            )
        ).scalar()
        or 0.0
    )

    painel_documentos = PainelDocumentos(
        hoje=documentos_hoje,
        cancelados_hoje=cancelados_hoje,
        total=total_documentos,
        aguardando_xml_completo=aguardando_xml,
        mes=documentos_mes,
        valor_mes=valor_mes,
        competencia=f"{hoje.month:02d}/{hoje.year:04d}",
    )

    # ---- Componentes de fundo ----------------------------------------------
    componentes: list[ComponenteStatus] = [
        ComponenteStatus(nome="api", status="ok", detalhe="Respondendo"),
    ]
    try:
        db.execute(select(1))
        componentes.append(ComponenteStatus(nome="banco", status="ok", detalhe="Conectado"))
    except Exception:  # noqa: BLE001
        componentes.append(ComponenteStatus(nome="banco", status="erro", detalhe="Sem resposta"))
    status_fila, detalhe_fila = batimento.situacao_fila()
    componentes.append(ComponenteStatus(nome="fila", status=status_fila, detalhe=detalhe_fila))
    status_worker, detalhe_worker = batimento.situacao_worker(db)
    componentes.append(
        ComponenteStatus(nome="worker", status=status_worker, detalhe=detalhe_worker)
    )
    status_agendador, detalhe_agendador = batimento.situacao_agendador(db)
    componentes.append(
        ComponenteStatus(
            nome="agendador", status=status_agendador, detalhe=detalhe_agendador
        )
    )
    componentes_ruins = sum(1 for c in componentes if c.status == "erro")

    # ---- Últimas sincronizações ---------------------------------------------
    ultimas_execucoes = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status.in_(
                [StatusExecucao.CONCLUIDA, StatusExecucao.ERRO, StatusExecucao.AGUARDANDO]
            ),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .limit(8)
        .all()
    )
    ultimas = [
        UltimaSincronizacao(
            empresa_id=ex.empresa_id,
            razao_social=ex.empresa.razao_social,
            tipo=ex.tipo.value,
            status=ex.status.value,
            documentos=ex.documentos_importados or 0,
            finalizado_em=ex.finalizado_em,
            iniciado_em=ex.iniciado_em,
            mensagem_erro=ex.mensagem_erro,
            aviso=ex.aviso,
        )
        for ex in ultimas_execucoes
    ]

    status_geral, mensagem = _status_geral(n_criticos, n_atencao, componentes_ruins)

    return PainelOperacional(
        status_geral=status_geral,
        mensagem=mensagem,
        alertas={"criticos": n_criticos, "atencao": n_atencao, "info": n_info},
        empresas=painel_empresas,
        certificados=PainelCertificados(validos=validos, vencendo=vencendo, vencidos=vencidos),
        execucoes=painel_execucoes,
        documentos=painel_documentos,
        componentes=componentes,
        ultimas_sincronizacoes=ultimas,
    )


@router.get("/execucoes", response_model=CentralExecucoes)
def central_execucoes(
    limite: int = Query(default=30, ge=5, le=100),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    A tela Execuções: tudo que o sistema está fazendo, sem log técnico.

    Três grupos, do mais vivo para o mais histórico:
    - `agora`: rodando ou esperando janela abrir (com o que já coletou);
    - `proximas`: quem volta a ser consultado e quando;
    - `recentes`/`erros`: o que terminou — resumo primeiro, detalhe por clique.
    """
    agora = datetime.now(timezone.utc)

    vivas = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status.in_(
                [StatusExecucao.EM_ANDAMENTO, StatusExecucao.AGUARDANDO]
            ),
        )
        .order_by(ExecucaoImportacao.iniciado_em.asc())
        .all()
    )
    ao_vivo = [
        ExecucaoAoVivo(
            execucao_id=ex.id,
            empresa_id=ex.empresa_id,
            razao_social=ex.empresa.razao_social,
            tipo=ex.tipo.value,
            status=ex.status.value,
            documentos_importados=ex.documentos_importados or 0,
            ultimo_nsu=ex.ultimo_nsu,
            iniciado_em=ex.iniciado_em,
            aguardando_ate=ex.bloqueado_ate,
            motivo_espera=ex.aviso,
            aviso=ex.aviso,
            mensagem_erro=ex.mensagem_erro,
        )
        for ex in vivas
    ]

    proximas: list[JanelaProximaConsulta] = []
    vivas_por_combinacao = {(ex.empresa_id, ex.tipo.value) for ex in vivas}
    for estado in estados_do_escritorio(db, escritorio_id=escritorio_id):
        if (estado.empresa_id, estado.tipo) in vivas_por_combinacao:
            continue
        quando = estado.bloqueado_ate or estado.proxima_consulta_em
        if quando is None:
            continue
        if quando.tzinfo is None:
            quando = quando.replace(tzinfo=timezone.utc)
        if quando <= agora:
            continue
        proximas.append(
            JanelaProximaConsulta(
                empresa_id=estado.empresa_id,
                razao_social=estado.razao_social,
                tipo=estado.tipo,
                proxima_consulta_em=quando,
                bloqueada=bool(estado.bloqueado_ate),
                pendencia=estado.pendencia,
            )
        )
    proximas.sort(key=lambda j: j.proxima_consulta_em)

    recentes = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status.in_(
                [StatusExecucao.CONCLUIDA, StatusExecucao.AGUARDANDO]
            ),
        )
        .order_by(ExecucaoImportacao.id.desc())
        .limit(limite)
        .all()
    )
    erros = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(
            Empresa.escritorio_id == escritorio_id,
            ExecucaoImportacao.status == StatusExecucao.ERRO,
        )
        .order_by(ExecucaoImportacao.id.desc())
        .limit(10)
        .all()
    )

    return CentralExecucoes(
        agora=ao_vivo,
        proximas=proximas,
        recentes=[_resposta_execucao(ex) for ex in recentes],
        erros=[_resposta_execucao(ex) for ex in erros],
    )
