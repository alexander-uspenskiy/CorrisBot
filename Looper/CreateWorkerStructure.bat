@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "SCRIPT_DIR_DEFAULT=%%~fI"
for %%I in ("%SCRIPT_DIR_DEFAULT%\..") do set "REPO_ROOT_DEFAULT=%%~fI"
set "LOOPER_ROOT_DEFAULT=%SCRIPT_DIR_DEFAULT%"
set "TALKER_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\Talker"
set "TEMPLATE_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\ProjectFolder_Template"
set "SOURCE_ROOT_DEFAULT=%TEMPLATE_ROOT_DEFAULT%\Workers\Worker_001"

if "%REPO_ROOT%"=="" (set "REPO_ROOT=%REPO_ROOT_DEFAULT%") else (for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI")
if "%LOOPER_ROOT%"=="" (set "LOOPER_ROOT=%LOOPER_ROOT_DEFAULT%") else (for %%I in ("%LOOPER_ROOT%") do set "LOOPER_ROOT=%%~fI")
if "%TALKER_ROOT%"=="" (set "TALKER_ROOT=%TALKER_ROOT_DEFAULT%") else (for %%I in ("%TALKER_ROOT%") do set "TALKER_ROOT=%%~fI")
if "%TEMPLATE_ROOT%"=="" (set "TEMPLATE_ROOT=%TEMPLATE_ROOT_DEFAULT%") else (for %%I in ("%TEMPLATE_ROOT%") do set "TEMPLATE_ROOT=%%~fI")
if "%SOURCE_ROOT%"=="" (set "SOURCE_ROOT=%SOURCE_ROOT_DEFAULT%") else (for %%I in ("%SOURCE_ROOT%") do set "SOURCE_ROOT=%%~fI")

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
if not "%~3"=="" goto :usage

set "SUBFOLDER_NAME=%~1"
set "ORCHESTRATOR_NAME=%~2"
set "DEST_ROOT=%CD%\%SUBFOLDER_NAME%"

echo [PATHS] REPO_ROOT=%REPO_ROOT%
echo [PATHS] LOOPER_ROOT=%LOOPER_ROOT%
echo [PATHS] TALKER_ROOT=%TALKER_ROOT%
echo [PATHS] TEMPLATE_ROOT=%TEMPLATE_ROOT%
echo [PATHS] SOURCE_ROOT=%SOURCE_ROOT%

if not exist "%SOURCE_ROOT%\" (
  echo Source template folder not found: "%SOURCE_ROOT%"
  exit /b 2
)

if not exist "%DEST_ROOT%\" (
  mkdir "%DEST_ROOT%" || (
    echo Failed to create destination root: "%DEST_ROOT%"
    exit /b 4
  )
)

for %%D in (Output Plans Temp Tools) do (
  if not exist "%SOURCE_ROOT%\%%D\" (
    echo Missing required source directory: "%SOURCE_ROOT%\%%D"
    exit /b 5
  )
  if not exist "%DEST_ROOT%\%%D\" (
    mkdir "%DEST_ROOT%\%%D" || (
      echo Failed to create directory: "%DEST_ROOT%\%%D"
      exit /b 6
    )
  )
)

if not exist "%SOURCE_ROOT%\Prompts\Inbox\" (
  echo Missing required source directory: "%SOURCE_ROOT%\Prompts\Inbox"
  exit /b 5
)

if not exist "%DEST_ROOT%\Prompts\" (
  mkdir "%DEST_ROOT%\Prompts" || (
    echo Failed to create directory: "%DEST_ROOT%\Prompts"
    exit /b 6
  )
)
if not exist "%DEST_ROOT%\Prompts\Inbox\" (
  mkdir "%DEST_ROOT%\Prompts\Inbox" || (
    echo Failed to create directory: "%DEST_ROOT%\Prompts\Inbox"
    exit /b 6
  )
)
if not exist "%DEST_ROOT%\Prompts\Inbox\%ORCHESTRATOR_NAME%\" (
  mkdir "%DEST_ROOT%\Prompts\Inbox\%ORCHESTRATOR_NAME%" || (
    echo Failed to create directory: "%DEST_ROOT%\Prompts\Inbox\%ORCHESTRATOR_NAME%"
    exit /b 6
  )
)

for %%F in (Info.md ROLE_WORKER.md agent_runner.json codex_profile.json kimi_profile.json) do (
  if not exist "%SOURCE_ROOT%\%%F" (
    echo Missing required source file: "%SOURCE_ROOT%\%%F"
    exit /b 7
  )
  if not exist "%DEST_ROOT%\%%F" (
    copy /Y "%SOURCE_ROOT%\%%F" "%DEST_ROOT%\%%F" >nul || (
      echo Failed to copy file: %%F
      exit /b 8
    )
  )
)

if not exist "%DEST_ROOT%\AGENTS.md" (
  py "%~dp0assemble_agents.py" "%SOURCE_ROOT%\AGENTS_TEMPLATE.md" "%DEST_ROOT%\AGENTS.md"
  if errorlevel 1 (
    echo Failed to assemble Worker AGENTS.md
    exit /b 8
  )
)

echo Structure ensured successfully: "%DEST_ROOT%"
exit /b 0

:usage
echo Usage: %~nx0 ^<subfolder_name^> ^<orchestrator_name^>
echo Creates new worker structure in current directory.
echo Example: %~nx0 Worker_002 Orc1
exit /b 1
