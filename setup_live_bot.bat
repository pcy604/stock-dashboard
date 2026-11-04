@echo off
rem 한 번만 실행: 평일(월~금) 02:30(한국장 10:30 KST · 서머타임 중 09:30 — 연중 장중) 에 run_live_bot.bat 를 돌리는 작업 등록
schtasks /create /tn "buza_live_bot" /tr "C:\Users\lg\Desktop\stock_screener\run_live_bot.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 02:30 /f
rem 노트북이 잠자기여도 깨워서 실행
powershell -NoProfile -Command "$t=Get-ScheduledTask -TaskName buza_live_bot; $t.Settings.WakeToRun=$true; Set-ScheduledTask -InputObject $t" >nul
echo 등록 완료 — 작업 스케줄러에서 buza_live_bot 확인
pause
