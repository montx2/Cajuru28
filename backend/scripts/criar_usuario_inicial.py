"""
Cria o primeiro escritório e o primeiro usuário — não existe endpoint
público de "cadastro" de propósito (isso é uso interno, não SaaS aberto
ainda).

Uso interativo:
    docker compose exec api python scripts/criar_usuario_inicial.py

Uso não-interativo (CI / first boot):
    docker compose exec -T api python scripts/criar_usuario_inicial.py \
        --escritorio "Meu Escritório" \
        --nome "Admin" \
        --email admin@exemplo.com \
        --senha "senha-forte"
"""

from __future__ import annotations

import argparse
import getpass
import sys

sys.path.insert(0, "/app")

from app.core.security import gerar_hash_senha
from app.db.base import criar_tabelas
from app.db.session import SessionLocal
from app.models import Escritorio, Usuario


def main() -> None:
    parser = argparse.ArgumentParser(description="Cria o primeiro usuário do Fluxa")
    parser.add_argument("--escritorio", default=None)
    parser.add_argument("--nome", default=None)
    parser.add_argument("--email", default=None)
    parser.add_argument("--senha", default=None)
    args = parser.parse_args()

    criar_tabelas()
    db = SessionLocal()
    try:
        nome_escritorio = (args.escritorio or input("Nome do escritório: ")).strip()
        nome_usuario = (args.nome or input("Seu nome: ")).strip()
        email = (args.email or input("Seu email de login: ")).strip()
        if args.senha:
            senha = args.senha
        else:
            senha = getpass.getpass("Senha: ")

        if not nome_escritorio or not nome_usuario or not email or not senha:
            print("Todos os campos são obrigatórios.", file=sys.stderr)
            sys.exit(1)

        ja_existe = db.query(Usuario).filter(Usuario.email == email).first()
        if ja_existe:
            print(f"Já existe um usuário com o email '{email}'. Nada a fazer.")
            return

        escritorio = Escritorio(nome=nome_escritorio)
        db.add(escritorio)
        db.flush()

        usuario = Usuario(
            escritorio_id=escritorio.id,
            nome=nome_usuario,
            email=email,
            senha_hash=gerar_hash_senha(senha),
        )
        db.add(usuario)
        db.commit()

        print(f"\nPronto. Escritório '{nome_escritorio}' e usuário '{email}' criados.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
