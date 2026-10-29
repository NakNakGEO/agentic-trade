# Registers the watchdog as a Windows scheduled task: it runs at logon and then every 5 minutes, with no window.
# Run it ONCE, in the LIVE folder, after the watchdog has been promoted. Undo with: scripts\remove_watchdog_task.ps1
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root "TradingAgents\.venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) { throw "pythonw.exe not found at $python" }
$action = New-ScheduledTaskAction -Execute $python -Argument "-m paper_trade watchdog --dashboard" -WorkingDirectory $root
$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn),
    (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5))
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
Register-ScheduledTask -TaskName "agentic-trade-watchdog" -Action $action -Trigger $triggers -Settings $settings -Description "Keeps the agentic-trade live loops and dashboard running" -Force | Out-Null
"Registered 'agentic-trade-watchdog' for $root"
