# =============================================================================
#  NotasFlow - ajuste automatico de portas (Windows)
#
#  Por que existe: no Windows, o Hyper-V/WinNAT reserva faixas dinamicas de
#  portas TCP a cada boot (veja com:
#      netsh interface ipv4 show excludedportrange protocol=tcp  ).
#  Quando a porta 3000 cai numa faixa reservada, o Docker Desktop falha com:
#
#      Error response from daemon: ports are not available: exposing port TCP
#      0.0.0.0:3000 ... bind: An attempt was made to access a socket in a way
#      forbidden by its access permissions.
#
#  Este script testa se cada porta consegue ser ocupada de verdade (bind real,
#  igual ao Docker fara). Porta ocupada pelo nosso proprio container NAO e
#  conflito. Conflito de verdade -> escolhe a proxima porta livre e grava no
#  .env da raiz (o docker-compose le de la).
#
#  Saida: linhas CHAVE=VALOR (para o .bat ler) e linhas com '#' (humanos).
#  Nao exige administrador.
#
#  Uso:
#    powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ajustar_portas.ps1
#    ... -Ver   (so mostra, nao grava)
# =============================================================================

param([switch]$Ver)

$ErrorActionPreference = "Stop"
try { [Console]::OutputEncoding = [Text.Encoding]::UTF8 } catch { }

$Raiz = Split-Path -Parent $PSScriptRoot   # pasta do projeto (acima de scripts\)
Set-Location $Raiz
$ArquivoEnv = Join-Path $Raiz ".env"

# ---------- definicoes: chave no .env, container e portas candidatas ----------
$Definicoes = @(
    @{ Chave = "FRONTEND_PORT"; Servico = "frontend";
       Candidatas = @(3000, 3001, 3002, 3003, 3004, 3005, 3100, 8080, 8081, 8082, 9090) },
    @{ Chave = "API_PORT"; Servico = "api";
       Candidatas = @(8000, 8001, 8002, 8003, 8004, 8005, 9000, 9001, 8443) },
    @{ Chave = "DB_PORT"; Servico = "db";
       Candidatas = @(5432, 5433, 5434, 5435, 5436, 55432) },
    @{ Chave = "REDIS_PORT"; Servico = "redis";
       Candidatas = @(6379, 6380, 6381, 6382, 6383, 16379) }
)
$ApiPortaPadrao = 8000

# ---------- funcoes de apoio ----------

# Le o .env da raiz num hashtable (chave -> valor).
function Ler-Env {
    $mapa = @{}
    if (Test-Path $ArquivoEnv) {
        foreach ($linha in (Get-Content $ArquivoEnv -ErrorAction SilentlyContinue)) {
            $l = "$linha".Trim()
            if ($l -eq "" -or $l.StartsWith("#")) { continue }
            $i = $l.IndexOf("=")
            if ($i -lt 1) { continue }
            $mapa[$l.Substring(0, $i).Trim()] = $l.Substring($i + 1).Trim()
        }
    }
    return $mapa
}

# Testa ocupar a porta de verdade - mesmo teste que o Docker fara.
# (netstat nao basta: porta reservada pelo WinNAT aparece como livre e falha
#  no bind com "access permissions").
function Porta-Livre([int]$Porta) {
    $ouvinte = $null
    try {
        $ouvinte = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Any, $Porta)
        $ouvinte.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($ouvinte -ne $null) {
            try { $ouvinte.Stop() } catch { }
        }
    }
}

# Servicos DESTE projeto compose que estao rodando (porta ocupada por nos
# nao e conflito). Qualquer falha -> vazio. Comandos nativos rodando com
# ErrorActionPreference=Stop exigem este cuidado no PowerShell 5.1.
function Servicos-Rodando {
    $resultado = @{}
    $anterior = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $saida = & docker compose ps --services --status running 2>$null
        if ($LASTEXITCODE -eq 0 -and $saida) {
            foreach ($s in $saida) {
                $t = "$s".Trim()
                if ($t -ne "") { $resultado[$t] = $true }
            }
        }
    } catch { }
    finally { $ErrorActionPreference = $anterior }
    return $resultado
}

