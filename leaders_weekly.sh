#!/usr/bin/env bash
# 주도주 주간 사이클 — 매주 월요일 1회 (약 10분)
#   가격만 새로 받고, 팩터는 새 주차만 증분 계산한다.
#   ※ 재무(fq_)·실적일(ek_)은 분기 단위라 캐시 유지 — 분기마다 아래 REFRESH_FUND=1 로 1회 갱신
#   ※ earnings_event 테이블은 분석 전용이라 주간 사이클에 불필요 (신호는 factor_weekly만 사용)
set -e
cd "$(dirname "$0")"
PY=/c/Users/lg/AppData/Local/Python/bin/python.exe
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1
LOG="results/leaders_weekly_$(date +%Y%m%d).log"
mkdir -p results

{
echo "=== 주도주 주간 사이클  $(date '+%Y-%m-%d %H:%M') ==="

echo "--- [1/5] 가격 캐시 갱신 (~5분)"
rm -f data/leaders_cache/px_*.csv data/leaders_cache/dy_*.csv
if [ "${REFRESH_FUND:-0}" = "1" ]; then
  echo "    (분기 갱신 요청 — 재무·8-K 캐시도 삭제)"
  rm -f data/leaders_cache/fq_*.csv data/leaders_cache/ek_*.csv
fi
$PY leaders_build.py fetch 1500

echo "--- [2/5] factor_weekly 증분 적재 (~2분)"
$PY leaders_build.py update

echo "--- [3/5] 보유 갱신 — 고점 추적 + 트레일링 −20% 청산 판정"
$PY leaders_paper.py update

echo "--- [4/5] 신규 신호 기록"
$PY leaders_paper.py log

echo "--- [5/5] 대시보드용 JSON 출력"
$PY leaders_publish.py

echo "--- 리포트"
$PY leaders_paper.py report
$PY leaders_listup.py

echo "--- 텔레그램 주간 요약"
$PY leaders_paper.py notify

echo "=== DONE $(date '+%H:%M') ==="
} 2>&1 | tee "$LOG"
echo "로그: $LOG"
