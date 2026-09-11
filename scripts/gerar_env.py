#!/usr/bin/env python3
"""
Gera backend/.env, frontend/.env.local e CREDENCIAIS.txt com chaves novas.
Ao recriar um .env existente, preserva a VAULT_MASTER_KEY por padrão: mudar
essa chave torna as senhas de certificados já gravados indecifráveis.

Uso:
  python scripts/gerar_env.py
  python scripts/gerar_env.py --forcar
  python scripts/gerar_env.py --forcar --trocar-chave-cofre
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


def gerar(vault_master_key: str | None = None) -> dict[str, str]:
    return {
        "SECRET_KEY": secrets.token_urlsafe(48),
        "VAULT_MASTER_KEY": vault_master_key or base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
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
# Use apenas durante uma rotação temporária; separe chaves antigas por vírgula.
VAULT_PREVIOUS_MASTER_KEYS=
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
    args = parser.parse_args()

    if args.trocar_chave_cofre and not args.forcar:
        parser.error("--trocar-chave-cofre exige --forcar")

    if BACKEND_ENV.exists() and not args.forcar:
        print(f"Já existe {BACKEND_ENV}")
        print("Use --forcar para gerar de novo. A VAULT_MASTER_KEY existente será preservada.")
        # Ainda garante o frontend .env.local
        if not FRONTEND_ENV.exists():
            escrever_frontend_env()
            print(f"Criado {FRONTEND_ENV}")
        return 0

    chave_cofre_anterior = None
    if BACKEND_ENV.exists() and not args.trocar_chave_cofre:
        chave_cofre_anterior = ler_valor_env(BACKEND_ENV, "VAULT_MASTER_KEY")
        if chave_cofre_anterior:
            print("Preservando a VAULT_MASTER_KEY existente para manter os certificados acessíveis.")

    dados = gerar(vault_master_key=chave_cofre_anterior)
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
    print("Guarde o arquivo CREDENCIAIS.txt. Depois rode: docker compose up --build")
    return 0


if __name__ == "__main__":
    sys.exit(main())
