@echo off
chcp 65001 >nul
title Fluxa - Setup
cd /d "%~dp0"

echo ============================================
echo   Fluxa - Configuracao inicial
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [FALTA] Python nao encontrado neste PC.
    echo.
    choice /c SN /m "Quer instalar TUDO automaticamente agora (Python + Docker + o resto)"
    if errorlevel 2 (
      echo.
      echo Ok. Instale o Python manualmente e rode SETUP.bat de novo:
      echo   https://www.python.org/downloads/
      echo   (marque "Add Python to PATH" na instalacao^)
      pause
      exit /b 1
    )
    call INSTALAR_TUDO.bat
    exit /b 0
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
echo   2. Rode INICIAR.bat (instala o Docker se faltar)
echo ============================================
echo.
if exist CREDENCIAIS.txt type CREDENCIAIS.txt
pause
