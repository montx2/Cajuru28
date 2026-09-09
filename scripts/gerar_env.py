#!/usr/bin/env python3
"""
Gera backend/.env, frontend/.env.local e CREDENCIAIS.txt com chaves novas.
Idempotente: se o .env já existir, pergunta antes de sobrescrever (ou use --forcar).

Uso:
  python scripts/gerar_env.py
  python scripts/gerar_env.py --forcar
"""

from __future__ import annotations

import argparse
import base64
import secrets
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BACKEND_ENV = RAIZ / "backend" / ".env"
FRONTEND_ENV = RAIZ / "frontend" / ".env.local"
CREDENCIAIS = RAIZ / "CREDENCIAIS.txt"


def gerar() -> dict[str, str]:
    return {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "VAULT_MASTER_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "BOOTSTRAP_SENHA": secrets.token_urlsafe(16),
        "BOOTSTRAP_EMAIL": "admin@notasflow.local",
        "BOOTSTRAP_NOME": "Administrador",
        "BOOTSTRAP_ESCRITORIO": "Escritorio Cajuru",
    }


def escrever_backend_env(dados: dict[str, str]) -> None:
    BACKEND_ENV.parent.mkdir(parents=True, exist_ok=True)
    BACKEND_ENV.write_text(
        f"""# NotasFlow — gerado por scripts/gerar_env.py (NÃO versionar)
DATABASE_URL=postgresql://notasflow:notasflow@db:5432/notasflow
REDIS_URL=redis://redis:6379/0
SECRET_KEY={dados["SECRET_KEY"]}
VAULT_MASTER_KEY={dados["VAULT_MASTER_KEY"]}
DADOS_DIR=/data
ACCESS_TOKEN_EXPIRE_MINUTES=480
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,*
AMBIENTE_FISCAL=producao
BOOTSTRAP_ESCRITORIO={dados["BOOTSTRAP_ESCRITORIO"]}
BOOTSTRAP_NOME={dados["BOOTSTRAP_NOME"]}
BOOTSTRAP_EMAIL={dados["BOOTSTRAP_EMAIL"]}
BOOTSTRAP_SENHA={dados["BOOTSTRAP_SENHA"]}
""",
        encoding="utf-8",
    )


def escrever_frontend_env() -> None:
    FRONTEND_ENV.parent.mkdir(parents=True, exist_ok=True)
    FRONTEND_ENV.write_text("NEXT_PUBLIC_API_URL=http://localhost:8000\n", encoding="utf-8")


def escrever_credenciais(dados: dict[str, str]) -> None:
    CREDENCIAIS.write_text(
        f"""================================================================================
  NotasFlow — credenciais geradas automaticamente
  NÃO versionar este arquivo. Altere as senhas em produção.
================================================================================

LOGIN DO PAINEL (http://localhost:3000)
  Email:  {dados["BOOTSTRAP_EMAIL"]}
  Senha:  {dados["BOOTSTRAP_SENHA"]}
  Nome:   {dados["BOOTSTRAP_NOME"]}
  Escritório: {dados["BOOTSTRAP_ESCRITORIO"]}

CHAVES DO SISTEMA (backend/.env)
  SECRET_KEY={dados["SECRET_KEY"]}
  VAULT_MASTER_KEY={dados["VAULT_MASTER_KEY"]}

URLs
  Painel:  http://localhost:3000
  API:     http://localhost:8000/docs

COMO SUBIR
  Windows:  INICIAR.bat
  Terminal: docker compose up --build

================================================================================
""",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Gera .env e CREDENCIAIS.txt do NotasFlow")
    parser.add_argument("--forcar", action="store_true", help="Sobrescreve .env existente")
    args = parser.parse_args()

    if BACKEND_ENV.exists() and not args.forcar:
        print(f"Já existe {BACKEND_ENV}")
        print("Use --forcar para gerar de novo (invalida senhas de certificados já salvos).")
        # Ainda garante o frontend .env.local
        if not FRONTEND_ENV.exists():
            escrever_frontend_env()
            print(f"Criado {FRONTEND_ENV}")
        return 0

    dados = gerar()
    escrever_backend_env(dados)
    escrever_frontend_env()
    escrever_credenciais(dados)

    print("Arquivos criados:")
    print(f"  - {BACKEND_ENV}")
    print(f"  - {FRONTEND_ENV}")
    print(f"  - {CREDENCIAIS}")
    print()
    print("LOGIN:")
    print(f"  Email: {dados['BOOTSTRAP_EMAIL']}")
    print(f"  Senha: {dados['BOOTSTRAP_SENHA']}")
    print()
    print("Guarde o arquivo CREDENCIAIS.txt. Depois rode: docker compose up --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
