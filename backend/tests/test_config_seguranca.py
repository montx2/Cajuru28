"""Produção falha fechada; conveniência local não pode vazar para deploy."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.core.config import ErroConfiguracaoProducao, Settings


def _producao_valida(**mudancas) -> Settings:
    valores = {
        "app_env": "production",
        "secret_key": "s" * 48,
        "database_url": "postgresql://notasflow:" + "b" * 24 + "@db:5432/notasflow",
        "redis_url": "redis://:" + "r" * 24 + "@redis:6379/0",
        "vault_master_key": Fernet.generate_key().decode(),
        "backup_encryption_key": Fernet.generate_key().decode(),
        "cors_origins": "https://fiscal.example.com.br",
        "trusted_hosts": "fiscal.example.com.br",
        "backup_dir": "/backups",
        "backup_s3_bucket": "notasflow-private",
        "backup_s3_prefix": "production",
        "access_token_expire_minutes": 20,
        "rate_limit_ativo": True,
    }
    valores.update(mudancas)
    return Settings(**valores)


def test_producao_aceita_apenas_configuracao_completa():
    _producao_valida().validar_producao()


@pytest.mark.parametrize(
    "mudancas, mensagem",
    [
        ({"secret_key": "curta"}, "SECRET_KEY"),
        ({"cors_origins": "*"}, "CORS_ORIGINS"),
        ({"trusted_hosts": "localhost"}, "TRUSTED_HOSTS"),
        ({"backup_dir": "/data/backups"}, "BACKUP_DIR"),
        ({"backup_s3_bucket": ""}, "BACKUP_S3_BUCKET"),
        ({"backup_encryption_key": ""}, "BACKUP_ENCRYPTION_KEY"),
        ({"vault_previous_master_keys": "chave-invalida"}, "VAULT_MASTER_KEY"),
        ({"rate_limit_ativo": False}, "RATE_LIMIT_ATIVO"),
        ({"access_token_expire_minutes": 61}, "ACCESS_TOKEN_EXPIRE_MINUTES"),
    ],
)
def test_producao_recusa_controles_ausentes_ou_inseguros(mudancas, mensagem):
    with pytest.raises(ErroConfiguracaoProducao, match=mensagem):
        _producao_valida(**mudancas).validar_producao()
