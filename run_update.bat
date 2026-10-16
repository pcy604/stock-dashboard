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

rem 2026-10-17 — 가치 스냅샷(가치 발굴 KR 화면)도 DART 연간재무가 필요한데 CI(해외)에서는 DART 가 막혔다.
rem 이 PC 에서 매일 만든다. 결과(results/value_kr.json)는 아래 [5/5] 의 results/*.json 커밋에 함께 실린다.
echo [+] 가치 스냅샷 - DART 연간재무 시총 상위 250...
%PYTHON% ingest_dart.py --top 250 --years 2
%PYTHON% value_export.py

echo [+] 토스 계좌 동기화 (키 없으면 건너뜀, 실패해도 계속)...
%PYTHON% tools\toss_sync.py

echo [5/5] 신선도 검사 + 결과 동기화(푸시)...
%PYTHON% pipeline_health.py
rem 경로 분리 필수: git add는 pathspec 하나라도 없으면 전체 실패 (portfolio.json 부재 함정)
git add results/*.json 2>nul
git add data/sectors.json 2>nul
git add data/portfolio.json 2>nul
git add data/portfolio_toss.enc 2>nul
rem [0/5]에서 이미 원격과 맞춰뒀으므로 여기서는 rebase 없이 바로 푸시한다.
rem 푸시가 거절되면(그 사이 원격이 움직인 경우) 다음 실행의 [0/5]이 알아서 정리한다.
rem 2026-10-17 고침: 위 가정이 깨졌다 - 실행 중 06:00~07:15 에 원격에 코드 커밋이 들어오면 푸시가 거절되고,
rem 다음날 [0/5] rebase 가 CI 결과 커밋과 같은 결과 파일에서 충돌해 배치가 멈춘다. 거절되면 그 자리에서 다시 맞춘다.
rem 주의: 괄호 블록 안에는 rem 을 두지 않는다 - 주석 속 닫는 괄호가 블록을 끝내 버린다.
git diff --staged --quiet || (
    git commit -m "auto: 로컬 데이터 갱신 %date:~0,10%"
    git push origin main || (
        git pull --rebase --autostash origin main && git push origin main
    )
    if errorlevel 1 (
        git rebase --abort 2>nul
        echo [WARN] 푸시 거절 - 커밋은 로컬에 남아 있고 다음 실행에서 재시도됩니다.
    )
)

echo [%date% %time%] ===== 업데이트 완료 =====
rem ── 2026-10-17 · KR 분기재무(DART) 주 1회(월요일) — CI 대신 이 PC 가 한다 ─────────────────
rem DART 가 해외 서버(GitHub Actions·Streamlit Cloud)의 연결을 받지 않는다(10-15~). 한국에 있는 이 PC 만 닿는다.
rem tools\refresh_kr_fundq.py 는 결과가 기존보다 나쁘면 쓰지 않는다(행 95%%·순이익 채움 80%% 미만 거부).
rem PC 가 꺼져 있던 주는 건너뛴다 - 화면 재무표는 네이버 기업분석으로 따로 돈다(kr_fin_naver.py).
for /f %%d in ('powershell -NoProfile -Command "[int][DateTime]::Now.DayOfWeek"') do set DOW=%%d
if "%DOW%"=="1" (
    echo [+] KR 분기재무 갱신 - DART, 월요일...
    %PYTHON% tools\refresh_kr_fundq.py
    git add data/kr_fundamentals_q.parquet 2>nul
    git add data/kr_universe.parquet 2>nul
    git diff --staged --quiet || (
        git commit -m "auto: KR quarterly fundamentals (PC, DART)"
        git push origin main || (
            git pull --rebase --autostash origin main && git push origin main
        )
        if errorlevel 1 (
            git rebase --abort 2>nul
            echo [WARN] 푸시 거절 - 다음 실행에서 재시도됩니다.
        )
    )
)
rem ── 2026-10-17 · 다음 실행이 깨끗한 작업 트리에서 시작하도록 ──────────────────────
rem 스크립트가 매번 다시 쓰는 추적 캐시(KRX 상장목록)가 커밋되지 않고 남아, 다음날 [0/5]
rem git pull --rebase 가 'unstaged changes' 로 실패 -> 배치 전체 중단(10-16, 10-17 미실행).
rem 캐시는 다음 실행에서 다시 만들어지므로 되돌려도 잃는 것이 없다. 사용자 작업 파일은 건드리지 않는다.
rem (규칙: [0/5] pull 줄보다 앞부분은 바꾸지 않는다 - 실행 중인 배치가 pull 로 바뀌어도 읽던 바이트 위치가 그대로여야 한다)
git checkout -- data/krx_listing_last.csv data/krx_listing_last.csv.asof 2>nul
