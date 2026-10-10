# -*- coding: utf-8 -*-
"""
익절 기준 선정 (2026-09-13) — 사용자 위임: "익절 기준으로 알아서 골라봐"

배경. 08-25 청산 연구 결론은 두 줄이었다.
  · 이긴 종목에 **트레일을 걸면 폭에 상관없이 손해**다(고점 −25% 알파 −15.5%p).
  · 그런데 **52주 최소보유 바닥을 깔면 트레일이 구제된다**(알파 12.1% = 무매도 동률, 보유 60주).
남은 질문: 기준점은 **시장이 아는 가격**이어야 한다(사용자 지적). 그래서 트레일 대신
차트 구조를 쓰는 세 후보를 재고, 52주 바닥과 조합한다.

후보
  A 직전 스윙 저점 이탈   최근 8주 최저가 하향 이탈
  B 베이스 붕괴          최근 20주 최저가 하향 이탈
  C 신고가 갱신 실패      진입 후 최고가를 N주 동안 못 넘음
  D (기존 최고) 고점 −30% 트레일

채점 기준(측정 전에 고정) — ①알파가 무매도 대비 −2%p 이내 ②평균 보유가 짧을 것
(슬롯 회전) ③10배+ 꼬리를 덜 죽일 것.

⚠️ 깨지는 지점 — ①생존편향은 여전히 "오래 들고 있어라" 쪽을 부풀린다 ②104주 관측
상한 ③자본 제약 무시(5칸이면 52주 최소보유 = 연 5종) ④주봉 종가라 장중 이탈은 못 본다.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_accel as AC   # leaders_accel_exit 은 대청소(42c4bbb) 로 import 가 깨졌다

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
pd.set_option("display.width", 300)
FEE, HMAX = 0.001, 104


def build():
    """close 패널 + 가속 게이트. leaders_accel 만 직접 쓴다(의존 최소화)."""
    d = AC.load()
    M = AC.matrices(d, ["close", "adv_20d", "marcap", "ret_1w", "ACC"])
    px = M["close"]
    gate = AC.gate_of(M).reindex(index=px.index, columns=px.columns).fillna(False)
    spy = pd.read_csv(os.path.join(AC.BASE, "data", "leaders_cache", "px_SPY.csv"),
                      index_col=0, parse_dates=True)["Close"].reindex(px.index).ffill()
    return px.values, spy.values, np.where(gate.values), px.index


def sim(V, SPY, gi, gj, rule, min_wk=0, need_gain=None):
    """rule(v, st)->bool. min_wk 전에는 안 판다. need_gain 주면 그만큼 오른 신호만 표본."""
    out, n = [], len(V)
    for i0, jc in zip(gi, gj):
        e = V[i0, jc]
        if not (e == e and e > 0):
            continue
        if need_gain is not None:
            seg = V[i0 + 1:min(n, i0 + HMAX + 1), jc]
            if not len(seg) or np.all(np.isnan(seg)) or np.nanmax(seg) / e - 1 < need_gain:
                continue
        peak, pk_k, px_, k_end = e, i0, e, None
        for k in range(i0 + 1, min(n, i0 + HMAX + 1)):
            v = V[k, jc]
            if v != v:
                continue
            if v > peak:
                peak, pk_k = v, k
            px_ = v
            if k - i0 < min_wk:
                continue
            w8 = V[max(0, k - 8):k, jc]
            w20 = V[max(0, k - 20):k, jc]
            st = dict(peak=peak, e=e,
                      low8=np.nanmin(w8) if len(w8) and not np.all(np.isnan(w8)) else np.nan,
                      low20=np.nanmin(w20) if len(w20) and not np.all(np.isnan(w20)) else np.nan,
                      dry=k - pk_k)
            if rule(v, st):
                k_end = k
                break
        if k_end is None:
            k_end = min(n - 1, i0 + HMAX)
            col = V[i0:k_end + 1, jc]
            col = col[~np.isnan(col)]
            px_ = col[-1] if len(col) else e
        r = px_ / e * (1 - FEE) ** 2 - 1
        s0, s1 = SPY[i0], SPY[min(k_end, n - 1)]
        out.append((r, r - (s1 / s0 - 1), k_end - i0))
    return pd.DataFrame(out, columns=["ret", "alpha", "wk"])


HOLD = lambda v, s: False
SWING = lambda v, s: s["low8"] == s["low8"] and v < s["low8"]
BASE = lambda v, s: s["low20"] == s["low20"] and v < s["low20"]
def DRY(n):  return lambda v, s: s["dry"] >= n
TRAIL = lambda x: (lambda v, s: v <= s["peak"] * (1 - x))


def show(title, rows, V, SPY, gi, gj, need_gain=None):
    print(f"\n══ {title} ══")
    print(f"{'규칙':<28}{'n':>6}{'평균':>9}{'알파':>9}{'2배+':>8}{'10배+':>8}{'보유':>7}{'Δ알파':>8}")
    base = None
    for nm, fn, mw in rows:
        t = sim(V, SPY, gi, gj, fn, mw, need_gain)
        if not len(t):
            continue
        if base is None:
            base = t.alpha.mean()
        print(f"{nm:<28}{len(t):>6}{t.ret.mean():>9.1%}{t.alpha.mean():>9.1%}"
              f"{(t.ret >= 1).mean():>8.1%}{(t.ret >= 9).mean():>8.2%}"
              f"{t.wk.mean():>7.0f}{t.alpha.mean()-base:>+8.1%}")


def wf(V, SPY, gi, gj, IDX):
    """워크포워드 + 정체 문턱 스윕. 격자 1위를 그냥 믿지 않기 위한 절차."""
    yr = IDX[gi].year.values
    seg = {"앞 2018~2021": yr <= 2021, "뒤 2022~": yr >= 2022}
    print()
    print("══ 정체 문턱 스윕 × 워크포워드 (전부 52주 바닥) ══")
    print(f"{'규칙':<22}" + "".join(f"{k+' 알파':>16}" for k in seg) + f"{'전체 알파':>11}{'보유':>7}")
    cand = [("안 판다", HOLD, 0)] + [(f"신고가 {n}주 실패", DRY(n), 52) for n in (13, 20, 26, 33, 39, 52)]
    cand += [("고점 −30% 트레일", TRAIL(0.30), 52), ("베이스 붕괴", BASE, 52)]
    for nm, fn, mw in cand:
        row = []
        for k, m in seg.items():
            t = sim(V, SPY, gi[m], gj[m], fn, mw)
            row.append(t.alpha.mean() if len(t) else float("nan"))
        t = sim(V, SPY, gi, gj, fn, mw)
        print(f"{nm:<22}" + "".join(f"{v:>16.1%}" for v in row)
              + f"{t.alpha.mean():>11.1%}{t.wk.mean():>7.0f}")


def main():
    V, SPY, (gi, gj), IDX = build()
    print(f"신호 {len(gi):,}건 · 최대 추적 {HMAX}주 · 수수료 {FEE:.1%}")

    rows = [
        ("안 판다 (104주)", HOLD, 0),
        ("A 스윙저점 이탈", SWING, 0),
        ("B 베이스(20주) 붕괴", BASE, 0),
        ("C 신고가 13주 실패", DRY(13), 0),
        ("C 신고가 26주 실패", DRY(26), 0),
        ("D 고점 −30% 트레일", TRAIL(0.30), 0),
        ("── 52주 최소보유 조합 ──", HOLD, 0),
        ("A + 52주 바닥", SWING, 52),
        ("B + 52주 바닥", BASE, 52),
        ("C13 + 52주 바닥", DRY(13), 52),
        ("C26 + 52주 바닥", DRY(26), 52),
        ("D + 52주 바닥", TRAIL(0.30), 52),
        ("── 39주 바닥 ──", HOLD, 0),
        ("A + 39주 바닥", SWING, 39),
        ("B + 39주 바닥", BASE, 39),
        ("D + 39주 바닥", TRAIL(0.30), 39),
    ]
    show("전체 신호", rows, V, SPY, gi, gj)
    show("이미 +50% 오른 신호만", rows, V, SPY, gi, gj, need_gain=0.50)
    wf(V, SPY, gi, gj, IDX)


if __name__ == "__main__":
    main()
