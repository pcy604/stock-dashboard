# -*- coding: utf-8 -*-
"""이익가속 신호 — 국면 분리 검증 (2026-10-26)

질문: 연도별 알파(2020 +47.8 · 2025 +30.7 · 2021~23 음수)를 가르는 국면을 **신호 달 직전에** 알 수 있었나?
방법: results/leaders_accel.json 의 월별 코호트(1년 뒤 알파, 신호 수 가중) × 직전 관측 국면 변수 11종.
      변수는 신호 달 1일 **이전** 값만 쓴다(look-ahead 없음).

결과 (2019-02~2025-10, 81개월, 신호 6,127건) — 표본 내(in-sample)
  1위 하이일드 스프레드 6개월 변화  순위상관 +0.76  (직전 6개월 신용 스트레스가 커졌던 달 → 알파 31.6 vs 0.5)
  2위 기준금리 6개월 변화           순위상관 −0.59  (금리 인하 중 → 22.0 vs 0.0)
  나머지(SPX 200일선·VIX·장단기·NFCI·NDX/SPX 등)는 |상관| ≤ 0.20
  결합 게이트(스프레드 확대 OR 금리 인하): 켜짐 33/81달(신호 43%) 알파 +30.4 vs 꺼짐 −0.3
  연도 안에서도 켜짐 ≥ 꺼짐 6/6년(양쪽 다 있는 해) — 단 2021·2022·2024 는 켜져도 0 근처

⚠️ 판정 보류 이유
  - 1년 보유 코호트가 겹친다 → 81개월이지만 독립 국면은 6~7개뿐
  - 변수 11개 중 상위 2개를 고른 것 → 다중검정. 이 숫자 자체가 과최적 가능성
  - **사전 등록**: 위 결합 게이트(임계값 0, 6개월)를 고정하고 2014-02~2018 v13y 구간(표본 외)에서
    같은 방향(켜짐 알파 > 꺼짐 알파, 차이 ≥ 10%p)이 나오면 채택. 파라미터 조정 금지.

실행: python research/regime_accel.py
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent


def _at(df, t):
    s = df[df.index < t]
    return s.iloc[-1] if len(s) else None


def build(acc_path=ROOT / "results" / "leaders_accel.json"):
    d = json.loads(Path(acc_path).read_text(encoding="utf-8"))
    bm = pd.DataFrame(d["by_month"])
    bm["t"] = pd.to_datetime(bm.ym + "-01")
    bm = bm.dropna(subset=["alpha"])
    px = pd.read_parquet(ROOT / "data/research/macro_long_px.parquet")[["SPX", "NDX", "VIX"]].ffill()
    mh = pd.read_parquet(ROOT / "data/macro_hist.parquet").ffill()
    rows = []
    for _, r in bm.iterrows():
        t = r["t"]
        p = px[px.index < t]
        spx = p.SPX
        m, m6 = _at(mh, t), _at(mh, t - pd.Timedelta(days=182))
        if m is None or m6 is None or len(p) < 260:
            continue
        rows.append(dict(
            ym=r.ym, t=t, n=r.n, alpha=r.alpha,
            spx_above_200d=float(spx.iloc[-1] > spx.iloc[-200:].mean()),
            spx_12m=spx.iloc[-1] / spx.iloc[-252] - 1,
            spx_dd=spx.iloc[-1] / spx.iloc[-252:].max() - 1,
            ndx_spx_6m=(p.NDX.iloc[-1] / p.NDX.iloc[-126]) / (spx.iloc[-1] / spx.iloc[-126]) - 1,
            vix=p.VIX.iloc[-1],
            hy=m["BAMLH0A0HYM2"], hy_6m=m["BAMLH0A0HYM2"] - m6["BAMLH0A0HYM2"],
            nfci=m["NFCI"], t10y3m=m["T10Y3M"], ff=m["FEDFUNDS"], ff_6m=m["FEDFUNDS"] - m6["FEDFUNDS"],
        ))
    return pd.DataFrame(rows)


def gate(X):
    """사전 등록 게이트 — 바꾸지 말 것."""
    return (X.hy_6m > 0) | (X.ff_6m < 0)


def report(X):
    wa = lambda g: (g.alpha * g.n).sum() / g.n.sum() if len(g) else np.nan
    g = gate(X)
    return {"months": len(X), "on_months": int(g.sum()), "on_signal_share": round(X[g].n.sum() / X.n.sum(), 3),
            "alpha_on": round(wa(X[g]), 1), "alpha_off": round(wa(X[~g]), 1)}


if __name__ == "__main__":
    X = build()
    print(report(X))
