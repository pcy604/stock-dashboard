# -*- coding: utf-8 -*-
"""
후보 공급량 — 종목수 상한이 애초에 작동하기는 하는가

hybrid_size에서 full/capped 사이징의 MDD가 종목수와 무관하게 완전히 동일한
값으로 나왔다. 상한이 한 번도 안 닿았다는 뜻일 수 있다. 그렇다면 A·R6의
종목수 스윕은 처음부터 의미 없는 실험이었던 셈이다.

각 주차에 조건을 통과하는 종목이 몇 개나 되는지 직접 센다.
"""
import os, warnings
import numpy as np, pandas as pd
import leaders_boost as B

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250)
BASE = os.path.dirname(os.path.abspath(__file__))


def main():
    d = B.build(); d["as_of"] = pd.to_datetime(d.as_of)
    P, M = B.matrices(d)
    i0 = int(np.searchsorted(P.index, pd.Timestamp("2018-06-01")))

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

    rows, series = [], {}
    for k, cond in R.items():
        c = []
        for i in range(i0, len(P)):
            px = P.iloc[i]
            ok = cond(M, i)
            c.append(sum(1 for s in ok[ok.fillna(False)].index
                         if px.get(s, np.nan) == px.get(s, np.nan)))
        c = pd.Series(c, index=P.index[i0:])
        series[k] = c
        rows.append(dict(규칙=k, 평균=round(c.mean(), 1), 중앙=int(c.median()),
                         최소=int(c.min()), 최대=int(c.max()),
                         **{f"≥{n}종": f"{(c >= n).mean()*100:.0f}%"
                            for n in (8, 12, 16, 20, 25)},
                         무후보주차=f"{(c == 0).mean()*100:.0f}%"))
    T = pd.DataFrame(rows)
    print("주차별 조건 통과 종목 수 (2018-06 이후 " + str(len(P) - i0) + "주)")
    print("=" * 110)
    print(T.to_string(index=False))

    print("\n연도별 평균 후보 수")
    print("=" * 110)
    Y = pd.DataFrame({k: v.groupby(v.index.year).mean().round(1)
                      for k, v in series.items()})
    print(Y.to_string())
    pd.DataFrame(series).to_csv(os.path.join(BASE, "results", "supply.csv"),
                                encoding="utf-8-sig")


if __name__ == "__main__":
    main()
