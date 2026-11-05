# -*- coding: utf-8 -*-
"""미국 분기재무 — 10-Q·10-K 가 제출된 회사만 매일 다시 받는다 (2026-11-05 차니 "공식 제출 시점부터").

왜
  분기재무 캐시(data/leaders_cache/fq_*.csv)는 주 1회 weekly-accel 이 '최신 분기가 120일 넘었고
  파일이 7일 넘게 묵었으면' 다시 받았다. 월요일에 10-Q 가 나와도 다음 주말에야 들어오고,
  실행 시각이 몇 시간 당겨지면(6.7일) 한 주를 더 건너뛰었다. 전 종목을 매일 두드리면 SEC 요청이 2,800건.
무엇을
  SEC 일별 색인(daily-index/form.YYYYMMDD.idx)에서 최근 N 영업일에 10-Q·10-K 를 낸 CIK 만 골라
  그 회사들의 fq_ 를 강제로 다시 받는다(실패하면 기존 파일을 되살린다 — 없는 데이터로 덮지 않음).

  python tools/us_fq_daily.py [일수=5]
"""
import os
import re
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FORMS = {"10-Q", "10-K"}


def filers(day: date) -> set:
    """그날 10-Q·10-K 를 낸 CIK(10자리) 집합. 색인이 없는 날(휴일)은 빈 집합, 실패는 None."""
    import leaders_build as LB
    q = (day.month - 1) // 3 + 1
    url = f"https://www.sec.gov/Archives/edgar/daily-index/{day.year}/QTR{q}/form.{day:%Y%m%d}.idx"
    raw = LB.get(url, LB.SUA, tries=3)
    if raw is None:
        return set()
    out = set()
    for line in raw.decode("latin-1").splitlines():
        form = line[:12].strip()
        if form in FORMS:
            m = re.search(r"\s(\d{3,10})\s+(\d{8})\s+edgar/", line)
            if m:
                out.add(m.group(1).zfill(10))
    return out


def main(days=5):
    import leaders_build as LB
    cm = LB.cikmap()
    cik2sym = {}
    for s, c in cm.items():
        cik2sym.setdefault(c, set()).add(s)
    have = {p.stem[3:] for p in Path(LB.CACHE).glob("fq_*.csv")}
    ciks = set()
    d = date.today()
    for _ in range(days + 4):          # 주말 포함해 영업일 days 개
        d -= timedelta(days=1)
        if d.weekday() < 5:
            ciks |= filers(d)
            days -= 1
            if days <= 0:
                break
    syms = sorted({s for c in ciks for s in cik2sym.get(c, ())} & have)
    print(f"최근 제출 10-Q·10-K {len(ciks)}건 → 우리 유니버스 {len(syms)}종 다시 받음", flush=True)
    ok = bad = 0
    for s in syms:
        p = Path(LB.CACHE) / f"fq_{s}.csv"
        bak = p.with_suffix(".bak")
        os.replace(p, bak)
        if LB.fetch_fund(s, cm[s]) and p.exists():
            bak.unlink(missing_ok=True); ok += 1
        else:
            os.replace(bak, p); bad += 1
    print(f"  갱신 {ok} · 실패(기존 유지) {bad}", flush=True)
    return ok


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 5)
