# -*- coding: utf-8 -*-
"""포트폴리오 위험 관리 덧씌우기(오버레이) 비교 (2026-10-24, 차니 아이디어)

질문: 교집합 RS순은 빠질 때 지수보다 훨씬 많이 빠진다(MDD -37~-68%). 비중을 미리/빨리 줄이면 낙폭을 줄이면서 수익을 지키나?

방법: robust_rs.json 의 144개 조합 주별 자산 곡선(종목 선택은 그대로) 위에 '전체 노출 비중'만 바꾼다.
  주 t 종가까지 아는 정보로 비중 e_t 를 정하고, **한 주 뒤(t+1 종가)에 체결** → t+1→t+2 수익부터 적용(W+1주 축소).
  포트 수익 = e × 전략 수익 + (1-e) × 현금(FEDFUNDS) · 비중을 바꿀 때마다 |변화량| × 0.3% 비용.
오버레이
  REL k·x·e  : 최근 k주 전략 수익 − SPY 수익 < x 이면 비중 e  (보유 종목이 지수보다 약해지기 시작하면 축소)
  NOHI n·e   : SPY 가 52주 신고가를 n주 넘게 갱신 못 하면 비중 e  (지수 신고가 실패 → 선제 축소)
  MA40 e     : SPY < 40주선(≈200일선)이면 비중 e  (원칙 v1.3 의 확정 규칙)
  DD x·e     : 전략 자체가 고점 대비 x% 넘게 빠져 있으면 비중 e  (계좌 낙폭 브레이크)
  CORE w     : SPY w + 전략 (1-w), 매주 비중 고정  (코어+위성)
결과: results/risk_overlay.json · 판단은 144개 조합 전체의 중앙값·비율로만(개별 최고 조합은 보지 않는다)
"""
import os, json, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "results", "robust_rs.json")
OUT = os.path.join(ROOT, "results", "risk_overlay.json")
COST = 0.003


def stats(v):
    v = pd.Series(v).dropna()
    yrs = (v.index[-1] - v.index[0]).days / 365.25
    cagr = (v.iloc[-1] / v.iloc[0]) ** (1 / yrs) - 1
    mdd = (v / v.cummax() - 1).min()
    r = v.pct_change().dropna()
    return dict(CAGR=round(cagr * 100, 2), MDD=round(mdd * 100, 1),
                Calmar=round(cagr / -mdd, 3) if mdd < 0 else None, Sharpe=round(r.mean() / r.std() * np.sqrt(52), 3))


def apply(rs, rc, expo):
    """rs: 전략 주간 수익 · rc: 현금 주간 수익 · expo: 주 t 에 정한 비중 → t+2 수익부터(1주 지연 체결)"""
    e = expo.shift(2).fillna(1.0)
    turn = e.diff().abs().fillna(0)
    r = e * rs + (1 - e) * rc - turn * COST
    return (1 + r).cumprod() * 100, float(e.mean())


