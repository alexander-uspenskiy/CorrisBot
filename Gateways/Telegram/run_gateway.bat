@echo off
setlocal EnableExtensions
set "PATH=%PATH%;%APPDATA%\npm"

for %%I in ("%~dp0.") do set "WORKDIR_DEFAULT=%%~fI"
for %%I in ("%WORKDIR_DEFAULT%\..\..") do set "REPO_ROOT_DEFAULT=%%~fI"
set "LOOPER_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\Looper"
set "TALKER_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\Talker"
set "TEMPLATE_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\ProjectFolder_Template"

if "%REPO_ROOT%"=="" (set "REPO_ROOT=%REPO_ROOT_DEFAULT%") else (for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI")
if "%LOOPER_ROOT%"=="" (set "LOOPER_ROOT=%LOOPER_ROOT_DEFAULT%") else (for %%I in ("%LOOPER_ROOT%") do set "LOOPER_ROOT=%%~fI")
if "%TALKER_ROOT%"=="" (set "TALKER_ROOT=%TALKER_ROOT_DEFAULT%") else (for %%I in ("%TALKER_ROOT%") do set "TALKER_ROOT=%%~fI")
if "%TEMPLATE_ROOT%"=="" (set "TEMPLATE_ROOT=%TEMPLATE_ROOT_DEFAULT%") else (for %%I in ("%TEMPLATE_ROOT%") do set "TEMPLATE_ROOT=%%~fI")
if "%WORKDIR%"=="" (set "WORKDIR=%WORKDIR_DEFAULT%") else (for %%I in ("%WORKDIR%") do set "WORKDIR=%%~fI")
if "%WT_WINDOW%"=="" set "WT_WINDOW=CorrisBot"
set "DRY_RUN=0"
if not "%~1"=="" (
  if /I "%~1"=="--dry-run" (
    set "DRY_RUN=1"
  ) else (
    echo [ERROR] Unsupported argument: %~1
    goto :usage
  )
)

echo [PATHS] REPO_ROOT=%REPO_ROOT%
echo [PATHS] LOOPER_ROOT=%LOOPER_ROOT%
echo [PATHS] TALKER_ROOT=%TALKER_ROOT%
echo [PATHS] TEMPLATE_ROOT=%TEMPLATE_ROOT%
echo [PATHS] WORKDIR=%WORKDIR%

set "WT_EXE="
if not exist "%TALKER_ROOT%\" (
  echo [ERROR] TALKER_ROOT not found: %TALKER_ROOT%
  pause
  exit /b 1
)
if not exist "%LOOPER_ROOT%\" (
  echo [ERROR] LOOPER_ROOT not found: %LOOPER_ROOT%
  pause
  exit /b 1
)
if not exist "%WORKDIR%\" (
  echo [ERROR] WORKDIR not found: %WORKDIR%
  pause
  exit /b 1
)

set "RESOLVE_OUT=%TEMP%\corrisbot_gateway_resolve_%RANDOM%_%RANDOM%.out"
set "RESOLVE_ERR=%TEMP%\corrisbot_gateway_resolve_%RANDOM%_%RANDOM%.err"
py -3 "%LOOPER_ROOT%\resolve_agent_config.py" --agent-dir "%TALKER_ROOT%" --format bat_env >"%RESOLVE_OUT%" 2>"%RESOLVE_ERR%"
if errorlevel 1 (
  set "RESOLVE_CODE="
  for /f "usebackq delims=" %%E in ("%RESOLVE_ERR%") do (
    if not defined RESOLVE_CODE set "RESOLVE_CODE=%%E"
  )
  if not defined RESOLVE_CODE set "RESOLVE_CODE=bridge_resolve_failed"
  echo [ERROR] Failed to resolve Talker config via bridge: %RESOLVE_CODE%
  if exist "%RESOLVE_OUT%" del /q "%RESOLVE_OUT%" >nul 2>&1
  if exist "%RESOLVE_ERR%" del /q "%RESOLVE_ERR%" >nul 2>&1
  pause
  exit /b 1
)
for /f "usebackq delims=" %%L in ("%RESOLVE_OUT%") do %%L
if exist "%RESOLVE_OUT%" del /q "%RESOLVE_OUT%" >nul 2>&1
if exist "%RESOLVE_ERR%" del /q "%RESOLVE_ERR%" >nul 2>&1

