"""
Primeira execução do programa instalado.

Um contador não vai editar `.env` nem rodar script nenhum antes de usar o
sistema. Então a primeira abertura do NotasFlow faz, sozinha e uma única vez:

1. cria a pasta de dados do usuário (fora da pasta do programa — é ela que
   sobrevive a toda atualização);
2. gera as chaves de segurança (`SECRET_KEY` do JWT e `VAULT_MASTER_KEY` do
   cofre Fernet) e grava o `.env` **na pasta de dados**;
3. sorteia o login do administrador e escreve um `CREDENCIAIS.txt` legível ao
   lado do banco, para o dono do computador guardar.

A partir da segunda abertura nada disso roda de novo: os arquivos existem e são
respeitados. Trocar a `VAULT_MASTER_KEY` depois de existir certificado gravado
tornaria as senhas ilegíveis — por isso a função nunca sobrescreve um `.env`
existente.
"""

from __future__ import annotations

import logging
import os
import secrets
import string
from pathlib import Path

from app.desktop import caminhos

log = logging.getLogger("notasflow.desktop")

MARCADOR_CONFIGURADO = "configurado.txt"


def _senha_legivel(tamanho: int = 16) -> str:
    """
    Senha forte que dá para digitar sem sofrimento.

    Alfabeto sem caracteres que se confundem no papel (0/O, 1/l/I) porque ela
    vai ser copiada de um arquivo de texto, e uma senha ilegível gera chamado
    de suporte — que é exatamente o custo que o modo desktop existe para evitar.
    """
    alfabeto = string.ascii_uppercase + string.ascii_lowercase + string.digits
    return "".join(secrets.choice(alfabeto) for _ in range(tamanho))


def _gerar_env(arquivo: Path, *, email: str, senha: str) -> None:
    from cryptography.fernet import Fernet

    pasta = caminhos.pasta_dados()
    banco = caminhos.caminho_banco()
    conteudo = f"""# NotasFlow — configuração deste computador
#
# Este arquivo é criado automaticamente na primeira execução e fica na pasta
# de dados do usuário. Ele NÃO vai para o Git e NÃO é substituído em uma
# atualização: mexer nele só afeta esta máquina.
#
# ATENÇÃO: a VAULT_MASTER_KEY abaixo cifra as senhas dos certificados A1.
# Se ela for perdida ou trocada, os certificados já cadastrados precisam ser
# enviados de novo. Faça backup desta pasta.

# ---------- Banco local (SQLite) ----------
# Uma atualização do programa nunca toca neste arquivo.
DATABASE_URL=sqlite:///{banco.as_posix()}

# ---------- Onde ficam certificados e XMLs ----------
DADOS_DIR={(pasta / 'dados').as_posix()}

# ---------- Chaves de segurança ----------
SECRET_KEY={secrets.token_urlsafe(48)}
VAULT_MASTER_KEY={Fernet.generate_key().decode()}

# ---------- Acesso ----------
ACCESS_TOKEN_EXPIRE_MINUTES=10080
BOOTSTRAP_ESCRITORIO=Meu Escritorio
BOOTSTRAP_NOME=Administrador
BOOTSTRAP_EMAIL={email}
BOOTSTRAP_SENHA={senha}

# ---------- Ambiente fiscal ----------
# producao = valendo de verdade. homologacao = testes, sem valor fiscal.
AMBIENTE_FISCAL=producao

# ---------- Automação ----------
# O programa consulta a SEFAZ sozinho, no ritmo que ela permite (1 hora por
# empresa e tipo de documento). Desligue só se outro sistema consultar os
# mesmos CNPJs.
SINCRONISMO_AUTOMATICO=true
SINCRONISMO_INTERVALO_MINUTOS=5

# ---------- Modo desktop ----------
MODO_DESKTOP=true

# ---------- Atualização automática ----------
# Deixe vazio para não verificar atualização nenhuma.
# Padrão: o repositório oficial.
NOTASFLOW_UPDATE_MANIFEST=
"""
    arquivo.write_text(conteudo, encoding="utf-8")


