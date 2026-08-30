# -*- coding: utf-8 -*-
"""
시작일 감사 — 2018년 예열 구간을 빼면 성적표가 어떻게 바뀌나

coverage 감사에서 2018년은 b_any의 8분기 rolling 충족률이 18%뿐이었다(2019년부터
89%+). 그 해엔 b_ophigh·b_nihigh가 구조적으로 못 뜨고 b_opjump·b_opmjump만
작동했으므로, 2018-06 시작 백테스트의 첫 7개월은 사실상 다른 규칙이 돌아간
구간이다. 게다가 A는 그 시기 후보가 연평균 0.5~0.7개라 거의 전액 현금이었다.

시작일만 2019-01-01로 옮겨 같은 구성을 다시 돌린다.
워크포워드 6분할은 전부 2021년 이후에서 시작하므로 시작일 변경의 영향을 받지 않는다.
"""
import os, warnings
import numpy as np, pandas as pd
import leaders_boost as B, leaders_sim2 as L2
from leaders_hybrid_size import run

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))
END = "2026-08-03"
STARTS = [("2018-06", "2018-06-01"), ("2019-01", "2019-01-01")]


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")
    mon = set(pd.Series(P.index, index=P.index)
              .groupby(P.index.to_period("M")).max().values)
    ent_w = np.ones(len(P), bool)
    ent_m = np.array([t in mon for t in P.index])

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

    rows = []
    for k, cond in R.items():
        for tag, ent in (("월/주", ent_m), ("주/주", ent_w)):
            for tr in (.15, .20):
                cur = {}
                for lab, st in STARTS:
                    r = run(P, M, cond, tr, 12, ent, sizing="fixed", start=st, end=END)
                    cur[lab] = r
                rows.append(dict(
                    규칙=k, 운용=tag, 손절=f"−{int(tr*100)}%",
                    배수_18=round(cur["2018-06"]["mult"], 2),
                    배수_19=round(cur["2019-01"]["mult"], 2),
                    CAGR_18=round(cur["2018-06"]["CAGR"], 1),
                    CAGR_19=round(cur["2019-01"]["CAGR"], 1),
                    MDD_18=round(cur["2018-06"]["MDD"], 1),
                    MDD_19=round(cur["2019-01"]["MDD"], 1),
                    회복_18=round(cur["2018-06"]["recov"], 2),
                    회복_19=round(cur["2019-01"]["recov"], 2),
                    노출_18=round(cur["2018-06"]["expo"], 1),
                    노출_19=round(cur["2019-01"]["expo"], 1),
                    거래_18=cur["2018-06"]["n"], 거래_19=cur["2019-01"]["n"]))
                print(f"  {k:2s} {tag} −{int(tr*100)}% → "
                      f"배수 {cur['2018-06']['mult']:5.2f}→{cur['2019-01']['mult']:5.2f} · "
                      f"CAGR {cur['2018-06']['CAGR']:5.1f}→{cur['2019-01']['CAGR']:5.1f} · "
                      f"회복 {cur['2018-06']['recov']:.2f}→{cur['2019-01']['recov']:.2f}",
                      flush=True)

    T = pd.DataFrame(rows)
    T.to_csv(os.path.join(BASE, "results", "start_audit.csv"),
             index=False, encoding="utf-8-sig")
    print("\n" + "=" * 140)
    print("시작일 2018-06 vs 2019-01 — 12종목 · fixed 사이징")
    print("=" * 140)
    print(T.to_string(index=False))

    for lab, st in STARTS:
        s = S.loc[st:END]
        y = (s.index[-1] - s.index[0]).days / 365.25
        print(f"[SPY {lab}~] 배수 {s.iloc[-1]/s.iloc[0]:.2f} · "
              f"CAGR {((s.iloc[-1]/s.iloc[0])**(1/y)-1)*100:.1f} · "
              f"MDD {(s/s.cummax()-1).min()*100:.1f}")


if __name__ == "__main__":
    main()
