param(
    [string]$InboxPath = 'C:\Temp\CorrisBot_UnfuddleYouTrack_Events\Orchestrator\Prompts\Inbox\Worker_AlarmClock_001',
    [string]$ReportType = 'status',
    [string]$ReportIdPrefix = 'alarmclock-hourly',
    [string]$NextResetReference = '04:47 local',
    [string]$LooperRoot = $env:LOOPER_ROOT,
    [switch]$IsTest
)

$ErrorActionPreference = 'Stop'

$now = Get-Date
$reportId = '{0}-{1}' -f $ReportIdPrefix, $now.ToString('yyyyMMddHHmmss')
$localTime = $now.ToString('yyyy-MM-dd HH:mm:ss zzz')

$messageMeta = @(
    'Message-Meta:',
    '- MessageClass: report',
    "- ReportType: $ReportType",
    "- ReportID: $reportId",
    '- RouteSessionID: tg_corriscant_unfuddle_events_20260223_1',
    '- ProjectTag: CorrisBot_UnfuddleYouTrack_Events',
    ''
)

$tickType = if ($IsTest.IsPresent) { 'test' } else { 'scheduled' }

$alarmBody = @(
    'AlarmClock-Status:',
    "- LocalTime: $localTime",
    "- NextResetReference: $NextResetReference",
    "- TickType: $tickType"
)

$content = ($messageMeta + $alarmBody) -join "`r`n"

$tempDir = Join-Path $PSScriptRoot '..\\Temp'
$tempDir = [System.IO.Path]::GetFullPath($tempDir)
if (-not (Test-Path -LiteralPath $tempDir)) {
    New-Item -ItemType Directory -Path $tempDir | Out-Null
}

$reportPath = Join-Path $tempDir ('alarmclock_tick_report_{0}.md' -f $now.ToString('yyyyMMdd_HHmmss_fff'))
Set-Content -LiteralPath $reportPath -Value $content -Encoding UTF8

$effectiveLooperRoot = if ([string]::IsNullOrWhiteSpace($LooperRoot)) { 'C:\CorrisBot\Looper' } else { $LooperRoot }
$createScript = Join-Path $effectiveLooperRoot 'create_prompt_file.py'
if (-not (Test-Path -LiteralPath $createScript)) {
    throw "create_prompt_file.py not found: $createScript"
}
$rawOutput = py "$createScript" create --inbox "$InboxPath" --from-file "$reportPath"

[pscustomobject]@{
    ReportPath = $reportPath
    CreateOutput = ($rawOutput | Out-String).Trim()
} | ConvertTo-Json -Compress
