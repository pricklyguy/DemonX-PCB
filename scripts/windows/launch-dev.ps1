$ErrorActionPreference='Stop'
$projectRoot=(Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$logDir=Join-Path $projectRoot 'desktop\logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log=Join-Path $logDir 'dev-launch.log'
function Fail([string]$message){Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) $message"; Add-Type -AssemblyName PresentationFramework; [System.Windows.MessageBox]::Show("$message`n`nDiagnostics: $log",'DemonX PCB Prep DEV','OK','Error')|Out-Null; exit 1}
Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Launch requested from $PWD"
$electron=Join-Path $projectRoot 'desktop\node_modules\electron\dist\electron.exe'
$python=Join-Path $projectRoot 'desktop\.venv\Scripts\python.exe'
if(!(Test-Path -LiteralPath $electron)){Fail "Electron runtime is missing. Run SET UP DemonX PCB Prep DEV.cmd once to provision locked desktop dependencies."}
if(!(Test-Path -LiteralPath $python)){Fail "PCB Prep Python environment is missing. Run SET UP DemonX PCB Prep DEV.cmd once to provision locked engine dependencies."}
$main=Join-Path $projectRoot 'desktop\electron\main.mjs'
$stamp=Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdout=Join-Path $logDir "electron-out-$stamp.log"
$stderr=Join-Path $logDir "electron-error-$stamp.log"
try { $process=Start-Process -FilePath $electron -ArgumentList ('"{0}"' -f $main) -WorkingDirectory $projectRoot -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru -ErrorAction Stop }
catch { Fail "Could not start DemonX PCB Prep: $($_.Exception.Message)" }
$deadline=(Get-Date).AddSeconds(20)
while((Get-Date) -lt $deadline){
  $diagnostic=''
  if(Test-Path -LiteralPath $stderr){$diagnostic=Get-Content -LiteralPath $stderr -Raw -ErrorAction SilentlyContinue}
  if($diagnostic -match 'Application window ready'){Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Application window ready ($stamp)"; exit 0}
  if($diagnostic -match 'Single-instance lock already held'){Add-Content -LiteralPath $log -Value "$(Get-Date -Format o) Existing application activated ($stamp)"; exit 0}
  if($process.HasExited){Fail "DemonX PCB Prep exited during startup with code $($process.ExitCode). Diagnostics: $stderr"}
  Start-Sleep -Milliseconds 500
}
Fail "DemonX PCB Prep did not report a ready window within 20 seconds. Diagnostics: $stderr"
