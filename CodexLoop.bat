@echo off
cd /d C:\CorrisBot\Looper

rem Legacy launch (PowerShell):
rem pwsh -ExecutionPolicy Bypass -File .\codex_prompt_fileloop.ps1

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_root^> ^<executor_id^>
  echo Example: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot Executor_001
  pause
  exit /b 1
)

if "%~2"=="" (
  echo Usage: %~nx0 ^<project_root^> ^<executor_id^>
  echo Example: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot Executor_001
  pause
  exit /b 1
)

py -3 .\codex_prompt_fileloop.py --project-root "%~1" --executor-id "%~2" --dangerously-bypass-sandbox
pause
