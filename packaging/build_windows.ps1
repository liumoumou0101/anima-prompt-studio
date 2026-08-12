param(
    [string]$Python = "python",
    [string]$Version = "2.0.0"
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$distRoot = Join-Path $root "dist"
$releaseRoot = Join-Path $root "release"
$portableRoot = Join-Path $distRoot "AnimaPromptStudio"

New-Item -ItemType Directory -Force $releaseRoot | Out-Null
if (Test-Path $portableRoot) { Remove-Item -LiteralPath $portableRoot -Recurse -Force }
Get-ChildItem -LiteralPath $releaseRoot -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force

Push-Location $root
try {
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $root "packaging\anima_prompt_studio.spec")
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed." }

    $portableZip = Join-Path $releaseRoot "ANIMA-Prompt-Studio-Portable-v$Version.zip"
    Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $portableZip -CompressionLevel Optimal

    $iscc = @(
        (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
        "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        "C:\Program Files\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
    if ($iscc) {
        & $iscc (Join-Path $root "packaging\installer.iss")
        if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed." }
    } else {
        Write-Warning "Inno Setup was not found; the portable package was created. GitHub Actions will create the installer."
    }
} finally {
    Pop-Location
}

Get-ChildItem -LiteralPath $releaseRoot -File | Select-Object Name,Length
