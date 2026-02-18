@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "LOOPER_ROOT=%SCRIPT_DIR:~0,-1%"

if "%~1"=="" goto :usage

set "PROJECT_ROOT=%~1"
set "AGENT_PATH=%~2"
set "DRY_RUN_FLAG="
set "RUNNER_FLAG="

rem Parse arguments
rem %1 = project_root (required)
rem %2 = agent_path or --dry-run or --runner (optional)
rem %3 = --dry-run or --runner or runner value (optional)
rem %4 = --dry-run (optional)

if "%AGENT_PATH%"=="" (
  set "AGENT_PATH=."
  goto :parse_done
) else if /I "%AGENT_PATH%"=="--dry-run" (
  set "AGENT_PATH=."
  set "DRY_RUN_FLAG=--dry-run"
  goto :parse_done
) else if /I "%AGENT_PATH%"=="--runner" (
  set "AGENT_PATH=."
  goto :parse_runner_arg3
)

rem %2 is agent_path, check %3
if /I "%~3"=="--dry-run" (
  set "DRY_RUN_FLAG=--dry-run"
  goto :parse_done
) else if /I "%~3"=="--runner" (
  goto :parse_runner_arg4
) else if "%~3"=="" (
  goto :parse_done
) else (
  echo Unexpected third argument: %~3
  goto :usage
)

:parse_runner_arg3
rem %2 was --runner, %3 should be runner value
if "%~3"=="" (
  echo Missing runner value after --runner
  goto :usage
)
if /I "%~3"=="codex" (
  set "RUNNER_FLAG=--runner codex"
) else if /I "%~3"=="kimi" (
  set "RUNNER_FLAG=--runner kimi"
) else (
  echo Invalid runner value: %~3. Use 'codex' or 'kimi'.
  goto :usage
)
rem Check %4 for --dry-run
if /I "%~4"=="--dry-run" (
  set "DRY_RUN_FLAG=--dry-run"
) else if not "%~4"=="" (
  echo Unexpected argument after runner: %~4
  goto :usage
)
goto :parse_done

:parse_runner_arg4
rem %3 was --runner, %4 should be runner value
if "%~4"=="" (
  echo Missing runner value after --runner
  goto :usage
)
if /I "%~4"=="codex" (
  set "RUNNER_FLAG=--runner codex"
) else if /I "%~4"=="kimi" (
  set "RUNNER_FLAG=--runner kimi"
) else if /I "%~4"=="--dry-run" (
  echo Missing runner value after --runner
  goto :usage
) else (
  echo Invalid runner value: %~4. Use 'codex' or 'kimi'.
  goto :usage
)
rem Check %5 for --dry-run
if /I "%~5"=="--dry-run" (
  set "DRY_RUN_FLAG=--dry-run"
) else if not "%~5"=="" (
  echo Unexpected argument after runner: %~5
  goto :usage
)
goto :parse_done

:parse_done
py -3 "%SCRIPT_DIR%StartLoopsInWT.py" "%PROJECT_ROOT%" "%AGENT_PATH%" %RUNNER_FLAG% %DRY_RUN_FLAG%
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo WT launcher failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

exit /b 0

:usage
echo Usage: %~nx0 ^<project_root^> [agent_path] [--runner codex^|kimi] [--dry-run]
echo Example 1: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Orchestrator
echo Example 2: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Workers\Worker_001
echo Example 3: %~nx0 "%LOOPER_ROOT%\..\Talker"
echo Example 4: %~nx0 "%LOOPER_ROOT%\..\Talker" --dry-run
echo Example 5: %~nx0 "%LOOPER_ROOT%\..\ProjectFolder_Template" Workers\Worker_001 --dry-run
echo Example 6: %~nx0 "%LOOPER_ROOT%\..\Talker" . --runner kimi
echo.
echo Options:
echo   --runner codex^|kimi   Choose CLI agent (default: codex)
echo   --dry-run             Print command without launching WT
exit /b 1
