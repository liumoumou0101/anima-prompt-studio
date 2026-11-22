param(
    [string]$Python = "python",
    [ValidatePattern('^\d+\.\d+\.\d+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?(?:\+[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$')]
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
$expectedPortable = [IO.Path]::GetFullPath($portableRoot)

if (-not $DataPackSource) {
    $DataPackSource = Join-Path $root "v3\.local\packs\anima-v3-dso-0636f762-r1"
}
$resolvedPack = (Resolve-Path -LiteralPath $DataPackSource).Path
if (-not (Test-Path -LiteralPath (Join-Path $resolvedPack "data-pack.json"))) {
    throw "Data pack manifest not found: $resolvedPack"
}

foreach ($outputRoot in @($distRoot, $releaseRoot)) {
    if ((Test-Path -LiteralPath $outputRoot) -and
        ((Get-Item -LiteralPath $outputRoot -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to build through a redirected output directory: $outputRoot"
    }
}
New-Item -ItemType Directory -Force $releaseRoot | Out-Null
if (Test-Path -LiteralPath $portableRoot) {
    $resolvedPortable = (Resolve-Path -LiteralPath $portableRoot).ProviderPath
    $resolvedParent = [IO.Directory]::GetParent($resolvedPortable).FullName
    if (-not [string]::Equals($resolvedPortable, $expectedPortable, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not [string]::Equals($resolvedParent, $distRoot, [System.StringComparison]::OrdinalIgnoreCase) -or
        ((Get-Item -LiteralPath $resolvedPortable -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw "Refusing to clean anything except the exact portable directory: $resolvedPortable"
    }
    $redirectedChild = Get-ChildItem -LiteralPath $resolvedPortable -Force -Recurse |
        Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } | Select-Object -First 1
    if ($redirectedChild) {
        throw "Refusing recursive cleanup with a redirected child: $($redirectedChild.FullName)"
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
        $smokeRoot = Join-Path $root ("v3\.local\packaged-exe-smoke\" + [guid]::NewGuid().ToString("N"))
        $smokeData = Join-Path $smokeRoot "data"
        $smokeWorkspace = Join-Path $smokeRoot "workspaces.db"
        & (Join-Path $portableRoot "AnimaPromptStudioV3.exe") --workspace-db $smokeWorkspace --install-bundled-examples
        if ($LASTEXITCODE -ne 0) { throw "Packaged V3 bundled example installation failed." }
        $examplePointer = Join-Path $smokeRoot "official-examples\current.json"
        $examplePointerHash = (Get-FileHash -LiteralPath $examplePointer -Algorithm SHA256).Hash
        $smokeArgs = @(
            "--data-root", $smokeData,
            "--workspace-db", $smokeWorkspace,
            "--runtime-database", (Join-Path $smokeRoot "runtime.db"),
            "--no-browser", "--exit-after-startup"
        )
        & (Join-Path $portableRoot "AnimaPromptStudioV3.exe") @smokeArgs --verify-runtime
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
        if ((Get-FileHash -LiteralPath $examplePointer -Algorithm SHA256).Hash -ne $examplePointerHash) {
            throw "Upgrade smoke changed the active example-pack pointer."
        }
    }

    $portableZip = Join-Path $releaseRoot "ANIMA-Prompt-Studio-V3-Portable-v$Version.zip"
    if (Test-Path -LiteralPath $portableZip) { Remove-Item -LiteralPath $portableZip -Force }
    Compress-Archive -Path (Join-Path $portableRoot "*") -DestinationPath $portableZip -CompressionLevel Optimal

    if (-not $SkipInstaller) {
        $iscc = @(
            (Get-Command iscc.exe -ErrorAction SilentlyContinue).Source,
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe"
        ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
        if ($iscc) {
            & $iscc "/DAppVersion=$Version" (Join-Path $root "packaging\installer_v3.iss")
            if ($LASTEXITCODE -ne 0) { throw "V3 Inno Setup build failed." }
        } else {
            throw "Inno Setup was not found. Install it or explicitly use -SkipInstaller for a portable-only build."
        }
    }
} finally {
    Remove-Item Env:ANIMA_V3_PACK_SOURCE -ErrorAction SilentlyContinue
    Pop-Location
}

Get-ChildItem -LiteralPath $releaseRoot -File | Where-Object { $_.Name -like "*V3*" } | Select-Object Name,Length
