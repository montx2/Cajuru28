"""
Cria o primeiro escritório e o primeiro usuário — não existe endpoint
público de "cadastro" de propósito (isso é uso interno, não SaaS aberto
ainda). Rode uma vez:

    docker compose exec api python scripts/criar_usuario_inicial.py
"""

import getpass
import sys

sys.path.insert(0, "/app")

from app.core.security import gerar_hash_senha
from app.db.base import criar_tabelas
from app.db.session import SessionLocal
from app.models import Escritorio, Usuario


def main() -> None:
    criar_tabelas()
    db = SessionLocal()
    try:
        nome_escritorio = input("Nome do escritório: ").strip()
        nome_usuario = input("Seu nome: ").strip()
        email = input("Seu email de login: ").strip()
        senha = getpass.getpass("Senha: ")

        escritorio = Escritorio(nome=nome_escritorio)
        db.add(escritorio)
        db.flush()  # gera o id sem precisar commitar ainda

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
