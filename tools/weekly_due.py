# -*- coding: utf-8 -*-
"""
주간 사이클을 지금 돌려야 하는가 — exit 0 = 돌려라, exit 1 = 이미 최신이다

왜 필요한가 (2026-09-09)
  작업 스케줄러가 토요일 08:00 주 1회로 잡혀 있었다(WeeksInterval=1,
  StartWhenAvailable=true). 설정은 맞았는데 **9/5 토요일을 통째로 걸렀다.**
  그날 PC 가 꺼져 있었고, Windows 는 놓친 *주간* 작업을 다음 주까지 다시 잡지
  않는다(마지막 실행 08-29 → 다음 실행 09-12). 화면에서는 "주차별 조회가
  8/24 이후 안 늘어남"으로만 보였다.

  그래서 트리거를 **매일**로 바꾸고, 이 스크립트가 문지기를 한다.
  토요일에 놓쳐도 일요일·월요일에 잡는다. 이미 최신이면 즉시 빠져나온다.

기준 — "금요일 종가"
  미국 장은 금요일에 마감하고, factor_weekly 의 주차 라벨은 그 주 **월요일**이다.
  가장 최근에 종가가 확정된 주차 = 직전 금요일이 속한 주의 월요일.
    · 토·일          → 이번 주 월요일 (금요일 장이 이미 끝났다)
    · 월~금          → 지난주 월요일 (이번 주 금요일은 아직 안 왔다)
  signal_week 가 그 값 이상이면 돌 필요가 없다.

깨지는 지점
  · 휴장일(추수감사절 등)로 금요일 장이 없으면 하루 일찍 확정되지만, 그 주차
    라벨은 같으므로 판정에 영향이 없다.
  · 데이터 제공처가 늦어 토요일 아침에 아직 금요일 종가가 안 들어왔으면,
    돌긴 돌되 지난주까지만 만들어진다. 다음 날 다시 돌면서 따라잡는다.

CLI
  python tools/weekly_due.py          # exit 0 = 실행 필요
  python tools/weekly_due.py --why    # 판단 근거를 찍는다
"""
import datetime
import json
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SIG = os.path.join(BASE, "results", "leaders_accel.json")


def last_closed_week(today=None):
    """종가가 확정된 가장 최근 주차(그 주 월요일)."""
    d = today or datetime.date.today()
    wd = d.weekday()                      # 월=0 … 금=4 토=5 일=6
    monday = d - datetime.timedelta(days=wd)
    if wd >= 5:                           # 토·일 — 이번 주 금요일 장이 끝났다
        return monday
    return monday - datetime.timedelta(days=7)   # 월~금 — 지난주까지가 확정


def main():
    why = "--why" in sys.argv
    want = last_closed_week()
    if not os.path.exists(SIG):
        if why:
            print(f"[실행 필요] {os.path.basename(SIG)} 가 없다")
        return 0
    try:
        have = json.load(open(SIG, encoding="utf-8")).get("signal_week")
    except Exception as e:
        if why:
            print(f"[실행 필요] 신호 파일을 읽을 수 없다: {e}")
        return 0
    if why:
        print(f"  확정된 최신 주차 {want}  ·  파일의 주차 {have}")
    if have and str(have) >= str(want):
        if why:
            print("[스킵] 이미 최신")
        return 1
    if why:
        print("[실행 필요] 주차가 밀려 있다")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
