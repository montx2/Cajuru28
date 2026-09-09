@echo off
chcp 65001 >nul
title NotasFlow - Atualizar
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - Atualizando o sistema
echo ============================================
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Git nao encontrado - pulando atualizacao do codigo.
) else (
  echo Baixando a versao mais recente...
  git pull --ff-only
  if errorlevel 1 (
    echo [AVISO] Nao foi possivel atualizar o codigo. Continuando com a versao local.
  )
)

where docker >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Docker nao encontrado. Rode INSTALAR_TUDO.bat
  pause
  exit /b 1
)

echo.
echo Reconstruindo e subindo containers...
docker compose up --build -d
if errorlevel 1 (
  echo [ERRO] Falha ao subir. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
echo Pronto! Painel: http://localhost:3000
start http://localhost:3000
pause
