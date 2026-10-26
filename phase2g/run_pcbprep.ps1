$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    throw "Phase 2G environment is missing. Create it with Python 3.12 and install phase2g/requirements.txt."
}
$RunGui = Join-Path $PSScriptRoot "run_gui.py"
$PreviousPythonPath = $env:PYTHONPATH
$PathEntries = @($Root)
if (-not [string]::IsNullOrWhiteSpace($PreviousPythonPath)) {
    $PathEntries += $PreviousPythonPath -split [regex]::Escape([string][IO.Path]::PathSeparator) |
        Where-Object { -not [string]::IsNullOrWhiteSpace($_) -and $_.TrimEnd('\','/') -ine $Root.TrimEnd('\','/') }
}
$env:PYTHONPATH = $PathEntries -join [IO.Path]::PathSeparator
$ExitCode = 1
try {
    & $Python $RunGui @args
    $ExitCode = $LASTEXITCODE
} finally {
    if ($null -eq $PreviousPythonPath) {
        Remove-Item Env:PYTHONPATH -ErrorAction SilentlyContinue
    } else {
        $env:PYTHONPATH = $PreviousPythonPath
    }
}
exit $ExitCode
