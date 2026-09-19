"""
Fechamento mensal: o mapa contábil de "o que entrou em cada empresa".

Enquanto `/documentos` lista nota a nota, aqui a unidade é empresa × tipo ×
mês — exatamente o recorte que o escritório usa para conferir o fechamento
antes de enviar ao cliente. Inclui versão CSV (Excel) do mesmo conteúdo.
"""

from __future__ import annotations

import csv
import io
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.core.tempo import hoje_operacional
from app.api.deps import escritorio_id_atual
from app.db.session import get_db
from app.models import (
    DocumentoFiscal,
    Empresa,
    StatusDocumentoFiscal,
    TipoDocumentoFiscal,
)
from app.schemas import FechamentoEmpresa, FechamentoMensal, FechamentoTipo, FechamentoTotais
from app.services.periodo import PeriodoInvalido, interpretar_competencia
from app.services.referencia import data_referencia_sql

router = APIRouter(prefix="/relatorios", tags=["relatórios"])


def _periodo(competencia: str | None):
    texto = (competencia or "").strip()
    if not texto:
        hoje = hoje_operacional()
        texto = f"{hoje.month:02d}/{hoje.year:04d}"
    try:
        return interpretar_competencia(texto)
    except PeriodoInvalido as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _valor_liquido():
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


def _linhas_fechamento(db: Session, escritorio_id: int, competencia: str | None):
    periodo = _periodo(competencia)
    comp = data_referencia_sql()
    linhas = (
        db.query(
            Empresa.id,
            Empresa.razao_social,
            Empresa.cnpj_cpf,
            Empresa.uf,
            DocumentoFiscal.tipo,
            func.count(DocumentoFiscal.id),
            _valor_liquido(),
            func.sum(
                case((DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA, 1), else_=0)
            ),
            func.sum(case((DocumentoFiscal.leiaute != "completo", 1), else_=0)),
        )
        .select_from(Empresa)
        .outerjoin(
            DocumentoFiscal,
            (DocumentoFiscal.empresa_id == Empresa.id)
            & (comp >= periodo.inicio)
            & (comp <= periodo.fim),
        )
        .filter(Empresa.escritorio_id == escritorio_id)
        .group_by(
            Empresa.id, Empresa.razao_social, Empresa.cnpj_cpf, Empresa.uf, DocumentoFiscal.tipo
        )
        .order_by(Empresa.razao_social)
        .all()
    )
    return periodo, linhas


def _montar_fechamento(db: Session, escritorio_id: int, competencia: str | None) -> FechamentoMensal:
    periodo, linhas = _linhas_fechamento(db, escritorio_id, competencia)

    por_empresa: dict[int, dict] = {}
    for empresa_id, razao, cnpj, uf, tipo, qtd, valor, canc, resumo in linhas:
        # LEFT JOIN: empresas sem documento no mês vêm com tipo NULL e qtd 0.
        entrada = por_empresa.setdefault(
            empresa_id,
            {
                "empresa_id": empresa_id,
                "razao_social": razao,
                "cnpj": cnpj,
                "uf": uf,
                "total": 0,
                "valor": 0.0,
                "canceladas": 0,
                "sem_xml": 0,
                "por_tipo": {t.value: {"qtd": 0, "valor": 0.0} for t in TipoDocumentoFiscal},
            },
        )
        if tipo is None:
            continue
        chave = tipo.value if hasattr(tipo, "value") else str(tipo)
        qtd_i, canc_i, resumo_i = int(qtd or 0), int(canc or 0), int(resumo or 0)
        valor_f = float(valor or 0)
        entrada["total"] += qtd_i
        entrada["valor"] += valor_f
        entrada["canceladas"] += canc_i
        entrada["sem_xml"] += resumo_i
        if chave in entrada["por_tipo"]:
            entrada["por_tipo"][chave]["qtd"] += qtd_i
            entrada["por_tipo"][chave]["valor"] += valor_f

    empresas = [
        FechamentoEmpresa(
            empresa_id=e["empresa_id"],
            razao_social=e["razao_social"],
            cnpj=e["cnpj"],
            uf=e["uf"],
            total=e["total"],
            valor=round(e["valor"], 2),
            canceladas=e["canceladas"],
            sem_xml=e["sem_xml"],
            por_tipo={k: FechamentoTipo(**v) for k, v in e["por_tipo"].items()},
        )
        for e in sorted(por_empresa.values(), key=lambda x: x["razao_social"])
    ]

    totais_tipos = {t.value: {"qtd": 0, "valor": 0.0} for t in TipoDocumentoFiscal}
    for empresa in empresas:
        for chave, bloco in empresa.por_tipo.items():
            totais_tipos[chave]["qtd"] += bloco.qtd
            totais_tipos[chave]["valor"] += bloco.valor

    assert periodo.inicio is not None and periodo.fim is not None
    return FechamentoMensal(
        competencia=periodo.rotulo(),
        inicio=periodo.inicio,
        fim=periodo.fim,
        totais=FechamentoTotais(
            documentos=sum(e.total for e in empresas),
            valor=round(sum(e.valor for e in empresas), 2),
            canceladas=sum(e.canceladas for e in empresas),
            sem_xml=sum(e.sem_xml for e in empresas),
            empresas_com_documento=sum(1 for e in empresas if e.total > 0),
            empresas_total=len(empresas),
            por_tipo={k: FechamentoTipo(**v) for k, v in totais_tipos.items()},
        ),
        empresas=empresas,
    )


@router.get("/fechamento", response_model=FechamentoMensal)
def fechamento_mensal(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = mês atual"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Mapa empresa × tipo do mês: quantidades, valores e pendências."""
    return _montar_fechamento(db, escritorio_id, competencia)


@router.get("/fechamento.csv")
def fechamento_csv(
    competencia: str | None = Query(default=None, description="MM/AAAA — vazio = mês atual"),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """O mesmo fechamento em CSV (separador `;`, abre direto no Excel)."""
    fechamento = _montar_fechamento(db, escritorio_id, competencia)

    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(
        [
            "competencia",
            "empresa",
            "cnpj",
            "uf",
            "tipo",
            "documentos",
            "valor_total",
            "canceladas",
            "sem_xml_completo",
        ]
    )
    for empresa in fechamento.empresas:
        for tipo, bloco in empresa.por_tipo.items():
            if bloco.qtd == 0:
                continue
            escritor.writerow(
                [
                    fechamento.competencia,
                    empresa.razao_social,
                    empresa.cnpj,
                    empresa.uf,
                    tipo,
                    bloco.qtd,
                    f"{bloco.valor:.2f}".replace(".", ","),
                    empresa.canceladas if tipo == "nfse" else "",
                    empresa.sem_xml if tipo == "nfse" else "",
                ]
            )
    escritor.writerow(
        [
            fechamento.competencia,
            "TOTAL",
            "",
            "",
            "todos",
            fechamento.totais.documentos,
            f"{fechamento.totais.valor:.2f}".replace(".", ","),
            fechamento.totais.canceladas,
            fechamento.totais.sem_xml,
        ]
    )

    corpo = "\ufeff" + saida.getvalue()
    nome = f"NotasFlow_fechamento_{fechamento.competencia.replace('/', '-')}.csv"
    return StreamingResponse(
        iter([corpo.encode("utf-8")]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nome}"'},
    )
