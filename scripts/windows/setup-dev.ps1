$ErrorActionPreference='Stop'
$root=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$node=Get-Command node -ErrorAction SilentlyContinue
if(!$node){throw 'Node.js 22.12 or newer was not found. Install it explicitly, then run this setup launcher again.'}
$nodeVersion=& node -p "process.versions.node"
if([version]$nodeVersion -lt [version]'22.12'){throw "Node.js 22.12 or newer is required; found $nodeVersion."}
$py=Get-Command py -ErrorAction SilentlyContinue
if(!$py){throw 'CPython 3.12 was not found. Install it explicitly, then run this setup launcher again.'}
& py -3.12 -m venv (Join-Path $root 'desktop\.venv')
if($LASTEXITCODE -ne 0){throw 'Could not create the PCB Prep Python environment.'}
& (Join-Path $root 'desktop\.venv\Scripts\python.exe') -m pip install -r (Join-Path $root 'phase2g\requirements.lock')
if($LASTEXITCODE -ne 0){throw 'Python dependency setup failed.'}
& (Join-Path $root 'desktop\.venv\Scripts\python.exe') -m pip install -r (Join-Path $root 'desktop\requirements-build.lock')
if($LASTEXITCODE -ne 0){throw 'Python engine build tools setup failed.'}
Push-Location (Join-Path $root 'desktop')
try {
  npm.cmd ci
  if($LASTEXITCODE -ne 0){throw 'Electron dependency setup failed.'}
  $runtime=Join-Path $root 'desktop\node_modules\electron\dist\electron.exe'
  if(!(Test-Path -LiteralPath $runtime)){
    & node (Join-Path $root 'desktop\node_modules\electron\install.js')
    if($LASTEXITCODE -ne 0 -or !(Test-Path -LiteralPath $runtime)){throw 'Electron runtime provisioning failed.'}
  }
} finally { Pop-Location }
Write-Host 'DemonX PCB Prep DEV is set up. Double-click "DemonX PCB Prep DEV.vbs" to launch.'
