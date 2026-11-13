# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd

import analysis_v2 as A


def test_high52_close_basis_and_date():
    idx = pd.bdate_range('2025-01-01', periods=300)
    c = pd.Series(np.linspace(100, 200, 300), idx)
    c.iloc[250] = 260
    h = A.high52(c)
    assert h['high'] == 260 and str(h['date']) == str(idx[250].date())
    assert abs(h['dd'] - (200 / 260 - 1) * 100) < 1e-9


def test_group_heat_and_quadrant():
    base = pd.DataFrame({'RS': [95, 90, 85, 20, 10, 15, 50], '시장': ['KR'] * 7},
                        index=['a', 'b', 'c', 'd', 'e', 'f', 'g'])
    gh = A.group_heat(base, {'hot': ['a', 'b', 'c'], 'cold': ['d', 'e', 'f'], 'tiny': ['g']}, market='KR')
    assert list(gh['group']) == ['hot', 'cold']          # tiny(1종)는 빠진다
    assert A.flow_quadrant(10, 90)['tone'] == 'good'
    assert A.flow_quadrant(10, 30)['label'].startswith('업종 강세')
    assert A.flow_quadrant(80, 90)['label'].startswith('종목 단독 강세')
    assert A.flow_quadrant(80, 10)['tone'] == 'bad'
    assert A.flow_quadrant(10, None)['tone'] == 'na'


def test_forward_us_upgrade_vs_downgrade():
    tr = pd.DataFrame({'current': [5.0, 8.0], '90daysAgo': [4.0, 6.0]}, index=['0y', '+1y'])
    rv = pd.DataFrame({'upLast30days': [10, 8], 'downLast30days': [1, 0]}, index=['0y', '+1y'])
    f = A.forward_us(tr, rv)
    assert f['tone'] == 'good' and f['growth'] > 50 and f['net30'] == 17
    tr2 = pd.DataFrame({'current': [3.0, 3.2], '90daysAgo': [4.0, 4.5]}, index=['0y', '+1y'])
    assert A.forward_us(tr2, None)['tone'] == 'bad'
    assert A.forward_us(None, None)['tone'] == 'na'


def test_forward_kr_short_history_is_honest():
    f = A.forward_kr([{'date': '2026-11-01', 'op_0y': 100, 'op_1y': 150}])
    assert f['growth'] == 50 and f['rev'] is None and '축적 중' in f['sub']
    f2 = A.forward_kr([{'date': '2026-10-01', 'op_0y': 100, 'op_1y': 150}, {'date': '2026-11-01', 'op_0y': 100, 'op_1y': 120}])
    assert f2['rev'] < 0


def test_cycle_position_memory_like_trough_recovering():
    # 사이클: 영업이익률이 30% ↔ −10% 로 출렁이다 바닥에서 올라오는 중
    idx = pd.period_range('2014Q1', periods=48, freq='Q').to_timestamp(how='end').normalize()
    rev = pd.Series(100.0, idx)
    opm = 10 + 20 * np.sin(np.arange(48) / 3.0)
    opm[-6:] = [-15, -18, -16, -10, -4, 2]
    q = pd.DataFrame({'revenue': rev, 'op_income': rev * opm / 100})
    c = A.cycle_position(q)
    assert c['cyclical'] is True and c['pct'] <= 30 and c['rising'] and c['tone'] == 'good'


def test_cycle_position_stable_company():
    idx = pd.period_range('2016Q1', periods=40, freq='Q').to_timestamp(how='end').normalize()
    rev = pd.Series(np.linspace(100, 200, 40), idx)
    q = pd.DataFrame({'revenue': rev, 'op_income': rev * (0.20 + np.linspace(0, 0.02, 40))})
    c = A.cycle_position(q)
    assert c['cyclical'] is False and c['value'].startswith('안정형')


def test_valuation_reading():
    assert A.valuation_reading(10, 0.5, 0.6, False)['tone'] == 'good'
    assert A.valuation_reading(90, 3.0, 1.5, False)['tone'] == 'bad'
    assert A.valuation_reading(None, None, None, False)['tone'] == 'na'
    assert A.valuation_reading(10, 0.5, 0.6, True)['tone'] == 'na'
