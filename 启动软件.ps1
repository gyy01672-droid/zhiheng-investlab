$ErrorActionPreference = 'Stop'
$projectFolder = $PSScriptRoot
$localPython = Join-Path $projectFolder '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $localPython)) { throw 'Local Python is missing. See README.md.' }
$running = $false
try { $response = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 2; $running = $null -ne $response.hardware } catch {}
if (-not $running) {
    $null = New-Item -ItemType Directory -Force -Path (Join-Path $projectFolder 'logs')
    Start-Process -FilePath $localPython -ArgumentList ('"' + (Join-Path $projectFolder 'app.py') + '"') -WorkingDirectory $projectFolder -WindowStyle Hidden -RedirectStandardOutput (Join-Path $projectFolder 'logs\app-out.log') -RedirectStandardError (Join-Path $projectFolder 'logs\app-error.log')
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        try { $null = Invoke-RestMethod 'http://127.0.0.1:8765/api/status' -TimeoutSec 2; $running = $true; break } catch {}
    }
}
if (-not $running) { throw 'Startup failed. See logs/app-error.log.' }
Start-Process 'http://127.0.0.1:8765'
