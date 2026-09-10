"""
Gestão da equipe do escritório (só `admin`).

Papéis:
- **admin** — tudo, incluindo gerenciar usuários;
- **operador** — cadastra empresas, envia certificados e dispara importações;
- **leitura** — só consulta e baixa (downloads liberados).

Não há exclusão: desligar alguém é `ativo=false`, preservando a trilha de
auditoria com o nome de quem fez cada ação.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import requer_papel
from app.core.security import gerar_hash_senha
from app.db.session import get_db
from app.models import Usuario
from app.schemas import UsuarioAtualizar, UsuarioCriar, UsuarioResposta
from app.services import auditoria

router = APIRouter(prefix="/usuarios", tags=["equipe"])

SoAdmin = Depends(requer_papel("admin"))


@router.get("", response_model=list[UsuarioResposta])
def listar_usuarios(
    admin: Usuario = SoAdmin,
    db: Session = Depends(get_db),
):
    return (
        db.query(Usuario)
        .filter(Usuario.escritorio_id == admin.escritorio_id)
        .order_by(Usuario.nome)
        .all()
    )


@router.post("", response_model=UsuarioResposta, status_code=status.HTTP_201_CREATED)
def criar_usuario(
    dados: UsuarioCriar,
    admin: Usuario = SoAdmin,
    db: Session = Depends(get_db),
):
    ja_existe = (
        db.query(Usuario)
        .filter(
            Usuario.escritorio_id == admin.escritorio_id,
            Usuario.email == dados.email,
        )
        .first()
    )
    if ja_existe:
        raise HTTPException(status_code=409, detail="Já existe um usuário com esse email.")

    usuario = Usuario(
        escritorio_id=admin.escritorio_id,
        nome=dados.nome,
        email=dados.email,
        senha_hash=gerar_hash_senha(dados.senha),
        papel=dados.papel,
        ativo=True,
    )
    db.add(usuario)
    db.flush()
    auditoria.registrar(
        db, admin, "usuario_criado",
        entidade="usuario", entidade_id=usuario.id,
        detalhe=f"{usuario.nome} <{usuario.email}> ({usuario.papel})",
    )
    db.commit()
    db.refresh(usuario)
    return usuario


@router.patch("/{usuario_id}", response_model=UsuarioResposta)
def atualizar_usuario(
    usuario_id: int,
    dados: UsuarioAtualizar,
    admin: Usuario = SoAdmin,
    db: Session = Depends(get_db),
):
    usuario = (
        db.query(Usuario)
        .filter(
            Usuario.id == usuario_id,
            Usuario.escritorio_id == admin.escritorio_id,
        )
        .first()
    )
    if usuario is None:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")

    mudancas = dados.model_dump(exclude_unset=True)
    if "senha" in mudancas and mudancas["senha"]:
        usuario.senha_hash = gerar_hash_senha(mudancas.pop("senha"))
    if "nome" in mudancas and mudancas["nome"] is not None:
        nome = (mudancas["nome"] or "").strip()
        if not nome:
            raise HTTPException(status_code=422, detail="Nome não pode ficar vazio.")
        usuario.nome = nome

    novo_papel = mudancas.get("papel")
    novo_ativo = mudancas.get("ativo")
    if usuario.id == admin.id:
        # Trava de segurança: ninguém se desativa nem se rebaixa sozinho.
        if novo_ativo is False:
            raise HTTPException(status_code=409, detail="Você não pode desativar o próprio acesso.")
        if novo_papel is not None and novo_papel != "admin":
            raise HTTPException(status_code=409, detail="Você não pode remover o próprio papel de admin.")
    if novo_papel is not None:
        # Não permitir rebaixar o último admin do escritório.
        if usuario.papel == "admin" and novo_papel != "admin":
            outros_admins = (
                db.query(Usuario)
                .filter(
                    Usuario.escritorio_id == admin.escritorio_id,
                    Usuario.id != usuario.id,
                    Usuario.papel == "admin",
                    Usuario.ativo.is_(True),
                )
                .count()
            )
            if outros_admins == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Este é o último admin do escritório — promova alguém antes.",
                )
        usuario.papel = novo_papel
    if novo_ativo is not None:
        usuario.ativo = novo_ativo

    auditoria.registrar(
        db, admin, "usuario_atualizado",
        entidade="usuario", entidade_id=usuario.id,
        detalhe=f"{usuario.nome} <{usuario.email}> ({usuario.papel}, {'ativo' if usuario.ativo else 'inativo'})",
    )
    db.commit()
    db.refresh(usuario)
    return usuario
