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


def papel_do_usuario(usuario: Usuario) -> str:
    """Papel efetivo (`admin` para linhas antigas sem valor)."""
    return (usuario.papel or "admin").strip().lower() or "admin"


def requer_papel(*papeis: str):
    """
    Guarda de rota por papel: `admin: Usuario = Depends(requer_papel("admin"))`.

    Uso: gestão da equipe (só admin), auditoria e testes (admin/operador).
    """

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if papel_do_usuario(usuario) not in papeis:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu perfil não tem permissão para esta ação.",
            )
        return usuario

    return verificar


def requer_escrita(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
    """
    Bloqueia o perfil `leitura` nas rotas de mutação (cadastrar, importar,
    enviar certificado). Leitura e download continuam liberados.
    """
    if papel_do_usuario(usuario) == "leitura":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu perfil é somente leitura.",
        )
    return usuario
