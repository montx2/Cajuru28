#!/usr/bin/env python3
"""
Escolhe portas livres para o NotasFlow e grava as escolhas no `.env` da raiz.

Por que este arquivo existe
---------------------------
No Windows, o Hyper-V/WinNAT reserva faixas dinâmicas de portas TCP a cada
boot (veja com `netsh interface ipv4 show excludedportrange protocol=tcp`).
Quando a porta 3000 cai numa faixa reservada, o Docker Desktop falha com:

    Error response from daemon: ports are not available: exposing port TCP
    0.0.0.0:3000 ... bind: An attempt was made to access a socket in a way
    forbidden by its access permissions.

O mesmo acontece quando outro programa já está usando a porta. Em vez de
falhar, este script:

1. testa se cada porta padrão pode ser ocupada (bind real, não só consulta);
2. mantém a porta se estiver livre OU se quem a ocupa for um contêiner
   deste próprio projeto (subir de novo com o sistema já no ar);
3. caso contrário, escolhe a primeira porta livre de uma lista de reservas
   e grava no `.env` da raiz (que o docker-compose lê automaticamente);
4. se a porta da API mudar, ajusta também `NEXT_PUBLIC_API_URL` — ela é
   "assada" no build do frontend e precisa bater com a porta real.

A escolha é "grudenta": uma vez gravada no `.env`, vale até o dia em que
deixar de funcionar. Assim o endereço do painel não muda toda hora.

Saída
-----
- Linhas `CHAVE=VALOR` — para os scripts de inicialização lerem.
- Linhas começando com `#` — mensagens para humanos (ignoradas pelos scripts).

Uso:
    python3 scripts/ajustar_portas.py        # ajusta e grava o .env
    python3 scripts/ajustar_portas.py --ver  # só mostra o que faria
"""

from __future__ import annotations

import argparse
import socket
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVO_ENV = RAIZ / ".env"

# Definições por serviço: chave no .env, contêiner correspondente e a lista
# de portas candidatas (a primeira é o padrão do projeto).
DEFINICOES = [
    {
        "chave": "FRONTEND_PORT",
        "servico": "frontend",
        "candidatas": [3000, 3001, 3002, 3003, 3004, 3005, 3100, 8080, 8081, 8082, 9090],
    },
    {
        "chave": "API_PORT",
        "servico": "api",
        "candidatas": [8000, 8001, 8002, 8003, 8004, 8005, 9000, 9001, 8443],
    },
    {
        "chave": "DB_PORT",
        "servico": "db",
        "candidatas": [5432, 5433, 5434, 5435, 5436, 55432],
    },
    {
        "chave": "REDIS_PORT",
        "servico": "redis",
        "candidatas": [6379, 6380, 6381, 6382, 6383, 16379],
    },
]

API_PORTA_PADRAO = 8000


