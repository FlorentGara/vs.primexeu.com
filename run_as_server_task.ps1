$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.\logs')) { New-Item -ItemType Directory -Path '.\logs' | Out-Null }
"[$(Get-Date -Format s)] Starting VS Tools from $PSScriptRoot" | Out-File -FilePath '.\logs\task.log' -Append -Encoding utf8
& (Join-Path $PSScriptRoot 'run_web_dashboard.ps1') 1>> '.\logs\vs-tools.out.log' 2>> '.\logs\vs-tools.err.log'
"[$(Get-Date -Format s)] VS Tools exited with code $LASTEXITCODE" | Out-File -FilePath '.\logs\task.log' -Append -Encoding utf8
