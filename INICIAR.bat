@echo off
chcp 65001 >nul
title NotasFlow
cd /d "%~dp0"

echo ============================================
echo   NotasFlow - subindo o sistema
echo ============================================
echo.

REM ---------- 1. Docker esta instalado? ----------
where docker >nul 2>nul
if not errorlevel 1 goto DOCKER_OK

echo [FALTA] Docker nao esta instalado neste PC.
echo.
choice /c SN /m "Quer instalar TUDO automaticamente agora (Docker + o resto)"
if errorlevel 2 (
  echo.
  echo Ok. Baixe o Docker manualmente e rode INICIAR.bat de novo:
  echo   https://www.docker.com/products/docker-desktop/
  pause
  exit /b 1
)
call INSTALAR_TUDO.bat

REM O instalador pede permissao de administrador e abre janela propria.
where docker >nul 2>nul
if errorlevel 1 (
  echo.
  echo O instalador abriu em outra janela com a instalacao.
  echo Quando ele terminar, feche esta janela e abra INICIAR.bat de novo.
  pause
  exit /b 1
)

:DOCKER_OK
REM ---------- 2. Motor do Docker esta ligado? ----------
docker info >nul 2>nul
if not errorlevel 1 goto MOTOR_OK

if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  echo Docker Desktop esta desligado. Ligando e aguardando...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
) else (
  echo [ERRO] Docker instalado mas o Docker Desktop nao foi encontrado.
  echo Abra o Docker Desktop manualmente e rode INICIAR.bat de novo.
  pause
  exit /b 1
)

set TENTATIVAS=0
:AGUARDAR_MOTOR
set /a TENTATIVAS+=1
if %TENTATIVAS% GEQ 60 (
  echo [ERRO] O Docker demorou demais para ligar ^(5 min^).
  echo Abra o Docker Desktop, espere a baleia ficar verde e rode de novo.
  pause
  exit /b 1
)
timeout /t 5 /nobreak >nul
docker info >nul 2>nul
if errorlevel 1 goto AGUARDAR_MOTOR
echo [OK] Docker ligado.

:MOTOR_OK
REM ---------- 3. Configuracao (.env) ----------
if not exist "backend\.env" (
  echo backend\.env nao encontrado. Rodando setup automatico...
  call SETUP.bat
  if not exist "backend\.env" (
    echo [ERRO] Falha no setup. Rode INSTALAR_TUDO.bat
    pause
    exit /b 1
  )
)

if not exist "frontend\.env.local" (
  copy /Y "frontend\.env.example" "frontend\.env.local" >nul
)

REM ---------- 4. Subir ----------
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
