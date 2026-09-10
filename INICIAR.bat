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
set "LOG_SUBIDA=%TEMP%\notasflow_up.log"
if exist "%LOG_SUBIDA%" del "%LOG_SUBIDA%" >nul 2>nul

REM Mostra a saida na tela e grava em log ao mesmo tempo (para diagnostico).
docker compose up --build -d 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG_SUBIDA%'"

REM Deu certo se a API estiver de pe.
docker compose ps --status running --services 2>nul | findstr /i /c:"api" >nul 2>nul
if not errorlevel 1 goto SUBIDA_OK

REM ---------- 4b. Diagnostico de erros conhecidos ----------
findstr /i /c:"read-only file system" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo ============================================
  echo   PROBLEMA NO DOCKER DESKTOP ^(nao e o projeto^)
  echo ============================================
  echo O Docker gravou "read-only file system" ao acessar o proprio
  echo banco interno ^(meta.db^). Isso acontece quando a maquina virtual
  echo do Docker Desktop travou, ficou sem espaco em disco ou o disco
  echo dela corrompeu. O codigo do NotasFlow nao tem relacao com isso.
  echo.
  echo COMO RESOLVER, na ordem:
  echo   1^) Feche o Docker Desktop pela bandeja ^(Quit Docker Desktop^)
  echo      e abra de novo. Depois rode INICIAR.bat outra vez.
  echo   2^) Se persistir: Docker Desktop ^> Troubleshoot ^> Restart.
  echo   3^) Libere espaco em disco ^(deixe ao menos 10 GB livres^) e rode:
  echo        docker system prune -a
  echo   4^) Reinicie o Windows.
  echo   5^) Ultimo recurso: Docker Desktop ^> Troubleshoot ^>
  echo      "Clean / Purge data" ou reinstale o Docker Desktop.
  echo      Isso apaga as imagens; os dados do NotasFlow ficam nos
  echo      volumes db_data/certificados/xml_saida - faca backup antes.
  echo.
  echo Detalhes em SOLUCAO_DE_PROBLEMAS.md
  echo ============================================
  pause
  exit /b 1
)

findstr /i /c:"no space left on device" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo [ERRO] Sem espaco em disco para o Docker.
  echo Libere espaco e rode:  docker system prune -a
  echo Depois execute INICIAR.bat de novo.
  pause
  exit /b 1
)

findstr /i /c:"port is already allocated" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 (
  echo.
  echo [ERRO] Uma porta ^(3000, 8000, 5432 ou 6379^) ja esta em uso.
  echo Feche o programa que usa a porta ou rode PARAR.bat antes.
  pause
  exit /b 1
)

echo [ERRO] Falha ao subir. Veja a mensagem acima.
echo Consulte SOLUCAO_DE_PROBLEMAS.md
pause
exit /b 1

:SUBIDA_OK

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
