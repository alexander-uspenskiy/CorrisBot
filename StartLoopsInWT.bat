@echo off
setlocal

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%~1"
set "AGENT_PATH=%~2"
set "DRY_RUN_FLAG="

if not "%~3"=="" (
  if /I "%~3"=="--dry-run" (
    set "DRY_RUN_FLAG=--dry-run"
  ) else (
    echo Unexpected third argument: %~3
    goto :usage
  )
)

py -3 "%SCRIPT_DIR%StartLoopsInWT.py" "%PROJECT_ROOT%" "%AGENT_PATH%" %DRY_RUN_FLAG%
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo WT launcher failed with exit code %EXIT_CODE%.
  exit /b %EXIT_CODE%
)

exit /b 0

:usage
echo Usage: %~nx0 ^<project_root^> ^<agent_path^> [--dry-run]
echo Example 1: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot Orchestrator
echo Example 2: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot Executors\Executor_001
echo Example 3: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot Executors\Executor_001 --dry-run
exit /b 1
