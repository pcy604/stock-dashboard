# -*- coding: utf-8 -*-
"""
진입 시점 분석 — 신호가 뜬 주에 바로 사는가, 몇 주 기다리는가

results/leaders_accel_entry.json

묻는 것 (형 질문, 2026-09-09)
  "주간 기준으로 신호 발생한 종목을 차주에 바로 사는 게 나은지,
   아니면 X주 이후에 사는 게 나은지"

두 가지를 따로 잰다 — 섞으면 답이 안 나온다
  ⓐ 진입 시점 기준 수익 : t+k 주 종가에 사서 그로부터 52주.
     "지금 사는 것과 k주 뒤에 사는 것 중 뭐가 나은가"에 대한 답이다.
     늦게 살수록 진입가가 달라지므로 분모가 바뀐다.
  ⓑ 신호 시점 기준 수익 : 신호 주 종가부터 t+k+52 주까지 통째로.
     기다리는 동안 놓친 구간까지 포함한 값이다.
     ⓐ가 좋아도 ⓑ가 나쁘면 "기다리는 사이에 이미 다 올랐다"는 뜻이다.

  ⓐ만 보면 "늦게 살수록 좋다"는 착시가 생기기 쉽다 — 급등 직후 눌린 가격에
  사는 셈이라 분모가 낮아지기 때문이다. ⓑ를 같이 봐야 실제로 돈이 되는지 안다.

⚠️ 한계
  · 지연 진입은 **그 종목이 그때까지 살아 있어야** 성립한다. 상장폐지 종목이
    유니버스에 없으므로 지연이 길수록 생존 편향이 커진다.
  · k 주 안에 다시 신호가 뜨면 중복 계산된다(같은 종목을 여러 번 센다).
    실제 운용에서는 한 번만 사겠지만, 여기서는 신호 단위로 잰다.
  · 52주 지평이 안 찬 최근 신호는 자동으로 빠진다 — k 가 클수록 표본이 준다.

CLI
  python leaders_accel_entry.py
"""
import json
import os
import sys

import pandas as pd

import leaders_accel as A

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "leaders_accel_entry.json")

DELAYS = [0, 1, 2, 3, 4, 6, 8, 13]     # 신호 주 종가 기준 지연(주)
HOLD = 52                              # 보유 지평(주)


def _r(v, n=1):
    if v is None or v != v:
        return None
    return round(float(v), n)


def build():
    print("데이터 적재…", flush=True)
    d = A.load()
    M = A.matrices(d, ["close", "marcap", "adv_20d", "ret_1w", "ACC"])
    px = M["close"]
    g = A.gate_of(M)

    spy_p = os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv")
    spy = pd.read_csv(spy_p, index_col=0, parse_dates=True).Close.reindex(px.index).ffill()

    rows = []
    for k in DELAYS:
        # ⓐ 진입 시점 기준 — t+k 에 사서 52주
        entry = px.shift(-k)                       # 신호 주에서 본 t+k 종가
        exit_a = px.shift(-(k + HOLD))
        fwd_a = exit_a / entry - 1
        s_entry = spy.shift(-k)
        s_exit = spy.shift(-(k + HOLD))
        sfw_a = s_exit / s_entry - 1

        # ⓑ 신호 시점 기준 — 신호 주 종가부터 t+k+52 까지 통째로
        fwd_b = px.shift(-(k + HOLD)) / px - 1
        sfw_b = spy.shift(-(k + HOLD)) / spy - 1

        a = fwd_a.where(g).sub(sfw_a, axis=0).stack().dropna()
        f = fwd_a.where(g).stack().dropna()
        b = fwd_b.where(g).sub(sfw_b, axis=0).stack().dropna()
        fb = fwd_b.where(g).stack().dropna()
        if len(a) < 30:
            continue
        rows.append(dict(
            k=k, n=int(len(a)),
            a_mean=_r(f.mean() * 100), a_alpha=_r(a.mean() * 100),
            a_med=_r(f.median() * 100), a_w2=_r((f >= 1).mean() * 100),
            a_w10=_r((f >= 9).mean() * 100, 2),
            b_mean=_r(fb.mean() * 100), b_alpha=_r(b.mean() * 100),
            b_med=_r(fb.median() * 100), b_w2=_r((fb >= 1).mean() * 100)))
        print(f"  +{k:>2}주  표본 {len(a):>5}  진입기준 알파 {rows[-1]['a_alpha']:>6}  "
              f"신호기준 알파 {rows[-1]['b_alpha']:>6}", flush=True)

    if not rows:
        print("[ERROR] 표본이 없다.")
        return 1

    base = next(r for r in rows if r["k"] == 0)
    best_a = max(rows, key=lambda r: r["a_alpha"] or -999)
    best_b = max(rows, key=lambda r: r["b_alpha"] or -999)
    out = dict(generated=str(pd.Timestamp.today().date()),
               hold_weeks=HOLD, delays=DELAYS, rows=rows,
               verdict=dict(base_k=0, base_alpha=base["a_alpha"],
                            best_entry_k=best_a["k"], best_entry_alpha=best_a["a_alpha"],
                            best_total_k=best_b["k"], best_total_alpha=best_b["b_alpha"]))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print()
    print(f"진입 시점 기준 최고: +{best_a['k']}주 (알파 {best_a['a_alpha']}%) "
          f"· 바로 사기(+0주)는 {base['a_alpha']}%")
    print(f"신호 시점 기준 최고: +{best_b['k']}주 (알파 {best_b['b_alpha']}%)")
    print(f"→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
