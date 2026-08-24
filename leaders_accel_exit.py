# -*- coding: utf-8 -*-
"""
이익 가속 규칙의 탈출 타이밍 — 현행 진입 규칙으로 다시

앞선 leaders_uturn2~4 · leaders_exit* 는 **구 규칙 L/S** 위에서 돌렸다. L/S 는
leaders_accel.py 문서가 적어놓은 대로 TSLA 0회 · NVDA 0회 · WDC 0회로 시대의
주도주를 못 잡는 규칙이다. 현행 규칙(이익 가속)으로 전부 다시 잰다.

이 규칙은 진입 성격이 다르다 — 급등 문턱이 +10% 로 낮고, 진입 시점이 신고가가
아니라 **낙폭 한가운데**인 경우가 많다(TSLA 진입 시 고점대비 −38%, NVDA −66%).
그래서 두 가지를 같이 잰다.
  · 진입 후 고점 대비 트레일 (기존과 동일 축)
  · **진입가 대비 손절** — 진입이 고점이 아니므로 이쪽이 더 자연스러울 수 있다

그리고 이 규칙에는 구조적으로 맞는 청산 후보가 있다:
  **진입 논리가 '가속'이면 청산 논리는 '감속'이다.** ACC 플래그가 꺼지는 주
  (rv_a>0 & oi_a>0 이 깨지는 분기 공시)에 나가는 규칙을 건다. 격자에서 주운 게
  아니라 진입 가설의 부정이라, 04절의 채택 기준(구조적 이유)을 통과할 자격이 있다.

⚠️ 6칸 등가중 포트폴리오는 이 규칙의 실제 용법이 아니다(문서: "신호 목록이지
   포트폴리오 규칙이 아니다", 평균 74종). 그래서 **트레이드 층위를 1차 지표로**
   보고 포트폴리오는 참고로만 싣는다.
"""
import os, sys
import numpy as np
import pandas as pd
import leaders_accel as AC
import leaders_uturn2 as U2
import leaders_uturn3 as U3
import leaders_exit as X

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
pd.set_option("display.width", 280, "display.max_columns", 60)
ACOLS = ["ACC", "oi_a", "rv_a", "dgpm", "dopm"]


def accel_panel():
    """현행 가속 규칙의 게이트 + 가속 팩터를, 기존 판넬 좌표계에 맞춰 얹는다."""
    M, spy = U2.panel()
    px = M["close"]
    d = AC.load()
    cols = ["close", "adv_20d", "marcap", "ret_1w"] + ACOLS
    A = AC.matrices(d, cols)
    gate = AC.gate_of(A).reindex(index=px.index, columns=px.columns).fillna(False)
    extra = {k: A[k].reindex(index=px.index, columns=px.columns) for k in ACOLS}
    return M, spy, gate, extra


def main():
    M, spy, gate, extra = accel_panel()
    px = M["close"]
    print(f"[가속 규칙] 판넬 {px.shape[0]}주 × {px.shape[1]}종 · 신호 {int(gate.sum().sum())}건 "
          f"· 신호 있는 주 {int((gate.sum(axis=1) > 0).sum())}")

    # ── ① 진입 시점의 성격: 이 규칙은 어디서 사는가 ──
    gi, gj = np.where(gate.values)
    dist = M["dist_52w"].values[gi, gj]
    print(f"  진입 시점 52주 신고가와의 거리: 중앙 {np.nanmedian(dist):.1f}% · "
          f"신고가 −20% 밖에서 사는 비율 {np.nanmean(dist < -20):.0%}")

    # ── ② 낙폭 문턱 스윕 ──
    print("\n── 판단의 순간: 진입 후 고점 대비 문턱을 처음 깬 뒤 ──")
    print(f"{'문턱':>6}{'n':>7}{'52주중앙':>10}{'평균':>9}{'음수':>7}{'고점회복':>9}"
          f"{'이후최대낙폭':>13}{'26주중앙':>10}")
    store = {}
    for tg in (0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50):
        E = U2.collect(M, spy, "ACC", trig=tg, gate=gate, extra=extra)
        store[tg] = E
        e = E.dropna(subset=["fwd52"])
        print(f"{tg:>5.0%}{len(e):>7}{e.fwd52.median():>+10.1%}{e.fwd52.mean():>+9.1%}"
              f"{(e.fwd52 < 0).mean():>7.0%}{e.rec52.mean():>9.0%}"
              f"{e.min52.median():>+13.1%}{e.fwd26.median():>+10.1%}")
    E20 = store[0.20].dropna(subset=["fwd52"])
    E20.to_parquet(os.path.join(BASE, "data", "_accel_dec.parquet"))

    # ── ③ 반응곡선 (가속 팩터 포함) ──
    U3.FEATS = U3.FEATS + [("oi_a", "이익 가속(그 시점)"), ("rv_a", "매출 가속"),
                           ("dopm", "OPM 전분기비"), ("dgpm", "GPM 전분기비")]
    U3.curves(E20, "이익 가속 규칙 · 고점대비 -20% 이탈 시점")

    # ── ④ 가속이 꺼졌는가 ──
    print("\n── ACC(가속) 플래그로 가른 판단의 순간 ──")
    for v, lab in ((1, "판단 시점에 여전히 가속 중"), (0, "가속 꺼짐(감속 전환)")):
        e = E20[E20.ACC == v]
        if len(e) < 20:
            continue
        print(f"  {lab:<22} n={len(e):>4}  52주 중앙 {e.fwd52.median():>+7.1%} · "
              f"평균 {e.fwd52.mean():>+7.1%} · 음수 {(e.fwd52<0).mean():.0%} · "
              f"고점회복 {e.rec52.mean():.0%}")


if __name__ == "__main__":
    main()
