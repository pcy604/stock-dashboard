# -*- coding: utf-8 -*-
"""백테스트 상세 — '100으로 시작하면 실제로 무슨 일이 일어났나' (2026-10-24, 차니 요청)

rs_accel_bt.py 의 판정 숫자(CAGR·MDD)가 어떻게 나왔는지 사람이 따라갈 수 있게 한 시나리오를 통째로 남긴다.
  · 무작위 순서 10회 중 **CAGR 이 중앙값에 가장 가까운 회차**를 대표로 고른다(가장 좋은 회차가 아니다).
  · 주별 자산(시작 100) · SPY(시작 100) · 보유 종목 수 · 현금 비중
  · 거래 원장 전부(매수일·매도일·가격·보유 주수·수익률·계좌 기여도·청산 사유)
  · 낙폭 상위 5회(고점일·바닥일·회복일·깊이·기간) — 전략과 SPY 각각
  · 연도별 수익률 vs SPY
규칙은 rs_accel_bt.py 와 같다(같은 신호·같은 시뮬레이터). 결과: results/rs_accel_detail.json
"""
import os, sys, json, time
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))
import portfolio_rules_sim as S
import rs_accel_bt as B
A = S.A

OUT = os.path.join(ROOT, "results", "rs_accel_detail.json")
KEEP = {"rs80_fund": "교집합 — RS 80+ × (이익가속 또는 흑자전환)", "star": "현행 ★ — 이익가속 × 주간 +10%"}
SLOTS, STOP, DELAY = 20, 20, 1


def dd_episodes(v, k=5):
    """고점 → 바닥 → (고점 회복) 구간. 깊은 순 k 개."""
    v = v.dropna(); pk = v.cummax(); dd = v / pk - 1
    eps, i, n = [], 0, len(v)
    while i < n:
        if dd.iloc[i] < 0:
            s = i - 1
            j = i
            while j < n and dd.iloc[j] < 0:
                j += 1
            seg = dd.iloc[i:j]
            t = seg.idxmin()
            eps.append(dict(peak=str(v.index[s].date()), trough=str(t.date()),
                            recover=(str(v.index[j].date()) if j < n else None),
                            depth=round(float(seg.min()) * 100, 1),
                            wk_down=int(v.index.get_loc(t) - s),
                            wk_total=(int(j - s) if j < n else None)))
            i = j
        else:
            i += 1
    return sorted(eps, key=lambda e: e["depth"])[:k]


def yearly(v):
    return {int(y): round((g.iloc[-1] / g.iloc[0] - 1) * 100, 1) for y, g in v.groupby(v.index.year) if len(g) > 4}


