@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"
cd /d "%REPO_ROOT%" || (
  echo Failed to switch to repo root: "%REPO_ROOT%"
  exit /b 1
)

call "%REPO_ROOT%\Gateways\Telegram\run_gateway.bat"
exit /b %ERRORLEVEL%
