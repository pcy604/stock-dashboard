# -*- coding: utf-8 -*-
"""RS 순 우선 교집합 — 강건성 격자 (2026-10-24, 차니 지정 범위)

발견(master_specs): 교집합(RS80 × (이익가속 또는 흑자전환))을 동시 신호 'RS 높은 순'으로 채우면 24.7%,
무작위 순서면 중앙 13.3%. 우연인지 보려고 아래 격자를 **한 번에 전부** 돌리고 전부 보여준다(골라 보여주지 않는다).

차니 지정(10-24): ① RS 정의 바꿔도 유지되나 ② 슬롯 수 ⑥ 상장폐지 충격 + 청산은 넓은 스펙트럼.
 (상위 N 안 무작위·기간 분할은 하지 않는다 — 기간은 화면에서 시작 월을 골라 직접 본다)

격자: RS 정의 3 × 슬롯 3 × 청산 16 = 144 조합, 각각 충격 없음 1회 + 상폐충격 연 1% 3회(중앙값)
  RS 정의  w    = 3·6·9·12개월 수익 0.4/0.2/0.2/0.2 가중(현행)
           r13  = 13주(3개월) 수익
           m121 = 12-1개월(52주 전 → 4주 전) 수익 — 학계 표준 모멘텀
           (모두 유동성 통과 종목 안 백분위 0~99. 진입 문턱 RS ≥ 80 과 우선순위 둘 다 같은 정의를 쓴다)
  슬롯     10(10%씩) · 20(5%씩) · 30(3.33%씩)
  청산     고점 -10/-15/-20/-25/-30/-40/-50% · 13/26/52주 최소보유 뒤 고점 -25% · 52/104주 보유 ·
           RS 50/70 미만 · 30주선 기울기 하락 · 30주선 이탈
공통: 1주 지연 체결 · 편도 0.3% · 현금 FEDFUNDS · 만석이면 새 신호 버림 · 평가 시작 = rs_accel_bt 와 같은 주
참고선: 같은 RS 정의·슬롯에서 '무작위 순서 + 고점 -20%' 5회 중앙값
결과: results/robust_rs.json (조합별 통계 + 주별 자산 곡선 → 화면에서 시작 월을 골라 100 으로 다시 맞춰 본다)
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
import rs_accel_bt as B
import spec_engine as E
A = S.A

OUT = os.path.join(ROOT, "results", "robust_rs.json")
BASE = dict(freq="W", fill="next_close", full="skip", pyramid=None, rebalance=None, cost=0.003, cash="fedfunds",
            source={}, entry="inter", market=None)
EXITS = [
    ("t10", "고점 -10%", [("trail", 10)]), ("t15", "고점 -15%", [("trail", 15)]), ("t20", "고점 -20%", [("trail", 20)]),
    ("t25", "고점 -25%", [("trail", 25)]), ("t30", "고점 -30%", [("trail", 30)]), ("t40", "고점 -40%", [("trail", 40)]),
    ("t50", "고점 -50%", [("trail", 50)]),
    ("m13", "13주 보유 뒤 고점 -25%", [("trail_after", 25, 13)]), ("m26", "26주 보유 뒤 고점 -25%", [("trail_after", 25, 26)]),
    ("m52", "52주 보유 뒤 고점 -25%", [("trail_after", 25, 52)]),
    ("h52", "52주 보유(손절 없음)", [("time", 52)]), ("h104", "104주 보유(손절 없음)", [("time", 104)]),
    ("rs50", "RS 50 미만", [("rank_below", 50)]), ("rs70", "RS 70 미만", [("rank_below", 70)]),
    ("slp", "30주선 기울기 하락", [("slope_neg", 30, 4)]), ("ma30", "30주선 이탈", [("below_ma", 30)]),
]
SLOTS = [10, 20, 30]
SHOCK = 0.01 / 52


def main():
    t0 = time.time()
    px, _, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    acc = (M["ACC"] == 1).fillna(False) & liq
    ta = B.turnaround(d, px) & liq
    fund = acc | ta
    pr = lambda sc: sc.where(liq).rank(axis=1, pct=True) * 99
    RSD = dict(w=B.rs_rank(px, liq), r13=pr(px / px.shift(13) - 1), m121=pr(px.shift(4) / px.shift(52) - 1))
    RSN = dict(w="3·6·9·12개월 가중(현행)", r13="13주 수익", m121="12-1개월 수익(학계 표준)")
    ma = {30: px.rolling(30, min_periods=24).mean()}
    try:
        t_ev = pd.Timestamp(json.load(open(B.OUT, encoding="utf-8"))["period"][0])
    except Exception:
        t_ev = px.index[60]
    sl = lambda z: z.loc[t_ev:]
    px_, spy_, cr_ = sl(px), sl(spy), sl(cr)
    ma_ = {k: sl(v) for k, v in ma.items()}
    spy_w = spy_.dropna()
    dates = [str(t.date()) for t in px_.index]
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER, period=[dates[0], dates[-1]], universe=int(px_.shape[1]),
               rs_defs=RSN, exits={k: nm for k, nm, _ in EXITS}, slots=SLOTS, dates=dates,
               spy=dict(stats=S.stats(spy_w)[0], curve=[round(float(x), 2) for x in (spy_.ffill() / spy_w.iloc[0] * 100).values]),
               grid=[], ref={}, curves={})
    for rk, rsm in RSD.items():
        sig = sl((fund & (rsm >= 80)).fillna(False))
        rsm_ = sl(rsm)
        for ns in SLOTS:
            cg = []
            for s_ in range(5):
                h = E.run(dict(BASE, name="ref", rank="random", slots=ns, weight=1 / ns, exits=[("trail", 20)]),
                          px_, sig, None, None, cr_, ma=ma_, seed=300 + s_)
                cg.append(S.stats(h.v)[0]["CAGR"])
            out["ref"][f"{rk}|{ns}"] = float(np.median(cg))
            for ek, enm, ex in EXITS:
                sp = dict(BASE, name=f"{rk}|{ns}|{ek}", rank="rs_desc", slots=ns, weight=1 / ns, exits=ex)
                L = []
                h = E.run(sp, px_, sig, rsm_, None, cr_, ma=ma_, seed=100, log=L)
                st, _ = S.stats(h.v, spy_)
                sh = []
                for s_ in range(3):
                    hh = E.run(sp, px_, sig, rsm_, None, cr_, ma=ma_, seed=400 + s_, shock=SHOCK)
                    sh.append(S.stats(hh.v)[0]["CAGR"])
                closed = [t for t in L if t["why"] != "보유 중"]
                key = f"{rk}|{ns}|{ek}"
                out["grid"].append(dict(key=key, rs=rk, slots=ns, exit=ek, CAGR=float(st["CAGR"]), MDD=float(st["MDD"]),
                                        Sharpe=float(st["Sharpe"]), beat_yrs=st.get("beat_yrs"),
                                        shock1=float(np.median(sh)), trades=len(closed),
                                        avg_wk=round(float(np.mean([t["wk"] for t in closed])), 1) if closed else None,
                                        win=round(float(np.mean([t["sell_px"] > t["buy_px"] for t in closed])) * 100, 1) if closed else None,
                                        avg_pos=round(float(h.n.mean()), 1), avg_cash=round(float(h.cash.mean()) * 100, 1)))
                out["curves"][key] = [round(float(x), 1) for x in (h.v / h.v.iloc[0] * 100).values]
            print(f"{rk} {ns} 완료 · {time.time() - t0:.0f}초", flush=True)
    G = pd.DataFrame(out["grid"])
    spy_c = out["spy"]["stats"]["CAGR"]
    out["summary"] = dict(
        n=len(G), beat_spy=int((G.CAGR > spy_c).sum()), beat_spy_shock=int((G.shock1 > spy_c).sum()),
        median_cagr=float(G.CAGR.median()), median_shock=float(G.shock1.median()),
        by_rs={k: float(v) for k, v in G.groupby("rs").CAGR.median().items()},
        by_slots={str(k): float(v) for k, v in G.groupby("slots").CAGR.median().items()},
        by_exit={k: float(v) for k, v in G.groupby("exit").CAGR.median().items()},
        rs_minus_ref=float(np.median([r["CAGR"] - out["ref"][f"{r['rs']}|{r['slots']}"]
                                      for r in out["grid"] if r["exit"] == "t20"])))
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    s = out["summary"]
    print(f"::notice title=RS순 강건성 ({A.VER})::{s['n']}조합 중 SPY({spy_c}%) 초과 {s['beat_spy']} · 충격1% 후 {s['beat_spy_shock']} · "
          f"중앙 CAGR {s['median_cagr']}% (충격 {s['median_shock']}%) · RS순-무작위(고점-20%) 중앙 {s['rs_minus_ref']:+.1f}%p · {out['secs']}초")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=RS순 강건성 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