def main():
    t0 = time.time()
    px, star, spy, cr, _ = S.load()
    d = A.load()
    M = A.matrices(d, ["adv_20d", "marcap", "ACC"])
    liq = ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)).fillna(False)
    acc = (M["ACC"] == 1).fillna(False) & liq
    rs = B.rs_rank(px, liq)
    ta = B.turnaround(d, px) & liq
    G = dict(star=star, rs80_fund=(acc | ta) & (rs >= 80))
    names = {c: n for c, n in d.drop_duplicates("sym", keep="last")[["sym", "name"]].values}

    spy_w = spy.dropna()
    s100 = spy_w / spy_w.iloc[0] * 100
    out = dict(run=time.strftime("%Y-%m-%d %H:%M"), factor_ver=A.VER,
               period=[str(px.index[0].date()), str(px.index[-1].date())], universe=int(px.shape[1]),
               rules=dict(
                   start="시작 자산 100(현금). 매주 월요일 라벨 주봉 종가로 체결",
                   slots=f"최대 {SLOTS}종목 동시 보유 — 신규 매수 1건 = 그 시점 총자산의 1/{SLOTS}(5%). 현금이 모자라면 남은 만큼",
                   entry=f"신호가 뜬 주의 {DELAY}주 뒤 종가에 매수(미리 알 수 없던 정보 차단). 같은 주 신호가 빈자리보다 많으면 무작위 순서로 채움",
                   full="20칸이 다 차면 새 신호는 버린다(교체 매매 없음)",
                   exit=f"손절·익절 구분 없이 하나: 보유 중 최고가 대비 -{STOP}% 이면 다음 체결(그 주 종가)에 전량 매도. 고정 익절 없음",
                   rebalance="리밸런싱 없음 — 오른 종목 비중을 덜지 않고, 내린 종목에 물타기·불타기 안 함",
                   cash="빈자리 현금은 미국 기준금리(FEDFUNDS) 이자를 받음",
                   cost="매수·매도 각각 0.3% 비용(수수료+슬리피지)",
                   seeds="같은 주 신호 순서를 10가지로 바꿔 돌린 뒤 CAGR 중앙값을 판정에 사용 — 이 화면은 중앙값에 가장 가까운 1회차"),
               spy=dict(curve=[round(float(x), 2) for x in s100.reindex(px.index).ffill().values],
                        yearly=yearly(spy_w), dd5=dd_episodes(spy_w), stats=S.stats(spy_w)[0]),
               dates=[str(t.date()) for t in px.index], variants={})
    for k, g in G.items():
        runs = []
        for s in range(B.SEEDS):
            h, _ = S.run(px, g, slots=SLOTS, stop=STOP, delay=DELAY, cash_r=cr, order="random", seed=100 + s)
            runs.append((S.stats(h.v)[0]["CAGR"], 100 + s))
        cagrs = sorted(c for c, _ in runs)
        medc = float(np.median(cagrs))
        seed = min(runs, key=lambda r: abs(r[0] - medc))[1]
        L = []
        h, info = S.run(px, g, slots=SLOTS, stop=STOP, delay=DELAY, cash_r=cr, order="random", seed=seed, log=L)
        v100 = h.v / h.v.iloc[0] * 100
        eq = h.v
        tr = []
        for x in L:
            r = (x["sell_px"] / x["buy_px"] - 1) * 100 if x["buy_px"] else None
            e0 = float(eq.loc[pd.Timestamp(x["buy"])])
            tr.append(dict(sym=x["sym"], name=names.get(x["sym"]), buy=x["buy"], sell=x["sell"],
                           buy_px=x["buy_px"], sell_px=x["sell_px"], peak_px=x["peak_px"], wk=x["wk"],
                           ret=(round(r, 1) if r is not None else None),
                           weight=round(x["inv"] / e0 * 100, 1),
                           contrib=round((x["out"] - x["inv"]) / e0 * 100, 2), why=x["why"]))
        closed = [t for t in tr if t["why"] != "보유 중"]
        wins = [t for t in closed if (t["ret"] or 0) > 0]
        loss = [t for t in closed if (t["ret"] or 0) <= 0]
        st, _ = S.stats(h.v, spy)
        out["variants"][k] = dict(
            label=KEEP[k], seed=seed, seed_cagrs=cagrs, stats=st,
            curve=[round(float(x), 2) for x in v100.values],
            n_pos=[int(x) for x in h.n.values], cash=[round(float(x) * 100, 1) for x in h.cash.values],
            yearly=yearly(h.v), dd5=dd_episodes(h.v),
            summary=dict(trades=len(closed), open=len(tr) - len(closed),
                         win_rate=round(len(wins) / max(1, len(closed)) * 100, 1),
                         avg_win=round(float(np.mean([t["ret"] for t in wins])), 1) if wins else None,
                         avg_loss=round(float(np.mean([t["ret"] for t in loss])), 1) if loss else None,
                         avg_wk=round(float(np.mean([t["wk"] for t in closed])), 1) if closed else None,
                         avg_pos=round(float(h.n.mean()), 1), avg_cash=round(float(h.cash.mean()) * 100, 1),
                         final=round(float(v100.iloc[-1]), 1), spy_final=round(float(s100.iloc[-1]), 1),
                         top10_share=round(sum(sorted([t["contrib"] for t in tr], reverse=True)[:10])
                                           / max(1e-9, sum(t["contrib"] for t in tr)) * 100, 1)),
            trades=tr)
        print(f"{k}: seed {seed} · CAGR {st['CAGR']} · 거래 {len(closed)} · 최종 {v100.iloc[-1]:.0f}", flush=True)
    out["secs"] = round(time.time() - t0)
    json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    V = out["variants"]
    print(f"::notice title=백테스트 상세 ({A.VER})::" + " · ".join(
        f"{k} 100→{V[k]['summary']['final']} (거래 {V[k]['summary']['trades']}, 승률 {V[k]['summary']['win_rate']}%)" for k in V)
        + f" · SPY 100→{V['star']['summary']['spy_final']}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        print(tb)
        print("::error title=백테스트 상세 예외::" + tb[-900:].replace("\n", " | "))
        sys.exit(1)
