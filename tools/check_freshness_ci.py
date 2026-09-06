# -*- coding: utf-8 -*-
"""
CI 산출물 신선도 검증 — 낡았으면 종료 코드 1 (2026-09-07 신설)

왜 필요한가
  daily-refresh 의 단계들은 전부 `continue-on-error: true` 다. 하나가 죽어도
  워크플로는 **초록불로 끝난다.** 실제로 미국 시총(us_marketcap.csv)이
  08-18 부터 19일간 갱신되지 않았는데 아무도 몰랐다 — 매일 캐시 없는 3,506종의
  시세를 받으려다 timeout-minutes: 55 를 넘겨 죽고 있었다.

  continue-on-error 를 걷어내면 한 단계 실패로 나머지 데이터까지 멈추므로 그건
  더 나쁘다. 대신 **파이프라인 끝에서 산출물의 실제 날짜를 검사**해서, 낡았으면
  워크플로를 실패시킨다. 실패하면 메일이 온다 — 그게 목적이다.

  data_freshness.py 도 pipeline_health.py 도 종료 코드를 내지 않는다(항상 0).
  화면에 빨간불을 그릴 뿐이라 CI 에서는 아무 역할을 못 했다.

CLI
  python tools/check_freshness_ci.py          # 낡으면 exit 1
  python tools/check_freshness_ci.py --warn   # 항상 exit 0 (보고만)
"""
import datetime
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (경로, 허용 일수) — 매일 도는 산출물만. 주간 산출물은 leaders_weekly 가 따로 검사한다.
CHECK = [
    ("data/us_marketcap.csv", 4),
    ("results/screener_latest.json", 4),
    ("results/perf_latest.json", 4),
    ("results/canslim_latest.json", 4),
    ("results/canslim_us_latest.json", 4),
    ("results/value_kr.json", 4),
]


def main():
    warn_only = "--warn" in sys.argv
    today = datetime.date.today()
    bad = []
    for rel, max_age in CHECK:
        path = os.path.join(BASE, rel)
        if not os.path.exists(path):
            print(f"  [MISSING] {rel}")
            bad.append(f"{rel}: 파일 없음")
            continue
        age = (today - datetime.date.fromtimestamp(os.path.getmtime(path))).days
        ok = age <= max_age
        print(f"  [{'OK   ' if ok else 'STALE'}] {rel:<40} {age}일 (허용 {max_age})")
        if not ok:
            bad.append(f"{rel}: {age}일 정지")

    if not bad:
        print("\n전부 최신")
        return 0

    print("\n낡은 산출물이 있다 — 위 단계 중 하나가 조용히 실패했다:")
    for b in bad:
        print("  -", b)
    print("\nActions 로그에서 해당 단계의 에러를 확인해라. "
          "continue-on-error 때문에 실패해도 초록불로 지나간다.")
    return 0 if warn_only else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
