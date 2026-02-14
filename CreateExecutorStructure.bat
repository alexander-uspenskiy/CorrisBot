@echo off
setlocal EnableExtensions

if "%~1"=="" goto :usage
if "%~2"=="" goto :usage
if not "%~3"=="" goto :usage

set "SOURCE_ROOT=C:\CorrisBot\ProjectFolder_Template\.CorrisBot\Executors\Executor_001"
set "SUBFOLDER_NAME=%~1"
set "ORCHESTRATOR_NAME=%~2"
set "DEST_ROOT=%CD%\%SUBFOLDER_NAME%"

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

for %%F in (AGENTS.md Info.md ROLE_EXECUTOR.md) do (
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

echo Structure ensured successfully: "%DEST_ROOT%"
exit /b 0

:usage
echo Usage: %~nx0 ^<subfolder_name^> ^<orchestrator_name^>
echo Creates new executor structure in current directory.
echo Example: %~nx0 Executor_002 Orc1
exit /b 1
