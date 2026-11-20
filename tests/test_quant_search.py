"""quant_search — 축 적용·이웃·판정이 사전 등록대로 움직이나 (2026-11-20)."""
import numpy as np
import pandas as pd
import quant_engine as Q
import quant_search as QS


def _P():
    d = pd.date_range('2018-01-01', periods=260, freq='W-MON')
    rng = np.random.default_rng(1)
    rows = []
    for k in range(8):
        px = 100 * np.cumprod(1 + rng.normal(0.003 * (k - 3), 0.04, len(d)))
        for t, p in zip(d, px):
            rows.append(dict(sym=f'S{k}', name=f'S{k}', date=t, open=p, high=p * 1.02, low=p * 0.98, close=p, volume=1e6, marcap=1e10))
    return Q.Panel(pd.DataFrame(rows))


def test_apply_does_not_mutate_base_and_sets_axes():
    base = Q.merged(dict(start='2018-01-01', filters=[], rank=dict(field='rs', desc=True)))
    s = QS.apply(base, {'trail': 20, 'rs_min': 80, 'max_pos': 5, 'rs_exit': 50})
    assert s['exit']['trail'] == [[0, 20.0]] and s['max_pos'] == 5 and s['max_w'] >= 0.2
    assert {'field': 'rs', 'op': '>=', 'value': 80.0} in s['filters']
    assert base['exit']['trail'] == [] and base['filters'] == []
    s0 = QS.apply(s, {'trail': 0, 'rs_min': 0, 'rs_exit': 0})
    assert s0['exit']['trail'] == [] and not any(f['field'] == 'rs' for f in s0['filters'])


def test_search_end_to_end():
    P = _P()
    base = Q.merged(dict(start='2018-06-04', filters=[], rank=dict(field='rs', desc=True), max_pos=3, max_w=0.34, exit=dict(signals=[])))
    res = QS.search(base, {'max_pos': [2, 3, 4], 'trail': [0, 20]}, lambda s: Q.run(P, s), '2021-01-04')
    assert len(res['df']) == 6 and res['verdict']['pick'] in res['df'].index
    assert len(res['verdict']['crit']) == 4 and 'pbo' in res['verdict']
    assert len(QS._neighbors(res['df'], res['axes'], 0)) == 2       # (2,0) 이웃 = (3,0)·(2,20)


def test_combo_cap():
    import pytest
    with pytest.raises(ValueError):
        QS.search({}, {'max_pos': list(range(QS.MAX_COMBOS + 1))}, lambda s: {}, '2020-01-01')
