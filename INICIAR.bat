@echo off
chcp 65001 >nul
title NotasFlow
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - subindo o sistema
echo ============================================
echo.

where docker >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Docker nao encontrado.
  echo Instale o Docker Desktop e reinicie o PC:
  echo   https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)

if not exist "backend\.env" (
  echo backend\.env nao encontrado. Rodando setup automatico...
  call SETUP.bat
  if not exist "backend\.env" (
    echo [ERRO] Falha no setup. Rode SETUP.bat manualmente.
    pause
    exit /b 1
  )
)

if not exist "frontend\.env.local" (
  copy /Y "frontend\.env.example" "frontend\.env.local" >nul
)

echo Subindo containers (primeira vez demora)...
docker compose up --build -d
if errorlevel 1 (
  echo [ERRO] Falha ao subir. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
echo Aguardando a API...
timeout /t 8 /nobreak >nul

echo.
echo ============================================
echo   Pronto!
echo ============================================
echo   Painel:  http://localhost:3000
echo   API:     http://localhost:8000/docs
echo.
echo   Login (veja tambem CREDENCIAIS.txt):
echo   Email: admin@notasflow.local
echo   Senha: (arquivo CREDENCIAIS.txt)
echo ============================================
echo.
start http://localhost:3000
pause
