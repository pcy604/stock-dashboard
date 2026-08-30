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

echo "--- [1/4] 가격 캐시 갱신 (~5분)"
rm -f data/leaders_cache/px_*.csv data/leaders_cache/dy_*.csv
if [ "${REFRESH_FUND:-0}" = "1" ]; then
  echo "    (분기 갱신 요청 — 재무·8-K 캐시도 삭제)"
  rm -f data/leaders_cache/fq_*.csv data/leaders_cache/ek_*.csv
fi
$PY leaders_build.py fetch 2900

echo "--- [2/4] factor_weekly 증분 적재 (~2분)"
$PY leaders_build.py update

# 2026-08-31: volwk_build 를 뺐다. 주봉 거래량 배수(vw)는 L/S 전용 조건이었고
# L/S 가 화면에서 제거되면서 아무도 안 쓰게 됐다.

echo "--- [3/4] 이익 가속 신호 발행 (2026-08-23 신설 · 주도주 탭 첫 화면)"
$PY leaders_accel.py



# ⚠️ 반드시 leaders_accel.py **뒤에** 온다. spans 를 읽어 곡선을 만들기 때문이다.
#    앞으로 옮기면 곡선이 지난주 신호 기준이 되고, 화면에선 "최근 ▲ 가 곡선 밖에 있다"로
#    나타난다 — 에러 없이 조용히 틀린다.
# 2026-08-31: L/S 단계 2개를 뺐다. 화면에서 규칙이 제거돼(e13b0f2) 아무도 안 보는
# 산출물을 매주 만들어 커밋하고 있었다. 곡선도 절반으로 줄었다.
echo "--- [4/4] 가격 곡선 발행 (심층조회 차트)"
$PY curves_build.py

echo "--- [5/5] 한국 주도주"
$PY leaders_kr.py publish || echo "    [WARN] KR 실패 — 미국 산출물은 이미 갱신됐다"
$PY leaders_kr6.py publish || echo "    [WARN] KR6 실패 — 미국 산출물은 이미 갱신됐다"

echo "--- 리포트"
$PY leaders_listup.py || echo "    [WARN] listup 실패 — 산출물은 이미 갱신됐다"

# 2026-08-22: 구 규칙⑥ 계열(leaders_publish · leaders_paper)을 주간 사이클에서 뺐다.
#   규칙⑥은 08-18 종료됐고 leaders_signal.json 은 '닫힌 기록'이라 매주 새로 만들 이유가 없다.
#   leaders_paper.json 은 대시보드 참조 0건이다(2026-08-22 검인).
#   그동안 이 사이클은 **폐기된 규칙만 갱신하고 현행 L/S 는 손도 안 대고 있었다** —
#   L/S 는 사람이 수동으로 돌릴 때만 갱신됐다. 규칙을 동결하고 신호를 쌓기로 한 이상
#   (2026-08-22 결정) 이게 자동으로 돌지 않으면 아웃오브샘플 표본이 안 쌓인다.

echo "=== DONE $(date '+%H:%M') ==="
} 2>&1 | tee "$LOG"
echo "로그: $LOG"
