@echo off
setlocal EnableExtensions

for %%I in ("%~dp0.") do set "LOOPER_ROOT=%%~fI"
for %%I in ("%LOOPER_ROOT%\..") do set "REPO_ROOT=%%~fI"
set "PROJECT_ROOT=%REPO_ROOT%\ProjectFolder_Template"

call "%LOOPER_ROOT%\CleanupPrompts.bat" "%PROJECT_ROOT%"
exit /b %ERRORLEVEL%
