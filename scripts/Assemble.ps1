$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$manifest = Get-Content -LiteralPath (Join-Path $base 'SHA256SUMS.json') -Raw | ConvertFrom-Json
foreach ($item in $manifest.assets) {
    $path = Join-Path $base $item.name
    if (-not (Test-Path -LiteralPath $path)) { throw ('Missing download: ' + $item.name) }
    Write-Host ('Checking ' + $item.name)
    if ((Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() -ne $item.sha256) { throw ('Checksum mismatch: ' + $item.name) }
}
$target = Join-Path $base 'InvestLab'
if (Test-Path -LiteralPath $target) { throw 'InvestLab already exists. Use a new folder to protect your data.' }
$stage = Join-Path $base ('assemble-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $stage | Out-Null
Expand-Archive -LiteralPath (Join-Path $base 'InvestLab-program.zip') -DestinationPath $stage
$modelDir = Join-Path $stage 'InvestLab/models'
$modelPath = Join-Path $modelDir $manifest.model.name
$stream = [IO.File]::Create($modelPath)
try {
    foreach ($part in $manifest.model.parts) {
        $inputStream = [IO.File]::OpenRead((Join-Path $base $part))
        try { $inputStream.CopyTo($stream) } finally { $inputStream.Dispose() }
    }
} finally { $stream.Dispose() }
if ((Get-FileHash -LiteralPath $modelPath -Algorithm SHA256).Hash.ToLower() -ne $manifest.model.sha256) { throw 'Combined model checksum mismatch.' }
$resolvedBase = [IO.Path]::GetFullPath($base).TrimEnd('\') + '\'
$source = [IO.Path]::GetFullPath((Join-Path $stage 'InvestLab'))
$destination = [IO.Path]::GetFullPath($target)
if (-not $source.StartsWith($resolvedBase,[StringComparison]::OrdinalIgnoreCase) -or -not $destination.StartsWith($resolvedBase,[StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid output path.' }
Move-Item -LiteralPath $source -Destination $destination
Write-Host 'Complete. Open InvestLab/InvestLab.exe.'
