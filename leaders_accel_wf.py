# -*- coding: utf-8 -*-
"""
이익 가속 규칙 워크포워드 검증 — results/leaders_accel_wf.json

왜 필요한가
  leaders_accel.py 의 성적(평균 +32.4% · 알파 +12.8%)은 **전 구간 인샘플**이다.
  8년을 다 보고 만든 규칙을 그 8년에 적용한 숫자라, "찾아낸 것"인지 "맞춘 것"인지
  구분이 안 된다. 특히 성과의 대부분을 2020(알파 +46.9%)과 2025(+35.9%) 두 해가
  만드는데, 그 둘을 빼면 시장을 못 이긴다.
  이전 L/S 규칙은 워크포워드에서 5분할 중 1개만 통과했다. 같은 잣대를 들이댄다.

두 가지를 잰다
  ⓐ 구간 안정성 — 파라미터를 고르지 않는다.
     이익가속 규칙은 튜닝할 게 사실상 없다(가속 문턱은 '> 0' 고정).
     각 TEST 구간에서 신호의 알파가 양수인지만 본다. 규칙이 시간에 걸쳐
     버티는지 보는 것이다.
  ⓑ 문턱 선택 워크포워드 — leaders_wf.py 가 청산 규칙에 쓰던 방식 그대로.
     TRAIN 구간에서 급등 문턱 5개(5/10/15/20/25%) 중 알파가 가장 높은 것을 고르고,
     그 선택을 TEST 1년에 그대로 적용한다.
     대조군: 아무것도 고르지 않고 **항상 +10%** 를 썼다면?
     고른 게 대조군보다 낫지 않으면, 그 최적화는 과거에만 맞춘 것이다.

⚠️ 이 검증도 완벽하지 않다
  · 유니버스에 상장폐지 종목이 없다. TRAIN·TEST 양쪽 다 낙관 편향이다.
  · 가속의 정의(영업익을 매출로 스케일)와 안전장치(매출 $10M·|가속| ≤ 10)는
    전 구간을 보고 정했다. 그 선택은 워크포워드 밖에 있다 —
    즉 여기서 통과해도 '완전한 아웃오브샘플'은 아니다.
  · TEST 구간의 신호 수가 적으면(수십 건) 알파가 몇 종목에 좌우된다.
    구간별 표본 수를 반드시 같이 본다.

CLI
  python leaders_accel_wf.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import leaders_accel as A

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "leaders_accel_wf.json")

SURGES = [5.0, 10.0, 15.0, 20.0, 25.0]     # 후보 급등 문턱
BASELINE = 10.0                            # 대조군 — 현재 채택값
HOLD = 52                                  # 성과 지평(주)

# TRAIN 2년 → TEST 1년, 1년씩 롤링.
# 마지막 구간은 TEST 의 52주 성과가 아직 안 나와서 넣지 않는다.
SPLITS = [
    ("2018-06-01", "2020-06-01", "2021-06-01"),
    ("2019-06-01", "2021-06-01", "2022-06-01"),
    ("2020-06-01", "2022-06-01", "2023-06-01"),
    ("2021-06-01", "2023-06-01", "2024-06-01"),
    ("2022-06-01", "2024-06-01", "2025-06-01"),
]


def _r(v, n=1):
    if v is None or v != v:
        return None
    return round(float(v), n)


def gate_at(M, surge):
    """leaders_accel.gate_of 와 같되 급등 문턱만 바꾼다."""
    return ((M["adv_20d"] >= A.MIN_ADV) & (M["marcap"] >= A.MIN_MC)
            & (M["ACC"] == 1) & (M["ret_1w"] >= surge)).fillna(False)


def window(mask_df, lo, hi):
    """[lo, hi) 주차만 남긴 마스크."""
    ix = mask_df.index
    keep = (ix >= pd.Timestamp(lo)) & (ix < pd.Timestamp(hi))
    return mask_df.where(pd.Series(keep, index=ix), other=False, axis=0)


def score(g, fwd, sfw):
    """그 구간 신호들의 (표본, 평균, 알파평균, 중앙알파, 2배+%)."""
    f = fwd.where(g).stack().dropna()
    a = fwd.where(g).sub(sfw, axis=0).stack().dropna()
    if len(a) < 5:
        return dict(n=int(len(a)), mean=None, alpha=None, med_alpha=None, w2=None)
    return dict(n=int(len(a)), mean=_r(f.mean() * 100), alpha=_r(a.mean() * 100),
                med_alpha=_r(a.median() * 100), w2=_r((f >= 1).mean() * 100))


def build():
    print("데이터 적재…", flush=True)
    d = A.load()
    COLS = ["close", "marcap", "adv_20d", "ret_1w", "ACC"]
    M = A.matrices(d, COLS)
    px = M["close"]
    fwd = px.shift(-HOLD) / px - 1

    spy_p = os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv")
    spy = pd.read_csv(spy_p, index_col=0, parse_dates=True).Close.reindex(px.index).ffill()
    sfw = spy.shift(-HOLD) / spy - 1

    gates = {s: gate_at(M, s) for s in SURGES}
    print(f"주차 {len(px)} · 문턱 {len(SURGES)}개 준비", flush=True)

    rows, picks = [], []
    for tr_lo, tr_hi, te_hi in SPLITS:
        # ── TRAIN: 문턱별 알파를 재고 최고를 고른다
        tr = {}
        for s in SURGES:
            tr[s] = score(window(gates[s], tr_lo, tr_hi), fwd, sfw)
        valid = {s: v for s, v in tr.items() if v["alpha"] is not None and v["n"] >= 30}
        pick = max(valid, key=lambda s: valid[s]["alpha"]) if valid else BASELINE

        # ── TEST: 고른 문턱과 대조군(항상 10%)을 같은 구간에 적용
        te_pick = score(window(gates[pick], tr_hi, te_hi), fwd, sfw)
        te_base = score(window(gates[BASELINE], tr_hi, te_hi), fwd, sfw)

        rows.append(dict(
            train=f"{tr_lo[:7]}~{tr_hi[:7]}", test=f"{tr_hi[:7]}~{te_hi[:7]}",
            pick=pick, train_alpha=tr[pick]["alpha"], train_n=tr[pick]["n"],
            test_n=te_pick["n"], test_alpha=te_pick["alpha"],
            test_mean=te_pick["mean"], test_med=te_pick["med_alpha"],
            test_w2=te_pick["w2"],
            base_n=te_base["n"], base_alpha=te_base["alpha"],
            base_mean=te_base["mean"], base_w2=te_base["w2"]))
        picks.append(pick)
        print(f"  {tr_hi[:7]}~{te_hi[:7]}  선택 +{pick:g}%  "
              f"TEST 알파 {te_pick['alpha']}  (대조 +10%: {te_base['alpha']})", flush=True)

    # ── 판정
    ok_alpha = sum(1 for r in rows if (r["test_alpha"] or -1) > 0)
    ok_vs_base = sum(1 for r in rows
                     if r["test_alpha"] is not None and r["base_alpha"] is not None
                     and r["test_alpha"] > r["base_alpha"])
    base_pos = sum(1 for r in rows if (r["base_alpha"] or -1) > 0)
    n = len(rows)

    out = dict(
        generated=str(pd.Timestamp.today().date()),
        hold_weeks=HOLD, baseline=BASELINE, surges=SURGES,
        splits=rows,
        verdict=dict(
            n_splits=n,
            alpha_positive=ok_alpha,          # TEST 알파가 양수인 분할 수
            base_positive=base_pos,           # 대조군(항상 10%)이 양수인 분할 수
            pick_beats_base=ok_vs_base,       # 고른 문턱이 대조군을 이긴 분할 수
            picks=picks))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print()
    print("═" * 72)
    print(f"ⓐ 구간 안정성 — 항상 +10% 를 썼을 때 TEST 알파가 양수인 분할: "
          f"{base_pos}/{n}")
    print(f"ⓑ 문턱 선택   — 고른 문턱이 대조군(+10%)을 이긴 분할: {ok_vs_base}/{n}")
    print(f"   선택된 문턱: {', '.join(f'+{p:g}%' for p in picks)}")
    print("═" * 72)
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
