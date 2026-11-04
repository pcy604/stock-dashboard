@echo off
rem 실전 시범 주문 봇 — 작업 스케줄러가 평일 02:30(바르샤바) = 한국장 10:30 KST(서머타임 중 09:30) — 연중 장중에 실행
rem 실주문 조건: live\switch.json "live": true  그리고  아래 LIVE_TRADING=ON (둘 다)
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
set LIVE_TRADING=OFF
cd /d %DIR%
git pull --rebase origin main
"%PYTHON%" live\bot.py --send >> data\live_bot.log 2>&1
git add live\ledger.json live\trades.jsonl live\violations.jsonl 2>nul
git diff --cached --quiet || (git commit -m "auto: 주문 봇 원장 %date%" && git push origin main)
