# -*- coding: utf-8 -*-
"""
이익 가속 규칙 — 트레이드 층위 청산 대결

이 규칙은 6칸 포트폴리오가 아니라 **신호 목록**이다(문서: 평균 74종, "신호 목록이지
포트폴리오 규칙이 아니다"). 그래서 슬롯 경쟁 없이 **모든 신호를 한 건씩** 채점한다.
leaders_accel.py 가 쓰는 것과 같은 지표로 잰다 — 평균 · 알파평균 · 2배+ · 10배+.
중앙값으로 판정하지 않는다(그 문서의 경고: 분포가 U자다).

기준선은 '고정 보유'다. 청산 규칙이 그것보다 나은지가 유일한 질문이다.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_accel_exit as AE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 300)
FEE = 0.001
HMAX = 104


def run(V, MA10, MA20, ACC, SPY, gi, gj, rule):
    """rule(k, state) -> True 면 그 주 종가 청산. 반환: 트레이드 DataFrame"""
    out = []
    n = len(V)
    for i0, jc in zip(gi, gj):
        e = V[i0, jc]
        if not (e == e and e > 0):
            continue
        peak, below, k_end, px = e, 0, None, e
        for k in range(i0 + 1, min(n, i0 + HMAX + 1)):
            v = V[k, jc]
            if v != v:
                continue
            peak = max(peak, v)
            m20, m10 = MA20[k, jc], MA10[k, jc]
            below = below + 1 if (m20 == m20 and v < m20) else 0
            st = dict(e=e, peak=peak, wk=k - i0, below=below, acc=ACC[k, jc],
                      m10=m10, m20=m20)
            px = v
            if rule(v, st):
                k_end = k
                break
        if k_end is None:
            k_end = min(n - 1, i0 + HMAX)
            px = V[i0:k_end + 1, jc]
            px = px[~np.isnan(px)]
            px = px[-1] if len(px) else e
        r = px / e * (1 - FEE) ** 2 - 1
        s0, s1 = SPY[i0], SPY[min(k_end, n - 1)]
        out.append((r, r - (s1 / s0 - 1), k_end - i0))
    T = pd.DataFrame(out, columns=["ret", "alpha", "wk"])
    return T


def line(nm, T):
    return (f"{nm:<26}{len(T):>6}{T.ret.mean():>9.1%}{T.alpha.mean():>9.1%}"
            f"{T.ret.median():>9.1%}{(T.ret >= 1).mean():>8.1%}"
            f"{(T.ret >= 3).mean():>8.2%}{(T.ret >= 9).mean():>8.2%}"
            f"{T.wk.mean():>8.0f}")


def main():
    M, spy, gate, extra = AE.accel_panel()
    px = M["close"]
    V = px.values
    MA20 = M["ma20"].reindex_like(px).values
    MA10 = M["ma10"].reindex_like(px).values
    ACC = extra["ACC"].reindex_like(px).fillna(0).values
    SPY = spy.reindex(px.index).ffill().values
    gi, gj = np.where(gate.values)
    print(f"[가속 규칙] 신호 {len(gi)}건 · 최대 추적 {HMAX}주 · 수수료 {FEE:.1%}\n")

    R = [
        ("고정 26주 보유", lambda v, s: s["wk"] >= 26),
        ("고정 52주 보유", lambda v, s: s["wk"] >= 52),
        ("고정 104주 보유", lambda v, s: False),
    ]
    for t in (0.20, 0.25, 0.30, 0.35, 0.40, 0.50):
        R.append((f"트레일 -{t:.0%}", (lambda t: lambda v, s: v <= s["peak"] * (1 - t))(t)))
    for t in (0.15, 0.20, 0.25, 0.30):
        R.append((f"진입가 대비 -{t:.0%} 손절",
                  (lambda t: lambda v, s: v <= s["e"] * (1 - t))(t)))
    R += [
        ("진입가-20% 후 트레일-30%",
         lambda v, s: (v <= s["e"] * 0.80) if s["peak"] <= s["e"] * 1.05
         else (v <= s["peak"] * 0.70)),
        ("20주선 이탈 2주", lambda v, s: s["below"] >= 2),
        ("가속 꺼짐(ACC=0)", lambda v, s: s["acc"] == 0),
        ("가속 꺼짐 or 트레일-30%",
         lambda v, s: (s["acc"] == 0) or (v <= s["peak"] * 0.70)),
        ("가속 꺼짐 & 20주선 아래",
         lambda v, s: (s["acc"] == 0) and s["below"] >= 1),
    ]
    print(f"{'청산 규칙':<26}{'n':>6}{'평균':>9}{'알파평균':>9}{'중앙':>9}"
          f"{'2배+':>8}{'4배+':>8}{'10배+':>8}{'보유주':>8}")
    res = {}
    for nm, fn in R:
        T = run(V, MA10, MA20, ACC, SPY, gi, gj, fn)
        res[nm] = T
        print(line(nm, T))
    pd.to_pickle(res, os.path.join(BASE, "data", "_accel_exit.pkl"))

    # 워크포워드: 신호 발생 시점으로 앞/뒤 가르기
    yr = px.index[gi].year.values
    print("\n── 워크포워드 (신호 발생 연도 기준) ──")
    print(f"{'청산 규칙':<26}{'앞 19~21 알파':>14}{'뒤 22~26 알파':>14}"
          f"{'앞 10배+':>10}{'뒤 10배+':>10}")
    keep = [k for k in res if k in
            ("고정 52주 보유", "고정 104주 보유", "트레일 -30%", "트레일 -40%",
             "트레일 -50%", "진입가 대비 -20% 손절", "20주선 이탈 2주",
             "가속 꺼짐(ACC=0)", "가속 꺼짐 or 트레일-30%")]
    ok = np.array([V[i, j] == V[i, j] and V[i, j] > 0 for i, j in zip(gi, gj)])
    yv = yr[ok]
    for k in keep:
        T = res[k]
        a = T[(yv >= 2019) & (yv <= 2021)]
        b = T[yv >= 2022]
        print(f"{k:<26}{a.alpha.mean():>14.1%}{b.alpha.mean():>14.1%}"
              f"{(a.ret>=9).mean():>10.2%}{(b.ret>=9).mean():>10.2%}")


if __name__ == "__main__":
    main()
