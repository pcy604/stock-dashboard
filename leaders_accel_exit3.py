# -*- coding: utf-8 -*-
"""
청산 재검정 — 사용자 지적(2026-08-25): "시장이 내 매수가를 아는 것도 아닌데"

앞선 leaders_accel_exit2.py 는 전 신호 7,551건 평균으로 청산을 비교했다. 두 결함이 있었다.
  ① **기준점과 폭을 동시에 바꿨다.** '진입가 −25%' 와 '고점 −30%' 를 비교해놓고
     기준점의 승리라고 했다. 보유기간을 맞추면 격차가 크게 줄어든다.
  ② **'초기 손절' 과 '추세 종료' 를 한 숫자로 뭉갰다.** 진입가 기준 손절은 포지션이
     이익 구간에 들어가면 사실상 발동하지 않는다. 즉 그건 청산 규칙이 아니라
     "지면 자르고 이기면 안 판다" 다. +100% 갔다 꺾인 종목은 −25% 까지 다 토해낸다.

그래서 질문을 바꾼다. **이미 오른 종목만 놓고** 무엇이 최선인가.
  · 표본을 '진입 후 최고 +X% 이상 도달' 로 조건부 제한한다
  · 그 시점(=+X% 도달 주) 이후의 청산만 비교한다 — 초기 손절 구간을 아예 뺀다
  · 지표는 leaders_accel.py 와 동일: 평균 · 알파 · 2배+ · 10배+
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_accel_exit as AE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 300)
FEE, HMAX = 0.001, 104


def run_cond(V, MA20, SPY, gi, gj, gain_gate, rule):
    """gain_gate 만큼 오른 뒤부터 rule 로 청산. 반환: (수익, 알파, 보유주) 리스트"""
    out, n = [], len(V)
    for i0, jc in zip(gi, gj):
        e = V[i0, jc]
        if not (e == e and e > 0):
            continue
        # ① 조건 도달 시점 찾기 (진입 후 최고가가 e*(1+gain_gate) 를 넘는 첫 주)
        k0 = None
        for k in range(i0 + 1, min(n, i0 + HMAX + 1)):
            v = V[k, jc]
            if v == v and v >= e * (1 + gain_gate):
                k0 = k
                break
        if k0 is None:
            continue                       # 그만큼 오르지 못한 신호는 이 표본이 아니다
        # ② 그 시점부터 청산 규칙 적용. 기준가 = 조건 도달가(= 시장이 아는 가격)
        base, peak, below, px, k_end = V[k0, jc], V[k0, jc], 0, V[k0, jc], None
        for k in range(k0 + 1, min(n, i0 + HMAX + 1)):
            v = V[k, jc]
            if v != v:
                continue
            peak = max(peak, v)
            m = MA20[k, jc]
            below = below + 1 if (m == m and v < m) else 0
            px = v
            if rule(v, dict(e=e, base=base, peak=peak, below=below, wk=k - k0)):
                k_end = k
                break
        if k_end is None:
            k_end = min(n - 1, i0 + HMAX)
            col = V[k0:k_end + 1, jc]
            col = col[~np.isnan(col)]
            px = col[-1] if len(col) else base
        r = px / e * (1 - FEE) ** 2 - 1          # 수익은 **진입가 기준** 으로 잰다
        s0, s1 = SPY[i0], SPY[min(k_end, n - 1)]
        out.append((r, r - (s1 / s0 - 1), k_end - i0))
    return pd.DataFrame(out, columns=["ret", "alpha", "wk"])


def main():
    M, spy, gate, extra = AE.accel_panel()
    px = M["close"]
    V = px.values
    MA20 = M["ma20"].reindex_like(px).values
    SPY = spy.reindex(px.index).ffill().values
    gi, gj = np.where(gate.values)

    RULES = [
        ("안 판다 (104주)", lambda v, s: False),
        ("고점 대비 −20%", lambda v, s: v <= s["peak"] * 0.80),
        ("고점 대비 −25%", lambda v, s: v <= s["peak"] * 0.75),
        ("고점 대비 −30%", lambda v, s: v <= s["peak"] * 0.70),
        ("고점 대비 −40%", lambda v, s: v <= s["peak"] * 0.60),
        ("고점 대비 −50%", lambda v, s: v <= s["peak"] * 0.50),
        ("20주선 이탈 2주", lambda v, s: s["below"] >= 2),
        ("진입가 −25% (현행 문구)", lambda v, s: v <= s["e"] * 0.75),
    ]
    for g in (0.30, 0.50, 1.00):
        print(f"\n═══ 진입 후 +{g:.0%} 이상 도달한 신호만 ═══")
        base = None
        print(f"{'청산 규칙':<24}{'n':>6}{'평균':>9}{'알파평균':>10}{'중앙':>9}"
              f"{'2배+':>8}{'10배+':>8}{'보유주':>8}{'알파차':>9}")
        for nm, fn in RULES:
            T = run_cond(V, MA20, SPY, gi, gj, g, fn)
            if not len(T):
                continue
            if base is None:
                base = T.alpha.mean()
            print(f"{nm:<24}{len(T):>6}{T.ret.mean():>9.1%}{T.alpha.mean():>10.1%}"
                  f"{T.ret.median():>9.1%}{(T.ret >= 1).mean():>8.1%}"
                  f"{(T.ret >= 9).mean():>8.2%}{T.wk.mean():>8.0f}"
                  f"{T.alpha.mean()-base:>+9.1%}")


if __name__ == "__main__":
    main()
