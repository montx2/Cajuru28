from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.db.session import get_db
from app.models import Empresa
from app.schemas import EmpresaCriar, EmpresaResposta

router = APIRouter(prefix="/empresas", tags=["empresas"])


@router.get("", response_model=list[EmpresaResposta])
def listar_empresas(
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    return db.query(Empresa).filter(Empresa.escritorio_id == escritorio_id).all()


@router.post("", response_model=EmpresaResposta, status_code=status.HTTP_201_CREATED)
def criar_empresa(
    dados: EmpresaCriar,
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    ja_existe = (
        db.query(Empresa)
        .filter(Empresa.escritorio_id == escritorio_id, Empresa.cnpj_cpf == dados.cnpj_cpf)
        .first()
    )
    if ja_existe:
        raise HTTPException(status_code=409, detail="Já existe uma empresa com esse CNPJ/CPF")

    empresa = Empresa(escritorio_id=escritorio_id, **dados.model_dump())
    db.add(empresa)
    db.commit()
    db.refresh(empresa)
    return empresa


@router.get("/{empresa_id}", response_model=EmpresaResposta)
def obter_empresa(
    empresa_id: int,
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
    return empresa
