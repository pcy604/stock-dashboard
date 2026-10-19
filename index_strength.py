# -*- coding: utf-8 -*-
"""
세계 주요 지수 강도판 (2026-10-19)

목적: "지금 어느 시장이 제일 강한가"를 한 화면에서 판단.
  · 기간별 수익률 히트맵 — 1일은 소음이라 빼고 1주·1개월·3개월·6개월·연초·1년
  · 52주 신고가 — '마지막 갱신 후 며칠'과 '최근 3개월에 몇 번 새로 썼나'
    (날짜 하나보다 '얼마나 자주 새로 쓰는가'가 강도를 더 정확히 보여준다)
  · 강도 순위 = 고점대비 거리 · 3개월 · 6개월 수익률의 순위 평균 (낮을수록 강함)

⚠️ 지수는 각국 통화 기준이다. 원·달러로 환산한 수익률이 아니다.
⚠️ 52주 신고가는 **종가 기준**이다(장중 고가 아님) — 증권사 앱 표기와 조금 다를 수 있다.
"""
import numpy as np
import pandas as pd

# (FDR 심볼, Yahoo 심볼, 이름, 지역)
INDICES = [
    ('US500', '^GSPC', 'S&P500', '미국'),
    ('IXIC', '^IXIC', '나스닥', '미국'),
    ('DJI', '^DJI', '다우', '미국'),
    ('RUT', '^RUT', '러셀2000', '미국'),
    ('KS11', '^KS11', '코스피', '한국'),
    ('KQ11', '^KQ11', '코스닥', '한국'),
    ('N225', '^N225', '닛케이225', '일본'),
    ('TWII', '^TWII', '대만 가권', '대만'),
    ('HSI', '^HSI', '항셍', '홍콩'),
    ('SSEC', '000001.SS', '상해종합', '중국'),
    (None, '^NSEI', '니프티50', '인도'),
    ('GDAXI', '^GDAXI', 'DAX', '독일'),
    (None, '^STOXX50E', '유로스톡스50', '유럽'),
    ('FTSE', '^FTSE', 'FTSE100', '영국'),
    (None, '^BVSP', '보베스파', '브라질'),
]

PERIODS = [('1주', 5), ('1개월', 21), ('3개월', 63), ('6개월', 126), ('연초 이후', 'ytd'), ('1년', 252)]


def metrics(close: pd.Series) -> dict | None:
    """종가 시계열 하나 → 강도 지표. 1년(252거래일) 미만이면 52주 지표는 비운다."""
    c = pd.to_numeric(close, errors='coerce').dropna()
    c = c[~c.index.duplicated(keep='last')].sort_index()
    if len(c) < 30:
        return None
    last = float(c.iloc[-1])
    out = {'last': last, 'asof': c.index[-1]}
    for lab, n in PERIODS:
        if n == 'ytd':
            prev = c[c.index < pd.Timestamp(c.index[-1].year, 1, 1)]
            out[lab] = (last / float(prev.iloc[-1]) - 1) * 100 if len(prev) else np.nan
        else:
            out[lab] = (last / float(c.iloc[-1 - n]) - 1) * 100 if len(c) > n else np.nan
    w = c.tail(252)
    full = len(c) >= 252
    hi = float(w.max())
    out['고점대비'] = (last / hi - 1) * 100 if full else np.nan
    # 52주 신고가 '갱신' = 그날 종가가 직전 251거래일 최고 종가를 넘은 날
    prev_hi = c.rolling(252, min_periods=252).max().shift(1)
    newhi = (c > prev_hi) & prev_hi.notna()
    days = newhi[newhi].index
    out['신고가일'] = days[-1] if len(days) else None
    out['신고가후'] = (c.index[-1] - days[-1]).days if len(days) else np.nan
    out['신고가3m'] = int(newhi.tail(63).sum()) if full else np.nan
    return out


def table(series: dict) -> pd.DataFrame:
    """{(이름, 지역): 종가 Series} → 강도 순으로 정렬된 표."""
    rows = []
    for (name, region), s in series.items():
        m = metrics(s) if s is not None else None
        if not m:
            continue
        rows.append({'지수': name, '지역': region, **{k: m[k] for k, _ in PERIODS},
                     '고점대비': m['고점대비'], '신고가후': m['신고가후'], '신고가3m': m['신고가3m'],
                     '신고가일': m['신고가일'], '기준일': m['asof']})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # 강도 순위 — 셋의 순위 평균. 결측은 꼴찌로(있는 척하지 않는다)
    rk = pd.concat([df['고점대비'].rank(ascending=False, na_option='bottom'),
                    df['3개월'].rank(ascending=False, na_option='bottom'),
                    df['6개월'].rank(ascending=False, na_option='bottom')], axis=1).mean(axis=1)
    df['강도순위'] = rk.rank(method='min').astype(int)
    return df.sort_values(['강도순위', '고점대비'], ascending=[True, False]).reset_index(drop=True)
