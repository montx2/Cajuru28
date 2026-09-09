# =============================================================================
#  NotasFlow - Instalador completo para Windows
#  Instala TUDO num PC zerado: Git + Python + Docker Desktop + WSL2,
#  gera as chaves (.env), sobe o sistema e abre o painel no navegador.
#
#  Como usar: de dois cliques em INSTALAR_TUDO.bat
#
#  Idempotente: pode rodar quantas vezes quiser - o que ja esta
#  instalado e detectado e pulado.
# =============================================================================

param(
    [switch]$SoVerificar,      # so checa o que falta, nao instala nada
    [switch]$NaoAbrirBrowser   # nao abre o navegador no final
)

# ---------- Configuracao basica do script ----------
$ErrorActionPreference = "Stop"
$ProgressPreference    = "SilentlyContinue"
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    [Console]::OutputEncoding = [Text.Encoding]::UTF8
} catch { }

$Raiz = Split-Path -Parent $PSScriptRoot   # pasta do projeto (acima de scripts\)
Set-Location $Raiz

# ---------- Auto-elevacao para Administrador (necessario p/ instalar) ----------
$identidade = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal  = New-Object Security.Principal.WindowsPrincipal($identidade)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    if ($SoVerificar) {
        Write-Host "[!] Modo verificacao nao precisa de administrador." -ForegroundColor Yellow
    } else {
        Write-Host "Pedindo permissao de administrador (necessario para instalar)..." -ForegroundColor Yellow
        $argsElev = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
        if ($NaoAbrirBrowser) { $argsElev += " -NaoAbrirBrowser" }
        try {
            Start-Process powershell -Verb RunAs -ArgumentList $argsElev
        } catch {
            Write-Host "[ERRO] Sem permissao de administrador nao da para instalar." -ForegroundColor Red
            Write-Host "       Clique com o botao direito em INSTALAR_TUDO.bat e" -ForegroundColor Red
            Write-Host "       escolha 'Executar como administrador'." -ForegroundColor Red
            Read-Host "  Pressione ENTER para sair"
        }
        exit
    }
}

# ---------- Funcoes de apoio ----------
function Log($m)   { Write-Host "  $m" -ForegroundColor Gray }
function Ok($m)    { Write-Host "  [OK] $m" -ForegroundColor Green }
function Aviso($m) { Write-Host "  [!] $m" -ForegroundColor Yellow }
function Erro($m)  { Write-Host "  [ERRO] $m" -ForegroundColor Red }

function Etapa($titulo) {
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
    Write-Host "  $titulo" -ForegroundColor Cyan
    Write-Host ("=" * 60) -ForegroundColor DarkCyan
}

# Recarrega o PATH da maquina + usuario (apos instalar algo)
function Atualizar-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
}

# Verifica se um comando existe no PATH
function Tem($comando) {
    return [bool](Get-Command $comando -ErrorAction SilentlyContinue)
}

# Executa um comando NATIVO (git/docker/wsl/winget/dism) de forma segura:
# o PowerShell 5.1 com ErrorActionPreference=Stop aborta se o comando
# escrever no stderr (ex.: "docker info" com o motor desligado).
# Retorna o codigo de saida do comando.
function Rodar-Seguro([scriptblock]$bloco) {
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $bloco 2>&1 | Out-Null
        return $LASTEXITCODE
    } catch {
        return 1
    } finally {
        $ErrorActionPreference = $anterior
    }
}

# Detecta Python REAL (ignora o 'alias' falso da Microsoft Store)
function Python-Real {
    foreach ($cmd in @("python", "py")) {
        if (Tem $cmd) {
            $cod = Rodar-Seguro { & $cmd --version }
            if ($cod -eq 0) {
                $versao = (& $cmd --version 2>&1 | Out-String).Trim()
                if ($versao -match "Python 3") { return $cmd }
            }
        }
    }
    return $null
}

