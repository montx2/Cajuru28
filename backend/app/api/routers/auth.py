from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import papel_do_usuario, usuario_atual
from app.core.security import criar_token_acesso, verificar_senha
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
    """Quem está logado — nome e escritório para a barra superior."""
    escritorio = db.get(Escritorio, usuario.escritorio_id)
    return UsuarioAtual(
        id=usuario.id,
        nome=usuario.nome,
        email=usuario.email,
        papel=papel_do_usuario(usuario),
        escritorio_id=usuario.escritorio_id,
        escritorio_nome=escritorio.nome if escritorio else "Escritório",
    )


@router.post("/login", response_model=TokenResponse)
def login(dados: LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.email == dados.email).first()
    if usuario is None or not verificar_senha(dados.senha, usuario.senha_hash):
        auditoria.registrar(
            db, usuario if usuario else None, "login_falha",
            email=dados.email,
            escritorio_id=usuario.escritorio_id if usuario else None,
            detalhe="Credenciais inválidas.",
        )
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email ou senha incorretos",
        )
    if not usuario.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo")

    auditoria.registrar(db, usuario, "login")
    db.commit()
    token = criar_token_acesso(subject=usuario.email, escritorio_id=usuario.escritorio_id)
    return TokenResponse(access_token=token)
