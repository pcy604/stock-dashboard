# -*- coding: utf-8 -*-
"""
시뮬 v2 — 사용자 지적 3건 반영
  ① 피라미딩 비교가 불공정했는지 검증: 실제 평균 투자비중(노출) 측정 + 노출 보정 비교
  ② 진입 시 목표비중 전액 매수가 맞는지 → 분할매수(N주 나눠) 옵션 추가
  ③ 밸류에이션·수익성 팩터(흑자전환·OPM QoQ·이익 개선)를 진입조건에 추가
"""
import os, sqlite3
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CACHE = os.path.join(BASE, "data", "leaders_cache")
pd.set_option("display.width", 250, "display.max_columns", 40)
FEE = 0.001
FCOLS = ["ma20", "rs_13w", "psr", "per", "dist_52w", "hi_52w", "marcap", "adv_20d",
         "op_turn", "opm", "opm_qoq", "npm_qoq", "op_pos_streak", "rev_yoy",
         # 2026-08-08 추가 — 영업레버리지 검증용.
         #   DOL       = 영업이익 증가율 ÷ 매출 증가율      (이미 일어난 레버리지)
         #   gpm - opm = 판관비 비중                        (앞으로 터질 여지)
         "gpm", "gpm_qoq", "rev_qoq"]


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql(f"SELECT as_of,sym,close,{','.join(FCOLS)} "
                    "FROM factor_weekly WHERE factor_ver='v1'", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    jump = px.pct_change().abs().gt(1.0).sum()
    return d[~d.sym.isin(set(jump[jump >= 3].index))]


def matrices(d):
    P = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    return P, {c: d.pivot(index="as_of", columns="sym", values=c).reindex_like(P) for c in FCOLS}


def spy():
    return pd.read_csv(os.path.join(CACHE, "px_SPY.csv"), index_col=0, parse_dates=True)["Close"]


def signal(M, i, ent):
    ok = ((M["rs_13w"].iloc[i] > ent.get("rs", 1.5)) &
          (M["adv_20d"].iloc[i] >= 5e6) & (M["marcap"].iloc[i] >= 2e9))
    if ent.get("psr_max") is not None:
        ok &= (M["psr"].iloc[i] < ent["psr_max"])
    if ent.get("turn"):
        ok &= (M["op_turn"].iloc[i] == 1)
    if ent.get("opm_qoq") is not None:
        ok &= (M["opm_qoq"].iloc[i] >= ent["opm_qoq"])
    if ent.get("npm_qoq") is not None:
        ok &= (M["npm_qoq"].iloc[i] >= ent["npm_qoq"])
    if ent.get("opm_min") is not None:
        ok &= (M["opm"].iloc[i] >= ent["opm_min"])
    return ok[ok.fillna(False)].index


def run(P, M, cfg, start="2018-06-01", end=None):
    idx = P.index
    i0 = int(np.searchsorted(idx, pd.Timestamp(start)))
    iN = len(idx) if end is None else min(len(idx), int(np.searchsorted(idx, pd.Timestamp(end))) + 1)
    cash, pos = 1.0, {}
    eq, dates, trades, expo = [], [], [], []
    maxpos, unit = cfg["maxpos"], cfg["weight"]
    ent = cfg.get("entry", {})
    tiers = cfg.get("tiers", [1.0])          # 차수별 비중 배분 (합=1)
    legs = cfg.get("legs", 1)                # 1차 진입을 몇 주에 나눠 살 것인가

    for i in range(i0, iN):
        px = P.iloc[i]
        val = sum(o["sh"] * px.get(s, np.nan) for s, o in pos.items()
                  if px.get(s, np.nan) == px.get(s, np.nan))
        V = cash + (val if val == val else 0)
        if V <= 0:
            break
        expo.append((val if val == val else 0) / V)

        # 청산
        for s in list(pos):
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]; o["peak"] = max(o["peak"], p)
            hit = None
            if p <= o["peak"] * (1 - cfg["trail"]):
                hit = "트레일"
            if hit:
                cash += o["sh"] * p * (1 - FEE)
                trades.append(dict(sym=s, ret=(p / o["avg"] - 1) * 100,
                                   wk=i - o["i0"], tier=o["tier"]))
                del pos[s]

        # 1차 분할매수 잔여분
        for s, o in list(pos.items()):
            p = px.get(s, np.nan)
            if p != p or o["legs_left"] <= 0:
                continue
            amt = min(unit * V * tiers[0] / legs, cash)
            if amt > 1e-6:
                sh = amt / p * (1 - FEE)
                o["avg"] = (o["avg"] * o["sh"] + p * sh) / (o["sh"] + sh)
                o["sh"] += sh; cash -= amt; o["legs_left"] -= 1

        # 피라미딩
        if len(tiers) > 1:
            for s, o in list(pos.items()):
                p = px.get(s, np.nan)
                if p != p or o["tier"] >= len(tiers) or o["legs_left"] > 0:
                    continue
                go = (o["tier"] == 1 and M["hi_52w"].iloc[i].get(s, 0) == 1) or \
                     (o["tier"] >= 2 and p >= o["tpx"] * 1.25)
                if go:
                    amt = min(unit * V * tiers[o["tier"]], cash)
                    if amt > 1e-6:
                        sh = amt / p * (1 - FEE)
                        o["avg"] = (o["avg"] * o["sh"] + p * sh) / (o["sh"] + sh)
                        o["sh"] += sh; cash -= amt; o["tier"] += 1; o["tpx"] = p

        # 신규 진입
        if len(pos) < maxpos:
            cand = [s for s in signal(M, i, ent)
                    if s not in pos and px.get(s, np.nan) == px.get(s, np.nan)]
            dd = M["dist_52w"].iloc[i]
            cand.sort(key=lambda s: -(dd.get(s, -999) if dd.get(s, -999) == dd.get(s, -999) else -999))
            for s in cand[:maxpos - len(pos)]:
                amt = min(unit * V * tiers[0] / legs, cash)
                if amt < 1e-6:
                    break
                p = px[s]; sh = amt / p * (1 - FEE)
                pos[s] = dict(sh=sh, avg=p, peak=p, tier=1, tpx=p, i0=i, legs_left=legs - 1)
                cash -= amt
        eq.append(V); dates.append(idx[i])

    E = pd.Series(eq, index=dates); T = pd.DataFrame(trades)
    y = (E.index[-1] - E.index[0]).days / 365.25
    cagr = ((E.iloc[-1] / E.iloc[0]) ** (1 / y) - 1) * 100
    mdd = (E / E.cummax() - 1).min() * 100
    return dict(equity=E, trades=T, TSR=(E.iloc[-1] / E.iloc[0] - 1) * 100,
                CAGR=cagr, MDD=mdd, 회복=cagr / abs(mdd) if mdd else np.nan,
                평균노출=np.mean(expo) * 100, 거래수=len(T),
                승률=(T.ret > 0).mean() * 100 if len(T) else np.nan,
                평균보유주=T.wk.mean() if len(T) else np.nan)


