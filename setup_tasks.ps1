# Laptop scheduled tasks (2026-11-07). Run once via setup_tasks.bat (as administrator).
#   buza_live_bot        : weekdays 02:30 and 10:30 local time; bot itself acts only inside KRX hours (09:05-15:10 KST).
#   StockScreener_Daily  : daily 06:00, Toss balance sync only.
# Both: run when missed (StartWhenAvailable), wake the laptop, kill if stuck.
$dir = 'C:\Users\lg\Desktop\stock_screener'
$days = 'Monday','Tuesday','Wednesday','Thursday','Friday'

$a1 = New-ScheduledTaskAction -Execute "$dir\run_live_bot.bat" -WorkingDirectory $dir
$t1 = @(
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At '02:30'),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek $days -At '10:30')
)
$s1 = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
      -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'buza_live_bot' -Action $a1 -Trigger $t1 -Settings $s1 -Force | Out-Null

$a2 = New-ScheduledTaskAction -Execute "$dir\run_update.bat" -WorkingDirectory $dir
$t2 = New-ScheduledTaskTrigger -Daily -At '06:00'
$s2 = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
      -ExecutionTimeLimit (New-TimeSpan -Minutes 15) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'StockScreener_Daily' -Action $a2 -Trigger $t2 -Settings $s2 -Force | Out-Null

Get-ScheduledTask -TaskName buza_live_bot,StockScreener_Daily | Get-ScheduledTaskInfo |
  Format-List TaskName,LastRunTime,LastTaskResult,NextRunTime
Write-Host 'OK - tasks registered. Close this window.'
