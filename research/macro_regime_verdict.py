# -*- coding: utf-8 -*-
"""사전 등록 합격 기준으로 macro_regime_bt 결과를 판정한다 (2026-10-20)."""
import os, sys
import pandas as pd
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
df = pd.read_csv(os.path.join(BASE, "research", "macro_regime_bt_2026-10-20.csv"))
P = ["A 1988-2007", "B 2008-2019", "C 2020-2026"]
g = lambda lab, per="전체": df[(df.신호 == lab) & (df.구간 == per)].iloc[0]

def check(lab, base):
    s, b = g(lab), g(base)
    ok1 = (s.Calmar - b.Calmar >= 0.05) and (s.MDD >= b.MDD) if base.startswith("B1") else \
          (s.MDD - b.MDD >= 5) and (s.Calmar > b.Calmar)
    wins = sum(g(lab, p).Calmar >= g(base, p).Calmar for p in P)
    worst = min(g(lab, p).CAGR - g(base, p).CAGR for p in P)
    ok2 = wins >= 2 and worst >= -2
    return ok1, ok2, wins, round(worst, 2), round(s.Calmar - b.Calmar, 3), round(s.MDD - b.MDD, 1)

fam = {"C1": ["C1 신용 13주 +0.30", "C1 주변 +0.20", "C1 주변 +0.40", "C1 주변 8주", "C1 주변 26주"],
       "C2": ["C2 NFCI>0", "C2 주변 −0.2", "C2 주변 +0.2"],
       "C3": ["C3 실업수당 +15%", "C3 주변 +10%", "C3 주변 +20%"],
       "C4": ["C4 삼 0.5", "C4 주변 0.4", "C4 주변 0.6"],
       "C5": ["C5 10Y−3M 역전"], "C6": ["C6 우라가미 역국면"],
       "C7": ["C7 시계추 ≥80", "C7 주변 70", "C7 주변 90"], "C8": ["C8 강달러"], "C9": ["C9 합성"]}
rows = []
for f, names in fam.items():
    for mode, base in (("(b)", "B1 200일선"), ("(a)", "B0 매수보유")):
        res = [check(f"{mode} {n}", base) for n in names]
        main = res[0]
        nb = res[1:]
        nb_ok = (sum(r[0] and r[1] for r in nb) > len(nb) / 2) if nb else None
        passed = main[0] and main[1] and (nb_ok if nb_ok is not None else True)
        rows.append(dict(후보=f, 방식=mode, 기준=base, Calmar차=main[4], MDD차=main[5], 조건1=main[0],
                         구간승=main[2], 최악구간CAGR차=main[3], 조건2=main[1],
                         주변값=("-" if nb_ok is None else f"{sum(r[0] and r[1] for r in nb)}/{len(nb)}"),
                         판정="✅" if passed else "❌"))
out = pd.DataFrame(rows)
pd.set_option("display.width", 220)
print(out.to_string(index=False))
out.to_csv(os.path.join(BASE, "research", "macro_regime_verdict_2026-10-20.csv"), index=False, encoding="utf-8-sig")
print()
print(df[df.신호.isin(["B0 매수보유", "B1 200일선", "참고 40주선", "(b) C1 신용 13주 +0.30", "(b) C8 강달러", "(b) C5 10Y−3M 역전", "(a) C3 실업수당 +15%", "(a) C4 삼 0.5", "(a) C6 우라가미 역국면", "(a) C9 합성"])].to_string(index=False))
