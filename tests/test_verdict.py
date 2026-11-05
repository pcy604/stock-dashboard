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


def test_weekly_gate_matches_live_plan_index_ok():
    """매크로 탭 '실전 판정' 카드 = 봇 계획표(live/plan.index_ok) 와 같은 계산이어야 한다(2026-11-06)."""
    import importlib.util
    p = Path(__file__).resolve().parent.parent / 'results' / 'trade_idx.parquet'
    if not p.exists():
        return
    spec = importlib.util.spec_from_file_location('live_plan', str(p.parent.parent / 'live' / 'plan.py'))
    plan = importlib.util.module_from_spec(spec); spec.loader.exec_module(plan)
    want = plan.index_ok()
    ix = pd.read_parquet(p)
    after = ix.index.max() + pd.Timedelta(days=1)          # 계획표는 토요일에 만든다 = 끝난 주
    for k, col in (('KR', 'KOSPI'), ('KQ', 'KOSDAQ')):
        g = V.weekly_gate(ix[col], 5, today=after)
        assert g['on'] == want[k]['ok'] and abs(g['ma'] - want[k]['ma200']) < 0.11 and g['week'] == want[k]['date'], (k, g, want[k])


def test_weekly_gate_partial_week_uses_last_finished_week():
    idx = pd.bdate_range('2026-01-05', '2026-03-04')       # 03-04(수) = 진행 중 주
    s = pd.Series(np.linspace(100, 120, len(idx)), index=idx)
    s.iloc[-3:] = 80                                         # 이번 주 급락 — 확정 판정은 지난주 기준이라 ON
    g = V.weekly_gate(s, 5, today=pd.Timestamp('2026-03-04'))
    assert g['partial'] and g['week'] == '2026-02-27' and g['on'] is True and g['live_on'] is False


def test_sahm_single_definition_everywhere():
    import macro_flow as mf
    ur = pd.Series([4.0] * 12 + [4.1, 4.3, 4.6, 4.9], index=pd.date_range('2025-01-01', periods=16, freq='MS'))
    s = mf.sahm_series(ur)
    assert abs(s.iloc[-1] - ((4.3 + 4.6 + 4.9) / 3 - 4.0)) < 1e-9          # 3개월 평균 − 직전 12개월 3개월 평균 최저
    obs = [(d.strftime('%Y-%m-%d'), v) for d, v in ur.items()]
    d = V.macro_inputs(lambda sid, n: obs if sid == 'UNRATE' else [])
    row = [r for r in mf.econ_rows({'UNRATE': ur}) if '삼의' in r['지표']][0]
    assert d['sahm'] == round(s.iloc[-1], 2) and f"{s.iloc[-1]:+.2f}" in row['설명']


def test_drawdown52():
    s = pd.Series([100.0] * 100 + [150.0] + [120.0] * 20, index=pd.bdate_range('2026-01-01', periods=121))
    assert V.drawdown52(s)['dd'] == -20.0