# Instala via winget; se winget nao existir/falhar, baixa o instalador direto
function Instalar-Pacote {
    param(
        [string]$Nome,                 # nome bonito p/ log
        [string]$WingetId,             # id do winget (ou vazio p/ so download)
        [string]$UrlDownload,          # URL do instalador fallback
        [string]$ModoDownload,         # "DOCKER" ou argumentos do instalador
        [scriptblock]$TesteInstalado   # retorna $true se ja instalado
    )
    if (& $TesteInstalado) { Ok "$Nome ja instalado"; return $true }

    Write-Host "  Instalando $Nome (pode demorar varios minutos)..." -ForegroundColor White

    $wingetExe = $null
    if ($WingetId -and (Tem "winget")) {
        $wingetExe = (Get-Command winget -ErrorAction SilentlyContinue).Source
    }
    if ($wingetExe) {
        Log "usando winget ($WingetId)..."
        Start-Process -FilePath $wingetExe -Wait -NoNewWindow -ArgumentList @(
            "install", "--id", $WingetId, "-e", "--silent",
            "--accept-package-agreements", "--accept-source-agreements"
        )
        Atualizar-Path
        if (& $TesteInstalado) { Ok "$Nome instalado (winget)"; return $true }
        Aviso "winget nao confirmou a instalacao; tentando download direto..."
    }

    if ($UrlDownload) {
        Log "baixando instalador..."
        Log $UrlDownload
        $arquivo = Join-Path $env:TEMP ([IO.Path]::GetFileName(($UrlDownload -replace "%20", " ")))
        try {
            Invoke-WebRequest -Uri $UrlDownload -OutFile $arquivo -UseBasicParsing
        } catch {
            Erro "falha ao baixar $Nome : $($_.Exception.Message)"
            return $false
        }
        Log "executando instalador silencioso..."
        try {
            if ($ModoDownload -eq "DOCKER") {
                # Docker Desktop tem modo proprio de instalacao silenciosa
                Start-Process -FilePath $arquivo -Wait -NoNewWindow -ArgumentList @("install", "--quiet", "--accept-license")
            } else {
                Start-Process -FilePath $arquivo -Wait -NoNewWindow -ArgumentList $ModoDownload
            }
        } catch {
            Erro "o instalador de $Nome falhou: $($_.Exception.Message)"
            return $false
        }
        Atualizar-Path
        if (& $TesteInstalado) { Ok "$Nome instalado"; return $true }
    }

    Erro "nao consegui instalar $Nome."
    Write-Host "  Instale manualmente e rode INSTALAR_TUDO.bat de novo:" -ForegroundColor Gray
    return $false
}

# ---------- Banner ----------
Clear-Host
Write-Host ""
Write-Host "  ################################################" -ForegroundColor Cyan
Write-Host "  #        NotasFlow - INSTALADOR COMPLETO        #" -ForegroundColor Cyan
Write-Host "  #   Git + Python + Docker + Sistema no ar       #" -ForegroundColor Cyan
Write-Host "  ################################################" -ForegroundColor Cyan
Write-Host ""
if ($SoVerificar) {
    Write-Host "  MODO VERIFICACAO: nada sera instalado." -ForegroundColor Yellow
    Write-Host ""
}

$faltando          = @()
$precisaReiniciar  = $false
$dockerRecemInstalado = $false

# =============================================================================
# PASSO 1 - Git
# =============================================================================
Etapa "PASSO 1/7 - Git"
$gitOk = $false
if (Tem "git") {
    if ((Rodar-Seguro { git --version }) -eq 0) {
        $gitOk = $true
        $gv = (git --version 2>&1 | Out-String).Trim()
        Ok "Git ja instalado ($gv)"
    }
}
if (-not $gitOk) {
    $faltando += "Git"
    if (-not $SoVerificar) {
        $gitOk = Instalar-Pacote -Nome "Git" `
            -WingetId "Git.Git" `
            -UrlDownload "https://github.com/git-for-windows/git/releases/download/v2.47.1-windows.1/Git-2.47.1-64-bit.exe" `
            -ModoDownload "/VERYSILENT /NORESTART /SUPPRESSMSGBOXES" `
            -TesteInstalado { (Rodar-Seguro { git --version }) -eq 0 }
    }
}

# =============================================================================
# PASSO 2 - Python 3
# =============================================================================
Etapa "PASSO 2/7 - Python 3"
$pythonCmd = Python-Real
if ($pythonCmd) {
    Ok "Python ja instalado ($(& $pythonCmd --version 2>&1 | Out-String).Trim())"
} else {
    $faltando += "Python"
    if (-not $SoVerificar) {
        $pythonOk = Instalar-Pacote -Nome "Python 3.12" `
            -WingetId "Python.Python.3.12" `
            -UrlDownload "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe" `
            -ModoDownload "/quiet InstallAllUsers=1 PrependPath=1 Include_test=0" `
            -TesteInstalado { [bool](Python-Real) }
        $pythonCmd = Python-Real
    }
}

