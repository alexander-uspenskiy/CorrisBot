@echo off
setlocal
set PATH=%PATH%;%APPDATA%\npm

set "TALKER_ROOT=C:\CorrisBot\Talker"
set "WORKDIR=C:\CorrisBot\Gateways\Telegram"
set "WT_WINDOW=CorrisBot-Talker"
set "WT_EXE="
if not exist "%TALKER_ROOT%\" (
  echo [ERROR] TALKER_ROOT not found: %TALKER_ROOT%
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
    goto :run_wt
  )
)
if not defined WT_EXE goto :run_fallback

:run_wt
"%WT_EXE%" -w "%WT_WINDOW%" new-tab --title "Telegram Gateway" cmd /k cd /d "%WORKDIR%" ^&^& py tg_codex_gateway.py "%TALKER_ROOT%"
if %errorlevel%==0 exit /b 0
echo [WARN] Failed to start Windows Terminal tab, fallback to direct run.

:run_fallback
cd /d "%WORKDIR%"
py tg_codex_gateway.py "%TALKER_ROOT%"
pause
