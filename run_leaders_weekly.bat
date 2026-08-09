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

"%DIR%\..\..\AppData\Local\Python\bin\python.exe" -c "import os,sys,json,datetime;p=r'%DIR%\results\leaders_signal.json';d=json.load(open(p,encoding='utf-8'));g=d.get('generated','');t=str(datetime.date.today());print('[OK] 신호 파일 갱신됨 '+g) if g==t else (print('[WARN] 신호 파일이 오늘 날짜가 아님: '+str(g)+' (오늘 '+t+')') or sys.exit(2))"
if errorlevel 2 (
    echo [WARN] 사이클은 끝났지만 산출물이 갱신되지 않았습니다. 로그를 확인하세요.
    exit /b 2
)

echo [%date% %time%] 완료
endlocal
