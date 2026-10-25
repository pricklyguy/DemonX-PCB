$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$python = Join-Path $repoRoot 'phase2a\.venv\Scripts\python.exe'
& $python (Join-Path $PSScriptRoot 'forensics.py')
if ($LASTEXITCODE -ne 0) { throw 'Region forensics failed' }
& $python -m unittest -v phase2d.test_regions *> (Join-Path $PSScriptRoot 'results\test-phase2d.txt')
if ($LASTEXITCODE -ne 0) { throw 'Phase 2D tests failed; inspect results/test-phase2d.txt' }
& $python -m pytest phase2a/test_verification.py -q *> (Join-Path $PSScriptRoot 'results\test-phase2a.txt')
if ($LASTEXITCODE -ne 0) { throw 'Phase 2A regressions failed' }
& $python -m unittest -v phase2c.test_phase2c *> (Join-Path $PSScriptRoot 'results\test-phase2c.txt')
if ($LASTEXITCODE -ne 0) { throw 'Phase 2C regressions failed' }
Write-Output 'Phase 2D: 19 tests; Phase 2A: 16 tests; Phase 2C: 9 tests. Logs in phase2d/results.'
