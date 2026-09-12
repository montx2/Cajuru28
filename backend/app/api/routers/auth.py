"""Autenticação por sessão curta em cookie HttpOnly."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.api.deps import papel_do_usuario, usuario_atual
from app.core.config import settings
from app.core.rate_limit import limitar_login
from app.core.security import criar_token_acesso, gerar_hash_senha, rehash_necessario, verificar_senha
from app.db.session import get_db
from app.models import Escritorio, Usuario
from app.schemas import LoginRequest, TokenResponse, UsuarioAtual
from app.services import auditoria

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.get("/me", response_model=UsuarioAtual)
def quem_sou_eu(
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    escritorio = db.get(Escritorio, usuario.escritorio_id)
    return UsuarioAtual(
        id=usuario.id,
        nome=usuario.nome,
        email=usuario.email,
        papel=papel_do_usuario(usuario),
        escritorio_id=usuario.escritorio_id,
        escritorio_nome=escritorio.nome if escritorio else "Escritório",
    )


def _definir_cookie_sessao(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max(60, settings.access_token_expire_minutes * 60),
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )


@router.post("/login", response_model=TokenResponse)
def login(
    dados: LoginRequest,
    response: Response,
    _limite: None = Depends(limitar_login),
    db: Session = Depends(get_db),
):
    """Autentica sem revelar/armazenar bearer token no JavaScript do painel."""
    candidatos = (
        db.query(Usuario)
        .filter(Usuario.email == dados.email, Usuario.ativo.is_(True))
        .order_by(Usuario.id)
        .all()
    )
    correspondentes = [u for u in candidatos if verificar_senha(dados.senha, u.senha_hash)]
    # Não informa se o e-mail existe, está inativo ou é ambíguo entre tenants.
    if len(correspondentes) != 1:
        usuario_auditoria = candidatos[0] if len(candidatos) == 1 else None
        auditoria.registrar(
            db,
            usuario_auditoria,
            "login_falha",
            email=dados.email,
            escritorio_id=usuario_auditoria.escritorio_id if usuario_auditoria else None,
            detalhe="Credenciais inválidas ou identidade ambígua.",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )

    usuario = correspondentes[0]
    if rehash_necessario(usuario.senha_hash):
        usuario.senha_hash = gerar_hash_senha(dados.senha)
    auditoria.registrar(db, usuario, "login")
    db.commit()

    token = criar_token_acesso(
        usuario_id=usuario.id,
        escritorio_id=usuario.escritorio_id,
        versao_sessao=usuario.versao_sessao,
    )
    _definir_cookie_sessao(response, token)
    return TokenResponse()


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    usuario: Usuario = Depends(usuario_atual),
    db: Session = Depends(get_db),
):
    """Invalida todas as sessões do usuário e remove o cookie atual."""
    usuario.versao_sessao = (usuario.versao_sessao or 0) + 1
    auditoria.registrar(db, usuario, "logout")
    db.commit()
    response.delete_cookie(
        key=settings.session_cookie_name,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.session_cookie_samesite,
        path="/",
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
