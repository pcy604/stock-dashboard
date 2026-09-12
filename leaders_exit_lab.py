# -*- coding: utf-8 -*-
"""
청산 규칙 실험실 — results/leaders_exit_lab.json

무엇을 재는가
  이익 가속 신호로 진입한 뒤 **언제 팔아야 하는가**. 후보 규칙을 하나씩 적용해
  "안 팔고 52주 들고 있기"와 비교한다. 기준은 셋이다.
    · 평균 수익 — 규칙을 쓰면 총액이 늘어나는가
    · 중앙값   — 전형적인 거래가 나아지는가
    · 최악 낙폭 — 견뎌야 하는 고통이 줄어드는가
  ⚠️ 셋이 서로 다른 답을 낼 수 있다. 낙폭은 줄지만 수익도 줄면 그건 취향의 문제지
     우열이 아니다 — 그럴 때는 그렇게 적는다.

지금까지 알아낸 것 (2026-08-25)
  고점 대비 트레일은 **측정한 모든 폭에서 안 파는 것보다 나빴다.** 좁을수록 더 나빴다.
  대박 종목이 중간에 -50% 를 겪고 다시 오르기 때문이다. 그래서 트레일은 후보에서 뺀다.
  이 실험의 초점은 **가격이 아니라 상태 변화**다 — 이익이 꺾였나, 추세가 깨졌나.

후보 규칙
  [기본적 분석]
    acc_off   이익 가속이 꺼진 분기 (진입 조건의 소멸)
    opm_pk    OPM 이 직전 고점 대비 X%p 하락
    oig_pk    이익 성장률이 직전 고점 대비 X%p 하락
  [기술적 분석]
    ma5       주봉 5주 이평 이탈
    ma20      주봉 20주 이평 이탈
    rsi_ex    RSI(14주) 과매수(70) 진입 후 다시 70 아래로
    macd_pk   MACD 히스토그램이 고점 찍고 음전
    dist_vol  고점 부근에서 거래량 급증 + 주간 음봉
  [대조군]
    none      안 판다(52주 보유)

⚠️ 한계
  · 주봉 종가 기준이다. 장중 이탈·회복은 안 보인다.
  · 청산 후 재진입은 없다고 본다. 실제로는 다시 신호가 뜨면 살 것이다.
  · 상장폐지 종목이 유니버스에 없어 모든 숫자가 낙관 쪽이다.
  · 표본이 규칙마다 다르다(조건이 한 번도 안 걸린 신호는 52주 만기 청산으로 처리).

CLI
  python leaders_exit_lab.py
"""
import json
import os
import sys

import numpy as np
import pandas as pd

import leaders_accel as A

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "leaders_exit_lab.json")
HOLD = 52                      # 최대 보유 주수(청산 신호가 없으면 여기서 판다)


def _r(v, n=1):
    if v is None or v != v:
        return None
    return round(float(v), n)


def rsi_weekly(px, n=14):
    """주봉 RSI. 종가 차분의 지수이동평균 방식."""
    d = px.diff()
    up = d.clip(lower=0)
    dn = (-d).clip(lower=0)
    au = up.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    ad = dn.ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    rs = au / ad.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd_hist(px, f=12, s=26, sig=9):
    """주봉 MACD 히스토그램."""
    ef = px.ewm(span=f, adjust=False).mean()
    es = px.ewm(span=s, adjust=False).mean()
    line = ef - es
    return line - line.ewm(span=sig, adjust=False).mean()


