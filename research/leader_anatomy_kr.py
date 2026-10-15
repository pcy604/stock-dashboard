# -*- coding: utf-8 -*-
"""시대의 주도주 해부 — 한국 (2026-10-15, Claude 연구)

미국판(leader_anatomy_us.py)과 같은 질문·측정을 한국 전 종목(상장폐지 포함)에 적용한다.

가격: FinanceData/marcap 일별(코스피 STK·코스닥 KSQ). **수정주가는 KRX 등락률(ChangesRatio)을 누적해 만든다.**
  ⚠️ 원 종가(Close)를 그대로 쓰면 액면분할·무상증자 날이 폭락으로 잡힌다
     (삼성전자 2018-05-04 원 종가 −98%, KRX 등락률 −2.08%). 2016~2026 에 이런 날이 1,998건이다.
재무: data/kr_fundamentals_q.parquet (DART). q=4 는 연간 합계라 Q4 = 연간 − (Q1+Q2+Q3).
  공시 시차: 분기 말 + 50일(Q4 는 90일) 뒤부터 사용 — 법정 기한(45일·90일)보다 보수적.
  ⚠️ 재무는 현재 상장 종목만 있다 → 재무 지표의 결과에는 생존편향이 남는다(가격 지표는 없음).
결과: t+1 주 종가 진입 → t+1+h 주. 상장폐지되면 마지막 거래가로 청산.

사용: KRDATA=<marcap-20XX.parquet 폴더> python research/leader_anatomy_kr.py
"""
import glob
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KRDATA = os.environ.get("KRDATA", "/home/claude/krdata")
OUT = os.path.join(ROOT, "research")


def prices():
    cols = ["Code", "Date", "Close", "ChangesRatio", "Amount", "Marcap", "MarketId", "Name", "Volume"]
    parts = []
    for f in sorted(glob.glob(os.path.join(KRDATA, "marcap-20*.parquet"))):
        x = pd.read_parquet(f, columns=cols)
        parts.append(x[x.MarketId.isin(["STK", "KSQ"])])
    d = pd.concat(parts)
    d["Date"] = pd.to_datetime(d.Date)
    d["Code"] = d.Code.astype(str).str.zfill(6)
    d = d[d.Close > 0].drop_duplicates(["Code", "Date"], keep="last")
    C = d.pivot(index="Date", columns="Code", values="Close")
    R = d.pivot(index="Date", columns="Code", values="ChangesRatio") / 100
    A = d.pivot(index="Date", columns="Code", values="Amount")
    M = d.pivot(index="Date", columns="Code", values="Marcap")
    V = d.pivot(index="Date", columns="Code", values="Volume")
    names = d.groupby("Code").Name.last()
    mkt = d.groupby("Code").MarketId.last()
    last = d.groupby("Code").Date.max()
    adj = (1 + R.fillna(0)).cumprod().where(C.notna())          # 수정주가 지수 (거래 없는 날 NaN)
    adv = A.rolling(20, min_periods=15).mean()
    W = lambda df, how: getattr(df.resample("W-FRI"), how)()
    w = dict(adj=W(adj, "last"), raw=W(C, "last"), mc=W(M, "last"), adv=W(adv, "last"), vol=W(V, "sum"))
    return w, names, mkt, last


def fundamentals():
    f = pd.read_parquet(os.path.join(ROOT, "data", "kr_fundamentals_q.parquet"))
    f["pref"] = (f.fs_div == "CFS").astype(int)
    f = f.sort_values("pref").drop_duplicates(["sym", "year", "q"], keep="last")
    p = f.pivot_table(index=["sym", "year"], columns="q", values=["revenue", "op_income"])
    rows = []
    for v in ("revenue", "op_income"):
        a = p[v].copy()
        q4 = a[4] - a[1] - a[2] - a[3]                            # 연간 → 4분기
        a[4] = q4
        rows.append(a.stack().rename(v))
    q = pd.concat(rows, axis=1).reset_index().rename(columns={"level_2": "q"})
    q.columns = ["sym", "year", "q", "revenue", "op_income"]
    q = q.sort_values(["sym", "year", "q"]).reset_index(drop=True)
    qend = {1: "-03-31", 2: "-06-30", 3: "-09-30", 4: "-12-31"}
    q["avail"] = pd.to_datetime(q.year.astype(str) + q.q.map(qend)) + pd.to_timedelta(
        np.where(q.q == 4, 90, 50), unit="D")
    q.loc[q.revenue.abs() < 1e9, "revenue"] = np.nan             # 분기매출 10억 미만은 비율이 발산
    g = q.groupby("sym")
    q["rv_g"] = (q.revenue / g.revenue.shift(4) - 1) * 100
    q.loc[g.revenue.shift(4) <= 0, "rv_g"] = np.nan
    q["oi_g"] = ((q.op_income - g.op_income.shift(4)) / q.revenue.abs()).replace([np.inf, -np.inf], np.nan)
    q["opm"] = q.op_income / q.revenue * 100
    g = q.groupby("sym")
    q["rv_a"] = q.rv_g - g.rv_g.shift(1)
    q["oi_a"] = q.oi_g - g.oi_g.shift(1)
    q["dopm"] = q.opm - g.opm.shift(1)
    g = q.groupby("sym")
    q["acc"] = ((q.rv_a > 0) & (q.oi_a > 0) & (q.oi_a.abs() <= 10)).astype(float)
    q["decel"] = ((q.rv_a < 0) & (q.oi_a < 0)).astype(float)
    q.loc[q.rv_a.isna() | q.oi_a.isna(), ["acc", "decel"]] = np.nan
    g = q.groupby("sym")
    q["acc2"] = ((q.acc == 1) & (g.acc.shift(1) == 1)).astype(float)
    q.loc[q.acc.isna(), "acc2"] = np.nan
    q["opm_up2"] = ((q.dopm > 0) & (g.dopm.shift(1) > 0)).astype(float)
    q.loc[q.dopm.isna(), "opm_up2"] = np.nan
    q["op_pos"] = (q.op_income > 0).astype(float)
    prev_neg = sum((g.op_income.shift(k) <= 0).astype(int) for k in range(1, 5))
    q["op_turn"] = ((q.op_income > 0) & (prev_neg > 0)).astype(float)
    return q


