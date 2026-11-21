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
  python tools/check_freshness_ci.py --job weekly-accel     # 레지스트리에서 그 job 산출물만
  python tools/check_freshness_ci.py --all                  # 등록된 전부

주간 산출물 (2026-11-22 추가)
  머리말에 "주간 산출물은 leaders_weekly 가 따로 검사한다"고 적혀 있었다. 그 leaders_weekly 를
  11-22 에 폐기했고, 폐기 전에도 /tmp 경로 버그로 죽어 있었다 — **주간 산출물은 한동안
  아무도 날짜를 보지 않았다.**

  ⚠️ 주간 것을 아래 CHECK(파일 mtime 기준)에 그냥 넣으면 **쓸모없다.** CI 는 매번 새로
  clone 하므로 모든 파일의 mtime 이 체크아웃 시각(=오늘)이다. mtime 검사가 daily-refresh 에서
  작동하는 건 그 산출물을 **같은 잡에서 방금 쓰기 때문**이고, 다른 워크플로가 만든 파일은
  언제나 '최신'으로 보인다.
  → 주간은 `data_freshness.statuses()` 를 쓴다. 거기 getter 는 **파일 내부 날짜 필드**
    (generated·asof·as_of…)를 읽으므로 체크아웃 시각과 무관하다. 허용 일수·경로도 그 한 곳
    (SOURCES, 41개)에만 적혀 있어 목록이 두 벌로 갈라지지 않는다.
"""
import datetime
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (경로, 허용 일수) — **같은 잡에서 방금 쓰였는지**를 mtime 으로 보는 목록(일간 전용).
#   주간·타 워크플로 산출물은 여기 넣지 말 것 — 위 머리말의 mtime 함정에 걸린다. --job 을 쓴다.
CHECK = [
    ("data/us_marketcap.csv", 4),
    ("results/screener_latest.json", 4),
    ("results/perf_latest.json", 4),
    ("results/canslim_latest.json", 4),
    ("results/canslim_us_latest.json", 4),
    ("results/value_kr.json", 4),
]


# 운영 주기 산출물의 기준 — 허용 일수가 이보다 길면 '수동·연구용'으로 보고 감시 대상에서 뺀다.
#   (research-rs·역분석 등은 max_age 400 으로 등록돼 있다 — 규칙이 바뀔 때만 다시 돈다)
AUDIT_MAX_AGE = 40


def audit(strict=False):
    """2026-11-22 신설 — **감시 커버리지 감사.**

    왜: 주간 산출물이 감시 밖으로 새어 나간 건 '주간을 빼먹었다'가 아니라
    '누가 무엇을 보는지 아무도 세지 않았다' 때문이다. 레지스트리에 산출물을 추가해도
    워크플로에 `--job` 을 안 붙이면 **화면에 빨간불만 그리고 CI 는 초록불**이다.
    여기서 레지스트리 × 워크플로를 맞대어 '감시자가 없는 산출물'을 이름으로 부른다.
    """
    import glob
    import re
    sys.path.insert(0, BASE)
    import data_freshness as F
    gated = set()
    for p in glob.glob(os.path.join(BASE, ".github", "workflows", "*.yml")):
        for m in re.finditer(r"check_freshness_ci\.py\s+(--all|--job\s+(\S+))", open(p, encoding="utf-8").read()):
            gated.add("*" if m.group(1) == "--all" else m.group(2))
    hard = {rel for rel, _ in CHECK}            # mtime 목록도 감시자다
    rows, holes = [], []
    for s in F.SOURCES:
        if s["max_age"] > AUDIT_MAX_AGE:
            continue
        job = (s["job"] or "").lower()
        who = sorted(g for g in gated if g == "*" or g.lower() in job)
        if s["path"] in hard:
            who.append("mtime")
        rows.append((s["path"], s["max_age"], s["job"], who))
        if not who:
            holes.append(s)
    print(f"[감시 커버리지] 운영 산출물 {len(rows)}개 (허용 {AUDIT_MAX_AGE}일 이내 등록분) · "
          f"워크플로에 걸린 --job {sorted(gated)}")
    for path, ma, job, who in rows:
        print(f"  [{'OK  ' if who else 'HOLE'}] {path:<46s} 허용{ma:>3d}일  job={job:<34s} 감시자={','.join(who) or '없음'}")
    if not holes:
        print("\n감시 공백 없음")
        return 0
    print(f"\n감시자가 없는 산출물 {len(holes)}개 — 화면엔 빨간불이 떠도 CI 는 초록불로 지나간다:")
    for s in holes:
        print(f"  - {s['path']} (job={s['job']}) → 그 워크플로 끝에 "
              f"`python tools/check_freshness_ci.py --job <이름>` 을 붙이거나 "
              f"수동 산출물이면 max_age 를 {AUDIT_MAX_AGE}일 초과로 올려라")
    return 1 if strict else 0


def by_job(job_substr, warn_only=False):
    """레지스트리(data_freshness.SOURCES)에서 job 이름에 job_substr 가 들어간 산출물만 검사.
    job_substr 가 None 이면 전부. 날짜는 **파일 내부 필드**로 잰다(체크아웃 시각과 무관)."""
    sys.path.insert(0, BASE)
    import data_freshness as F
    #   only= 로 좁혀 넘긴다 — 안 그러면 41개 파일을 다 연다(워크플로마다 parquet 의존성이 다르다)
    want = None if job_substr is None else {
        s["path"] for s in F.SOURCES if job_substr.lower() in (s["job"] or "").lower()}
    if want is not None and not want:
        print(f"[freshness] job '{job_substr}' 에 해당하는 등록 산출물이 없다 — "
              f"이름이 바뀌었는지 data_freshness.SOURCES 의 job 을 확인하라")
        return 0 if warn_only else 1          # 조용히 통과시키면 감시가 사라진다
    rows = F.statuses(only=want)
    bad = []
    for r in rows:
        mark = {"ok": "OK   ", "stale": "STALE", "missing": "MISS ",
                "nodate": "NODT ", "error": "ERR  "}.get(r["state"], r["state"])
        print(f"  [{mark}] {r['path']:<46s} {r['date'] or '-':<10s} "
              f"{'' if r['age'] is None else str(r['age']) + '일'} (허용 {r['max_age']}일)  {r['note']}")
        if r["state"] != "ok":
            bad.append(f"{r['path']}: {r['note'] or r['state']}")
    print(f"\n{len(rows) - len(bad)}/{len(rows)} 최신" + (" — 전부 최신" if not bad else ""))
    if not bad:
        return 0
    print("\n낡거나 없는 산출물 — 이 워크플로의 어느 단계가 조용히 실패했다:")
    for b in bad:
        print("  -", b)
    return 0 if warn_only else 1


def main():
    warn_only = "--warn" in sys.argv
    if "--audit" in sys.argv:
        return audit(strict=not warn_only)
    if "--all" in sys.argv:
        return by_job(None, warn_only)
    if "--job" in sys.argv:
        i = sys.argv.index("--job")
        if i + 1 >= len(sys.argv):
            print("--job 뒤에 job 이름(부분 문자열)이 필요하다"); return 2
        return by_job(sys.argv[i + 1], warn_only)
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
