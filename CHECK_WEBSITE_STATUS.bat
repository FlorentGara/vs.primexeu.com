@echo off
echo Checking port 8780...
powershell.exe -NoProfile -Command "Get-NetTCPConnection -LocalPort 8780 -ErrorAction SilentlyContinue | Select-Object LocalAddress,LocalPort,State,OwningProcess; try { (Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:8780/' -TimeoutSec 5).StatusCode } catch { $_.Exception.Message }"
pause
