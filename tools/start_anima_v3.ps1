$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$v3Source = Join-Path $projectRoot "v3\src"
$v2Source = Join-Path $projectRoot "src"
$dataRoot = Join-Path $projectRoot "v3\.local\data"
$packRoot = Join-Path $projectRoot "v3\.local\packs"
$frontend = Join-Path $projectRoot "v3\web\dist"
$workspace = Join-Path $projectRoot "v3\.local\state\workspaces.db"
$v2Database = Join-Path $env:LOCALAPPDATA "AnimaPromptStudio\anima_prompt_studio.db"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    Write-Host "[ANIMA V3] Project Python environment was not found:" -ForegroundColor Red
    Write-Host $python
    throw "Install the V3 development environment first."
}
if (-not (Test-Path -LiteralPath (Join-Path $frontend "index.html") -PathType Leaf)) {
    Write-Host "[ANIMA V3] Web build was not found. Run npm build in v3/web first." -ForegroundColor Red
    throw "Missing V3 Web build."
}

$sourcePaths = @($v3Source, $v2Source)
if ($env:PYTHONPATH) { $sourcePaths += $env:PYTHONPATH }
$env:PYTHONPATH = $sourcePaths -join [IO.Path]::PathSeparator
$env:PYTHONUNBUFFERED = "1"

$arguments = @(
    "-m", "anima_prompt_studio_v3.tools.run_desktop",
    "--data-root", $dataRoot,
    "--pack-source-root", $packRoot,
    "--frontend-dist", $frontend,
    "--workspace-db", $workspace
)
if (Test-Path -LiteralPath $v2Database -PathType Leaf) {
    $arguments += @("--v2-database", $v2Database)
}

Write-Host "[ANIMA V3] Starting local service..." -ForegroundColor Cyan
& $python @arguments
if ($LASTEXITCODE -ne 0) {
    throw "ANIMA V3 exited with code $LASTEXITCODE."
}
