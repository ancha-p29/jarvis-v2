# JARVIS v2 one-shot Windows setup.
#
# What it does:
#   1. Checks for Python 3.10+ (installs via winget if missing)
#   2. Creates a virtual environment and installs pyyaml (the only
#      core dependency - the brain is a cloud API client now, no
#      Ollama, no 5 GB model download)
#   3. Tells you how to set your free Groq API key
#   4. Runs the environment check
#
# HOW TO RUN (in the cloned jarvis-v2 folder):
#   powershell -ExecutionPolicy Bypass -File setup_windows.ps1

$ErrorActionPreference = "Stop"
function Step($m) { Write-Host "`n== $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "[ok] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[!!] $m" -ForegroundColor Red; exit 1 }

Step "Checking Python"
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Step "Installing Python 3.12 via winget"
    winget install -e --id Python.Python.3.12 --silent --accept-source-agreements --accept-package-agreements
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { Fail "Python installed but not on PATH. Open a NEW PowerShell and re-run this script." }
}
& python -c "import sys; assert sys.version_info >= (3,10), sys.version" 
if ($LASTEXITCODE -ne 0) { Fail "Python 3.10+ is required." }
Ok "Python found"

Step "Creating virtual environment and installing the core dependency"
& python -m venv .venv
& .\.venv\Scripts\python -m pip install --upgrade pip | Out-Null
& .\.venv\Scripts\pip install pyyaml
Ok "Core installed (pyyaml only)"

Step "Brain API key"
if ($env:GROQ_API_KEY) {
    Ok "GROQ_API_KEY is already set"
} else {
    Write-Host "The brain uses fast open-source models hosted by Groq (free key)."
    Write-Host "1. Get a free key at https://console.groq.com/keys"
    Write-Host "2. In THIS PowerShell, run:  `$env:GROQ_API_KEY = 'your-key-here'"
    Write-Host "   Or set it permanently:    [Environment]::SetEnvironmentVariable('GROQ_API_KEY','your-key-here','User')"
    Write-Host "Alternatives if you prefer: SARVAM_API_KEY, OPENROUTER_API_KEY, TOGETHER_API_KEY, HF_TOKEN."
}

Step "Environment check"
& .\.venv\Scripts\python main.py --check

Write-Host "`nDone. Try a simulated phone call:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\python main.py --phone-sim"
