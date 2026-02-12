param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot "Plans\loops.wt.json"),
    [string]$ProjectRootOverride,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

function Resolve-DotCorrisBotRoot {
    param([Parameter(Mandatory = $true)][string]$PathText)
    $fullPath = [System.IO.Path]::GetFullPath($PathText)
    $dotPath = Join-Path $fullPath ".CorrisBot"
    if (Test-Path -LiteralPath $dotPath -PathType Container) {
        return [System.IO.Path]::GetFullPath($dotPath)
    }
    return $fullPath
}

function Get-ProjectTag {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)
    $leaf = Split-Path -Path $ProjectRoot -Leaf
    if ($leaf -ieq ".CorrisBot") {
        $parent = Split-Path -Path $ProjectRoot -Parent
        return (Split-Path -Path $parent -Leaf)
    }
    return $leaf
}

function Normalize-AgentPath {
    param([Parameter(Mandatory = $true)][string]$AgentPath)
    $normalized = $AgentPath.Trim() -replace "/", "\"
    if ($normalized.StartsWith(".\")) {
        $normalized = $normalized.Substring(2)
    }
    return $normalized
}

function Resolve-AgentDir {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$AgentPath
    )
    $candidate = Normalize-AgentPath -AgentPath $AgentPath
    if ([System.IO.Path]::IsPathRooted($candidate)) {
        return [System.IO.Path]::GetFullPath($candidate)
    }
    return [System.IO.Path]::GetFullPath((Join-Path $ProjectRoot $candidate))
}

function Convert-ToPathRegex {
    param([Parameter(Mandatory = $true)][string]$PathText)
    $escaped = [regex]::Escape($PathText.ToLowerInvariant())
    return ($escaped -replace "\\\\", "[\\\\/]")
}

function Test-AgentAlreadyRunning {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$AgentPath,
        [Parameter(Mandatory = $true)][string]$AgentAbsPath
    )
    $projectPattern = Convert-ToPathRegex -PathText $ProjectRoot
    $agentRelPattern = Convert-ToPathRegex -PathText (Normalize-AgentPath -AgentPath $AgentPath)
    $agentAbsPattern = Convert-ToPathRegex -PathText $AgentAbsPath

    $processes = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue
    foreach ($proc in $processes) {
        $cmdline = [string]$proc.CommandLine
        if ([string]::IsNullOrWhiteSpace($cmdline)) {
            continue
        }
        $lower = $cmdline.ToLowerInvariant()
        $isLoopProcess = ($lower -match "codex_prompt_fileloop\.py") -or ($lower -match "codexloop\.bat")
        if (-not $isLoopProcess) {
            continue
        }
        if (($lower -match $projectPattern) -and (($lower -match $agentRelPattern) -or ($lower -match $agentAbsPattern))) {
            return $true
        }
    }
    return $false
}

function Convert-ToPaneSpec {
    param([Parameter(Mandatory = $true)]$RawPane)

    if ($RawPane -is [string]) {
        return [pscustomobject]@{
            agent_path = [string]$RawPane
            title = ""
        }
    }

    $agentPath = [string]$RawPane.agent_path
    if ([string]::IsNullOrWhiteSpace($agentPath)) {
        throw "Pane object must contain non-empty 'agent_path'."
    }
    $title = ""
    if ($null -ne $RawPane.title) {
        $title = [string]$RawPane.title
    }
    return [pscustomobject]@{
        agent_path = $agentPath
        title = $title
    }
}

function Format-ArgsForDisplay {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $parts = foreach ($a in $Args) {
        if ($a -eq ";") {
            ";"
        }
        elseif ($a -match "\s") {
            '"' + $a + '"'
        }
        else {
            $a
        }
    }
    return ($parts -join " ")
}

function Get-LoopInvocation {
    param(
        [Parameter(Mandatory = $true)][string]$LoopBatPath,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$AgentPath
    )
    return ('"{0}" "{1}" "{2}"' -f $LoopBatPath, $ProjectRoot, $AgentPath)
}

