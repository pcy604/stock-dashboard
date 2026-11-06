"""우라가미 4계절 v2 상태 기계 (2026-11-06)."""
import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import macro_season as M


def _sig(rows):
    """rows = [(rate, growth, px, infl)] → run() 이 먹는 신호표(조건 열만)."""
    idx = pd.date_range('2000-01-31', periods=len(rows), freq='ME')
    d = pd.DataFrame(index=idx)
    d['rate'] = [r[0] for r in rows]
    d['growth'] = [r[1] for r in rows]
    d['px'] = [r[2] for r in rows]
    d['infl'] = [r[3] for r in rows]
    c = pd.DataFrame(index=idx)
    c['rate_dn'] = d['rate'] == '하락'; c['not_rate_dn'] = d['rate'] != '하락'; c['not_rate_up'] = d['rate'] != '상승'
    c['ip_up'] = d['growth'] == '개선'; c['ip_dn'] = d['growth'] == '악화'; c['not_ip_dn'] = d['growth'] != '악화'
    c['px_up'] = d['px'] == '상승'; c['px_dn'] = d['px'] == '하락'
    c['not_hot'] = d['infl'] != '과열'; c['tight'] = (d['rate'] == '상승') | (d['infl'] == '과열')
    for k, conds in M.COND.items():
        d[f'n_{k}'] = sum(c[ck].astype(int) for ck, _ in conds)
    return d


FIN = ('하락', '횡보', '상승', '중립')
EARN = ('횡보', '개선', '상승', '중립')
RFIN = ('상승', '개선', '하락', '중립')
RERN = ('횡보', '악화', '하락', '중립')


def test_next_needs_two_months():
    h = M.run(_sig([FIN, EARN, EARN]))
    assert list(h['phase']) == ['FIN', 'FIN', 'EARN']
    assert h['pending'].iloc[1] == 'EARN'          # 한 달 충족 = 전환 대기


def test_single_month_blip_does_not_flip():
    h = M.run(_sig([FIN, FIN, EARN, FIN, FIN]))
    assert set(h['phase']) == {'FIN'}


def test_jump_needs_three_months():
    h = M.run(_sig([FIN, RFIN, RFIN, RFIN]))        # 🌱 → 🍂 는 순서 건너뛰기
    assert list(h['phase']) == ['FIN', 'FIN', 'FIN', 'RFIN']


def test_inflation_alone_counts_as_tightening():
    hot_earn = ('횡보', '개선', '하락', '과열')     # 금리 횡보여도 물가 과열 + 주가 하락 → 역금융 조건 3/3
    h = M.run(_sig([EARN, hot_earn, hot_earn]))
    assert h['phase'].iloc[-1] == 'RFIN'


def test_hot_inflation_blocks_spring():
    hot_fin = ('하락', '횡보', '상승', '과열')
    d = _sig([hot_fin])
    assert d['n_FIN'].iloc[0] == 2


def test_position_and_stage():
    assert M.position(0, 10, 0) == 0
    assert M.position(10, 10, 3) == 100
    assert M.position(5, 10, 1) == 42
    assert M.stage(20, False) == '초입' and M.stage(50, False) == '중반' and M.stage(80, False) == '후반'
    assert M.stage(10, True) == '전환 대기'


def test_long_history_runs_and_is_stabler_than_v1():
    if not os.path.exists(M.FRED_PQ):
        return
    L = M.load_long()
    h = M.history(**L)
    assert len(h) > 600 and h['phase'].notna().mean() > 0.95
    flips = int((h['phase'] != h['phase'].shift()).sum() - 1)
    assert flips < len(h) / 8                       # 평균 8개월 넘게 한 계절에 머문다
    n = M.now(h)
    assert n['phase'] in M.ORDER and 0 <= n['pos'] <= 100 and len(n['lines']) == 4
