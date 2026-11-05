# -*- coding: utf-8 -*-
"""한국 정기보고서 실제 제출일 — 백테스트·신호가 '공시된 날부터' 재무를 쓰게 한다 (2026-11-05 차니).

왜
  지금까지 한국 분기 재무는 '분기말 + 45일(4분기 90일)'에 알게 됐다고 일괄 가정했다(quant_panel)·
  leaders_kr 는 +50일. 실제로는 마감 전에 내는 회사가 많아 며칠~몇 주 늦게 쓰고, 드물게 마감을 넘기면
  미래를 훔쳐본다. 미국은 이미 SEC 제출일(filed_at)을 쓴다 — 한국도 DART 접수일로 맞춘다.

무엇을
  DART 공시검색(list.json, 정기공시 A)에서 '분기보고서 (2026.09)'·'반기보고서 (2026.06)'·'사업보고서 (2025.12)'
  의 접수일(rcept_dt)을 모은다. 정정 공시([기재정정] 등)는 늦은 날짜라 **가장 이른 접수일**을 쓴다(처음 알 수 있던 날).
  12월 결산이 아닌 회사는 분기 재무에서 빠져 있으므로(kr_nondec.json) 결산월 3·6·9·12 만 받는다.

결과 data/kr_filing_dates.parquet — sym, year, q(1~4), filed(YYYY-MM-DD)
  · 파일이 없으면 2017-01-01 부터 전체, 있으면 최근 200일만 다시 받아 합친다(증분).
  · DART 가 닿는 곳(집 PC · 가끔 Actions)에서만 돈다. 안 닿으면 아무것도 바꾸지 않는다.

  python tools/kr_filing_dates.py            # 증분
  python tools/kr_filing_dates.py --full     # 전체 다시
"""
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "kr_filing_dates.parquet"
RX = re.compile(r"(분기보고서|반기보고서|사업보고서)\s*\((\d{4})\.(\d{2})\)")
WORKERS = 6


def parse(report_nm: str):
    """'[기재정정]분기보고서 (2026.09)' → (2026, 3). 결산월이 3·6·9·12 가 아니면 None."""
    m = RX.search(report_nm or "")
    if not m:
        return None
    y, mm = int(m.group(2)), int(m.group(3))
    if mm not in (3, 6, 9, 12):
        return None
    return y, mm // 3


def known(sym, year, q, lag=(45, 90)):
    """(sym, year, q) 배열 → 알게 된 날(Timestamp 배열). 실제 제출일이 있으면 그날 **다음 날**
    (장 마감 뒤 접수가 많다 — 그날 종가로 사면 미래를 본다), 없으면 분기말 + lag(1~3분기, 4분기).
    반환 (날짜, 실제 제출일 여부 bool 배열)."""
    import numpy as np
    import pandas as pd
    sym = pd.Series(sym).astype(str).str.zfill(6).values
    year = pd.Series(year).astype(int).values
    q = pd.Series(q).astype(int).values
    end = pd.to_datetime([f"{y}-{m * 3:02d}-01" for y, m in zip(year, q)]) + pd.offsets.MonthEnd(0)
    assumed = end + pd.to_timedelta(np.where(q == 4, lag[1], lag[0]), unit="D")
    if not OUT.exists():
        return pd.DatetimeIndex(assumed), np.zeros(len(sym), bool)
    f = pd.read_parquet(OUT)
    f["sym"] = f["sym"].astype(str).str.zfill(6)
    key = pd.MultiIndex.from_arrays([sym, year, q])
    fd = pd.to_datetime(f.set_index(["sym", "year", "q"])["filed"]).reindex(key)
    has = fd.notna().values
    real = pd.DatetimeIndex(fd.values) + pd.Timedelta(days=1)
    return pd.DatetimeIndex(np.where(has, real, assumed)), has


def fetch(corp_code: str, bgn: str, end: str) -> list:
    """한 회사의 정기공시 [(year, q, rcept_dt)]. 실패하면 None(빈 결과와 구별)."""
    import requests
    import dart_client as D
    out, page = [], 1
    while True:
        try:
            r = requests.get(f"{D.BASE}/list.json", timeout=20, headers={"Connection": "close"},
                             params={"crtfc_key": D._key(), "corp_code": corp_code, "bgn_de": bgn, "end_de": end,
                                     "pblntf_ty": "A", "page_no": page, "page_count": 100})
            j = r.json()
        except Exception:
            return None
        st = j.get("status")
        if st == "013":                 # 조회 결과 없음
            return out
        if st != "000":
            return None
        for x in j.get("list", []):
            p = parse(x.get("report_nm"))
            if p and x.get("rcept_dt"):
                out.append((p[0], p[1], x["rcept_dt"]))
        if page >= int(j.get("total_page") or 1):
            return out
        page += 1
        time.sleep(0.2)


def main(full=False):
    import pandas as pd
    import dart_client as D
    try:
        cm = D.corp_map()
    except Exception as e:
        print(f"DART 회사 목록 실패({type(e).__name__}) — 건너뜀", flush=True)
        return False
    fq = pd.read_parquet(ROOT / "data" / "kr_fundamentals_q.parquet", columns=["sym"])
    syms = sorted(set(fq.sym.astype(str).str.zfill(6)))
    pairs = [(s, cm[s]) for s in syms if s in cm]
    old = pd.read_parquet(OUT) if (OUT.exists() and not full) else None
    bgn = "20170101" if old is None else (date.today() - timedelta(days=200)).strftime("%Y%m%d")
    end = date.today().strftime("%Y%m%d")
    print(f"제출일 수집 {len(pairs)}종 · {bgn}~{end}", flush=True)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        res = list(ex.map(lambda p: (p[0], fetch(p[1], bgn, end)), pairs))
    fail = sum(1 for _, r in res if r is None)
    rows = [(s, y, q, d) for s, r in res if r for (y, q, d) in r]
    print(f"  {len(rows):,}건 · 실패 {fail}종 · {time.time() - t0:.0f}초", flush=True)
    if fail > len(pairs) * 0.3:          # 대부분 실패 = DART 가 안 닿는 서버. 기존 파일을 지키고 실패로 알린다
        print(f"::warning title=KR 제출일::DART 실패 {fail}/{len(pairs)} — 기존 파일 유지", flush=True)
        return False
    new = pd.DataFrame(rows, columns=["sym", "year", "q", "filed"])
    if old is not None:
        new = pd.concat([old, new])
    new["filed"] = pd.to_datetime(new["filed"].astype(str)).dt.strftime("%Y-%m-%d")
    new = new.groupby(["sym", "year", "q"], as_index=False)["filed"].min()      # 처음 알 수 있던 날
    new = new.sort_values(["sym", "year", "q"]).reset_index(drop=True)
    new.to_parquet(OUT, index=False)
    print(f"{OUT.name} — {len(new):,}행 · {new.sym.nunique():,}종 · {new.year.min()}~{new.year.max()}", flush=True)
    return True


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ok = main(full="--full" in sys.argv)
    sys.exit(0 if ok else 1)
