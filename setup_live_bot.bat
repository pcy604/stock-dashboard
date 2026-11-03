@echo off
rem 한 번만 실행: 평일(월~금) 16:00 에 run_live_bot.bat 를 돌리는 작업 등록
schtasks /create /tn "buza_live_bot" /tr "C:\Users\lg\Desktop\stock_screener\run_live_bot.bat" /sc weekly /d MON,TUE,WED,THU,FRI /st 16:00 /f
echo 등록 완료 — 작업 스케줄러에서 buza_live_bot 확인
pause
