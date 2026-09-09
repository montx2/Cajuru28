import os

from cryptography.fernet import Fernet

# Precisa estar setado ANTES de qualquer import de app.* (Settings lê do
# ambiente na importação do módulo).
os.environ.setdefault("DATABASE_URL", "postgresql://test:test@localhost/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "chave-de-teste-nao-usar-em-producao")
os.environ.setdefault("VAULT_MASTER_KEY", Fernet.generate_key().decode())
