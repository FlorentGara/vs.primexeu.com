$ErrorActionPreference = "Continue"

Set-Location -LiteralPath $PSScriptRoot

if (!(Test-Path -LiteralPath ".\logs")) {
    New-Item -ItemType Directory -Path ".\logs" | Out-Null
}

$python = "C:\Users\Administrator\Desktop\b2b\b2b h24\.venv\Scripts\python.exe"
if (!(Test-Path -LiteralPath $python)) {
    $python = "python"
}

"[$(Get-Date -Format s)] Installing requirements with $python" | Out-File -FilePath ".\logs\install.log" -Append -Encoding utf8
& $python -m pip install -r ".\requirements.txt" 1>> ".\logs\install.out.log" 2>> ".\logs\install.err.log"
"[$(Get-Date -Format s)] Install exited with code $LASTEXITCODE" | Out-File -FilePath ".\logs\install.log" -Append -Encoding utf8
