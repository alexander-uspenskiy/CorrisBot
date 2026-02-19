@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "SCRIPT_DIR_DEFAULT=%%~fI"
for %%I in ("%SCRIPT_DIR_DEFAULT%\..") do set "REPO_ROOT_DEFAULT=%%~fI"
set "TEMPLATE_ROOT_DEFAULT=%REPO_ROOT_DEFAULT%\ProjectFolder_Template"

if "%TEMPLATE_ROOT%"=="" (set "TEMPLATE_ROOT=%TEMPLATE_ROOT_DEFAULT%") else (for %%I in ("%TEMPLATE_ROOT%") do set "TEMPLATE_ROOT=%%~fI")

if "%~1"=="" goto :usage
if not "%~2"=="" goto :usage

set "REPO_ROOT=%~1"
for %%I in ("%REPO_ROOT%") do set "REPO_ROOT=%%~fI"

echo [PATHS] TEMPLATE_ROOT=%TEMPLATE_ROOT%
echo [PATHS] REPO_ROOT=%REPO_ROOT%

if not exist "%TEMPLATE_ROOT%\" (
  echo Source template root not found: "%TEMPLATE_ROOT%"
  exit /b 2
)

if not exist "%TEMPLATE_ROOT%\gitignore_template.txt" (
  echo Missing gitignore template: "%TEMPLATE_ROOT%\gitignore_template.txt"
  exit /b 3
)

if not exist "%REPO_ROOT%\" (
  mkdir "%REPO_ROOT%" || (
    echo Failed to create repo root: "%REPO_ROOT%"
    exit /b 4
  )
)

git --version >nul 2>&1 || (
  echo Git is not available in PATH
  exit /b 5
)

if not exist "%REPO_ROOT%\.git" (
  echo Initializing git repository in "%REPO_ROOT%"
  git -C "%REPO_ROOT%" init >nul 2>&1 || (
    echo Failed to initialize git repository: "%REPO_ROOT%"
    exit /b 6
  )
)

copy /Y "%TEMPLATE_ROOT%\gitignore_template.txt" "%REPO_ROOT%\.gitignore" >nul || (
  echo Failed to copy .gitignore template to "%REPO_ROOT%\.gitignore"
  exit /b 7
)
echo .gitignore synchronized from template

git -C "%REPO_ROOT%" rev-parse --verify HEAD >nul 2>&1
if errorlevel 1 (
  echo No commits detected, creating initial repository bootstrap commit
  git -C "%REPO_ROOT%" add . >nul 2>&1 || (
    echo Failed to stage files for bootstrap commit
    exit /b 8
  )
  git -C "%REPO_ROOT%" commit -m "Initial repository bootstrap" >nul 2>&1 || (
    echo Failed to create initial repository bootstrap commit
    echo Ensure git user.name and user.email are configured
    exit /b 9
  )
  echo Initial repository bootstrap commit created
) else (
  echo Existing commit history detected, bootstrap commit skipped
)

echo Repository ensured successfully: "%REPO_ROOT%"
exit /b 0

:usage
echo Usage: %~nx0 ^<repo_root_path^>
echo Ensures git repository bootstrap in ^<repo_root_path^>
echo Example: %~nx0 C:\Temp\.EnsureRepo_Test_01
exit /b 1
