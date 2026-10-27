$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$log = Join-Path $PSScriptRoot 'results\regression-suite.txt'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log) | Out-Null
Set-Content -Path $log -Value "DemonX PCB Prep Phase 2I regression run`nStarted: $(Get-Date -Format o)`n"

$steps = @(
    @{ Name = 'Phase 2A'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','pytest','phase2a/test_verification.py','-q') },
    @{ Name = 'Phase 2B'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2b.test_phase2b','-v') },
    @{ Name = 'Phase 2C'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2c.test_phase2c','-v') },
    @{ Name = 'Phase 2D'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2d.test_regions','-v') },
    @{ Name = 'Phase 2E'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2e.test_recovery','-v') },
    @{ Name = 'Phase 2F'; Python = 'phase2a\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2f.test_revision','-v') },
    @{ Name = 'Phase 2G / 2H GUI'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2g.test_phase2g','-v') },
    @{ Name = 'Phase 2I'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2i.test_phase2i_corpus','-v') },
    @{ Name = 'Phase 2J'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2j.test_phase2j','-v') },
    @{ Name = 'Phase 2K'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2k.test_phase2k','-v') },
    @{ Name = 'Phase 2L'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2l.test_geometry','phase2l.test_preview','-v') },
    @{ Name = 'Phase 2M'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2m.test_workflow','phase2m.test_launcher','-v') },
    @{ Name = 'Phase 2N'; Python = 'phase2g\.venv\Scripts\python.exe'; Args = @('-m','unittest','phase2n.test_audit','phase2n.test_compatibility','-v') }
)

Push-Location $root
try {
    foreach ($step in $steps) {
        $python = Join-Path $root $step.Python
        Add-Content -Path $log -Value "`n=== $($step.Name) ==="
        & $python @($step.Args) 2>&1 | Tee-Object -FilePath $log -Append
        if ($LASTEXITCODE -ne 0) {
            Add-Content -Path $log -Value "FAILED: $($step.Name) exit $LASTEXITCODE"
            exit $LASTEXITCODE
        }
    }
    Add-Content -Path $log -Value "`nCompleted: $(Get-Date -Format o)`nAll suites passed."
} finally {
    Pop-Location
}
Write-Output "All Phase 2A–2N regression suites passed. Log: $log"
