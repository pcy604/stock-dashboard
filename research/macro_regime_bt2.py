# -*- coding: utf-8 -*-
"""욕심 조절 2차 — C5(10Y−3M)·C8(강달러) 주변값과 결합 (사전 등록 추가분, 2026-10-20)"""
import os, sys
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import macro_regime_bt as M

fred, px = M.load()
D, R = M.build(fred, px)
D = D.loc[M.START:M.END]; R = {k: v.loc[M.START:M.END] for k, v in R.items()}
B1 = D["above200"]
t = R["t10y3m"]
c5 = {"C5 기준 <0": (t < 0), "C5 주변 <−0.25": (t < -0.25), "C5 주변 <+0.25": (t < 0.25),
      "C5 주변 4주연속": (t < 0).astype(int).rolling(4).sum().eq(4)}
dx, d200 = R["dxy"], R["dxy200"]
c8 = {"C8 기준": (dx > d200) & (dx - dx.shift(13) > 0), "C8 주변 200일선만": (dx > d200),
      "C8 주변 8주": (dx > d200) & (dx - dx.shift(8) > 0), "C8 주변 26주": (dx > d200) & (dx - dx.shift(26) > 0)}
rows = M.evaluate(D, pd.Series(1.0, index=D.index), "B0 매수보유") + M.evaluate(D, B1, "B1 200일선")
for k, s in {**c5, **c8}.items():
    s = s.astype(float).reindex(D.index).fillna(0)
    rows += M.evaluate(D, B1 * (1 - 0.5 * s), f"(b) {k}")
both = c5["C5 기준 <0"].astype(float).fillna(0) + c8["C8 기준"].astype(float).fillna(0)
rows += M.evaluate(D, B1 * (0.5 ** both), "(b) C5+C8")
df = pd.DataFrame(rows)
df.to_csv(os.path.join(M.BASE, "research", "macro_regime_bt2_2026-10-20.csv"), index=False, encoding="utf-8-sig")
P = list(M.PERIODS)
g = lambda l, p="전체": df[(df.신호 == l) & (df.구간 == p)].iloc[0]
b = g("B1 200일선")
for l in df.신호.unique()[2:]:
    s = g(l)
    ok1 = s.Calmar - b.Calmar >= 0.05 and s.MDD >= b.MDD
    wins = sum(g(l, p).Calmar >= g("B1 200일선", p).Calmar for p in P)
    worst = min(g(l, p).CAGR - g("B1 200일선", p).CAGR for p in P)
    print(f"{l:<22} CAGR {s.CAGR:5.2f} MDD {s.MDD:6.1f} Calmar {s.Calmar:.3f} Δ{s.Calmar-b.Calmar:+.3f} ①{ok1} 구간승{wins} 최악{worst:+.2f} ②{wins>=2 and worst>=-2} 노출{s.노출} 변경{s.변경_연}")
print("지금 10Y-3M", round(float(t.iloc[-1]),2), "DXY", round(float(dx.iloc[-1]),1), "DXY200", round(float(d200.iloc[-1]),1))
