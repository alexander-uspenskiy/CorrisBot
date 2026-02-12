@echo off
cd /d C:\CorrisBot\Looper

rem Legacy launch (PowerShell):
rem pwsh -ExecutionPolicy Bypass -File .\codex_prompt_fileloop.ps1

if "%~1"=="" (
  echo Usage: %~nx0 ^<exchange_dir^>
  echo Example: %~nx0 C:\CorrisBot\Looper\Prompts
  pause
  exit /b 1
)

py -3 .\codex_prompt_fileloop.py --exchange-dir "%~1" --dangerously-bypass-sandbox
pause
