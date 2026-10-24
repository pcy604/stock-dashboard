# -*- coding: utf-8 -*-
"""불타기 재검증 — '수익금 플레이어' 관점 (2026-10-24, 차니 지적)

지적: 그레이엄(GEICO)·버핏(아멕스·애플)·리버모어 모두 핵심 승자에 돈을 몰아 계좌 수익금을 만들었다.
측정 결함 발견: loss_cut_grid 의 불타기는 '남는 현금'으로만 샀는데 20칸이 늘 차 있어 평균 현금 5~15% → 대부분 실행 불가.
→ 재원 조달 방식을 바꿔 다시 잰다.

기준 전략 3: 현행 20칸(고점 -20%) · 낙폭 영역 20칸(진입가 -15% → 고점 -15% + 재돌파 재매수 + 냉각 4주) · 10칸(고점 -20%)
재원 3: cash(남는 현금만, 지난번과 같음) · reserve(칸 수를 75%로 줄여 처음부터 현금 25% 예비) ·
        sell_weakest(현금이 모자라면 RS 가장 낮은 보유 종목을 팔아 승자에 몰아줌)
불타기: 없음 + (진입가 대비 +20/30/50% 마다 & 그 주 신고가) × (첫 매수의 50%/100%) × 종목당 상한(계좌 15/25/40%) · 최대 3회 · 다음 주 체결
지표: CAGR·MDD·Calmar·샤프 + 한 종목 최대 비중(기간 중 최고·평균) + 상위 5종목이 순수익금에서 차지한 비중
공통: 교집합(RS80 × (이익가속 또는 흑자전환)) · RS 가중 · 동시 신호 RS 높은 순 · 1주 지연 · 편도 0.3% · 현금 FEDFUNDS
결과: results/pyramid_grid.json
"""
import os, sys, json, time, itertools
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
import rs_accel_bt as B
import spec_engine as E
A = S.A

OUT = os.path.join(ROOT, "results", "pyramid_grid.json")
BASE = dict(freq="W", fill="next_close", full="skip", rebalance=None, cost=0.003, cash="fedfunds",
            source={}, entry="inter", market=None, rank="rs_desc")
BASES = {
    "cur20": ("현행 20칸 · 고점 -20%", dict(slots=20, weight=0.05, exits=[("trail", 20)])),
    "dd20": ("낙폭 영역 20칸 · -15%→고점 -15% · 재돌파 재매수 · 냉각 4주",
             dict(slots=20, weight=0.05, exits=[("stop_entry", 15), ("trail", 15)],
                  reentry=dict(mode="breakout", window=26, max_n=3), cooldown=4)),
    "cur10": ("10칸 · 고점 -20%", dict(slots=10, weight=0.10, exits=[("trail", 20)])),
}
FUND = {"cash": "남는 현금만", "reserve": "현금 25% 예비(칸 75%)", "sell_weakest": "약한 종목 팔아 몰아주기"}
STEP, ADD, CAP = [20, 30, 50], [0.5, 1.0], [15, 25, 40]


