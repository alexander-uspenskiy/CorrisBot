@echo off
setlocal
set PATH=%PATH%;%APPDATA%\npm

set "TALKER_ROOT=C:\CorrisBot\Talker"
set "LOOPER_ROOT=C:\CorrisBot\Looper"
set "WORKDIR=C:\CorrisBot\Gateways\Telegram"
set "WT_WINDOW=CorrisBot"
set "WT_EXE="
if not exist "%TALKER_ROOT%\" (
  echo [ERROR] TALKER_ROOT not found: %TALKER_ROOT%
  pause
  exit /b 1
)
if not exist "%LOOPER_ROOT%\CodexLoop.bat" (
  echo [ERROR] CodexLoop.bat not found: %LOOPER_ROOT%\CodexLoop.bat
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
py "%LOOPER_ROOT%\assemble_agents.py" "%TALKER_ROOT%\AGENTS_TEMPLATE.md" "%TALKER_ROOT%\AGENTS.md"
if errorlevel 1 (
  echo [ERROR] Failed to assemble Talker AGENTS.md
  pause
  exit /b 1
)

:run_wt
"%WT_EXE%" -w "%WT_WINDOW%" new-tab --title "Telegram Gateway" --suppressApplicationTitle cmd /k cd /d "%WORKDIR%" ^&^& set "GATEWAY_SKIP_TALKER_BOOT=1" ^&^& py tg_codex_gateway.py "%TALKER_ROOT%" ; split-pane -V --title "Talker [Talker/Agents-01]" --suppressApplicationTitle cmd /k ""%LOOPER_ROOT%\CodexLoop.bat" "%TALKER_ROOT%" ".""
if %errorlevel%==0 exit /b 0
echo [WARN] Failed to start Windows Terminal tab, fallback to direct run.

:run_fallback
cd /d "%WORKDIR%"
py tg_codex_gateway.py "%TALKER_ROOT%"
pause
