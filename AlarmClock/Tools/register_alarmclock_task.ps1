param(
    [string]$TaskName = 'CorrisBot_Worker_AlarmClock_001_HourlyReminder'
)

$ErrorActionPreference = 'Stop'

$scriptPath = Join-Path $PSScriptRoot 'alarmclock_tick.ps1'
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Tick script not found: $scriptPath"
}

$startTime = (Get-Date).AddMinutes(1).ToString('HH:mm')
$command = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""

schtasks /Create /TN "$TaskName" /SC HOURLY /MO 1 /ST $startTime /TR "$command" /F | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "schtasks create failed with exit code $LASTEXITCODE"
}

$taskQuery = schtasks /Query /TN "$TaskName" /FO LIST /V
if ($LASTEXITCODE -ne 0) {
    throw "schtasks query failed with exit code $LASTEXITCODE"
}

[pscustomobject]@{
    TaskName = $TaskName
    StartTime = $startTime
    Query = ($taskQuery | Out-String).Trim()
} | ConvertTo-Json -Compress
