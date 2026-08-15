# -*- coding: utf-8 -*-
"""
전략 전수 스윕 — 시총 게이트 없이, 여러 매매 아이디어를 같은 조건에서 비교

공통: 청산 = 주봉 종가가 고점 대비 −20% 도달 시 전량 / 유동성 거래대금 $1M+ /
      종료일 2026-08-03 (08-10 주차는 393종만 있어 자산계산이 오염된다)
"""
import os, warnings, sqlite3
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 260)
BASE = os.path.dirname(os.path.abspath(__file__))
END = "2026-08-03"
SPL = [("2021", "2021-01-01", "2021-12-31"), ("2022", "2022-01-01", "2022-12-31"),
       ("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"),
       ("2025", "2025-01-01", "2025-12-31"), ("2025H2~26", "2025-07-01", END)]
LIQ = 1e6


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    ex = pd.read_sql("SELECT as_of,sym,mdd_52w,vol_x_20w,hi_20w,low_52w_dist "
                     "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    ex["as_of"] = pd.to_datetime(ex.as_of)
    for col in ["mdd_52w", "vol_x_20w", "hi_20w", "low_52w_dist"]:
        M[col] = ex.pivot(index="as_of", columns="sym", values=col).reindex_like(P)
    S = L2.spy().reindex(P.index, method="nearest")

    def spy_cagr(a, b=None):
        s = S.loc[a:] if b is None else S.loc[a:b]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100

    def g(M, i, k):
        return M[k].iloc[i]

    R = {
        "01 A 현행⑥ (시총게이트 유지)":
            lambda M, i: (g(M,i,"rs_13w") > 1.5) & (g(M,i,"opm") > 0) &
                         ((g(M,i,"op_turn") == 1) | (g(M,i,"b_any") == 1)) &
                         (g(M,i,"marcap") >= 2e9),
        "02 A 시총게이트 제거":
            lambda M, i: (g(M,i,"rs_13w") > 1.5) & (g(M,i,"opm") > 0) &
                         ((g(M,i,"op_turn") == 1) | (g(M,i,"b_any") == 1)),
        "03 C 소형반등 (시총<0.5B)":
            lambda M, i: (g(M,i,"mdd_52w") < -50) & (g(M,i,"vol_x_20w") > 1.5) &
                         (g(M,i,"psr") < 1) & (g(M,i,"rs_13w") > 1.5) & (g(M,i,"marcap") < 5e8),
        "04 C 시총게이트 제거":
            lambda M, i: (g(M,i,"mdd_52w") < -50) & (g(M,i,"vol_x_20w") > 1.5) &
                         (g(M,i,"psr") < 1) & (g(M,i,"rs_13w") > 1.5),
        "05 52주 신고가":
            lambda M, i: (g(M,i,"hi_52w") == 1),
        "06 52주 신고가 + RS>1.5":
            lambda M, i: (g(M,i,"hi_52w") == 1) & (g(M,i,"rs_13w") > 1.5),
        "07 52주 신고가 + 이익폭증":
            lambda M, i: (g(M,i,"hi_52w") == 1) & (g(M,i,"b_any") == 1),
        "08 흑자전환만":
            lambda M, i: (g(M,i,"op_turn") == 1),
        "09 흑자전환 + RS>1.5":
            lambda M, i: (g(M,i,"op_turn") == 1) & (g(M,i,"rs_13w") > 1.5),
        "10 턴어라운드 (흑자전환 + 낙폭−30)":
            lambda M, i: (g(M,i,"op_turn") == 1) & (g(M,i,"mdd_52w") < -30),
        "11 이익폭증만":
            lambda M, i: (g(M,i,"b_any") == 1),
        "12 이익폭증 + 저PER<20 (고PER→저PER)":
            lambda M, i: (g(M,i,"b_any") == 1) & (g(M,i,"per") > 0) & (g(M,i,"per") < 20),
        "13 이익폭증 + 저PER + RS>1.5":
            lambda M, i: (g(M,i,"b_any") == 1) & (g(M,i,"per") > 0) &
                         (g(M,i,"per") < 20) & (g(M,i,"rs_13w") > 1.5),
        "14 RS>1.5 단독":
            lambda M, i: (g(M,i,"rs_13w") > 1.5),
        "15 낙폭−50 + 거래량1.5 + RS>1.5 (PSR무관)":
            lambda M, i: (g(M,i,"mdd_52w") < -50) & (g(M,i,"vol_x_20w") > 1.5) &
                         (g(M,i,"rs_13w") > 1.5),
        "16 저PSR<1 + RS>1.5":
            lambda M, i: (g(M,i,"psr") < 1) & (g(M,i,"rs_13w") > 1.5),
    }

    def mk(fn):
        def sig(Mx, i, ent):
            ok = fn(Mx, i) & (Mx["adv_20d"].iloc[i] >= LIQ)
            return ok[ok.fillna(False)].index
        return sig

    rows = []
    for lab, fn in R.items():
        B.signal = mk(fn)
        for n in [8, 12]:
            cfg = dict(trail=.20, maxpos=n, weight=1.0 / n, tiers=[1.0],
                       ptrig="hi52", entry={}, sort="rs_13w")
            r = B.run(P, M, cfg, end=END)
            w = sum(1 for _, a, b in SPL
                    if B.run(P, M, cfg, start=a, end=b)["CAGR"] > spy_cagr(pd.Timestamp(a), pd.Timestamp(b)))
            rows.append(dict(전략=lab, 종목=n, TSR=round(r["TSR"], 0), CAGR=round(r["CAGR"], 1),
                             MDD=round(r["MDD"], 1), 회복=round(r["회복"], 2), 거래=r["거래수"],
                             승률=round(r["승률"], 1), 노출=round(r["평균노출"], 1), WF=f"{w}/6"))
            print(f"  done {lab} n={n}", flush=True)
    T = pd.DataFrame(rows).sort_values("회복", ascending=False)
    print("\n" + "=" * 130)
    print("전략 전수 비교 — 청산 고점−20%(주봉) · 거래대금 $1M+ · 정렬 rs_13w")
    print("=" * 130)
    print(T.to_string(index=False))
    sc = spy_cagr(P.index[0], END); sm = (S.loc[:END] / S.loc[:END].cummax() - 1).min() * 100
    print(f"\n[SPY] CAGR {sc:.1f}% · MDD {sm:.1f}% · 회복 {sc/abs(sm):.2f}")
    T.to_csv(os.path.join(BASE, "results", "sweep_all.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
