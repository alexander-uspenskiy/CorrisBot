@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "LOOPER_ROOT_DEFAULT=%%~fI"
for %%I in ("%LOOPER_ROOT_DEFAULT%\..") do set "REPO_ROOT_DEFAULT=%%~fI"
set "TEMPLATE_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\ProjectFolder_Template"

if "%REPO_ROOT%"=="" (set "REPO_ROOT=%REPO_ROOT_DEFAULT%") else (for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI")
if "%LOOPER_ROOT%"=="" (set "LOOPER_ROOT=%LOOPER_ROOT_DEFAULT%") else (for %%I in ("%LOOPER_ROOT%") do set "LOOPER_ROOT=%%~fI")
if "%TEMPLATE_ROOT%"=="" (set "TEMPLATE_ROOT=%TEMPLATE_ROOT_DEFAULT%") else (for %%I in ("%TEMPLATE_ROOT%") do set "TEMPLATE_ROOT=%%~fI")

rem Legacy launch (PowerShell):
rem pwsh -ExecutionPolicy Bypass -File .\codex_prompt_fileloop.ps1

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_root^> [agent_path]
  echo Example 1: %~nx0 "%TEMPLATE_ROOT%" Workers\Worker_001
  echo Example 2: %~nx0 "%REPO_ROOT%\Talker"
  echo [PATHS] REPO_ROOT=%REPO_ROOT%
  echo [PATHS] LOOPER_ROOT=%LOOPER_ROOT%
  echo [PATHS] TEMPLATE_ROOT=%TEMPLATE_ROOT%
  pause
  exit /b 1
)

set "PROJECT_ROOT=%~1"
for %%I in ("%PROJECT_ROOT%") do set "PROJECT_ROOT=%%~fI"
set "TALKER_ROOT=%PROJECT_ROOT%"

cd /d "%LOOPER_ROOT%" || (
  echo Failed to switch to LOOPER_ROOT: "%LOOPER_ROOT%"
  pause
  exit /b 2
)

echo [PATHS] REPO_ROOT=%REPO_ROOT%
echo [PATHS] LOOPER_ROOT=%LOOPER_ROOT%
echo [PATHS] TALKER_ROOT=%TALKER_ROOT%

set "AGENT_PATH=%~2"
if "%AGENT_PATH%"=="" set "AGENT_PATH=."
set "AGENT_DIR=%PROJECT_ROOT%"
if /I not "%AGENT_PATH%"=="." set "AGENT_DIR=%PROJECT_ROOT%\%AGENT_PATH%"
set "TALKER_ROUTING_FLAG="
if exist "%AGENT_DIR%\ROLE_TALKER.md" set "TALKER_ROUTING_FLAG=--talker-routing"

py -3 .\codex_prompt_fileloop.py --project-root "%PROJECT_ROOT%" --agent-path "%AGENT_PATH%" --runner codex --dangerously-bypass-sandbox %TALKER_ROUTING_FLAG%
pause
