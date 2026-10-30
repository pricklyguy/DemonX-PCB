$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
& (Join-Path $repoRoot 'phase2a\.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'run_phase2e.py')
if ($LASTEXITCODE -ne 0) { throw 'Phase 2E failed; inspect phase2e/results logs' }
