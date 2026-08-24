#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# git 히스토리에서 results/ · exports/ 를 제거해 저장소를 줄인다 (2026-08-25)
#
# ⚠️ 되돌릴 수 없는 작업이다. 반드시 읽고 돌려라.
#
# 왜 하는가
#   .git 이 580MB 다(gc 전 1,006MB). 히스토리 용량을 파일별로 재보면:
#     results/guru_insights.json        517.9 MB   (686KB × 734회 커밋 · 하루 6번)
#     exports/factor_weekly.csv.gz      136.1 MB   (이미 추적 해제)
#     exports/factor_weekly.parquet     100.4 MB   (이미 추적 해제)
#     results/leaders_symbol_detail.json 89.3 MB
#     results/guru_chart_latest.png      37.3 MB   (338회 커밋)
#   결과 데이터는 전부 재생성 가능하다. 히스토리로 되짚을 일이 거의 없으므로 지운다.
#
# 무엇이 깨지는가 — 돌리기 전에 이걸 받아들일 수 있는지 판단해라
#   ① 모든 커밋 해시가 바뀐다. 다른 PC 의 클론은 전부 무효가 되고 다시 받아야 한다.
#   ② 강제 푸시가 필요하다. 푸시 순간 진행 중이던 GitHub Actions 의 커밋은 실패한다
#      (다음 실행에서 자동 복구된다).
#   ③ **results/ 의 과거 이력이 사라진다.** "지난달 신호가 뭐였나"를 git 으로 못 본다.
#      현재 파일은 이 스크립트가 스냅샷에서 되살려 새 커밋으로 남긴다.
#   ④ Streamlit Cloud 는 재배포(재클론)해야 한다. results/ 가 저장소에 있어야 돌아간다.
#
# ⚠️ ②(guru_insights 커밋 빈도 축소)를 안 한 상태라면, 이 정리는 **한 번짜리**다.
#    guru 워크플로 3개가 하루 6번 커밋을 계속하므로 주당 약 29MB 씩 다시 쌓인다.
#    대략 1년이면 원래 크기로 돌아온다.
#
# 사용법
#   bash tools/shrink_history.sh            # 미리보기(아무것도 안 바꾼다)
#   bash tools/shrink_history.sh --run      # 실제 실행
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

cd "$(dirname "$0")/.."
PY="${PY:-/c/Users/lg/AppData/Local/Python/bin/python.exe}"
STAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP="../stock_screener_BACKUP_${STAMP}.git"
SNAP="../_results_snapshot_${STAMP}"

echo "── 현재 상태 ─────────────────────────────"
git count-objects -vH | grep -E 'size-pack'
echo "  추적 중인 results 파일: $(git ls-files results | wc -l) 개"
echo "  추적 중인 exports 파일: $(git ls-files exports | wc -l) 개"
echo

if [ "${1:-}" != "--run" ]; then
  echo "미리보기 모드다. 실제로 돌리려면:"
  echo "    bash tools/shrink_history.sh --run"
  exit 0
fi

# 워킹트리가 깨끗한지 — 커밋 안 된 변경이 있으면 날아간다
if [ -n "$(git status --porcelain)" ]; then
  echo "[중단] 커밋되지 않은 변경이 있다. 먼저 커밋하거나 stash 해라."
  git status --short | head -20
  exit 1
fi

REMOTE="$(git remote get-url origin)"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "원격: $REMOTE"
echo "브랜치: $BRANCH"
echo

echo "── [1/6] 백업 (미러 클론) ─────────────────"
git clone --mirror . "$BACKUP"
echo "  → $BACKUP"

echo "── [2/6] results/ 현재 스냅샷 ─────────────"
mkdir -p "$SNAP"
cp -r results/. "$SNAP/"
git ls-files results > "$SNAP/_tracked.txt"
echo "  → $SNAP  ($(wc -l < "$SNAP/_tracked.txt") 개 추적 파일)"

echo "── [3/6] 히스토리에서 제거 ────────────────"
"$PY" -m git_filter_repo --path results --path exports --invert-paths --force

echo "── [4/6] results/ 복원 ────────────────────"
mkdir -p results
cp -r "$SNAP/." results/
rm -f results/_tracked.txt
# 원래 추적하던 파일만 다시 올린다 (스냅샷엔 추적 안 하던 파일도 섞여 있다)
while IFS= read -r f; do
  [ -f "$f" ] && git add -f "$f"
done < "$SNAP/_tracked.txt"
git commit -q -m "chore: 히스토리 정리 후 results/ 현재 스냅샷 복원

git 히스토리에서 results/ · exports/ 를 제거했다(tools/shrink_history.sh).
결과 데이터는 전부 재생성 가능하고 과거 이력을 되짚을 일이 없어서,
현재 스냅샷만 남기고 과거 버전은 버렸다.

제거 전 히스토리 용량 1위는 results/guru_insights.json 으로 686KB 파일이
734회(하루 6번) 커밋되며 518MB 를 먹고 있었다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"

echo "── [5/6] 정리 ─────────────────────────────"
git reflog expire --expire=now --all
git gc --prune=now --aggressive --quiet
git count-objects -vH | grep -E 'size-pack'

echo "── [6/6] 원격 복구 + 강제 푸시 ────────────"
git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
echo
echo "여기까지는 로컬만 바뀌었다. 원격에 반영하려면 아래를 직접 실행해라:"
echo
echo "    git push --force origin $BRANCH"
echo
echo "푸시 후 할 일:"
echo "  · Streamlit Cloud 재배포(재클론)"
echo "  · 다른 PC 의 클론은 버리고 다시 clone"
echo "  · 문제가 생기면 백업에서 복구: $BACKUP"