def panel():
    w, names, mkt, last = prices()
    adj = w["adj"]
    # 상장폐지 종목은 마지막 가격으로 청산 — 마지막 거래 이후로만 앞으로 채운다
    alive_end = pd.Series({c: last[c] for c in adj.columns})
    adj_ff = adj.ffill()
    future_mask = pd.DataFrame(adj_ff.index.values[:, None] > (alive_end.values + np.timedelta64(7, "D")),
                               index=adj.index, columns=adj.columns)
    delisted = alive_end < pd.Timestamp("2026-10-01")
    adj_exit = adj_ff.where(~future_mask | delisted.values[None, :])
    r1 = adj / adj.shift(1) - 1
    mc_prev = w["mc"].shift(1)
    mret = (r1 * mc_prev).sum(axis=1) / mc_prev.where(r1.notna()).sum(axis=1)
    midx = (1 + mret.fillna(0)).cumprod()
    ma10 = adj.rolling(10, min_periods=8).mean(); ma20 = adj.rolling(20, min_periods=16).mean()
    hi52 = adj.rolling(52, min_periods=40).max(); lo52 = adj.rolling(52, min_periods=40).min()
    feats = {
        "ret_1w": r1 * 100, "ret_4w": (adj / adj.shift(4) - 1) * 100, "ret_13w": (adj / adj.shift(13) - 1) * 100,
        "rs_26w": (adj / adj.shift(26)).div(midx / midx.shift(26), axis=0),
        "dist_52w": (adj / hi52 - 1) * 100, "low_52w_dist": (adj / lo52 - 1) * 100,
        "hi_52w": (adj >= hi52).astype(float).where(hi52.notna()),
        "close_gt_ma20": (adj > ma20).astype(float).where(ma20.notna()),
        "ma10_gt_ma20": (ma10 > ma20).astype(float).where(ma20.notna()),
        "ext20": adj / ma20 - 1,
        "vol_x_20w": w["vol"] / w["vol"].shift(1).rolling(20, min_periods=16).mean(),
        "mdd_52w": (adj / adj.rolling(52, min_periods=40).max() - 1).rolling(52, min_periods=40).min() * 100,
        "ret_52b": adj / adj.shift(52) - 1,
    }
    feats["above_ma20_52w"] = feats["close_gt_ma20"].rolling(52, min_periods=40).mean()
    feats["surge10"] = (feats["ret_1w"] >= 10).astype(float).where(feats["ret_1w"].notna())
    out = {}
    e1 = adj_exit.shift(-1)
    for h in (13, 26, 52):
        out[f"f{h}"] = adj_exit.shift(-(1 + h)) / e1 - 1
    long = []
    for k, v in {**feats, **out, "mc": w["mc"], "adv": w["adv"], "raw": w["raw"]}.items():
        long.append(v.stack(future_stack=True).rename(k))
    d = pd.concat(long, axis=1).reset_index()
    d.columns = ["as_of", "sym"] + list(d.columns[2:])
    d = d.dropna(subset=["raw"])
    d["lmc"] = np.log(d.mc)
    d["tradable"] = (d.adv >= 10e8) & (d.mc >= 1000e8) & (d.raw >= 1000)
    # 재무 (공시 시차 반영) — 주차별 최신 가용 분기
    q = fundamentals()
    q["avail"] = q.avail.astype("datetime64[ns]")
    d["as_of"] = d.as_of.astype("datetime64[ns]")
    q = q.sort_values("avail")
    d = d.sort_values("as_of")
    fc = ["rv_g", "rv_a", "oi_g", "oi_a", "acc", "acc2", "decel", "opm", "dopm", "opm_up2", "op_pos", "op_turn"]
    d = pd.merge_asof(d, q[["sym", "avail"] + fc], left_on="as_of", right_on="avail", by="sym",
                      direction="backward", tolerance=pd.Timedelta(days=200))
    d["b0"] = ((d.acc == 1) & (d.ret_1w >= 10) & d.tradable).astype(float)
    d["name"] = d.sym.map(names); d["market"] = d.sym.map(mkt)
    return d.sort_values(["sym", "as_of"]).reset_index(drop=True), mret


