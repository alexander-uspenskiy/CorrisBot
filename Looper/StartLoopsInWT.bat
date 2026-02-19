@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
set "LOOPER_ROOT=%SCRIPT_DIR:~0,-1%"

if "%~1"=="" goto :usage

set "PROJECT_ROOT=%~1"
shift

set "AGENT_PATH=."
set "AGENT_PATH_SET="
set "DRY_RUN_FLAG="
set "RUNNER_FLAG="
set "REASONING_FLAG="

rem Parse remaining arguments in any order:
rem [agent_path] [--runner codex|kimi] [--reasoning-effort low|medium|high] [--dry-run]
:parse_args
if "%~1"=="" goto :parse_done

if /I "%~1"=="--dry-run" (
  set "DRY_RUN_FLAG=--dry-run"
  shift
  goto :parse_args
)

if /I "%~1"=="--runner" (
  if "%~2"=="" (
    echo Missing runner value after --runner
    goto :usage
  )
  if /I "%~2"=="codex" (
    set "RUNNER_FLAG=--runner codex"
  ) else if /I "%~2"=="kimi" (
    set "RUNNER_FLAG=--runner kimi"
  ) else (
    echo Invalid runner value: %~2. Use 'codex' or 'kimi'.
    goto :usage
  )
  shift
  shift
  goto :parse_args
)

if /I "%~1"=="--reasoning-effort" (
  if "%~2"=="" (
    echo Missing value after --reasoning-effort
    goto :usage
  )
  if /I "%~2"=="low" (
    set "REASONING_FLAG=--reasoning-effort low"
  ) else if /I "%~2"=="medium" (
    set "REASONING_FLAG=--reasoning-effort medium"
  ) else if /I "%~2"=="high" (
    set "REASONING_FLAG=--reasoning-effort high"
  ) else (
    echo Invalid reasoning effort value: %~2. Use 'low', 'medium' or 'high'.
    goto :usage
  )
  shift
  shift
  goto :parse_args
)

if not defined AGENT_PATH_SET (
  set "AGENT_PATH=%~1"
  set "AGENT_PATH_SET=1"
  shift
  goto :parse_args
)

echo Unexpected argument: %~1
goto :usage

:parse_done
py -3 "%SCRIPT_DIR%StartLoopsInWT.py" "%PROJECT_ROOT%" "%AGENT_PATH%" %RUNNER_FLAG% %REASONING_FLAG% %DRY_RUN_FLAG%
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo WT launcher failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

exit /b 0

:usage
echo Usage: %~nx0 ^<project_root^> [agent_path] [--runner codex^|kimi] [--reasoning-effort low^|medium^|high] [--dry-run]
echo Example 1: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Orchestrator
echo Example 2: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Workers\Worker_001
echo Example 3: %~nx0 "%LOOPER_ROOT%\..\Talker"
echo Example 4: %~nx0 "%LOOPER_ROOT%\..\Talker" --dry-run
echo Example 5: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Workers\Worker_001 --dry-run
echo Example 6: %~nx0 "%LOOPER_ROOT%\..\Talker" . --runner kimi
echo Example 7: %~nx0 "%LOOPER_ROOT%\..\Talker" . --runner codex --reasoning-effort high --dry-run
echo.
echo Options:
echo   --runner codex^|kimi   Choose CLI agent (default: codex)
echo   --reasoning-effort     Per-call override for Codex: low^|medium^|high
echo   --dry-run             Print command without launching WT
exit /b 1
