@echo off
chcp 65001 >nul
title Fluxa - Instalador Completo (Git + Python + Docker + Sistema)
cd /d "%~dp0"

echo.
echo ============================================================
echo   Fluxa - INSTALADOR COMPLETO
echo ============================================================
echo   Este instalador vai:
echo     1. Instalar o Git (se nao tiver)
echo     2. Instalar o Python 3 (se nao tiver)
echo     3. Instalar o Docker Desktop (se nao tiver)
echo     4. Preparar o WSL2 (se precisar)
echo     5. Gerar suas chaves de seguranca e login
echo     6. Subir o sistema e abrir o painel no navegador
echo.
echo   Pode rodar quantas vezes quiser - ele pula o que ja existe.
echo   Se pedir permissao de Administrador, clique SIM.
echo ============================================================
echo.
pause

powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\instalar_windows.ps1" %*

exit /b %ERRORLEVEL%
