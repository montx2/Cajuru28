@echo off
chcp 65001 >nul
title NotasFlow - Diagnostico de login
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - nao consigo entrar
echo ============================================
echo.

docker compose ps --status running --services 2>nul | findstr /i /c:"api" >nul 2>nul
if errorlevel 1 (
  echo [ERRO] O container da API nao esta rodando.
  echo Rode INICIAR.bat primeiro e espere terminar.
  pause
  exit /b 1
)

echo Analisando o banco de dados...
echo.
docker compose exec -T api python scripts/diagnosticar_login.py
echo.
echo ============================================
choice /c SN /m "Quer redefinir a senha de um usuario agora"
if errorlevel 2 goto FIM

echo.
set /p EMAIL="Email do usuario (ex: admin@notasflow.local): "
set /p NOVASENHA="Senha nova: "

if "%EMAIL%"=="" goto FALTOU
if "%NOVASENHA%"=="" goto FALTOU

docker compose exec -T api python scripts/diagnosticar_login.py --redefinir "%EMAIL%" --senha "%NOVASENHA%"
if errorlevel 1 (
  echo.
  echo [ERRO] Nao foi possivel redefinir. Confira o email na lista acima.
  pause
  exit /b 1
)

echo.

REM Descobre a porta real do painel (pode ter sido trocada pelo INICIAR.bat
REM quando a 3000 estava ocupada/reservada no Windows).
set PORTA_PAINEL=3000
if exist ".env" (
  for /f "eol=# tokens=1,* delims==" %%A in (.env) do (
    if /i "%%A"=="FRONTEND_PORT" set PORTA_PAINEL=%%B
  )
)

echo Pronto. Entre em http://localhost:%PORTA_PAINEL% com a senha nova.
goto FIM

:FALTOU
echo.
echo [ERRO] Email e senha sao obrigatorios.

:FIM
echo.
pause
