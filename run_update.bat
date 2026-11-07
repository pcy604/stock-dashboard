@echo off
chcp 65001 >nul
rem 노트북 일일 작업(StockScreener_Daily) — 2026-11-07 개편: 노트북만 할 수 있는 일만 한다.
rem   토스 Open API 는 허용 IP 에서만 응답 → 토스 잔고 동기화(tools\toss_sync.py)만 이 PC 에서.
rem   예전 [1/4]~[4/4](주봉·성과·CANSLIM·흑자전환)·DART 가치 스냅샷은 GitHub Actions(daily-refresh·fin-daily)가 매일 똑같이 만든다.
rem   그중 하나(주봉 스크리너)가 11-07 08:01 부터 13시간 넘게 멈춰 토스 동기화까지 가지 못했다 → 뺐다.
rem 로그: data\update.log (Claude 상시 점검이 읽는다)
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
set LOG=data\update.log
cd /d %DIR%

echo [%date% %time%] ===== 노트북 일일 작업 시작 ===== >> %LOG%
if exist ".git\rebase-merge" (
    echo [%date% %time%] [ERROR] 끝나지 않은 rebase 가 있어 중단 - git status 로 확인 >> %LOG%
    exit /b 1
)
git pull --rebase --autostash origin main >> %LOG% 2>&1
if errorlevel 1 (
    echo [%date% %time%] [ERROR] 원격 동기화 실패 - 되돌리고 중단 >> %LOG%
    git rebase --abort >> %LOG% 2>&1
    exit /b 1
)

echo [%date% %time%] 토스 잔고 동기화... >> %LOG%
%PYTHON% tools\toss_sync.py >> %LOG% 2>&1

git add data/portfolio_toss.vault 2>nul
git diff --staged --quiet || (
    git commit -m "auto: 토스 잔고 동기화 %date:~0,10%" >> %LOG% 2>&1
    git push origin main >> %LOG% 2>&1 || (
        git pull --rebase --autostash origin main >> %LOG% 2>&1 && git push origin main >> %LOG% 2>&1
    )
)
echo [%date% %time%] ===== 끝 ===== >> %LOG%
