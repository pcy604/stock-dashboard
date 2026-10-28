# -*- coding: utf-8 -*-
"""사전 등록(2026-10-28, 결과 보기 전 커밋) — ① RS '수준' 대신 '변화·가속'  ② 이익 단계별 흑자전환

━━ ① RS 변화·가속 (차니: 변하는 흐름을 보고 가속하는 종목을 사야 하지 않나) ━━
근거: Gettleman·Marks(2005, 1926~2003) 6개월 모멘텀의 변화(가속)가 단순 모멘텀에 6개월 +3% 추가 ·
      Chen·Yu(2013, 1962~2011) 볼록하게 가속하는 승자 월 1.32% vs 단순 모멘텀 0.83% ·
      오닐(IBD) 'RS선(종목÷지수)이 주가보다 먼저 신고가' · 우리 실측: RS 80 첫 도달 매수는 대박 상승의 41%만 먹음(촉매 시점 63%)
변형(진입 = 교집합 펀더멘털(이익가속 또는 흑자전환) × 아래 문턱, 체계는 위성 A·B 그대로):
  base  RS(가중) ≥ 80 · 우선순위 RS 수준                       (현행 — 비교 기준)
  dRS   RS(가중) ≥ 60 · 우선순위 RS 순위 k주 개선 폭
  acc   RS(가중) ≥ 60 · 우선순위 가격 가속 = 최근 k주 수익 − 그 전 k주 수익
  line  RS(가중) ≥ 60 & RS선(종목÷SPY)이 k주 신고가 · 우선순위 RS 수준
  mix   RS(가중) ≥ 70 · 우선순위 = RS 수준 백분위 50% + k주 개선 폭 백분위 50%
  k 는 13·26·52주 3가지(사전 등록 기준 ④의 '정의 3종' 자리). 중심값 k = 26.
합격(변형마다, A·B 각각): ① k=26 CAGR·Calmar > SPY  ② k 3종 모두 CAGR > SPY  ③ 상폐충격 1%(3회 중앙) 후 CAGR > SPY
  ④ base 보다 Calmar 높음(같은 체계)  · 참고: 매수 시점 52주 고점 대비 위치 중앙(낮을수록 '일찍' 산 것)
━━ ② 이익 단계별 흑자전환 (매출총이익 → 영업이익 → 순이익) ━━
조정 EBITDA 는 비GAAP 이라 SEC 표준 재무(XBRL)에 없고, 감가상각비도 우리 데이터에 없다 → 제외(화면에 명시).
사건 = 분기 X > 0 이고 전년 같은 분기 X ≤ 0 (계절성 제거), 그 주에 공시된 값만. X ∈ {매출총이익, 영업이익, 순이익}
측정 a) 사건 다음 주 종가 매수 → 13·26·52주 수익(평균·중앙·SPY 대비 초과·2배 이상 비율) · 같은 기간 전 종목 기준선
     b) 순서: 같은 종목에서 매출총이익 → 영업이익 → 순이익 흑자전환까지 걸린 분기 수(중앙)
     c) 포트폴리오: 흑자전환(X) × RS(가중) ≥ 80 · 20칸 · 위성 A 체계 → CAGR·MDD (X 3종 비교, 같은 엔진)
결과: results/rs_accel_turn.json
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

OUT = os.path.join(ROOT, "results", "rs_accel_turn.json")
BASE = dict(freq="W", fill="next_close", full="skip", rebalance=None, cost=0.003, cash="fedfunds",
            source={}, entry="x", market=None, rank="rs_desc", slots=20, weight=0.05,
            exits=[("stop_entry", 15), ("trail", 15)], reentry=dict(mode="breakout", window=26, max_n=3), cooldown=4)
SYS = {"A": None, "B": dict(step=30, add=0.5, max_adds=3, cap=25, fund="cash")}


def pct(df, liq):
    return df.where(liq).rank(axis=1, pct=True) * 100


def main():
    t0 = time.time()
    px, _, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    ta_oi = B.turnaround(d, px) & liq
    fund = ((M["ACC"] == 1).fillna(False) & liq) | ta_oi
    rs = B.rs_rank(px, liq)
    spw = spy.reindex(px.index).ffill()
    rel = px.div(spw, axis=0)
    hi52 = px.rolling(52, min_periods=40).max()
    try:
        t_ev = pd.Timestamp(json.load(open(B.OUT, encoding="utf-8"))["period"][0])
    except Exception:
        t_ev = px.index[60]
    sl = lambda z: z.loc[t_ev:]
    px_, spy_, cr_ = sl(px), sl(spy), sl(cr)
    spy_w = spy_.dropna(); spy_st = S.stats(spy_w)[0]

    def variant(v, k):
        if v == "base":
            return fund & (rs >= 80), rs
        if v == "dRS":
            return fund & (rs >= 60), pct(rs - rs.shift(k), liq)
        if v == "acc":
            a = (px / px.shift(k) - 1) - (px.shift(k) / px.shift(2 * k) - 1)
            return fund & (rs >= 60), pct(a, liq)
        if v == "line":
            return fund & (rs >= 60) & (rel >= rel.rolling(k, min_periods=int(k * .8)).max() * 0.999), rs
        if v == "mix":
            return fund & (rs >= 70), 0.5 * pct(rs, liq) + 0.5 * pct(rs - rs.shift(k), liq)

    def run(sig, rk, sysk, seed=100, shock=0.0, log=None):
        h = E.run(dict(BASE, name="v", pyramid=SYS[sysk]), px_, sl(sig.fillna(False)), sl(rk), None, cr_,
                  seed=seed, shock=shock, log=log)
        st = S.stats(h.v, spy_)[0]
        return dict(CAGR=float(st["CAGR"]), MDD=float(st["MDD"]), Calmar=float(st["Calmar"]) if st.get("Calmar") else 0.0)

    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER, period=[str(px_.index[0].date()), str(px_.index[-1].date())],
               spy=spy_st, rs={}, turn={})
    hp = sl(px / hi52)
    for sysk in SYS:
        base_c = None
        for v in ("base", "dRS", "acc", "line", "mix"):
            ks = {}
            for k in (13, 26, 52):
                sig, rk = variant(v, k)
                L = []
                r = run(sig, rk, sysk, log=L)
                buys = [(t["buy"], t["sym"]) for t in L]
                pos_hi = [hp.at[pd.Timestamp(b), s_] for b, s_ in buys if s_ in hp.columns]
                r["entry_vs_hi52"] = round(float(np.nanmedian(pos_hi)) * 100 - 100, 1) if pos_hi else None
                r["trades"] = sum(1 for t in L if t["why"] != "보유 중")
                ks[str(k)] = r
                if v == "base":
                    break
            if v == "base":
                ks = {"26": ks["13"]}
            sig, rk = variant(v, 26)
            sh = float(np.median([run(sig, rk, sysk, seed=800 + s_, shock=0.01 / 52)["CAGR"] for s_ in range(3)]))
            c = ks["26"]
            if v == "base":
                base_c = c
            crit = {"① k=26 CAGR·Calmar > SPY": c["CAGR"] > spy_st["CAGR"] and c["Calmar"] > spy_st["Calmar"],
                    "② k 3종 모두 > SPY": all(x["CAGR"] > spy_st["CAGR"] for x in ks.values()),
                    "③ 상폐충격 후 > SPY": sh > spy_st["CAGR"],
                    "④ 현행(base)보다 Calmar 높음": v != "base" and c["Calmar"] > base_c["Calmar"]}
            out["rs"][f"{sysk}|{v}"] = dict(ks=ks, shock1=sh, criteria={a: bool(b) for a, b in crit.items()},
                                            passed=bool(all(crit.values())) if v != "base" else None)
            print(sysk, v, ks, sh, crit, flush=True)

    # ── ② 이익 단계별 흑자전환 ──
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "gross_profit", "op_income", "net_income"]].sort_values(["sym", "period_end"]).copy())
    lab = {"gross_profit": "매출총이익", "op_income": "영업이익", "net_income": "순이익"}
    for c_ in lab:
        prev = q.groupby("sym")[c_].shift(4)
        q[f"T_{c_}"] = ((q[c_] > 0) & (prev <= 0)).astype(int)
    x = d[["as_of", "sym", "period_end"]].merge(q[["sym", "period_end"] + [f"T_{c}" for c in lab]], on=["sym", "period_end"], how="left")
    fwd = {h: px.shift(-h - 1) / px.shift(-1) - 1 for h in (13, 26, 52)}             # 다음 주 종가 매수
    spf = {h: spw.shift(-h - 1) / spw.shift(-1) - 1 for h in (13, 26, 52)}
    for c_, nm in lab.items():
        T = (x.pivot_table(index="as_of", columns="sym", values=f"T_{c_}").reindex(index=px.index, columns=px.columns).fillna(0) == 1)
        first = T & ~T.shift(1).astype("boolean").fillna(False).astype(bool) & liq    # 새 분기가 반영된 첫 주만
        first = first.loc[t_ev:]
        res = dict(name=nm, events=int(first.values.sum()), by_h={})
        for h in (13, 26, 52):
            f = fwd[h].loc[t_ev:][first].stack()
            ex = (fwd[h].loc[t_ev:].sub(spf[h].loc[t_ev:], axis=0))[first].stack()
            basef = fwd[h].loc[t_ev:].where(liq.loc[t_ev:]).stack()
            res["by_h"][str(h)] = dict(n=int(len(f)), mean=round(float(f.mean()) * 100, 1), median=round(float(f.median()) * 100, 1),
                                       excess_vs_spy=round(float(ex.mean()) * 100, 1), p2x=round(float((f >= 1).mean()) * 100, 2),
                                       base_mean=round(float(basef.mean()) * 100, 1), base_median=round(float(basef.median()) * 100, 1))
        for sysk in ("A",):
            res["port_rs80"] = run(T & liq & (rs >= 80), rs, sysk)
            res["port_any"] = run(T & liq, rs, sysk)
        out["turn"][c_] = res
        print(nm, res, flush=True)
    # 순서(분기 수): 같은 종목에서 매출총이익 → 영업이익 → 순이익
    lag = {"매출총이익→영업이익": [], "영업이익→순이익": []}
    for s_, g in q.groupby("sym"):
        def first_q(col):
            w = np.where(g[col].values == 1)[0]
            return w
        for (a, b), key in ((("T_gross_profit", "T_op_income"), "매출총이익→영업이익"), (("T_op_income", "T_net_income"), "영업이익→순이익")):
            for ia in first_q(a):
                nb = [ib for ib in first_q(b) if ib >= ia]
                if nb and nb[0] - ia <= 12:
                    lag[key].append(nb[0] - ia)
    out["turn_lag_q"] = {k: dict(n=len(v), median=float(np.median(v)) if v else None, same_q=round(float(np.mean([z == 0 for z in v])) * 100, 1) if v else None)
                         for k, v in lag.items()}
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    R = out["rs"]
    print(f"::notice title=RS 변화·가속 + 단계별 흑자전환 ({A.VER})::SPY {spy_st['CAGR']}% · " + " · ".join(
        f"{k} {v['ks']['26']['CAGR']}%/{v['ks']['26']['MDD']}% {'합격' if v['passed'] else ('기준' if v['passed'] is None else '불합격')}"
        for k, v in R.items()) + " · " + " · ".join(f"{v['name']} 사건 {v['events']} 52주 초과 {v['by_h']['52']['excess_vs_spy']}%p" for v in out["turn"].values()))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=RS 변화·흑자전환 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
