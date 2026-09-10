"""
Trilha de auditoria: quem fez o quê, quando.

Uso típico dentro de um endpoint (antes do `commit` dele)::

    from app.services import auditoria
    auditoria.registrar(db, usuario, "empresa_criada",
                        entidade="empresa", entidade_id=empresa.id,
                        detalhe=empresa.razao_social)

A função só adiciona + `flush`: quem commita é o endpoint, então o registro
de auditoria e a mudança andam na mesma transação — ou os dois entram, ou
nenhum. Endpoints sem commit próprio (login, downloads) precisam commitar
explicitamente após chamar.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import RegistroAuditoria, Usuario


def registrar(
    db: Session,
    usuario: Usuario | None,
    acao: str,
    *,
    entidade: str | None = None,
    entidade_id: int | None = None,
    detalhe: str | None = None,
    email: str | None = None,
    escritorio_id: int | None = None,
) -> RegistroAuditoria:
    """Cria o registro e dá flush (o commit é do chamador)."""
    registro = RegistroAuditoria(
        escritorio_id=usuario.escritorio_id if usuario else escritorio_id,
        usuario_id=usuario.id if usuario else None,
        usuario_email=(usuario.email if usuario else email) or "",
        acao=acao[:60],
        entidade=entidade[:60] if entidade else None,
        entidade_id=entidade_id,
        detalhe=(detalhe or "")[:2000] or None,
    )
    db.add(registro)
    db.flush()
    return registro
