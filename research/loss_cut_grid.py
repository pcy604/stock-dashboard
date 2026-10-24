# -*- coding: utf-8 -*-
"""손절·익절 올려 잡기(래칫) × 재매수 × 냉각 기간 × 불타기 격자 (2026-10-24, 차니 설계)

차니 설계(10-24):
  ① 처음엔 진입가 -x% 손절. 수익이 커지면 손절선을 고점 대비 -y% 로 '자연스럽게' 끌어올린다
     → 손절선 = max(진입가 × (1-x), 보유 중 최고가 × (1-y))   (예: 10,000 매수·-10%·-20% → 20,000 가면 16,000 에서 매도)
  ② 판 뒤 다시 오르면 재매수: 청산가 재돌파(16,000 위) 또는 청산 후 최저가 대비 +20~30% 반등(추세 전환)
  ③ 위험을 감지하고 판 돈은 바로 다른 종목에 쓰지 않고 k주 대기(같은 종목 재매수는 허용)
  ④ 불타기: 진입가 대비 +step% 마다(그 주 신고가일 때) 첫 매수금액 × add 를 다음 주 추가
과거 기록(02_전략검증_목록 1-2·1-3, ★·무작위 순서 기준): 불타기 4종·조이기 3종·수익 절반 잠금 전부 기각.
  → 이번엔 기준이 다르다(교집합·RS 높은 순) + 재매수·냉각은 처음 시험. 그래서 다시 잰다.

격자(전부 공개): 슬롯 10·20 × 래칫(초기 -7/-10/-15% × 고점 -15/-20/-25%) × 재매수 5 × 냉각 0/4/8주 × 불타기 3 = 810
  재매수: 없음 · 청산가 재돌파 · 청산 후 저점 +20% · +30% · 재돌파 또는 +20%   (청산 뒤 26주 안, 종목당 3회까지)
  불타기: 없음 · +20%마다 첫 매수의 50% (최대 2회) · +10%마다 50% (최대 3회, 터틀·오닐식 잘게)
공통: 교집합(RS80 × (이익가속 또는 흑자전환)) · RS 가중 정의 · 동시 신호 RS 높은 순 · 1주 지연 · 편도 0.3% · 현금 FEDFUNDS
참고선: 같은 슬롯 '고점 -20% 만'(현행 측정) · 상폐충격 1% 는 상위 후보 10개만 별도(3회 중앙)
결과: results/loss_cut_grid.json (조합별 통계 + 주별 자산 곡선)
"""
import os, sys, json, time, itertools
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
import rs_accel_bt as B
import spec_engine as E
A = S.A

OUT = os.path.join(ROOT, "results", "loss_cut_grid.json")
BASE = dict(freq="W", fill="next_close", full="skip", rebalance=None, cost=0.003, cash="fedfunds",
            source={}, entry="inter", market=None, rank="rs_desc")
INIT = [7, 10, 15]
TRAIL = [15, 20, 25]
RE = {"none": ("재매수 없음", None), "brk": ("청산가 재돌파", dict(mode="breakout", window=26, max_n=3)),
      "rb20": ("저점 +20% 반등", dict(mode="rebound", rb=0.2, window=26, max_n=3)),
      "rb30": ("저점 +30% 반등", dict(mode="rebound", rb=0.3, window=26, max_n=3)),
      "both": ("재돌파 또는 +20%", dict(mode="both", rb=0.2, window=26, max_n=3))}
CD = [0, 4, 8]
PY = {"none": ("불타기 없음", None), "p20": ("+20%마다 50% ×2", dict(step=20, add=0.5, max_adds=2)),
      "p10": ("+10%마다 50% ×3", dict(step=10, add=0.5, max_adds=3))}
