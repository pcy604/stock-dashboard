# -*- coding: utf-8 -*-
"""전략 명세서 엔진 (2026-10-24) — '빈칸이 하나라도 있으면 실행이 안 되는' 전략 정의 → 주봉 포트폴리오 시뮬레이션

명세서(spec) 필수 항목 — 하나라도 없으면 ValueError:
  name        이름
  source      규칙의 출처와 '추정'(책에 없어서 우리가 정한 값) 목록
  freq        판단 주기. 현재 'W'(주봉 금요일 종가 기준 판정)만 지원
  fill        체결: 'next_close'(판정 다음 주 종가) — 미리 알 수 없던 정보 차단
  entry       진입 신호: 불리언 행렬(주 × 종목) 이름 — build() 가 만들어 넘긴다
  rank        동시 신호가 빈자리보다 많을 때 우선순위: 'rs_desc' | 'random'
  slots       최대 보유 종목 수
  weight      신규 1건 비중 = 총자산 × weight (현금이 모자라면 남은 만큼)
  full        만석일 때: 'skip'(새 신호 버림)
  exits       청산 규칙 목록(먼저 걸리는 것으로 전량 매도):
                ('stop_entry', p)      진입가 대비 -p%
                ('trail', p)           보유 중 최고가 대비 -p%
                ('trail_after', p, w)  w주 보유 뒤부터 고점 대비 -p%
                ('tp', p)              진입가 대비 +p% 익절
                ('tp_unless_fast', p, g, wg)  +p% 익절. 단 진입 후 wg주 안에 +g% 이상 오른 '급등주'는 익절 면제
                                       (오닐 8주 규칙 — 면제 종목은 다른 규칙, 예: below_ma_after 로 판다)
                ('below_ma', k)        주봉 종가 < k주 이동평균
                ('below_ma_after', k, w)  w주 보유 뒤부터 종가 < k주선
                ('time', w)            w주 보유 후 매도
  market      신규 매수 허용 조건 행렬 이름(주 단위 불리언, 종목 무관) 또는 None
  pyramid     None(추가매수 없음)
  rebalance   None(비중 조절 없음)
  cost        편도 비용(소수)
  cash        현금 이자: 'fedfunds'
시뮬레이터 관례는 portfolio_rules_sim.run 과 같다(주봉 종가 체결·1주 지연·편도 비용·현금 이자).
"""
import numpy as np
import pandas as pd

REQUIRED = ("name", "source", "freq", "fill", "entry", "rank", "slots", "weight", "full", "exits",
            "market", "pyramid", "rebalance", "cost", "cash")


def check(spec):
    miss = [k for k in REQUIRED if k not in spec]
    if miss:
        raise ValueError(f"명세서 빈칸: {miss}")
    if spec["freq"] != "W" or spec["fill"] != "next_close" or spec["full"] != "skip":
        raise ValueError("지원하지 않는 freq/fill/full")
    if spec["pyramid"] is not None or spec["rebalance"] is not None:
        raise ValueError("pyramid/rebalance 미지원(None 만)")


def run(spec, px, sig, rank_mat, mkt, cash_r, ma=None, seed=0, log=None):
    """px: 주봉 종가 DataFrame · sig: 진입 불리언 DataFrame · rank_mat: 우선순위 값(클수록 먼저)
    mkt: 주별 불리언 Series(None=항상 허용) · ma: {k: k주 이동평균 DataFrame}"""
    check(spec)
    rng = np.random.default_rng(seed)
    P = px.values; idx = px.index; cols = px.columns; n = len(idx)
    G = sig.shift(1).astype("boolean").fillna(False).values.astype(bool)    # 1주 지연
    MK = (mkt.shift(1).fillna(False).values.astype(bool) if mkt is not None else np.ones(n, bool))
    R = rank_mat.shift(1).values if rank_mat is not None else None
    MA = {k: v.values for k, v in (ma or {}).items()}
    cost = spec["cost"]; slots = spec["slots"]; wt = spec["weight"]
    cash = 1.0; pos = {}; hist = []

    def price(j, i):
        v = P[i, j]
        if v == v and v > 0:
            pos[j]["last"] = v
            return v
        return pos[j]["last"]

    for i in range(n):
        if cash_r is not None and cash > 0:
            cash *= 1 + cash_r.iloc[i]
        for j in list(pos):
            e = pos[j]; c = price(j, i); e["wk"] += 1
            e["peak"] = max(e["peak"], c)
            g = c / e["entry"] - 1
            why = None
            for rule in spec["exits"]:
                t = rule[0]
                if t == "stop_entry" and g <= -rule[1] / 100: why = t
                elif t == "trail" and c / e["peak"] - 1 <= -rule[1] / 100: why = t
                elif t == "trail_after" and e["wk"] >= rule[2] and c / e["peak"] - 1 <= -rule[1] / 100: why = t
                elif t == "tp" and g >= rule[1] / 100: why = t
                elif t == "tp_unless_fast":
                    p_, g_, wg = rule[1:]
                    if e["wk"] <= wg and g >= g_ / 100:
                        e["fast"] = True
                    if g >= p_ / 100 and not e.get("fast"):
                        why = t
                elif t == "below_ma":
                    m = MA[rule[1]][i, j]
                    if m == m and c < m: why = t
                elif t == "below_ma_after":
                    m = MA[rule[1]][i, j]
                    if e["wk"] >= rule[2] and m == m and c < m: why = t
                elif t == "time" and e["wk"] >= rule[1]: why = t
                if why:
                    break
            if why:
                v = e["sh"] * c * (1 - cost); cash += v
                if log is not None:
                    log.append(dict(sym=str(cols[j]), buy=str(idx[e["i0"]].date()), sell=str(idx[i].date()),
                                    buy_px=round(float(e["entry"]), 4), sell_px=round(float(c), 4),
                                    peak_px=round(float(e["peak"]), 4), wk=int(e["wk"]), inv=float(e["inv"]),
                                    out=float(v), why=why))
                del pos[j]
        eq = cash + sum(pos[j]["sh"] * price(j, i) for j in pos)
        if MK[i]:
            hit = np.where(G[i])[0]
            if spec["rank"] == "random" or R is None:
                hit = rng.permutation(hit)
            else:
                rv = R[i, hit]
                rv = np.where(rv == rv, rv, -np.inf)
                order = np.lexsort((rng.random(len(hit)), -rv))           # 같은 값이면 무작위
                hit = hit[order]
            for j in hit:
                if j in pos:
                    continue
                c = P[i, j]
                if not (c == c and c > 0):
                    continue
                if len(pos) >= slots:
                    break
                amt = min(eq * wt, cash)
                if amt <= eq * 0.001:
                    break
                pos[j] = dict(sh=amt / c * (1 - cost), entry=c, peak=c, wk=0, last=c, inv=amt, i0=i)
                cash -= amt
        eq = cash + sum(pos[j]["sh"] * price(j, i) for j in pos)
        hist.append((idx[i], eq, len(pos), cash / eq))
    if log is not None:
        for j in list(pos):
            e = pos[j]; c = price(j, n - 1)
            log.append(dict(sym=str(cols[j]), buy=str(idx[e["i0"]].date()), sell=str(idx[n - 1].date()),
                            buy_px=round(float(e["entry"]), 4), sell_px=round(float(c), 4),
                            peak_px=round(float(e["peak"]), 4), wk=int(e["wk"]), inv=float(e["inv"]),
                            out=float(e["sh"] * c * (1 - cost)), why="보유 중"))
    return pd.DataFrame(hist, columns=["t", "v", "n", "cash"]).set_index("t")
