@echo off
setlocal

if "%~1"=="" (
  echo Usage: %~nx0 ^<project_path^>
  echo Example 1: %~nx0 C:\CorrisBot\ProjectFolder_Template
  pause
  exit /b 1
)

set "INPUT_PATH=%~1"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$inputPath = [System.IO.Path]::GetFullPath('%INPUT_PATH%');" ^
  "if (-not (Test-Path -LiteralPath $inputPath)) { throw \"Path not found: $inputPath\" };" ^
  "$root = $inputPath;" ^
  "Write-Host ('Cleanup root: ' + $root);" ^
  "$promptsDirs = Get-ChildItem -LiteralPath $root -Recurse -Directory -Filter 'Prompts' -ErrorAction SilentlyContinue;" ^
  "if (-not $promptsDirs) { Write-Host 'No Prompts directories found.'; exit 0 };" ^
  "$preserve = @('Info.md','.info.md');" ^
  "function Is-ProtectedEmptyDir([string]$path) {" ^
  "  try {" ^
  "    $leaf = [System.IO.Path]::GetFileName($path);" ^
  "    $parent = [System.IO.Path]::GetDirectoryName($path);" ^
  "    $parentLeaf = if ($parent) { [System.IO.Path]::GetFileName($parent) } else { '' };" ^
  "    return (($leaf -ieq 'Talker') -and ($parentLeaf -ieq 'Inbox'));" ^
  "  } catch { return $false }" ^
  "};" ^
  "function Clear-KeepInfo([string]$dir) {" ^
  "  Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {" ^
  "    if ($_.PSIsContainer) {" ^
  "      Clear-KeepInfo $_.FullName;" ^
  "      $left = Get-ChildItem -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue;" ^
  "      if (-not $left) { if (-not (Is-ProtectedEmptyDir $_.FullName)) { Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue } }" ^
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
REM pause
exit /b 0
