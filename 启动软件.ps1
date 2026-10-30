$ErrorActionPreference = 'Stop'
$projectFolder = $PSScriptRoot
$portable = Join-Path $projectFolder 'output\embedded\InvestLab\InvestLab.exe'
if (Test-Path -LiteralPath $portable) {
    Start-Process -FilePath $portable -WorkingDirectory (Split-Path $portable) -WindowStyle Normal
    exit
}
$localPython = Join-Path $projectFolder '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $localPython)) { throw 'Download the portable desktop package, extract it and open InvestLab.exe.' }
Start-Process -FilePath $localPython -ArgumentList ('"' + (Join-Path $projectFolder 'desktop.py') + '"') -WorkingDirectory $projectFolder -WindowStyle Normal
