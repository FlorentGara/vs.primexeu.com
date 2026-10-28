$ErrorActionPreference = 'Stop'

$projectRoot = 'E:\websites\vs.primexeu.com'
$startupScript = Join-Path $projectRoot 'start_vs_dashboard.ps1'
$deployScript = Join-Path $projectRoot 'deploy_vs_dashboard.ps1'
$taskName = 'VS Primexeu Dashboard'
$deployTaskName = 'VS Primexeu Git Deploy'
$powershell = Join-Path $env:WINDIR 'System32\WindowsPowerShell\v1.0\powershell.exe'
$git = 'C:\Program Files\Git\cmd\git.exe'
$logRoot = Join-Path $projectRoot 'logs'
$deployState = Join-Path $logRoot 'git-deploy-commit.txt'

if (-not (Test-Path -LiteralPath $startupScript) -or -not (Test-Path -LiteralPath $deployScript)) {
    throw "VS startup or Git deployment script was not found in $projectRoot"
}
if (-not (Test-Path -LiteralPath $git) -or -not (Test-Path -LiteralPath (Join-Path $projectRoot '.git'))) {
    throw 'Git or the server repository is missing; automatic Git deployment cannot be installed.'
}

$cloudflared = Get-Service -Name 'cloudflared' -ErrorAction SilentlyContinue
if ($cloudflared) {
    Set-Service -Name $cloudflared.Name -StartupType Automatic
    if ($cloudflared.Status -ne 'Running') {
        Start-Service -Name $cloudflared.Name
    }
}

$action = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$startupScript`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 3)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Starts the VS Primexeu photo dashboard after Windows boots.' `
    -Force | Out-Null

# Record the current GitHub main commit as the starting point. Later commits
# are deployed automatically; existing manually copied server files stay live
# until the desired source code is committed to main.
$null = & $git -c "safe.directory=$projectRoot" -C $projectRoot fetch --quiet origin main 2>&1
if ($LASTEXITCODE -ne 0) {
    throw 'Could not reach GitHub to establish the initial deployment baseline.'
}
$baseline = (& $git -c "safe.directory=$projectRoot" -C $projectRoot rev-parse origin/main 2>&1 | Select-Object -Last 1).ToString().Trim()
if ($LASTEXITCODE -ne 0 -or -not $baseline) {
    throw 'Could not read the current origin/main commit.'
}
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $deployState)) {
    Set-Content -LiteralPath $deployState -Value $baseline -Encoding ASCII
}

$deployAction = New-ScheduledTaskAction `
    -Execute $powershell `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$deployScript`""
$deploySettings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 3650)
Register-ScheduledTask `
    -TaskName $deployTaskName `
    -Action $deployAction `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $deploySettings `
    -Description 'Polls GitHub main and deploys committed VS dashboard changes.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
Start-ScheduledTask -TaskName $deployTaskName
Write-Host "Installed and started scheduled task: $taskName"
Write-Host "Installed and started scheduled task: $deployTaskName"
Write-Host 'The site starts with Windows. GitHub main is checked every 60 seconds.'
