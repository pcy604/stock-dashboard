# -*- coding: utf-8 -*-
"""
주도주 탈출 (5단계) — 청산 규칙 선택 가능성 검정

4단계에서 앞구간 1위(트레일-30% or 20주선2주)가 뒤구간에서 원금을 깎았고,
앞구간 최하위권이던 현행 -30% 가 뒤구간 1위였다. 그렇다면 질문은
"어느 청산이 좋은가"가 아니라 **"이 표본으로 청산을 고를 수 있는가"** 다.

  ① 앞구간 순위 vs 뒤구간 순위의 순위상관 (0 이면 고를 수 없다는 뜻)
  ② 상·하한선: 정점 매도(신) vs 무매도(방치) — 청산이 만들 수 있는 폭
  ③ 트레일 폭을 촘촘히 — 성과가 파라미터에 대해 매끈한지, 뾰족한지
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_ab as AB
import leaders_uturn2 as U2
import leaders_exit as X

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pd.set_option("display.width", 280)


def rankcorr(a, b):
    ra, rb = pd.Series(a).rank().values, pd.Series(b).rank().values
    return float(np.corrcoef(ra, rb)[0, 1])


def main():
    M, spy = U2.panel()
    spy_dd = spy / spy.rolling(52, min_periods=8).max() - 1
    key = sys.argv[1] if len(sys.argv) > 1 else "L"
    N, gate = AB.RULES[key]["slots"], AB.gate_of(M, key)

    grid = [(f"트레일 -{x:.0%}", X.ex_trail(x))
            for x in np.arange(0.15, 0.56, 0.05)]
    grid += [("20주선 이탈 2주", X.ex_ma(20, 2)), ("10주선 이탈 2주", X.ex_ma(10, 2)),
             ("트레일-30% or 20주선2주", X.ex_both(0.30, 20, 2)),
             ("시장조건부 20/40", X.ex_regime(0.20, 0.40)),
             ("포물선꼭지 -20%/+25%", X.ex_para(0.20, 0.25)),
             ("26주 시간청산", X.ex_time(26)), ("52주 시간청산", X.ex_time(52)),
             ("무매도(방치)", lambda v, st, c: False)]

    res = {}
    for seg, (a, b) in X.SEG.items():
        yrs = (pd.Timestamp(min(b, "2026-08-24")) - pd.Timestamp(a)).days / 365.25
        res[seg] = {}
        for nm, fn in grid:
            e, T = X.sim(M, gate, N, fn, a, b, spy_dd)
            res[seg][nm] = X.stat(e, T, yrs)

    R = pd.DataFrame({seg: {k: v["배수"] for k, v in d.items()} for seg, d in res.items()})
    R["앞순위"] = R["앞 2019~2021"].rank(ascending=False)
    R["뒤순위"] = R["뒤 2022~2026"].rank(ascending=False)
    R["MDD전체"] = [res["전체 2019~"][k]["MDD"] for k in R.index]
    R["CAGR전체"] = [res["전체 2019~"][k]["CAGR"] for k in R.index]
    R["포착률"] = [res["전체 2019~"][k]["포착률"] for k in R.index]
    R["n"] = [res["전체 2019~"][k]["n"] for k in R.index]
    print(f"═══ 규칙 {key} — 구간별 자산배수 ═══")
    print(R.round(2).to_string())

    c = rankcorr(R["앞 2019~2021"], R["뒤 2022~2026"])
    print(f"\n▶ 앞구간 순위 ↔ 뒤구간 순위 상관: {c:+.2f}  (n={len(R)} 규칙)")
    top = R["앞 2019~2021"].idxmax()
    print(f"  앞구간 1위 '{top}' → 뒤구간 {R.loc[top,'뒤 2022~2026']:.2f}배 "
          f"(뒤구간 순위 {R.loc[top,'뒤순위']:.0f}/{len(R)})")
    best2 = R["뒤 2022~2026"].idxmax()
    print(f"  뒤구간 1위 '{best2}' → 앞구간 순위 {R.loc[best2,'앞순위']:.0f}/{len(R)}")

    # ── 상한선: 정점 매도 ──
    px = M["close"]
    for seg, (a, b) in [("전체 2019~", X.SEG["전체 2019~"])]:
        e, T = X.sim(M, gate, N, X.ex_trail(AB.RULES[key]["trail"]), a, b, spy_dd)
        print(f"\n▶ 포착률 상한 진단 (현행 트레일, n={len(T)})")
        print(f"   트레이드가 도달했던 최대수익 중앙 {T.mx.median():+.0%} · "
              f"실현 중앙 {T.ret.median():+.0%}")
        print(f"   '정점에 팔았다면' 자산배수는 이 표본에서 계산 불가(경로 의존) — "
              f"대신 개별 포착률 중앙 {(T.ret/T.mx.replace(0,np.nan)).clip(-3,3).median():.0%}")
        print(f"   최대수익 +100% 이상 도달한 트레이드 {(T.mx>=1).sum()}건 중 "
              f"실현 +100% 이상은 {(T.ret>=1).sum()}건")


if __name__ == "__main__":
    main()
