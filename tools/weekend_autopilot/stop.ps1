# stop.ps1 — Signal the supervisor to stop cleanly after the current task
# Usage: .\stop.ps1

$StopFile = Join-Path $PSScriptRoot ".STOP"

Write-Host "Signaling supervisor to stop..."
"STOP" | Out-File $StopFile -Encoding utf8

Write-Host "  Stop signal written to .STOP"
Write-Host "  The supervisor will finish its current task and then exit."
Write-Host "  Check status.ps1 to confirm it stopped."

# Also show current state
$StateFile = Join-Path $PSScriptRoot "..\..\audits\weekend_stability\MISSION_STATE.json"
if (Test-Path $StateFile) {
    $state = Get-Content $StateFile | ConvertFrom-Json
    Write-Host ""
    Write-Host "Current state:"
    Write-Host "  Status:      $($state.status)"
    Write-Host "  Active task: $($state.active_task)"
    Write-Host "  Cycle:       $($state.cycle)"
}
