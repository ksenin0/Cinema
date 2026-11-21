param([switch]$VerboseBuild)
$ErrorActionPreference = 'Stop'
$projectRoot = $PSScriptRoot
$buildTool = Join-Path $projectRoot '.venv\Scripts\flet.exe'
$javaTempPath = Join-Path $projectRoot '.qa\java-temp'
New-Item -ItemType Directory -Path $javaTempPath -Force | Out-Null
$previousLocation = Get-Location
$previousJavaOptions = $env:JAVA_TOOL_OPTIONS
$previousJavaHome = $env:JAVA_HOME
$previousNoIndex = $env:PIP_NO_INDEX
$previousFindLinks = $env:PIP_FIND_LINKS
$previousUserProfile = $env:USERPROFILE
$previousPubCache = $env:PUB_CACHE
try {
    $env:PUB_CACHE = Join-Path $projectRoot '.qa\pub-cache'
    # Java Properties reads Flutter's local.properties as Latin-1. Use the same
    # Windows profile through its ASCII short path for this child build only.
    $shortProfile = (New-Object -ComObject Scripting.FileSystemObject).GetFolder($env:USERPROFILE).ShortPath
    if ($shortProfile -notmatch '[^\x00-\x7F]') { $env:USERPROFILE = $shortProfile }
    & (Join-Path $projectRoot 'tools\prepare-android-wheels.ps1')
    $env:PIP_NO_INDEX = '1'
    $env:PIP_FIND_LINKS = Join-Path $projectRoot '.qa\android-wheels'
    $javaCompiler = Get-Command javac -ErrorAction SilentlyContinue
    if ($javaCompiler -and -not (Test-Path -LiteralPath "$env:JAVA_HOME\bin\javac.exe")) {
        $env:JAVA_HOME = Split-Path (Split-Path $javaCompiler.Source -Parent) -Parent
    }
    $env:JAVA_TOOL_OPTIONS = "$previousJavaOptions -Djava.io.tmpdir=`"$javaTempPath`" -Djdk.net.unixdomain.tmpdir=`"$javaTempPath`""
    Set-Location -LiteralPath (Join-Path $projectRoot 'client')
    if ($VerboseBuild) {
        & $buildTool build apk --yes --verbose
    } else {
        & $buildTool build apk --yes
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Сборка APK не завершена. Посмотрите сообщение Flet выше.'
    }
    $apkSource = Join-Path $projectRoot 'client\build\apk\cinema-client.apk'
    $distributionDirectory = Join-Path $projectRoot 'dist'
    if (-not (Test-Path -LiteralPath $apkSource)) { throw 'Flet не создал ожидаемый APK.' }
    New-Item -ItemType Directory -Path $distributionDirectory -Force | Out-Null
    Copy-Item -LiteralPath $apkSource -Destination (Join-Path $distributionDirectory 'cinema.apk') -Force
    Write-Output "Готовый APK: $(Join-Path $distributionDirectory 'cinema.apk')"
} finally {
    Set-Location -LiteralPath $previousLocation.Path
    $env:JAVA_TOOL_OPTIONS = $previousJavaOptions
    $env:JAVA_HOME = $previousJavaHome
    $env:PIP_NO_INDEX = $previousNoIndex
    $env:PIP_FIND_LINKS = $previousFindLinks
    $env:USERPROFILE = $previousUserProfile
    $env:PUB_CACHE = $previousPubCache
}
