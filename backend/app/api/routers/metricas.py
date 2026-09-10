"""
Métricas no formato de exposição do Prometheus (`GET /metricas`).

Sem dependência nova: o formato texto é simples o bastante para montar na
mão. Exige autenticação (o Prometheus envia o JWT no header `Authorization`),
então cada escritório expõe só os próprios números.

Exemplo de scrape_config:

    scrape_configs:
      - job_name: notasflow
        authorization:
          credentials: <JWT de um usuário leitura>
        static_configs:
          - targets: ["api:8000"]
        metrics_path: /metricas
"""

from fastapi import APIRouter, Depends
from fastapi.responses import PlainTextResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.api.routers.alertas import computar_alertas
from app.db.session import get_db
from app.models import (
    Certificado,
    DocumentoFiscal,
    Empresa,
    ExecucaoImportacao,
    StatusDocumentoFiscal,
    StatusExecucao,
)

router = APIRouter(tags=["observabilidade"])


def _linhas() -> list[str]:
    return []


def _gauge(saida: list[str], nome: str, ajuda: str, valor: float, rotulos: str = "") -> None:
    saida.append(f"# HELP {nome} {ajuda}")
    saida.append(f"# TYPE {nome} gauge")
    saida.append(f"{nome}{rotulos} {valor}")


@router.get("/metricas", response_class=PlainTextResponse)
def metricas(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    docs = (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
    )
    total_docs = docs.count()
    resumos = docs.filter(DocumentoFiscal.leiaute == "resumo").count()
    canceladas = docs.filter(
        DocumentoFiscal.status == StatusDocumentoFiscal.CANCELADA
    ).count()

    por_tipo = (
        docs.with_entities(DocumentoFiscal.tipo, func.count(DocumentoFiscal.id))
        .group_by(DocumentoFiscal.tipo)
        .all()
    )

    execs = (
        db.query(ExecucaoImportacao)
        .join(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id)
    )
    por_status = (
        execs.with_entities(ExecucaoImportacao.status, func.count(ExecucaoImportacao.id))
        .group_by(ExecucaoImportacao.status)
        .all()
    )

    empresas_ativas = (
        db.query(Empresa.id)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.ativa.is_(True))
        .all()
    )
    ids_ativas = [linha[0] for linha in empresas_ativas]
    com_cert = (
        db.query(func.count(func.distinct(Certificado.empresa_id)))
        .filter(
            Certificado.empresa_id.in_(ids_ativas or [-1]),
            Certificado.ativo.is_(True),
        )
        .scalar()
        or 0
    )

    alertas = computar_alertas(db, escritorio_id)
    criticos = sum(1 for a in alertas if a.nivel == "critico")
    atencao = sum(1 for a in alertas if a.nivel == "atencao")

    saida = _linhas()
    _gauge(saida, "notasflow_build_info", "Versao da API.", 1, '{versao="2.1.0"}')
    _gauge(saida, "notasflow_empresas_ativas", "Empresas ativas.", len(ids_ativas))
    _gauge(saida, "notasflow_empresas_com_certificado", "Empresas com A1 ativo.", com_cert)
    _gauge(saida, "notasflow_documentos_total", "Documentos no banco.", total_docs)
    _gauge(saida, "notasflow_documentos_so_resumo", "Documentos aguardando XML.", resumos)
    _gauge(saida, "notasflow_documentos_cancelados", "Documentos cancelados.", canceladas)
    for tipo, qtd in por_tipo:
        nome = tipo.value if hasattr(tipo, "value") else str(tipo)
        _gauge(
            saida, "notasflow_documentos_por_tipo",
            "Documentos por tipo.", qtd or 0, f'{{tipo="{nome}"}}',
        )
    for st, qtd in por_status:
        nome = st.value if hasattr(st, "value") else str(st)
        _gauge(
            saida, "notasflow_execucoes_por_status",
            "Execucoes por status.", qtd or 0, f'{{status="{nome}"}}',
        )
    _gauge(saida, "notasflow_alertas_criticos", "Alertas criticos abertos.", criticos)
    _gauge(saida, "notasflow_alertas_atencao", "Alertas de atencao abertos.", atencao)
    return "\n".join(saida) + "\n"
