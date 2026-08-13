# -*- coding: utf-8 -*-
"""
팩터 스캔 2차 — 원데이터에서 파생 지표를 직접 계산해 추가

1차(leaders_factors.py)에서 빠졌던 것들을 raw에서 만들어 잰다.
  · 매출총이익 YoY / QoQ            (gross_profit 원값에서)
  · 영업이익·순이익 YoY / QoQ       (EPS 대체 — EDGAR에서 EPS 태그를 안 받아와 eps_yoy가 전부 비어 있다)
  · MACD(12·26·9, 주봉) 값과 기울기  (가격 대비 정규화 — 안 하면 고가주가 항상 커진다)
  · RSI(14, 주봉) 값과 기울기
  · op_pos_streak 구간 × 이익폭증 교차 (흑자 지속이 진짜 추세전환인가)

승률 정의: fwd52 = 52주 뒤 종가/현재 종가 − 1 이 양수인 비율.
           고정 지평 보유이며 손절·중간청산이 없다. 백테스트 승률과 다른 개념이다.
"""
import os, sqlite3, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
pd.set_option("display.width", 250, "display.max_columns", 40)
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CUT, MIN_N = 1.50, 3000


def _growth(d):
    """분기 원값 → YoY/QoQ. (sym, period_end) 유일화 후 계산해 주간으로 되돌린다."""
    q = (d.dropna(subset=["period_end"])
           .sort_values("as_of").drop_duplicates(["sym", "period_end"])
           .sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    out = q[["sym", "period_end"]].copy()
    for src, name in [("gross_profit", "gp"), ("op_income", "opi"), ("net_income", "ni")]:
        prev1, prev4 = g[src].shift(1), g[src].shift(4)
        # 부호가 바뀌는 적자 구간에서 증가율은 의미가 없다 → 직전이 양수일 때만 계산
        out[f"{name}_qoq"] = np.where(prev1 > 0, (q[src] / prev1 - 1) * 100, np.nan)
        out[f"{name}_yoy"] = np.where(prev4 > 0, (q[src] / prev4 - 1) * 100, np.nan)
    return d.merge(out, on=["sym", "period_end"], how="left")


def _tech(d):
    """주봉 종가로 MACD·RSI와 그 기울기. MACD는 가격으로 나눠 정규화한다."""
    d = d.sort_values(["sym", "as_of"])
    g = d.groupby("sym")["close"]
    e12 = g.transform(lambda s: s.ewm(span=12, adjust=False).mean())
    e26 = g.transform(lambda s: s.ewm(span=26, adjust=False).mean())
    macd = e12 - e26
    sig = macd.groupby(d.sym).transform(lambda s: s.ewm(span=9, adjust=False).mean())
    d["macd"] = macd / d.close * 100                       # 가격 대비 %
    d["macd_hist"] = (macd - sig) / d.close * 100
    d["macd_slope"] = d.groupby("sym")["macd"].diff()

    diff = g.diff()
    up = diff.clip(lower=0).groupby(d.sym).transform(lambda s: s.ewm(alpha=1/14, adjust=False).mean())
    dn = (-diff.clip(upper=0)).groupby(d.sym).transform(lambda s: s.ewm(alpha=1/14, adjust=False).mean())
    d["rsi"] = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    d["rsi_slope"] = d.groupby("sym")["rsi"].diff()
    return d


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql(
        "SELECT as_of,sym,close,period_end,revenue,gross_profit,op_income,net_income,"
        "op_pos_streak,op_turn,opm,opm_qoq,gpm,rs_13w,marcap,adv_20d,psr "
        "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    d = _growth(d)
    d = _tech(d)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    fwd = (px.shift(-52) / px - 1).stack().rename("fwd").reset_index()
    d = d.merge(fwd, on=["as_of", "sym"], how="left").dropna(subset=["fwd"])
    bad = set(d.groupby("sym").fwd.max().pipe(lambda s: s[s > 20]).index)
    d = d[~d.sym.isin(bad)].copy()
    d["leader"] = (d.fwd >= CUT).astype(int)
    d["yr"] = d.as_of.dt.year
    return d


def scan(d, cols, br, title):
    rows = []
    for c in cols:
        x = d[[c, "leader", "fwd", "yr"]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(x) < MIN_N:
            rows.append(dict(팩터=c, 구간="관측부족", 관측=len(x))); continue
        try:
            x["b"] = pd.qcut(x[c], 10, duplicates="drop")
        except Exception:
            continue
        g = x.groupby("b", observed=True).agg(
            n=("leader", "size"), rate=("leader", "mean"),
            med=("fwd", "median"), win=("fwd", lambda v: (v > 0).mean()))
        g = g[g.n >= MIN_N]
        if g.empty:
            continue
        g["lift"] = g.rate / br
        best = g.lift.idxmax(); b = g.loc[best]
        x20 = x[x.yr != 2020]; s20 = x20[x20.b == best]
        l20 = s20.leader.mean() / x20.leader.mean() if len(s20) >= MIN_N // 2 else np.nan
        sub = x[x.b == best]
        yc = sub[sub.leader == 1].yr.value_counts(normalize=True)
        rows.append(dict(팩터=c, 구간=str(best)[:24], 관측=int(b.n), 리프트=round(b.lift, 2),
                         리프트_2020제외=round(l20, 2) if l20 == l20 else None,
                         수익중앙=round(b.med * 100, 1), 승률52주=round(b.win * 100, 1),
                         연도집중=round(yc.iloc[0] * 100, 0) if len(yc) else None))
    print("=" * 108); print(title); print("=" * 108)
    print(pd.DataFrame(rows).sort_values("리프트", ascending=False, na_position="last")
          .to_string(index=False))
    print()


def main():
    d = load()
    br = d.leader.mean()
    print(f"관측 {len(d):,} · 종목 {d.sym.nunique()} · 주도주 기준율 {br*100:.2f}%")
    print("※ 승률52주 = 52주 뒤 종가가 플러스일 확률(고정 지평, 손절 없음). 백테스트 승률과 다름.\n")

    scan(d, ["gp_yoy", "gp_qoq", "opi_yoy", "opi_qoq", "ni_yoy", "ni_qoq"], br,
         "① 이익 증가율 — 원데이터에서 자동 계산 (EPS 대체)")
    scan(d, ["macd", "macd_hist", "macd_slope", "rsi", "rsi_slope"], br,
         "② MACD · RSI — 값과 기울기 (주봉)")

    # ③ 흑자 지속 가설
    print("=" * 108)
    print("③ 흑자 지속이 진짜 추세전환인가 — op_pos_streak 구간별")
    print("=" * 108)
    x = d.dropna(subset=["op_pos_streak"]).copy()
    x["st"] = pd.cut(x.op_pos_streak, [-1, 0, 1, 2, 3, 4, 999],
                     labels=["0(적자)", "1분기", "2분기", "3분기", "4분기", "5분기+"])
    g = x.groupby("st", observed=True).agg(
        관측=("leader", "size"), 리프트=("leader", lambda v: v.mean() / br),
        수익중앙=("fwd", lambda v: v.median() * 100), 승률52주=("fwd", lambda v: (v > 0).mean() * 100))
    print(g.round(2).to_string()); print()

    print("=" * 108)
    print("④ 흑자 지속 × 이익폭증 교차 — 규모의 경제 가설 (RS13>1.5 안에서)")
    print("=" * 108)
    x = d[(d.rs_13w > 1.5) & (d.adv_20d >= 5e6) & (d.marcap >= 2e9)].dropna(subset=["op_pos_streak"])
    boost = (x.opm_qoq >= 3) | (x.opi_qoq >= 50)
    for lab, m in [("지속 0~1분기 · 폭증X", (x.op_pos_streak <= 1) & ~boost),
                   ("지속 0~1분기 · 폭증O", (x.op_pos_streak <= 1) & boost),
                   ("지속 2분기+ · 폭증X", (x.op_pos_streak >= 2) & ~boost),
                   ("지속 2분기+ · 폭증O", (x.op_pos_streak >= 2) & boost)]:
        s = x[m]
        if len(s) < 500:
            print(f"  {lab:24s} 관측 {len(s):5,} — 표본 부족"); continue
        print(f"  {lab:24s} 관측 {len(s):5,} · 리프트 {s.leader.mean()/br:5.2f} · "
              f"수익중앙 {s.fwd.median()*100:6.1f}% · 승률52주 {(s.fwd>0).mean()*100:4.1f}%")


if __name__ == "__main__":
    main()