def build():
    print("데이터 적재…", flush=True)
    d = A.load()
    # ⚠️ A.load() 의 SQL 은 이 실험에 필요한 이평·거래량을 안 읽는다.
    #    같은 DB 에서 따로 붙인다 — 조인 키는 (as_of, sym).
    import sqlite3
    _c = sqlite3.connect(f"file:{os.path.join(BASE,'data','market.db')}?mode=ro", uri=True)
    _ex = pd.read_sql("SELECT as_of,sym,ma5,ma20,vol_x_20w FROM factor_weekly "
                      "WHERE factor_ver='v1'", _c)
    _c.close()
    _ex["as_of"] = pd.to_datetime(_ex.as_of)
    d = d.merge(_ex, on=["as_of", "sym"], how="left", suffixes=("", "_x"))
    COLS = ["close", "marcap", "adv_20d", "ret_1w", "ACC",
            "ma5", "ma20", "opm", "vol_x_20w", "dist_52w"]
    M = A.matrices(d, COLS)
    px = M["close"]
    g = A.gate_of(M)
    print(f"주차 {len(px)} · 신호 {int(g.sum().sum()):,}건", flush=True)

    # ── 청산 조건 매트릭스 (True = 그 주에 청산 신호) ──────────────
    print("청산 조건 계산…", flush=True)
    rsi = px.apply(rsi_weekly)
    mh = px.apply(macd_hist)
    opm = M["opm"]

    # ⚠️ 1차 측정(2026-09-11)에서 8개 후보가 **전부** 대조군에 졌다.
    #    원인은 조건이 너무 예민한 것이었다 — ma5 는 평균 4.6주, opm_pk 는 9.4주 만에
    #    팔았다. 이 규칙은 낙폭 한가운데서 사서 출렁이며 오르므로 한 번 스치는 이탈로
    #    털리면 안 된다. 문턱을 올리고 **연속 조건**을 넣어 다시 잰다.
    cond = {}
    below5 = px < M["ma5"]
    below20 = px < M["ma20"]
    cond["ma5"] = below5
    cond["ma20"] = below20
    cond["ma20_x2"] = below20 & below20.shift(1).fillna(False)
    cond["ma20_x3"] = (below20 & below20.shift(1).fillna(False)
                       & below20.shift(2).fillna(False))
    cond["ma20_dn"] = below20 & (M["ma20"] < M["ma20"].shift(4))

    cond["acc_off"] = (M["ACC"] == 0)
    _off = (M["ACC"] == 0)
    cond["acc_off2"] = _off & _off.shift(13).fillna(False)

    opm_run_max = opm.cummax()
    cond["opm_pk3"] = (opm_run_max - opm) >= 3.0
    cond["opm_pk10"] = (opm_run_max - opm) >= 10.0
    cond["opm_pk20"] = (opm_run_max - opm) >= 20.0

    _hot = rsi.shift(1) >= 70
    cond["rsi_ex"] = _hot & (rsi < 70)
    cond["rsi_50"] = (rsi.shift(1) >= 70) & (rsi < 50)
    cond["macd_pk"] = (mh.shift(1) > 0) & (mh <= 0)
    cond["dist_vol"] = ((M["dist_52w"] >= -10) & (M["vol_x_20w"] >= 2.0)
                        & (M["ret_1w"] < 0))
    cond["dd_ma20"] = (M["dist_52w"] <= -25) & below20


    spy = pd.read_csv(os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv"),
                      index_col=0, parse_dates=True).Close.reindex(px.index).ffill()

    idx = {t: i for i, t in enumerate(px.index)}
    sig = [(t, s) for t in g.index for s in g.columns if g.at[t, s]]
    print(f"평가 대상 {len(sig):,}건", flush=True)

    # ── 부분 매도 (2026-09-11 추가) ─────────────────────────────
    # ⚠️ 1·2차 측정에서 14개 전량매도 규칙이 **전부** 대조군에 졌다.
    #    문헌을 보니 원인이 설계에 있었다 — O'Neil·Minervini 는 전량이 아니라
    #    **일부**를 판다("sell portions at 20-30% gains", "trim into strength").
    #    전량 매도는 대박을 통째로 포기하므로 이 규칙과 상극이다.
    #    목표가에 닿으면 절반만 팔고 나머지는 52주까지 들고 간다.
    partial = {"trim25": 25.0, "trim50": 50.0, "trim100": 100.0}

    rules = ["none"] + list(cond) + [f"{k}_half" for k in partial]
    res = {k: [] for k in rules}          # (수익률, 알파, 보유주, 최저점)

    for t, s in sig:
        i0 = idx[t]
        if i0 + 1 >= len(px):
            continue
        ser = px[s].iloc[i0:i0 + HOLD + 1]
        if len(ser) < 2 or pd.isna(ser.iloc[0]):
            continue
        entry = float(ser.iloc[0])
        spy_ser = spy.iloc[i0:i0 + HOLD + 1]
        # 보유 중 최저점(진입가 대비) — 견뎌야 했던 폭
        run_min = float(ser.min() / entry - 1) * 100

        for rk in rules:
            if rk.endswith("_half"):
                # 목표가 도달 시 절반 매도, 나머지는 만기까지
                thr = partial[rk[:-5]]
                rel = (ser / entry - 1) * 100
                hit = np.flatnonzero((rel.iloc[1:] >= thr).to_numpy())
                jend = len(ser) - 1
                if len(hit):
                    jt = int(hit[0]) + 1
                    r1 = float(ser.iloc[jt] / entry - 1) * 100
                    r2 = float(ser.iloc[jend] / entry - 1) * 100
                    ret = 0.5 * r1 + 0.5 * r2
                    # 절반을 뺀 뒤의 낙폭은 그만큼 얕게 느껴진다
                    mn = 0.5 * r1 + 0.5 * float(ser.iloc[:jend + 1].min() / entry - 1) * 100
                    hold = jend
                else:
                    ret = float(ser.iloc[jend] / entry - 1) * 100
                    mn = float(ser.iloc[:jend + 1].min() / entry - 1) * 100
                    hold = jend
                sret = (float(spy_ser.iloc[jend]) / float(spy_ser.iloc[0]) - 1) * 100
                if np.isfinite(ret) and np.isfinite(mn) and np.isfinite(sret):
                    res[rk].append((ret, ret - sret, hold, mn))
                continue
            if rk == "none":
                j = len(ser) - 1
            else:
                c = cond[rk][s].iloc[i0 + 1:i0 + HOLD + 1]   # 진입 다음 주부터
                hit = np.flatnonzero(c.fillna(False).to_numpy())
                j = int(hit[0]) + 1 if len(hit) else len(ser) - 1
            j = min(j, len(ser) - 1)
            ex = float(ser.iloc[j])
            if not np.isfinite(ex) or entry <= 0:
                continue
            ret = (ex / entry - 1) * 100
            sret = (float(spy_ser.iloc[j]) / float(spy_ser.iloc[0]) - 1) * 100
            mn = float(ser.iloc[:j + 1].min() / entry - 1) * 100
            res[rk].append((ret, ret - sret, j, mn))

    rows = []
    base = None
    for rk in rules:
        v = res[rk]
        if len(v) < 100:
            continue
        a = np.array(v, dtype=float)
        a = a[np.isfinite(a).all(axis=1)]        # NaN 행 제거
        if len(a) < 100:
            continue
        row = dict(
            rule=rk, n=len(v),
            mean=_r(a[:, 0].mean()), median=_r(np.median(a[:, 0])),
            alpha=_r(a[:, 1].mean()),
            hold=_r(a[:, 2].mean()), worst=_r(np.median(a[:, 3])),
            w2=_r((a[:, 0] >= 100).mean() * 100), loss=_r((a[:, 0] < 0).mean() * 100))
        if rk == "none":
            base = row
        rows.append(row)
    for r in rows:
        r["d_mean"] = _r((r["mean"] or 0) - (base["mean"] or 0))
        r["d_worst"] = _r((r["worst"] or 0) - (base["worst"] or 0))

    out = dict(generated=str(pd.Timestamp.today().date()), hold=HOLD,
               rules=rows, base=base)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    print()
    print(f"{'규칙':<10}{'표본':>7}{'평균':>8}{'중앙':>8}{'알파':>8}"
          f"{'보유주':>7}{'최저(중앙)':>11}{'2배+':>7}{'손실':>7}  대조대비")
    for r in sorted(rows, key=lambda x: -(x["mean"] or -999)):
        mk = ("  ← 대조" if r["rule"] == "none"
              else (f"  {r['d_mean']:+.1f}%p" if r.get("d_mean") is not None else "  -"))
        _f = lambda k: (f"{r[k]:.1f}" if r.get(k) is not None else "-")
        print(f"{r['rule']:<12}{r['n']:>7,}{_f('mean'):>7}%{_f('median'):>7}%"
              f"{_f('alpha'):>7}%{_f('hold'):>7}{_f('worst'):>9}%"
              f"{_f('w2'):>6}%{_f('loss'):>6}%{mk}")
    print(f"\n→ {OUT}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(build())
