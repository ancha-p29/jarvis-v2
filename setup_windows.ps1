# JARVIS one-shot Windows setup.
#
# This script installs everything JARVIS needs and gets it talking:
#   1. Ollama (the local AI brain) + the llama3.1:8b model (~4.7 GB, one time)
#   2. Python 3.12 (if you don't have Python 3.10+ already)
#   3. A project virtual environment + all Python packages
#   4. The JARVIS voice (~60 MB, one time)
#   5. Runs the JARVIS environment check
#
# HOW TO RUN (from the folder where you extracted the JARVIS zip):
#   powershell -ExecutionPolicy Bypass -File setup_windows.ps1
#
# Total download is roughly 5.5 GB, so run it on Wi-Fi and let it work.
# You only ever run this once.

$ErrorActionPreference = "Stop"

function Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}
function Ok($msg) {
    Write-Host "  [ok] $msg" -ForegroundColor Green
}
function Fail($msg) {
    Write-Host "  [!!] $msg" -ForegroundColor Red
    throw $msg
}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
Step "JARVIS setup starting in $ProjectRoot"

# --- 1. winget -------------------------------------------------------------
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Fail "winget not found. Install 'App Installer' from the Microsoft Store, then re-run this script."
}
Ok "winget found"

# --- 2. Ollama -------------------------------------------------------------
function Find-Ollama {
    $c = Get-Command ollama -ErrorAction SilentlyContinue
    if ($c) { return $c.Source }
    $p = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
    if (Test-Path $p) { return $p }
    return $null
}

$ollama = Find-Ollama
if (-not $ollama) {
    Step "Installing Ollama (the local AI brain)"
    winget install -e --id Ollama.Ollama --silent `
        --accept-package-agreements --accept-source-agreements
    $ollama = Find-Ollama
}
if (-not $ollama) {
    Fail "Ollama installed but ollama.exe was not found. Close this window, open a NEW PowerShell, and re-run the script."
}
Ok "Ollama at $ollama"

# Make sure the Ollama server is running (the Windows installer usually starts it).
$ollamaUp = $false
try {
    Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 5 | Out-Null
    $ollamaUp = $true
} catch { $ollamaUp = $false }
if (-not $ollamaUp) {
    Step "Starting the Ollama server"
    $app = Join-Path (Split-Path $ollama -Parent) "ollama app.exe"
    if (Test-Path $app) { Start-Process $app } else { Start-Process $ollama -ArgumentList "serve" -WindowStyle Hidden }
    Start-Sleep -Seconds 10
    try {
        Invoke-RestMethod -Uri "http://localhost:11434/api/tags" -TimeoutSec 10 | Out-Null
        $ollamaUp = $true
    } catch { $ollamaUp = $false }
}
if (-not $ollamaUp) { Fail "Could not reach Ollama at http://localhost:11434. Start the Ollama app from the Start menu, then re-run this script." }
Ok "Ollama server is running"

# --- 3. Pull the model (one time, ~4.7 GB) ----------------------------------
Step "Downloading the AI model (llama3.1:8b, ~4.7 GB, one time). Grab a coffee."
& $ollama pull llama3.1:8b
if ($LASTEXITCODE -ne 0) { Fail "ollama pull failed. Check your internet connection and re-run the script." }
Ok "AI model ready"

# --- 4. Python 3.10+ ---------------------------------------------------------
function Find-Python {
    foreach ($cmd in @("python", "py")) {
        $c = Get-Command $cmd -ErrorAction SilentlyContinue
        if ($c) {
            try {
                $v = & $c.Source --version 2>&1
                if ($v -match "Python 3\.(\d+)") {
                    if ([int]$Matches[1] -ge 10) { return $c.Source }
                }
            } catch { }
        }
    }
    $cand = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path $cand) { return $cand }
    return $null
}

$python = Find-Python
if (-not $python) {
    Step "Installing Python 3.12"
    winget install -e --id Python.Python.3.12 --silent `
        --accept-package-agreements --accept-source-agreements
    $python = Find-Python
}
if (-not $python) {
    Fail "Python 3.10+ not found after install. Close this window, open a NEW PowerShell, and re-run the script."
}
Ok "Python: $(& $python --version)"

# --- 5. Virtual environment + packages ---------------------------------------
Step "Creating the JARVIS virtual environment and installing packages (a few minutes)"
if (-not (Test-Path ".\venv")) {
    & $python -m venv venv
}
$venvPy = Join-Path $ProjectRoot "venv\Scripts\python.exe"
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install pyyaml -r requirements.txt
if ($LASTEXITCODE -ne 0) { Fail "pip install failed. Re-run the script; if it keeps failing, send me the red error text." }
Ok "Python packages installed"

# --- 6. JARVIS voice (one time, ~60 MB) ---------------------------------------
Step "Downloading the JARVIS voice (~60 MB)"
$voicesDir = Join-Path $ProjectRoot "data\voices"
New-Item -ItemType Directory -Force -Path $voicesDir | Out-Null
$base = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium"
foreach ($ext in @(".onnx", ".onnx.json")) {
    $dest = Join-Path $voicesDir "en_US-lessac-medium$ext"
    if (-not (Test-Path $dest)) {
        Invoke-WebRequest -Uri "$base$ext" -OutFile $dest -UseBasicParsing
    }
    Ok (Split-Path $dest -Leaf)
}

# --- 7. Environment check ------------------------------------------------------
Step "Running the JARVIS environment check"
& $venvPy main.py --check

Write-Host ""
Write-Host "================================================================" -ForegroundColor Green
Write-Host "  JARVIS is ready, sir." -ForegroundColor Green
Write-Host "================================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Talk to JARVIS in text mode (works right now, no mic needed):"
Write-Host "  .\venv\Scripts\python main.py --text"
Write-Host ""
Write-Host "Full voice mode (once the check above is all green):"
Write-Host "  .\venv\Scripts\python main.py"
Write-Host "Then say: hey jarvis"
Write-Host ""
Write-Host "Note: the very first voice run downloads the speech-recognition"
Write-Host "model (~460 MB, one time). After that, everything runs offline."

# JARVIS v2 note: core install is just "pip install pyyaml".
# Phone/watcher/sim modes need no audio packages. See PLAYBOOK.md Phase 3 for Twilio.
