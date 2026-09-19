"""
Dashboard executivo: KPIs, evolução, rankings e atividade.

Todas as rotas aqui são **leitura agregada** sobre dados que já existem —
nenhum efeito colateral, nenhuma consulta à SEFAZ. É o que transforma o banco
de XMLs em resposta para "como está meu escritório este mês?".
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.api.routers.importacoes import estados_do_escritorio
from app.core.config import settings
from app.core.tempo import hoje_operacional
from app.db.session import get_db
from app.models import (
    Certificado,
    DirecaoDocumento,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
)
from app.schemas import (
    EmitenteTop,
    EmpresaRanking,
    EvolucaoMensal,
    ExecucaoImportacaoResposta,
    KpisDashboard,
    TipoBreakdown,
)
from app.services.periodo import (
    Periodo,
    PeriodoInvalido,
    interpretar_competencia,
    interpretar_periodo,
    periodo_do_mes,
)
from app.services.referencia import data_referencia_sql

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_MES_CURTO = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
_ROTULO_TIPO = {"nfse": "NFS-e", "nfe": "NFe", "cte": "CT-e"}


def _mes_chave():
    """Agrupador mensal 'AAAA-MM' que funciona em PostgreSQL e SQLite."""
    comp = data_referencia_sql()
    if settings.usando_sqlite:
        return func.strftime("%Y-%m", comp)
    return func.to_char(comp, "YYYY-MM")


def _valor_liquido():
    """Soma de valores excluindo canceladas (é o número que o contador usa)."""
    return func.coalesce(
        func.sum(
            case(
                (
                    DocumentoFiscal.status != StatusDocumentoFiscal.CANCELADA,
                    DocumentoFiscal.valor_total,
                ),
                else_=0.0,
            )
        ),
        0.0,
    )


def _competencia_atual() -> str:
    hoje = hoje_operacional()
    return f"{hoje.month:02d}/{hoje.year:04d}"


def _periodo_competencia(competencia: str | None) -> Periodo:
    try:
        return interpretar_competencia((competencia or "").strip() or _competencia_atual())
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _mes_anterior(periodo: Periodo) -> Periodo:
    assert periodo.inicio is not None
    ano, mes = periodo.inicio.year, periodo.inicio.month - 1
    if mes < 1:
        ano, mes = ano - 1, 12
    return periodo_do_mes(ano, mes)


def _documentos_do_escritorio(db: Session, escritorio_id: int):
    return (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
    )


@router.get("/kpis", response_model=KpisDashboard)
def kpis(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = mês atual"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Os números da Visão geral: mês atual, saúde e certificados."""
    periodo = _periodo_competencia(competencia)
    anterior = _mes_anterior(periodo)
    comp = data_referencia_sql()

    base = _documentos_do_escritorio(db, escritorio_id)
    no_mes = base.filter(comp >= periodo.inicio, comp <= periodo.fim)
    documentos_mes = no_mes.count()
    canceladas_mes = no_mes.filter(
        DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA
    ).count()
    valor_mes = float(no_mes.with_entities(_valor_liquido()).scalar() or 0.0)
    documentos_anterior = base.filter(comp >= anterior.inicio, comp <= anterior.fim).count()
    variacao = (
        round((documentos_mes - documentos_anterior) / documentos_anterior * 100, 1)
        if documentos_anterior
        else None
    )

    sem_xml = base.filter(DocumentoFiscal.leiaute != "completo").count()
    documentos_total = base.count()

    empresas_ativas = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )
    ids_ativas = {empresa.id for empresa in empresas_ativas}
    certificados = {
        cert.empresa_id: cert
        for cert in db.query(Certificado)
        .filter(
            Certificado.empresa_id.in_(list(ids_ativas) or [-1]),
            Certificado.ativo.is_(True),
        )
        .all()
    }
    from datetime import datetime, timezone

    agora = datetime.now(timezone.utc)
    vencidos = vencendo = sem_cert = 0
    for empresa in empresas_ativas:
        cert = certificados.get(empresa.id)
        if cert is None:
            sem_cert += 1
            continue
        validade = cert.validade
        if validade is not None and validade.tzinfo is None:
            validade = validade.replace(tzinfo=timezone.utc)
        dias = (validade - agora).days if validade is not None else None
        if dias is not None and dias < 0:
            vencidos += 1
        elif dias is not None and dias <= 30:
            vencendo += 1

    estados = [e for e in estados_do_escritorio(db, escritorio_id=escritorio_id) if e.empresa_id in ids_ativas]
    combinacoes_em_dia = sum(1 for e in estados if e.em_dia)
    bloqueadas = sum(1 for e in estados if e.bloqueado_ate)
    em_andamento = sum(1 for e in estados if e.em_andamento)
    por_empresa: dict[int, list] = {}
    for estado in estados:
        por_empresa.setdefault(estado.empresa_id, []).append(estado)
    empresas_em_dia = sum(
        1 for lista in por_empresa.values() if lista and all(e.em_dia for e in lista)
    )

    return KpisDashboard(
        competencia=periodo.rotulo(),
        documentos_mes=documentos_mes,
        documentos_mes_anterior=documentos_anterior,
        variacao_pct=variacao,
        valor_mes=valor_mes,
        canceladas_mes=canceladas_mes,
        sem_xml_completo=sem_xml,
        documentos_total=documentos_total,
        empresas_total=len(empresas_ativas),
        empresas_em_dia=empresas_em_dia,
        combinacoes_em_dia=combinacoes_em_dia,
        combinacoes_total=len(estados),
        certificados_vencidos=vencidos,
        certificados_vencendo=vencendo,
        empresas_sem_certificado=sem_cert,
        bloqueadas_agora=bloqueadas,
        em_andamento=em_andamento,
    )


