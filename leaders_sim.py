# -*- coding: utf-8 -*-
"""
운용 시뮬레이션 — 손절·피라미딩·비중조절 포함
  KPI = TSR(총수익·CAGR) + MDD  (사용자 원래 KPI)
  진입: 길B (RS13>1.5 & PSR<3) + 유동성/시총
  피라미딩: 1차 → 52주 신고가 돌파 시 2차 → 2차 대비 +25% 시 3차 (50:30:20)
  청산 규칙을 여러 안으로 스윕
"""
import os, sqlite3, itertools
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
CACHE = os.path.join(BASE, "data", "leaders_cache")
pd.set_option("display.width", 250, "display.max_columns", 40)
FEE = 0.001          # 편도 0.1% (수수료+슬리피지)


def load():
    c = sqlite3.connect(DB)
    d = pd.read_sql("""SELECT as_of,sym,close,ma20,rs_13w,rs_26w,psr,dist_52w,hi_52w,
                              marcap,adv_20d,low_52w_dist,mdd_52w,op_turn
                       FROM factor_weekly WHERE factor_ver='v1'""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)
    # 왜곡 종목 제거
    px = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    jump = px.pct_change().abs().gt(1.0).sum()
    d = d[~d.sym.isin(set(jump[jump >= 3].index))]
    return d


def matrices(d):
    P = d.pivot(index="as_of", columns="sym", values="close").sort_index()
    M = {c: d.pivot(index="as_of", columns="sym", values=c).reindex_like(P)
         for c in ["ma20", "rs_13w", "psr", "dist_52w", "hi_52w", "marcap", "adv_20d"]}
    return P, M


def spy():
    s = pd.read_csv(os.path.join(CACHE, "px_SPY.csv"), index_col=0, parse_dates=True)["Close"]
    return s


def signal(M, i):
    """길B 진입 조건 — 그 주에 알 수 있는 값만"""
    ok = ((M["rs_13w"].iloc[i] > 1.5) & (M["psr"].iloc[i] < 3) &
          (M["adv_20d"].iloc[i] >= 5e6) & (M["marcap"].iloc[i] >= 2e9))
    return ok[ok.fillna(False)].index


def run(P, M, cfg, start="2018-06-01", end=None):
    idx = P.index
    i0 = int(np.searchsorted(idx, pd.Timestamp(start)))
    iN = len(idx) if end is None else min(len(idx), int(np.searchsorted(idx, pd.Timestamp(end))) + 1)
    V0 = 1.0
    cash = V0
    pos = {}                       # sym -> dict
    eq, dates, trades = [], [], []
    maxpos = cfg["maxpos"]
    w_tier = [0.5, 0.3, 0.2] if cfg["pyramid"] else [1.0, 0, 0]
    unit = cfg["weight"]           # 종목당 목표 총비중

    for i in range(i0, iN):
        px = P.iloc[i]
        # ── 평가 ──
        val = sum(p["sh"] * px.get(s, np.nan) for s, p in pos.items()
                  if px.get(s, np.nan) == px.get(s, np.nan))
        V = cash + (val if val == val else 0)
        if V <= 0:
            break

        # ── 청산 ──
        for s in list(pos):
            p = px.get(s, np.nan)
            if p != p:
                continue
            o = pos[s]
            o["peak"] = max(o["peak"], p)
            m20 = M["ma20"].iloc[i].get(s, np.nan)
            hit = None
            if cfg["stop"] == "ma20" and m20 == m20 and p < m20:
                hit = "MA20이탈"
            elif cfg["stop"] == "trail" and p <= o["peak"] * (1 - cfg["trail"]):
                hit = f"트레일-{cfg['trail']*100:.0f}%"
            elif cfg["stop"] == "both":
                if m20 == m20 and p < m20:
                    hit = "MA20이탈"
                elif p <= o["peak"] * (1 - cfg["trail"]):
                    hit = f"트레일-{cfg['trail']*100:.0f}%"
            if hit is None and cfg["hard"] and p <= o["avg"] * (1 - cfg["hard"]):
                hit = f"손절-{cfg['hard']*100:.0f}%"
            if hit:
                cash += o["sh"] * p * (1 - FEE)
                trades.append(dict(sym=s, ret=(p / o["avg"] - 1) * 100,
                                   wk=i - o["i0"], reason=hit, tier=o["tier"]))
                del pos[s]

        # ── 피라미딩 ──
        if cfg["pyramid"]:
            for s, o in list(pos.items()):
                p = px.get(s, np.nan)
                if p != p or o["tier"] >= 3:
                    continue
                go = False
                if o["tier"] == 1 and M["hi_52w"].iloc[i].get(s, 0) == 1:
                    go = True
                elif o["tier"] == 2 and p >= o["t2px"] * 1.25:
                    go = True
                if go:
                    amt = unit * V * w_tier[o["tier"]]
                    amt = min(amt, cash)
                    if amt > 1e-6:
                        sh = amt / p * (1 - FEE)
                        o["avg"] = (o["avg"] * o["sh"] + p * sh) / (o["sh"] + sh)
                        o["sh"] += sh; cash -= amt
                        o["tier"] += 1
                        if o["tier"] == 2:
                            o["t2px"] = p

        # ── 신규 진입 ──
        if len(pos) < maxpos:
            cand = [s for s in signal(M, i) if s not in pos and px.get(s, np.nan) == px.get(s, np.nan)]
            if cand:
                # 신고가에 가까운 순 (강세 우선)
                dd = M["dist_52w"].iloc[i]
                cand.sort(key=lambda s: -(dd.get(s, -999) if dd.get(s, -999) == dd.get(s, -999) else -999))
                for s in cand[:maxpos - len(pos)]:
                    amt = min(unit * V * w_tier[0], cash)
                    if amt < 1e-6:
                        break
                    p = px[s]
                    sh = amt / p * (1 - FEE)
                    pos[s] = dict(sh=sh, avg=p, peak=p, tier=1, t2px=p, i0=i)
                    cash -= amt
        eq.append(V); dates.append(idx[i])

    E = pd.Series(eq, index=dates)
    T = pd.DataFrame(trades)
    yrs = (E.index[-1] - E.index[0]).days / 365.25
    return dict(
        equity=E, trades=T,
        TSR=(E.iloc[-1] / E.iloc[0] - 1) * 100,
        CAGR=((E.iloc[-1] / E.iloc[0]) ** (1 / yrs) - 1) * 100,
        MDD=(E / E.cummax() - 1).min() * 100,
        거래수=len(T), 승률=(T.ret > 0).mean() * 100 if len(T) else np.nan,
        평균보유주=T.wk.mean() if len(T) else np.nan,
        평균수익=T.ret.mean() if len(T) else np.nan,
        손익비=(T[T.ret > 0].ret.mean() / abs(T[T.ret <= 0].ret.mean())
              if len(T) and (T.ret <= 0).any() and (T.ret > 0).any() else np.nan))


def main():
    d = load()
    P, M = matrices(d)
    S = spy().reindex(P.index, method="nearest")
    print(f"유니버스 {P.shape[1]}종 · {P.index[0].date()}~{P.index[-1].date()}")

    cfgs = []
    for stop, trail, hard in [("ma20", 0, 0), ("ma20", 0, .15),
                              ("trail", .20, 0), ("trail", .25, 0), ("trail", .30, 0),
                              ("both", .25, 0), ("both", .25, .15), ("none", 0, 0)]:
        for pyr in (True, False):
            cfgs.append(dict(stop=stop, trail=trail, hard=hard, pyramid=pyr,
                             maxpos=8, weight=0.125))
    rows = []
    for c in cfgs:
        r = run(P, M, c)
        lab = (f"{c['stop']}" + (f"-{c['trail']*100:.0f}" if c['trail'] else "")
               + (f" +손절{c['hard']*100:.0f}%" if c['hard'] else "")
               + (" +피라미딩" if c['pyramid'] else ""))
        rows.append(dict(규칙=lab, TSR=r["TSR"], CAGR=r["CAGR"], MDD=r["MDD"],
                         회복배율=r["CAGR"] / abs(r["MDD"]) if r["MDD"] else np.nan,
                         거래수=r["거래수"], 승률=r["승률"], 평균보유주=r["평균보유주"],
                         손익비=r["손익비"]))
    R = pd.DataFrame(rows).sort_values("회복배율", ascending=False)
    sp_tsr = (S.iloc[-1] / S.loc[R.index[0] if False else S.index[0]] - 1) * 100
    yrs = (S.index[-1] - S.index[0]).days / 365.25
    sp_cagr = ((S.iloc[-1] / S.iloc[0]) ** (1 / yrs) - 1) * 100
    sp_mdd = (S / S.cummax() - 1).min() * 100
    print("\n" + "=" * 118)
    print("운용 시뮬레이션 — 길B(RS13>1.5 & PSR<3) · 최대 8종목 · 종목당 12.5%")
    print("=" * 118)
    print(R.round(1).to_string(index=False))
    print(f"\n[벤치마크 SPY] TSR {(S.iloc[-1]/S.iloc[0]-1)*100:.0f}% · "
          f"CAGR {sp_cagr:.1f}% · MDD {sp_mdd:.1f}% · 회복배율 {sp_cagr/abs(sp_mdd):.2f}")
    print("  ※ 회복배율 = CAGR ÷ |MDD|. 높을수록 위험 대비 효율")


if __name__ == "__main__":
    main()
