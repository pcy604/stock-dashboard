@echo off
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
cd /d %DIR%

echo [%date% %time%] ===== 스크리너 업데이트 시작 =====

echo [1/4] 주봉 스크리너...
%PYTHON% weekly_run.py

echo [2/4] 월간 성과...
%PYTHON% perf_run.py

echo [3/4] CANSLIM...
%PYTHON% canslim_run.py

echo [4/4] 흑자전환...
%PYTHON% turnaround_run.py

echo [5/6] 포트폴리오 모니터링...
%PYTHON% portfolio_monitor.py

echo [6/6] 신선도 검사 + 결과 동기화(푸시)...
%PYTHON% pipeline_health.py
git add results/*.json data/sectors.json data/portfolio.json 2>nul
git diff --staged --quiet || (git commit -m "auto: 로컬 데이터 갱신 %date:~0,10%" && git pull --rebase origin main && git push origin main)

echo [%date% %time%] ===== 업데이트 완료 =====
