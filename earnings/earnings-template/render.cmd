@echo off
setlocal
if "%~1"=="" goto usage
if "%~2"=="" (
  node "%~dp0render.mjs" "%~f1"
) else (
  node "%~dp0render.mjs" "%~f1" "%~f2"
)
if errorlevel 1 (
  pause
  exit /b 1
)
exit /b 0
:usage
echo Usage: render.cmd "input.json" ["output-folder"]
echo You can also drag a prepared JSON file onto this script.
pause
exit /b 1
