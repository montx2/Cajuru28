"""
Diagnostica (e resolve) problemas de login do Fluxa.

Uso:
    docker compose exec api python scripts/diagnosticar_login.py

Só diagnostica; nada é alterado. Para redefinir a senha de um usuário:

    docker compose exec api python scripts/diagnosticar_login.py \
        --redefinir admin@notasflow.local --senha "NovaSenha123"

Para criar o admin quando o banco está vazio:

    docker compose exec api python scripts/diagnosticar_login.py --criar-admin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Dentro do contêiner o código vive em /app; rodando fora dele, o pacote
# `app` está na pasta acima de scripts/. Aceitar os dois deixa o script
# utilizável também sem Docker.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "/app")

from app.core.config import settings
from app.core.security import gerar_hash_senha, verificar_senha
from app.db.base import criar_tabelas
from app.db.session import SessionLocal
from app.models import Escritorio, Usuario


def _linha() -> None:
    print("-" * 70)


def diagnosticar(db) -> None:
    print("=" * 70)
    print("  Fluxa — diagnóstico de login")
    print("=" * 70)

    # 1. Banco acessível?
    try:
        total = db.query(Usuario).count()
    except Exception as exc:  # noqa: BLE001
        print(f"[FALHA] Não consegui ler a tabela de usuários: {exc}")
        print("        O contêiner 'db' está saudável? docker compose ps")
        return

    print(f"[OK] Banco acessível. Usuários cadastrados: {total}")
    _linha()

    # 2. Bootstrap configurado?
    email_bootstrap = (settings.bootstrap_email or "").strip().lower()
    if not email_bootstrap or not settings.bootstrap_senha:
        print("[AVISO] BOOTSTRAP_EMAIL/BOOTSTRAP_SENHA vazios no backend/.env.")
        print("        Sem isso a API não cria o admin sozinha no startup.")
    else:
        print(f"[OK] Bootstrap configurado para: {email_bootstrap}")
    _linha()

    # 3. Nenhum usuário = ninguém consegue entrar.
    if total == 0:
        print("[CAUSA PROVÁVEL] O banco não tem nenhum usuário.")
        print("  O bootstrap só roda quando a tabela está vazia E as variáveis")
        print("  BOOTSTRAP_* estão preenchidas no momento em que a API sobe.")
        print()
        print("  Resolva com:")
        print("    docker compose exec api python scripts/diagnosticar_login.py --criar-admin")
        return

    # 4. Lista os usuários e confere a senha do bootstrap.
    print("Usuários no banco:")
    for u in db.query(Usuario).order_by(Usuario.id).all():
        estado = "ativo" if u.ativo else "INATIVO"
        papel = (u.papel or "admin").strip().lower()
        print(f"  #{u.id}  {u.email}  ({papel}, {estado})  escritório={u.escritorio_id}")
    _linha()

    if not email_bootstrap:
        return

    usuario = db.query(Usuario).filter(Usuario.email == email_bootstrap).first()
    if usuario is None:
        print(f"[CAUSA PROVÁVEL] Não existe usuário com o email '{email_bootstrap}'.")
        print("  O CREDENCIAIS.txt aponta para um email que não está no banco —")
        print("  típico de .env regerado depois que o banco já existia.")
        print()
        print("  Resolva entrando com um dos emails listados acima, ou:")
        print(f"    ... --redefinir <email-da-lista> --senha \"NovaSenha123\"")
        return

    if not usuario.ativo:
        print(f"[CAUSA] O usuário '{email_bootstrap}' está INATIVO — a API recusa o login.")
        print("  Resolva com --redefinir (ele é reativado junto).")
        return

    if verificar_senha(settings.bootstrap_senha, usuario.senha_hash):
        print(f"[OK] A senha do CREDENCIAIS.txt confere para '{email_bootstrap}'.")
        print()
        print("  Se mesmo assim o painel diz 'Não foi possível entrar', o problema")
        print("  não é a senha e sim o navegador não alcançar a API. Verifique:")
        print("    1. docker compose ps          -> api deve estar 'running'")
        print("    2. http://localhost:8000/saude -> deve responder {\"status\":\"ok\"}")
        print("    3. frontend/.env.local NEXT_PUBLIC_API_URL=http://localhost:8000")
        print("       (mudou? precisa rebuildar: docker compose up --build -d frontend)")
    else:
        print(f"[CAUSA] A senha do backend/.env NÃO confere com a gravada no banco.")
        print("  Isso acontece quando o .env foi regerado (senha nova) mas o banco")
        print("  ainda guarda o hash da senha antiga — o bootstrap não sobrescreve")
        print("  usuário existente, de propósito.")
        print()
        print("  Resolva com:")
        print(f'    docker compose exec api python scripts/diagnosticar_login.py \\')
        print(f'        --redefinir {email_bootstrap} --senha "NovaSenha123"')


def redefinir(db, email: str, senha: str) -> None:
    email = email.strip().lower()
    usuario = db.query(Usuario).filter(Usuario.email == email).first()
    if usuario is None:
        print(f"Não existe usuário com o email '{email}'.")
        print("Emails disponíveis:")
        for u in db.query(Usuario).order_by(Usuario.id).all():
            print(f"  - {u.email}")
        sys.exit(1)

    usuario.senha_hash = gerar_hash_senha(senha)
    usuario.ativo = True
    db.commit()
    print(f"Pronto. Senha redefinida e usuário reativado: {email}")
    print("Entre no painel em http://localhost:3000 com a senha nova.")


def criar_admin(db, email: str | None, senha: str | None) -> None:
    email = (email or settings.bootstrap_email or "admin@notasflow.local").strip().lower()
    senha = senha or settings.bootstrap_senha
    if not senha:
        print("Informe a senha com --senha (ou preencha BOOTSTRAP_SENHA no .env).")
        sys.exit(1)

    if db.query(Usuario).filter(Usuario.email == email).first():
        print(f"Já existe usuário '{email}'. Use --redefinir para trocar a senha.")
        sys.exit(1)

    escritorio = db.query(Escritorio).first()
    if escritorio is None:
        escritorio = Escritorio(nome=(settings.bootstrap_escritorio or "Escritorio").strip())
        db.add(escritorio)
        db.flush()

    db.add(
        Usuario(
            escritorio_id=escritorio.id,
            nome=(settings.bootstrap_nome or "Administrador").strip(),
            email=email,
            senha_hash=gerar_hash_senha(senha),
            papel="admin",
            ativo=True,
        )
    )
    db.commit()
    print(f"Admin criado: {email}")
    print("Entre no painel em http://localhost:3000.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostica problemas de login do Fluxa")
    parser.add_argument("--redefinir", metavar="EMAIL", help="Redefine a senha desse usuário")
    parser.add_argument("--criar-admin", action="store_true", help="Cria o admin inicial")
    parser.add_argument("--email", help="Email para --criar-admin")
    parser.add_argument("--senha", help="Senha nova")
    args = parser.parse_args()

    criar_tabelas()
    db = SessionLocal()
    try:
        if args.redefinir:
            if not args.senha:
                print("Use --senha junto com --redefinir.")
                sys.exit(1)
            redefinir(db, args.redefinir, args.senha)
        elif args.criar_admin:
            criar_admin(db, args.email, args.senha)
        else:
            diagnosticar(db)
    finally:
        db.close()


if __name__ == "__main__":
    main()
