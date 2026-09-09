from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.db.session import get_db
from app.models import DocumentoFiscal, Empresa, TipoDocumentoFiscal
from app.schemas import DocumentoFiscalResposta

router = APIRouter(prefix="/documentos", tags=["documentos fiscais"])


@router.get("", response_model=list[DocumentoFiscalResposta])
def listar_documentos(
    empresa_id: int,
    tipo: TipoDocumentoFiscal | None = None,
    data_inicio: datetime | None = Query(default=None),
    data_fim: datetime | None = Query(default=None),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    consulta = db.query(DocumentoFiscal).filter(DocumentoFiscal.empresa_id == empresa_id)
    if tipo is not None:
        consulta = consulta.filter(DocumentoFiscal.tipo == tipo)
    if data_inicio is not None:
        consulta = consulta.filter(DocumentoFiscal.data_emissao >= data_inicio)
    if data_fim is not None:
        consulta = consulta.filter(DocumentoFiscal.data_emissao <= data_fim)

    return consulta.order_by(DocumentoFiscal.data_emissao.desc()).all()
