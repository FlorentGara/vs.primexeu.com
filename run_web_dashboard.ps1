$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:VS_DASHBOARD_HOST = '127.0.0.1'
$env:VS_DASHBOARD_PORT = '8791'
$env:VS_ROOT = '\\192.168.10.8\klientat\05_CLIENTS\02_VS\00_TEMPLATE\FILLED\AMAZON\01_WINE-SPIRITS\FINAL\PICTURE'
if (-not (Test-Path -LiteralPath $env:VS_ROOT)) { throw "VS_ROOT is unavailable: $env:VS_ROOT" }
py -3.11 hetzner_url_dashboard.py
