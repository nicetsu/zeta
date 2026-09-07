# Launch everything for the voice-chat AI in one click.
#   1) Ollama runs as a Windows background service automatically.
#   2) Start the Style-Bert-VITS2 API server (the "voice", port 5000).
#   3) Start our web server (what the iPad/browser connects to, port 8443).
#
# Run:  powershell -ExecutionPolicy Bypass -File start.ps1

$ErrorActionPreference = "Stop"

# --- paths (relative to this script, so renaming/moving the folder can't break them) ---
$APP_DIR     = $PSScriptRoot
$SBV2_DIR    = "$APP_DIR\Style-Bert-VITS2"
$SBV2_PYTHON = "$SBV2_DIR\venv\Scripts\python.exe"   # SBV2's own venv (Python 3.11)

# --- environment (all required; discovered during setup) ---
$env:OLLAMA_MODELS   = "$APP_DIR\ollama_models"  # keep models off the full C: drive
$env:HF_HOME         = "$APP_DIR\hf_cache"       # whisper + bert caches
$env:NLTK_DATA       = "$APP_DIR\nltk_data"      # English g2p data
$env:PYTHONUTF8      = "1"                                    # avoid cp874 console crashes
$env:PYTHONIOENCODING = "utf-8"

# GPU tuning for Ollama: halve the KV cache (q8_0, ~no quality loss) + flash attention so the
# whole 8B Q4 model + 4096 ctx fits in 6GB VRAM at 100% GPU. NOTE: the Ollama *tray app* ignores
# these env vars (it always serves from C: with defaults), so start.ps1 runs `ollama serve` itself
# below with this env instead of relying on the tray app.
$env:OLLAMA_FLASH_ATTENTION = "1"
$env:OLLAMA_KV_CACHE_TYPE   = "q8_0"
$env:OLLAMA_KEEP_ALIVE      = "30m"

Write-Host "[1/3] Starting Ollama server (D: models, q8_0 KV cache, full GPU)..." -ForegroundColor Cyan
$OLLAMA_EXE = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
# The tray app may already be running a server bound to C: (no models). Replace it with our own
# `ollama serve` that inherits the env above, so models load from D: at 100% GPU.
Stop-Process -Name "ollama app","ollama" -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-Process -FilePath $OLLAMA_EXE -ArgumentList "serve" -WindowStyle Hidden
do {
    Start-Sleep -Seconds 2
    try { $up = (Invoke-WebRequest "http://127.0.0.1:11434/api/tags" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { $up = $false }
} until ($up)
Write-Host "Ollama is up (models from D:)." -ForegroundColor Green

Write-Host "[2/3] Starting Style-Bert-VITS2 voice server (port 5000)..." -ForegroundColor Cyan
Start-Process -FilePath $SBV2_PYTHON -ArgumentList "server_fastapi.py" -WorkingDirectory $SBV2_DIR

Write-Host "Waiting for the voice server to load (BERT + model)..." -ForegroundColor DarkGray
do {
    Start-Sleep -Seconds 3
    try { $up = (Invoke-WebRequest "http://127.0.0.1:5000/docs" -UseBasicParsing -TimeoutSec 3).StatusCode -eq 200 }
    catch { $up = $false }
} until ($up)
Write-Host "Voice server is up." -ForegroundColor Green

Write-Host "[3/3] Starting voice-chat web server (port 8443)..." -ForegroundColor Cyan
Set-Location $APP_DIR
python server.py
