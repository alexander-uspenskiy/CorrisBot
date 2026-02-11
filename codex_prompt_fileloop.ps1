$ErrorActionPreference = "Stop"

# Force UTF-8 for native command I/O to avoid OEM code page mojibake in result logs.
$utf8NoBom = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = $utf8NoBom
[Console]::OutputEncoding = $utf8NoBom
$OutputEncoding = $utf8NoBom

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$PromptsDir = Join-Path $Root "Prompts"
New-Item -ItemType Directory -Force -Path $PromptsDir | Out-Null

$StatePath = Join-Path $PromptsDir "loop_state.json"

function Read-State {
    if (-not (Test-Path -LiteralPath $StatePath)) {
        return @{
            thread_id = $null
            next_index = 0
        }
    }

    try {
        $raw = Get-Content -Path $StatePath -Raw
        $obj = $raw | ConvertFrom-Json -ErrorAction Stop
        return @{
            thread_id = $obj.thread_id
            next_index = [int]$obj.next_index
        }
    }
    catch {
        $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
        $corruptPath = Join-Path $PromptsDir "loop_state.corrupt.$stamp.json"
        Move-Item -Path $StatePath -Destination $corruptPath -Force -ErrorAction SilentlyContinue
        Write-Warning "State file is invalid JSON. Moved to '$corruptPath'. Starting with empty state."
        return @{
            thread_id = $null
            next_index = 0
        }
    }
}

function Write-State {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ThreadId,

        [Parameter(Mandatory = $true)]
        [int]$NextIndex
    )

    $payload = [ordered]@{
        thread_id = $ThreadId
        next_index = $NextIndex
        updated_at = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    } | ConvertTo-Json

    $tmpStatePath = "$StatePath.tmp"
    Set-Content -Path $tmpStatePath -Encoding UTF8 -Value $payload
    Move-Item -Path $tmpStatePath -Destination $StatePath -Force
}

function Wait-ForPromptFile {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    if (Test-Path -LiteralPath $FilePath) {
        return
    }

    $targetName = [IO.Path]::GetFileName($FilePath)
    Write-Host "Waiting for $targetName in $PromptsDir ..."

    $watcher = New-Object IO.FileSystemWatcher $PromptsDir, $targetName
    $watcher.IncludeSubdirectories = $false
    $watcher.EnableRaisingEvents = $true

    $prefix = "PromptWatch_$([guid]::NewGuid().ToString('N'))"
    $createdId = "${prefix}_Created"
    $changedId = "${prefix}_Changed"
    $renamedId = "${prefix}_Renamed"

    $createdSub = Register-ObjectEvent -InputObject $watcher -EventName Created -SourceIdentifier $createdId
    $changedSub = Register-ObjectEvent -InputObject $watcher -EventName Changed -SourceIdentifier $changedId
    $renamedSub = Register-ObjectEvent -InputObject $watcher -EventName Renamed -SourceIdentifier $renamedId

    try {
        while (-not (Test-Path -LiteralPath $FilePath)) {
            $evt = Wait-Event -SourceIdentifier "${prefix}_*" -Timeout 5
            if ($null -ne $evt) {
                Remove-Event -EventIdentifier $evt.EventIdentifier -ErrorAction SilentlyContinue
            }
        }
    }
    finally {
        Unregister-Event -SourceIdentifier $createdId -ErrorAction SilentlyContinue
        Unregister-Event -SourceIdentifier $changedId -ErrorAction SilentlyContinue
        Unregister-Event -SourceIdentifier $renamedId -ErrorAction SilentlyContinue
        $createdSub | Remove-Job -Force -ErrorAction SilentlyContinue
        $changedSub | Remove-Job -Force -ErrorAction SilentlyContinue
        $renamedSub | Remove-Job -Force -ErrorAction SilentlyContinue
        $watcher.Dispose()
    }
}

