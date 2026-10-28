@echo off
set "SCRIPT=%~dp0install_vs_dashboard_autostart.ps1"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%"
if errorlevel 1 (
  echo.
  echo Installation failed. Right-click this file and choose Run as administrator.
  pause
  exit /b 1
)
echo.
echo VS dashboard startup task is installed.
pause
