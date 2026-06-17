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

echo [5/5] 포트폴리오 모니터링...
%PYTHON% portfolio_monitor.py

echo [%date% %time%] ===== 업데이트 완료 =====
