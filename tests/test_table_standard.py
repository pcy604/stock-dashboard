"""종목 발굴 표 표준(2026-10-26) — 열 계약·시총 단위·RS 표기·흑자전환 정의·휴장일 KRX 목록."""
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import common_metrics as cm  # noqa: E402
import table_ui as tui  # noqa: E402


def _base():
    b = pd.DataFrame({
        '종목': ['삼성전자', 'NVIDIA'], '시장': ['KR', 'US'],
        '_mc_usd': [9e11, 4.5e12], '_mc_local': [1.26e15, 4.5e12],
        'RS': [60.0, 90.0], '1개월(%)': [-5.0, 3.0], '52주고점대비(%)': [-40.0, -10.0],
        '매출YoY(%)': [130.0, 60.0], '영업익YoY(%)': [None, 70.0], 'PER(배)': [8.4, 40.0],
        '업종': ['반도체', 'Semis']}, index=['005930', 'NVDA'])
    return b


def test_frame_column_contract():
    rows = pd.DataFrame({'코드': ['NVDA', '005930'], 'X(%)': [1, 2], 'Y': ['a', 'b']})
    df = cm.frame(rows, _base(), ['X(%)', 'Y'], market='전체')
    assert list(df.columns) == ['종목', '코드', '시장', '시총($B)', '업종', 'X(%)', 'Y'] + cm.COMMON
    assert df['코드'].tolist() == ['NVDA', '005930']          # 탭이 정한 순서를 지킨다


def test_frame_single_market_units():
    kr = cm.frame(pd.DataFrame({'코드': ['005930']}), _base(), [], market='KR')
    assert '시총(억원)' in kr.columns and '시장' not in kr.columns
    assert kr['시총(억원)'].iloc[0] == 12_600_000
    us = cm.frame(pd.DataFrame({'코드': ['NVDA']}), _base(), [], market='US')
    assert us['시총($B)'].iloc[0] == 4500.0


def test_mixed_cap_header_and_values():
    tui.set_fx(lambda: 1400.0)
    df = pd.DataFrame({'종목': ['a', 'b'], '코드': ['005930', 'NVDA'], '시장': ['KR', 'US'], '시총($B)': [900.0, 4500.0]})
    out, ren, _ = tui.normalize(df)
    assert tui.CAP_MIXED in out.columns                     # 머리행에 두 단위
    assert out[tui.CAP_MIXED].tolist() == [12_600_000, 4500.0]   # 한국 = 억원, 미국 = $B 그대로


def test_rs_header_not_ratio():
    out, _, _ = tui.normalize(pd.DataFrame({'RS': [99, 50], 'RS13': [1.5, 0.8]}))
    assert 'RS' in out.columns and 'RS(배)' not in out.columns
    assert 'RS13(배)' in out.columns


def test_rs_scores_weighted():
    ret = pd.DataFrame({'market': ['US'] * 3, 'ret_3m': [10, 0, -10], 'ret_6m': [10, 0, -10],
                        'ret_9m': [10, 0, -10], 'ret_12m': [10, 0, -10]}, index=['a', 'b', 'c'])
    rs, exact = cm.rs_scores(ret)
    assert exact and rs['a'] > rs['b'] > rs['c']
    rs2, exact2 = cm.rs_scores(ret.drop(columns=['ret_9m']))
    assert not exact2 and rs2['a'] == rs['a']


def test_tradable_keeps_holiday_listing():
    import krx_listing as K
    hol = pd.DataFrame({'Code': ['1', '2', '3'], 'Volume': [0, 0, 0], 'MarketId': ['STK', 'KSQ', 'KNX']})
    assert len(K._tradable(hol)) == 2                       # 휴장일 목록이 한국 전 종목을 지우던 사고
    day = pd.DataFrame({'Code': ['1', '2'], 'Volume': [5, 0], 'MarketId': ['STK', 'STK']})
    assert len(K._tradable(day)) == 1


def test_turnaround_operating_income_rule(monkeypatch):
    import turnaround_run as T
    ends = list(pd.date_range(end='2026-06-30', periods=8, freq='QE'))[::-1]

    def fake(op):
        return pd.DataFrame({'Operating Income': op, 'Total Revenue': [100.0] * 8, 'Net Income': op},
                            index=ends).T
    T.DATE_STR = '2026-10-26'
    # 매년 4분기만 적자 — 전년 같은 분기는 흑자 → 흑자전환 아님(옛 정의는 '완료'로 잡았다)
    monkeypatch.setattr(T, 'fetch_quarterly_fin', lambda s: fake([5, 6, -3, 4, 5, 6, -2, 4]))
    assert T.analyze('X', 'x', 1, 'US') is None
    # 6분기 연속 적자 뒤 이번 분기 흑자 → 완료, 1분기째
    monkeypatch.setattr(T, 'fetch_quarterly_fin', lambda s: fake([2, -1, -3, -5, -4, -2, -1, -1]))
    r = T.analyze('X', 'x', 1, 'US')
    assert r['status'] == '흑자전환완료' and r['profit_streak'] == 1 and r['loss_run_before'] == 7
