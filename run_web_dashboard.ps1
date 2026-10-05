$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot

$env:VS_DASHBOARD_HOST = "0.0.0.0"
$env:VS_DASHBOARD_PORT = "8780"
$env:VS_FILE_ROOT = "\\192.168.10.8\klientat\05_CLIENTS\02_VS\00_TEMPLATE\FILLED\AMAZON\01_WINE-SPIRITS\FINAL\PICTURE"
$env:VS_SCRIPT_ROOT = $PSScriptRoot

py -3 -m waitress --host=$env:VS_DASHBOARD_HOST --port=$env:VS_DASHBOARD_PORT web_dashboard:app
