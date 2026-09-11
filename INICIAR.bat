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

REM ---------- 4. Portas livres ----------
REM No Windows o Hyper-V/WinNAT reserva faixas de portas a cada boot; quando
REM a 3000 cai numa delas o Docker falha com "ports are not available ...
REM access permissions". O script abaixo testa cada porta de verdade e,
REM se precisar, escolhe outra livre e grava no .env da raiz.
echo Verificando portas (painel 3000 / API 8000 / banco 5432 / fila 6379)...
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
echo [OK] Portas definidas: painel %PORTA_PAINEL% - API %PORTA_API%.
echo.

REM ---------- 5. Subir ----------
echo Subindo containers (primeira vez demora)...
set "LOG_SUBIDA=%TEMP%\notasflow_up.log"
if exist "%LOG_SUBIDA%" del "%LOG_SUBIDA%" >nul 2>nul

REM Mostra a saida na tela e grava em log ao mesmo tempo (para diagnostico).
REM Detalhes: o Tee-Object antigo gravava UTF-16 e o findstr nao encontrava
REM NADA no log (diagnostico quebrado em silencio). Agora: UTF-8 sem BOM,
REM gravado uma unica vez no fim (rapido mesmo com milhares de linhas).
docker compose up --build -d 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -Variable saida | ForEach-Object { Write-Host $_ }; if ($saida) { [IO.File]::WriteAllLines('%LOG_SUBIDA%', [string[]]$saida, (New-Object Text.UTF8Encoding($false))) }"

REM ---------- 5b. TODOS os servicos estao de pe? ----------
REM Antes so a API era verificada: com o frontend caido o script dizia
REM "Pronto!" e abria uma pagina que nao carregava. Agora confere os 6.
set FALTANDO_SERVICOS=0
for %%S in (api frontend worker beat db redis) do (
  docker compose ps --services --status running 2>nul | findstr /x /i "%%S" >nul 2>nul
  if errorlevel 1 set /a FALTANDO_SERVICOS+=1
)
if %FALTANDO_SERVICOS%==0 goto SUBIDA_OK

REM ---------- 5c. Diagnostico de erros conhecidos ----------
findstr /i /c:"read-only file system" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_READONLY

findstr /i /c:"no space left on device" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_ESPACO

findstr /i /c:"port is already allocated" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA
findstr /i /c:"ports are not available" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA
findstr /i /c:"access permissions" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA
findstr /i /c:"bind: An attempt was made" "%LOG_SUBIDA%" >nul 2>nul
if not errorlevel 1 goto ERRO_PORTA

goto ERRO_GENERICO

:PORTA_FALHOU
REM Distincao: falha real (sem porta livre) x PowerShell quebrado.
findstr /c:"[ERRO]" "%ARQ_PORTAS%" >nul 2>nul
if not errorlevel 1 goto PORTA_SEM_PORTA
echo.
echo [AVISO] Nao foi possivel verificar as portas automaticamente.
echo         Seguindo com as padroes (3000/8000/5432/6379).
echo.
goto SUBIR

:PORTA_SEM_PORTA
echo.
echo ============================================
echo   NAO SOBROU PORTA LIVRE
echo ============================================
echo Todas as portas alternativas estao ocupadas ou reservadas pelo Windows.
echo Isso costuma ser o WinNAT/Hyper-V reservando faixas de portas.
echo.
echo Para ver as faixas reservadas, abra um PowerShell como ADMINISTRADOR:
echo   netsh interface ipv4 show excludedportrange protocol=tcp
echo.
echo Liberacao classica (ADMINISTRADOR, solta as reservas dinamicas):
echo   net stop winnat
echo   net start winnat
echo Depois rode INICIAR.bat de novo.
echo.
echo Tambem da para fixar uma porta manualmente: crie um arquivo .env na
echo raiz do projeto com a linha  FRONTEND_PORT=3030  (por exemplo).
echo.
pause
exit /b 1

