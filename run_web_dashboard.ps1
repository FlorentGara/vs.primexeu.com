$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:VS_DASHBOARD_HOST = '127.0.0.1'
$env:VS_DASHBOARD_PORT = '8791'
$env:VS_ROOT = 'H:\website\vs.primexeu.com\Photos'
if (-not (Test-Path -LiteralPath $env:VS_ROOT)) { throw "VS_ROOT is unavailable: $env:VS_ROOT" }
py -3.11 hetzner_url_dashboard.py
