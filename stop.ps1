# Stop the voice-chat servers (Style-Bert-VITS2 + the web app).
# Ollama keeps running in the background (leave it; it idles cheaply).
#
# Run:  powershell -ExecutionPolicy Bypass -File stop.ps1

$stopped = 0
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    # Match only OUR scripts. Require a space or backslash right before the name so a bare
    # "*server.py*" glob doesn't also kill unrelated tools like VSCode's lsp_server.py.
    Where-Object { $_.CommandLine -match 'server_fastapi\.py' -or $_.CommandLine -match '[\\ ]server\.py($|\s)' } |
    ForEach-Object {
        Write-Host "Stopping PID $($_.ProcessId)  ($($_.CommandLine))" -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        $stopped++
    }
if ($stopped -eq 0) { Write-Host "No voice-chat servers were running." -ForegroundColor DarkGray }
else { Write-Host "Stopped $stopped server process(es)." -ForegroundColor Green }

# Also unload any LLM that Ollama is keeping in the GPU's VRAM, so the graphics
# card is free again (e.g. for games). Ollama itself keeps running in the tray.
$ollama = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
if (Test-Path $ollama) {
    try {
        & $ollama ps 2>$null | Select-Object -Skip 1 | ForEach-Object {
            $name = ($_ -split '\s{2,}')[0].Trim()
            if ($name) { & $ollama stop $name 2>$null; Write-Host "Freed VRAM (unloaded $name)." -ForegroundColor Green }
        }
    } catch {}
}
Write-Host "Done. Servers off and GPU freed." -ForegroundColor Cyan
