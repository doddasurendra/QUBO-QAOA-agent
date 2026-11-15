<#
.SYNOPSIS
  Register (or remove) a weekly Windows scheduled task that runs scripts\download-backup.ps1: it creates a fresh
  backup on the Fly.io app, downloads it to backups-offsite\ and checks its integrity.

  Runs as the current user, only when that user is logged on (flyctl needs your login token in your profile),
  and catches up after a missed run (StartWhenAvailable). Output is appended to backups-offsite\backup-task.log.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register-backup-task.ps1                     # Sundays 10:00
  powershell -ExecutionPolicy Bypass -File scripts\register-backup-task.ps1 -Day Wednesday -At 20:30
  powershell -ExecutionPolicy Bypass -File scripts\register-backup-task.ps1 -RunNow             # register + test
  powershell -ExecutionPolicy Bypass -File scripts\register-backup-task.ps1 -Unregister
#>
param(
  [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")][string]$Day = "Sunday",
  [string]$At = "10:00",
  [string]$App = "qopt-quantum-c4da",
  [string]$TaskName = "qopt off-site backup",
  [switch]$RunNow,
  [switch]$Unregister
)
$ErrorActionPreference = "Stop"
$Repo = (Resolve-Path "$PSScriptRoot\..").Path

if ($Unregister) {
  if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Removed scheduled task '$TaskName'."
  } else { Write-Host "No scheduled task '$TaskName'." }
  return
}

$Script = Join-Path $Repo "scripts\download-backup.ps1"
$Log = Join-Path $Repo "backups-offsite\backup-task.log"
New-Item -ItemType Directory -Force (Split-Path $Log) | Out-Null
# Timestamped, appended log; the task's exit code is the script's (non-zero on any failure).
$cmd = "& { `"=== `$(Get-Date -Format o) ===`" | Out-File -Append -Encoding utf8 '$Log'; " +
       "try { & '$Script' -App '$App' *>&1 | Out-File -Append -Encoding utf8 '$Log' } " +
       "catch { `"FAILED: `$_`" | Out-File -Append -Encoding utf8 '$Log'; exit 1 }; exit 0 }"
# -EncodedCommand (Base64 of UTF-16LE) avoids any command-line quoting problems with paths containing spaces.
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($cmd))
$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $Repo `
  -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand $encoded"
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $Day -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
  -Principal $principal -Description "Weekly off-site backup of $App (qopt). Log: $Log" -Force | Out-Null
Write-Host "Registered '$TaskName': every $Day at $At (runs late if the PC was off). Log: $Log"

if ($RunNow) {
  Start-ScheduledTask -TaskName $TaskName
  Write-Host "Started a test run; watch $Log (or: Get-ScheduledTaskInfo -TaskName '$TaskName')."
}
