param([switch]$Web, [string]$ApiUrl = 'http://127.0.0.1:8000/api/v1/')
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$clientPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$clientEntry = Join-Path $projectRoot 'client\src\main.py'
if (-not (Test-Path -LiteralPath $clientPython)) {
    throw 'Сначала установите зависимости по инструкции в README.md.'
}
$env:CINEMA_API_URL = $ApiUrl
if ($Web) {
    & $clientPython $clientEntry --web
} else {
    & $clientPython $clientEntry
}
