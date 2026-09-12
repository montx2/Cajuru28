#!/usr/bin/env python3
"""
Gera backend/.env, frontend/.env.local e CREDENCIAIS.txt com chaves novas.
Ao recriar um .env existente, preserva VAULT_MASTER_KEY e
BACKUP_ENCRYPTION_KEY por padrão: trocá-las torna certificados ou backups
históricos irrecuperáveis.

Uso:
  python scripts/gerar_env.py
  python scripts/gerar_env.py --forcar
  python scripts/gerar_env.py --forcar --trocar-chave-cofre
  python scripts/gerar_env.py --forcar --trocar-chave-backup
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


def ler_valor_env(caminho: Path, nome: str) -> str | None:
    """Lê uma variável simples de um .env sem carregar seus segredos no ambiente."""
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        if chave.strip() != nome:
            continue
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in {"'", '"'}:
            valor = valor[1:-1]
        return valor or None
    return None


def gerar(
    vault_master_key: str | None = None,
    backup_encryption_key: str | None = None,
) -> dict[str, str]:
    return {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "VAULT_MASTER_KEY": vault_master_key or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "BACKUP_ENCRYPTION_KEY": backup_encryption_key or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
        "BOOTSTRAP_SENHA": secrets.token_urlsafe(16),
        "BOOTSTRAP_EMAIL": "admin@notasflow.local",
        "BOOTSTRAP_NOME": "Administrador",
        "BOOTSTRAP_ESCRITORIO": "Escritorio Cajuru",
    }


def escrever_backend_env(dados: dict[str, str]) -> None:
    BACKEND_ENV.parent.mkdir(parents=True, exist_ok=True)
    BACKEND_ENV.write_text(
        f"""# NotasFlow — gerado por scripts/gerar_env.py (NÃO versionar)
APP_ENV=development
DATABASE_URL=postgresql://notasflow:notasflow@db:5432/notasflow
REDIS_URL=redis://redis:6379/0
SECRET_KEY={dados["SECRET_KEY"]}
VAULT_MASTER_KEY={dados["VAULT_MASTER_KEY"]}
BACKUP_ENCRYPTION_KEY={dados["BACKUP_ENCRYPTION_KEY"]}
# Chaves de pacotes antigos durante uma rotação; separe por vírgula.
BACKUP_PREVIOUS_ENCRYPTION_KEYS=
# Use apenas durante uma rotação temporária; separe chaves antigas por vírgula.
VAULT_PREVIOUS_MASTER_KEYS=
DADOS_DIR=/data
BACKUP_DIR=/backups
ACCESS_TOKEN_EXPIRE_MINUTES=20
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000
TRUSTED_HOSTS=localhost,127.0.0.1,testserver
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
  BACKUP_ENCRYPTION_KEY={dados["BACKUP_ENCRYPTION_KEY"]}

URLs
  Painel:  http://localhost:3000
  (Se esta porta estiver ocupada/reservada no Windows, o INICIAR.bat
   escolhe outra sozinho e mostra o endereco certo no final.)
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
    parser.add_argument(
        "--trocar-chave-cofre",
        action="store_true",
        help="Gera outra VAULT_MASTER_KEY (certificados existentes precisarão ser reenviados)",
    )
    parser.add_argument(
        "--trocar-chave-backup",
        action="store_true",
        help="Gera outra BACKUP_ENCRYPTION_KEY (pacotes antigos não poderão ser abertos)",
    )
    args = parser.parse_args()

    if (args.trocar_chave_cofre or args.trocar_chave_backup) and not args.forcar:
        parser.error("--trocar-chave-cofre/--trocar-chave-backup exigem --forcar")

    if BACKEND_ENV.exists() and not args.forcar:
        print(f"Já existe {BACKEND_ENV}")
        print("Use --forcar para gerar de novo. As chaves de cofre e backup existentes serão preservadas.")
        # Ainda garante o frontend .env.local
        if not FRONTEND_ENV.exists():
            escrever_frontend_env()
            print(f"Criado {FRONTEND_ENV}")
        return 0

    chave_cofre_anterior = None
    chave_backup_anterior = None
    if BACKEND_ENV.exists() and not args.trocar_chave_cofre:
        chave_cofre_anterior = ler_valor_env(BACKEND_ENV, "VAULT_MASTER_KEY")
        if chave_cofre_anterior:
            print("Preservando a VAULT_MASTER_KEY existente para manter os certificados acessíveis.")
    if BACKEND_ENV.exists() and not args.trocar_chave_backup:
        chave_backup_anterior = ler_valor_env(BACKEND_ENV, "BACKUP_ENCRYPTION_KEY")
        if chave_backup_anterior:
            print("Preservando a BACKUP_ENCRYPTION_KEY para manter os backups acessíveis.")

    dados = gerar(
        vault_master_key=chave_cofre_anterior,
        backup_encryption_key=chave_backup_anterior,
    )
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
    if args.trocar_chave_cofre:
        print(
            "ATENÇÃO: a chave do cofre foi trocada. Restaure a chave anterior em "
            "VAULT_PREVIOUS_MASTER_KEYS ou reenvie cada certificado A1."
        )
    if args.trocar_chave_backup:
        print(
            "ATENÇÃO: a chave de backup foi trocada. Guarde a chave anterior em "
            "um cofre externo; ela é necessária para abrir pacotes históricos."
        )
    print("Guarde o arquivo CREDENCIAIS.txt. Depois rode: docker compose up --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
