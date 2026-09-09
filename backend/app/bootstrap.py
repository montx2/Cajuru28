"""
Cria o primeiro escritório + usuário admin automaticamente no startup,
quando as variáveis BOOTSTRAP_* estão preenchidas no .env e ainda não
existe nenhum usuário no banco.

Idempotente: rodar de novo não duplica nada.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.core.security import gerar_hash_senha
from app.db.session import SessionLocal
from app.models import Escritorio, Usuario

log = logging.getLogger("notasflow.bootstrap")


def garantir_usuario_inicial() -> None:
    email = (settings.bootstrap_email or "").strip().lower()
    senha = settings.bootstrap_senha or ""
    if not email or not senha:
        return

    db = SessionLocal()
    try:
        if db.query(Usuario).count() > 0:
            return

        escritorio = Escritorio(nome=(settings.bootstrap_escritorio or "Escritorio").strip())
        db.add(escritorio)
        db.flush()

        usuario = Usuario(
            escritorio_id=escritorio.id,
            nome=(settings.bootstrap_nome or "Administrador").strip(),
            email=email,
            senha_hash=gerar_hash_senha(senha),
            ativo=True,
        )
        db.add(usuario)
        db.commit()
        log.info(
            "Usuário inicial criado: email=%s escritorio=%s",
            email,
            escritorio.nome,
        )
        print(
            f"[bootstrap] Usuário inicial pronto — login: {email} "
            f"(escritório: {escritorio.nome})"
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        log.exception("Falha no bootstrap do usuário inicial: %s", exc)
        print(f"[bootstrap] ERRO ao criar usuário inicial: {exc}")
    finally:
        db.close()
