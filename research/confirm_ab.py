# -*- coding: utf-8 -*-
"""위성 후보 A·B 사전 등록 재확인 + 코어·위성 결합표 (2026-10-26, 결과 보기 전 커밋)

후보(810·168 격자에서 나온 영역 — 여기서 다시 고르지 않는다):
  A 낙폭 우선  : 교집합 RS순 · 20칸 5% · 손절 = max(진입가 -15%, 고점 -15%) · 청산가 재돌파 재매수(26주·3회) · 냉각 4주 · 불타기 없음
  B 수익금 우선: A + 불타기(진입가 대비 +30%마다·그 주 신고가 → 첫 매수의 50% 다음 주 추가, 최대 3회, 종목당 상한 25%, 남는 현금만)

사전 등록 합격 기준 (후보마다, SPY = 같은 구간 매수보유)
  ① 중심 조합 CAGR > SPY 이고 Calmar > SPY
  ② 이웃값(한 번에 한 항목만 바꿈) 중 70% 이상이 ① 유지
     이웃: 냉각 2·3·5·6주 · 고점 -12·-18% · 초기 -12·-18% · (B) 불타기 +25·+35% · 추가 40·60%
  ③ 상폐충격 연 1%(3회 중앙) 에서도 CAGR > SPY
  ④ RS 정의 3종(가중·13주·12-1) 모두 CAGR > SPY
  ⑤ (A만) 중심 MDD ≥ SPY MDD(덜 빠짐) 이고 이웃 50% 이상 유지
  참고(합격 기준 아님): 동시 신호 무작위 순서 10회 중앙 — RS 순서 의존도를 보려고
결합표: 코어 = SPY + 40주선 스위치(아래면 현금, 1주 지연) · 위성 = A/B/현행(20칸·고점 -20%) ·
        위성 비중 0/20/30/40/50/70/100% · 13주마다 비중 복원 · 비용 편도 0.1%(지수)·위성 내부 비용은 이미 반영
결과: results/confirm_ab.json
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

OUT = os.path.join(ROOT, "results", "confirm_ab.json")
BASE = dict(freq="W", fill="next_close", full="skip", rebalance=None, cost=0.003, cash="fedfunds",
            source={}, entry="inter", market=None, rank="rs_desc", slots=20, weight=0.05)
RE = dict(mode="breakout", window=26, max_n=3)


def spec(init=15, trail=15, cd=4, py=None):
    return dict(BASE, name="c", exits=[("stop_entry", init), ("trail", trail)], reentry=RE, cooldown=cd, pyramid=py)


def pyd(step=30, add=0.5):
    return dict(step=step, add=add, max_adds=3, cap=25, fund="cash")


def main():
    t0 = time.time()
    px, _, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    fund = ((M["ACC"] == 1).fillna(False) & liq) | (B.turnaround(d, px) & liq)
    pr = lambda sc: sc.where(liq).rank(axis=1, pct=True) * 99
    RSD = dict(w=B.rs_rank(px, liq), r13=pr(px / px.shift(13) - 1), m121=pr(px.shift(4) / px.shift(52) - 1))
    try:
        t_ev = pd.Timestamp(json.load(open(B.OUT, encoding="utf-8"))["period"][0])
    except Exception:
        t_ev = px.index[60]
    sl = lambda z: z.loc[t_ev:]
    px_, spy_, cr_ = sl(px), sl(spy), sl(cr)
    SIG = {k: sl((fund & (v >= 80)).fillna(False)) for k, v in RSD.items()}
    RK = {k: sl(v) for k, v in RSD.items()}
    spy_w = spy_.dropna()
    spy_st = S.stats(spy_w)[0]
    idx = px_.index

    def run(sp, rs="w", rank=True, seed=100, shock=0.0):
        h = E.run(sp if rank else dict(sp, rank="random"), px_, SIG[rs], RK[rs] if rank else None, None, cr_,
                  seed=seed, shock=shock)
        st = S.stats(h.v, spy_)[0]
        return dict(CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Calmar=float(st["Calmar"]) if st.get("Calmar") else 0.0,
                    Sharpe=float(st["Sharpe"])), h.v

    def ok(r):
        return r["CAGR"] > spy_st["CAGR"] and r["Calmar"] > spy_st["Calmar"]

    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER, period=[str(idx[0].date()), str(idx[-1].date())],
               spy=spy_st, cands={}, blend={})
    curves = {}
    for ck, py0 in (("A", None), ("B", pyd())):
        c = {}
        center, v = run(spec(py=py0)); curves[ck] = v
        nb = {}
        for cd in (2, 3, 5, 6):
            nb[f"냉각 {cd}주"] = run(spec(cd=cd, py=py0))[0]
        for tr in (12, 18):
            nb[f"고점 -{tr}%"] = run(spec(trail=tr, py=py0))[0]
        for it in (12, 18):
            nb[f"초기 -{it}%"] = run(spec(init=it, py=py0))[0]
        if py0:
            for stp in (25, 35):
                nb[f"불타기 +{stp}%"] = run(spec(py=pyd(step=stp)))[0]
            for ad in (0.4, 0.6):
                nb[f"추가 {int(ad*100)}%"] = run(spec(py=pyd(add=ad)))[0]
        shock = float(np.median([run(spec(py=py0), seed=600 + s_, shock=0.01 / 52)[0]["CAGR"] for s_ in range(3)]))
        rsv = {k: run(spec(py=py0), rs=k)[0] for k in ("w", "r13", "m121")}
        rnd = [run(spec(py=py0), rank=False, seed=700 + s_)[0]["CAGR"] for s_ in range(10)]
        crit = {
            "① 중심 CAGR·Calmar > SPY": ok(center),
            "② 이웃 70%↑ 유지": sum(ok(r) for r in nb.values()) / len(nb) >= 0.7,
            "③ 상폐충격 후 CAGR > SPY": shock > spy_st["CAGR"],
            "④ RS 정의 3종 모두 > SPY": all(r["CAGR"] > spy_st["CAGR"] for r in rsv.values()),
        }
        if ck == "A":
            crit["⑤ MDD ≤ SPY(중심·이웃 50%↑)"] = center["MDD"] >= spy_st["MDD"] and \
                sum(r["MDD"] >= spy_st["MDD"] for r in nb.values()) / len(nb) >= 0.5
        c.update(center=center, neighbors=nb, nb_ok=sum(ok(r) for r in nb.values()), nb_n=len(nb), shock1=shock, rs=rsv,
                 random=dict(median=float(np.median(rnd)), p10=float(np.quantile(rnd, .1)), all=sorted(rnd)),
                 criteria={k: bool(v) for k, v in crit.items()}, passed=bool(all(crit.values())))
        out["cands"][ck] = c
        print(ck, center, "통과" if c["passed"] else "불합격", c["criteria"], flush=True)
    _, curves["cur"] = run(dict(BASE, name="cur", exits=[("trail", 20)], pyramid=None))

    # ── 결합표 ──
    spw = spy_.ffill()
    rspy = spw.pct_change().fillna(0)
    ma40 = spw.rolling(40, min_periods=30).mean()
    on = (spw > ma40).astype(float).shift(2).fillna(1.0)            # 주 t 판정 → t+1 체결 → t+2 수익
    turn = on.diff().abs().fillna(0)
    core_r = on * rspy + (1 - on) * cr_ - turn * 0.001
    core = (1 + core_r).cumprod()
    out["core"] = S.stats(core * 100)[0]
    for sk, sv in curves.items():
        rs_sat = sv.pct_change().fillna(0)
        rows = []
        for w in (0.0, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0):
            val, wc, ws = [1.0], 1 - w, w
            for i in range(1, len(idx)):
                if i % 13 == 0:                                       # 분기 복원
                    tot = wc + ws; wc, ws = tot * (1 - w), tot * w
                wc *= 1 + core_r.iloc[i]; ws *= 1 + rs_sat.iloc[i]
                val.append(wc + ws)
            v = pd.Series(val, index=idx) * 100
            st = S.stats(v)[0]
            rows.append(dict(w=w, CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Calmar=float(st["Calmar"]) if st.get("Calmar") else None,
                             Sharpe=float(st["Sharpe"]), final=round(float(v.iloc[-1]), 1)))
        out["blend"][sk] = rows
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    C = out["cands"]
    print(f"::notice title=A·B 사전 등록 재확인 ({A.VER})::SPY {spy_st['CAGR']}%/{spy_st['MDD']}% · "
          + " · ".join(f"{k} {v['center']['CAGR']}%/{v['center']['MDD']}% 이웃 {v['nb_ok']}/{v['nb_n']} 충격 {v['shock1']}% "
                       f"무작위 {v['random']['median']}% → {'합격' if v['passed'] else '불합격'}" for k, v in C.items()))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=A·B 재확인 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
