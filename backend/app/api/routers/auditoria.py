"""
Consulta à trilha de auditoria (admin e operador).

Responde "quem baixou esta nota, quando" e "quem disparou aquela importação"
— o tipo de pergunta que aparece em escritório com mais de uma pessoa e em
qualquer discussão sobre compliance.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import requer_papel
from app.db.session import get_db
from app.models import RegistroAuditoria, Usuario
from app.schemas import RegistroAuditoriaResposta

router = APIRouter(prefix="/auditoria", tags=["auditoria"])

PodeVer = Depends(requer_papel("admin", "operador"))


@router.get("", response_model=list[RegistroAuditoriaResposta])
def listar_auditoria(
    acao: str | None = Query(default=None, description="filtrar por ação exata"),
    busca: str | None = Query(default=None, description="email, entidade ou detalhe"),
    limite: int = Query(default=100, ge=1, le=500),
    usuario: Usuario = PodeVer,
    db: Session = Depends(get_db),
):
    consulta = db.query(RegistroAuditoria).filter(
        RegistroAuditoria.escritorio_id == usuario.escritorio_id
    )
    if acao:
        consulta = consulta.filter(RegistroAuditoria.acao == acao.strip())
    if busca and busca.strip():
        padrao = f"%{busca.strip()}%"
        consulta = consulta.filter(
            (RegistroAuditoria.usuario_email.ilike(padrao))
            | (RegistroAuditoria.entidade.ilike(padrao))
            | (RegistroAuditoria.detalhe.ilike(padrao))
        )
    return consulta.order_by(RegistroAuditoria.id.desc()).limit(limite).all()


@router.get("/acoes", response_model=list[str])
def listar_acoes(
    usuario: Usuario = PodeVer,
    db: Session = Depends(get_db),
):
    """Ações distintas já registradas (alimenta o filtro da tela)."""
    linhas = (
        db.query(RegistroAuditoria.acao)
        .filter(RegistroAuditoria.escritorio_id == usuario.escritorio_id)
        .distinct()
        .order_by(RegistroAuditoria.acao)
        .all()
    )
    return [acao for (acao,) in linhas]
