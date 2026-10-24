# -*- coding: utf-8 -*-
"""RS 강도 × 이익가속/흑자전환 — '주도주 = 교집합' 후보 검증 (2026-10-23, 사전 등록)

질문(차니, 10-23): 52주 신고가 전에 더 빨리 사려면 '빵빵 오르는 종목 × 이익가속/흑자전환' 을 주도주 후보로?
사실 확인: 현행 ★(leaders_accel.gate_of)는 이미 'ACC == 1 × 주간 +10% 급등' 이다 — 주간 상승 × 이익가속 = ★.
그래서 여기서 새로 재는 것은 '1주 급등' 자리에 **RS 강도**(오닐식, 시장 전체 백분위)를 넣는 변형이다.

RS 점수 = 0.4·r13 + 0.2·r26 + 0.2·r39 + 0.2·r52 (주봉 수익률) → 유동성 통과 종목 안에서 그 주 백분위(0~99).
흑자전환(TA) = 분기 영업이익 > 0 이고 4분기 전(전년 동기) ≤ 0. period_end 기준(그 주에 알 수 있던 값).

변형(규칙 고정 · 주변값 탐색 없음):
  star      현행 ★ = ACC × 주간 +10%
  acc       ACC 만(급등 조건 없음)
  rs80_acc  RS ≥ 80 × ACC
  rs90_acc  RS ≥ 90 × ACC
  rs80_fund RS ≥ 80 × (ACC 또는 TA)          ← 제안된 '주도주 = 교집합' 정의
  rs80      RS ≥ 80 만(모멘텀만)
  ta        TA 만
공통: 유동성(거래대금 $5M·시총 $0.3B) · 20칸 · 고점 대비 -20% · 1주 지연 · 무작위 순서 10회 중앙값 · 편도 0.3% · 현금 FEDFUNDS.
합격: (1) CAGR 중앙값 > ★  (2) p10 > ★ 중앙값  (3) 전체 CAGR ≥ SPY  (4) 2014~2019 ≥ SPY  (5) 상폐충격 연 1% 에서도 (3) 유지
사용: FACTOR_VER=v13y python research/rs_accel_bt.py   (market.db 필요 → CI research-rs 워크플로)
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
A = S.A

SEEDS = 10
OUT = os.path.join(ROOT, "results", "rs_accel_bt.json")


def rs_rank(px, liq):
    r = {k: px / px.shift(k) - 1 for k in (13, 26, 39, 52)}
    score = 0.4 * r[13] + 0.2 * r[26] + 0.2 * r[39] + 0.2 * r[52]
    score = score.where(liq)
    return score.rank(axis=1, pct=True) * 99


def turnaround(d, px):
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "op_income"]].sort_values(["sym", "period_end"]))
    q["TA"] = ((q.op_income > 0) & (q.groupby("sym").op_income.shift(4) <= 0)).astype(int)
    x = d[["as_of", "sym", "period_end"]].merge(q[["sym", "period_end", "TA"]], on=["sym", "period_end"], how="left")
    return (x.pivot_table(index="as_of", columns="sym", values="TA")
             .reindex(index=px.index, columns=px.columns).fillna(0) == 1)


def med(px, g, cr, spy, **kw):
    R = []
    for s in range(SEEDS):
        h, _ = S.run(px, g, slots=20, stop=20, delay=1, cash_r=cr, order="random", seed=100 + s, **kw)
        st, _ = S.stats(h.v, spy)
        sub = h.v[(h.v.index >= "2014-01-01") & (h.v.index < "2020-01-01")]
        st["y14_19"] = S.stats(sub)[0]["CAGR"] if len(sub) > 52 else None
        R.append(st)
    D = pd.DataFrame(R)
    return dict(CAGR=float(D.CAGR.median()), p10=float(D.CAGR.quantile(.1)), MDD=float(D.MDD.median()),
                Sharpe=float(D.Sharpe.median()),
                y14_19=(float(D.y14_19.median()) if D.y14_19.notna().any() else None))


def main():
    t0 = time.time()
    px, star, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    acc = (M["ACC"] == 1).fillna(False) & liq
    rs = rs_rank(px, liq)
    ta = turnaround(d, px) & liq
    G = dict(star=star, acc=acc,
             rs80_acc=acc & (rs >= 80), rs90_acc=acc & (rs >= 90),
             rs80_fund=(acc | ta) & (rs >= 80), rs80=liq & (rs >= 80), ta=ta)
    # 2026-10-24 측정 정정: 이익가속은 4분기+1 이력, RS 는 52주 이력이 있어야 첫 신호가 난다 →
    #   v13y 첫 ~1년(2014-02~2015-02)은 어떤 변형도 살 수 없어 현금만 들고 SPY(+12%)를 그냥 놓쳤다(CAGR -1.1%p 왜곡).
    #   평가 구간을 '어느 변형이든 첫 신호가 가능한 주'부터로 통일한다(규칙·문턱은 그대로, 모든 변형·SPY 동일 적용).
    t0 = min(g.index[g.any(axis=1)][0] for g in G.values())
    px, spy, cr = px.loc[t0:], spy.loc[t0:], cr.loc[t0:]
    G = {k: g.loc[t0:] for k, g in G.items()}
    spy_w = spy.dropna()
    sub = spy_w[(spy_w.index >= "2014-01-01") & (spy_w.index < "2020-01-01")]
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER,
               period=[str(px.index[0].date()), str(px.index[-1].date())], eval_start_reason='첫 신호가 가능한 주부터(이익가속 5분기·RS 52주 이력 필요)', universe=int(px.shape[1]),
               SPY=dict(CAGR=S.stats(spy_w)[0]["CAGR"], MDD=S.stats(spy_w)[0]["MDD"],
                        y14_19=S.stats(sub)[0]["CAGR"] if len(sub) > 52 else None),
               variants={})
    for k, g in G.items():
        r = med(px, g, cr, spy)
        r["signals_per_week"] = round(float(g.sum(axis=1).mean()), 1)
        r["overlap_star"] = round(float((g & star).sum().sum()) / max(1.0, float(g.sum().sum())), 3)
        out["variants"][k] = r
        print(f"{k}: {r}", flush=True)
    st = out["variants"]["star"]
    for k in ("rs80_acc", "rs90_acc", "rs80_fund"):
        a = out["variants"][k]
        a["shock1"] = med(px, G[k], cr, spy, shock=0.01 / 52)["CAGR"]
        v = dict(beats_star=a["CAGR"] > st["CAGR"], p10_beats_star=a["p10"] > st["CAGR"],
                 beats_spy=a["CAGR"] >= out["SPY"]["CAGR"],
                 y14_19_beats_spy=(a["y14_19"] is not None and out["SPY"]["y14_19"] is not None
                                   and a["y14_19"] >= out["SPY"]["y14_19"]),
                 shock_beats_spy=a["shock1"] >= out["SPY"]["CAGR"])
        v["pass"] = all(v.values())
        a["verdict"] = {x: bool(y) for x, y in v.items()}
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    V = out["variants"]
    print(f"::notice title=RS×이익가속 ({A.VER})::SPY {out['SPY']['CAGR']}% · ★ {st['CAGR']}% · "
          + " · ".join(f"{k} {V[k]['CAGR']}%(p10 {V[k]['p10']}, MDD {V[k]['MDD']})"
                       + (f" {'합격' if V[k]['verdict']['pass'] else '불합격'}" if 'verdict' in V[k] else "")
                       for k in V if k != "star"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=RS 백테스트 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
