from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.security import decodificar_token
from app.db.session import get_db
from app.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def usuario_atual(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    credenciais_invalidas = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciais inválidas ou expiradas",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decodificar_token(token)
        email = payload.get("sub")
        if email is None:
            raise credenciais_invalidas
    except JWTError:
        raise credenciais_invalidas

    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None or not usuario.ativo:
        raise credenciais_invalidas
    return usuario


def escritorio_id_atual(usuario: Usuario = Depends(usuario_atual)) -> int:
    """
    Todo endpoint que lê/escreve dado de negócio usa isto para filtrar por
    tenant — é o que garante que um escritório nunca vê dado de outro,
    mesmo que o multiempresa ainda não esteja "ligado" no produto.
    """
    return usuario.escritorio_id
