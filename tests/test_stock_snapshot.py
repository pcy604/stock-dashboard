# -*- coding: utf-8 -*-
"""stock_snapshot — 7블록 계약·유형 규칙·깨지는 조건. streamlit 없이 돈다."""
import json
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analysis_v2 as A2          # noqa: E402
import common_metrics as cm       # noqa: E402
import stock_snapshot as S        # noqa: E402


def test_axes_contract_match():
    assert A2.AXES == S.BLOCKS
    assert set(A2.AXIS_ALIAS.values()) <= set(A2.AXES)
    assert all(a in A2.AXIS_ICON for a in A2.AXES)


def test_lynch_type_rules():
    assert S.lynch_type(False, 35, None, 1e9)['label'] == '고성장'
    assert S.lynch_type(True, 35, None, 1e9)['label'] == '경기순환'        # 사이클이 성장률보다 먼저
    assert S.lynch_type(False, 10, '흑자전환', 1e9)['label'].startswith('회생')
    assert S.lynch_type(False, 8, None, 80e9)['label'] == '대형우량'
    assert S.lynch_type(False, 2, None, 80e9)['label'] == '저성장'
    assert S.lynch_type(False, None, None, None)['label'] == '판정 불가'


def test_break_conditions_distance():
    bc = S.break_conditions(rs=65, dd52=-25, fwd_tone='good', gate_on=True)
    assert bc['tone'] == 'bad' and bc['value'] == '4개 중 2개 이미 해당'
    assert S.break_conditions(90, -5, 'good', True)['tone'] == 'good'
    assert S.break_conditions(None, None, None, None)['tone'] == 'na'


def _fake():
    idx = pd.bdate_range('2025-01-01', periods=300)
    hist = pd.DataFrame({'Close': np.linspace(100, 200, 300), 'Volume': np.full(300, 1e6)}, idx)
    syms = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE', 'FFF']
    CMB = pd.DataFrame({'RS': [92, 88, 85, 80, 75, 70], '시장': ['US'] * 6, '업종': ['반도체'] * 6,
                        '매출YoY(%)': [30, 10, 5, 2, 8, 9], '영업익YoY(%)': [40, 5, -3, 1, 2, 3],
                        'PER(배)': [30, 20, 15, 10, 12, 14], '1개월(%)': [5, 4, 3, 2, 1, 0],
                        '52주고점대비(%)': [-1, -5, -9, -12, -15, -20],
                        '_mc_usd': [60e9, 50e9, 40e9, 30e9, 20e9, 10e9]}, index=syms)
    qf = pd.DataFrame({'매출액': np.linspace(100, 200, 16), '영업이익': np.r_[np.linspace(5, 30, 8), np.linspace(30, 8, 8)]},
                      index=pd.period_range('2022Q1', periods=16, freq='Q'))
    class SX:
        @staticmethod
        def quarterly_frame(rows):
            return qf
    L = {'sym8_clean': 'AAA', 'is_kr_sym': False, 'hist': hist, 'info': {'shortName': 'Triple A'},
         '_A2': A2, '_ed': {}, '_bm': {'kind': 'P/E', 'now': 30.0, 'rank': 80.0, 'pct': {50: 22.0}}, '_vb': {'per_ttm': 30.0},
         '_peg': 1.5, '_prof': {'summary': 'Triple A makes widgets for data centers.'}, '_risk': [], '_chk_': [],
         '_rk': [('이익', True, ''), ('RS ≥ 80', True, '')], '_bst': '후보'}
    ctx = {'A2': A2, 'CMB': CMB, 'cm': cm, 'sector_detail': lambda: {}, 'kr_cons_hist': lambda s: [],
           'kr_cons_live': lambda s: None, 'sx': SX, 'q_rows_long': lambda s, k: ([], None),
           'live_plan': lambda: {'index': {'US': {'ok': True}}}}
    return L, ctx


def test_compute_contract_and_public(tmp_path):
    L, ctx = _fake()
    snap = S.compute(L, ctx)
    assert list(snap['blocks']) == S.BLOCKS
    for b in snap['blocks'].values():
        assert {'tone', 'cards', 'detail', 'error'} <= set(b)
    assert snap['type']['label'] == '고성장'
    assert snap['verdict']['type_chip'] == '고성장'
    assert snap['blocks']['수급']['cards'][1]['value'].startswith('RS 92')
    assert snap['blocks']['정체']['cards'][1]['value'].startswith('반도체 · 시총 1/6위')
    assert snap['blocks']['깨지는 조건·촉매']['cards'][0]['label'] == '판단이 깨지는 조건'
    assert snap['verdict']['rules'] == {'pass': 2, 'total': 2, 'bot': '후보'}
    p = S.save(snap, str(tmp_path))
    pub = json.load(open(p, encoding='utf-8'))
    assert '매매 계획' not in pub['blocks'] and 'rules' not in pub['verdict']       # 소유자 전용은 공개 파일에 없다
    assert pub['sym'] == 'AAA' and pub['v'] == 1 and 'peer_rank' not in pub['blocks']['가격']
