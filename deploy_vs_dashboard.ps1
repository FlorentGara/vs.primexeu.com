$ErrorActionPreference = 'Stop'

$projectRoot = 'E:\websites\vs.primexeu.com'
$logRoot = Join-Path $projectRoot 'logs'
$git = 'C:\Program Files\Git\cmd\git.exe'
$python = Join-Path $projectRoot '.venv\Scripts\python.exe'
$deployState = Join-Path $logRoot 'git-deploy-commit.txt'
$failedState = Join-Path $logRoot 'git-deploy-failed-commit.txt'
$deployLog = Join-Path $logRoot 'git-deploy.log'
$archive = Join-Path $logRoot 'git-release.zip'
$stage = Join-Path $logRoot 'git-release-stage'
$backup = Join-Path $logRoot 'git-release-backup'

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Write-DeployLog([string]$message) {
    Add-Content -LiteralPath $deployLog -Value "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $message"
}

function Get-RefCommit([string]$reference) {
    $value = & $git -c "safe.directory=$projectRoot" -C $projectRoot rev-parse $reference 2>&1
    if ($LASTEXITCODE -ne 0) { throw "git rev-parse failed for $reference`: $value" }
    return ($value | Select-Object -Last 1).ToString().Trim()
}

function Stop-Dashboard {
    $listeners = @(Get-NetTCPConnection -LocalPort 8792 -State Listen -ErrorAction SilentlyContinue)
    foreach ($listener in $listeners) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($listener.OwningProcess)" -ErrorAction SilentlyContinue
        if ($process -and $process.CommandLine -match 'hetzner_url_dashboard\.py') {
            Stop-Process -Id $listener.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    }
    Start-Sleep -Seconds 2
}

function Start-Dashboard {
    $env:VS_ROOT = Join-Path $projectRoot 'Photos'
    $env:VS_BASE_URL = 'https://vs.primexeu.com/photos/'
    $env:VS_DASHBOARD_HOST = '127.0.0.1'
    $env:VS_DASHBOARD_PORT = '8792'
    $env:USERPROFILE = 'C:\Users\Administrator'

    Start-Process -FilePath $python `
        -ArgumentList @('-u', 'hetzner_url_dashboard.py') `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot 'photos-server.out.log') `
        -RedirectStandardError (Join-Path $logRoot 'photos-server.err.log')

    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Seconds 1
        if (Get-NetTCPConnection -LocalPort 8792 -State Listen -ErrorAction SilentlyContinue) {
            try {
                $response = Invoke-WebRequest 'http://127.0.0.1:8792/login' -UseBasicParsing -TimeoutSec 4
                if ($response.StatusCode -eq 200) { return }
            } catch { }
        }
    }
    throw 'The dashboard did not pass its /login health check on port 8792.'
}

function Copy-Release([string]$source, [string]$destination, [switch]$Mirror) {
    $mode = if ($Mirror) { '/MIR' } else { '/E' }
    & robocopy.exe $source $destination $mode '/R:2' '/W:2' '/COPY:DAT' '/DCOPY:DAT' '/XJ' '/XD' '.git' '.venv' 'logs' 'Photos' 'photos' '/XF' '.env' | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge 8) { throw "robocopy failed with exit code $code." }
}

function Deploy-Commit([string]$commit) {
    if (-not (Test-Path -LiteralPath $python)) { throw "Python environment not found: $python" }

    Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
    New-Item -ItemType Directory -Path $stage -Force | Out-Null
    & $git -c "safe.directory=$projectRoot" -C $projectRoot archive --format=zip "--output=$archive" $commit
    if ($LASTEXITCODE -ne 0) { throw "Could not export commit $commit from Git." }
    Expand-Archive -LiteralPath $archive -DestinationPath $stage -Force
    if (-not (Test-Path -LiteralPath (Join-Path $stage 'VS_WINDOWS_DEPLOY_ENABLED.txt'))) {
        Write-DeployLog 'Deployment marker missing from origin/main; waiting for the initial source commit.'
        return
    }

    $oldRequirements = Join-Path $projectRoot 'requirements.txt'
    $newRequirements = Join-Path $stage 'requirements.txt'
    if ((Test-Path -LiteralPath $newRequirements) -and (Test-Path -LiteralPath $oldRequirements)) {
        $oldHash = (Get-FileHash -LiteralPath $oldRequirements -Algorithm SHA256).Hash
        $newHash = (Get-FileHash -LiteralPath $newRequirements -Algorithm SHA256).Hash
        if ($oldHash -ne $newHash) {
            Write-DeployLog 'Installing updated Python requirements before switching the app.'
            & $python -m pip install --disable-pip-version-check -r $newRequirements *>> $deployLog
            if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed; the current app files were left in place.' }
        }
    }

    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Copy-Release $projectRoot $backup

    Stop-Dashboard
    try {
        Copy-Release $stage $projectRoot
        Start-Dashboard
    } catch {
        Write-DeployLog "New release failed; restoring the previous files: $($_.Exception.Message)"
        Stop-Dashboard
        Copy-Release $backup $projectRoot -Mirror
        Start-Dashboard
        throw
    }

    Set-Content -LiteralPath $deployState -Value $commit -Encoding ASCII
    Remove-Item -LiteralPath $failedState -Force -ErrorAction SilentlyContinue
    Write-DeployLog "Deployed commit $commit and verified /login."
}

while ($true) {
    try {
        if (-not (Test-Path -LiteralPath $git)) { throw "Git was not found: $git" }
        $null = & $git -c "safe.directory=$projectRoot" -C $projectRoot fetch --quiet origin main 2>&1
        if ($LASTEXITCODE -ne 0) { throw 'Could not fetch origin/main.' }
        $latest = Get-RefCommit 'origin/main'

        if (-not (Test-Path -LiteralPath $deployState)) {
            Set-Content -LiteralPath $deployState -Value $latest -Encoding ASCII
            Write-DeployLog "Initialized deployment baseline at $latest; no files were changed."
        } else {
            $current = (Get-Content -LiteralPath $deployState -Raw).Trim()
            $failed = if (Test-Path -LiteralPath $failedState) { (Get-Content -LiteralPath $failedState -Raw).Trim() } else { '' }
            if ($latest -ne $current -and $latest -ne $failed) {
                $null = & $git -c "safe.directory=$projectRoot" -C $projectRoot cat-file -e "${latest}:VS_WINDOWS_DEPLOY_ENABLED.txt" 2>$null
                if ($LASTEXITCODE -ne 0) {
                    Set-Content -LiteralPath $failedState -Value $latest -Encoding ASCII
                    Write-DeployLog "Commit $latest does not contain VS_WINDOWS_DEPLOY_ENABLED.txt; deployment is waiting for the initial source commit."
                } else {
                    try {
                        Deploy-Commit $latest
                    } catch {
                        Set-Content -LiteralPath $failedState -Value $latest -Encoding ASCII
                        Write-DeployLog "Deployment of $latest failed: $($_.Exception.Message)"
                    }
                }
            }
        }
    } catch {
        Write-DeployLog "Git update check failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds 60
}
