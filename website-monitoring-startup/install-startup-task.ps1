$ErrorActionPreference = 'Stop'

$TaskName = 'Website Monitoring App'
$ScriptPath = 'E:\websites\website-monitoring\start-monitor.ps1'

$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)

if (-not $isAdmin) {
    throw 'Run this script from an elevated PowerShell window.'
}

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Startup script not found: $ScriptPath"
}

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""

$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description 'Starts the NiceGUI website monitoring app after server reboot.' `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName

Write-Host "Scheduled task '$TaskName' installed and started."
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName,State
