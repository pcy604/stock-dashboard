# -*- coding: utf-8 -*-
import numpy as np
import pandas as pd
import trade_plan as TP


def _path(points, n=40):
    """꼭짓점 사이를 선형으로 잇는 일봉 시계열."""
    vals = []
    for a, b in zip(points, points[1:]):
        vals += list(np.linspace(a, b, n, endpoint=False))
    vals.append(points[-1])
    return pd.Series(vals, index=pd.bdate_range('2015-01-01', periods=len(vals)))


def test_zigzag_swings_known():
    c = _path([100, 80, 120, 84, 100])          # −20%, +50%, −30%, 진행 중 +19%
    s = TP.swings(c, theta=10)
    assert [round(x) for x in s['declines']] == [20, 30]
    assert [round(x) for x in s['rallies']] == [50]
    assert s['current']['dir'] == 'up' and round(s['current']['move']) == 19 and s['current']['from'] == 84
    s2 = TP.swings(_path([100, 80, 120, 96, 105]), theta=10)   # 고점 120 → 96(−20%) → 105 반등(10% 미만)
    assert s2['current']['dir'] == 'down' and round(s2['current']['reached']) == 20 and round(s2['current']['move']) == 12


def test_zigzag_ignores_small_wiggles():
    c = _path([100, 95, 99, 90, 120])           # 5%·10% 이내 출렁임은 한 스윙
    s = TP.swings(c, theta=10)
    assert [round(x) for x in s['declines']] == [10]
    assert s['current']['dir'] == 'up'


def test_next_stops_and_gap():
    sizes = [12, 18, 22, 35, 40, 55, 15, 11]
    ns = TP.next_stops(sizes, 17)
    assert ns['n'] == 5                          # 17% 이상 간 스윙 5개
    r = {x['level']: x for x in ns['rows']}
    assert r[20]['hit'] == 4 and round(r[30]['p']) == 60 and r[60]['hit'] == 0
    g = {x['from']: x for x in TP.gap_map(sizes)}
    assert g[15]['n'] == 6 and round(g[15]['p']) == 67   # 15% 넘은 6개 중 20% 넘은 4개


def test_forward_similar_runs():
    idx = pd.bdate_range('2010-01-01', periods=1500)
    c = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(0).normal(0.0004, 0.02, len(idx)))), index=idx)
    f = TP.forward_similar(c)
    assert f and f['n'] > 3 and f['p10'] <= f['median'] <= f['p90']


def test_targets_and_stops_and_size():
    t = TP.targets(100, cons={'mean': 130, 'n': 2}, band={'kind': 'P/E', 'pct': {10: 8, 25: 10, 50: 15, 75: 20, 90: 25}},
                   eps_fwd=6, eps_ttm=5, hi52=120)
    names = {x['name']: x for x in t}
    assert names['역사적 PER 고점(90분위)']['price'] == 150 and '3명 미만' in names['컨센서스 평균']['basis']
    assert round(names['PEG 1 적정가(린치)']['price']) == 120 and 'PEG' not in str(TP.targets(100, eps_fwd=4, eps_ttm=5))
    s = TP.stops(100, ma200=90)
    assert round(s['s1']) == 92 and s['s2'] == 90 and s['why2'].startswith('200일선')
    s = TP.stops(100, ma200=96)                  # 200일선이 −8% 보다 가까우면 1차 = 200일선
    assert s['s1'] == 96 and round(s['s2']) == 92
    s = TP.stops(100, ma200=92.5)                # 2% 안으로 붙으면 다음 후보로
    assert s['s2'] <= s['s1'] * 0.98
    s = TP.stops(100, ma200=110, last_low=95)
    assert s['s2'] < s['s1']                    # 2차는 항상 1차보다 아래
    p = TP.position_size(verdict_state='매수 가능 영역', stop_pct=-8, vol_annual=30)
    assert round(p['risk_size'], 1) == 12.5 and p['rec'] == 1.5
    assert TP.position_size(verdict_state='매수 가능 영역', stop_pct=-8, vol_annual=80)['rec'] == 0.75
    assert TP.position_size(verdict_state='탈출 검토 영역', stop_pct=-8, vol_annual=30)['rec'] == 0


def test_verdict_states():
    liv = {'state': '피벗 대기', 'pivot': 100, 'gap': -2}
    m_up = {'above': True, 'hist': 1, 'hist_prev': 0.5}
    v = TP.verdict(price=98, ma50=90, ma200=80, ma200_prev=79, tt_n=8, rsi_v=60, macd_d=m_up, canslim_grade='A', liv=liv, dd52=-2)
    assert v['state'] == '매수 가능 영역'
    v = TP.verdict(price=70, ma50=75, ma200=80, ma200_prev=81, tt_n=2, rsi_v=35, macd_d={**m_up, 'above': False},
                   canslim_grade='D', liv={'state': '피벗 아래', 'pivot': 100, 'gap': -30}, dd52=-40)
    assert v['state'] == '탈출 검토 영역' and len(v['exit']) >= 2
    v = TP.verdict(price=130, ma50=100, ma200=90, ma200_prev=89, tt_n=8, rsi_v=80, macd_d=m_up, canslim_grade='A',
                   liv={'state': '연장 — 추격 금지', 'pivot': 110, 'gap': 18}, dd52=0)
    assert v['state'] == '추세는 좋음 · 진입 자리 아님'


def test_rsi_macd_livermore():
    c = _path([100, 150], n=100)
    assert TP.rsi(c) > 70 and TP.macd(c)['above'] in (True, False)
    v = pd.Series(1.0, index=c.index)
    v.iloc[-5:] = 3.0
    lv = TP.livermore(c, v)
    assert lv['state'] in ('돌파 매수 구간', '연장 — 추격 금지') and lv['vol_ratio'] > 1.4


def test_station_map_finds_stops():
    """일부러 20%·35% 에서 많이 멈추게 만든 분포 → 그 두 곳이 역, 사이(22.5~32.5)는 멈춤 확률이 낮다."""
    rng = np.random.default_rng(3)
    sizes = list(rng.uniform(10, 60, 2000)) + [20.5] * 900 + [35.5] * 700
    sm = TP.station_map(TP.DEC_EDGES, TP.bin_counts(sizes, TP.DEC_EDGES))
    st = [sm['edges'][i] for i in sm['stations']]
    assert 20 in st and 35 in st, st
    lk = TP.station_lookup(sm, 21)
    assert lk['next'][0]['from'] == 35 and 0 < lk['next'][0]['p_reach'] < 100
    assert TP.vol_bucket(70, [35, 55]) == 'high' and TP.vol_bucket(None, None) == 'all'