:ERRO_PORTA
echo.
echo ============================================
echo   PROBLEMA DE PORTA NO WINDOWS
echo ============================================
echo O Docker nao conseguiu usar uma das portas. Nao e bug do NotasFlow:
echo e o Windows (Hyper-V/WinNAT) reservando faixas de portas, ou outro
echo programa usando a mesma porta.
echo.
echo O NotasFlow JA tenta desviar disso sozinho (escolhe outra porta
echo automaticamente). Como mesmo assim falhou, faca na ordem:
echo.
echo   1^) Feche programas que possam usar as portas 3000/8000/5432/6379
echo      ^(outro Docker, Node, Postgres, Redis...^) e rode INICIAR.bat de novo.
echo.
echo   2^) PowerShell como ADMINISTRADOR - libera as reservas do Windows:
echo        net stop winnat
echo        net start winnat
echo      Depois rode INICIAR.bat de novo.
echo.
echo   3^) Para fixar a porta 3000 de vez ^(ADMINISTRADOR, depois de reiniciar
echo      o winnat^), reserve-a para o Docker:
echo        netsh int ipv4 add excludedportrange protocol=tcp startport=3000 numberofports=1
echo.
echo   4^) Alternativa: fixe outra porta no arquivo .env da raiz do projeto:
echo        FRONTEND_PORT=3030
echo.
echo Detalhes em SOLUCAO_DE_PROBLEMAS.md
echo ============================================
pause
exit /b 1

:ERRO_READONLY
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

:ERRO_ESPACO
echo.
echo [ERRO] Sem espaco em disco para o Docker.
echo Libere espaco e rode:  docker system prune -a
echo Depois execute INICIAR.bat de novo.
pause
exit /b 1

:ERRO_GENERICO
echo.
echo ============================================
echo   FALHA AO SUBIR
echo ============================================
echo Alguns servicos nao ficaram de pe. Ultimas mensagens da subida:
echo.
powershell -NoProfile -Command "Get-Content '%LOG_SUBIDA%' -Tail 40"
echo.
echo Log dos containers que nao subiram:
echo.
for %%S in (api frontend worker beat db redis) do (
  docker compose ps --services --status running 2>nul | findstr /x /i "%%S" >nul 2>nul
  if errorlevel 1 docker compose logs --tail 30 %%S
)
echo.
echo Consulte SOLUCAO_DE_PROBLEMAS.md. Tente INICIAR.bat de novo.
pause
exit /b 1

:SUBIDA_OK

REM ---------- 6. Aguardar a API ----------
echo.
echo Aguardando a API responder (na primeira vez pode demorar)...
set TENTATIVAS_API=0
:AGUARDAR_API
set /a TENTATIVAS_API+=1
curl.exe -fsS --max-time 4 http://localhost:%PORTA_API%/saude >nul 2>nul
if not errorlevel 1 goto API_OK
if %TENTATIVAS_API% GEQ 60 goto API_FALHOU
timeout /t 3 /nobreak >nul
goto AGUARDAR_API

:API_FALHOU
echo.
echo ============================================
echo   A API NAO CONSEGUIU INICIAR
echo ============================================
echo Abaixo estao as ultimas mensagens da API:
echo.
docker compose logs --tail 120 api
echo.
echo Tente novamente com INICIAR.bat. Se persistir, copie as mensagens
echo acima ao pedir suporte. Consulte tambem SOLUCAO_DE_PROBLEMAS.md.
pause
exit /b 1

:API_OK
echo [OK] API respondendo.

REM ---------- 7. Aguardar o painel (frontend) ----------
REM Antes o script abria o navegador antes da hora e a pagina nao carregava.
echo Aguardando o painel responder...
set TENTATIVAS_PAINEL=0
:AGUARDAR_PAINEL
set /a TENTATIVAS_PAINEL+=1
curl.exe -fsS --max-time 4 http://localhost:%PORTA_PAINEL%/ >nul 2>nul
if not errorlevel 1 goto PAINEL_OK
if %TENTATIVAS_PAINEL% GEQ 40 goto PAINEL_AVISO
timeout /t 3 /nobreak >nul
goto AGUARDAR_PAINEL

:PAINEL_AVISO
echo [AVISO] O painel ainda nao respondeu. Veja o estado dele:
docker compose ps frontend
docker compose logs --tail 40 frontend
echo.
goto PRONTO

:PAINEL_OK
echo [OK] Painel respondendo.

:PRONTO
echo.
echo ============================================
echo   Pronto!
echo ============================================
echo   Painel:  http://localhost:%PORTA_PAINEL%
echo   API:     http://localhost:%PORTA_API%/docs
echo.
if not "%PORTA_PAINEL%"=="3000" (
  echo   [AVISO] A porta padrao 3000 estava ocupada/reservada no Windows,
  echo   por isso o painel esta na porta %PORTA_PAINEL%. Anote este endereco.
)
echo.
echo   Login (veja tambem CREDENCIAIS.txt):
echo   Email: admin@notasflow.local
echo   Senha: (arquivo CREDENCIAIS.txt)
echo ============================================
echo.
start http://localhost:%PORTA_PAINEL%
pause
