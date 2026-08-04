# -*- coding: utf-8 -*-
"""
조건 심화 분석
  ① 단변량 반응 곡선 — 팩터를 구간으로 나눠 주도주율·중앙수익·상위10% 측정
  ② 2차원 상호작용 — RS × 신고가거리, 저점대비 × 신고가거리
  ③ 재무 조건이 상방을 깎는가 검증
"""
import os
import numpy as np
import pandas as pd
import leaders_profile as P

pd.set_option("display.width", 250, "display.max_columns", 40)
BASE_RATE = None


def curve(d, col, bins, labels=None, minn=300):
    """구간별 주도주율·수익률"""
    x = d[[col, "leader", "fwd"]].dropna()
    if len(x) < minn:
        return None
    x = x.copy()
    x["b"] = pd.cut(x[col], bins, labels=labels or None, include_lowest=True)
    g = x.groupby("b", observed=True).agg(
        관측=("leader", "size"),
        주도주율=("leader", lambda v: v.mean()*100),
        리프트=("leader", lambda v: v.mean()/BASE_RATE),
        수익중앙=("fwd", lambda v: v.median()*100),
        상위10p=("fwd", lambda v: v.quantile(.9)*100),
        승률=("fwd", lambda v: (v > 0).mean()*100))
    g = g[g.관측 >= minn]
    print(f"\n── {col} ──")
    print(g.round(2).to_string())
    return g


def cross(d, r, c, rb, cb, rl, cl, metric="leader"):
    x = d[[r, c, "leader", "fwd"]].dropna().copy()
    x["R"] = pd.cut(x[r], rb, labels=rl, include_lowest=True)
    x["C"] = pd.cut(x[c], cb, labels=cl, include_lowest=True)
    if metric == "leader":
        t = x.pivot_table(index="R", columns="C", values="leader",
                          aggfunc=lambda v: v.mean()*100, observed=True)
    else:
        t = x.pivot_table(index="R", columns="C", values="fwd",
                          aggfunc=lambda v: v.median()*100, observed=True)
    n = x.pivot_table(index="R", columns="C", values="leader", aggfunc="size", observed=True)
    t = t.where(n >= 150)
    lab = "주도주율 %" if metric == "leader" else "52주 수익 중앙 %"
    print(f"\n── {r} × {c}  ({lab}, 관측 150 미만은 공란) ──")
    print(t.round(1).to_string())
    print(f"   [관측수]\n{n.to_string()}")