def porta_livre(porta: int) -> bool:
    """Tenta ocupar a porta de verdade — é o mesmo teste que o Docker fará.

    Consultar netstat não basta: porta reservada pelo WinNAT/Hyper-V aparece
    como livre no netstat, mas falha no bind com "access permissions".
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("0.0.0.0", porta))
            return True
    except OSError:
        return False


def servicos_do_projeto_rodando() -> set[str]:
    """Serviços DESTE projeto docker-compose que estão rodando agora.

    Se a porta está ocupada pelo nosso próprio contêiner, não é conflito:
    o `docker compose up` vai reutilizar em vez de brigar pela porta.
    Qualquer falha (Docker desligado, comando ausente) devolve vazio.
    """
    try:
        resultado = subprocess.run(
            ["docker", "compose", "ps", "--services", "--status", "running"],
            cwd=RAIZ,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if resultado.returncode != 0:
            return set()
        return {ln.strip() for ln in resultado.stdout.splitlines() if ln.strip()}
    except Exception:
        return set()


def ler_env() -> dict[str, str]:
    if not ARQUIVO_ENV.exists():
        return {}
    valores: dict[str, str] = {}
    for linha in ARQUIVO_ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valores[chave.strip()] = valor.strip()
    return valores


def gravar_env(atual: dict[str, str], mudancas: dict[str, str]) -> None:
    """Regrava o .env preservando comentários e variáveis não relacionados."""
    linhas: list[str] = (
        ARQUIVO_ENV.read_text(encoding="utf-8", errors="replace").splitlines()
        if ARQUIVO_ENV.exists()
        else []
    )
    cabecalho = (
        "# Portas do NotasFlow — escolhidas automaticamente pelo INICIAR/INSTALAR."
        if not any(l.strip() == "# Portas do NotasFlow — escolhidas automaticamente pelo INICIAR/INSTALAR." for l in linhas)
        else None
    )

    restantes = dict(mudancas)
    novas: list[str] = []
    for linha in linhas:
        linha_limpa = linha.strip()
        if linha_limpa and not linha_limpa.startswith("#") and "=" in linha_limpa:
            chave = linha_limpa.split("=", 1)[0].strip()
            if chave in restantes:
                novas.append(f"{chave}={restantes.pop(chave)}")
                continue
        novas.append(linha)

    if cabecalho:
        novas.insert(0, cabecalho)
    for chave, valor in restantes.items():
        novas.append(f"{chave}={valor}")

    ARQUIVO_ENV.write_text("\n".join(novas) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Escolhe portas livres para o NotasFlow")
    parser.add_argument("--ver", action="store_true", help="apenas mostra; não grava nada")
    args = parser.parse_args()

    env_atual = ler_env()
    rodando = servicos_do_projeto_rodando()
    escolhidas: set[int] = set()
    mudancas: dict[str, str] = {}
    final: dict[str, str] = {}
    mudou = False

    for definicao in DEFINICOES:
        chave = definicao["chave"]
        candidatas = definicao["candidatas"]
        padrao = candidatas[0]

        atual_bruto = env_atual.get(chave, "").strip()
        try:
            atual = int(atual_bruto) if atual_bruto else padrao
        except ValueError:
            print(f"# [AVISO] {chave}={atual_bruto!r} não é um número; usando {padrao}.")
            atual = padrao

        # 1) A porta atual está disponível para este projeto?
        if atual not in escolhidas and porta_livre(atual):
            escolhida = atual
        # 2) Ocupada, mas por contêiner nosso deste projeto: mantém.
        elif atual not in escolhidas and definicao["servico"] in rodando:
            escolhida = atual
        # 3) Conflito de verdade: procura a primeira candidata livre.
        else:
            escolhida = None
            for candidata in candidatas:
                if candidata in escolhidas:
                    continue
                if porta_livre(candidata):
                    escolhida = candidata
                    break
            if escolhida is None:
                print(f"# [ERRO] Nenhuma porta livre encontrada para {definicao['servico']}.")
                print(f"#         Testadas: {', '.join(str(c) for c in candidatas)}.")
                print("#         Feche o programa que ocupa a porta ou escolha outra")
                print("#         manualmente no arquivo .env da raiz do projeto.")
                return 1
            mudou = True
            print(
                f"# Porta {atual} indisponível para {definicao['servico']} "
                f"(em uso ou reservada pelo Windows). Usando {escolhida}."
            )

        escolhidas.add(escolhida)
        final[chave] = str(escolhida)
        if env_atual.get(chave, "").strip() != str(escolhida):
            mudancas[chave] = str(escolhida)

    # A URL da API é embutida no build do frontend — precisa acompanhar a porta.
    if final["API_PORT"] != str(API_PORTA_PADRAO):
        url_api = f"http://localhost:{final['API_PORT']}"
        if env_atual.get("NEXT_PUBLIC_API_URL", "") != url_api:
            mudancas["NEXT_PUBLIC_API_URL"] = url_api
            mudou = True
            print(f"# API fora da porta padrão: frontend vai usar {url_api}")
            print("# (o frontend será reconstruído automaticamente)")

    if mudou and not args.ver:
        gravar_env(env_atual, mudancas)
        if mudancas:
            print(
                "# Gravado no .env da raiz: "
                + ", ".join(f"{c}={v}" for c, v in mudancas.items())
            )
            print("# Para voltar ao padrão, apague essas linhas do arquivo .env.")
    elif mudou and args.ver:
        print("# (--ver: nada foi gravado)")

    # Saída para os scripts: sempre as 4 portas finais.
    for definicao in DEFINICOES:
        print(f"{definicao['chave']}={final[definicao['chave']]}")
    print(f"MUDOU={'1' if mudou else '0'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
