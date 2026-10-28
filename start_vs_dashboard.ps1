$ErrorActionPreference = 'Stop'

$projectRoot = 'E:\websites\vs.primexeu.com'
$logRoot = Join-Path $projectRoot 'logs'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$app = Join-Path $projectRoot 'hetzner_url_dashboard.py'
$stdout = Join-Path $logRoot 'photos-server.out.log'
$stderr = Join-Path $logRoot 'photos-server.err.log'

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
Start-Sleep -Seconds 45

$listeners = @(Get-NetTCPConnection -LocalPort 8792 -State Listen -ErrorAction SilentlyContinue)
if ($listeners.Count -gt 0) {
    $ownedByDashboard = $false
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine -match 'hetzner_url_dashboard\.py') {
            $ownedByDashboard = $true
        }
    }
    if ($ownedByDashboard) { exit 0 }
    Add-Content -LiteralPath $stderr -Value "$(Get-Date -Format o) Port 8792 is already occupied by another process."
    exit 1
}

if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath $app)) {
    Add-Content -LiteralPath $stderr -Value "$(Get-Date -Format o) Python environment or dashboard script was not found."
    exit 1
}

$env:VS_ROOT = Join-Path $projectRoot 'Photos'
$env:VS_BASE_URL = 'https://vs.primexeu.com/photos/'
$env:VS_DASHBOARD_HOST = '127.0.0.1'
$env:VS_DASHBOARD_PORT = '8792'
$env:USERPROFILE = 'C:\Users\Administrator'

Start-Process -FilePath $python `
    -ArgumentList @('-u', 'hetzner_url_dashboard.py') `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden `
    -RedirectStandardOutput $stdout `
    -RedirectStandardError $stderr

Start-Sleep -Seconds 5
$started = Get-NetTCPConnection -LocalPort 8792 -State Listen -ErrorAction SilentlyContinue
if (-not $started) {
    Add-Content -LiteralPath $stderr -Value "$(Get-Date -Format o) Dashboard did not open port 8792 after startup."
    exit 1
}
