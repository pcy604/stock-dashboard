# -*- coding: utf-8 -*-
"""시대의 주도주 해부 — 미국 (2026-10-15, Claude 연구)

질문: 주도주가 되기 '전에' 보이는 지표는 무엇이고, 주도주가 '끝나기 전에' 보이는 지표는 무엇인가.
원칙: 시점 t 의 지표는 t 에 알 수 있던 값만 쓴다(재무=최초 공시·공시일 기준, factor_weekly 가 이미 보장).
      결과는 t+1 주 종가 진입 → t+53 주 종가(1주 지연, 52주 보유).

측정
  ① 순위상관(IC): 매주 단면에서 지표와 이후 52주 수익률의 스피어만 상관 → 주별 평균
  ② 꼬리 리프트: 지표 상위 20% 에서 '52주 뒤 2배 이상' 확률 ÷ 전체 확률
  ③ 매도 신호: 이미 1년에 2배 오른 종목(리더 상태)만 놓고, 이후 26주 수익률과의 IC
     + '이후 26주 −30% 이하' 확률 리프트

⚠️ 한계 — 수집 유니버스가 '현재 시총 $150M+ 생존 종목'이다. 상장폐지·소멸 종목이 없어
   위험한 지표(적자·급등)의 성과가 좋게 나오고, 붕괴 신호는 약하게 나온다.
사용: python research/leader_anatomy_us.py  → research/anatomy_us_*.csv
"""
import os
import sys

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "leaders_cache", "_fw_v13y.parquet")
OUT = os.path.join(ROOT, "research")

COLS = ["as_of", "sym", "close", "marcap", "adv_20d", "period_end", "revenue", "op_income",
        "gross_profit", "net_income", "rev_yoy", "gpm", "opm", "gpm_up2", "opm_up2", "npm_up2",
        "op_turn", "ret_1w", "ret_4w", "ret_13w", "rs_4w", "rs_13w", "rs_26w", "dist_52w",
        "low_52w_dist", "hi_52w", "close_gt_ma20", "ma10_gt_ma20", "ma20", "above_ma20_52w",
        "break_ma20_52w", "vol_x_20w", "mdd_52w", "earn_react_w0", "weeks_since_earn",
        "psr", "psr_pct5y"]


def load():
    d = pq.read_table(SRC, columns=COLS).to_pandas()
    d["as_of"] = pd.to_datetime(d.as_of)
    d = d.sort_values(["sym", "as_of"]).reset_index(drop=True)

    # ── 분기 가속 (leaders_accel.load 와 같은 정의) ──
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "revenue", "op_income", "rev_yoy", "gpm", "opm"]]
           .sort_values(["sym", "period_end"]).copy())
    q.loc[q.revenue.abs() < 1e7, "revenue"] = np.nan
    g = q.groupby("sym")
    q["oi_g"] = ((q.op_income - g.op_income.shift(4)) / q.revenue.abs()).replace([np.inf, -np.inf], np.nan)
    q["rv_g"] = q.rev_yoy
    g = q.groupby("sym")
    q["oi_a"] = q.oi_g - g.oi_g.shift(1)
    q["rv_a"] = q.rv_g - g.rv_g.shift(1)
    g = q.groupby("sym")
    q["acc"] = ((q.rv_a > 0) & (q.oi_a > 0) & (q.oi_a.abs() <= 10)).astype(float)
    q["acc2"] = ((q.acc == 1) & (g.acc.shift(1) == 1)).astype(float)          # Code 33형: 2분기 연속 가속
    q["decel"] = ((q.rv_a < 0) & (q.oi_a < 0)).astype(float)                   # 매출·이익 동시 감속
    q["dgpm"] = q.gpm - g.gpm.shift(1)
    q["dopm"] = q.opm - g.opm.shift(1)
    q["op_pos"] = (q.op_income > 0).astype(float)
    q.loc[q.rv_a.isna() | q.oi_a.isna(), ["acc", "acc2", "decel"]] = np.nan
    d = d.merge(q[["sym", "period_end", "oi_g", "rv_g", "oi_a", "rv_a", "acc", "acc2", "decel",
                   "dgpm", "dopm", "op_pos"]], on=["sym", "period_end"], how="left")
    d = d.sort_values(["sym", "as_of"]).reset_index(drop=True)

    # ── 가격 파생 (전부 t 까지의 값) ──
    gs = d.groupby("sym")
    d["ext20"] = d.close / d.ma20 - 1                       # 20주선 이격
    d["ret_52b"] = d.close / gs.close.shift(52) - 1         # 직전 52주 수익률 (리더 상태 판정)
    d["surge10"] = (d.ret_1w >= 10).astype(float)
    d.loc[d.ret_1w.isna(), "surge10"] = np.nan
    d["earn_r"] = np.where(d.weeks_since_earn <= 13, d.earn_react_w0, np.nan)   # 최근 분기 실적 반응
    d["lmc"] = np.log(d.marcap)
    # ── 결과 (1주 지연) ──
    c1 = gs.close.shift(-1)
    for h in (13, 26, 52):
        d[f"f{h}"] = gs.close.shift(-(1 + h)) / c1 - 1
    d["tradable"] = (d.marcap >= 3e8) & (d.adv_20d >= 5e6)
    d["b0"] = ((d.acc == 1) & (d.ret_1w >= 10) & d.tradable).astype(float)
    return d


