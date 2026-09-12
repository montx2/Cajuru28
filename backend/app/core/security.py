"""Senhas e sessões do NotasFlow.

Sessões são curtas, vinculadas ao ID imutável do usuário e à versão de sessão
persistida no banco. Trocar senha/desativar uma conta invalida todos os JWTs
anteriores sem precisar manter tokens individuais em memória.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Novas senhas usam Argon2id. bcrypt é mantido apenas para verificar hashes
# legados e rehash no próximo login; bcrypt trunca em 72 bytes, Argon2id não.
_pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],
    deprecated="auto",
    argon2__type="ID",
    argon2__memory_cost=65536,
    argon2__time_cost=3,
    argon2__parallelism=2,
    bcrypt__truncate_error=False,
)


def gerar_hash_senha(senha_texto_puro: str) -> str:
    return _pwd_context.hash(senha_texto_puro)


def verificar_senha(senha_texto_puro: str, senha_hash: str) -> bool:
    """Verifica hashes Argon2 atuais e bcrypt legado sem quebrar logins antigos."""
    try:
        esquema = _pwd_context.identify(senha_hash)
        # Compatibilidade deliberada: instalações antigas gravavam bcrypt do
        # prefixo de 72 caracteres. Após sucesso, `rehash_necessario` grava a
        # senha completa em Argon2id.
        candidato = senha_texto_puro[:72] if esquema == "bcrypt" else senha_texto_puro
        return bool(_pwd_context.verify(candidato, senha_hash))
    except (ValueError, TypeError):
        return False


def rehash_necessario(senha_hash: str) -> bool:
    try:
        return bool(_pwd_context.needs_update(senha_hash))
    except (ValueError, TypeError):
        return True


def criar_token_acesso(usuario_id: int, escritorio_id: int, versao_sessao: int) -> str:
    agora = datetime.now(timezone.utc)
    expira_em = agora + timedelta(minutes=settings.access_token_expire_minutes)
    payload = {
        "sub": str(usuario_id),
        "escritorio_id": escritorio_id,
        "sv": versao_sessao,
        "jti": str(uuid4()),
        "iat": agora,
        "exp": expira_em,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decodificar_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.secret_key,
        algorithms=[settings.algorithm],
        issuer=settings.jwt_issuer,
        audience=settings.jwt_audience,
        options={"require": ["sub", "escritorio_id", "sv", "jti", "iat", "exp", "iss", "aud"]},
    )
