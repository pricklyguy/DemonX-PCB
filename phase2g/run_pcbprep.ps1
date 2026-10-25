$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Phase 2G environment is missing. Create it with Python 3.12 and install phase2g/requirements.txt."
}
& $Python (Join-Path $PSScriptRoot "run_gui.py") @args
exit $LASTEXITCODE