SLOTS = [10, 20]
SHOCK = 0.01 / 52


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
               dims=dict(slots=SLOTS, init=INIT, trail=TRAIL, re={k: v[0] for k, v in RE.items()}, cd=CD,
                         py={k: v[0] for k, v in PY.items()}),
               dates=dates, spy=dict(stats=S.stats(spy_w)[0], curve=[round(float(x), 2) for x in (spy_.ffill() / spy_w.iloc[0] * 100).values]),
               ref={}, grid=[], curves={})

    def one(sp, seed=100, shock=0.0, log=None):
        h = E.run(sp, px_, sig, rs_, None, cr_, seed=seed, shock=shock, log=log)
        return h

    for ns in SLOTS:
        h = one(dict(BASE, name="ref", slots=ns, weight=1 / ns, exits=[("trail", 20)], pyramid=None))
        st = S.stats(h.v, spy_)[0]
        out["ref"][str(ns)] = dict(CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Sharpe=float(st["Sharpe"]))
        out["curves"][f"ref|{ns}"] = [round(float(x), 1) for x in (h.v / h.v.iloc[0] * 100).values]
    for ns, x, y, rk, cd, pk in itertools.product(SLOTS, INIT, TRAIL, RE, CD, PY):
        sp = dict(BASE, name="g", slots=ns, weight=1 / ns, exits=[("stop_entry", x), ("trail", y)],
                  pyramid=PY[pk][1], reentry=RE[rk][1], cooldown=cd)
        L = []
        h = one(sp, log=L)
        st = S.stats(h.v, spy_)[0]
        closed = [t for t in L if t["why"] != "보유 중"]
        key = f"{ns}|{x}|{y}|{rk}|{cd}|{pk}"
        out["grid"].append(dict(key=key, slots=ns, init=x, trail=y, re=rk, cd=cd, py=pk,
                                CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Sharpe=float(st["Sharpe"]),
                                Calmar=float(st["Calmar"]) if st.get("Calmar") else None, beat_yrs=st.get("beat_yrs"),
                                trades=len(closed), avg_wk=round(float(np.mean([t["wk"] for t in closed])), 1) if closed else None,
                                win=round(float(np.mean([t["sell_px"] > t["buy_px"] for t in closed])) * 100, 1) if closed else None,
                                avg_pos=round(float(h.n.mean()), 1), avg_cash=round(float(h.cash.mean()) * 100, 1)))
        out["curves"][key] = [round(float(v), 1) for v in (h.v / h.v.iloc[0] * 100).values]
        if len(out["grid"]) % 90 == 0:
            print(f"{len(out['grid'])}/810 · {time.time() - t0:.0f}초", flush=True)
    G = pd.DataFrame(out["grid"])
    # 상폐충격: Calmar 상위 10개만
    for _, r in G.sort_values("Calmar", ascending=False).head(10).iterrows():
        sp = dict(BASE, name="g", slots=r.slots, weight=1 / r.slots, exits=[("stop_entry", r.init), ("trail", r.trail)],
                  pyramid=PY[r.py][1], reentry=RE[r.re][1], cooldown=int(r.cd))
        sh = [S.stats(one(sp, seed=500 + s_, shock=SHOCK).v)[0]["CAGR"] for s_ in range(3)]
        G.loc[G.key == r.key, "shock1"] = float(np.median(sh))
    out["grid"] = json.loads(G.to_json(orient="records"))
    spy_c, spy_m = out["spy"]["stats"]["CAGR"], out["spy"]["stats"]["MDD"]
    eff = {}
    for dim in ("init", "trail", "re", "cd", "py", "slots"):
        eff[dim] = {str(k): dict(CAGR=float(g.CAGR.median()), MDD=float(g.MDD.median()), Calmar=float(g.Calmar.median()))
                    for k, g in G.groupby(dim)}
    out["summary"] = dict(n=len(G), beat_spy=int((G.CAGR > spy_c).sum()), mdd_le_spy=int((G.MDD >= spy_m).sum()),
                          both=int(((G.CAGR > spy_c) & (G.MDD >= spy_m)).sum()),
                          median_cagr=float(G.CAGR.median()), median_mdd=float(G.MDD.median()), effects=eff)
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    s = out["summary"]
    print(f"::notice title=래칫·재매수·냉각·불타기 격자 ({A.VER})::{s['n']}조합 · SPY 초과 {s['beat_spy']} · MDD≤SPY {s['mdd_le_spy']} · 둘 다 {s['both']} · "
          f"중앙 {s['median_cagr']}%/{s['median_mdd']}% · 참고(고점 -20%만) {out['ref']} · {out['secs']}초")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=래칫 격자 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
