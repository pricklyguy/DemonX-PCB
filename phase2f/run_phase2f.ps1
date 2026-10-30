$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'phase2a\.venv\Scripts\python.exe'
$results = Join-Path $PSScriptRoot 'results'
if (-not (Test-Path -LiteralPath $python)) { throw "Project-local Python 3.12 environment not found: $python" }
New-Item -ItemType Directory -Path $results -Force | Out-Null
& $python -u (Join-Path $PSScriptRoot 'compare_revision.py') *> (Join-Path $results 'generation.log')
if ($LASTEXITCODE -ne 0) { Get-Content (Join-Path $results 'generation.log'); exit $LASTEXITCODE }
& $python -m unittest phase2e.test_recovery phase2f.test_revision -v 2>&1 | Tee-Object -FilePath (Join-Path $results 'test-phase2f.txt')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
