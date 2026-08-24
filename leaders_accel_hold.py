# -*- coding: utf-8 -*-
"""
얼마나 오래 자리를 내줘야 하나 — 보유기간 연구 (2026-08-25, 사용자 질문)

  "보통 주도주는 자리를 몇 달이나 가져가나. 한 번 진입하면 최소 몇 달은 끌고 가는 게 맞나."

세 갈래로 잰다.
  ① 사후 주도주(+150% 런)의 저점→정점 소요 기간 — '자리를 얼마나 오래 차지하나'
  ② 이익 가속 신호 진입 후 최고가까지 걸린 기간 — 실제 규칙에서의 숙성 시간
  ③ **최소 보유기간(N주 전에는 안 판다) 스윕** — 질문에 대한 직접적 답
     · 고정 N주 보유
     · N주 바닥 + 그 뒤 고점 −30% 트레일  ← 트레일이 최소보유로 구제되는지
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_accel_exit as AE

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 300)
FEE, HMAX = 0.001, 104
W2M = 12 / 52.0          # 주 → 개월


def main():
    M, spy, gate, extra = AE.accel_panel()
    px = M["close"]
    V = px.values
    SPY = spy.reindex(px.index).ffill().values
    gi, gj = np.where(gate.values)

    # ── ① 사후 주도주 런의 지속 기간 ──
    cp = os.path.join(BASE, "data", "_uturn_cases_inv.parquet")
    if os.path.exists(cp):
        C = pd.read_parquet(cp)
        w = C["주수"]
        print(f"── ① +150% 런의 저점→정점 소요 (투자가능 런 {len(C)}개) ──")
        for q, lab in ((.25, "하위25%"), (.5, "중앙"), (.75, "상위25%"), (.9, "상위10%")):
            v = w.quantile(q)
            print(f"   {lab:<8} {v:>5.0f}주  ({v*W2M:>4.1f}개월)")
        print(f"   6개월(26주) 안에 정점 찍은 런: {(w <= 26).mean():.0%} · "
              f"1년(52주) 안: {(w <= 52).mean():.0%} · 2년 이상: {(w >= 104).mean():.0%}")

    # ── ② 신호 진입 후 최고가까지 ──
    tomax, gains = [], []
    for i0, jc in zip(gi, gj):
        e = V[i0, jc]
        if not (e == e and e > 0):
            continue
        seg = V[i0 + 1:min(len(V), i0 + HMAX + 1), jc]
        if not len(seg) or np.all(np.isnan(seg)):
            continue
        k = int(np.nanargmax(seg))
        tomax.append(k + 1)
        gains.append(np.nanmax(seg) / e - 1)
    T = pd.Series(tomax)
    G = pd.Series(gains)
    print(f"\n── ② 이익 가속 신호 진입 → 최고가까지 (n={len(T):,}, 104주 관측) ──")
    for q, lab in ((.25, "하위25%"), (.5, "중앙"), (.75, "상위25%")):
        print(f"   {lab:<8} {T.quantile(q):>5.0f}주  ({T.quantile(q)*W2M:>4.1f}개월)")
    print(f"   3개월(13주) 안에 최고가: {(T <= 13).mean():.0%} · "
          f"6개월 안: {(T <= 26).mean():.0%} · 1년 넘어서: {(T > 52).mean():.0%}")
    big = T[G >= 1.0]
    print(f"   ⭐ 2배 이상 간 트레이드({len(big):,}건)만: 최고가까지 중앙 "
          f"{big.median():.0f}주({big.median()*W2M:.1f}개월) · "
          f"6개월 안에 끝난 비율 {(big <= 26).mean():.0%}")

    # ── ③ 최소 보유기간 스윕 ──
    def sim(min_wk, trail=None):
        out = []
        for i0, jc in zip(gi, gj):
            e = V[i0, jc]
            if not (e == e and e > 0):
                continue
            peak, px_, k_end = e, e, None
            for k in range(i0 + 1, min(len(V), i0 + HMAX + 1)):
                v = V[k, jc]
                if v != v:
                    continue
                peak = max(peak, v)
                px_ = v
                if k - i0 < min_wk:
                    continue
                if trail is None or v <= peak * (1 - trail):
                    k_end = k
                    break
            if k_end is None:
                k_end = min(len(V) - 1, i0 + HMAX)
                col = V[i0:k_end + 1, jc]
                col = col[~np.isnan(col)]
                px_ = col[-1] if len(col) else e
            r = px_ / e * (1 - FEE) ** 2 - 1
            s0, s1 = SPY[i0], SPY[min(k_end, len(V) - 1)]
            out.append((r, r - (s1 / s0 - 1), k_end - i0))
        return pd.DataFrame(out, columns=["ret", "alpha", "wk"])

    print(f"\n── ③ 최소 보유기간 — '언제까지는 안 판다' ──")
    print(f"{'규칙':<26}{'평균':>9}{'알파':>9}{'중앙':>9}{'2배+':>8}{'10배+':>8}{'보유':>7}")
    rows = []
    for n in (4, 13, 26, 39, 52, 78, 104):
        t = sim(n, None)
        rows.append((f"{n}주 딱 채우고 매도", t))
    for n in (0, 13, 26, 39, 52):
        t = sim(n, 0.30)
        lab = "고점 −30% 트레일만" if n == 0 else f"{n}주 버틴 뒤 −30% 트레일"
        rows.append((lab, t))
    for lab, t in rows:
        print(f"{lab:<26}{t.ret.mean():>9.1%}{t.alpha.mean():>9.1%}{t.ret.median():>9.1%}"
              f"{(t.ret >= 1).mean():>8.1%}{(t.ret >= 9).mean():>8.2%}{t.wk.mean():>7.0f}")


if __name__ == "__main__":
    main()
