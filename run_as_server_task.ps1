$ErrorActionPreference = "Continue"

Set-Location -LiteralPath $PSScriptRoot

if (!(Test-Path -LiteralPath ".\logs")) {
    New-Item -ItemType Directory -Path ".\logs" | Out-Null
}

$env:VS_DASHBOARD_HOST = "0.0.0.0"
$env:VS_DASHBOARD_PORT = "8780"
$env:VS_FILE_ROOT = "\\192.168.10.8\klientat\05_CLIENTS\02_VS\00_TEMPLATE\FILLED\AMAZON\01_WINE-SPIRITS\FINAL\PICTURE"
$env:VS_BROWSE_ROOT = "\\192.168.10.8\klientat"
$env:VS_SCRIPT_ROOT = $PSScriptRoot

$python = Join-Path $PSScriptRoot "python-runtime\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    $python = "C:\Users\Administrator\Desktop\b2b\b2b h24\.venv\Scripts\python.exe"
}
if (!(Test-Path -LiteralPath $python)) {
    $python = "python"
}

"[$(Get-Date -Format s)] Starting VS Picture Dashboard from $PSScriptRoot" | Out-File -FilePath ".\logs\task.log" -Append -Encoding utf8
"& $python" | Out-File -FilePath ".\logs\task.log" -Append -Encoding utf8
& $python -m waitress --host=$env:VS_DASHBOARD_HOST --port=$env:VS_DASHBOARD_PORT web_dashboard:app 1>> ".\logs\server.out.log" 2>> ".\logs\server.err.log"
"[$(Get-Date -Format s)] Website process exited with code $LASTEXITCODE" | Out-File -FilePath ".\logs\task.log" -Append -Encoding utf8