@router.get("/evolucao", response_model=list[EvolucaoMensal])
def evolucao(
    meses: int = Query(default=12, ge=1, le=24),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Série mensal dos últimos N meses (barras do dashboard)."""
    hoje = hoje_operacional()
    chaves: list[str] = []
    ano, mes = hoje.year, hoje.month
    for _ in range(meses):
        chaves.append(f"{ano:04d}-{mes:02d}")
        mes -= 1
        if mes < 1:
            ano, mes = ano - 1, 12

    chave = _mes_chave()
    linhas = (
        db.query(
            chave.label("mes"),
            func.count(DocumentoFiscal.id),
            _valor_liquido(),
            func.sum(case((DocumentoFiscal.tipo == TipoDocumentoFiscal.NFSE, 1), else_=0)),
            func.sum(case((DocumentoFiscal.tipo == TipoDocumentoFiscal.NFE, 1), else_=0)),
            func.sum(case((DocumentoFiscal.tipo == TipoDocumentoFiscal.CTE, 1), else_=0)),
        )
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, chave.in_(chaves))
        .group_by(chave)
        .all()
    )
    por_mes = {
        str(mes): (total or 0, float(valor or 0), int(nfse or 0), int(nfe or 0), int(cte or 0))
        for mes, total, valor, nfse, nfe, cte in linhas
    }

    saida: list[EvolucaoMensal] = []
    for codigo in sorted(chaves):
        ano_i, mes_i = int(codigo[:4]), int(codigo[5:7])
        total, valor, nfse, nfe, cte = por_mes.get(codigo, (0, 0.0, 0, 0, 0))
        saida.append(
            EvolucaoMensal(
                mes=codigo,
                rotulo=f"{_MES_CURTO[mes_i - 1]}/{str(ano_i)[2:]}",
                total=total,
                valor=valor,
                nfse=nfse,
                nfe=nfe,
                cte=cte,
            )
        )
    return saida


@router.get("/por-tipo", response_model=list[TipoBreakdown])
def por_tipo(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = tudo"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Quebra por NFS-e / NFe / CT-e no período (donut do dashboard)."""
    try:
        periodo = interpretar_periodo(competencia, None, None)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    consulta = _documentos_do_escritorio(db, escritorio_id)
    if periodo.definido:
        comp = data_referencia_sql()
        if periodo.inicio:
            consulta = consulta.filter(comp >= periodo.inicio)
        if periodo.fim:
            consulta = consulta.filter(comp <= periodo.fim)

    linhas = (
        consulta.with_entities(DocumentoFiscal.tipo, func.count(DocumentoFiscal.id), _valor_liquido())
        .group_by(DocumentoFiscal.tipo)
        .all()
    )
    por_tipo_map = {
        (tipo.value if hasattr(tipo, "value") else str(tipo)): (total or 0, float(valor or 0))
        for tipo, total, valor in linhas
    }
    total_geral = sum(total for total, _ in por_tipo_map.values())
    saida: list[TipoBreakdown] = []
    for tipo in TipoDocumentoFiscal:
        total, valor = por_tipo_map.get(tipo.value, (0, 0.0))
        saida.append(
            TipoBreakdown(
                tipo=tipo,
                rotulo=_ROTULO_TIPO.get(tipo.value, tipo.value),
                total=total,
                valor=valor,
                percentual=round(total / total_geral * 100, 1) if total_geral else 0.0,
            )
        )
    return saida


@router.get("/top-emitentes", response_model=list[EmitenteTop])
def top_emitentes(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = tudo"),
    limite: int = Query(default=8, ge=1, le=25),
    direcao: DirecaoDocumento = Query(default=DirecaoDocumento.TOMADA),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """De quem vêm os maiores valores (notas tomadas por padrão)."""
    try:
        periodo = interpretar_periodo(competencia, None, None)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    consulta = _documentos_do_escritorio(db, escritorio_id).filter(
        DocumentoFiscal.direcao == direcao
    )
    if periodo.definido:
        comp = data_referencia_sql()
        if periodo.inicio:
            consulta = consulta.filter(comp >= periodo.inicio)
        if periodo.fim:
            consulta = consulta.filter(comp <= periodo.fim)

    linhas = (
        consulta.with_entities(
            DocumentoFiscal.emitente_documento,
            DocumentoFiscal.emitente_nome,
            func.count(DocumentoFiscal.id),
            _valor_liquido(),
        )
        .group_by(DocumentoFiscal.emitente_documento, DocumentoFiscal.emitente_nome)
        .order_by(_valor_liquido().desc())
        .limit(limite)
        .all()
    )
    return [
        EmitenteTop(
            documento=documento,
            nome=nome,
            total=total or 0,
            valor=float(valor or 0),
        )
        for documento, nome, total, valor in linhas
    ]


@router.get("/ranking-empresas", response_model=list[EmpresaRanking])
def ranking_empresas(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = tudo"),
    limite: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Empresas ordenadas por volume de documentos no período."""
    try:
        periodo = interpretar_periodo(competencia, None, None)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    consulta = _documentos_do_escritorio(db, escritorio_id)
    if periodo.definido:
        comp = data_referencia_sql()
        if periodo.inicio:
            consulta = consulta.filter(comp >= periodo.inicio)
        if periodo.fim:
            consulta = consulta.filter(comp <= periodo.fim)

    linhas = (
        consulta.with_entities(
            Empresa.id,
            Empresa.razao_social,
            func.count(DocumentoFiscal.id),
            _valor_liquido(),
            func.sum(
                case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)
            ),
            func.sum(case((DocumentoFiscal.leiaute != "completo", 1), else_=0)),
        )
        .group_by(Empresa.id, Empresa.razao_social)
        .order_by(func.count(DocumentoFiscal.id).desc())
        .limit(limite)
        .all()
    )
    return [
        EmpresaRanking(
            empresa_id=empresa_id,
            razao_social=razao_social,
            total=total or 0,
            valor=float(valor or 0),
            canceladas=int(canceladas or 0),
            sem_xml=int(sem_xml or 0),
        )
        for empresa_id, razao_social, total, valor, canceladas, sem_xml in linhas
    ]


@router.get("/atividades", response_model=list[ExecucaoImportacaoResposta])
def atividades(
    limite: int = Query(default=12, ge=1, le=50),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """O feed 'o que o sistema andou fazendo' — últimas execuções."""
    execucoes = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
        .order_by(ExecucaoImportacao.id.desc())
        .limit(limite)
        .all()
    )
    respostas: list[ExecucaoImportacaoResposta] = []
    for execucao in execucoes:
        resposta = ExecucaoImportacaoResposta.model_validate(execucao)
        resposta.empresa_razao_social = execucao.empresa.razao_social
        respostas.append(resposta)
    return respostas
