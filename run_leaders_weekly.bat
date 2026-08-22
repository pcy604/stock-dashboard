@echo off
rem ─────────────────────────────────────────────────────────────────────────
rem 주도주 주간 사이클 자동 실행 (2026-08-08 신설)
rem   더블클릭으로도 돌고, 작업 스케줄러(StockScreener_LeadersWeekly)도 이걸 부른다.
rem   PowerShell PATH에 bash가 없어서 Git Bash를 전체 경로로 호출한다.
rem ─────────────────────────────────────────────────────────────────────────
setlocal
set BASH=C:\Program Files\Git\bin\bash.exe
set DIR=C:\Users\lg\Desktop\stock_screener
set SH=%DIR%/leaders_weekly.sh

cd /d "%DIR%"

if not exist "%BASH%" (
    echo [ERROR] Git Bash를 찾을 수 없습니다: %BASH%
    echo [ERROR] Git for Windows 설치 경로를 확인하세요.
    exit /b 1
)

rem ── [사전] 원격 먼저 당겨온다 ──────────────────────────────────────────
rem run_update.bat과 같은 이유. 작업 트리가 깨끗한 지금 당겨와야
rem 나중에 커밋할 때 rebase 충돌로 저장소가 멈추지 않는다.
if exist ".git\rebase-merge" (
    echo [ERROR] 이전 rebase가 끝나지 않은 채 남아 있습니다. 자동으로 건드리지 않고 중단합니다.
    echo [ERROR]   확인 : git status      취소 : git rebase --abort
    exit /b 1
)
rem 2026-08-22: --autostash 추가. 작업 트리가 더러우면 pull 이 실패하고
rem 스크립트를 부르기도 전에 중단돼 로그조차 안 남았다(08-22 08:00 실행이 그렇게 죽었다).
git pull --rebase --autostash origin main
if errorlevel 1 (
    echo [ERROR] 원격 동기화 실패 - 되돌리고 중단합니다.
    git rebase --abort
    exit /b 1
)

echo [%date% %time%] 주도주 주간 사이클 시작
"%BASH%" "%SH%"
set RC=%ERRORLEVEL%

rem ── 조용한 실패 방지 ───────────────────────────────────────────────────
rem 이 프로젝트의 고질병이 "돌았다고 생각했는데 안 돈 것"이다.
rem 스크립트가 성공했다고 말해도 산출물이 실제로 갱신됐는지 따로 확인한다.
if %RC% NEQ 0 (
    echo [ERROR] 사이클이 실패했습니다 ^(exit %RC%^). results\leaders_weekly_*.log 확인
    exit /b %RC%
)

"%DIR%\..\..\AppData\Local\Python\bin\python.exe" -c "import os,sys,json,datetime;p=r'%DIR%\results\leaders_ab.json';d=json.load(open(p,encoding='utf-8'));g=d.get('generated','');t=str(datetime.date.today());print('[OK] 신호 파일 갱신됨 '+g) if g==t else (print('[WARN] 신호 파일이 오늘 날짜가 아님: '+str(g)+' (오늘 '+t+')') or sys.exit(2))"
if errorlevel 2 (
    echo [WARN] 사이클은 끝났지만 산출물이 갱신되지 않았습니다. 커밋하지 않고 종료합니다.
    exit /b 2
)

rem ── 대시보드 반영 ─────────────────────────────────────────────────────
rem 신호·페이퍼 원장을 바로 올려야 토요일 아침에 대시보드에서 볼 수 있다.
rem 위에서 이미 pull 해뒀으므로 여기서는 rebase 없이 커밋+푸시만 한다.
git add results/leaders_ab.json 2>nul
git add results/leaders_symbol_detail.json 2>nul
git add results/leaders_kr.json 2>nul
git add results/leaders_kr6.json 2>nul
git diff --staged --quiet || (
    git commit -m "data: 주도주 주간 사이클 %date:~0,10%"
    git push origin main
    if errorlevel 1 echo [WARN] 푸시 거절 - 커밋은 로컬에 남아 있고 다음 실행에서 재시도됩니다.
)

echo [%date% %time%] 완료 - 대시보드 반영됨
endlocal
