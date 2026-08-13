# -*- coding: utf-8 -*-
"""
점수제 선정 — 하드 필터를 가중 점수로 교체

배경: 흑자전환 = 1 같은 이진 필터는 '이미 흑자를 내며 성장 중인' 주도주를
통째로 배제한다. 그래서 조건을 통과/탈락이 아니라 가산점으로 바꾼다.
핵심 축은 '증가율의 증가'(가속) — 성장률 수준이 아니라 성장률이 오르고 있는가.

  scan : 가속 지표들의 리프트를 먼저 잰다 (가중치 근거를 만들기 위해)
  sim  : 측정된 리프트로 가중치를 잡아 점수 상위 N종목 매수 백테스트

승률52주 = 52주 뒤 종가가 플러스일 확률(고정 지평, 손절 없음).
"""
import os, sys, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 260, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT, MIN_N = 1.50, 3000


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql(
        "SELECT as_of,sym,close,period_end,revenue,gross_profit,op_income,net_income,"
        "rev_yoy,rev_qoq,gpm,gpm_qoq,opm,opm_qoq,npm,npm_qoq,op_turn,op_pos_streak,"
        "rs_13w,rs_26w,marcap,adv_20d,psr,dist_52w "
        "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)

    # ── 분기 단위에서 성장률과 '성장률의 변화'(가속)를 만든다 ──
    q = (d.dropna(subset=["period_end"]).sort_values("as_of")
           .drop_duplicates(["sym", "period_end"]).sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    out = q[["sym", "period_end"]].copy()
    for src, nm in [("revenue", "rev"), ("gross_profit", "gp"),
                    ("op_income", "opi"), ("net_income", "ni")]:
        p4 = g[src].shift(4)
        yoy = np.where(p4 > 0, (q[src] / p4 - 1) * 100, np.nan)
        out[f"{nm}_yoy2"] = yoy
        # 가속: 이번 분기 YoY − 직전 분기 YoY (증가율이 오르고 있는가)
        out[f"{nm}_acc"] = pd.Series(yoy, index=q.index).groupby(q.sym).diff()
    # 마진 가속: 마진 변화의 변화
    for src, nm in [("opm", "opm"), ("gpm", "gpm"), ("npm", "npm")]:
        out[f"{nm}_acc"] = g[src].diff().groupby(q.sym).diff()
    d = d.merge(out, on=["sym", "period_end"], how="left")

    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    d = d[~d.sym.isin(bad)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    d["yr"] = d.as_of.dt.year
    return d


def curve(d, c, br, bins=10):
    """구간별 반응 — 최고 구간만이 아니라 상·하위를 같이 본다."""
    x = d[[c, "leader", "fwd", "yr"]].replace([np.inf, -np.inf], np.nan).dropna()
    if len(x) < MIN_N:
        return None
    try:
        x["b"] = pd.qcut(x[c], bins, duplicates="drop")
    except Exception:
        return None
    g = x.groupby("b", observed=True).agg(
        n=("leader", "size"), rate=("leader", "mean"),
        med=("fwd", "median"), win=("fwd", lambda v: (v > 0).mean()))
    g = g[g.n >= MIN_N]
    if g.empty:
        return None
    g["lift"] = g.rate / br
    top, bot = g.iloc[-1], g.iloc[0]
    best = g.lift.idxmax()
    x20 = x[x.yr != 2020]; s20 = x20[x20.b == best]
    l20 = s20.leader.mean() / x20.leader.mean() if len(s20) >= MIN_N // 2 else np.nan
    return dict(팩터=c, 최상위리프트=round(top.lift, 2), 최상위수익=round(top.med * 100, 1),
                최하위리프트=round(bot.lift, 2), 최고구간=str(best)[:20],
                최고리프트=round(g.lift.max(), 2),
                최고_2020제외=round(l20, 2) if l20 == l20 else None,
                최고수익중앙=round(g.loc[best, "med"] * 100, 1),
                최고승률=round(g.loc[best, "win"] * 100, 1))


def cmd_scan():
    d = load()
    br = d.leader.mean()
    print(f"관측 {len(d):,} · 종목 {d.sym.nunique()} · 기준율 {br*100:.2f}%\n")

    print("=" * 118)
    print("① 가속 지표 — '증가율이 오르고 있는가'. 최상위 = 가속이 가장 큰 십분위")
    print("=" * 118)
    rows = [curve(d, c, br) for c in
            ["rev_acc", "gp_acc", "opi_acc", "ni_acc", "opm_acc", "gpm_acc", "npm_acc"]]
    print(pd.DataFrame([r for r in rows if r]).to_string(index=False)); print()

    print("=" * 118)
    print("② 비교군 — 성장률 '수준' (가속이 아니라)")
    print("=" * 118)
    rows = [curve(d, c, br) for c in ["rev_yoy2", "gp_yoy2", "opi_yoy2", "ni_yoy2"]]
    print(pd.DataFrame([r for r in rows if r]).to_string(index=False)); print()

    print("=" * 118)
    print("③ 흑자전환 상태별 — 가산점 크기를 정하기 위한 근거")
    print("=" * 118)
    x = d.dropna(subset=["op_pos_streak"]).copy()
    x["st"] = np.where(x.op_turn == 1, "갓 흑자전환",
              np.where(x.op_pos_streak <= 1, "흑자 0~1분기",
              np.where(x.op_pos_streak <= 3, "흑자 2~3분기",
              np.where(x.op_pos_streak <= 7, "흑자 4~7분기", "흑자 8분기+"))))
    g = x.groupby("st").agg(관측=("leader", "size"),
                            리프트=("leader", lambda v: v.mean() / br),
                            수익중앙=("fwd", lambda v: v.median() * 100),
                            승률52주=("fwd", lambda v: (v > 0).mean() * 100))
    print(g.round(2).sort_values("리프트", ascending=False).to_string()); print()

    print("=" * 118)
    print("④ 거래 가능 영역(RS13>1.5 · 시총$2B+ · 거래대금$5M+) 안에서 같은 측정")
    print("=" * 118)
    t = d[(d.rs_13w > 1.5) & (d.marcap >= 2e9) & (d.adv_20d >= 5e6)]
    brt = t.leader.mean()
    print(f"  거래가능 관측 {len(t):,} · 기준율 {brt*100:.2f}%")
    for c in ["rev_acc", "gp_acc", "opi_acc", "opm_acc"]:
        x = t[[c, "leader", "fwd"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(x) < 1000:
            print(f"  {c:10s} 표본부족 {len(x)}"); continue
        hi = x[x[c] > x[c].quantile(.7)]
        print(f"  {c:10s} 상위30% 관측 {len(hi):5,} · 리프트 {hi.leader.mean()/brt:5.2f} · "
              f"수익중앙 {hi.fwd.median()*100:6.1f}% · 승률 {(hi.fwd>0).mean()*100:4.1f}%")
    x = t.dropna(subset=["op_pos_streak"])
    for lab, m in [("갓 흑자전환", x.op_turn == 1),
                   ("흑자 2~3분기", x.op_pos_streak.between(2, 3)),
                   ("흑자 8분기+", x.op_pos_streak >= 8)]:
        s = x[m]
        if len(s) < 300:
            print(f"  {lab:12s} 표본부족 {len(s)}"); continue
        print(f"  {lab:12s} 관측 {len(s):5,} · 리프트 {s.leader.mean()/brt:5.2f} · "
              f"수익중앙 {s.fwd.median()*100:6.1f}% · 승률 {(s.fwd>0).mean()*100:4.1f}%")


if __name__ == "__main__":
    {"scan": cmd_scan}.get(sys.argv[1] if len(sys.argv) > 1 else "scan", cmd_scan)()
