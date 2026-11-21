$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$wheelDirectory = Join-Path $projectRoot '.qa\android-wheels'
New-Item -ItemType Directory -Path $wheelDirectory -Force | Out-Null
$buildPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$requirements = Join-Path $projectRoot 'client\requirements-android-build.txt'
& $buildPython -m pip download --index-url 'https://pypi.org/simple' --only-binary ':all:' --no-deps --dest $wheelDirectory -r $requirements
if ($LASTEXITCODE -ne 0) { throw 'Не удалось подготовить Python-зависимости Android.' }

# Official Flet Android wheels. Hashes are from https://pypi.flet.dev/msgpack/.
# Download using Windows HTTP here to avoid TLS handshake hangs in the packager.
$nativeWheels = @(
    @{Architecture='arm64_v8a'; VersionPath='ver_e8CbQ'; Hash='bca8335b228992380589f6a93048b051110695078952f5718d01aa685e0fc7f7'},
    @{Architecture='armeabi_v7a'; VersionPath='ver_NOCSl'; Hash='90d3df9efbbcfa0deb0f282689548c34776719c2bbe147e8415d6c14c63bfa64'},
    @{Architecture='x86_64'; VersionPath='ver_350O6'; Hash='2a11143fa92377c25e10f7f9e9e8ceee33c1b309f62f009489dbdab81f5c48d7'},
    @{Architecture='x86'; VersionPath='ver_1Qq7zp'; Hash='9e843e896b04b373f22288e69677021215b657411de2c40db921cd9c2c793251'}
)
foreach ($wheel in $nativeWheels) {
    $fileName = "msgpack-1.1.2-1-cp312-cp312-android_24_$($wheel.Architecture).whl"
    $targetPath = Join-Path $wheelDirectory $fileName
    if (-not (Test-Path -LiteralPath $targetPath)) {
        Invoke-WebRequest -Uri "https://pypi.flet.dev/-/$($wheel.VersionPath)/$fileName" -OutFile $targetPath -TimeoutSec 60
    }
    if ((Get-FileHash -LiteralPath $targetPath -Algorithm SHA256).Hash.ToLowerInvariant() -ne $wheel.Hash) {
        throw "Контрольная сумма не совпадает: $fileName"
    }
}
Write-Output "Android wheels готовы: $wheelDirectory"
