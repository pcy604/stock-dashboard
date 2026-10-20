"""verdict — 판정 단일 출처. 같은 입력이면 어느 소비자가 불러도 같은 답."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
import pandas as pd
import verdict as V


def _ser(last_jump):
    idx = pd.bdate_range('2025-01-01', periods=300)
    v = np.linspace(100, 110, 300)
    v[-1] = v[-1] * (1 + last_jump)
    return pd.Series(v, index=idx)


def test_core_switch_on_off_and_gap():
    on = V.core_switch(_ser(0.0)); off = V.core_switch(_ser(-0.2))
    assert on['on'] is True and on['gap'] > 0
    assert off['on'] is False and off['gap'] < 0
    assert V.core_switch(_ser(0)[:150]) == {}          # 데이터 부족 → 판정 불가(추측하지 않는다)


def test_alloc_follows_principle_and_sums_100():
    s = V.sleeves()
    a_on, a_off = V.alloc(True), V.alloc(False)
    assert a_on['core_now'] == s['core'] and a_on['cash_total'] == s['buffer']
    assert a_off['core_now'] == 0 and a_off['cash_total'] == s['buffer'] + s['core']
    assert a_on['core_now'] + s['satellite'] + a_on['cash_total'] == 100
    assert a_off['core_now'] + s['satellite'] + a_off['cash_total'] == 100
    assert V.alloc(None)['cash_total'] is None


def test_market_dir_same_rule_for_kr_us():
    assert V.market_dir(V.core_switch(_ser(0))).startswith('상승추세')
    assert V.market_dir({}) == '판단불가'


def test_build_offline_and_history_change(tmp_path):
    p = tmp_path / 'macro.json'
    v = V.build(spy=_ser(0), kospi=_ser(-0.2), fetch=lambda *_: [], closes={})
    assert v['core']['on'] and not v['kr_core']['on']
    assert v['canslim_m']['KR'].startswith('하락추세')
    V.write(v, str(p))
    v2 = V.build(spy=_ser(-0.2), kospi=_ser(0), fetch=lambda *_: [], closes={})
    v2['asof'] = '2099-01-01'
    v2 = V.write(v2, str(p))
    assert v2['changed'] is True and v2['prev_on'] is True and len(v2['history']) == 2
