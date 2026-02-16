@echo off
cd /d C:\CorrisBot\Looper
chcp 65001 >nul 2>&1
set PYTHONIOENCODING=utf-8

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_root^> [agent_path]
  echo Example: %~nx0 C:\CorrisBot\Talker
  pause
  exit /b 1
)

set "AGENT_PATH=%~2"
if "%AGENT_PATH%"=="" set "AGENT_PATH=."

py -3 .\codex_prompt_fileloop.py --project-root "%~1" --agent-path "%AGENT_PATH%" --runner kimi
pause