FEATS = {
    "rv_g": ("매출 YoY 성장률(수준)", "F"), "rv_a": ("매출 가속", "F"), "oi_g": ("영업이익 성장(수준)", "F"),
    "oi_a": ("영업이익 가속", "F"), "acc": ("이익·매출 동시 가속", "F"), "acc2": ("동시 가속 2분기 연속", "F"),
    "decel": ("이익·매출 동시 감속", "F"), "opm": ("OPM 수준", "F"), "dopm": ("ΔOPM", "F"),
    "opm_up2": ("OPM 2분기 연속 개선", "F"), "op_pos": ("영업흑자", "F"), "op_turn": ("흑자전환", "F"),
    "lmc": ("시총(log)", "V"), "ret_1w": ("1주 수익률", "T"), "surge10": ("주봉 +10%", "T"),
    "ret_4w": ("4주 수익률", "T"), "ret_13w": ("13주 수익률", "T"), "rs_26w": ("26주 상대강도", "T"),
    "dist_52w": ("52주 고점 대비", "T"), "hi_52w": ("52주 신고가", "T"), "low_52w_dist": ("52주 저점 대비", "T"),
    "close_gt_ma20": ("20주선 위", "T"), "ma10_gt_ma20": ("10주선 > 20주선", "T"),
    "above_ma20_52w": ("1년 중 20주선 위 비율", "T"), "ext20": ("20주선 이격", "T"),
    "vol_x_20w": ("거래량 / 20주 평균", "T"), "mdd_52w": ("52주 최대낙폭", "T"), "b0": ("이익가속+급등(B0)", "FT"),
}


def nw_t(s, L):
    s = s.dropna().values; n = len(s)
    if n < 20:
        return np.nan
    e = s - s.mean(); v = (e @ e) / n
    for l in range(1, L + 1):
        v += 2 * (1 - l / (L + 1)) * (e[l:] @ e[:-l]) / n
    return s.mean() / np.sqrt(v / n)


def ic_table(d, mask, fwd, tail_fn, L, min_n=30):
    x = d[mask & d[fwd].notna()].copy()
    x["_tail"] = tail_fn(x[fwd]).astype(float)
    base = x["_tail"].mean()
    rows = []
    for f in FEATS:
        y = x[x[f].notna()]
        if len(y) < 1000:
            continue
        r1 = y.groupby("as_of")[f].rank(pct=True); r2 = y.groupby("as_of")[fwd].rank(pct=True)
        tmp = pd.DataFrame({"a": r1, "b": r2, "w": y.as_of})
        tmp = tmp[tmp.groupby("w").a.transform("size") >= min_n]
        ics = tmp.groupby("w").apply(lambda z: z.a.corr(z.b), include_groups=False).dropna()
        if y[f].dropna().isin([0, 1]).all():
            hi = y[y[f] == 1]; lo = y[y[f] == 0]
        else:
            qq = y.groupby("as_of")[f].rank(pct=True); hi = y[qq >= 0.8]; lo = y[qq <= 0.2]
        rows.append(dict(feat=f, desc=FEATS[f][0], axis=FEATS[f][1], n=len(y), ic=ics.mean(), t=nw_t(ics, L),
                         ic_1619=ics[ics.index < "2020-01-01"].mean(), ic_2026=ics[ics.index >= "2020-01-01"].mean(),
                         lift_hi=hi._tail.mean() / base, lift_lo=lo._tail.mean() / base,
                         med_hi=hi[fwd].median(), med_lo=lo[fwd].median()))
    return pd.DataFrame(rows), base


def main():
    d, mret = panel()
    d.to_parquet(os.path.join(ROOT, "data", "leaders_cache", "_anatomy_kr_panel.parquet"))
    t = d.tradable & (d.as_of >= "2017-01-01")
    buy, bb = ic_table(d, t, "f52", lambda s: s >= 1.0, 52)
    lead = t & (d.ret_52b >= 1.0)
    sell, bs = ic_table(d, lead, "f26", lambda s: s <= -0.30, 26, min_n=10)
    buy.sort_values("ic", ascending=False).to_csv(os.path.join(OUT, "anatomy_kr_buy.csv"), index=False)
    sell.sort_values("ic").to_csv(os.path.join(OUT, "anatomy_kr_sell.csv"), index=False)
    pd.set_option("display.width", 250)
    print(f"[KR 매수] 종목-주 {int(t.sum()):,} · 2배+ 기저 {bb:.3%}")
    print(buy.sort_values("ic", ascending=False).drop(columns="desc").round(3).to_string(index=False))
    print(f"\n[KR 매도] 리더 상태 {int(lead.sum()):,} · 26주 −30% 기저 {bs:.3%}")
    print(sell.sort_values("ic").drop(columns="desc").round(3).to_string(index=False))


if __name__ == "__main__":
    main()
