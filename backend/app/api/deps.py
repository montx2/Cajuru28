"""Dependências de autenticação e autorização.

A resolução de identidade usa exclusivamente o ID imutável presente no JWT.
E-mail é atributo de contato, não uma chave de segurança nem uma fronteira de
tenant.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decodificar_token
from app.db.session import get_db
from app.models import Usuario

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)


def _credenciais_invalidas() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Sessão inválida ou expirada",
        headers={"WWW-Authenticate": "Bearer"},
    )


def usuario_atual(
    request: Request,
    token_bearer: str | None = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> Usuario:
    """Carrega usuário e confirma tenant/versão da sessão em cada requisição."""
    token = token_bearer or request.cookies.get(settings.session_cookie_name)
    if not token:
        raise _credenciais_invalidas()
    try:
        payload = decodificar_token(token)
        usuario_id = int(payload["sub"])
        escritorio_token = int(payload["escritorio_id"])
        versao_token = int(payload["sv"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        raise _credenciais_invalidas()

    usuario = db.get(Usuario, usuario_id)
    if (
        usuario is None
        or not usuario.ativo
        or usuario.escritorio_id != escritorio_token
        or usuario.versao_sessao != versao_token
    ):
        raise _credenciais_invalidas()
    return usuario


def escritorio_id_atual(usuario: Usuario = Depends(usuario_atual)) -> int:
    """Tenant vem do usuário validado, nunca de parâmetro fornecido pelo cliente."""
    return usuario.escritorio_id


def papel_do_usuario(usuario: Usuario) -> str:
    """Papel efetivo (`admin` para linhas antigas sem valor)."""
    return (usuario.papel or "admin").strip().lower() or "admin"


def requer_papel(*papeis: str):
    """Guarda de rota por papel."""

    def verificar(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
        if papel_do_usuario(usuario) not in papeis:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Seu perfil não tem permissão para esta ação.",
            )
        return usuario

    return verificar


def requer_escrita(usuario: Usuario = Depends(usuario_atual)) -> Usuario:
    """Bloqueia o perfil `leitura` em rotas de mutação."""
    if papel_do_usuario(usuario) == "leitura":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Seu perfil é somente leitura.",
        )
    return usuario
