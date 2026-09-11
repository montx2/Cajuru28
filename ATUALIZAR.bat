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
  goto PORTAS
)

echo Baixando a versao mais recente...
git pull --ff-only
if not errorlevel 1 goto PORTAS

echo.
echo [AVISO] Nao foi possivel atualizar o codigo automaticamente.
echo Isso costuma acontecer quando ha alteracoes locais nos arquivos.
echo O sistema vai subir com a versao que ja esta no PC.
echo.
echo Para ver o que esta travando:  git status
echo.

:PORTAS
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

REM ---------- 2. Reavaliar portas ----------
REM Mantem as portas gravadas no .env enquanto funcionarem; se algo novo
REM ocupar, escolhe outra automaticamente.
set "ARQ_PORTAS=%TEMP%\notasflow_portas.txt"
set PORTA_PAINEL=3000
set PORTA_API=8000
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\ajustar_portas.ps1" > "%ARQ_PORTAS%" 2>&1
if errorlevel 1 goto PORTA_FALHOU
type "%ARQ_PORTAS%"
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ARQ_PORTAS%") do (
  if "%%A"=="FRONTEND_PORT" set PORTA_PAINEL=%%B
  if "%%A"=="API_PORT" set PORTA_API=%%B
)
echo [OK] Portas: painel %PORTA_PAINEL% - API %PORTA_API%.

:RECONSTRUIR
REM ---------- 3. Reconstruir e subir ----------
echo.
echo Reconstruindo e subindo containers...
set "LOG_UP=%TEMP%\notasflow_update.log"
if exist "%LOG_UP%" del "%LOG_UP%" >nul 2>nul

REM UTF-8 sem BOM (o Tee-Object antigo gravava UTF-16 e o findstr nao achava nada).
docker compose up --build -d 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -Variable saida | ForEach-Object { Write-Host $_ }; if ($saida) { [IO.File]::WriteAllLines('%LOG_UP%', [string[]]$saida, (New-Object Text.UTF8Encoding($false))) }"

REM TODOS os servicos de pe? (antes so a API era verificada)
set FALTANDO_SERVICOS=0
for %%S in (api frontend worker beat db redis) do (
  docker compose ps --services --status running 2>nul | findstr /x /i "%%S" >nul 2>nul
  if errorlevel 1 set /a FALTANDO_SERVICOS+=1
)
if %FALTANDO_SERVICOS%==0 goto OK

findstr /i /c:"read-only file system" "%LOG_UP%" >nul 2>nul
if not errorlevel 1 goto ERRO_READONLY

findstr /i /c:"ports are not available" "%LOG_UP%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA
findstr /i /c:"port is already allocated" "%LOG_UP%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA

echo.
echo [ERRO] Falha ao subir. Ultimas mensagens:
powershell -NoProfile -Command "Get-Content '%LOG_UP%' -Tail 30"
echo Consulte SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:PORTA_FALHOU
REM Falha real (sem porta livre) x PowerShell quebrado.
findstr /c:"[ERRO]" "%ARQ_PORTAS%" >nul 2>nul
if not errorlevel 1 goto PORTA_SEM_PORTA
echo [AVISO] Nao foi possivel verificar portas; seguindo com as padroes.
goto RECONSTRUIR

:PORTA_SEM_PORTA
echo.
echo [ERRO] Nenhuma porta livre. Feche programas que usem as portas
echo 3000/8000/5432/6379 ou rode, como ADMINISTRADOR:
echo    net stop winnat
echo    net start winnat
echo Depois rode este arquivo de novo. Detalhes em SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:ERRO_PORTA
echo.
echo [ERRO] Conflito de porta no Windows (Hyper-V/WinNAT ou outro programa).
echo Como administrador:
echo    net stop winnat
echo    net start winnat
echo Depois rode este arquivo de novo. Detalhes em SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:ERRO_READONLY
echo.
echo [ERRO] Falha do Docker Desktop, nao do projeto.
echo Feche e reabra o Docker Desktop, depois rode este arquivo de novo.
echo Detalhes em SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:OK
echo.
echo ============================================
echo   Atualizado!
echo ============================================
echo   Painel:  http://localhost:%PORTA_PAINEL%
echo   API:     http://localhost:%PORTA_API%/docs
echo.
echo   Seu login continua o mesmo de antes.
echo   Nao consegue entrar? Rode RESETAR_SENHA.bat
echo ============================================
echo.
start http://localhost:%PORTA_PAINEL%
pause
