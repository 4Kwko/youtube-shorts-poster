<#
.SYNOPSIS
    Sobe o ambiente de desenvolvimento do Clipper no Windows.

.DESCRIPTION
    Aplica as migrations, inicia FastAPI e o worker em janelas próprias e,
    por último, o app Tauri no terminal atual. Ao fechar o Tauri, os processos
    filhos são encerrados.

    É um atalho de desenvolvimento, não um supervisor de produção: não há
    restart automático, health check contínuo nem gestão de logs.

.EXAMPLE
    .\scripts\dev-desktop.ps1
    .\scripts\dev-desktop.ps1 -SkipMigrations -Port 8010
#>

[CmdletBinding()]
param(
    [int]$Port = 8000,
    [switch]$SkipMigrations,
    # Sobe só backend e worker; útil quando o frontend já está rodando.
    [switch]$NoDesktop
)

# Qualquer erro interrompe o script: falha silenciosa aqui vira confusão depois.
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $ProjectRoot "frontend"
$BackendDir = Join-Path $ProjectRoot "backend"
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

$Children = @()

function Write-Step { param([string]$Message) Write-Host "==> $Message" -ForegroundColor Cyan }
function Write-Warn { param([string]$Message) Write-Host "    $Message" -ForegroundColor Yellow }

function Assert-Command {
    param([string]$Name, [string]$Hint)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "'$Name' não encontrado no PATH. $Hint"
    }
}

function Stop-Children {
    foreach ($process in $script:Children) {
        if ($process -and -not $process.HasExited) {
            Write-Step "Encerrando PID $($process.Id)"
            # /T derruba a árvore: o uvicorn com --reload cria subprocessos.
            & taskkill.exe /PID $process.Id /T /F 2>$null | Out-Null
        }
    }
}

try {
    Write-Step "Verificando pré-requisitos"

    if (-not (Test-Path $VenvPython)) {
        throw "Ambiente virtual não encontrado em .venv. Rode: python -m venv .venv; .venv\Scripts\pip install -e "".[dev]"""
    }
    Assert-Command -Name "node" -Hint "Instale o Node.js 20+."
    Assert-Command -Name "npm" -Hint "Instale o Node.js 20+."
    Assert-Command -Name "ffmpeg" -Hint "Instale o FFmpeg e adicione ao PATH."
    Assert-Command -Name "ffprobe" -Hint "Vem junto com o FFmpeg."

    if (-not $NoDesktop) {
        Assert-Command -Name "cargo" -Hint "Instale o Rust stable via https://rustup.rs."
        if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
            throw "Dependências do frontend ausentes. Rode: cd frontend; npm install"
        }
    }

    if (-not (Test-Path (Join-Path $ProjectRoot ".env"))) {
        Write-Warn "Sem .env na raiz; copiando .env.example."
        Copy-Item (Join-Path $ProjectRoot ".env.example") (Join-Path $ProjectRoot ".env")
    }

    Push-Location $ProjectRoot
    $env:PYTHONPATH = $BackendDir

    if (-not $SkipMigrations) {
        Write-Step "Aplicando migrations"
        & $VenvPython -m alembic upgrade head
        if ($LASTEXITCODE -ne 0) { throw "Falha ao aplicar as migrations." }
    }

    Write-Step "Iniciando FastAPI em http://127.0.0.1:$Port"
    $Children += Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "uvicorn", "app.main:app", "--app-dir", "backend", "--port", "$Port") `
        -WorkingDirectory $ProjectRoot -PassThru

    Write-Step "Iniciando worker"
    $Children += Start-Process -FilePath $VenvPython `
        -ArgumentList @("-m", "app.worker") `
        -WorkingDirectory $ProjectRoot -PassThru

    Start-Sleep -Seconds 3
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
        Write-Step "Motor pronto (ffmpeg=$($health.dependencies.ffmpeg), ffprobe=$($health.dependencies.ffprobe))"
    }
    catch {
        Write-Warn "O /health ainda não respondeu; verifique a janela do FastAPI."
    }

    if ($NoDesktop) {
        Write-Step "Backend e worker no ar. Ctrl+C encerra."
        Wait-Process -Id $Children[0].Id
    }
    else {
        Write-Step "Iniciando o app desktop (Tauri)"
        Push-Location $FrontendDir
        try {
            & npm run tauri dev
        }
        finally {
            Pop-Location
        }
    }
}
finally {
    Stop-Children
    if ((Get-Location).Path -ne $PSScriptRoot) { Pop-Location -ErrorAction SilentlyContinue }
}
