# Removes the scheduled task made by install_watchdog_task.ps1 (the loops it started keep running).
Unregister-ScheduledTask -TaskName "agentic-trade-watchdog" -Confirm:$false
"Removed 'agentic-trade-watchdog'"
