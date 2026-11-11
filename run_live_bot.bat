@echo off
chcp 65001 >nul
rem 실전 시범 주문 봇 — 작업 스케줄러가 평일 00:40·01:10·08:40·09:10(노트북 현지 시각) 깨운다(2026-11-09).
rem 08:31~08:58 KST = 시가 단일가 주문(09:00 시가 체결) · 09:05~15:10 = 체결 확인·재시도 · 그 밖은 '건너뜀' 한 줄.
rem   한국: 08:40·09:10 · 폴란드(겨울): 00:40·01:10 = KST 08:40·09:10.
rem 실주문 조건: live\switch.json "live": true  그리고  아래 LIVE_TRADING=ON (둘 다). 2026-11-09 차니 결정으로 ON — 끄려면 switch.json live:false 한 줄
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
set LIVE_TRADING=ON
cd /d %DIR%
rem 2026-11-11: 노트북의 다른 작업이 data\krx_listing_last.csv(.asof)를 고치고 CI 도 같은 파일을 커밋 → autostash 되돌리기 충돌로
rem   '병합 안 된 파일'이 남아 11-10~11 봇 결과가 커밋·푸시되지 못했다. 데이터 파일은 CI 가 주인 — 노트북 수정본은 버리고 시작한다.
git rebase --abort >nul 2>&1
git checkout HEAD -- data/krx_listing_last.csv data/krx_listing_last.csv.asof >nul 2>&1
git pull --rebase --autostash origin main || echo ⛔ git pull 실패 — 노트북 저장소 확인 필요(git status)
"%PYTHON%" live\bot.py --send > live\bot_last.txt 2>&1
type live\bot_last.txt >> data\live_bot.log
rem bot_last.txt = 상시 점검(Claude)이 노트북이 돌았는지 확인하는 흔적
rem 2026-11-09: 없는 파일(trades.jsonl 등)이 하나라도 섞이면 git add 전체가 실패해 원장이 안 올라갔다 → 파일마다 따로
for %%F in (live\bot_last.txt live\ledger.json live\trades.jsonl live\violations.jsonl) do if exist %%F git add %%F
git diff --cached --quiet || git commit -m "auto: 주문 봇 원장 %date%"
rem 2026-11-09: CI 자동 커밋이 앞서면 push 가 거부됐다 → 올리기 전에 받고, 실패하면 한 번 더
git pull --rebase --autostash origin main
git push origin main || (git pull --rebase --autostash origin main && git push origin main)
