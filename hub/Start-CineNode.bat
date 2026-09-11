@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-CineNode.ps1" %*
if errorlevel 1 (
  echo.
  echo CineNode did not start. See the message above.
  pause
)
