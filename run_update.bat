@echo off
set PYTHON=C:\Users\lg\AppData\Local\Python\bin\python.exe
set DIR=C:\Users\lg\Desktop\stock_screener
cd /d %DIR%

echo [%date% %time%] ===== 스크리너 업데이트 시작 =====

rem ── [0/5] 원격 먼저 당겨온다 ────────────────────────────────────────────
rem 2026-08-08 수정. 예전에는 생성 → 커밋 → pull --rebase 순서였는데,
rem results/*.json 을 GitHub Actions(daily-refresh)도 매일 새로 만들어 커밋하기 때문에
rem rebase가 반드시 충돌했고, 배치에 실패 처리가 없어 저장소가 detached HEAD 로
rem 멈춘 채 방치됐다 (08-05·08-08 두 번 발생, 그 사이 커밋들이 브랜치에서 떨어짐).
rem 작업 트리가 깨끗한 시점에 먼저 당겨오면 충돌 자체가 생기지 않는다.
echo [0/5] 원격 동기화...
rem 남아 있는 rebase는 무조건 지우지 않는다 - 사용자가 직접 하던 작업일 수 있다.
rem 발견하면 크게 알리고 중단한다. 판단은 사람이 한다.
if exist ".git\rebase-merge" (
    echo [ERROR] ===================================================
    echo [ERROR] 이전 rebase가 끝나지 않은 채 남아 있습니다.
    echo [ERROR] 자동으로 건드리지 않고 중단합니다.
    echo [ERROR]   확인 : git status
    echo [ERROR]   취소 : git rebase --abort
    echo [ERROR] ===================================================
    exit /b 1
)
git pull --rebase origin main
if errorlevel 1 (
    echo [ERROR] 원격 동기화 실패 - 되돌리고 중단합니다.
    git rebase --abort
    exit /b 1
)

echo [1/4] 주봉 스크리너...
%PYTHON% weekly_run.py

echo [2/4] 월간 성과...
%PYTHON% perf_run.py

echo [3/4] CANSLIM...
%PYTHON% canslim_run.py

echo [4/4] 흑자전환...
%PYTHON% turnaround_run.py

echo [5/5] 신선도 검사 + 결과 동기화(푸시)...
%PYTHON% pipeline_health.py
rem 경로 분리 필수: git add는 pathspec 하나라도 없으면 전체 실패 (portfolio.json 부재 함정)
git add results/*.json 2>nul
git add data/sectors.json 2>nul
git add data/portfolio.json 2>nul
rem [0/5]에서 이미 원격과 맞춰뒀으므로 여기서는 rebase 없이 바로 푸시한다.
rem 푸시가 거절되면(그 사이 원격이 움직인 경우) 다음 실행의 [0/5]이 알아서 정리한다.
git diff --staged --quiet || (
    git commit -m "auto: 로컬 데이터 갱신 %date:~0,10%"
    git push origin main
    if errorlevel 1 echo [WARN] 푸시 거절 - 커밋은 로컬에 남아 있고 다음 실행에서 재시도됩니다.
)

echo [%date% %time%] ===== 업데이트 완료 =====
