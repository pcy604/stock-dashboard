# -*- coding: utf-8 -*-
"""미국 시총·주식수 정합 (2026-11-08, 차니 "미국 퀀트 에러 느낌") — factor_weekly marcap = 수정주가 × '그 주에 알던 SEC 공시 주식수'.

발견(퀀트 패널 실측):
  · 주식수 기준이 가격과 어긋난다 — 수정주가는 오늘 기준(분할 반영)인데 공시 주식수는 공시가 날 때까지 옛 기준.
    TSLA 2022-08-29 시총 $281B(실제 ~$860B, 3:1 분할 직후) · GOOGL 2022-07 $73B·PER 1.0(실제 ~$1.4T, 20:1)
  · 역분할 초소형주는 과거 시총이 분할 배수만큼 부풀어 '$3억 이상'을 통과 — SLS 2017 시총 $35.5B(실제 ~$3천만)·RCAT $4.5B
  · 단위 오류(×1,000·÷1,000) — PRK·DIOD·SKY·RILY 등. 425종에서 1,348번의 주식수 급변.
  · ADR 은 보통주 수 × ADS 가격 → 배수만큼 부풀음(ONC 2022 $218B, 1 ADS = 13주).
방법(종목마다):
  ① 주식수 sh = 시총 ÷ 종가. 최신 쪽에서 과거로 가며 한 주 사이 1.8배 넘게 뛰면 '기준이 바뀐 것'으로 보고 이어 붙인다
     (실제 주식수는 한 주에 1.8배 안 바뀐다 — 대형 주식 교환 합병만 예외, 드묾).
  ② 최신 수준은 data/us_marketcap.csv(companiesmarketcap 실제 시총 ÷ 가격 = ADS 기준 주식수)와 1.8배 넘게 어긋나면 그쪽에 맞춘다.
  ③ 시총이 빈 주는 앞뒤 주식수로 채운다(PLTR 이 2021-11 전 시총 NULL 로 패널에서 빠져 있던 것).
  ④ PER·PBR·PSR 은 시총 비례라 같은 배수로 고친다.
  ⑤ 그래도 남는 엉터리(RPAY 시총 $3,800억 = SEC 주식수 단위 ×1,000, ONC ADR ×13 — 기준 csv 자체가 같은 원천이라 ②로 못 잡음)는
     **회전율**로 가린다: 주간 거래대금 ÷ 시총의 직전 26주 중앙이 0.1% 미만(미국 종목 중앙 약 5%, 하위 1% = 0.1%)이면
     그 주 시총·PER·PBR·PSR 을 비운다('-'). 시점 기준(과거 26주만) — 미래 정보 없음. 장외 껍데기 종목도 같이 빠진다.
"""
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
JUMP = np.log(1.8)


def _anchor():
    try:
        m = pd.read_csv(os.path.join(ROOT, "data", "us_marketcap.csv"))
        m = m[(m.marketcap > 0) & (m["price (USD)"] > 0)]
        return dict(zip(m.Symbol.astype(str), m.marketcap / m["price (USD)"]))
    except Exception:
        return {}


def fix(d: pd.DataFrame, sym="sym", date="date", close="close", cap="marcap", ratios=("per", "pbr", "psr"),
        dollar_vol: str = None, min_turnover: float = 0.001) -> pd.DataFrame:
    """long 표(종목·주) → marcap(+ 비율 열)을 고친 새 표. 열 _capfix = 곱한 배수(1 = 그대로)."""
    d = d.sort_values([sym, date]).copy()
    anc = _anchor()
    sh = (d[cap] / d[close]).where((d[cap] > 0) & (d[close] > 0))
    out = np.empty(len(d))
    pos = 0
    for s, g in sh.groupby(d[sym], sort=False):
        v = g.values.astype(float)
        n = len(v)
        okx = np.where(np.isfinite(v))[0]
        if not len(okx):
            out[pos:pos + n] = np.nan
            pos += n
            continue
        c = v.copy()
        last = okx[-1]
        # ① 최신 → 과거 체인
        ref, mult = v[last], 1.0
        for i in range(last - 1, -1, -1):
            if not np.isfinite(v[i]):
                continue
            if abs(np.log(v[i] * mult / ref)) > JUMP:        # 기준이 바뀐 지점 → 이 구간 전체에 곱할 배수를 새로
                mult = ref / v[i]
            c[i] = v[i] * mult
            ref = c[i]
        # ② 최신 수준 앵커
        a = anc.get(str(s))
        if a and np.isfinite(a) and a > 0:
            k = a / c[last]
            if abs(np.log(k)) > JUMP:
                c = c * k
        # ③ 빈 주 채우기(앞뒤)
        c = pd.Series(c).ffill().bfill().values
        out[pos:pos + n] = c
        pos += n
    d["_sh"] = out
    newcap = d[close] * d["_sh"]
    k = (newcap / d[cap]).where(d[cap] > 0)
    for r in ratios:
        if r in d.columns:
            d[r] = d[r] * k.fillna(1.0)
    d["_capfix"] = k.fillna(1.0)
    d[cap] = newcap.where(newcap.notna(), d[cap])
    # ⑤ 회전율 가림
    dv = d[dollar_vol] if dollar_vol else (d[close] * d["volume"] if "volume" in d.columns else None)
    if dv is not None:
        to = (dv / d[cap]).where(d[cap] > 0)
        med = to.groupby(d[sym], sort=False).transform(lambda x: x.rolling(26, min_periods=8).median())
        bad = med < min_turnover
        d["_capbad"] = bad.fillna(False)
        for c in (cap,) + tuple(r for r in ratios if r in d.columns):
            d.loc[bad.fillna(False), c] = np.nan
    return d.drop(columns=["_sh"])
