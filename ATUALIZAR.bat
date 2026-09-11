@echo off
chcp 65001 >nul
title NotasFlow - Atualizar
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - Atualizando o sistema
echo ============================================
echo.
echo Seus dados NAO serao apagados (banco, certificados e XMLs
echo ficam em volumes Docker, separados do codigo).
echo.

REM ---------- 1. Baixar o codigo novo ----------
where git >nul 2>nul
if errorlevel 1 (
  echo [AVISO] Git nao encontrado - pulando atualizacao do codigo.
  goto SUBIR
)

echo Baixando a versao mais recente...
git pull --ff-only
if not errorlevel 1 goto SUBIR

echo.
echo [AVISO] Nao foi possivel atualizar o codigo automaticamente.
echo Isso costuma acontecer quando ha alteracoes locais nos arquivos.
echo O sistema vai subir com a versao que ja esta no PC.
echo.
echo Para ver o que esta travando:  git status
echo.

:SUBIR
where docker >nul 2>nul
if errorlevel 1 (
  echo [ERRO] Docker nao encontrado. Rode INSTALAR_TUDO.bat
  pause
  exit /b 1
)

docker info >nul 2>nul
if errorlevel 1 (
  echo [ERRO] O Docker Desktop esta desligado.
  echo Abra o Docker Desktop, espere ficar pronto e rode este arquivo de novo.
  pause
  exit /b 1
)

REM ---------- 2. Reconstruir e subir ----------
echo.
echo Reconstruindo e subindo containers...
set "LOG_UP=%TEMP%\notasflow_update.log"
if exist "%LOG_UP%" del "%LOG_UP%" >nul 2>nul

docker compose up --build -d 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_UP%'"

docker compose ps --status running --services 2>nul | findstr /i /c:"api" >nul 2>nul
if not errorlevel 1 goto OK

findstr /i /c:"read-only file system" "%LOG_UP%" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo [ERRO] Falha do Docker Desktop, nao do projeto.
  echo Feche e reabra o Docker Desktop, depois rode este arquivo de novo.
  echo Detalhes em SOLUCAO_DE_PROBLEMAS.md
  pause
  exit /b 1
)

echo.
echo [ERRO] Falha ao subir. Veja a mensagem acima.
echo Consulte SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:OK
echo.
echo ============================================
echo   Atualizado!
echo ============================================
echo   Painel:  http://localhost:3000
echo   API:     http://localhost:8000/docs
echo.
echo   Seu login continua o mesmo de antes.
echo   Nao consegue entrar? Rode RESETAR_SENHA.bat
echo ============================================
echo.
start http://localhost:3000
pause
