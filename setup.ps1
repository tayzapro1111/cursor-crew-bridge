#Requires -Version 5.1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) {
    throw "Python is not on PATH. Install Python 3.11+ and tick Add python.exe to PATH."
}

$VenvPy = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    Write-Host "Creating .venv ..."
    python -m venv .venv
}

Write-Host "Installing cursor-crew-bridge ..."
& $VenvPy -m pip install -U pip
& $VenvPy -m pip install -e "."

$CursorNamed = Join-Path $env:USERPROFILE ".local\bin\cursor-agent.exe"
$CursorLocal = Join-Path $env:USERPROFILE ".local\bin\agent.exe"
$GrokAgent = Join-Path $env:USERPROFILE ".grok\bin\agent.exe"
$NeedCli = -not (Test-Path $CursorNamed)
if ((Test-Path $CursorLocal) -and ((Resolve-Path $CursorLocal).Path -ne (Resolve-Path $GrokAgent -ErrorAction SilentlyContinue).Path)) {
    $NeedCli = $false
}
if ($NeedCli) {
    Write-Host "Cursor Agent CLI not found. Installing from cursor.com ..."
    irm "https://cursor.com/install?win32=true" | iex
}

& $VenvPy -m cursor_crew_bridge.cli setup --no-install
if ($LASTEXITCODE -ne 0) {
    throw "doctor reported missing pieces. Fix the hints above, then re-run setup.ps1"
}

Write-Host ""
Write-Host "Next: double-click start-cursor-gateway.bat"
