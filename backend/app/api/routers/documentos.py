from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
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
    limit: int = Query(default=500, le=2000),
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

    return consulta.order_by(DocumentoFiscal.data_emissao.desc()).limit(limit).all()


@router.get("/{documento_id}/xml")
def baixar_xml(
    documento_id: int,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """Download do XML original importado — o que o contador realmente precisa."""
    documento = (
        db.query(DocumentoFiscal)
        .join(Empresa)
        .filter(DocumentoFiscal.id == documento_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if documento is None:
        raise HTTPException(status_code=404, detail="Documento não encontrado")

    import os

    if not documento.xml_path or not os.path.isfile(documento.xml_path):
        raise HTTPException(status_code=404, detail="Arquivo XML não encontrado no disco")

    return FileResponse(
        documento.xml_path,
        media_type="application/xml",
        filename=f"{documento.chave_acesso}.xml",
    )
