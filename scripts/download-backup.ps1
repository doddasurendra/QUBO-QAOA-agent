<#
.SYNOPSIS
  Off-site copy: create a fresh consistent backup on the Fly.io server and download it (plus any other recent
  backups) to this PC. Backups contain password hashes; keep the folder private.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\download-backup.ps1
  powershell -ExecutionPolicy Bypass -File scripts\download-backup.ps1 -App qopt-quantum-c4da -Dest D:\qopt-backups
#>
param([string]$App = "qopt-quantum-c4da", [string]$Dest = "", [switch]$NoCreate)

# "Continue": flyctl writes progress ("Connecting to ...") to stderr, which Windows PowerShell 5.1 would turn into a
# terminating error under "Stop". Native failures are checked explicitly via $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
function Assert-Ok($what) { if ($LASTEXITCODE -ne 0) { throw "$what failed (exit code $LASTEXITCODE)" } }
$Repo = (Resolve-Path "$PSScriptRoot\..").Path
if (-not $Dest) { $Dest = Join-Path $Repo "backups-offsite" }
$Fly = Join-Path $env:USERPROFILE ".fly\bin\flyctl.exe"
if (-not (Test-Path $Fly)) { $Fly = "flyctl" }
New-Item -ItemType Directory -Force $Dest | Out-Null

if (-not $NoCreate) {
  Write-Host "Creating a fresh backup on $App ..."
  # run as the app's own user so the backup files stay owned by (and prunable by) the application
  & $Fly ssh console -a $App -u qopt -C "python -m qopt.services.backup create" 2>$null | Out-Host
  Assert-Ok "creating the backup on $App"
}
$names = & $Fly ssh console -a $App -C "ls -1 /app/data/backups" 2>$null |
  ForEach-Object { "$_".Trim() } | Where-Object { $_ -match '^qopt-\d{8}T\d+Z\.db$' }
Assert-Ok "listing backups on $App"
if (-not $names) { throw "no backups found on $App" }
$latest = ($names | Sort-Object)[-1]
$target = Join-Path $Dest $latest
if (Test-Path $target) { Write-Host "Already downloaded: $target"; return }
& $Fly ssh sftp get -a $App "/app/data/backups/$latest" $target 2>$null | Out-Host
Assert-Ok "downloading $latest"
if (-not (Test-Path $target)) { throw "download reported success but $target is missing" }

# Verify the downloaded copy opens and passes SQLite's integrity check.
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
if (Test-Path $Py) {
  $check = & $Py -c "import sqlite3,sys;c=sqlite3.connect(sys.argv[1]);print(c.execute('PRAGMA integrity_check').fetchone()[0])" $target
  Write-Host "Integrity check of the downloaded copy: $check"
  if ($check -ne "ok") { throw "downloaded backup failed the integrity check" }
}
Write-Host "Off-site backup saved: $target"
