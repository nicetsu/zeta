# Stage the weights that Modal needs and push them to the "zeta-models" Volume.
#
# Only ~1.1 GB is uploaded from here. The 4.9 GB Lumimaid GGUF is NOT uploaded -
# `modal run modal_app.py::warm` makes Modal pull it straight from HuggingFace at
# datacenter speed, which is far faster than pushing it over a home connection.
#
# What goes up:
#   bert/          EN DeBERTa weights for SBV2  (~885 MB, .bin excluded - it is the
#                  same tensors as model.safetensors, which is the one torch<2.6 loads)
#   model_assets/  the Vestia Zeta voice        (~190 MB)
#   nltk_data/     English g2p data             (~13 MB)
#
# Run:  powershell -ExecutionPolicy Bypass -File prepare_upload.ps1
#
# -StageOnly builds and verifies the staging folder but skips the upload, so the slow
# local copy can be done before you have logged in with `modal setup`.

param([switch]$StageOnly)

$ErrorActionPreference = "Stop"

$ROOT  = $PSScriptRoot
$SBV2  = "$ROOT\Style-Bert-VITS2"
$STAGE = "$ROOT\.upload"
$VOLUME = "zeta-models"

# `modal` may be installed as a console script or only as `python -m modal`.
# NOTE: don't try to splat a sub-range like $a[1..($a.Count-1)] - when the array has a
# single element PowerShell evaluates 1..0 as @(1,0) and silently mangles the arguments.
$MODAL_EXE = $null
$MODAL_PRE = @()
if (Get-Command modal -ErrorAction SilentlyContinue) {
    $MODAL_EXE = "modal"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $MODAL_EXE = "python"; $MODAL_PRE = @("-m", "modal")
}

if (-not $StageOnly -and -not $MODAL_EXE) {
    throw "The 'modal' CLI was not found. Run:  pip install modal  &&  modal setup"
}

function Invoke-Modal {
    param([Parameter(ValueFromRemainingArguments = $true)] [string[]]$ModalArgs)
    & $MODAL_EXE @($MODAL_PRE + $ModalArgs)
}

Write-Host "[1/4] Building staging folder..." -ForegroundColor Cyan
if (Test-Path $STAGE) { Remove-Item -Recurse -Force $STAGE }
New-Item -ItemType Directory -Path $STAGE | Out-Null

# --- bert/ : copy everything EXCEPT the redundant .bin and the HF .cache dir ---
Write-Host "      bert/ (excluding pytorch_model.bin, ~874 MB saved)" -ForegroundColor DarkGray
robocopy "$SBV2\bert" "$STAGE\bert" /E /XF "pytorch_model.bin" /XD ".cache" /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed on bert/ (exit $LASTEXITCODE)" }

# --- model_assets/ : the voice ---
Write-Host "      model_assets/" -ForegroundColor DarkGray
robocopy "$SBV2\model_assets" "$STAGE\model_assets" /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed on model_assets/ (exit $LASTEXITCODE)" }

# --- nltk_data/ ---
Write-Host "      nltk_data/" -ForegroundColor DarkGray
robocopy "$ROOT\nltk_data" "$STAGE\nltk_data" /E /NFL /NDL /NJH /NJS | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed on nltk_data/ (exit $LASTEXITCODE)" }

$size = [math]::Round(((Get-ChildItem $STAGE -Recurse -File | Measure-Object Length -Sum).Sum / 1GB), 2)
Write-Host "      staged $size GB in $STAGE" -ForegroundColor Green

Write-Host "[2/4] Sanity check..." -ForegroundColor Cyan
$must = @(
    "$STAGE\bert\deberta-v3-large\model.safetensors",
    "$STAGE\bert\bert_models.json",
    "$STAGE\model_assets\SBV2_HoloIDFlu\SBV2_HoloIDFlu.safetensors",
    "$STAGE\model_assets\SBV2_HoloIDFlu\config.json",
    "$STAGE\model_assets\SBV2_HoloIDFlu\style_vectors.npy"
)
foreach ($f in $must) {
    if (-not (Test-Path $f)) { throw "missing expected file: $f" }
}
Write-Host "      all expected files present." -ForegroundColor Green

if ($StageOnly) {
    Write-Host ""
    Write-Host "Staged only (-StageOnly). Nothing was uploaded." -ForegroundColor Yellow
    Write-Host "After 'modal setup', re-run without the flag to upload:" -ForegroundColor Cyan
    Write-Host "  powershell -ExecutionPolicy Bypass -File prepare_upload.ps1" -ForegroundColor Cyan
    exit 0
}

Write-Host "[3/4] Creating the Volume (no-op if it already exists)..." -ForegroundColor Cyan
try { Invoke-Modal volume create $VOLUME | Out-Null } catch { }

Write-Host "[4/4] Uploading (~1.1 GB, this is the slow part)..." -ForegroundColor Cyan
foreach ($d in @("bert", "model_assets", "nltk_data")) {
    Write-Host "      -> $d/" -ForegroundColor DarkGray
    Invoke-Modal volume put $VOLUME "$STAGE\$d" "/$d"
    if ($LASTEXITCODE -ne 0) { throw "upload of $d failed" }
}

Write-Host ""
Write-Host "Done. Volume contents:" -ForegroundColor Green
Invoke-Modal volume ls $VOLUME
Write-Host ""
Write-Host "Next:  modal run modal_app.py::warm     # pulls the 4.9 GB LLM (once)" -ForegroundColor Cyan
Write-Host "Then:  modal serve modal_app.py         # test with a temporary URL" -ForegroundColor Cyan