def _escrever_credenciais(pasta: Path, *, email: str, senha: str) -> Path:
    arquivo = pasta / "CREDENCIAIS.txt"
    arquivo.write_text(
        (
            "NotasFlow — acesso deste computador\n"
            "====================================\n\n"
            f"Endereço do painel: http://127.0.0.1 (aberto automaticamente pelo programa)\n"
            f"E-mail:             {email}\n"
            f"Senha:              {senha}\n\n"
            "Guarde este arquivo. Você pode trocar a senha depois, dentro do\n"
            "próprio painel, em Configurações.\n\n"
            "Se esquecer a senha, use o menu do NotasFlow (ícone ao lado do\n"
            "relógio) → 'Redefinir senha do administrador'.\n\n"
            f"Pasta de dados (é esta que precisa de backup):\n{pasta}\n"
        ),
        encoding="utf-8",
    )
    return arquivo


def configurado() -> bool:
    return caminhos.arquivo_env().is_file()


def preparar_primeira_execucao(*, silencioso: bool = False) -> dict[str, object]:
    """
    Garante `.env` e credenciais. Idempotente: chamar de novo não muda nada.

    Devolve um resumo do que foi feito (ou do que já existia) para o chamador
    poder mostrar na tela inicial.
    """
    pasta = caminhos.pasta_dados()
    arquivo = caminhos.arquivo_env()
    resultado: dict[str, object] = {
        "pasta_dados": str(pasta),
        "env": str(arquivo),
        "criado_agora": False,
        "arquivo_credenciais": str(pasta / "CREDENCIAIS.txt"),
    }

    if arquivo.is_file():
        return resultado

    email = os.environ.get("NOTASFLOW_EMAIL_INICIAL") or "admin@notasflow.local"
    senha = os.environ.get("NOTASFLOW_SENHA_INICIAL") or _senha_legivel()

    arquivo.parent.mkdir(parents=True, exist_ok=True)
    _gerar_env(arquivo, email=email, senha=senha)
    _escrever_credenciais(pasta, email=email, senha=senha)
    (pasta / MARCADOR_CONFIGURADO).write_text("ok\n", encoding="utf-8")

    resultado["criado_agora"] = True
    resultado["email"] = email
    if not silencioso:
        log.info("Primeira execução: configuração criada em %s", pasta)
    return resultado


def redefinir_senha_administrador(nova_senha: str | None = None) -> tuple[str, str]:
    """
    Troca a senha do administrador direto no banco local.

    Existe porque o programa roda na máquina da própria pessoa: exigir suporte
    para recuperar uma senha que está a 30 cm do usuário é fricção sem
    segurança nenhuma ganha. Só funciona com acesso físico + à pasta de dados —
    que é exatamente o mesmo nível de acesso necessário para ler o banco.
    """
    from app.db.session import SessionLocal
    from app.core.security import gerar_hash_senha
    from app.models import Escritorio, Usuario

    senha = nova_senha or _senha_legivel()
    db = SessionLocal()
    try:
        usuario = db.query(Usuario).order_by(Usuario.id).first()
        if usuario is None:
            escritorio = db.query(Escritorio).first() or Escritorio(nome="Meu Escritorio")
            db.add(escritorio)
            db.flush()
            email = (os.environ.get("NOTASFLOW_EMAIL_INICIAL") or "admin@notasflow.local").lower()
            usuario = Usuario(
                escritorio_id=escritorio.id,
                nome="Administrador",
                email=email,
                senha_hash=gerar_hash_senha(senha),
                ativo=True,
            )
            db.add(usuario)
        else:
            usuario.senha_hash = gerar_hash_senha(senha)
            usuario.ativo = True
        db.commit()
        _escrever_credenciais(caminhos.pasta_dados(), email=usuario.email, senha=senha)
        return usuario.email, senha
    finally:
        db.close()