def show(rows, title):
    R = pd.DataFrame(rows)
    print(f"\n{'='*118}\n{title}\n{'='*118}")
    print(R.round(1).to_string(index=False))
    return R


if __name__ == "__main__":
    d = load(); P, M = matrices(d); S = spy().reindex(P.index, method="nearest")
    B = dict(trail=.20, maxpos=8, weight=0.125, entry=dict(rs=1.5, psr_max=3))

    # ① 피라미딩 노출 문제
    rows = []
    for lab, tiers, wt in [("피라미딩 없음 (1차 전액)", [1.0], 0.125),
                           ("피라미딩 50:30:20", [.5, .3, .2], 0.125),
                           ("피라미딩 50:30:20 · unit 2배", [.5, .3, .2], 0.25),
                           ("피라미딩 34:33:33", [.34, .33, .33], 0.125)]:
        r = run(P, M, {**B, "tiers": tiers, "weight": wt})
        rows.append(dict(설정=lab, TSR=r["TSR"], CAGR=r["CAGR"], MDD=r["MDD"],
                         회복=r["회복"], 평균노출=r["평균노출"], 거래수=r["거래수"]))
    show(rows, "① 피라미딩 비교 — 평균노출(실제 투자비중)을 같이 봐야 공정하다")

    # ② 분할매수
    rows = []
    for legs in (1, 2, 4):
        r = run(P, M, {**B, "tiers": [1.0], "legs": legs})
        rows.append(dict(설정=f"1차를 {legs}주에 나눠 매수", TSR=r["TSR"], CAGR=r["CAGR"],
                         MDD=r["MDD"], 회복=r["회복"], 평균노출=r["평균노출"]))
    show(rows, "② 진입 시 전액 매수 vs 분할매수")

    # ③ 밸류에이션·수익성 팩터 추가
    rows = []
    for lab, ent in [("RS>1.5 & PSR<3 (현행)", dict(rs=1.5, psr_max=3)),
                     ("+ 흑자전환", dict(rs=1.5, psr_max=3, turn=True)),
                     ("+ OPM QoQ ≥ 0", dict(rs=1.5, psr_max=3, opm_qoq=0)),
                     ("+ OPM QoQ ≥ 2", dict(rs=1.5, psr_max=3, opm_qoq=2)),
                     ("+ NPM QoQ ≥ 2", dict(rs=1.5, psr_max=3, npm_qoq=2)),
                     ("+ OPM > 0 (흑자)", dict(rs=1.5, psr_max=3, opm_min=0)),
                     ("+ 흑자전환 & OPM QoQ≥0", dict(rs=1.5, psr_max=3, turn=True, opm_qoq=0)),
                     ("PSR<3 빼고 OPM QoQ≥2만", dict(rs=1.5, opm_qoq=2)),
                     ("PSR<3 빼고 흑자전환만", dict(rs=1.5, turn=True))]:
        r = run(P, M, {**B, "tiers": [1.0], "entry": ent})
        rows.append(dict(진입조건=lab, TSR=r["TSR"], CAGR=r["CAGR"], MDD=r["MDD"],
                         회복=r["회복"], 거래수=r["거래수"], 승률=r["승률"],
                         평균보유주=r["평균보유주"]))
    R = show(rows, "③ 밸류에이션만이 아니라 수익성 팩터를 진입에 넣으면?")
    y = (S.index[-1] - S.index[0]).days / 365.25
    sc = ((S.iloc[-1] / S.iloc[0]) ** (1 / y) - 1) * 100
    sm = (S / S.cummax() - 1).min() * 100
    print(f"\n[SPY] CAGR {sc:.1f}% · MDD {sm:.1f}% · 회복 {sc/abs(sm):.2f}")
