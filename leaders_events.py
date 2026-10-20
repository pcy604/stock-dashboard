# -*- coding: utf-8 -*-
"""
실적 이벤트 테이블 (earnings_event) — PEAD 검증용.

  python leaders_events.py build     # earnings_event 테이블 생성 + 커버리지 요약 저장
  python leaders_events.py check     # 커버리지 확인

복원 이력 (2026-10-20)
  08-31 대청소(42c4bbb)에서 삭제됐다. 그 전에 만든 테이블(2026-08-05)은 당시 수집 기준
  '현재 시총 $2B 이상' 1,249종에만 있었다 → "나중에 커진 회사"를 미리 고른 집합이라
  PEAD 결과(24.6%)에 종목 선택 편향 의심이 남았다(05 문서 §3).
  복원판은 universe 전체(data/universe_ever.csv 포함, 한 번 들어온 종목은 빼지 않음)를 대상으로 하고,
  주봉은 px_*.csv 대신 market.db(prices) 에서 읽는다(10-10 이후 보관소가 하나).

입력
  ek_{sym}.csv   leaders_build.fetch_8k — 8-K item 2.02 접수 시각 → BMO/AMC
  dy_{sym}.csv   leaders_build.fetch_px — 일봉(수정주가)
  prices         market.db 주봉(월요일 라벨)
  factor_weekly  그 주에 알 수 있던 팩터 조인 (FACTOR_VER, 기본 v1 · v13y 가 있으면 그쪽)
"""
import os, sqlite3, sys, glob, json, time
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "leaders_cache")
DB = os.path.join(DATA, "market.db")
SUMMARY = os.path.join(BASE, "results", "earnings_event_summary.json")


def _factor_ver(con):
    want = os.environ.get("FACTOR_VER")
    have = {r[0]: r[1] for r in con.execute(
        "SELECT factor_ver, COUNT(DISTINCT sym) FROM factor_weekly GROUP BY factor_ver")}
    if want:
        return want, have
    return ("v13y" if have.get("v13y", 0) >= have.get("v1", 0) and "v13y" in have else "v1"), have


def _weekly(sym, con):
    try:
        import price_store
        w = price_store.get(sym, "US", conn=con)
        if w is not None and len(w):
            return w.sort_index()
    except Exception:
        pass
    p = os.path.join(CACHE, f"px_{sym}.csv")          # 구버전 캐시 호환
    return pd.read_csv(p, index_col=0, parse_dates=True).sort_index() if os.path.exists(p) else None


def events_for(sym, w, d, ek):
    """한 종목의 실적 이벤트 행들. w=주봉, d=일봉, ek=8-K 발표일(earn_date, earn_time)."""
    ek = ek.copy()
    ek["earn_date"] = pd.to_datetime(ek.earn_date)
    ek = ek.sort_values("earn_date").drop_duplicates("earn_date")
    c = w["Close"]
    ev = []
    for _, e in ek.iterrows():
        ed = e.earn_date
        # 반응일 = AMC면 다음 거래일, 아니면 당일
        di = int(np.searchsorted(d.index, ed))
        if e.earn_time == "AMC":
            di += 1
        if di < 2 or di >= len(d):
            continue
        react = d.index[di]
        wi = int(np.searchsorted(w.index, react, side="right")) - 1
        if wi < 21 or wi >= len(w) - 1:
            continue
        prev = float(d["Close"].iloc[di - 1])
        if not prev:
            continue
        ev.append(dict(
            sym=sym, as_of=w.index[wi], wi=wi,
            earn_date=str(ed.date()), earn_time=e.earn_time,
            react_gap=(float(d["Open"].iloc[di]) / prev - 1) * 100,
            react_d0=(float(d["Close"].iloc[di]) / prev - 1) * 100,
            react_d1=((float(d["Close"].iloc[di + 1]) / float(d["Close"].iloc[di]) - 1) * 100
                      if di + 1 < len(d) else np.nan),
            react_w0=(float(c.iloc[wi]) / float(c.iloc[wi - 1]) - 1) * 100,
            close=float(c.iloc[wi]),
        ))
    if not ev:
        return None
    E = pd.DataFrame(ev).drop_duplicates("as_of").sort_values("as_of").reset_index(drop=True)
    E["next_as_of"] = E.as_of.shift(-1)
    E["hold_wk"] = (E.wi.shift(-1) - E.wi)
    nxt = E.wi.shift(-1)
    E["ret_to_next"] = [((float(c.iloc[int(j)]) / p - 1) * 100)
                        if j == j and int(j) < len(c) else np.nan
                        for j, p in zip(nxt, E.close)]
    for h in (13, 26, 52):
        E[f"ret_{h}w"] = [((float(c.iloc[min(i + h, len(c) - 1)]) / p - 1) * 100)
                          if i + h < len(c) else np.nan
                          for i, p in zip(E.wi, E.close)]
    dd = []
    for i, j, p in zip(E.wi, nxt, E.close):
        if j != j:
            dd.append(np.nan); continue
        seg = c.iloc[int(i):int(j) + 1]
        dd.append((seg.min() / p - 1) * 100 if len(seg) else np.nan)
    E["dd_to_next"] = dd
    pos = (E.react_w0 > 0).astype(int)
    E["react_streak"] = pos.groupby((pos == 0).cumsum()).cumcount() * pos
    return E.drop(columns=["wi"])


