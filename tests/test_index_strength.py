"""index_strength — 세계 지수 강도판 (2026-10-19)"""
import numpy as np
import pandas as pd

import index_strength as I


def _s(vals, start='2025-01-01'):
    return pd.Series(vals, index=pd.bdate_range(start, periods=len(vals)), dtype=float)


def test_new_high_counting_and_days_since():
    # 300일 상승 후 마지막 20일 하락 → 마지막 신고가는 하락 직전
    v = list(np.linspace(100, 200, 300)) + list(np.linspace(199, 180, 20))
    m = I.metrics(_s(v))
    assert m['신고가일'] == _s(v).index[299]
    assert m['신고가후'] > 0
    assert m['고점대비'] < 0
    assert m['신고가3m'] == 43            # 63일 창 중 하락 전 43일이 매일 신고가


def test_short_history_leaves_52w_blank():
    m = I.metrics(_s(np.linspace(100, 110, 100)))
    assert np.isnan(m['고점대비']) and np.isnan(m['신고가3m'])
    assert m['신고가일'] is None                     # 1년 이력이 없으면 '신고가'를 말하지 않는다


def test_table_ranks_strongest_first():
    up = _s(np.linspace(100, 200, 300))
    down = _s(np.linspace(200, 100, 300))
    df = I.table({('강세', 'A'): up, ('약세', 'B'): down, ('없음', 'C'): None})
    assert list(df['지수']) == ['강세', '약세']
    assert df['강도순위'].tolist() == [1, 2]
    assert df.loc[0, '고점대비'] == 0
