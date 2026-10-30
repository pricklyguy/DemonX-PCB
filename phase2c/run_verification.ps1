$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot 'phase2a\.venv\Scripts\python.exe'
$pygerberPackages = Join-Path $repoRoot 'phase2b\.venv\Lib\site-packages'
if (-not (Test-Path -LiteralPath $python)) { throw "Missing project-local Python environment: $python" }
if (-not (Test-Path -LiteralPath (Join-Path $pygerberPackages 'pygerber'))) { throw "Missing pinned PyGerber environment: $pygerberPackages" }
$env:PYTHONPATH = $pygerberPackages
& $python (Join-Path $PSScriptRoot 'verify_phase2c.py')
if ($LASTEXITCODE -ne 0) { throw "Phase 2C verification failed with exit code $LASTEXITCODE" }
& $python -m unittest -v phase2c.test_phase2c
if ($LASTEXITCODE -ne 0) { throw "Phase 2C regression tests failed with exit code $LASTEXITCODE" }