# =============================================================================
# PASSO 3 - Docker Desktop
# =============================================================================
Etapa "PASSO 3/7 - Docker Desktop"
$dockerDesktopExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
if ((Tem "docker") -or (Test-Path $dockerDesktopExe)) {
    Ok "Docker Desktop ja instalado"
} else {
    $faltando += "Docker Desktop"
    if (-not $SoVerificar) {
        $dockerRecemInstalado = Instalar-Pacote -Nome "Docker Desktop" `
            -WingetId "Docker.DockerDesktop" `
            -UrlDownload "https://desktop.docker.com/win/main/amd64/Docker%20Desktop%20Installer.exe" `
            -ModoDownload "DOCKER" `
            -TesteInstalado { (Tem "docker") -or (Test-Path (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")) }
        $dockerDesktopExe = Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"
        if ($dockerRecemInstalado) { $precisaReiniciar = $true }
    }
}

# =============================================================================
# PASSO 4 - WSL2 (motor do Docker no Windows)
# =============================================================================
Etapa "PASSO 4/7 - WSL2 (nucleo do Linux para o Docker)"
if (Tem "wsl") {
    if ((Rodar-Seguro { wsl --status }) -eq 0) {
        Ok "WSL2 ja configurado"
    } elseif ($SoVerificar) {
        Aviso "WSL presente mas com problema (pode precisar de reparo)"
        $faltando += "WSL2 (reparo)"
    } else {
        Aviso "WSL presente mas com problema; tentando reparar..."
        [void](Rodar-Seguro { wsl --update })
        [void](Rodar-Seguro { wsl --set-default-version 2 })
        if ((Rodar-Seguro { wsl --status }) -eq 0) {
            Ok "WSL2 reparado"
        } else {
            $precisaReiniciar = $true
        }
    }
} else {
    if (-not $SoVerificar) {
        Aviso "WSL2 nao encontrado. Habilitando (pede reinicio do Windows)..."
        $cod = Rodar-Seguro { wsl --install --no-launch }
        if (-not (Tem "wsl") -or $cod -ne 0) {
            Log "comando 'wsl --install' indisponivel; habilitando recursos via DISM..."
            [void](Rodar-Seguro { dism.exe /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart })
            [void](Rodar-Seguro { dism.exe /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart })
        }
        $precisaReiniciar = $true
    } else {
        $faltando += "WSL2"
    }
}

# ---------- Modo verificacao termina aqui ----------
if ($SoVerificar) {
    Etapa "RESULTADO DA VERIFICACAO"
    if ($faltando.Count -eq 0) {
        Ok "Tudo instalado! Pode rodar INICIAR.bat (ou INSTALAR_TUDO.bat)"
    } else {
        Aviso "Falta instalar: $($faltando -join ', ')"
        Write-Host "  Rode INSTALAR_TUDO.bat para instalar automaticamente." -ForegroundColor White
    }
    Read-Host "  Pressione ENTER para fechar"
    exit 0
}

if ($precisaReiniciar) {
    Etapa "REINICIO NECESSARIO"
    Write-Host @"

  O Windows precisa REINICIAR para terminar de habilitar o WSL2/Docker.

  Depois de reiniciar:
    1. Abra esta pasta de novo
    2. De dois cliques em INSTALAR_TUDO.bat novamente
    3. Ele continua de onde parou (nao repete nada que ja existe)

"@ -ForegroundColor Yellow
    $resp = Read-Host "  Reiniciar o PC agora? (S/N)"
    if ($resp -match "^[sS]") { Restart-Computer -Force }
    exit 0
}

# =============================================================================
# PASSO 5 - Ligar o motor do Docker
# =============================================================================
Etapa "PASSO 5/7 - Ligando o Docker"
Atualizar-Path

$motorLigado = ((Rodar-Seguro { docker info }) -eq 0)

if (-not $motorLigado) {
    if (Test-Path $dockerDesktopExe) {
        Aviso "Docker Desktop esta desligado. Abrindo..."
        Start-Process $dockerDesktopExe
    } else {
        Erro "Docker Desktop nao foi encontrado neste PC."
        Write-Host "  Rode INSTALAR_TUDO.bat de novo para instala-lo." -ForegroundColor Gray
        Read-Host "  Pressione ENTER para sair"
        exit 1
    }

    Write-Host "  Aguardando o motor do Docker ligar (primeira vez pode levar ate 5 min)..." -ForegroundColor White
    $tentativas = 0
    while ($tentativas -lt 60) {
        Start-Sleep -Seconds 5
        if ((Rodar-Seguro { docker info }) -eq 0) { $motorLigado = $true; break }
        $tentativas++
        if ($tentativas % 6 -eq 0) {
            Write-Host "    ... ainda aguardando ($($tentativas * 5) segundos)" -ForegroundColor DarkGray
        }
    }
}

if ($motorLigado) {
    Ok "Docker ligado"
} else {
    if ($dockerRecemInstalado) {
        Erro "O Docker foi instalado agora e o motor nao ligou."
        Write-Host "  Na maioria das vezes basta REINICIAR o PC e rodar" -ForegroundColor Yellow
        Write-Host "  INSTALAR_TUDO.bat de novo." -ForegroundColor Yellow
        $resp = Read-Host "  Reiniciar o PC agora? (S/N)"
        if ($resp -match "^[sS]") { Restart-Computer -Force }
        exit 1
    }
    Erro "O Docker nao ligou. Abra o Docker Desktop manualmente, espere"
    Write-Host "  o icone da baleia parar de animar e rode INSTALAR_TUDO.bat de novo." -ForegroundColor Gray
    Read-Host "  Pressione ENTER para sair"
    exit 1
}

# Docker Compose vem junto com o Docker Desktop moderno; garante que existe
if ((Rodar-Seguro { docker compose version }) -ne 0) {
    Erro "Docker Compose nao encontrado. Atualize o Docker Desktop."
    Read-Host "  Pressione ENTER para sair"
    exit 1
}
Ok "Docker Compose disponivel"

# =============================================================================
# PASSO 6 - Chaves e credenciais (.env)
# =============================================================================
Etapa "PASSO 6/7 - Gerando chaves e login"
if (Test-Path "backend\.env") {
    Ok "backend\.env ja existe (mantendo o atual)"
} else {
    $gerou = $false
    if ($pythonCmd) {
        $cod = Rodar-Seguro { & $pythonCmd "scripts\gerar_env.py" }
        if ($cod -eq 0 -and (Test-Path "backend\.env")) {
            $gerou = $true
            Ok "Chaves geradas pelo gerar_env.py"
        }
    }
    if (-not $gerou) {
        if (-not $pythonCmd) { Aviso "Python ainda indisponivel; gerando chaves pelo PowerShell..." }
        else { Aviso "gerar_env.py falhou; gerando chaves pelo PowerShell..." }

        $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
        # Gera chave urlsafe base64 MANTENDO o padding ("=") no final.
        # IMPORTANTE: a VAULT_MASTER_KEY (32 bytes -> 44 chars com "=") precisa do
        # padding para ser uma chave Fernet valida - sem ele o cofre quebra e a
        # importacao de notas falha. NAO remover o "=" da chave do cofre.
        function Nova-Chave([int]$bytes) {
            $b = New-Object byte[] $bytes
            $rng.GetBytes($b)
            return [Convert]::ToBase64String($b).Replace("+", "-").Replace("/", "_")
        }
        $dados = @{
            SECRET_KEY       = Nova-Chave 48   # 64 chars, igual token_urlsafe(48)
            VAULT_MASTER_KEY = Nova-Chave 32   # 44 chars COM "=" (formato Fernet)
            BOOTSTRAP_SENHA  = (Nova-Chave 16).TrimEnd("=")  # 22 chars, igual token_urlsafe(16)
        }
        New-Item -ItemType Directory -Force -Path "backend" | Out-Null
        $envBackend = @"
# NotasFlow - gerado por scripts/instalar_windows.ps1 (NAO versionar)
DATABASE_URL=postgresql://notasflow:notasflow@db:5432/notasflow
REDIS_URL=redis://redis:6379/0
SECRET_KEY=$($dados.SECRET_KEY)
VAULT_MASTER_KEY=$($dados.VAULT_MASTER_KEY)
# Use apenas durante uma rotação temporária; separe chaves antigas por vírgula.
VAULT_PREVIOUS_MASTER_KEYS=
DADOS_DIR=/data
ACCESS_TOKEN_EXPIRE_MINUTES=480
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,*
AMBIENTE_FISCAL=producao
BOOTSTRAP_ESCRITORIO=Escritorio Cajuru
BOOTSTRAP_NOME=Administrador
BOOTSTRAP_EMAIL=admin@notasflow.local
BOOTSTRAP_SENHA=$($dados.BOOTSTRAP_SENHA)
"@
        [IO.File]::WriteAllText((Join-Path $Raiz "backend\.env"), $envBackend, (New-Object Text.UTF8Encoding($false)))

        $envFrontend = "NEXT_PUBLIC_API_URL=http://localhost:8000`n"
        [IO.File]::WriteAllText((Join-Path $Raiz "frontend\.env.local"), $envFrontend, (New-Object Text.UTF8Encoding($false)))

        $credenciais = @"
================================================================================
  NotasFlow - credenciais geradas automaticamente
  NAO versionar este arquivo. Altere as senhas em producao.
================================================================================

LOGIN DO PAINEL (http://localhost:3000)
  Email:  admin@notasflow.local
  Senha:  $($dados.BOOTSTRAP_SENHA)
  Nome:   Administrador
  Escritorio: Escritorio Cajuru

URLs
  Painel:  http://localhost:3000
  API:     http://localhost:8000/docs

COMO SUBIR
  Windows:  INICIAR.bat
  Terminal: docker compose up --build

================================================================================
"@
        [IO.File]::WriteAllText((Join-Path $Raiz "CREDENCIAIS.txt"), $credenciais, (New-Object Text.UTF8Encoding($false)))
        $gerou = $true
        Ok "Chaves geradas (fallback PowerShell)"
    }
}
if (-not (Test-Path "frontend\.env.local")) {
    Copy-Item "frontend\.env.example" "frontend\.env.local" -ErrorAction SilentlyContinue
}

# =============================================================================
# PASSO 7 - Subir o sistema
# =============================================================================
Etapa "PASSO 7/7 - Subindo o NotasFlow (primeira vez demora varios minutos)"
$codUp = Rodar-Seguro { docker compose up --build -d }
if ($codUp -ne 0) {
    # mostra o erro real (sem Rodar-Seguro, agora que ja sabemos que falhou)
    docker compose up --build -d 2>&1 | Select-Object -First 30 | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
    Erro "Falha ao subir os containers. Veja a mensagem acima."
    Read-Host "  Pressione ENTER para sair"
    exit 1
}
Ok "Containers no ar"

Write-Host "  Aguardando a API responder..." -ForegroundColor White
$apiPronta = $false
$tentativas = 0
while ($tentativas -lt 60) {
    try {
        $r = Invoke-WebRequest -Uri "http://localhost:8000/saude" -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -eq 200) { $apiPronta = $true; break }
    } catch { }
    Start-Sleep -Seconds 5
    $tentativas++
}
if ($apiPronta) { Ok "API respondendo em http://localhost:8000" }
else { Aviso "API ainda subindo - de mais 1-2 minutos e abra o painel." }

# ---------- Final ----------
Etapa "PRONTO! NotasFlow instalado"
Write-Host @"

  Painel:  http://localhost:3000
  API:     http://localhost:8000/docs

"@ -ForegroundColor Green

if (Test-Path "CREDENCIAIS.txt") {
    Write-Host "  Seu login (guarde o arquivo CREDENCIAIS.txt):" -ForegroundColor White
    Get-Content "CREDENCIAIS.txt" | Select-String "Email:|Senha:" | ForEach-Object { Write-Host "    $($_.Line)" }
    Write-Host ""
}

if (-not $NaoAbrirBrowser) {
    Start-Process "http://localhost:3000"
}

Write-Host "  Para parar o sistema:  PARAR.bat"
Write-Host "  Para ligar de novo:    INICIAR.bat"
Write-Host "  Para atualizar:        ATUALIZAR.bat"
Write-Host ""
Read-Host "  Pressione ENTER para fechar"
