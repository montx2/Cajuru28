from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import criar_token_acesso, verificar_senha
from app.db.session import get_db
from app.models import Usuario
from app.schemas import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/login", response_model=TokenResponse)
def login(dados: LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == dados.email).first()
    if usuario is None or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )
    if not usuario.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    token = criar_token_acesso(subject=usuario.email, escritorio_id=usuario.escritorio_id)
    return TokenResponse(access_token=token)
