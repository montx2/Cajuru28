<#
.SYNOPSIS
    Instala o Cajuru Agent nesta estação Windows.

.DESCRIPTION
    Prepara a máquina que guarda os certificados A1 para operar o módulo
    Procurações RFB do Cajuru28:

      1. confere Python 3.11+;
      2. cria um ambiente virtual isolado e instala as dependências;
      3. grava a credencial da estação no Windows Credential Manager;
      4. registra uma tarefa agendada que sobe o Agent no logon;
      5. roda o diagnóstico do Assinador Digital SERPRO e mostra o que falta.

    O instalador NÃO pede, não lê e não copia senha de certificado. A chave
    privada permanece sob o CryptoAPI do Windows do começo ao fim.

.PARAMETER ServidorUrl
    Endereço HTTPS do Cajuru28. Ex.: https://cajuru.suaempresa.com.br

.PARAMETER Identificador
    Identificador da estação. Quem o gera é o servidor, no momento da
    matrícula: em Procurações -> Estações, clique em "Matricular estação",
    informe só o nome da máquina e copie o comando pronto que a tela exibe.
    São 32 caracteres hexadecimais; não invente nem edite esse valor.

.PARAMETER Segredo
    Segredo exibido uma única vez no momento da matrícula.

.EXAMPLE
    .\instalar_agent.ps1 -ServidorUrl "https://cajuru.exemplo.com.br" `
                         -Identificador "a1b2c3..." -Segredo "..."
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ServidorUrl,
    [Parameter(Mandatory = $true)][string]$Identificador,
    [Parameter(Mandatory = $true)][string]$Segredo,
    [string]$NomeEstacao = $env:COMPUTERNAME,
    [string]$PastaPfx = "",
    [int]$Capacidade = 1,
    [switch]$SemTarefaAgendada
)

$ErrorActionPreference = 'Stop'
$RaizAgent = Split-Path -Parent $MyInvocation.MyCommand.Path
$Destino   = Join-Path $env:LOCALAPPDATA 'Cajuru28\Agent'
$Venv      = Join-Path $Destino 'venv'

function Escrever-Passo([string]$Texto) { Write-Host "`n==> $Texto" -ForegroundColor Cyan }
function Escrever-Ok([string]$Texto)    { Write-Host "    OK   $Texto" -ForegroundColor Green }
function Escrever-Aviso([string]$Texto) { Write-Host "    !!   $Texto" -ForegroundColor Yellow }

Write-Host ""
Write-Host "Cajuru Agent - instalacao" -ForegroundColor White
Write-Host "=========================" -ForegroundColor White

# ---------------------------------------------------------------- validações
Escrever-Passo "Validando parametros"

if ($ServidorUrl -notmatch '^https://') {
    throw "ServidorUrl precisa comecar com https:// (recebido: $ServidorUrl). " +
          "A credencial da estacao nunca deve trafegar em texto claro."
}
if ($Identificador -notmatch '^[0-9a-fA-F]{16,64}$') {
    throw "Identificador invalido: '$Identificador'. O valor e gerado pelo Cajuru28 " +
          "na matricula da estacao (Procuracoes -> Estacoes -> Matricular estacao) e tem " +
          "32 caracteres hexadecimais. Copie o comando pronto exibido na tela."
}
$Identificador = $Identificador.ToLower()
Escrever-Ok "Servidor: $ServidorUrl"
Escrever-Ok "Estacao : $NomeEstacao"

# -------------------------------------------------------------------- Python
Escrever-Passo "Verificando Python 3.11 ou superior"

$python = $null
foreach ($candidato in @('py -3.12','py -3.11','python')) {
    try {
        $partes = $candidato.Split(' ')
        $versao = & $partes[0] $partes[1..($partes.Length-1)] -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
        if ($LASTEXITCODE -eq 0 -and [version]$versao -ge [version]'3.11') {
            $python = $candidato
            Escrever-Ok "Python $versao encontrado ($candidato)"
            break
        }
    } catch { }
}
if (-not $python) {
    throw "Python 3.11+ nao encontrado. Instale a partir de https://www.python.org/downloads/windows/ " +
          "marcando 'Add python.exe to PATH'."
}

