@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo Starting VS Picture Dashboard...
echo Folder: %CD%
echo.
echo Website will be:
echo   http://127.0.0.1:8780/
echo   http://192.168.10.8:8780/
echo.
echo Leave this window open while using the website.
echo.
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_web_dashboard.ps1" 1>> "%~dp0logs\server.out.log" 2>> "%~dp0logs\server.err.log"
echo.
echo Website stopped or failed. Check:
echo   %~dp0logs\server.out.log
echo   %~dp0logs\server.err.log
pause
