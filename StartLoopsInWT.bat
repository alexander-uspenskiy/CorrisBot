@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "DEFAULT_CONFIG=%SCRIPT_DIR%Plans\loops.wt.json"
set "CONFIG_PATH="
set "PROJECT_ROOT_OVERRIDE="
set "DRY_RUN_FLAG="

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--help" goto :usage
if /I "%~1"=="--dry-run" (
  set "DRY_RUN_FLAG=--dry-run"
  shift
  goto :parse_args
)
if not defined CONFIG_PATH (
  set "CONFIG_PATH=%~1"
  shift
  goto :parse_args
)
if not defined PROJECT_ROOT_OVERRIDE (
  set "PROJECT_ROOT_OVERRIDE=%~1"
  shift
  goto :parse_args
)
echo Unexpected argument: %~1
goto :usage

:args_done
if not defined CONFIG_PATH (
  set "CONFIG_PATH=%DEFAULT_CONFIG%"
)

if defined PROJECT_ROOT_OVERRIDE (
  py -3 "%SCRIPT_DIR%StartLoopsInWT.py" --config-path "%CONFIG_PATH%" --project-root-override "%PROJECT_ROOT_OVERRIDE%" %DRY_RUN_FLAG%
) else (
  py -3 "%SCRIPT_DIR%StartLoopsInWT.py" --config-path "%CONFIG_PATH%" %DRY_RUN_FLAG%
)

set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo WT launcher failed with exit code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)

exit /b 0

:usage
echo Usage: %~nx0 [config_path] [project_root_override] [--dry-run]
echo Example 1: %~nx0
echo Example 2: %~nx0 C:\CorrisBot\Looper\Plans\loops.wt.json
echo Example 3: %~nx0 C:\CorrisBot\Looper\Plans\loops.wt.json C:\CorrisBot\ProjectFolder_Template\.CorrisBot --dry-run
exit /b 0
