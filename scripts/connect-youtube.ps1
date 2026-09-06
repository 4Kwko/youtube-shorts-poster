param([Parameter(Mandatory=$true)][string]$ClientJson)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    & '.\.venv\Scripts\python.exe' -m app.cli.youtube connect $ClientJson
    if ($LASTEXITCODE -ne 0) { throw 'YouTube connection failed' }
} finally { Pop-Location }
