"""종목분석 탭 '📆 월별 상승률 통계 (연도 × 월)' 표 데이터 (2026-10-20 분리).

- RAW: 연도 오래된 순 → 최신 순(위→아래로 시간이 흐른다). 칸 = 그 달 수익률(%), 연간 = 연말 대비(올해는 YTD).
- 요약: 전체 / 홀수해 / 짝수해 각각 평균·승률. 연간 열도 같은 방식(연간 승률 = 오른 해의 비율).
  RAW 와 표를 나눈다 — 열 정렬을 눌러도 요약 행이 연도 사이로 섞여 들어가지 않게.
"""
from __future__ import annotations

import pandas as pd

MONTHS = [f'{m}월' for m in range(1, 13)]
COLS = MONTHS + ['연간']
GROUPS = (('전체', None), ('홀수해', 1), ('짝수해', 0))


def build(close: pd.Series, max_years: int = 35):
    """일봉 종가 → (raw, summary). 표본 부족(월 12개 미만)이면 (None, None)."""
    close = close.dropna()
    mret = (close.resample('ME').last().pct_change() * 100).dropna()
    if len(mret) < 12:
        return None, None
    yret = (close.resample('YE').last().pct_change() * 100)
    yret.index = yret.index.year
    pv = (mret.to_frame('r').assign(y=mret.index.year, m=mret.index.month)
          .pivot_table(index='y', columns='m', values='r', aggfunc='first')
          .reindex(columns=range(1, 13)))
    pv.columns = MONTHS
    pv['연간'] = yret.reindex(pv.index)
    pv = pv.sort_index().iloc[-max_years:]          # 오래된 순 → 최신 순

    raw = pv.reset_index().rename(columns={'y': '연도'})
    raw['연도'] = raw['연도'].astype(int).astype(str)

    rows = []
    for name, par in GROUPS:
        sub = pv if par is None else pv[pv.index % 2 == par]
        avg = {'구분': f'{name} 평균'}
        win = {'구분': f'{name} 승률'}
        for c in COLS:
            s = sub[c].dropna()
            avg[c] = float(s.mean()) if len(s) else None
            win[c] = float((s > 0).mean() * 100) if len(s) else None
        rows += [avg, win]
    summary = pd.DataFrame(rows, columns=['구분'] + COLS)
    return raw, summary
