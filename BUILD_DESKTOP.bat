@echo off
REM NotasFlow Desktop - Build do .exe no Windows
REM Gera instalador bonito que roda local, sem Docker

echo ============================================
echo  NotasFlow Desktop - Gerando .exe
echo ============================================
echo.

REM Verificar Node.js
where node >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Node.js nao encontrado!
    echo Instale Node.js 20+ em https://nodejs.org
    pause
    exit /b 1
)

REM Verificar Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado!
    echo Instale Python 3.11+ em https://python.org
    pause
    exit /b 1
)

echo [1/5] Verificando dependencias...

REM Backend deps
cd backend
echo   - Backend Python...
pip install -q -r requirements.txt
pip install -q pyinstaller
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao instalar dependencias Python
    pause
    exit /b 1
)

echo [2/5] Compilando backend para .exe...
REM Limpar build anterior
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM PyInstaller - modo onedir (mais rapido) para dev, onefile para release
pyinstaller --noconfirm --clean --log-level=WARN --name notasflow-backend --onedir --console --hidden-import=app.main --hidden-import=app.desktop_main --hidden-import=app.models --hidden-import=app.schemas --hidden-import=app.db.base --hidden-import=app.db.session --hidden-import=app.db.migracoes --hidden-import=app.api.routers.auth --hidden-import=app.api.routers.empresas --hidden-import=app.api.routers.certificados --hidden-import=app.api.routers.documentos --hidden-import=app.api.routers.importacoes --hidden-import=app.core.config --hidden-import=app.core.security --hidden-import=app.core.vault --hidden-import=app.services.fila --hidden-import=app.services.sincronizacao --hidden-import=app.services.certificados --hidden-import=app.services.mtls --hidden-import=app.services.periodo --hidden-import=app.services.importadores.base --hidden-import=app.services.importadores.nfse_adn --hidden-import=app.services.importadores.nfe_sefaz --hidden-import=app.services.importadores.cte_sefaz --hidden-import=app.services.importadores.eventos --hidden-import=app.services.importadores._distribuicao_dfe --hidden-import=app.worker.executor --hidden-import=app.bootstrap --hidden-import=uvicorn --hidden-import=uvicorn.logging --hidden-import=uvicorn.loops --hidden-import=uvicorn.loops.auto --hidden-import=uvicorn.protocols --hidden-import=uvicorn.protocols.http --hidden-import=uvicorn.protocols.http.auto --hidden-import=uvicorn.protocols.websockets --hidden-import=uvicorn.protocols.websockets.auto --hidden-import=uvicorn.lifespan --hidden-import=uvicorn.lifespan.on --hidden-import=sqlalchemy --hidden-import=sqlalchemy.dialects.sqlite --hidden-import=cryptography --hidden-import=jose --hidden-import=passlib --hidden-import=bcrypt --hidden-import=httpx --hidden-import=lxml --hidden-import=dateutil --hidden-import=OpenSSL app/desktop_main.py

if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao compilar backend
    pause
    exit /b 1
)

echo   Backend compilado em backend/dist/notasflow-backend/

cd ..

echo [3/5] Instalando frontend...
cd frontend
call npm install --silent
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao instalar frontend
    pause
    exit /b 1
)

echo [4/5] Compilando frontend standalone...
set NEXT_PUBLIC_API_URL=http://localhost:8000
call node scripts/build-desktop.js
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Build desktop falhou
    pause
    exit /b 1
)

cd ..

echo [5/5] Gerando instalador Electron...
cd desktop
call npm install --silent
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao instalar desktop deps
    pause
    exit /b 1
)

call npx electron-builder --win --x64
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Falha ao gerar instalador
    pause
    exit /b 1
)

echo.
echo ============================================
echo  SUCESSO! .exe gerado em desktop/dist/
echo ============================================
echo.
dir dist\*.exe
echo.
echo Para distribuir, envie o .exe da pasta desktop/dist/
echo Para atualizar todos automaticamente, crie uma Release no GitHub
echo.
pause
