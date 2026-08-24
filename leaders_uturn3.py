# -*- coding: utf-8 -*-
"""
주도주 탈출 타이밍 (3단계) — ① 낙폭 문턱 스윕 ② 특징별 반응곡선(U자 확인)

'판단의 순간'(진입 후 고점 대비 -X% 최초 이탈) 이후 무슨 일이 벌어지는가.
IC(선형 순위상관)로 재지 않는다 — 이 프로젝트는 팩터가 U자라는 걸 이미 겪었다.
구간별로 잘라 반응 곡선을 그린다.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_uturn2 as U2

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 260, "display.max_columns", 60)

FEATS = [
    ("wk_pk", "고점 이후 경과주(하락 속도)"),
    ("wk_held", "진입 후 경과주"),
    ("gain_ent", "진입가 대비 현재 수익"),
    ("pk_gain", "진입가 대비 고점 수익(익은 정도)"),
    ("c_ma10", "10주선 대비 위치"),
    ("c_ma20", "20주선 대비 위치"),
    ("rs13", "RS 13주"),
    ("rs26", "RS 26주"),
    ("dist52", "52주 신고가와의 거리"),
    ("vw", "거래량 전주비"),
    ("volx", "거래량 20주평균비"),
    ("psrp", "PSR 5년 백분위"),
    ("opm", "영업이익률"),
    ("opmq", "OPM 전분기비"),
    ("opstk", "영업흑자 연속분기"),
    ("revy", "매출 YoY"),
    ("react", "직전 실적 주가반응"),
    ("mcap", "시가총액"),
    ("spy_dd", "SPY 52주고점 대비(시장 레짐)"),
    ("spy_r4", "SPY 4주 수익률"),
]


def sweep():
    M, spy = U2.panel()
    print("── ① 낙폭 문턱 스윕: 그 문턱을 깬 순간 이후 ──")
    print(f"{'규칙':^4}{'문턱':>6}{'n':>7}{'52주중앙':>10}{'평균':>9}{'음수':>7}"
          f"{'고점회복':>9}{'이후최대낙폭':>13}{'26주중앙':>10}")
    store = {}
    for key in ("L", "S"):
        for tg in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40):
            E = U2.collect(M, spy, key, trig=tg)
            store[(key, tg)] = E
            e = E.dropna(subset=["fwd52"])
            if not len(e):
                continue
            print(f"{key:^4}{tg:>5.0%}{len(e):>7}{e.fwd52.median():>+10.1%}"
                  f"{e.fwd52.mean():>+9.1%}{(e.fwd52 < 0).mean():>7.0%}"
                  f"{e.rec52.mean():>9.0%}{e.min52.median():>+13.1%}"
                  f"{e.fwd26.median():>+10.1%}")
    pd.concat(store.values()).assign(
        trig=np.repeat([f"{k[0]}{k[1]:.2f}" for k in store],
                       [len(v) for v in store.values()])
    ).to_parquet(os.path.join(BASE, "data", "_uturn_sweep.parquet"))
    return store


def curves(E, label, q=5):
    print(f"\n── ② 반응 곡선 — {label} (n={len(E)}) ──")
    base_m, base_r = E.fwd52.median(), E.rec52.mean()
    print(f"   기저: 52주 중앙 {base_m:+.1%} · 고점회복 {base_r:.0%}")
    rows = []
    for c, nm in FEATS:
        s = E[c]
        if s.notna().sum() < 60:
            continue
        try:
            b = pd.qcut(s, q, duplicates="drop")
        except ValueError:
            continue
        g = E.groupby(b, observed=True).agg(n=("fwd52", "size"),
                                            med=("fwd52", "median"),
                                            rec=("rec52", "mean"))
        g = g[g.n >= 20]
        if len(g) < 3:
            continue
        spread = g.med.max() - g.med.min()
        # scipy 없음 → 순위 상관을 직접 (값의 순위 vs 구간 순서)
        rk = pd.Series(g.med.values).rank().values
        mono = abs(np.corrcoef(rk, np.arange(len(g)))[0, 1]) if len(g) > 2 else 0.0
        rows.append(dict(feat=c, name=nm, spread=spread, mono=mono,
                         lo=g.med.iloc[0], hi=g.med.iloc[-1],
                         worst=g.med.idxmin(), best=g.med.idxmax(),
                         cells="  ".join(f"{v:+.0%}" for v in g.med)))
    R = pd.DataFrame(rows).sort_values("spread", ascending=False)
    for r in R.itertuples():
        tag = "단조" if r.mono >= 0.9 else ("U/역U" if r.mono <= 0.5 else "혼합")
        print(f"  {r.name:<24s} 폭 {r.spread:5.0%} [{tag}]  {r.cells}")
    return R


def main():
    store = sweep()
    for key in ("L", "S"):
        E = store[(key, 0.20)].dropna(subset=["fwd52"])
        curves(E, f"규칙 {key} · 고점대비 -20% 이탈 시점")


if __name__ == "__main__":
    main()
