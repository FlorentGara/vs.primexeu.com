@echo off
echo Checking VS Tools on port 8791...
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8791 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess; try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8791/login' -TimeoutSec 5).StatusCode } catch { $_.Exception.Message }"
pause
