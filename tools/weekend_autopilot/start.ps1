# start.ps1 — Launch the Weekend Autopilot supervisor in the background
# Usage: .\start.ps1
# The supervisor runs claude --print sessions autonomously until Sunday 25-Oct-2026 EOD

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Supervisor = Join-Path $PSScriptRoot "supervisor.py"
$LogFile = Join-Path $Root "audits\weekend_stability\supervisor_stdout.log"

Write-Host "Starting Weekend Autopilot..."
Write-Host "  Project: $Root"
Write-Host "  Log: $LogFile"

# Check for existing instance
$LockFile = Join-Path $PSScriptRoot ".supervisor.pid"
if (Test-Path $LockFile) {
    $pid = Get-Content $LockFile -ErrorAction SilentlyContinue
    Write-Host "  WARNING: Lock file exists (PID $pid). Check status.ps1 before starting."
    $confirm = Read-Host "  Force start anyway? [y/N]"
    if ($confirm -ne 'y') { exit 1 }
    Remove-Item $LockFile -Force
}

# Ensure audit dir exists
$AuditDir = Join-Path $Root "audits\weekend_stability"
if (-not (Test-Path $AuditDir)) { New-Item -ItemType Directory -Force $AuditDir | Out-Null }

# Start supervisor as a background job, stdout/stderr to log
$job = Start-Job -ScriptBlock {
    param($py, $root, $log)
    Set-Location $root
    python $py 2>&1 | Tee-Object -FilePath $log -Append
} -ArgumentList $Supervisor, $Root, $LogFile

Write-Host "  Supervisor started as background job ID $($job.Id)"
Write-Host "  Monitor with: .\status.ps1"
Write-Host "  Stop with:    .\stop.ps1"
Write-Host ""
Write-Host "  Live log: Get-Content '$LogFile' -Wait -Tail 20"