function Build-TabArguments {
    param(
        [Parameter(Mandatory = $true)]$TabNode,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$ProjectTag,
        [Parameter(Mandatory = $true)][string]$LoopBatPath
    )

    $tabName = "UnnamedTab"
    if ($null -ne $TabNode.name -and -not [string]::IsNullOrWhiteSpace([string]$TabNode.name)) {
        $tabName = [string]$TabNode.name
    }
    $paneNodes = @($TabNode.panes)
    if ($paneNodes.Count -eq 0) {
        Write-Host "[skip] Tab '$tabName' has no panes."
        return @()
    }

    $launchablePanes = @()
    foreach ($paneNode in $paneNodes) {
        $pane = Convert-ToPaneSpec -RawPane $paneNode
        $agentPath = Normalize-AgentPath -AgentPath $pane.agent_path
        $agentDir = Resolve-AgentDir -ProjectRoot $ProjectRoot -AgentPath $agentPath

        if (-not (Test-Path -LiteralPath $agentDir -PathType Container)) {
            Write-Host "[skip] Agent path not found: $agentDir"
            continue
        }
        if (Test-AgentAlreadyRunning -ProjectRoot $ProjectRoot -AgentPath $agentPath -AgentAbsPath $agentDir) {
            Write-Host "[skip] Agent already running: $agentPath"
            continue
        }

        $paneTitle = [string]$pane.title
        if ([string]::IsNullOrWhiteSpace($paneTitle)) {
            $paneTitle = "[{0}] {1} | {2}" -f $ProjectTag, $tabName, ($agentPath -replace "\\", "/")
        }

        $launchablePanes += [pscustomobject]@{
            agent_path = $agentPath
            title = $paneTitle
        }
    }

    if ($launchablePanes.Count -eq 0) {
        Write-Host "[skip] Tab '$tabName' has nothing to launch."
        return @()
    }

    $tabArgs = @()
    $first = $true
    $splitIndex = 0
    foreach ($pane in $launchablePanes) {
        $loopCmd = Get-LoopInvocation -LoopBatPath $LoopBatPath -ProjectRoot $ProjectRoot -AgentPath $pane.agent_path
        if ($first) {
            $tabArgs += @("new-tab", "--title", [string]$pane.title, "cmd", "/k", $loopCmd)
            $first = $false
            continue
        }
        $splitIndex += 1
        $orientation = if (($splitIndex % 2) -eq 1) { "-H" } else { "-V" }
        $tabArgs += @(";", "split-pane", $orientation, "--title", [string]$pane.title, "cmd", "/k", $loopCmd)
    }
    return $tabArgs
}

function Resolve-WtExecutable {
    $wtCmd = Get-Command wt.exe -ErrorAction SilentlyContinue
    if ($wtCmd -and $wtCmd.Source) {
        return [string]$wtCmd.Source
    }
    $winApps = Join-Path $env:LOCALAPPDATA "Microsoft\WindowsApps\wt.exe"
    if (Test-Path -LiteralPath $winApps -PathType Leaf) {
        return [System.IO.Path]::GetFullPath($winApps)
    }
    return ""
}

$wtExe = Resolve-WtExecutable
if ([string]::IsNullOrWhiteSpace($wtExe)) {
    if ($DryRun) {
        Write-Host "[warning] wt.exe was not found, running in dry-run with command preview only."
        $wtExe = "wt.exe"
    }
    else {
        throw "Windows Terminal command 'wt.exe' not found in PATH."
    }
}

$configFullPath = [System.IO.Path]::GetFullPath($ConfigPath)
if (-not (Test-Path -LiteralPath $configFullPath -PathType Leaf)) {
    throw "Config file not found: $configFullPath"
}

$config = Get-Content -LiteralPath $configFullPath -Raw | ConvertFrom-Json
$projectRootFromConfig = [string]$config.project_root
if ([string]::IsNullOrWhiteSpace($projectRootFromConfig) -and [string]::IsNullOrWhiteSpace($ProjectRootOverride)) {
    throw "Config must contain non-empty 'project_root' or pass -ProjectRootOverride."
}

$effectiveProjectRoot = if ([string]::IsNullOrWhiteSpace($ProjectRootOverride)) { $projectRootFromConfig } else { $ProjectRootOverride }
$projectRoot = Resolve-DotCorrisBotRoot -PathText $effectiveProjectRoot
if (-not (Test-Path -LiteralPath $projectRoot -PathType Container)) {
    throw "Project root not found: $projectRoot"
}

$projectTag = Get-ProjectTag -ProjectRoot $projectRoot
$loopBatPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "CodexLoop.bat"))
if (-not (Test-Path -LiteralPath $loopBatPath -PathType Leaf)) {
    throw "CodexLoop.bat not found: $loopBatPath"
}

$windows = @($config.windows)
if ($windows.Count -eq 0) {
    throw "Config must contain non-empty 'windows' array."
}

Write-Host ("Project root: " + $projectRoot)
Write-Host ("Project tag:  " + $projectTag)
Write-Host ("Config file:  " + $configFullPath)

foreach ($window in $windows) {
    $windowName = "CorrisBot"
    if ($null -ne $window.name -and -not [string]::IsNullOrWhiteSpace([string]$window.name)) {
        $windowName = [string]$window.name
    }
    $tabs = @($window.tabs)
    if ($tabs.Count -eq 0) {
        Write-Host "[skip] Window '$windowName' has no tabs."
        continue
    }

    $windowArgs = @("-w", $windowName)
    $hasCommands = $false

    foreach ($tab in $tabs) {
        $tabArgs = Build-TabArguments -TabNode $tab -ProjectRoot $projectRoot -ProjectTag $projectTag -LoopBatPath $loopBatPath
        if ($tabArgs.Count -eq 0) {
            continue
        }
        if ($hasCommands) {
            $windowArgs += ";"
        }
        $windowArgs += $tabArgs
        $hasCommands = $true
    }

    if (-not $hasCommands) {
        Write-Host "[skip] Window '$windowName' has no new agents to launch."
        continue
    }

    if ($DryRun) {
        Write-Host ("[dry-run] wt " + (Format-ArgsForDisplay -Args $windowArgs))
    }
    else {
        Start-Process -FilePath $wtExe -ArgumentList $windowArgs | Out-Null
        Write-Host ("[ok] Launch command sent to WT window: " + $windowName)
        Start-Sleep -Milliseconds 150
    }
}
