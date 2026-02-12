@echo off
setlocal

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_path_or_dotCorrisBot_path^>
  echo Example 1: %~nx0 C:\CorrisBot\ProjectFolder_Template
  echo Example 2: %~nx0 C:\CorrisBot\ProjectFolder_Template\.CorrisBot
  pause
  exit /b 1
)

set "INPUT_PATH=%~1"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$inputPath = [System.IO.Path]::GetFullPath('%INPUT_PATH%');" ^
  "if (-not (Test-Path -LiteralPath $inputPath)) { throw \"Path not found: $inputPath\" };" ^
  "$dot = Join-Path $inputPath '.CorrisBot';" ^
  "if (Test-Path -LiteralPath $dot) { $root = $dot } else { $root = $inputPath };" ^
  "Write-Host ('Cleanup root: ' + $root);" ^
  "$promptsDirs = Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter 'Prompts' -ErrorAction SilentlyContinue;" ^
  "if (-not $promptsDirs) { Write-Host 'No Prompts directories found.'; exit 0 };" ^
  "$preserve = @('Info.md','.info.md');" ^
  "function Clear-KeepInfo([string]$dir) {" ^
  "  Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {" ^
  "    if ($_.PSIsContainer) {" ^
  "      Clear-KeepInfo $_.FullName;" ^
  "      $left = Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue;" ^
  "      if (-not $left) { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }" ^
  "    } else {" ^
  "      if ($preserve -notcontains $_.Name) { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue }" ^
  "    }" ^
  "  }" ^
  "};" ^
  "foreach ($p in $promptsDirs) {" ^
  "  Write-Host ('Cleaning: ' + $p.FullName);" ^
  "  Clear-KeepInfo $p.FullName;" ^
  "};" ^
  "Write-Host 'Done.'"

if errorlevel 1 (
  echo Cleanup failed.
  pause
  exit /b 1
)

echo Cleanup completed.
pause
exit /b 0
