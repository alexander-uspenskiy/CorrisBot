@echo off
cd /d C:\CorrisBot\Looper

rem Legacy launch (PowerShell):
rem pwsh -ExecutionPolicy Bypass -File .\codex_prompt_fileloop.ps1

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_root^> [agent_path]
  echo Example 1: %~nx0 C:\CorrisBot\ProjectFolder_Template Executors\Executor_001
  echo Example 2: %~nx0 C:\CorrisBot\Talker
  pause
  exit /b 1
)

set "AGENT_PATH=%~2"
if "%AGENT_PATH%"=="" set "AGENT_PATH=."

py -3 .\codex_prompt_fileloop.py --project-root "%~1" --agent-path "%AGENT_PATH%" --dangerously-bypass-sandbox
pause