def _universe():
    s = set()
    for p in (os.path.join(CACHE, "_universe.csv"), os.path.join(DATA, "universe_ever.csv")):
        if os.path.exists(p):
            try:
                s |= set(pd.read_csv(p)["sym"].astype(str))
            except Exception:
                pass
    return s


def build():
    con = sqlite3.connect(DB)
    ver, have = _factor_ver(con)
    fw = pd.read_sql("SELECT * FROM factor_weekly WHERE factor_ver=?", con, params=(ver,))
    fw["as_of"] = pd.to_datetime(fw.as_of)
    print(f"factor_weekly[{ver}] {len(fw):,}행 · {fw.sym.nunique():,}종 (보유 버전 {have})")

    uni = _universe()
    ek_syms = {os.path.basename(p)[3:-4] for p in glob.glob(os.path.join(CACHE, "ek_*.csv"))}
    targets = sorted(ek_syms | uni) if uni else sorted(ek_syms)
    why = {"8-K 발표일 없음": 0, "일봉 없음": 0, "주봉 없음": 0, "이벤트 0건": 0}
    rows = []
    t0 = time.time()
    for n, sym in enumerate(targets, 1):
        ekp = os.path.join(CACHE, f"ek_{sym}.csv")
        dyp = os.path.join(CACHE, f"dy_{sym}.csv")
        if not os.path.exists(ekp):
            why["8-K 발표일 없음"] += 1; continue
        if not os.path.exists(dyp):
            why["일봉 없음"] += 1; continue
        w = _weekly(sym, con)
        if w is None or len(w) < 30:
            why["주봉 없음"] += 1; continue
        d = pd.read_csv(dyp, index_col=0, parse_dates=True).sort_index()
        try:
            E = events_for(sym, w, d, pd.read_csv(ekp))
        except Exception as e:
            print(f"  [skip] {sym}: {str(e)[:80]}"); E = None
        if E is None:
            why["이벤트 0건"] += 1; continue
        rows.append(E)
        if n % 300 == 0:
            print(f"  {n}/{len(targets)} · {time.time() - t0:.0f}s", flush=True)

    if not rows:
        print("::error title=earnings_event::이벤트 0건 — 캐시(ek_/dy_) 복원 여부부터 확인")
        sys.exit(1)
    ALL = pd.concat(rows, ignore_index=True)
    ALL["as_of"] = pd.to_datetime(ALL.as_of)
    keep = [c for c in fw.columns if c not in
            ("sym", "as_of", "close", "name", "sector", "factor_ver", "built_at",
             "earn_date", "earn_time", "earn_week_flag", "earn_react_w0",
             "earn_react_d2", "earn_react_gap")]
    J = ALL.merge(fw[["sym", "as_of", "name"] + keep], on=["sym", "as_of"], how="left")
    J["factor_ver"] = ver
    J.to_sql("earnings_event", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_ee ON earnings_event(as_of, sym)")
    con.commit()

    g = J.groupby("sym").size()
    joined = float(J["dist_52w"].notna().mean()) if "dist_52w" in J else None
    S = dict(
        built=time.strftime("%Y-%m-%d %H:%M"), factor_ver=ver,
        rows=int(len(J)), syms=int(J.sym.nunique()), targets=len(targets), universe=len(uni),
        period=[str(J.as_of.min().date()), str(J.as_of.max().date())],
        per_sym_median=float(g.median()), factor_join_rate=joined,
        dropped=why, by_year={int(k): int(v) for k, v in J.groupby(J.as_of.dt.year).size().items()},
        # 2026-08-05 판(1,249종, 시총 $2B+ 사후 선택)과 비교용
        prev_build=dict(date="2026-08-05", syms=1249, rows=63365, note="현재 시총 $2B 이상만 — 선택 편향"),
    )
    os.makedirs(os.path.dirname(SUMMARY), exist_ok=True)
    json.dump(S, open(SUMMARY, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\nearnings_event {len(J):,}행 · {J.sym.nunique():,}종 · 대상 {len(targets):,} · 빠진 이유 {why}")
    print(f"  기간 {S['period'][0]} ~ {S['period'][1]} · 종목당 중앙 {S['per_sym_median']:.0f}회 · 팩터 결합 {joined}")
    print(f"::notice title=earnings_event::{len(J):,}행 · {J.sym.nunique():,}종(08-05판 1,249종) · "
          f"{S['period'][0]}~{S['period'][1]} · 빠짐 {why}")
    con.close()
    return S


def check():
    con = sqlite3.connect(DB)
    d = pd.read_sql("SELECT * FROM earnings_event", con)
    con.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    print(f"{len(d):,}행 · {d.sym.nunique()}종 · {d.as_of.min().date()}~{d.as_of.max().date()}")
    print("\n연도별 이벤트 수")
    print(d.groupby(d.as_of.dt.year).size().to_string())
    print("\n핵심 컬럼 분포")
    for c in ["react_gap", "react_d0", "react_w0", "ret_to_next", "dd_to_next",
              "hold_wk", "dist_52w", "opm_qoq", "psr"]:
        if c in d:
            v = d[c].dropna()
            print(f"  {c:12s} n={len(v):6,}  중앙 {v.median():+8.2f}  "
                  f"25% {v.quantile(.25):+8.2f}  75% {v.quantile(.75):+8.2f}")


if __name__ == "__main__":
    (build if (len(sys.argv) < 2 or sys.argv[1] == "build") else check)()