function Wait-ForFileReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath
    )

    # TODO(producer): for production reliability switch to "write to .tmp, then atomic rename to Promp_NNNN.md".
    # This consumer-side stability check reduces races but cannot guarantee completion if producer writes in delayed chunks.
    $stableRounds = 0
    $lastSize = -1

    while ($stableRounds -lt 2) {
        Start-Sleep -Milliseconds 250

        if (-not (Test-Path -LiteralPath $FilePath)) {
            $stableRounds = 0
            $lastSize = -1
            continue
        }

        $currentSize = (Get-Item -LiteralPath $FilePath).Length
        $canRead = $false

        try {
            $stream = [System.IO.File]::Open($FilePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::Read)
            $stream.Dispose()
            $canRead = $true
        }
        catch {
            $canRead = $false
        }

        if ($canRead -and $currentSize -eq $lastSize) {
            $stableRounds++
        }
        else {
            $stableRounds = 0
        }

        $lastSize = $currentSize
    }
}

function Get-ThreadIdFromOutput {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Lines
    )

    foreach ($line in $Lines) {
        $trim = $line.Trim()
        if (-not ($trim.StartsWith("{") -and $trim.EndsWith("}"))) {
            continue
        }

        try {
            $obj = $trim | ConvertFrom-Json -ErrorAction Stop
        }
        catch {
            continue
        }

        if ($obj.type -eq "thread.started" -and $obj.thread_id) {
            return [string]$obj.thread_id
        }
    }

    return $null
}

$state = Read-State
$index = [int]$state.next_index
$threadId = $state.thread_id

while ($true) {
    $promptName = "Promp_{0:D4}.md" -f $index
    $promptPath = Join-Path $PromptsDir $promptName

    Wait-ForPromptFile -FilePath $promptPath
    Wait-ForFileReady -FilePath $promptPath

    $resultName = "Promp_{0:D4}_Result.md" -f $index
    $resultPath = Join-Path $PromptsDir $resultName

    Write-Host "Processing $promptName"

    $header = @(
        "# Codex Result for $promptName",
        "",
        "Started: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        ""
    )
    $header | Set-Content -Path $resultPath -Encoding UTF8

    $promptText = Get-Content -Path $promptPath -Raw
    $usedResume = -not [string]::IsNullOrWhiteSpace($threadId)

    $cmdOutput = if ($usedResume) {
        $promptText |
            & codex exec resume $threadId --skip-git-repo-check --json - 2>&1 |
            ForEach-Object { $_.ToString() }
    }
    else {
        $promptText |
            & codex exec --skip-git-repo-check --json - 2>&1 |
            ForEach-Object { $_.ToString() }
    }
    $exitCode = $LASTEXITCODE

    $cmdOutput | Tee-Object -FilePath $resultPath -Append | Out-Null

    if ($exitCode -ne 0 -and $usedResume) {
        $resumeErr = ($cmdOutput -join "`n")
        if ($resumeErr -match "(?i)(session|thread).*(not found|missing|unknown)|not found.*(session|thread)") {
            Add-Content -Path $resultPath -Encoding UTF8 -Value "`nResume failed because session was not found. Starting a new session for this prompt."
            $threadId = $null

            $cmdOutput = $promptText |
                & codex exec --skip-git-repo-check --json - 2>&1 |
                ForEach-Object { $_.ToString() }
            $exitCode = $LASTEXITCODE

            Add-Content -Path $resultPath -Encoding UTF8 -Value "`n--- Fallback: new session attempt ---`n"
            $cmdOutput | Tee-Object -FilePath $resultPath -Append | Out-Null
        }
    }

    if ($exitCode -ne 0) {
        Add-Content -Path $resultPath -Encoding UTF8 -Value "`nCommand failed with exit code: $exitCode"
        throw "codex command failed with exit code $exitCode"
    }

    $detectedThreadId = Get-ThreadIdFromOutput -Lines $cmdOutput
    if ($detectedThreadId) {
        $threadId = $detectedThreadId
    }

    if ([string]::IsNullOrWhiteSpace($threadId)) {
        Add-Content -Path $resultPath -Encoding UTF8 -Value "`nCould not detect thread_id from codex output."
        throw "thread_id was not detected; refusing to continue without explicit session id."
    }

    Add-Content -Path $resultPath -Encoding UTF8 -Value "`nFinished: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"

    $index++
    Write-State -ThreadId $threadId -NextIndex $index
}
