"""오닐(IBD) 방식 시장 방향 — 분배일 · 반등 시도 · 팔로스루 데이. 2026-11-12 종합 진단(오닐 70점의 감점 사유).

⚠️ 참고 지표다. 실전 규칙(v1.9 지수 게이트 = 주봉 5주선)과 별개이고 이 저장소에서 백테스트하지 않았다.
규칙(IBD 공개 설명 기준, 숫자는 아래 상수):
  · 분배일: 종가 −0.2% 이하 하락 + 거래량이 전일보다 많음. 25거래일이 지나거나, 그날 종가보다 지수가 5% 이상
    오르면 지운다.
  · 조정: 최근 60거래일 최저 종가가 그 전 52주 고점보다 7% 이상 아래면 '조정이 있었다'.
  · 반등 시도: 그 최저일 다음 거래일부터 센다(최저일 = 0일). 최저 종가를 다시 깨면 시도 실패 → 그날이 새 최저.
  · 팔로스루 데이: 시도 4일째 이후, 종가 +1.25% 이상 + 거래량이 전일보다 많음.
상태: '상승 추세'(조정 없음) / '상승 확인'(팔로스루 뒤) / '압력 받는 상승'(위 둘 + 분배일 5개 이상) /
      '반등 시도 n일째' / '조정 중'(오늘이 최저).
"""
from __future__ import annotations

import pandas as pd

DIST_DROP = -0.2          # %
DIST_WINDOW = 25          # 거래일
DIST_EXPIRE_UP = 5.0      # %
CORR_DD = 7.0             # %
LOW_LOOKBACK = 60         # 거래일
FTD_MIN_DAY = 4
FTD_GAIN = 1.25           # %
PRESSURE_N = 5


def distribution_days(close: pd.Series, vol: pd.Series) -> list[pd.Timestamp]:
    ret = close.pct_change() * 100
    up_vol = vol > vol.shift(1)
    idx = list(close.index[-DIST_WINDOW:])
    out = []
    for d in idx:
        if ret.get(d) is not None and ret[d] <= DIST_DROP and bool(up_vol.get(d)):
            after = close[close.index > d]
            if len(after) and (after.max() / close[d] - 1) * 100 >= DIST_EXPIRE_UP:
                continue
            out.append(d)
    return out


def pulse(close: pd.Series, vol: pd.Series) -> dict:
    close, vol = close.dropna(), vol.reindex(close.index)
    if len(close) < 80 or vol.isna().all() or (vol.fillna(0) == 0).all():
        return {}
    dist = distribution_days(close, vol)
    look = close.iloc[-LOW_LOOKBACK:]
    low_d = look.idxmin()
    low = float(look.min())
    prior_high = float(close[:low_d].iloc[-252:].max())
    dd = (low / prior_high - 1) * 100
    hi_now = float(close.iloc[-252:].max())
    out = dict(asof=str(close.index[-1].date()), close=round(float(close.iloc[-1]), 2),
               dist_n=len(dist), dist_dates=[str(d.date()) for d in dist],
               from_high=round((float(close.iloc[-1]) / hi_now - 1) * 100, 2))
    if dd > -CORR_DD:
        state = '상승 추세'
        out.update(state=state)
    else:
        after = close[close.index > low_d]
        ret = close.pct_change() * 100
        ftd = None
        for i, d in enumerate(after.index, start=1):
            if i >= FTD_MIN_DAY and ret[d] >= FTD_GAIN and vol[d] > vol.shift(1)[d]:
                ftd = d
                break
        out.update(low=round(low, 2), low_date=str(low_d.date()), corr_dd=round(dd, 2),
                   rally_day=len(after), ftd_date=str(ftd.date()) if ftd is not None else None)
        if len(after) == 0:
            state = '조정 중'
        elif ftd is not None:
            state = '상승 확인'
            # 팔로스루 이후 분배일만 압력으로 센다
            out['dist_n'] = len([d for d in dist if d > ftd])
        else:
            state = f'반등 시도 {len(after)}일째'
        out['state'] = state
    if out['state'] in ('상승 추세', '상승 확인') and out['dist_n'] >= PRESSURE_N:
        out['state'] = '압력 받는 상승'
    return out
