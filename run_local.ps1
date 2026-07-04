# run_local.ps1 - set up (first run) and launch the Literature Research Aide on this PC.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\run_local.ps1
#
# First run creates a virtual environment and installs all dependencies
# (a large download: torch + sentence-transformers + faiss, possibly ~2 GB).
# Later runs skip the install and just start the server.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# --- 1. Find a real Python interpreter (the py launcher avoids the Store stub) ---
$pyExe = $null
$pyArgs = @()
if (Get-Command py -ErrorAction SilentlyContinue) {
    $pyExe = "py"
    $pyArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $ver = (& python --version) 2>&1
    if ($ver -match "Python 3") { $pyExe = "python"; $pyArgs = @() }
}
if (-not $pyExe) {
    Write-Host "ERROR: No real Python found. Install Python 3.11 from python.org" -ForegroundColor Red
    Write-Host "       and tick 'Add python.exe to PATH', then re-run this script." -ForegroundColor Red
    exit 1
}

# --- 2. Create the virtual environment on first run ---
$venvPy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Creating virtual environment (.venv)..." -ForegroundColor Cyan
    & $pyExe @pyArgs -m venv .venv
}

# --- 3. Install dependencies once (sentinel file marks completion) ---
$depsMarker = Join-Path $PSScriptRoot ".venv\.deps_installed"
if (-not (Test-Path $depsMarker)) {
    Write-Host "Installing dependencies. This is a large one-time download..." -ForegroundColor Cyan
    & $venvPy -m pip install --upgrade pip
    # CPU-only PyTorch first (smaller than the default GPU build).
    & $venvPy -m pip install torch --index-url https://download.pytorch.org/whl/cpu
    & $venvPy -m pip install -r requirements.txt
    New-Item -ItemType File -Path $depsMarker | Out-Null
    Write-Host "Dependencies installed." -ForegroundColor Green
}

# --- 4. Configuration ---
# SECRET_KEY signs the login tokens. Generate once and reuse it across runs
# (a new key every restart would invalidate everyone's session). DEBUG=true
# keeps auth cookies non-Secure so they work over plain http://localhost.
if (-not $env:SECRET_KEY) {
    $keyFile = Join-Path $PSScriptRoot ".venv\.secret_key"
    if (-not (Test-Path $keyFile)) {
        $buf = New-Object byte[] 48
        [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
        [Convert]::ToBase64String($buf) | Set-Content -Path $keyFile -NoNewline -Encoding ascii
    }
    $env:SECRET_KEY = (Get-Content -Path $keyFile -Raw).Trim()
}
$env:DEBUG = "true"

$bind = if ($env:HOST_LAN -eq "1") { "0.0.0.0" } else { "127.0.0.1" }
$port = if ($env:PORT) { $env:PORT } else { "7860" }

Write-Host ""
Write-Host "Starting server at http://localhost:$port" -ForegroundColor Green
Write-Host "Press Ctrl-C in this window to stop the server." -ForegroundColor Green
if ($bind -eq "0.0.0.0") {
    Write-Host "LAN access on. Other devices can reach it at http://YOUR-PC-IP:$port" -ForegroundColor Yellow
}
Write-Host ""

# --- 5. Run the app ---
& $venvPy -m uvicorn main:app --host $bind --port $port
