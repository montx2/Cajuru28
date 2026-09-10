@echo off
REM NotasFlow Desktop - Rodar local sem gerar .exe (modo desenvolvimento desktop)

echo ============================================
echo  NotasFlow Desktop - Modo Desenvolvimento
echo ============================================
echo.

REM Verificar Python
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [ERRO] Python nao encontrado
    pause
    exit /b 1
)

REM Criar venv se nao existir
if not exist backend\venv_desktop (
    echo Criando venv desktop...
    cd backend
    python -m venv venv_desktop
    cd ..
)

echo Ativando venv e instalando deps...
call backend\venv_desktop\Scripts\activate.bat
pip install -q -r backend\requirements.txt

REM Configurar env desktop
set DATABASE_URL=sqlite:///%CD%/data_desktop/notasflow.db
set DADOS_DIR=%CD%/data_desktop
set MODO_DESKTOP=true
set DESKTOP_MODE=true
set CORS_ORIGINS=*
set PORT=8000

REM Gerar .env se nao existir
if not exist data_desktop mkdir data_desktop
if not exist data_desktop\certificados mkdir data_desktop\certificados
if not exist data_desktop\xml mkdir data_desktop\xml

echo.
echo Banco: %DATABASE_URL%
echo Dados: %DADOS_DIR%
echo.

REM Rodar backend desktop
echo Iniciando backend desktop em http://localhost:8000
echo Docs: http://localhost:8000/docs
echo Saude: http://localhost:8000/saude
echo.
echo Para frontend, em outro terminal:
echo   cd frontend ^&^& npm install ^&^& npm run dev
echo.

cd backend
python -m app.desktop_main

pause
