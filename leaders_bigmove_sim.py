# -*- coding: utf-8 -*-
"""
대시세 전략 백테스트 — 청산은 주봉 종가 −20% 도달 시 전량, 아니면 계속 보유

비교 대상
  A 현행 규칙⑥      RS13>1.5 & (흑자전환|이익폭증) & OPM>0 · 시총 $2B+
  B 소형 대시세      52주 낙폭 −50%↓ & 거래량 1.5배↑ & PSR<1 · 시총 $0.5B 미만
  C 소형 + 강세      위에 RS13>1.5 추가
  D 소형 단순        52주 낙폭 −50%↓ & 거래량 1.5배↑ (PSR 조건 없음)

슬롯 경쟁 정렬을 dist_52w(구 기본값, 기각된 조건)와 rs_13w 양쪽으로 돌려 영향도 함께 본다.
"""
import os, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))
SPL = [("2021", "2021-01-01", "2021-12-31"), ("2022", "2022-01-01", "2022-12-31"),
       ("2023", "2023-01-01", "2023-12-31"), ("2024", "2024-01-01", "2024-12-31"),
       ("2025", "2025-01-01", "2025-12-31"), ("2025H2~26", "2025-07-01", None)]


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    # FCOLS에 없는 컬럼은 DB에서 직접 붙인다
    import sqlite3
    c = sqlite3.connect(os.path.join(BASE, "data", "market.db"))
    ex = pd.read_sql("SELECT as_of,sym,mdd_52w,vol_x_20w FROM factor_weekly "
                     "WHERE factor_ver='v1'", c)
    c.close()
    ex["as_of"] = pd.to_datetime(ex.as_of)
    for col in ["mdd_52w", "vol_x_20w"]:
        M[col] = ex.pivot(index="as_of", columns="sym", values=col).reindex_like(P)
    S = L2.spy().reindex(P.index, method="nearest")

    def spy_cagr(a, b=None):
        s = S.loc[a:] if b is None else S.loc[a:b]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100

    RULES = {
        "A 현행⑥ RS1.5·(전환|폭증)·OPM>0 [$2B+]":
            lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                          ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                          (M["marcap"].iloc[i] >= 2e9) & (M["adv_20d"].iloc[i] >= 5e6)),
        "B 소형 낙폭−50·거래량1.5·PSR<1":
            lambda M, i: ((M["mdd_52w"].iloc[i] < -50) & (M["vol_x_20w"].iloc[i] > 1.5) &
                          (M["psr"].iloc[i] < 1) & (M["marcap"].iloc[i] < 5e8) &
                          (M["adv_20d"].iloc[i] >= 1e6)),
        "C B + RS13>1.5":
            lambda M, i: ((M["mdd_52w"].iloc[i] < -50) & (M["vol_x_20w"].iloc[i] > 1.5) &
                          (M["psr"].iloc[i] < 1) & (M["rs_13w"].iloc[i] > 1.5) &
                          (M["marcap"].iloc[i] < 5e8) & (M["adv_20d"].iloc[i] >= 1e6)),
        "D 소형 낙폭−50·거래량1.5 (PSR 무관)":
            lambda M, i: ((M["mdd_52w"].iloc[i] < -50) & (M["vol_x_20w"].iloc[i] > 1.5) &
                          (M["marcap"].iloc[i] < 5e8) & (M["adv_20d"].iloc[i] >= 1e6)),
    }

    def mk(fn):
        def sig(Mx, i, ent):
            ok = fn(Mx, i)
            return ok[ok.fillna(False)].index
        return sig

    rows = []
    for lab, fn in RULES.items():
        B.signal = mk(fn)
        for sk in ["dist_52w", "rs_13w"]:
            for n in [8, 12]:
                cfg = dict(trail=.20, maxpos=n, weight=1.0 / n, tiers=[1.0],
                           ptrig="hi52", entry={}, sort=sk)
                r = B.run(P, M, cfg, end="2026-08-03")   # 08-10 주차는 393종만 있어 자산계산 오염
                w = sum(1 for _, a, b in SPL
                        if B.run(P, M, cfg, start=a, end=(b or "2026-08-03"))["CAGR"] >
                        spy_cagr(pd.Timestamp(a), pd.Timestamp(b) if b else None))
                rows.append(dict(규칙=lab, 정렬=sk, 종목=n, TSR=round(r["TSR"], 0),
                                 CAGR=round(r["CAGR"], 1), MDD=round(r["MDD"], 1),
                                 회복=round(r["회복"], 2), 거래=r["거래수"],
                                 승률=round(r["승률"], 1), 보유주=round(r["평균보유주"], 1),
                                 노출=round(r["평균노출"], 1), WF=f"{w}/6"))
    R = pd.DataFrame(rows)
    print("=" * 126)
    print("대시세 전략 — 청산: 주봉 종가가 고점 대비 −20% 도달 시 전량 매도, 아니면 계속 보유")
    print("=" * 126)
    print(R.to_string(index=False))
    sc = spy_cagr(P.index[0]); sm = (S / S.cummax() - 1).min() * 100
    print(f"\n[SPY] TSR {(S.iloc[-1]/S.iloc[0]-1)*100:.0f}% · CAGR {sc:.1f}% · MDD {sm:.1f}% · 회복 {sc/abs(sm):.2f}")
    R.to_csv(os.path.join(BASE, "results", "bigmove_sim.csv"), index=False, encoding="utf-8-sig")


if __name__ == "__main__":
    main()