# ------------------------------------------------------------------ arquivos
Escrever-Passo "Copiando o Agent para $Destino"
New-Item -ItemType Directory -Force -Path $Destino | Out-Null
Copy-Item -Recurse -Force (Join-Path $RaizAgent 'cajuru_agent') $Destino
Copy-Item -Force (Join-Path $RaizAgent 'requirements.txt') $Destino
Escrever-Ok "Arquivos copiados"

# ---------------------------------------------------------------------- venv
Escrever-Passo "Preparando ambiente virtual isolado"
if (-not (Test-Path (Join-Path $Venv 'Scripts\python.exe'))) {
    $partes = $python.Split(' ')
    & $partes[0] $partes[1..($partes.Length-1)] -m venv $Venv
}
$PythonVenv = Join-Path $Venv 'Scripts\python.exe'
& $PythonVenv -m pip install --quiet --upgrade pip
& $PythonVenv -m pip install --quiet -r (Join-Path $Destino 'requirements.txt')
Escrever-Ok "Dependencias instaladas"

# --------------------------------------------------------------- credenciais
Escrever-Passo "Gravando credencial no Windows Credential Manager"
& $PythonVenv -m cajuru_agent configurar `
    --servidor $ServidorUrl `
    --identificador $Identificador `
    --segredo $Segredo `
    --nome $NomeEstacao `
    --pasta-pfx $PastaPfx `
    --capacidade $Capacidade
if ($LASTEXITCODE -ne 0) { throw "Falha ao gravar a configuracao da estacao." }
Escrever-Ok "Credencial protegida pelo cofre do Windows (DPAPI)"
Escrever-Aviso "Apague agora a mensagem/anotacao que continha o segredo: ele nao e mais necessario."

# ----------------------------------------------------- Assinador e hosts
Escrever-Passo "Conferindo o mapeamento do Assinador SERPRO no arquivo hosts"
$Hosts = "$env:WINDIR\System32\drivers\etc\hosts"
$Linha = "127.0.0.1 assinador-desktop.serpro.gov.br"
$JaTem = (Get-Content $Hosts -ErrorAction SilentlyContinue) -match 'assinador-desktop\.serpro\.gov\.br'
if ($JaTem) {
    Escrever-Ok "Mapeamento ja presente"
} else {
    try {
        Add-Content -Path $Hosts -Value "`r`n$Linha" -ErrorAction Stop
        Escrever-Ok "Mapeamento adicionado"
    } catch {
        Escrever-Aviso "Nao foi possivel editar o arquivo hosts (execute como Administrador)."
        Escrever-Aviso "Adicione manualmente a linha: $Linha"
    }
}

# ------------------------------------------------------------ tarefa agendada
if (-not $SemTarefaAgendada) {
    Escrever-Passo "Registrando tarefa agendada (inicia no logon do usuario)"
    $NomeTarefa = 'Cajuru28 - Agent Procuracoes'
    $Acao    = New-ScheduledTaskAction -Execute $PythonVenv -Argument '-m cajuru_agent executar' -WorkingDirectory $Destino
    $Gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $Opcoes  = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
                                            -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5)
    try {
        Unregister-ScheduledTask -TaskName $NomeTarefa -Confirm:$false -ErrorAction SilentlyContinue
        Register-ScheduledTask -TaskName $NomeTarefa -Action $Acao -Trigger $Gatilho `
                               -Settings $Opcoes -Description 'Cajuru28 - operacao assistida de Autorizacoes de Acesso da RFB' | Out-Null
        Escrever-Ok "Tarefa '$NomeTarefa' registrada"
    } catch {
        Escrever-Aviso "Nao foi possivel registrar a tarefa: $_"
        Escrever-Aviso "Inicie manualmente com: $PythonVenv -m cajuru_agent executar"
    }
}

# --------------------------------------------------------------- diagnóstico
Escrever-Passo "Diagnostico do ambiente"
& $PythonVenv -m cajuru_agent diagnostico
& $PythonVenv -m cajuru_agent certificados

Escrever-Passo "Testando a conexao com o Cajuru28"
& $PythonVenv -m cajuru_agent testar

Write-Host ""
Write-Host "Instalacao concluida." -ForegroundColor Green
Write-Host "Para iniciar agora:  $PythonVenv -m cajuru_agent executar" -ForegroundColor White
Write-Host "Log da estacao    :  $Destino\agent.log" -ForegroundColor White
Write-Host ""
