# -*- coding: utf-8 -*-
"""
marketcap_fix_db.py — factor_weekly 의 marcap·per·psr 을 제자리에서 바로잡는다

왜 필요한가 (2026-08-18):
  leaders_build.py:395 가 주식수를 `낡은시총 ÷ 최신종가` 로 역산했다.
  그 오차가 marcap 은 물론 per·psr 에까지 전 주차 동일 배수로 곱해져 있었다.
  실측: 2,476종 중 시총 오차 ±25% 안은 27.5% 뿐. PER<20 행의 22.1%가 가짜.

왜 재적재가 아니라 제자리 보정인가:
  factor_weekly 전체 재적재는 가격·재무를 다시 받아 6시간 넘게 돈다(leaders_build 주석).
  그런데 틀린 건 **주식수 하나**이고 종가·재무는 이미 DB 에 정확히 들어 있다.
  marcap = 주식수 × 종가 이므로 저장된 종가로 다시 곱하면 그만이다.
  per = marcap/순이익, psr = marcap/매출 이라 분모는 그대로 → 같은 비율로 다시 스케일하면
  정확히 맞는다(근사가 아니라 항등식이다).

point-in-time:
  주식수는 SEC 공시(filed)마다 갱신되므로, 각 주차에 대해 **그 주차 이전에 제출된
  가장 최근 공시**의 주식수를 쓴다. 미래 공시를 끌어다 쓰지 않는다 → look-ahead 없음.
  분할은 us_splits.csv 로 오늘 주식수 기준(shares_adj)으로 환산해 둔 값을 쓴다
  (가격 캐시가 소급 분할조정돼 있어 주식수도 같은 기준이어야 한다).

CLI
  python marketcap_fix_db.py check    # 바뀌는 정도만 보고, 쓰지 않음
  python marketcap_fix_db.py apply    # 백업 뜨고 UPDATE
"""
import os, sys, shutil, sqlite3

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
SH = os.path.join(BASE, "data", "us_shares.csv")
VER = "v1"


def shares_at(sh: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    """주차 × 종목 → 그 주차 시점에 알 수 있던 주식수(오늘 분할 기준).

    merge_asof 로 '주차 <= filed' 가 아니라 '가장 최근 filed <= 주차' 를 고른다.
    공시 전 구간(첫 공시보다 앞선 주차)은 첫 공시값으로 뒤로 채운다 — 그 시절
    주식수를 알 방법이 없고, 비우면 그 구간이 통째로 유니버스에서 빠진다.
    """
    out = {}
    for sym, g in sh.groupby("sym", sort=False):
        g = g.dropna(subset=["filed", "shares_adj"]).sort_values("filed")
        if g.empty:
            continue
        s = pd.Series(g.shares_adj.values,
                      index=pd.to_datetime(g.filed.values))
        s = s[~s.index.duplicated(keep="last")]
        out[sym] = s.reindex(s.index.union(weeks)).ffill().bfill().reindex(weeks)
    return pd.DataFrame(out, index=weeks)


def main(apply: bool):
    if not os.path.exists(SH):
        sys.exit(f"{SH} 가 없다. 먼저 `python marketcap_refresh.py all` 을 돌려라.")
    sh = pd.read_csv(SH)
    print(f"주식수 시계열 {len(sh):,}행 · {sh.sym.nunique()}종")

    con = sqlite3.connect(DB)
    d = pd.read_sql(f"SELECT rowid, as_of, sym, close, marcap, per, psr "
                    f"FROM factor_weekly WHERE factor_ver='{VER}'", con)
    d["as_of"] = pd.to_datetime(d.as_of)
    weeks = pd.DatetimeIndex(sorted(d.as_of.unique()))
    print(f"factor_weekly {len(d):,}행 · {d.sym.nunique()}종 · 주차 {len(weeks)}")

    S = shares_at(sh, weeks)
    print(f"주식수 매칭된 종목 {S.shape[1]}종 "
          f"(DB 종목의 {S.columns.isin(d.sym.unique()).sum()/d.sym.nunique()*100:.1f}%)")

    idx = pd.MultiIndex.from_arrays([d.as_of, d.sym])
    st = S.stack(future_stack=True).reindex(idx).values
    new_mc = st * d.close.values

    ok = np.isfinite(new_mc) & (new_mc > 0) & np.isfinite(d.marcap.values) & (d.marcap.values > 0)
    ratio = np.where(ok, new_mc / d.marcap.values, np.nan)
    print(f"\n보정 가능 {ok.sum():,}행 ({ok.mean()*100:.1f}%) · "
          f"주식수 없어 그대로 두는 행 {(~ok).sum():,}")
    r = pd.Series(ratio[ok])
    print("  배수 분포: " + "  ".join(f"{p}%={r.quantile(p/100):.2f}"
                                   for p in (5, 25, 50, 75, 95)))
    print(f"  2배 이상 바뀌는 행 {(r.gt(2) | r.lt(.5)).sum():,} ({(r.gt(2)|r.lt(.5)).mean()*100:.1f}%)")

    old2b = (d.marcap.values >= 2e9)
    new2b = np.where(ok, new_mc >= 2e9, old2b)
    print(f"\n  $2B 문턱 통과: {old2b.sum():,}행 → {new2b.sum():,}행 "
          f"(신규 {(~old2b & new2b).sum():,} · 탈락 {(old2b & ~new2b).sum():,})")

    if not apply:
        print("\ncheck 모드 — DB 를 바꾸지 않았다. 적용하려면 `apply`.")
        con.close()
        return

    bak = DB + f".bak-capfix-{pd.Timestamp.now():%Y%m%d-%H%M}"
    con.close()
    print(f"\n백업 → {os.path.basename(bak)}", flush=True)
    shutil.copy2(DB, bak)

    con = sqlite3.connect(DB)
    con.execute("PRAGMA journal_mode=WAL")
    rows = [(float(new_mc[i]),
             float(d.per.values[i] * ratio[i]) if pd.notna(d.per.values[i]) else None,
             float(d.psr.values[i] * ratio[i]) if pd.notna(d.psr.values[i]) else None,
             int(d.rowid.values[i]))
            for i in np.where(ok)[0]]
    con.executemany("UPDATE factor_weekly SET marcap=?, per=?, psr=? WHERE rowid=?", rows)
    con.commit()
    con.close()
    print(f"완료 — {len(rows):,}행 갱신 (marcap·per·psr)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main(apply=(sys.argv[1:] or ["check"])[0] == "apply")
