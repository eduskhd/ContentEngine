# status.ps1 — Show current supervisor and mission status
# Usage: .\status.ps1

$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$AuditDir = Join-Path $Root "audits\weekend_stability"
$StateFile = Join-Path $AuditDir "MISSION_STATE.json"
$LockFile  = Join-Path $PSScriptRoot ".supervisor.pid"
$LogFile   = Join-Path $AuditDir "supervisor_stdout.log"

Write-Host "=== Weekend Autopilot Status ===" -ForegroundColor Cyan
Write-Host ""

# Check if supervisor is running
if (Test-Path $LockFile) {
    $pid = Get-Content $LockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $pid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "RUNNING — PID $pid  (started $($proc.StartTime))" -ForegroundColor Green
    } else {
        Write-Host "STALE LOCK — PID $pid not running (lock file may be stale)" -ForegroundColor Yellow
    }
} else {
    Write-Host "NOT RUNNING — no lock file" -ForegroundColor Yellow
}

Write-Host ""

# Mission state
if (Test-Path $StateFile) {
    $state = Get-Content $StateFile | ConvertFrom-Json
    Write-Host "Mission State:" -ForegroundColor Cyan
    Write-Host "  Status:       $($state.status)"
    Write-Host "  Cycle:        $($state.cycle)"
    Write-Host "  Active task:  $($state.active_task)"
    Write-Host "  Last advance: $($state.last_advance)"
    Write-Host "  Updated at:   $($state.updated_at)"
    Write-Host ""
    Write-Host "Tasks:" -ForegroundColor Cyan
    foreach ($task in $state.tasks) {
        $icon = switch ($task.status) {
            "done"    { "[DONE]   " }
            "running" { "[RUN]    " }
            "blocked" { "[BLOCKED]" }
            "pending" { "[PENDING]" }
            default   { "[ ? ]    " }
        }
        Write-Host "  $icon $($task.id) (attempts: $($task.attempts))"
    }
} else {
    Write-Host "No MISSION_STATE.json found — supervisor not started yet." -ForegroundColor Yellow
}

Write-Host ""

# Recent log lines
if (Test-Path $LogFile) {
    Write-Host "Recent log (last 10 lines):" -ForegroundColor Cyan
    Get-Content $LogFile -Tail 10 | ForEach-Object { Write-Host "  $_" }
}

Write-Host ""
Write-Host "Stop with: .\stop.ps1  |  View live log: Get-Content '$LogFile' -Wait -Tail 20"
