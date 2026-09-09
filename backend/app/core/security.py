from datetime import datetime, timedelta, timezone

from jose import jwt
from passlib.context import CryptContext

from app.core.config import settings

# Isto é sobre a senha de LOGIN do usuário do sistema (contador, staff do
# escritório) — não confundir com a senha do certificado A1, que é tratada
# no cofre de segredos (app/core/vault.py). São dois problemas diferentes.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def gerar_hash_senha(senha_texto_puro: str) -> str:
    return _pwd_context.hash(senha_texto_puro)


def verificar_senha(senha_texto_puro: str, senha_hash: str) -> bool:
    return _pwd_context.verify(senha_texto_puro, senha_hash)


def criar_token_acesso(subject: str, escritorio_id: int) -> str:
    expira_em = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {"sub": subject, "escritorio_id": escritorio_id, "exp": expira_em}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decodificar_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