def main():
    o = json.load(open(SRC, encoding="utf-8"))
    idx = pd.DatetimeIndex(o["dates"])
    spy = pd.Series(o["spy"]["curve"], index=idx).ffill().bfill()
    rspy = spy.pct_change().fillna(0)
    m = pd.read_parquet(os.path.join(ROOT, "data", "macro_hist.parquet"))
    ff = m["FEDFUNDS"].reindex(idx.union(m.index)).ffill().reindex(idx).bfill()
    rc = (1 + ff / 100) ** (1 / 52) - 1
    hi = spy.rolling(52, min_periods=1).max()
    wk_since_hi = pd.Series(0, index=idx, dtype=float)
    c = 0
    for i, (p, h) in enumerate(zip(spy.values, hi.values)):
        c = 0 if p >= h * 0.999 else c + 1
        wk_since_hi.iloc[i] = c
    ma40 = spy.rolling(40, min_periods=30).mean()

    OV = [("none", "덧씌우기 없음", lambda v: pd.Series(1.0, index=idx))]
    for k, x, e in itertools.product((1, 2, 4, 8), (0.0, -0.03, -0.06), (0.5, 0.0)):
        OV.append((f"rel_{k}_{int(-x*100)}_{int(e*100)}", f"최근 {k}주 SPY보다 {abs(x)*100:.0f}%p 넘게 약하면 → 비중 {e*100:.0f}%",
                   lambda v, k=k, x=x, e=e: pd.Series(np.where((v.pct_change(k) - spy.pct_change(k)) < x, e, 1.0), index=idx)))
    for n, e in itertools.product((1, 2, 4, 8, 13), (0.5, 0.0)):
        OV.append((f"nohi_{n}_{int(e*100)}", f"SPY 신고가 {n}주 넘게 못 깨면 → 비중 {e*100:.0f}%",
                   lambda v, n=n, e=e: pd.Series(np.where(wk_since_hi > n, e, 1.0), index=idx)))
    for e in (0.5, 0.0):
        OV.append((f"ma40_{int(e*100)}", f"SPY 40주선 아래면 → 비중 {e*100:.0f}%",
                   lambda v, e=e: pd.Series(np.where(spy < ma40, e, 1.0), index=idx)))
    for x, e in itertools.product((10, 15, 20, 25), (0.5, 0.0)):
        OV.append((f"dd_{x}_{int(e*100)}", f"전략이 고점 대비 -{x}% 넘게 빠져 있으면 → 비중 {e*100:.0f}%",
                   lambda v, x=x, e=e: pd.Series(np.where(v / v.cummax() - 1 < -x / 100, e, 1.0), index=idx)))
    core = [(f"core_{int(w*100)}", f"SPY {w*100:.0f}% + 전략 {100-w*100:.0f}%", w) for w in (0.3, 0.5, 0.7)]

    spy_st = stats(spy)
    rows = []
    for key, cv in o["curves"].items():
        v = pd.Series(cv, index=idx)
        rs = v.pct_change().fillna(0)
        for ok, nm, fn in OV:
            ex = fn(v).astype(float)
            curve, avg_e = apply(rs, rc, ex)
            st = stats(curve)
            rows.append(dict(cfg=key, ov=ok, avg_e=round(avg_e, 3), **st))
        for ok, nm, w in core:
            r = w * rspy + (1 - w) * rs
            st = stats((1 + r).cumprod() * 100)
            rows.append(dict(cfg=key, ov=ok, avg_e=1 - w, **st))
    D = pd.DataFrame(rows)
    names = {k: n for k, n, _ in OV} | {k: n for k, n, _ in core}
    base = D[D.ov == "none"].set_index("cfg")
    summ = []
    for ok, g in D.groupby("ov", sort=False):
        g = g.set_index("cfg")
        summ.append(dict(ov=ok, name=names[ok], n=len(g),
                         CAGR=float(g.CAGR.median()), MDD=float(g.MDD.median()), Calmar=float(g.Calmar.median()),
                         Sharpe=float(g.Sharpe.median()), avg_e=float(g.avg_e.median()),
                         beat_spy=int((g.CAGR > spy_st["CAGR"]).sum()),
                         mdd_le_spy=int((g.MDD >= spy_st["MDD"]).sum()),
                         both=int(((g.CAGR > spy_st["CAGR"]) & (g.MDD >= spy_st["MDD"])).sum()),
                         d_cagr=float((g.CAGR - base.CAGR).median()), d_mdd=float((g.MDD - base.MDD).median()),
                         calmar_up=int((g.Calmar > base.Calmar).sum())))
    S = pd.DataFrame(summ).sort_values("Calmar", ascending=False)
    rep = {}
    for cfg in ("w|20|t20", "w|20|m26", "w|10|t25", "m121|20|rs70"):
        if cfg in base.index:
            rep[cfg] = D[D.cfg == cfg].set_index("ov")[["CAGR", "MDD", "Calmar", "avg_e"]].to_dict("index")
    out = dict(src=o["run"], period=o["period"], spy=spy_st, summary=S.to_dict("records"), rep=rep,
               spy_overlays={ok: stats(apply(rspy, rc, fn(spy).astype(float))[0]) for ok, _, fn in OV if not ok.startswith(("rel", "dd"))})
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    pd.set_option("display.width", 250)
    print("SPY", spy_st)
    print(S[["ov", "name", "CAGR", "MDD", "Calmar", "Sharpe", "avg_e", "beat_spy", "mdd_le_spy", "both", "d_cagr", "d_mdd", "calmar_up"]]
          .to_string(index=False))


if __name__ == "__main__":
    main()