FEATS = {  # 이름: (설명, 축)
    "rv_g": ("매출 YoY 성장률(수준)", "F"), "rv_a": ("매출 가속(Δ YoY)", "F"),
    "oi_g": ("영업이익 성장(매출 대비, 수준)", "F"), "oi_a": ("영업이익 가속", "F"),
    "acc": ("이익·매출 동시 가속", "F"), "acc2": ("동시 가속 2분기 연속(Code 33형)", "F"),
    "decel": ("이익·매출 동시 감속", "F"), "gpm": ("GPM 수준", "F"), "dgpm": ("ΔGPM", "F"),
    "opm": ("OPM 수준", "F"), "dopm": ("ΔOPM", "F"), "gpm_up2": ("GPM 2분기 연속 개선", "F"),
    "opm_up2": ("OPM 2분기 연속 개선", "F"), "npm_up2": ("순이익률 2분기 연속 개선", "F"),
    "op_turn": ("흑자전환", "F"), "op_pos": ("영업흑자", "F"), "psr": ("PSR", "V"),
    "lmc": ("시총(log)", "V"),
    "ret_1w": ("1주 수익률", "T"), "surge10": ("주봉 +10% 장대양봉", "T"), "ret_4w": ("4주 수익률", "T"),
    "ret_13w": ("13주 수익률", "T"), "rs_26w": ("26주 상대강도", "T"), "dist_52w": ("52주 고점 대비", "T"),
    "hi_52w": ("52주 신고가", "T"), "low_52w_dist": ("52주 저점 대비", "T"),
    "close_gt_ma20": ("20주선 위", "T"), "ma10_gt_ma20": ("10주선 > 20주선", "T"),
    "above_ma20_52w": ("1년 중 20주선 위 비율", "T"), "ext20": ("20주선 이격", "T"),
    "vol_x_20w": ("거래량 / 20주 평균", "T"), "mdd_52w": ("52주 최대낙폭", "T"),
    "earn_r": ("최근 실적 주 반응", "T"), "b0": ("현행 신호(B0)", "FT"),
}


def ic_table(d, mask, fwd, tail_col, tail_fn, min_n=30):
    """주별 스피어만 IC 평균 + 상위/하위 20% 꼬리 확률 리프트."""
    x = d[mask & d[fwd].notna()].copy()
    x["_tail"] = tail_fn(x[fwd]).astype(float)
    base = x["_tail"].mean()
    rows = []
    early = x.as_of < "2020-01-01"
    for f in FEATS:
        y = x[x[f].notna()]
        if len(y) < 1000:
            continue
        # 주별 순위상관
        r1 = y.groupby("as_of")[f].rank(pct=True)
        r2 = y.groupby("as_of")[fwd].rank(pct=True)
        tmp = pd.DataFrame({"a": r1, "b": r2, "w": y.as_of, "e": early[y.index]})
        cnt = tmp.groupby("w").a.transform("size")
        tmp = tmp[cnt >= min_n]
        ics = tmp.groupby("w").apply(lambda z: z.a.corr(z.b), include_groups=False).dropna()
        e_ics = ics[ics.index < "2020-01-01"]; l_ics = ics[ics.index >= "2020-01-01"]
        # 꼬리 리프트: 이진 지표는 1/0, 연속 지표는 주별 상·하위 20%
        if y[f].dropna().isin([0, 1]).all():
            hi = y[y[f] == 1]; lo = y[y[f] == 0]
        else:
            q = y.groupby("as_of")[f].rank(pct=True)
            hi = y[q >= 0.8]; lo = y[q <= 0.2]
        rows.append(dict(feat=f, desc=FEATS[f][0], axis=FEATS[f][1], n=len(y),
                         ic=ics.mean(), ic_1419=e_ics.mean(), ic_2026=l_ics.mean(),
                         pos_weeks=(ics > 0).mean(),
                         lift_hi=hi["_tail"].mean() / base, lift_lo=lo["_tail"].mean() / base,
                         n_hi=len(hi), ret_hi=hi[fwd].median(), ret_lo=lo[fwd].median()))
    return pd.DataFrame(rows), base


def main():
    d = load()
    t = d.tradable
    # ① 매수 측: 전체 종목, 52주 뒤 2배 이상
    buy, base_b = ic_table(d, t, "f52", "_tail", lambda s: s >= 1.0)
    buy = buy.sort_values("ic", ascending=False)
    buy.to_csv(os.path.join(OUT, "anatomy_us_buy.csv"), index=False)
    # ② 매도 측: 리더 상태(직전 52주 +100% 이상)에서 이후 26주, −30% 이하 확률
    lead = t & (d.ret_52b >= 1.0)
    sell, base_s = ic_table(d, lead, "f26", "_tail", lambda s: s <= -0.30, min_n=10)
    sell = sell.sort_values("ic")
    sell.to_csv(os.path.join(OUT, "anatomy_us_sell.csv"), index=False)

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
    fmt = lambda df: df.drop(columns=["desc"]).round(3).to_string(index=False)
    print(f"[매수] 거래 가능 종목-주 {int(t.sum()):,} · 52주 뒤 2배+ 기저확률 {base_b:.3%}")
    print(fmt(buy))
    print(f"\n[매도] 리더 상태 종목-주 {int(lead.sum()):,} · 26주 뒤 −30% 이하 기저확률 {base_s:.3%}")
    print(fmt(sell))
    d.to_parquet(os.path.join(ROOT, "data", "leaders_cache", "_anatomy_us_panel.parquet"))


if __name__ == "__main__":
    main()