if /I "%RUNNER%"=="kimi" (
  set "LOOP_BAT=%LOOPER_ROOT%\KimiLoop.bat"
) else if /I "%RUNNER%"=="codex" (
  set "LOOP_BAT=%LOOPER_ROOT%\CodexLoop.bat"
) else (
  echo [ERROR] Resolver returned unsupported RUNNER: %RUNNER%
  pause
  exit /b 1
)
if not exist "%LOOP_BAT%" (
  echo [ERROR] %RUNNER% loop bat not found: %LOOP_BAT%
  pause
  exit /b 1
)
set "MODEL_ARG="
if defined MODEL set "MODEL_ARG= --model %MODEL%"
set "REASONING_ARG="
if defined REASONING_EFFORT set "REASONING_ARG= --reasoning-effort %REASONING_EFFORT%"

if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe" (
  set "WT_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\wt.exe"
)
if not defined WT_EXE if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\Microsoft.WindowsTerminal_8wekyb3d8bbwe\wt.exe" (
  set "WT_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\Microsoft.WindowsTerminal_8wekyb3d8bbwe\wt.exe"
)
if not defined WT_EXE (
  for /f "delims=" %%I in ('where wt 2^>nul') do (
    set "WT_EXE=%%I"
    goto :assemble
  )
)
if not defined WT_EXE goto :run_fallback

:assemble
echo [BOOT] Assembling Talker AGENTS.md ...
echo [BOOT] Effective runner: %RUNNER% ^(source=%SOURCE_RUNNER%^)
echo [BOOT] Effective model: %MODEL% ^(source=%SOURCE_MODEL%^)
echo [BOOT] Effective reasoning: %REASONING_EFFORT% ^(source=%SOURCE_REASONING%^)
echo [BOOT] Environment REPO_ROOT=%REPO_ROOT%
echo [BOOT] Environment LOOPER_ROOT=%LOOPER_ROOT%
echo [BOOT] Environment TALKER_ROOT=%TALKER_ROOT%
py "%LOOPER_ROOT%\assemble_agents.py" "%TALKER_ROOT%\AGENTS_TEMPLATE.md" "%TALKER_ROOT%\AGENTS.md"
if errorlevel 1 (
  echo [ERROR] Failed to assemble Talker AGENTS.md
  pause
  exit /b 1
)
if "%DRY_RUN%"=="1" (
  echo [dry-run] Gateway cmd: py tg_codex_gateway.py "%TALKER_ROOT%"
  echo [dry-run] Talker cmd: call "%LOOP_BAT%" "%TALKER_ROOT%" "."%MODEL_ARG%%REASONING_ARG%
  echo [dry-run] WT window: %WT_WINDOW%
  exit /b 0
)

:run_wt
"%WT_EXE%" -w "%WT_WINDOW%" new-tab --title "Telegram Gateway" --suppressApplicationTitle cmd /k set "REPO_ROOT=%REPO_ROOT%" ^&^& set "LOOPER_ROOT=%LOOPER_ROOT%" ^&^& set "TALKER_ROOT=%TALKER_ROOT%" ^&^& set "TEMPLATE_ROOT=%TEMPLATE_ROOT%" ^&^& cd /d "%WORKDIR%" ^&^& set "GATEWAY_SKIP_TALKER_BOOT=1" ^&^& py tg_codex_gateway.py "%TALKER_ROOT%" ; split-pane -V --title "Talker/%RUNNER% [Talker/Agents-01]" --suppressApplicationTitle cmd /k set "REPO_ROOT=%REPO_ROOT%" ^&^& set "LOOPER_ROOT=%LOOPER_ROOT%" ^&^& set "TALKER_ROOT=%TALKER_ROOT%" ^&^& set "TEMPLATE_ROOT=%TEMPLATE_ROOT%" ^&^& call "%LOOP_BAT%" "%TALKER_ROOT%" "."%MODEL_ARG%%REASONING_ARG%
if %errorlevel%==0 exit /b 0
echo [WARN] Failed to start Windows Terminal tab, fallback to direct run.

:run_fallback
cd /d "%WORKDIR%"
py tg_codex_gateway.py "%TALKER_ROOT%"
pause
exit /b 0

:usage
echo Usage: %~nx0 [--dry-run]
exit /b 1
