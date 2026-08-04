# -*- coding: utf-8 -*-
"""
실적 이벤트 테이블 — '1년에 4번만 본다' 체제
  판단 시점 = 각 종목의 실적 반응 주 (8-K item 2.02 기준, AMC면 다음 거래일)
  그 주 종가에 결정하고, 다음 실적까지 아무것도 안 한다.

  python leaders_events.py build     # earnings_event 테이블 생성
  python leaders_events.py check     # 커버리지 확인
"""
import os, sqlite3, sys, glob
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "leaders_cache")
DB = os.path.join(DATA, "market.db")


def build():
    con = sqlite3.connect(DB)
    fw = pd.read_sql("SELECT * FROM factor_weekly WHERE factor_ver='v1'", con)
    fw["as_of"] = pd.to_datetime(fw.as_of)
    fwi = fw.set_index(["sym", "as_of"])
    print(f"factor_weekly {len(fw):,}행 로드")

    rows = []
    files = sorted(glob.glob(os.path.join(CACHE, "ek_*.csv")))
    for n, ekp in enumerate(files, 1):
        sym = os.path.basename(ekp)[3:-4]
        pxp = os.path.join(CACHE, f"px_{sym}.csv")
        dyp = os.path.join(CACHE, f"dy_{sym}.csv")
        if not (os.path.exists(pxp) and os.path.exists(dyp)):
            continue
        w = pd.read_csv(pxp, index_col=0, parse_dates=True).sort_index()
        d = pd.read_csv(dyp, index_col=0, parse_dates=True).sort_index()
        ek = pd.read_csv(ekp)
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
            continue
        E = pd.DataFrame(ev).drop_duplicates("as_of").sort_values("as_of").reset_index(drop=True)
        # 다음 실적까지의 수익률 (가변 기간) + 고정 지평
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
        # 실적 사이 최대 낙폭 (분기 점검의 비용)
        dd = []
        for i, j, p in zip(E.wi, nxt, E.close):
            if j != j:
                dd.append(np.nan); continue
            seg = c.iloc[int(i):int(j) + 1]
            dd.append((seg.min() / p - 1) * 100 if len(seg) else np.nan)
        E["dd_to_next"] = dd
        # 연속 양(+) 실적반응
        pos = (E.react_w0 > 0).astype(int)
        E["react_streak"] = pos.groupby((pos == 0).cumsum()).cumcount() * pos
        rows.append(E.drop(columns=["wi"]))
        if n % 200 == 0:
            print(f"  {n}/{len(files)}", flush=True)

    ALL = pd.concat(rows, ignore_index=True)
    ALL["as_of"] = pd.to_datetime(ALL.as_of)
    # factor_weekly 조인 — 그 주에 알 수 있던 모든 팩터
    keep = [c for c in fw.columns if c not in
            ("sym", "as_of", "close", "name", "sector", "factor_ver", "built_at",
             "earn_date", "earn_time", "earn_week_flag", "earn_react_w0",
             "earn_react_d2", "earn_react_gap")]
    J = ALL.merge(fw[["sym", "as_of", "name"] + keep], on=["sym", "as_of"], how="left")
    J.to_sql("earnings_event", con, if_exists="replace", index=False)
    con.execute("CREATE INDEX IF NOT EXISTS ix_ee ON earnings_event(as_of, sym)")
    con.commit()
    print(f"\nearnings_event {len(J):,}행 · {J.sym.nunique()}종")
    print(f"  기간 {J.as_of.min().date()} ~ {J.as_of.max().date()}")
    g = J.groupby("sym").size()
    print(f"  종목당 실적주 중앙 {g.median():.0f}회 (30회 이상 {int((g>=30).sum())}종)")
    print(f"  팩터 결합 성공률 {J.dist_52w.notna().mean()*100:.0f}%")
    print(f"  다음 실적까지 보유주수 중앙 {J.hold_wk.median():.0f}주")
    con.close()


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
