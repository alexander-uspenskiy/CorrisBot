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

echo [PATHS] REPO_ROOT=%REPO_ROOT%
echo [PATHS] LOOPER_ROOT=%LOOPER_ROOT%
echo [PATHS] TALKER_ROOT=%TALKER_ROOT%
echo [PATHS] TEMPLATE_ROOT=%TEMPLATE_ROOT%
echo [PATHS] WORKDIR=%WORKDIR%

rem Read runner from loops.wt.json (default: codex)
set "RUNNER=codex"
for /f "delims=" %%R in ('py -3 -c "import json,pathlib; p=pathlib.Path(r'%REPO_ROOT%\loops.wt.json'); print((json.loads(p.read_text(encoding='utf-8')).get('runner','codex') if p.exists() else 'codex'))" 2^>nul') do set "RUNNER=%%R"
if not "%RUNNER%"=="kimi" set "RUNNER=codex"

rem Determine loop bat file based on runner
if "%RUNNER%"=="kimi" (
  set "LOOP_BAT=%LOOPER_ROOT%\KimiLoop.bat"
) else (
  set "LOOP_BAT=%LOOPER_ROOT%\CodexLoop.bat"
)

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
if not exist "%LOOP_BAT%" (
  echo [ERROR] %RUNNER% loop bat not found: %LOOP_BAT%
  pause
  exit /b 1
)

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
echo [BOOT] Runner: %RUNNER%
echo [BOOT] Environment REPO_ROOT=%REPO_ROOT%
echo [BOOT] Environment LOOPER_ROOT=%LOOPER_ROOT%
echo [BOOT] Environment TALKER_ROOT=%TALKER_ROOT%
py "%LOOPER_ROOT%\assemble_agents.py" "%TALKER_ROOT%\AGENTS_TEMPLATE.md" "%TALKER_ROOT%\AGENTS.md"
if errorlevel 1 (
  echo [ERROR] Failed to assemble Talker AGENTS.md
  pause
  exit /b 1
)

:run_wt
"%WT_EXE%" -w "%WT_WINDOW%" new-tab --title "Telegram Gateway" --suppressApplicationTitle cmd /k set "REPO_ROOT=%REPO_ROOT%" ^&^& set "LOOPER_ROOT=%LOOPER_ROOT%" ^&^& set "TALKER_ROOT=%TALKER_ROOT%" ^&^& set "TEMPLATE_ROOT=%TEMPLATE_ROOT%" ^&^& cd /d "%WORKDIR%" ^&^& set "GATEWAY_SKIP_TALKER_BOOT=1" ^&^& py tg_codex_gateway.py "%TALKER_ROOT%" ; split-pane -V --title "Talker/%RUNNER% [Talker/Agents-01]" --suppressApplicationTitle cmd /k set "REPO_ROOT=%REPO_ROOT%" ^&^& set "LOOPER_ROOT=%LOOPER_ROOT%" ^&^& set "TALKER_ROOT=%TALKER_ROOT%" ^&^& set "TEMPLATE_ROOT=%TEMPLATE_ROOT%" ^&^& call "%LOOP_BAT%" "%TALKER_ROOT%" "."
if %errorlevel%==0 exit /b 0
echo [WARN] Failed to start Windows Terminal tab, fallback to direct run.

:run_fallback
cd /d "%WORKDIR%"
py tg_codex_gateway.py "%TALKER_ROOT%"
pause
