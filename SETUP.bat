@echo off
chcp 65001 >nul
title NotasFlow - Setup
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - Configuracao inicial
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERRO] Python nao encontrado.
    echo Instale em: https://www.python.org/downloads/
    echo Marque a opcao "Add Python to PATH" na instalacao.
    pause
    exit /b 1
  )
  set PY=py
) else (
  set PY=python
)

echo Gerando chaves e arquivo de login...
%PY% scripts\gerar_env.py
if errorlevel 1 (
  echo [ERRO] Falha ao gerar .env
  pause
  exit /b 1
)

echo.
echo ============================================
echo   Setup concluido!
echo ============================================
echo   1. Abra CREDENCIAIS.txt e anote o login
echo   2. Instale o Docker Desktop (se ainda nao tiver)
echo   3. Rode INICIAR.bat
echo ============================================
echo.
if exist CREDENCIAIS.txt type CREDENCIAIS.txt
pause
