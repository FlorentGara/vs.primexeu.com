@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
start "VS Picture Dashboard" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_web_dashboard.ps1" 1^> "%~dp0logs\server.out.log" 2^> "%~dp0logs\server.err.log"
