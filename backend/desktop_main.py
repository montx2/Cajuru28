"""
NotasFlow — ponto de entrada do programa instalado.

É este arquivo que vira o `.exe`. Ele faz o mínimo antes de entregar o controle
para `app.desktop.servidor`:

- **descobre onde ficam os dados do usuário** e avisa a configuração por
  variável de ambiente. Isso precisa acontecer *antes* de importar
  `app.core.config`, porque o `.env` do modo desktop mora nessa pasta (e no
  Windows o "diretório atual" de um atalho é imprevisível);
- trata os argumentos de linha de comando que existem para dar suporte sem
  interface: diagnosticar, ver a versão, redefinir a senha do administrador;
- garante `MODO_DESKTOP=true` — este binário é o modo desktop por definição.

Uso:

    NotasFlow.exe                      abre normalmente
    NotasFlow.exe --minimizado         sobe só no relógio (início automático)
    NotasFlow.exe --console            só a API, com log na tela (suporte)
    NotasFlow.exe --diagnostico        imprime o estado do ambiente e sai
    NotasFlow.exe --redefinir-senha    nova senha do administrador
    NotasFlow.exe --versao             versão instalada

Nada aqui decide regra fiscal — isso é do resto do sistema, que é o mesmo nos
dois modos (servidor e programa instalado).
"""

from __future__ import annotations

import json
import os
import sys

NOME_EXECUTAVEL = "NotasFlow"


def _preparar_ambiente() -> None:
    """
    Aponta o `.env` para a pasta de dados e fixa o modo desktop.

    `os.environ` tem prioridade sobre o `.env` no pydantic-settings — é o que
    permite ao programa instalado usar a pasta de dados do usuário sem
    reescrever configuração nenhuma.
    """
    from app.desktop import caminhos

    os.environ.setdefault("NOTASFLOW_ENV_FILE", str(caminhos.arquivo_env()))
    os.environ.setdefault("MODO_DESKTOP", "true")

    # Primeira abertura: cria a pasta de dados, o `.env` (banco SQLite local,
    # chaves de segurança, chaves do cofre) e o `CREDENCIAIS.txt`.
    #
    # Isso acontece AQUI, antes de qualquer import de `app.core.config` — é o
    # único instante em que dá para fazer isso, porque o `.env` é lido no import.
    # Sem esta chamada, um programa recém-instalado tentaria abrir o banco do
    # servidor (que não existe nesse computador) na primeira abertura.
    from app.desktop.ambiente import preparar_primeira_execucao

    preparar_primeira_execucao(silencioso=True)
    # Em `--noconsole`, `sys.stdout`/`stderr` são None. Bibliotecas que testam
    # `sys.stdout.isatty()` na importação estouram por causa disso.
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")


def _imprimir(mensagem: str) -> None:
    try:
        print(mensagem)
    except Exception:  # noqa: BLE001 — sem console não há onde imprimir
        pass


def _diagnostico() -> int:
    # Cria o `.env` se for a primeira execução: o diagnóstico de uma instalação
    # nova precisa mostrar a configuração que ela *vai* usar, não a ausência
    # dela.
    from app.desktop.ambiente import preparar_primeira_execucao

    primeira = preparar_primeira_execucao(silencioso=True)

    from app.core.config import settings
    from app.desktop import caminhos

    dados = caminhos.descricao_ambiente()
    banco = settings.database_url
    if "@" in banco:  # esconde usuário/senha do PostgreSQL no relatório
        banco = banco.split("@", 1)[-1]
    relatorio = {
        **dados,
        "configurado_agora": primeira.get("criado_agora", False),
        "modo_desktop": settings.modo_desktop,
        "banco": banco,
        "dados_dir": settings.dados_dir,
        "arquivo_env": str(caminhos.arquivo_env()),
        "env_existe": caminhos.arquivo_env().is_file(),
        "porta": settings.notasflow_porta,
        "permitir_rede": settings.notasflow_permitir_rede,
        "sincronismo_automatico": settings.sincronismo_automatico,
        "ambiente_fiscal": settings.ambiente_fiscal,
        "manifesto_atualizacao": settings.notasflow_update_manifest or settings.notasflow_repo,
    }
    _imprimir(json.dumps(relatorio, indent=2, ensure_ascii=False))

    # O diagnóstico só é útil se também disser se o banco abre.
    try:
        from app.db.base import criar_tabelas
        from app.db.session import engine
        from sqlalchemy import text

        criar_tabelas()
        with engine.connect() as conexao:
            conexao.execute(text("SELECT 1"))
        _imprimir("Banco: OK")
        return 0
    except Exception as exc:  # noqa: BLE001
        _imprimir(f"Banco: FALHOU — {exc}")
        return 2


def _redefinir_senha() -> int:
    from app.db.base import criar_tabelas
    from app.desktop.ambiente import redefinir_senha_administrador

    criar_tabelas()
    email, senha = redefinir_senha_administrador()
    _imprimir("=" * 56)
    _imprimir("  Nova senha do administrador do NotasFlow")
    _imprimir("=" * 56)
    _imprimir(f"  E-mail: {email}")
    _imprimir(f"  Senha:  {senha}")
    _imprimir("=" * 56)
    _imprimir("  Anotada também em CREDENCIAIS.txt, na pasta de dados.")
    return 0


def main(argv: list[str] | None = None) -> int:
    argumentos = list(sys.argv[1:] if argv is None else argv)
    _preparar_ambiente()

    if "--versao" in argumentos or "-v" in argumentos:
        from app.desktop.caminhos import versao_do_pacote

        _imprimir(f"{NOME_EXECUTAVEL} {versao_do_pacote()}")
        return 0

    if "--diagnostico" in argumentos:
        return _diagnostico()

    if "--redefinir-senha" in argumentos:
        return _redefinir_senha()

    modo = "normal"
    if "--minimizado" in argumentos or "--bandeja" in argumentos:
        modo = "bandeja"
    if "--console" in argumentos:
        modo = "console"

    abrir_janela = None
    if "--sem-janela" in argumentos:
        abrir_janela = False

    from app.desktop.servidor import executar

    return executar(abrir_janela=abrir_janela, modo=modo)


if __name__ == "__main__":
    sys.exit(main())
