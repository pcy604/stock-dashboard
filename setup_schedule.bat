@echo off
echo 기존 작업 삭제 후 재등록 중...
schtasks /delete /tn "StockScreener_Daily" /f 2>nul

schtasks /create /tn "StockScreener_Daily" /tr "C:\Users\lg\Desktop\stock_screener\run_update.bat" /sc daily /st 06:00 /f /rl HIGHEST

echo.
echo ✅ 등록 완료: 매일 오전 6:00 자동 실행
echo.
schtasks /query /tn "StockScreener_Daily"
pause