# Regrava o .env trocando/apensando as chaves informadas, preservando o
# resto. UTF-8 SEM BOM: o parser de .env do docker-compose engasga com BOM.
function Gravar-Env([hashtable]$Mudancas) {
    $linhas = @()
    if (Test-Path $ArquivoEnv) {
        $linhas = @(Get-Content $ArquivoEnv -ErrorAction SilentlyContinue)
    }
    $cabecalho = "# Portas do NotasFlow - escolhidas automaticamente pelo INICIAR/INSTALAR."
    if (-not ($linhas | Where-Object { "$_".Trim() -eq $cabecalho })) {
        $linhas = @($cabecalho) + $linhas
    }

    $restantes = @{}
    foreach ($chave in $Mudancas.Keys) { $restantes[$chave] = $Mudancas[$chave] }
    $novas = @()
    foreach ($linha in $linhas) {
        $l = "$linha".Trim()
        $processada = $false
        if ($l -ne "" -and -not $l.StartsWith("#")) {
            $i = $l.IndexOf("=")
            if ($i -ge 1) {
                $chave = $l.Substring(0, $i).Trim()
                if ($restantes.ContainsKey($chave)) {
                    $novas += "$chave=$($restantes[$chave])"
                    $restantes.Remove($chave) | Out-Null
                    $processada = $true
                }
            }
        }
        if (-not $processada) { $novas += $linha }
    }
    foreach ($chave in $restantes.Keys) { $novas += "$chave=$($restantes[$chave])" }

    $utf8SemBom = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllLines($ArquivoEnv, [string[]]$novas, $utf8SemBom)
}

# ---------- execucao ----------

$Mapa = Ler-Env
$Rodando = Servicos-Rodando
$Escolhidas = @{}
$Mudancas = @{}
$Final = @{}
$Mudou = $false

foreach ($def in $Definicoes) {
    $chave = $def.Chave
    $candidatas = $def.Candidatas
    $padrao = $candidatas[0]

    $atualBruto = ""
    if ($Mapa.ContainsKey($chave)) { $atualBruto = "$($Mapa[$chave])".Trim() }
    $atual = 0
    if (-not [int]::TryParse($atualBruto, [ref]$atual) -or $atual -le 0) {
        if ($atualBruto -ne "") {
            Write-Output "# [AVISO] $chave=$atualBruto nao e um numero; usando $padrao."
        }
        $atual = $padrao
    }

    $escolhida = 0

    # 1) Porta atual consegue ser ocupada por este projeto?
    if (-not $Escolhidas.ContainsKey($atual) -and (Porta-Livre $atual)) {
        $escolhida = $atual
    }
    # 2) Ocupada, mas por container NOSSO deste projeto: mantem.
    elseif (-not $Escolhidas.ContainsKey($atual) -and $Rodando.ContainsKey($def.Servico)) {
        $escolhida = $atual
    }
    # 3) Conflito de verdade: primeira candidata livre.
    else {
        foreach ($candidata in $candidatas) {
            if ($Escolhidas.ContainsKey($candidata)) { continue }
            if (Porta-Livre $candidata) { $escolhida = $candidata; break }
        }
        if ($escolhida -le 0) {
            Write-Output "# [ERRO] Nenhuma porta livre encontrada para $($def.Servico)."
            Write-Output "#         Testadas: $($candidatas -join ', ')."
            Write-Output "#         Feche o programa que ocupa a porta ou escolha outra"
            Write-Output "#         manualmente no arquivo .env na raiz do projeto."
            exit 1
        }
        $Mudou = $true
        Write-Output "# Porta $atual indisponivel para $($def.Servico) (em uso ou"
        Write-Output "# reservada pelo Windows/Hyper-V). Usando $escolhida."
    }

    $Escolhidas[$escolhida] = $true
    $Final[$chave] = "$escolhida"
    if ($atualBruto -ne "$escolhida") { $Mudancas[$chave] = "$escolhida" }
}

# A URL da API e embutida no build do frontend - precisa acompanhar a porta.
$portaApi = [int]$Final["API_PORT"]
if ($portaApi -ne $ApiPortaPadrao) {
    $urlApi = "http://localhost:$portaApi"
    $urlAtual = ""
    if ($Mapa.ContainsKey("NEXT_PUBLIC_API_URL")) { $urlAtual = "$($Mapa["NEXT_PUBLIC_API_URL"])".Trim() }
    if ($urlAtual -ne $urlApi) {
        $Mudancas["NEXT_PUBLIC_API_URL"] = $urlApi
        $Mudou = $true
        Write-Output "# API fora da porta padrao: frontend vai usar $urlApi"
        Write-Output "# (o frontend sera reconstruido automaticamente)"
    }
}

if ($Mudou -and -not $Ver) {
    if ($Mudancas.Count -gt 0) {
        Gravar-Env $Mudancas
        $pares = ($Mudancas.Keys | Sort-Object | ForEach-Object { "$_=$($Mudancas[$_])" }) -join ", "
        Write-Output "# Gravado no .env da raiz: $pares"
        Write-Output "# Para voltar ao padrao, apague essas linhas do arquivo .env."
    }
}
elseif ($Mudou -and $Ver) {
    Write-Output "# (-Ver: nada foi gravado)"
}

# Saida para o .bat: sempre as 4 portas finais.
foreach ($def in $Definicoes) {
    Write-Output "$($def.Chave)=$($Final[$def.Chave])"
}
$marcador = "0"
if ($Mudou) { $marcador = "1" }
Write-Output "MUDOU=$marcador"
exit 0
