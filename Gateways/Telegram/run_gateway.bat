@echo off
setlocal
set PATH=%PATH%;%APPDATA%\npm

set "TALKER_ROOT=C:\CorrisBot\Talker"
set "LOOPER_ROOT=C:\CorrisBot\Looper"
set "WORKDIR=C:\CorrisBot\Gateways\Telegram"
set "WT_WINDOW=CorrisBot"

rem Read runner from loops.wt.json (default: codex)
for /f "delims=" %%R in ('py -3 -c "import json,pathlib; c=json.loads(pathlib.Path(r'%LOOPER_ROOT%\Plans\loops.wt.json').read_text()); print(c.get('runner','codex'))"') do set "RUNNER=%%R"
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
py "%LOOPER_ROOT%\assemble_agents.py" "%TALKER_ROOT%\AGENTS_TEMPLATE.md" "%TALKER_ROOT%\AGENTS.md"
if errorlevel 1 (
  echo [ERROR] Failed to assemble Talker AGENTS.md
  pause
  exit /b 1
)

:run_wt
"%WT_EXE%" -w "%WT_WINDOW%" new-tab --title "Telegram Gateway" --suppressApplicationTitle cmd /k cd /d "%WORKDIR%" ^&^& set "GATEWAY_SKIP_TALKER_BOOT=1" ^&^& py tg_codex_gateway.py "%TALKER_ROOT%" ; split-pane -V --title "Talker/%RUNNER% [Talker/Agents-01]" --suppressApplicationTitle cmd /k ""%LOOP_BAT%" "%TALKER_ROOT%" ".""
if %errorlevel%==0 exit /b 0
echo [WARN] Failed to start Windows Terminal tab, fallback to direct run.

:run_fallback
cd /d "%WORKDIR%"
py tg_codex_gateway.py "%TALKER_ROOT%"
pause
