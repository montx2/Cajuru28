#!/usr/bin/env bash
# Ambiente de auditoria em um comando.
#
# Ferramenta de desenvolvimento: cria a pasta de dados FORA do repositório,
# escreve o env.sh com as chaves de teste, semeia o banco e imprime o que
# subir. O sandbox desta auditoria já foi recriado duas vezes do zero e sem
# isto o ambiente (banco + variáveis) tinha de ser remontado à mão a cada vez.
#
# Uso:
#   bash backend/scripts/dev/ambiente_dev.sh          # cria e semeia se faltar
#   bash backend/scripts/dev/ambiente_dev.sh --reseed # apaga o banco e semeia
#
# Depois:
#   source ~/_fluxa_dev/env.sh
#   (cd backend  && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000)
#   (cd frontend && PREVIEW_PROXY=1 npx next dev -H 0.0.0.0)   # preview local

set -euo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DEV="${FLUXA_DEV_DIR:-$HOME/_fluxa_dev}"
ENV_FILE="$DEV/env.sh"
BANCO="$DEV/fluxa.db"

mkdir -p "$DEV/data" "$DEV/backups"

cat > "$ENV_FILE" <<'ENV'
# Ambiente de desenvolvimento da auditoria (fora do repositório de propósito).
export NOTASFLOW_ENV_FILE=/dev/null
export APP_ENV=development
export DATABASE_URL="sqlite:////PWD/fluxa.db"
export SECRET_KEY="dev-secret-key-com-mais-de-32-caracteres-ok"
export VAULT_MASTER_KEY="IGWdDJCadNIHrKZvW-ES-iSfpcsnWc-29RS4aJgEe6o="
export BACKUP_ENCRYPTION_KEY="5IBolsp8dIKz_cSVzZsaY--u_mAwuJXLFti2iyeKa7w="
export RATE_LIMIT_ATIVO=false
export SINCRONISMO_AUTOMATICO=false
export BACKUP_ATIVO=false
export BOOTSTRAP_EMAIL=admin@escritorio.com
export BOOTSTRAP_SENHA='SenhaForte#2026ab'
export BOOTSTRAP_ESCRITORIO='Escritório Contábil Cajuru'
export TRUSTED_HOSTS="localhost,127.0.0.1,testserver,*.e2b.app"
ENV
sed -i "s#/PWD#${DEV}#g" "$ENV_FILE"
# DADOS_DIR/BACKUP_DIR só existem neste ambiente: ficam fora do heredoc acima
# porque dependem do caminho resolvido.
{
  echo "export DADOS_DIR=$DEV/data"
  echo "export BACKUP_DIR=$DEV/backups"
} >> "$ENV_FILE"

if [[ "${1:-}" == "--reseed" ]]; then
  rm -f "$BANCO" "$BANCO-wal" "$BANCO-shm"
fi

if [[ -s "$BANCO" ]]; then
  echo "Banco já existe em $BANCO (use --reseed para recriar)."
else
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  (cd "$RAIZ/backend" && .venv/bin/python scripts/dev/semear_auditoria.py)
fi

echo
echo "Ambiente pronto. Agora:"
echo "  source $ENV_FILE"
echo "  cd $RAIZ/backend  && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000"
echo "  cd $RAIZ/frontend && PREVIEW_PROXY=1 npx next dev -H 0.0.0.0"
echo "  login: admin@escritorio.com / SenhaForte#2026ab"
