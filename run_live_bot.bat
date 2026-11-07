@echo off
chcp 65001 >nul
rem 실전 시범 주문 봇 — 작업 스케줄러가 평일 02:30·10:30(노트북 현지 시각) 두 번 깨운다(2026-11-07).
rem 봇은 한국장 안(평일 09:05~15:10 KST)일 때만 움직이고, 장 밖이면 '건너뜀' 한 줄만 남긴다.
rem   폴란드: 02:30 = 10:30 KST(서머타임 중 09:30) · 한국: 10:30 KST — 노트북이 어디 있든 하루 한 번.
rem 실주문 조건: live\switch.json "live": true  그리고  아래 LIVE_TRADING=ON (둘 다)
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
set LIVE_TRADING=OFF
cd /d %DIR%
git pull --rebase --autostash origin main
"%PYTHON%" live\bot.py --send > live\bot_last.txt 2>&1
type live\bot_last.txt >> data\live_bot.log
rem bot_last.txt = 상시 점검(Claude)이 노트북이 돌았는지 확인하는 흔적
git add live\bot_last.txt live\ledger.json live\trades.jsonl live\violations.jsonl 2>nul
git diff --cached --quiet || (git commit -m "auto: 주문 봇 원장 %date%" && git push origin main)
