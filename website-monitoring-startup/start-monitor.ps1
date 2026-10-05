$ErrorActionPreference = 'Stop'

$AppDir = 'E:\websites\website-monitoring'
$Port = 8081
$LogFile = Join-Path $AppDir 'monitor-startup.log'

function Write-StartupLog {
    param([string]$Message)
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -LiteralPath $LogFile -Value "[$timestamp] $Message"
}

try {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        Write-StartupLog "Port $Port is already listening; website monitor was not started again."
        exit 0
    }

    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pythonLauncher) {
        $pythonExe = $pythonLauncher.Source
        $pythonArgs = '-3 monitor.py'
    }
    else {
        $python = Get-Command python.exe -ErrorAction SilentlyContinue
        if (-not $python) {
            throw 'Could not find py.exe or python.exe in PATH.'
        }

        $pythonExe = $python.Source
        $pythonArgs = 'monitor.py'
    }

    Write-StartupLog "Starting website monitor with $pythonExe $pythonArgs"
    Start-Process -FilePath $pythonExe -ArgumentList $pythonArgs -WorkingDirectory $AppDir -WindowStyle Hidden
}
catch {
    Write-StartupLog "Startup failed: $($_.Exception.Message)"
    exit 1
}
