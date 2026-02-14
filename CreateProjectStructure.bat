@echo off
setlocal EnableExtensions

if "%~1"=="" goto :usage
if not "%~2"=="" goto :usage

set "TEMPLATE_ROOT=C:\CorrisBot\ProjectFolder_Template"
set "DEST_PROJECT_ROOT=%~1"
set "DEST_ROOT=%DEST_PROJECT_ROOT%"

if not exist "%TEMPLATE_ROOT%\" (
  echo Source template root not found: "%TEMPLATE_ROOT%"
  exit /b 2
)

if not exist "%DEST_PROJECT_ROOT%\" (
  mkdir "%DEST_PROJECT_ROOT%" || (
    echo Failed to create project root: "%DEST_PROJECT_ROOT%"
    exit /b 3
  )
)

for %%D in ("" "Executors" "Orchestrator" "Temp" "Orchestrator\Output" "Orchestrator\Prompts" "Orchestrator\Temp" "Orchestrator\Tools" "Orchestrator\Prompts\Inbox" "Orchestrator\Prompts\Inbox\Talker") do (
  if not exist "%TEMPLATE_ROOT%\%%~D\" (
    echo Missing required source directory: "%TEMPLATE_ROOT%\%%~D"
    exit /b 4
  )
  if not exist "%DEST_ROOT%\%%~D\" (
    mkdir "%DEST_ROOT%\%%~D" || (
      echo Failed to create directory: "%DEST_ROOT%\%%~D"
      exit /b 5
    )
  )
)

for %%F in (AGENTS.md Info.md ROLE_ORCHESTRATOR.md) do (
  if not exist "%TEMPLATE_ROOT%\Orchestrator\%%F" (
    echo Missing required source file: "%TEMPLATE_ROOT%\Orchestrator\%%F"
    exit /b 6
  )
  if not exist "%DEST_ROOT%\Orchestrator\%%F" (
    copy /Y "%TEMPLATE_ROOT%\Orchestrator\%%F" "%DEST_ROOT%\Orchestrator\%%F" >nul || (
      echo Failed to copy file: "%TEMPLATE_ROOT%\Orchestrator\%%F"
      exit /b 7
    )
  )
)

for %%D in ("" "Executors" "Orchestrator" "Temp" "Orchestrator\Output" "Orchestrator\Prompts" "Orchestrator\Temp" "Orchestrator\Tools" "Orchestrator\Prompts\Inbox\Talker") do (
  for %%N in (Info.md .Info.md) do (
    if exist "%TEMPLATE_ROOT%\%%~D\%%N" (
      if not exist "%DEST_ROOT%\%%~D\%%N" (
        copy /Y "%TEMPLATE_ROOT%\%%~D\%%N" "%DEST_ROOT%\%%~D\%%N" >nul || (
          echo Failed to copy file: "%TEMPLATE_ROOT%\%%~D\%%N"
          exit /b 8
        )
      )
    )
  )
)

echo Project structure ensured successfully: "%DEST_PROJECT_ROOT%"
exit /b 0

:usage
echo Usage: %~nx0 ^<project_root_path^>
echo Ensures base multi-agent project structure under ^<project_root_path^>
echo Example: %~nx0 C:\Temp\.CreateProjectStructure_TEST
exit /b 1