def main():
    global BASE_RATE
    d, px = P.load()
    sp = P.spy_high()
    d = d.merge(sp, left_on="as_of", right_index=True, how="left")
    BASE_RATE = d.leader.mean()
    print(f"관측 {len(d):,} · 기준 주도주율 {BASE_RATE*100:.2f}%")

    print("\n" + "#" * 110)
    print("① 단변량 반응 곡선 — 어디가 최적이고 어디서 꺾이나")
    print("#" * 110)
    curve(d, "rs_13w", [0, .8, .9, 1.0, 1.1, 1.2, 1.5, 2.0, 99],
          ["<0.8", "0.8-0.9", "0.9-1.0", "1.0-1.1", "1.1-1.2", "1.2-1.5", "1.5-2.0", "2.0+"])
    curve(d, "rs_26w", [0, .8, .9, 1.0, 1.1, 1.2, 1.5, 2.0, 99],
          ["<0.8", "0.8-0.9", "0.9-1.0", "1.0-1.1", "1.1-1.2", "1.2-1.5", "1.5-2.0", "2.0+"])
    curve(d, "dist_52w", [-100, -70, -55, -40, -30, -20, -10, -5, 0.1],
          ["-100~-70", "-70~-55", "-55~-40", "-40~-30", "-30~-20", "-20~-10", "-10~-5", "-5~0"])
    curve(d, "low_52w_dist", [-1, 10, 25, 50, 75, 100, 150, 300, 9999],
          ["0-10", "10-25", "25-50", "50-75", "75-100", "100-150", "150-300", "300+"])
    curve(d, "mdd_52w", [-100, -70, -55, -40, -30, -20, -10, 0.1],
          ["-100~-70", "-70~-55", "-55~-40", "-40~-30", "-30~-20", "-20~-10", "-10~0"])
    curve(d, "opm", [-999, -50, -20, -5, 0, 5, 10, 20, 999],
          ["<-50", "-50~-20", "-20~-5", "-5~0", "0-5", "5-10", "10-20", "20+"])
    curve(d, "rev_yoy", [-999, -20, 0, 10, 20, 30, 50, 100, 9999],
          ["<-20", "-20~0", "0-10", "10-20", "20-30", "30-50", "50-100", "100+"])
    curve(d, "opm_qoq", [-999, -10, -3, 0, 3, 10, 999], ["<-10", "-10~-3", "-3~0", "0-3", "3-10", "10+"])
    curve(d, "psr", [0, 1, 2, 3, 5, 10, 20, 9999], ["0-1", "1-2", "2-3", "3-5", "5-10", "10-20", "20+"])
    curve(d, "marcap", [0, 3e9, 5e9, 10e9, 20e9, 50e9, 100e9, 9e15],
          ["2-3B", "3-5B", "5-10B", "10-20B", "20-50B", "50-100B", "100B+"])
    curve(d, "spy_dist", [-100, -20, -15, -10, -5, -2, 0.1],
          ["<-20", "-20~-15", "-15~-10", "-10~-5", "-5~-2", "-2~0"])
    curve(d, "above_ma20_52w", [-1, 20, 40, 60, 80, 101], ["0-20", "20-40", "40-60", "60-80", "80-100"])

    print("\n" + "#" * 110)
    print("② 2차원 상호작용")
    print("#" * 110)
    rb = [0, .9, 1.0, 1.1, 1.2, 1.5, 99]; rl = ["<0.9", "0.9-1.0", "1.0-1.1", "1.1-1.2", "1.2-1.5", "1.5+"]
    cb = [-100, -50, -35, -25, -15, -5, 0.1]; cl = ["-100~-50", "-50~-35", "-35~-25", "-25~-15", "-15~-5", "-5~0"]
    cross(d, "rs_13w", "dist_52w", rb, cb, rl, cl)
    lb = [-1, 25, 50, 100, 200, 9999]; ll = ["0-25", "25-50", "50-100", "100-200", "200+"]
    cross(d, "low_52w_dist", "dist_52w", lb, cb, ll, cl)
    ob = [-999, -20, 0, 5, 15, 999]; ol = ["<-20", "-20~0", "0-5", "5-15", "15+"]
    cross(d, "opm", "rev_yoy", ob, [-999, 0, 20, 50, 9999], ol, ["<0", "0-20", "20-50", "50+"])

    print("\n" + "#" * 110)
    print("③ 재무 조건이 상방을 깎는가 — 기본조합에 하나씩 추가")
    print("#" * 110)
    base = (d.rs_13w > 1.2) & (d.low_52w_dist >= 50) & (d.dist_52w < -20) & (d.marcap < 10e9)
    tests = [("기본조합 (RS13>1.2 & 저점+50% & 신고가-20%밖 & <10B)", base),
             ("+ 매출YoY > 0", base & (d.rev_yoy > 0)),
             ("+ 매출YoY > 20", base & (d.rev_yoy > 20)),
             ("+ 매출YoY > 30", base & (d.rev_yoy > 30)),
             ("+ 매출YoY > 50", base & (d.rev_yoy > 50)),
             ("+ OPM < 0 (적자)", base & (d.opm < 0)),
             ("+ OPM 0~10", base & (d.opm >= 0) & (d.opm < 10)),
             ("+ OPM > 10", base & (d.opm >= 10)),
             ("+ OPM QoQ > 0", base & (d.opm_qoq > 0)),
             ("+ OPM QoQ > 3", base & (d.opm_qoq > 3)),
             ("+ 흑자전환", base & (d.op_turn == 1)),
             ("+ OPM 2Q연속개선", base & (d.opm_up2 == 1)),
             ("+ PSR < 3", base & (d.psr < 3)),
             ("+ PSR > 5", base & (d.psr > 5)),
             ("+ 지수 26주내 신고가", base & (d.spy_hi_within26 == 1)),
             ("+ 지수 −10% 이상 조정중", base & (d.spy_dist < -10)),
             ]
    rows = []
    for lab, m in tests:
        s = d[m]
        if len(s) < 60:
            rows.append(dict(조건=lab, 관측=len(s), 주도주율=np.nan, 리프트=np.nan,
                             수익중앙=np.nan, 상위10p=np.nan, 승률=np.nan)); continue
        rows.append(dict(조건=lab, 관측=len(s), 주도주율=s.leader.mean()*100,
                         리프트=s.leader.mean()/BASE_RATE,
                         수익중앙=s.fwd.median()*100, 상위10p=s.fwd.quantile(.9)*100,
                         승률=(s.fwd > 0).mean()*100))
    print(pd.DataFrame(rows).round(2).to_string(index=False))


if __name__ == "__main__":
    main()
