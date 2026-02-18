@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "REPO_ROOT=%%~fI"

echo [RUN] Runtime cleanup launcher
echo [RUN] REPO_ROOT=%REPO_ROOT%
echo.

call "%REPO_ROOT%\CorrisBot_CleanRuntime.bat" %*
set "EXIT_CODE=%ERRORLEVEL%"

echo.
if "%EXIT_CODE%"=="0" (
  echo [OK] Cleanup finished successfully.
) else (
  echo [ERROR] Cleanup failed with exit code %EXIT_CODE%.
)
echo.
pause
exit /b %EXIT_CODE%
