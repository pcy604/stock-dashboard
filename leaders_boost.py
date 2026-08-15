# -*- coding: utf-8 -*-
"""
이익 폭증(earnings boost) 팩터 + 펀더멘털 트리거 불타기
  아이디어(사용자): 흑자전환만 보면 이익 폭증 기업을 놓친다.
                   그리고 흑자전환 → 다음 분기 이익 폭증 때 불타기.
  → 피라미딩 트리거를 '가격(52주 신고가)'이 아니라 '이익 확인'으로 교체
"""
import os, sqlite3
import numpy as np
import pandas as pd
import leaders_sim2 as L2

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
pd.set_option("display.width", 250, "display.max_columns", 40)


def boost_flags():
    """분기 단위로 이익 폭증 판정 → (sym, as_of) 주간 플래그로 확장"""
    c = sqlite3.connect(DB)
    d = pd.read_sql("""SELECT as_of,sym,period_end,op_income,net_income,revenue,opm,npm
                       FROM factor_weekly WHERE factor_ver='v1' AND period_end IS NOT NULL""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    # 종목×분기 유일화 (그 분기가 처음 반영된 주)
    q = (d.sort_values("as_of").drop_duplicates(["sym", "period_end"])
           .sort_values(["sym", "period_end"]).reset_index(drop=True))
    g = q.groupby("sym")
    q["op_max8"] = g.op_income.transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q["ni_max8"] = g.net_income.transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q["op_prev"] = g.op_income.shift(1)
    q["opm_prev"] = g.opm.shift(1)

    # ── 이익 폭증 정의들 ──
    q["b_ophigh"] = ((q.op_income > q.op_max8) & (q.op_income > 0)).astype(int)   # 영업이익 8분기 신고점
    q["b_nihigh"] = ((q.net_income > q.ni_max8) & (q.net_income > 0)).astype(int)  # 순이익 신고점
    q["b_opjump"] = ((q.op_prev > 0) & (q.op_income / q.op_prev - 1 >= 0.5)).astype(int)  # 영업이익 QoQ +50%
    q["b_opmjump"] = ((q.opm - q.opm_prev) >= 3).astype(int)                       # OPM QoQ +3%p
    q["b_any"] = q[["b_ophigh", "b_nihigh", "b_opjump", "b_opmjump"]].max(axis=1)
    q["boost_wk"] = q.as_of                                                        # 이 플래그가 뜬 주

    cols = ["b_ophigh", "b_nihigh", "b_opjump", "b_opmjump", "b_any"]
    # 주간으로 되돌리기: 각 (sym, period_end)의 플래그를 그 분기가 유효한 모든 주에 부여
    m = d.merge(q[["sym", "period_end", "boost_wk"] + cols], on=["sym", "period_end"], how="left")
    m["boost_age"] = ((m.as_of - m.boost_wk).dt.days / 7).round()   # 폭증 공시 후 경과 주
    return m[["as_of", "sym", "boost_age"] + cols]


def build():
    d = L2.load()
    B = boost_flags()
    d = d.merge(B, on=["as_of", "sym"], how="left")
    for c in ["b_ophigh", "b_nihigh", "b_opjump", "b_opmjump", "b_any"]:
        d[c] = d[c].fillna(0)
    d["boost_age"] = d["boost_age"].fillna(999)
    return d


def matrices(d):
    P = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    cols = L2.FCOLS + ["b_ophigh", "b_nihigh", "b_opjump", "b_opmjump", "b_any", "boost_age"]
    return P, {c: d.pivot(index="as_of", columns="sym", values=c).reindex_like(P) for c in cols}


def signal(M, i, ent):
    ok = ((M["rs_13w"].iloc[i] > ent.get("rs", 1.5)) &
          (M["adv_20d"].iloc[i] >= 5e6) & (M["marcap"].iloc[i] >= 2e9))
    sub = None
    if ent.get("turn"):
        sub = (M["op_turn"].iloc[i] == 1)
    if ent.get("boost"):
        b = (M[ent["boost"]].iloc[i] == 1)
        sub = b if sub is None else (sub | b)      # 흑자전환 OR 이익폭증
    if sub is not None:
        ok &= sub
    if ent.get("psr_max") is not None:
        ok &= (M["psr"].iloc[i] < ent["psr_max"])
    return ok[ok.fillna(False)].index


def run(P, M, cfg, start="2018-06-01", end=None):
    idx = P.index
    i0 = int(np.searchsorted(idx, pd.Timestamp(start)))
    iN = len(idx) if end is None else min(len(idx), int(np.searchsorted(idx, pd.Timestamp(end))) + 1)
    FEE = L2.FEE
    cash, pos = 1.0, {}
    eq, dates, trades, expo, addlog = [], [], [], [], []
    maxpos, unit = cfg["maxpos"], cfg["weight"]
    ent, tiers = cfg.get("entry", {}), cfg.get("tiers", [1.0])
    ptrig = cfg.get("ptrig", "hi52")     # 'hi52' | 'boost'

    for i in range(i0, iN):
        px = P.iloc[i]
        val = sum(o["sh"] * px.get(s, np.nan) for s, o in pos.items()
                  if px.get(s, np.nan) == px.get(s, np.nan))
        V = cash + (val if val == val else 0)
        if V <= 0:
            break
        expo.append((val if val == val else 0) / V)

        for s in list(pos):
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]; o["peak"] = max(o["peak"], p)
            if p <= o["peak"] * (1 - cfg["trail"]):
                cash += o["sh"] * p * (1 - FEE)
                trades.append(dict(sym=s, ret=(p / o["avg"] - 1) * 100,
                                   wk=i - o["i0"], tier=o["tier"]))
                del pos[s]

        if len(tiers) > 1:
            for s, o in list(pos.items()):
                p = px.get(s, np.nan)
                if p != p or o["tier"] >= len(tiers):
                    continue
                if ptrig == "boost":
                    # 진입 이후에 새로 뜬 이익폭증 공시 (age<=1주)
                    go = (M["b_any"].iloc[i].get(s, 0) == 1
                          and M["boost_age"].iloc[i].get(s, 999) <= 1 and i > o["i0"])
                else:
                    go = (o["tier"] == 1 and M["hi_52w"].iloc[i].get(s, 0) == 1) or \
                         (o["tier"] >= 2 and p >= o["tpx"] * 1.25)
                if go:
                    amt = min(unit * V * tiers[o["tier"]], cash)
                    if amt > 1e-6:
                        sh = amt / p * (1 - FEE)
                        o["avg"] = (o["avg"] * o["sh"] + p * sh) / (o["sh"] + sh)
                        o["sh"] += sh; cash -= amt; o["tier"] += 1; o["tpx"] = p
                        addlog.append(dict(sym=s, tier=o["tier"], wk_after=i - o["i0"]))

        if len(pos) < maxpos:
            cand = [s for s in signal(M, i, ent)
                    if s not in pos and px.get(s, np.nan) == px.get(s, np.nan)]
            # 2026-08-14: 정렬 기준을 cfg로 뺐다. 기존 기본값은 dist_52w(신고가 근접)였는데,
            # 신고가 근접은 유니버스 검증에서 네 번 기각된 조건이다(리프트 0.4~0.7).
            # 기각한 조건이 슬롯 경쟁의 우선순위를 정하고 있었다.
            sk = cfg.get("sort", "dist_52w")
            dd = M[sk].iloc[i]
            cand.sort(key=lambda s: -(dd.get(s, -999) if dd.get(s, -999) == dd.get(s, -999) else -999))
            for s in cand[:maxpos - len(pos)]:
                amt = min(unit * V * tiers[0], cash)
                if amt < 1e-6:
                    break
                p = px[s]; sh = amt / p * (1 - FEE)
                pos[s] = dict(sh=sh, avg=p, peak=p, tier=1, tpx=p, i0=i)
                cash -= amt
        eq.append(V); dates.append(idx[i])

    E = pd.Series(eq, index=dates); T = pd.DataFrame(trades)
    y = (E.index[-1] - E.index[0]).days / 365.25
    cagr = ((E.iloc[-1] / E.iloc[0]) ** (1 / y) - 1) * 100
    mdd = (E / E.cummax() - 1).min() * 100
    return dict(equity=E, trades=T, CAGR=cagr, MDD=mdd,
                TSR=(E.iloc[-1] / E.iloc[0] - 1) * 100,
                회복=cagr / abs(mdd) if mdd else np.nan,
                평균노출=np.mean(expo) * 100, 거래수=len(T), 불타기=len(addlog),
                승률=(T.ret > 0).mean() * 100 if len(T) else np.nan,
                평균보유주=T.wk.mean() if len(T) else np.nan)


if __name__ == "__main__":
    d = build()
    print("이익 폭증 팩터 발생률 (전체 관측 대비)")
    for c, lab in [("b_ophigh", "영업이익 8분기 신고점"), ("b_nihigh", "순이익 8분기 신고점"),
                   ("b_opjump", "영업이익 QoQ +50%"), ("b_opmjump", "OPM QoQ +3%p"),
                   ("b_any", "위 중 하나라도")]:
        print(f"  {lab:22s} {d[c].mean()*100:5.2f}%")
    print(f"  {'흑자전환(비교)':22s} {(d.op_turn==1).mean()*100:5.2f}%")

    P, M = matrices(d)
    S = L2.spy().reindex(P.index, method="nearest")
    base = dict(trail=.20, maxpos=8, weight=0.125)
    rows = []
    for lab, ent, tiers, pt in [
        ("① 흑자전환만 (어제 최고)", dict(rs=1.5, turn=True), [1.0], "hi52"),
        ("② 이익폭증만 (b_any)", dict(rs=1.5, boost="b_any"), [1.0], "hi52"),
        ("③ 영업이익 신고점만", dict(rs=1.5, boost="b_ophigh"), [1.0], "hi52"),
        ("④ 흑자전환 OR 이익폭증", dict(rs=1.5, turn=True, boost="b_any"), [1.0], "hi52"),
        ("⑤ ④ + PSR<3", dict(rs=1.5, turn=True, boost="b_any", psr_max=3), [1.0], "hi52"),
        ("⑥ ④ + 불타기(가격트리거)", dict(rs=1.5, turn=True, boost="b_any"), [.6, .4], "hi52"),
        ("⑦ ④ + 불타기(이익트리거) ★", dict(rs=1.5, turn=True, boost="b_any"), [.6, .4], "boost"),
        ("⑧ ⑦ 3차까지", dict(rs=1.5, turn=True, boost="b_any"), [.5, .3, .2], "boost"),
        ("⑨ ① + 불타기(이익트리거)", dict(rs=1.5, turn=True), [.6, .4], "boost"),
    ]:
        r = run(P, M, {**base, "entry": ent, "tiers": tiers, "ptrig": pt})
        rows.append(dict(설정=lab, TSR=r["TSR"], CAGR=r["CAGR"], MDD=r["MDD"], 회복=r["회복"],
                         노출=r["평균노출"], 거래=r["거래수"], 불타기=r["불타기"],
                         승률=r["승률"], 보유주=r["평균보유주"]))
    R = pd.DataFrame(rows)
    print(f"\n{'='*126}\n이익 폭증 팩터 + 펀더멘털 트리거 불타기\n{'='*126}")
    print(R.round(1).to_string(index=False))
    y = (S.index[-1] - S.index[0]).days / 365.25
    sc = ((S.iloc[-1] / S.iloc[0]) ** (1 / y) - 1) * 100
    sm = (S / S.cummax() - 1).min() * 100
    print(f"\n[SPY] CAGR {sc:.1f}% · MDD {sm:.1f}% · 회복 {sc/abs(sm):.2f}")
