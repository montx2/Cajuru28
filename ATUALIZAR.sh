#!/usr/bin/env bash
# NotasFlow — Atualiza o código (git pull) e reconstrói os containers.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "============================================"
echo "  NotasFlow - Atualizando o sistema"
echo "============================================"

if command -v git >/dev/null 2>&1; then
  echo "Baixando a versão mais recente..."
  git pull --ff-only || echo "[AVISO] Não foi possível atualizar o código. Continuando."
else
  echo "[AVISO] Git não encontrado — pulando atualização do código."
fi

DC="docker compose"
if ! docker info >/dev/null 2>&1; then
  if command -v sudo >/dev/null 2>&1 && sudo docker info >/dev/null 2>&1; then
    DC="sudo docker compose"
  else
    echo "[ERRO] Docker não está rodando. Rode ./INSTALAR_TUDO.sh"
    exit 1
  fi
fi

echo ""
echo "Reconstruindo e subindo containers..."
$DC up --build -d

echo ""
echo "Pronto! Painel: http://localhost:3000"
