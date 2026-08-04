# -*- coding: utf-8 -*-
"""
M4 워크포워드 검증
  각 분할에서: TRAIN 구간으로 청산규칙 8개를 돌려 최적을 고르고 → TEST 1년에 그대로 적용
  판정: 6분할 중 몇 번이나 TEST에서 SPY 회복배율을 넘겼나
  대조: 항상 trail-20을 썼다면?
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_sim as L

pd.set_option("display.width", 250, "display.max_columns", 30)

RULES = [("ma20", 0, 0), ("ma20", 0, .15), ("trail", .20, 0), ("trail", .25, 0),
         ("trail", .30, 0), ("both", .25, 0), ("both", .25, .15), ("none", 0, 0)]
SPLITS = [("2020-12-31", "2021-12-31"), ("2021-12-31", "2022-12-31"),
          ("2022-12-31", "2023-12-31"), ("2023-12-31", "2024-12-31"),
          ("2024-12-31", "2025-12-31"), ("2025-06-30", "2026-07-27")]
START = "2018-06-01"


def lab(c):
    return (f"{c['stop']}" + (f"-{c['trail']*100:.0f}" if c["trail"] else "")
            + (f"+손절{c['hard']*100:.0f}" if c["hard"] else ""))


def bench(S, a, b):
    s = S.loc[a:b]
    if len(s) < 5:
        return np.nan, np.nan, np.nan
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    cagr = ((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1) * 100
    mdd = (s / s.cummax() - 1).min() * 100
    return cagr, mdd, cagr / abs(mdd) if mdd else np.nan


def main():
    d = L.load()
    P, M = L.matrices(d)
    S = L.spy().reindex(P.index, method="nearest")
    cfgs = [dict(stop=s, trail=t, hard=h, pyramid=False, maxpos=8, weight=0.125)
            for s, t, h in RULES]

    rows = []
    for tr_end, te_end in SPLITS:
        # ── TRAIN: 최적 규칙 선택 ──
        best, best_rr = None, -9e9
        for c in cfgs:
            try:
                r = L.run(P, M, c, start=START, end=tr_end)
                rr = r["CAGR"] / abs(r["MDD"]) if r["MDD"] else -9e9
                if rr > best_rr:
                    best, best_rr = c, rr
            except Exception:
                pass
        if best is None:
            continue
        # ── TEST: 선택된 규칙 + 대조군 trail-20 ──
        out = {}
        for tag, c in [("선택", best), ("trail20", cfgs[2])]:
            try:
                r = L.run(P, M, c, start=tr_end, end=te_end)
                out[tag] = (r["CAGR"], r["MDD"],
                            r["CAGR"] / abs(r["MDD"]) if r["MDD"] else np.nan, r["거래수"])
            except Exception:
                out[tag] = (np.nan,) * 4
        bc, bm, br = bench(S, tr_end, te_end)
        rows.append(dict(
            분할=f"~{tr_end[:7]} → {te_end[:7]}",
            TRAIN선택=lab(best), TRAIN회복=best_rr,
            TEST_CAGR=out["선택"][0], TEST_MDD=out["선택"][1], TEST회복=out["선택"][2],
            SPY_CAGR=bc, SPY_MDD=bm, SPY회복=br,
            승=("O" if out["선택"][2] > br else "X"),
            t20회복=out["trail20"][2], t20승=("O" if out["trail20"][2] > br else "X")))

    R = pd.DataFrame(rows)
    print("=" * 128)
    print("M4 워크포워드 — TRAIN에서 고른 규칙을 TEST 1년에 그대로 적용")
    print("=" * 128)
    print(R.round(2).to_string(index=False))
    n = len(R)
    w1 = (R.승 == "O").sum(); w2 = (R.t20승 == "O").sum()
    print(f"\n  워크포워드 선택 규칙: SPY 회복배율 상회 {w1}/{n}")
    print(f"  항상 trail-20 고정:   SPY 회복배율 상회 {w2}/{n}")
    print(f"  선택된 규칙 분포: {R.TRAIN선택.value_counts().to_dict()}")
    print(f"\n  TEST 평균 CAGR  선택 {R.TEST_CAGR.mean():.1f}%  vs  SPY {R.SPY_CAGR.mean():.1f}%")
    print(f"  TEST 평균 MDD   선택 {R.TEST_MDD.mean():.1f}%  vs  SPY {R.SPY_MDD.mean():.1f}%")
    print(f"\n  판정: {'✅ 통과 (4/6 이상)' if w1 >= 4 else '❌ 미달 — M4 완료조건 미충족'}")


if __name__ == "__main__":
    main()
