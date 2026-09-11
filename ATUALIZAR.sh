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

# Reavalia as portas: se a que estava no .env continuar boa, mantém (o
# endereço do painel não muda); se algo novo ocupar, escolhe outra.
if command -v python3 >/dev/null 2>&1; then
  SAIDA_PORTAS="$(python3 scripts/ajustar_portas.py)" || true
  [[ -n "${SAIDA_PORTAS:-}" ]] && printf '%s\n' "$SAIDA_PORTAS" | grep '^#' | sed 's/^#//' || true
fi

echo ""
echo "Reconstruindo e subindo containers..."
$DC up --build -d

# Confere que todos os serviços ficaram de pé.
FALTANDO=""
for s in api frontend worker beat db redis; do
  if ! $DC ps --services --status running 2>/dev/null | grep -qx "$s"; then
    FALTANDO="$FALTANDO $s"
  fi
done
if [[ -n "$FALTANDO" ]]; then
  echo "[ERRO] Estes serviços não subiram:$FALTANDO"
  $DC logs --tail 40 $FALTANDO || true
  exit 1
fi

# Descobre as portas reais (do .env da raiz; padrão 3000/8000).
FRONTEND_PORT="$(sed -n 's/^FRONTEND_PORT=//p' .env 2>/dev/null | head -1 || true)"
API_PORT="$(sed -n 's/^API_PORT=//p' .env 2>/dev/null | head -1 || true)"
[[ -z "${FRONTEND_PORT:-}" ]] && FRONTEND_PORT=3000
[[ -z "${API_PORT:-}" ]] && API_PORT=8000

echo ""
echo "Pronto! Painel: http://localhost:${FRONTEND_PORT}"
echo "        API:    http://localhost:${API_PORT}/docs"
