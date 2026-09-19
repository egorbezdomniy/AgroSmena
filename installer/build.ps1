param(
    [string]$NsisCompiler = "",
    [switch]$SkipSmokeTest
)
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    $python = Join-Path $projectRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python)) { throw 'Create .venv and install requirements-build.txt first.' }
    $releaseVersion = (Get-Content -Raw -LiteralPath 'version.json' | ConvertFrom-Json).version
    & $python -c "import sys; from updatekit.protocol import version_key; version_key(sys.argv[1])" $releaseVersion
    if ($LASTEXITCODE -ne 0) { throw 'version.json must contain a valid SemVer.' }
    $windowsVersion = ($releaseVersion -split '[-+]', 2)[0] + '.0'
    if (-not $NsisCompiler) {
        $localCompiler = Join-Path $projectRoot '.build-tools\nsis-3.12\makensis.exe'
        if (Test-Path -LiteralPath $localCompiler) {
            $NsisCompiler = $localCompiler
        } else {
            $NsisCompiler = (Get-Command makensis.exe -ErrorAction Stop).Source
        }
    }
    New-Item -ItemType Directory -Path build -Force | Out-Null
    & $python -c "from PIL import Image, ImageOps; logo = ImageOps.contain(Image.open('assets/crm-logo.png').convert('RGBA'), (256,256), Image.Resampling.LANCZOS); icon = Image.new('RGBA', (256,256)); icon.alpha_composite(logo, ((256-logo.width)//2, (256-logo.height)//2)); icon.save('build/crm.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])"
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }
    & $python -m PyInstaller --clean --noconfirm AgroSmena.spec
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }
    & $python -m PyInstaller --noconfirm Updater.spec
    if ($LASTEXITCODE -ne 0) { throw 'Updater build failed.' }
    Copy-Item -LiteralPath 'dist\updater.exe' -Destination 'dist\AgroSmenaCRM\updater.exe'
    Copy-Item -LiteralPath 'version.json' -Destination 'dist\AgroSmenaCRM\version.json'
    if (-not $SkipSmokeTest) {
        $previousPlatform = $env:QT_QPA_PLATFORM
        try {
            $env:QT_QPA_PLATFORM = 'offscreen'
            $exe = Join-Path $projectRoot 'dist\AgroSmenaCRM\AgroSmenaCRM.exe'
            $check = Start-Process -FilePath $exe -ArgumentList '--smoke-test' -WindowStyle Hidden -PassThru
            if (-not $check.WaitForExit(30000)) { throw 'Packaged application smoke test timed out.' }
            if ($check.ExitCode -ne 0) { throw 'Packaged application smoke test failed.' }
        } finally {
            $env:QT_QPA_PLATFORM = $previousPlatform
        }
    } else {
        Write-Host 'Packaged application smoke test skipped by request.'
    }
    & $NsisCompiler "/DAPP_VERSION=$releaseVersion" "/DPRODUCT_VERSION=$windowsVersion" /INPUTCHARSET UTF8 /V3 installer\AgroSmena.nsi
    if ($LASTEXITCODE -ne 0) { throw 'Installer compilation failed.' }
    Write-Host "Ready: dist\AgroSmenaCRM-$releaseVersion-Setup.exe"
} finally {
    Pop-Location
}
