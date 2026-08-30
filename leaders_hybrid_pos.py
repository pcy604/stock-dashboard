# -*- coding: utf-8 -*-
"""
하이브리드 × 종목수 — 월 1회 진입이면 몇 종목까지 담아야 하나

앞선 hybrid_sim은 12종목 고정이었다. 그런데 월말 주차에만 사면 진입 창이
1/4로 줄어드는 만큼, 한 번에 더 많이 담아야 노출이 유지될 수도 있다.
반대로 신호 순위가 낮은 종목까지 끌어오는 희석 효과가 더 클 수도 있다.

  주/주  매주 스크리닝 + 매주 손절 확인
  월/주  월말에만 스크리닝 + 손절은 매주 확인   ← 관심 대상

손절은 −20% 고정(사용자 확정 규칙). 종목수만 바꿔가며 어디서 꺾이는지 본다.
"""
import os, sys, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2
from leaders_hybrid_sim import run, SPL, END

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))
POSN = (8, 12, 16, 20, 25)
TRAIL = 0.20


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")
    mon = set(pd.Series(P.index, index=P.index)
              .groupby(P.index.to_period("M")).max().values)
    ent_w = np.ones(len(P), bool)
    ent_m = np.array([t in mon for t in P.index])
    print(f"주봉 {len(P)}주 · 월말 주차 {ent_m.sum()}개 · 손절 −{int(TRAIL*100)}% 고정",
          flush=True)

    R = {
        "A": lambda M, i: ((M["b_any"].iloc[i] == 1) & (M["per"].iloc[i] > 0) &
                           (M["per"].iloc[i] < 20) & (M["rs_13w"].iloc[i] > 1.5) &
                           (M["adv_20d"].iloc[i] >= 1e6)),
        "B": lambda M, i: ((((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                            (M["rs_13w"].iloc[i] > 1.7) & (M["adv_20d"].iloc[i] >= 1e6))),
        "R6": lambda M, i: ((M["rs_13w"].iloc[i] > 1.5) & (M["opm"].iloc[i] > 0) &
                            ((M["op_turn"].iloc[i] == 1) | (M["b_any"].iloc[i] == 1)) &
                            (M["marcap"].iloc[i] >= 2e9) & (M["adv_20d"].iloc[i] >= 5e6)),
    }

    def spy_cagr(a, b):
        s = S.loc[a:b]
        y = (s.index[-1] - s.index[0]).days / 365.25
        return ((s.iloc[-1] / s.iloc[0]) ** (1 / y) - 1) * 100

    rows = []
    for k, cond in R.items():
        for tag, ent in (("월/주", ent_m), ("주/주", ent_w)):
            for mp in POSN:
                r = run(P, M, cond, TRAIL, mp, ent)
                w = sum(1 for _, a, b in SPL
                        if run(P, M, cond, TRAIL, mp, ent, start=a, end=b)["CAGR"] >
                        spy_cagr(pd.Timestamp(a), pd.Timestamp(b)))
                rows.append(dict(규칙=k, 운용=tag, 종목수=mp,
                                 자산배수=round(r["mult"], 2), TSR=f"{r['TSR']:,.0f}%",
                                 CAGR=round(r["CAGR"], 1), MDD=round(r["MDD"], 1),
                                 회복=round(r["recov"], 2), 거래=r["n"],
                                 승률=round(r["win"], 1), 보유=round(r["hold"], 1),
                                 노출=round(r["expo"], 1), WF=f"{w}/6"))
                print(f"  {k:2s} {tag} {mp:2d}종 → {r['mult']:6.2f}배 "
                      f"MDD {r['MDD']:6.1f} 회복 {r['recov']:.2f} "
                      f"노출 {r['expo']:.1f} WF {w}/6", flush=True)
    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(BASE, "results", "hybrid_pos.csv"),
             index=False, encoding="utf-8-sig")
    print("\n" + "=" * 122)
    print(f"진입 주기 × 종목수 — 손절 −{int(TRAIL*100)}% 고정")
    print("=" * 122)
    print(T.to_string(index=False))
    sp = S.loc[:END]
    print(f"\n[SPY] 자산배수 {sp.iloc[-1]/sp.iloc[0]:.2f} · "
          f"MDD {(sp/sp.cummax()-1).min()*100:.1f}%")


if __name__ == "__main__":
    main()
