param(
    [string]$Python = "python",
    [string]$Version = "3.0.0-alpha.1",
    [string]$DataPackSource = "",
    [switch]$SkipWebBuild,
    [switch]$SkipInstaller,
    [switch]$SkipExeSmoke
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$distRoot = Join-Path $root "dist"
$releaseRoot = Join-Path $root "release"
$portableRoot = Join-Path $distRoot "AnimaPromptStudioV3"

if (-not $DataPackSource) {
    $DataPackSource = Join-Path $root "v3\.local\packs\anima-v3-dso-0636f762-r1"
}
$resolvedPack = (Resolve-Path -LiteralPath $DataPackSource).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedPack "data-pack.json"))) {
    throw "Data pack manifest not found: $resolvedPack"
}

New-Item -ItemType Directory -Force $releaseRoot | Out-Null
if (Test-Path -LiteralPath $portableRoot) {
    $resolvedPortable = (Resolve-Path -LiteralPath $portableRoot).Path
    if (-not $resolvedPortable.StartsWith($distRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to clean a portable directory outside dist: $resolvedPortable"
    }
    Remove-Item -LiteralPath $resolvedPortable -Recurse -Force
}

Push-Location $root
try {
    if (-not $SkipWebBuild) {
        Push-Location (Join-Path $root "v3\web")
        try {
            & npm ci
            if ($LASTEXITCODE -ne 0) { throw "V3 web dependency install failed." }
            & npm run build
            if ($LASTEXITCODE -ne 0) { throw "V3 web build failed." }
        } finally {
            Pop-Location
        }
    }

    $env:ANIMA_V3_PACK_SOURCE = $resolvedPack
    & $Python -m PyInstaller --noconfirm --clean (Join-Path $root "packaging\anima_prompt_studio_v3.spec")
    if ($LASTEXITCODE -ne 0) { throw "V3 PyInstaller build failed." }

    if (-not $SkipExeSmoke) {
        $smokeRoot = Join-Path $root ("v3\.local\packaged-exe-smoke\" + (Split-Path -Leaf $resolvedPack))
        $smokeData = Join-Path $smokeRoot "data"
        $smokeWorkspace = Join-Path $smokeRoot "workspaces.db"
        $smokeArgs = @(
            "--data-root", $smokeData,
            "--workspace-db", $smokeWorkspace,
            "--without-v2", "--no-browser", "--exit-after-startup"
        )
        & (Join-Path $portableRoot "AnimaPromptStudioV3.exe") @smokeArgs
        if ($LASTEXITCODE -ne 0) { throw "Packaged V3 executable first-start smoke test failed." }

        $state = Get-Content -LiteralPath (Join-Path $smokeData "active.json") -Raw | ConvertFrom-Json
        $installedReference = Join-Path $smokeData ("packs\" + $state.active_pack_id + "\reference.db")
        $stateHash = (Get-FileHash -LiteralPath (Join-Path $smokeData "active.json") -Algorithm SHA256).Hash
        $referenceHash = (Get-FileHash -LiteralPath $installedReference -Algorithm SHA256).Hash

        & (Join-Path $portableRoot "AnimaPromptStudioV3.exe") @smokeArgs
        if ($LASTEXITCODE -ne 0) { throw "Packaged V3 executable upgrade smoke test failed." }
        if ((Get-FileHash -LiteralPath (Join-Path $smokeData "active.json") -Algorithm SHA256).Hash -ne $stateHash) {
            throw "Upgrade smoke changed the active data-pack pointer."
        }
        if ((Get-FileHash -LiteralPath $installedReference -Algorithm SHA256).Hash -ne $referenceHash) {
            throw "Upgrade smoke changed the installed reference database."
        }
    }

    $portableZip = Join-Path $releaseRoot "ANIMA-Prompt-Studio-V3-Portable-v$Version.zip"
    if (Test-Path -LiteralPath $portableZip) { Remove-Item -LiteralPath $portableZip -Force }
    Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $portableZip -CompressionLevel Optimal

    if (-not $SkipInstaller) {
        $iscc = @(
            (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if ($iscc) {
            & $iscc "/DAppVersion=$Version" (Join-Path $root "packaging\installer_v3.iss")
            if ($LASTEXITCODE -ne 0) { throw "V3 Inno Setup build failed." }
        } else {
            Write-Warning "Inno Setup was not found; the V3 portable package was created."
        }
    }
} finally {
    Remove-Item Env:ANIMA_V3_PACK_SOURCE -ErrorAction SilentlyContinue
    Pop-Location
}

Get-ChildItem -LiteralPath $releaseRoot -File | Where-Object { $_.Name -like "*V3*" } | Select-Object Name,Length
