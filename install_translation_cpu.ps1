param(
    [switch]$DownloadModels
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
$env:PYTHONPATH = Join-Path $projectRoot "src"

if (-not (Test-Path -LiteralPath $projectPython)) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) {
        throw "Python was not found. Install Python 3.12 and create the project .venv first."
    }
    $projectPython = $pythonCommand.Source
    Write-Warning "Project .venv was not found; using: $projectPython"
}

Write-Host "[1/3] Installing CPU-only PyTorch (no CUDA runtime)..."
& $projectPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { throw "CPU-only PyTorch installation failed." }

Write-Host "[2/3] Installing Marian/Transformers dependencies..."
& $projectPython -m pip install -r (Join-Path $projectRoot "requirements-translation.txt")
if ($LASTEXITCODE -ne 0) { throw "Translation dependency installation failed." }

if ($DownloadModels) {
    Write-Host "Downloading both Marian models (about 600 MB)..."
    & $projectPython -m anima_prompt_studio.tools.resource_setup --models
    if ($LASTEXITCODE -ne 0) { throw "Marian model download failed." }
}

Write-Host "[3/3] Verifying the translation environment..."
$verifyArgs = @("-m", "anima_prompt_studio.tools.verify_translation_env")
if ($DownloadModels) { $verifyArgs += "--require-models" }
& $projectPython @verifyArgs
if ($LASTEXITCODE -ne 0) { throw "Translation environment verification failed." }

if (-not $DownloadModels) {
    Write-Host "Dependencies are ready. To download models later, run:"
    Write-Host "  python -m anima_prompt_studio.tools.resource_setup --models"
}
