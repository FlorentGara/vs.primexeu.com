@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo Starting VS Tools...
echo Website: http://127.0.0.1:8791/login
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_web_dashboard.ps1" 1>> "%~dp0logs\vs-tools.out.log" 2>> "%~dp0logs\vs-tools.err.log"
echo.
echo Website stopped or failed. Check logs\vs-tools.err.log
pause
