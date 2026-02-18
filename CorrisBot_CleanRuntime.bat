@echo off
setlocal EnableExtensions EnableDelayedExpansion

if /I "%~1"=="--help" goto :usage
if /I "%~1"=="-h" goto :usage
if /I "%~1"=="--force" (
  set "FORCE=1"
) else (
  if not "%~1"=="" (
    echo [ERROR] Unknown argument: %~1
    goto :usage_error
  )
  set "FORCE=0"
)

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"
set "TALKER_ROOT=%REPO_ROOT%\Talker"
set "GATEWAY_ROOT=%REPO_ROOT%\Gateways\Telegram"

set "TALKER_PROMPTS=%TALKER_ROOT%\Prompts"
set "TALKER_TEMP=%TALKER_ROOT%\Temp"
set "GATEWAY_SESSIONS=%GATEWAY_ROOT%\sessions"
set "GATEWAY_PROMPTS=%GATEWAY_ROOT%\prompts"
set "GATEWAY_EXPORTS=%GATEWAY_ROOT%\exports"
set "GATEWAY_TEMP=%GATEWAY_ROOT%\_Temp"
set "GATEWAY_STATE=%GATEWAY_ROOT%\gateway_delivery_state.json"
set "GATEWAY_LOCK=%GATEWAY_ROOT%\.gateway.lock"
set "ROUTING_STATE=%TALKER_PROMPTS%\Inbox\routing_state.json"

set "FAILED=0"

echo [CLEAN] REPO_ROOT=%REPO_ROOT%

call :ensure_safe_to_clean
if errorlevel 1 (
  echo [ERROR] Cleanup aborted.
  exit /b 1
)

if "%FORCE%"=="0" (
  echo [WARN] This will delete runtime prompts/sessions/temp artifacts.
  set /p "CONFIRM=Type YES to continue: "
  set "CONFIRM=!CONFIRM:"=!"
  for /f "tokens=* delims= " %%A in ("!CONFIRM!") do set "CONFIRM=%%A"
  set "CONFIRM=!CONFIRM: =!"
  if /I "!CONFIRM!"=="YES" goto :confirm_ok
  if /I "!CONFIRM!"=="Y" goto :confirm_ok
  (
    echo [INFO] Cleanup canceled by user.
    exit /b 1
  )
)
:confirm_ok

call :reset_dir "%TALKER_PROMPTS%"
call :reset_dir "%TALKER_TEMP%"
call :reset_dir "%GATEWAY_SESSIONS%"
call :reset_dir "%GATEWAY_PROMPTS%"
call :reset_dir "%GATEWAY_EXPORTS%"
call :reset_dir "%GATEWAY_TEMP%"

call :delete_file "%GATEWAY_STATE%"
call :delete_file "%GATEWAY_LOCK%"

call :ensure_dir "%TALKER_PROMPTS%\Inbox"
call :ensure_dir "%TALKER_PROMPTS%\Inbox\Talker"

> "%ROUTING_STATE%" echo {"user_sender_id":"","updated_at":"","updated_by":"CorrisBot_CleanRuntime.bat"}
if errorlevel 1 (
  echo [ERROR] Failed to write routing state: "%ROUTING_STATE%"
  set "FAILED=1"
) else (
  echo [OK] Reset routing state: "%ROUTING_STATE%"
)

if "%FAILED%"=="0" (
  echo [OK] Runtime cleanup completed.
  exit /b 0
)

echo [ERROR] Runtime cleanup completed with errors.
exit /b 1

:reset_dir
set "DIR=%~1"
if exist "%DIR%\" (
  echo [CLEAN] Reset dir: "%DIR%"
  rmdir /s /q "%DIR%"
  if errorlevel 1 (
    echo [ERROR] Failed to remove dir: "%DIR%"
    set "FAILED=1"
    goto :eof
  )
)
mkdir "%DIR%" 2>nul
if exist "%DIR%\" (
  echo [OK] Ready dir: "%DIR%"
) else (
  echo [ERROR] Failed to create dir: "%DIR%"
  set "FAILED=1"
)
goto :eof

:ensure_dir
set "DIR=%~1"
if not exist "%DIR%\" (
  mkdir "%DIR%" 2>nul
)
if exist "%DIR%\" (
  echo [OK] Ensured dir: "%DIR%"
) else (
  echo [ERROR] Failed to ensure dir: "%DIR%"
  set "FAILED=1"
)
goto :eof

:delete_file
set "FILE=%~1"
if exist "%FILE%" (
  del /f /q "%FILE%"
  if errorlevel 1 (
    echo [ERROR] Failed to delete file: "%FILE%"
    set "FAILED=1"
  ) else (
    echo [OK] Deleted file: "%FILE%"
  )
)
goto :eof

:ensure_safe_to_clean
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$repo = [System.IO.Path]::GetFullPath('%REPO_ROOT%');" ^
  "$procs = Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and (($_.CommandLine -match 'tg_codex_gateway\.py') -or ($_.CommandLine -match 'codex_prompt_fileloop\.py')) -and ($_.CommandLine -like ('*' + $repo + '*')) };" ^
  "if ($procs) {" ^
  "  Write-Host '[ERROR] Active looper/gateway processes detected for this repo:';" ^
  "  $procs | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize | Out-String | Write-Host;" ^
  "  exit 2" ^
  "}"
if errorlevel 1 (
  echo [ERROR] Stop running Talker/Gateway/Looper processes and retry.
  exit /b 1
)
goto :eof

:usage
echo Usage: %~nx0 [--force]
echo Cleans runtime state for reproducible local tests:
echo   - Talker\Prompts
echo   - Talker\Temp
echo   - Gateways\Telegram\sessions
echo   - Gateways\Telegram\prompts
echo   - Gateways\Telegram\exports
echo   - Gateways\Telegram\_Temp
echo   - Gateways\Telegram\gateway_delivery_state.json
echo   - Gateways\Telegram\.gateway.lock
echo   - resets Talker\Prompts\Inbox\routing_state.json
echo.
echo Without --force asks interactive confirmation.
exit /b 0

:usage_error
echo.
echo Use --help for details.
exit /b 1
