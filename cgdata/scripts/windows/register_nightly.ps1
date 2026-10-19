# Register the nightly cgdata render as a Windows scheduled task (run once,
# from an elevated PowerShell). Starts 22:00 local time daily, wakes the
# machine to run, and lets run_batch stop itself at 07:00.
#
#   powershell -ExecutionPolicy Bypass -File register_nightly.ps1
#   (remove with: Unregister-ScheduledTask -TaskName "cgdata nightly" -Confirm:$false)

$bat = Join-Path $PSScriptRoot "nightly.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -Daily -At 22:00
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 10) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "cgdata nightly" -Action $action -Trigger $trigger `
    -Settings $settings -Description "cgdata pilot render (10pm-7am)" -Force

# Keep the machine awake on AC power while it renders (0 = never sleep).
powercfg /change standby-timeout-ac 0
Write-Host "Registered 'cgdata nightly' (22:00 daily). Edit the paths at the top of nightly.bat."
