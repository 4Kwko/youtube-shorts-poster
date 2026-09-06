<# Builds a Windows executable for this checkout. Python/FFmpeg remain prerequisites. #>
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location (Join-Path $projectRoot 'frontend')
try {
    & npm ci
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
    & npm run tauri -- build --no-bundle
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    Copy-Item 'src-tauri\target\release\clipper-desktop.exe' (Join-Path $projectRoot 'Clipper.exe')
    Write-Host 'Built Clipper.exe. Keep it beside backend/ and .venv/.'
} finally { Pop-Location }
