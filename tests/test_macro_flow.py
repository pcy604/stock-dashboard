# -*- coding: utf-8 -*-
"""매크로 두 축(macro_flow) 판정 규칙 고정 — 네트워크 없이 합성 시계열로 검사한다."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import macro_flow as mf


def _line(n, start, end, freq='B'):
    idx = pd.date_range('2024-01-01', periods=n, freq=freq)
    return pd.Series(np.linspace(start, end, n), index=idx)


def test_asset_table_kospi_in_dollars_and_ma_gap():
    up = _line(300, 100, 200)
    fx = _line(300, 1000, 2000)            # 원화가 지수만큼 약해지면 달러 기준 코스피는 제자리
    closes = {'SPY': up, '^KS11': up, mf.FX_KRW: fx}
    at = mf.asset_table(closes).set_index('자산')
    assert at.loc['미국 주식 (S&P500)', '200일선 이격(%)'] > 0
    assert abs(at.loc['한국 주식 (코스피·$)', '1년(%)']) < 1e-6
    assert np.isnan(at.loc['비트코인', '1년(%)'])      # 없는 데이터는 숨기지 않고 빈칸


def test_flow_verdict_counts_risk_assets():
    at = pd.DataFrame({'자산': ['미국 주식 (S&P500)', '한국 주식 (코스피·$)', '구리', '비트코인', '금'],
                       '200일선 이격(%)': [5, 3, 2, 10, -1]})
    v = mf.flow_verdict(at)
    assert v['risk_up'] == 4 and v['word'] == '위험자산으로 유입'
    at['200일선 이격(%)'] = [-5, -3, -2, -10, 4]
    assert mf.flow_verdict(at)['word'] == '위험자산에서 이탈'


def test_net_liquidity_units():
    idx = pd.date_range('2025-01-01', periods=3, freq='W-WED')
    walcl = pd.Series([7_000_000.0] * 3, index=idx)     # 백만 달러 → 7,000 십억
    tga = pd.Series([700_000.0] * 3, index=idx)          # 백만 달러
    rrp = pd.Series([300.0] * 3, index=idx)
    assert mf.net_liquidity(walcl, tga, rrp).iloc[-1] == 6000


def test_econ_rows_rules():
    m = pd.date_range('2023-01-01', periods=30, freq='MS')
    S = {
        'ICSA': pd.Series(np.r_[np.full(56, 200_000.0), np.full(4, 240_000.0)], index=pd.date_range('2025-01-04', periods=60, freq='W-SAT')),
        'T10Y3M': pd.Series([-0.2], index=[pd.Timestamp('2026-10-16')]),
        'UNRATE': pd.Series(np.r_[np.full(27, 4.0), [4.6, 4.7, 4.8]], index=m),
        'FEDFUNDS': pd.Series(np.r_[np.full(24, 4.5), np.full(6, 3.75)], index=m),
    }
    R = {r['지표']: r for r in mf.econ_rows(S)}
    assert R['신규 실업수당 (4주 평균)']['판정'] == '경고'
    assert R['장단기 금리차 10Y−3M']['판정'] == '경고'
    assert R['실업률 · 삼의 법칙']['판정'] == '경고'
    assert R['기준금리 (Fed)']['판정'] == '인하 중'
    assert R['GDPNow (이번 분기 추정)']['판정'] == '자료없음'     # 빈 자료는 '확장'으로 칠하지 않는다


def test_greed_only_core_switch_cuts():
    assert mf.greed_signals(False, 0.0, 'EARN', -1, -1)['word'] == '줄여라'
    g = mf.greed_signals(True, 0.5, 'RFIN', 2, 1)
    assert g['n'] == 3 and g['word'] == '평소대로 · 주의'      # 참고 경고만으로는 '줄여라'가 되지 않는다
    assert mf.greed_signals(None, None, None, None, None)['word'] == '판정 불가'


def test_country_mcap_index_fx_actual_and_stale():
    idx = pd.Series([100.0, 110.0, 121.0], index=pd.to_datetime(['2025-12-31', '2026-06-30', '2026-10-16']))
    jpy = pd.Series([150.0, 150.0, 100.0], index=idx.index)        # 엔 강세: 1달러 150엔 → 100엔
    base = {'USA': {'usd': 60e12, 'year': 2025}, 'JPN': {'usd': 6e12, 'year': 2025},
            'EMU': {'usd': 5e12, 'year': 2018}, 'TWN': {'local': 90e12, 'ccy': 'TWD', 'year': 2025}}
    m = mf.country_mcap(base, {'S&P500': idx, '닛케이225': idx, '유로스톡스50': idx, '대만 가권': idx},
                        fx={'JPY': jpy, 'TWD': pd.Series([30.0, 30.0, 30.0], index=idx.index)},
                        actual={'KOR': (3.8e12, '2026-10-20')})
    assert abs(m['S&P500'][0] - 72.6) < 1e-6 and m['나스닥'][0] == m['S&P500'][0]
    assert abs(m['닛케이225'][0] - 6 * 1.21 * 1.5) < 1e-6           # 지수 +21% × 엔화 +50%
    assert abs(m['대만 가권'][0] - 90 * 1.21 / 30) < 1e-6
    assert m['코스피'][0] == 3.8 and '실측' in m['코스피'][1] and m['코스닥'][0] == 3.8
    assert '유로스톡스50' not in m                                     # 2018년 말 지수가 없으면 만들지 않는다


def test_regime_history_no_lookahead_and_labels():
    days = pd.bdate_range('2014-01-01', '2026-09-30')
    px = pd.Series(np.linspace(100, 300, len(days)), index=days)        # 꾸준한 상승
    m = pd.date_range('2012-01-01', '2026-09-01', freq='MS')
    fed = pd.Series(2.0, index=m); ip = pd.Series(np.linspace(100, 140, len(m)), index=m); ur = pd.Series(4.0, index=m)
    h = mf.regime_history(fed, ip, ur, px)
    assert not h.empty and set(h['phase']) == {'EARN'}       # 금리 횡보 · 실적 개선 · 주가 상승 = 실적장세
    f = mf.regime_forward(h, 3)
    assert f.loc['EARN', '다음 3개월 상승 비율(%)'] == 100
