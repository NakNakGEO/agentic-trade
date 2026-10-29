# Stops Windows from going to sleep while this script runs (like "caffeinate"). Changes no settings.
# Ends when this process is stopped. A closed laptop lid still sleeps the machine.
Add-Type -Namespace Win -Name Power -MemberDefinition '[DllImport("kernel32.dll")] public static extern uint SetThreadExecutionState(uint flags);'
[Win.Power]::SetThreadExecutionState([uint32]2147483649) | Out-Null     # 0x80000001 = ES_CONTINUOUS | ES_SYSTEM_REQUIRED
while ($true) { Start-Sleep -Seconds 60 }
