import os

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import escritorio_id_atual
from app.core.config import settings
from app.core.vault import cifrar_segredo
from app.db.session import get_db
from app.models import Certificado, Empresa
from app.schemas import CertificadoResposta
from app.services.mtls import obter_validade_certificado

router = APIRouter(prefix="/certificados", tags=["certificados"])


@router.post("", response_model=CertificadoResposta, status_code=status.HTTP_201_CREATED)
async def enviar_certificado(
    empresa_id: int = Form(...),
    senha: str = Form(...),
    arquivo: UploadFile = File(...),
    db: Session = Depends(get_db),
    escritorio_id: int = Depends(escritorio_id_atual),
):
    """
    Recebe o .pfx e a senha em texto puro apenas nesta requisição (via
    HTTPS). A senha é cifrada e o arquivo original nunca é devolvido —
    dali em diante, só o cofre sabe abri-lo.
    """
    empresa = (
        db.query(Empresa)
        .filter(Empresa.id == empresa_id, Empresa.escritorio_id == escritorio_id)
        .first()
    )
    if empresa is None:
        raise HTTPException(status_code=404, detail="Empresa não encontrada")

    pfx_bytes = await arquivo.read()

    try:
        validade = obter_validade_certificado(pfx_bytes, senha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pasta_empresa = os.path.join(settings.dados_dir, "certificados", str(empresa_id))
    os.makedirs(pasta_empresa, exist_ok=True)
    caminho_arquivo = os.path.join(pasta_empresa, f"{empresa.cnpj_cpf}.pfx")
    with open(caminho_arquivo, "wb") as f:
        f.write(pfx_bytes)
    os.chmod(caminho_arquivo, 0o600)

    # Desativa certificados anteriores desta empresa — só um ativo por vez
    db.query(Certificado).filter(
        Certificado.empresa_id == empresa_id, Certificado.ativo.is_(True)
    ).update({"ativo": False})

    certificado = Certificado(
        empresa_id=empresa_id,
        arquivo_path=caminho_arquivo,
        senha_cifrada=cifrar_segredo(senha),
        validade=validade,
        ativo=True,
    )
    db.add(certificado)
    db.commit()
    db.refresh(certificado)
    return certificado


@router.get("/empresa/{empresa_id}", response_model=list[CertificadoResposta])
def listar_certificados_da_empresa(
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
    return db.query(Certificado).filter(Certificado.empresa_id == empresa_id).all()
