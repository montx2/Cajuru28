#!/bin/bash
# NotasFlow Desktop - Build no Linux/Mac

set -e

echo "============================================"
echo " NotasFlow Desktop - Gerando binário"
echo "============================================"
echo ""

# Verificar deps
command -v node >/dev/null 2>&1 || { echo "[ERRO] Node.js não encontrado"; exit 1; }
command -v python3 >/dev/null 2>&1 || { echo "[ERRO] Python não encontrado"; exit 1; }

echo "[1/5] Dependências..."
cd backend
pip3 install -q -r requirements.txt pyinstaller

echo "[2/5] Backend..."
rm -rf dist build
pyinstaller --noconfirm --clean --log-level=WARN --name notasflow-backend --onedir --console \
  --hidden-import=app.main --hidden-import=app.desktop_main --hidden-import=app.models \
  --hidden-import=app.schemas --hidden-import=app.db.base --hidden-import=app.db.session \
  --hidden-import=app.db.migracoes --hidden-import=app.api.routers.auth \
  --hidden-import=app.api.routers.empresas --hidden-import=app.api.routers.certificados \
  --hidden-import=app.api.routers.documentos --hidden-import=app.api.routers.importacoes \
  --hidden-import=app.core.config --hidden-import=app.core.security --hidden-import=app.core.vault \
  --hidden-import=app.services.fila --hidden-import=app.services.sincronizacao \
  --hidden-import=app.services.certificados --hidden-import=app.services.mtls \
  --hidden-import=app.services.periodo --hidden-import=app.services.importadores.base \
  --hidden-import=app.services.importadores.nfse_adn --hidden-import=app.services.importadores.nfe_sefaz \
  --hidden-import=app.services.importadores.cte_sefaz --hidden-import=app.services.importadores.eventos \
  --hidden-import=app.services.importadores._distribuicao_dfe --hidden-import=app.worker.executor \
  --hidden-import=app.bootstrap --hidden-import=uvicorn --hidden-import=sqlalchemy \
  --hidden-import=sqlalchemy.dialects.sqlite --hidden-import=cryptography --hidden-import=jose \
  --hidden-import=passlib --hidden-import=bcrypt --hidden-import=httpx --hidden-import=lxml \
  --hidden-import=dateutil --hidden-import=OpenSSL app/desktop_main.py

cd ..

echo "[3/5] Frontend..."
cd frontend
npm install --silent
NEXT_PUBLIC_API_URL=http://localhost:8000 node scripts/build-desktop.js
cd ..

echo "[4/5] Desktop..."
cd desktop
npm install --silent

echo "[5/5] Electron..."
npx electron-builder --linux --x64 || npx electron-builder --dir

echo ""
echo "============================================"
echo " SUCESSO! Binário em desktop/dist/"
echo "============================================"
ls -lh dist/ | tail -20