def main():
    t0 = time.time()
    px, _, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    acc = (M["ACC"] == 1).fillna(False) & liq
    ta = B.turnaround(d, px) & liq
    rs = B.rs_rank(px, liq)
    try:
        t_ev = pd.Timestamp(json.load(open(B.OUT, encoding="utf-8"))["period"][0])
    except Exception:
        t_ev = px.index[60]
    sl = lambda z: z.loc[t_ev:]
    px_, spy_, cr_ = sl(px), sl(spy), sl(cr)
    sig = sl(((acc | ta) & (rs >= 80)).fillna(False))
    rs_ = sl(rs)
    spy_w = spy_.dropna()
    dates = [str(t.date()) for t in px_.index]
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER, period=[dates[0], dates[-1]], universe=int(px_.shape[1]),
               bases={k: v[0] for k, v in BASES.items()}, funds=FUND, dims=dict(step=STEP, add=ADD, cap=CAP),
               dates=dates, spy=dict(stats=S.stats(spy_w)[0], curve=[round(float(x), 2) for x in (spy_.ffill() / spy_w.iloc[0] * 100).values]),
               grid=[], curves={})
    combos = [(bk, fk, None) for bk in BASES for fk in FUND if fk != "sell_weakest"] + \
             [(bk, fk, (st_, ad, cp)) for bk, fk, st_, ad, cp in itertools.product(BASES, FUND, STEP, ADD, CAP)]
    for bk, fk, pyp in combos:
        b = dict(BASES[bk][1])
        if fk == "reserve":
            b["slots"] = int(round(b["slots"] * 0.75))
        py = None if pyp is None else dict(step=pyp[0], add=pyp[1], max_adds=3, cap=pyp[2],
                                           fund="sell_weakest" if fk == "sell_weakest" else "cash")
        sp = dict(BASE, name="py", pyramid=py, **b)
        L = []
        h = E.run(sp, px_, sig, rs_, None, cr_, seed=100, log=L)
        st = S.stats(h.v, spy_)[0]
        pnl = {}
        for t in L:
            pnl[t["sym"]] = pnl.get(t["sym"], 0.0) + (t["out"] - t["inv"])
        tot = sum(pnl.values())
        top5 = sum(sorted(pnl.values(), reverse=True)[:5])
        key = f"{bk}|{fk}|" + ("none" if pyp is None else f"{pyp[0]}_{pyp[1]}_{pyp[2]}")
        out["grid"].append(dict(key=key, base=bk, fund=fk, py="none" if pyp is None else "on",
                                step=None if pyp is None else pyp[0], add=None if pyp is None else pyp[1],
                                cap=None if pyp is None else pyp[2],
                                CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Sharpe=float(st["Sharpe"]),
                                Calmar=float(st["Calmar"]) if st.get("Calmar") else None, beat_yrs=st.get("beat_yrs"),
                                max_w=round(float(h.mx.max()) * 100, 1), avg_max_w=round(float(h.mx.mean()) * 100, 1),
                                top5=round(top5 / tot * 100, 1) if tot > 0 else None,
                                funding_sells=sum(1 for t in L if t["why"] == "불타기 재원"),
                                avg_cash=round(float(h.cash.mean()) * 100, 1), final=round(float(h.v.iloc[-1] / h.v.iloc[0] * 100), 1)))
        out["curves"][key] = [round(float(v), 1) for v in (h.v / h.v.iloc[0] * 100).values]
    G = pd.DataFrame(out["grid"])
    eff = {}
    for bk in BASES:
        for fk in FUND:
            g = G[(G.base == bk) & (G.fund == fk)]
            on = g[g.py == "on"]
            none = G[(G.base == bk) & (G.fund == ("cash" if fk == "sell_weakest" else fk)) & (G.py == "none")]
            if len(on) and len(none):
                n0 = none.iloc[0]
                eff[f"{bk}|{fk}"] = dict(none_CAGR=float(n0.CAGR), none_MDD=float(n0.MDD), none_top5=n0.top5,
                                         on_CAGR=float(on.CAGR.median()), on_MDD=float(on.MDD.median()),
                                         on_top5=float(on.top5.median()), on_maxw=float(on.max_w.median()),
                                         better_calmar=int((on.Calmar > n0.Calmar).sum()), better_cagr=int((on.CAGR > n0.CAGR).sum()),
                                         n=len(on))
    out["effects"] = eff
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print(f"::notice title=불타기 재검증 ({A.VER})::{len(G)}조합 · " + " · ".join(
        f"{k}: 없음 {v['none_CAGR']}%/{v['none_MDD']}% → 불타기 중앙 {v['on_CAGR']}%/{v['on_MDD']}% (Calmar 개선 {v['better_calmar']}/{v['n']})"
        for k, v in eff.items()) + f" · {out['secs']}초")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=불타기 재검증 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
