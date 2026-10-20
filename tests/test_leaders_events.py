"""leaders_events.events_for — 반응일(AMC 다음날)·갭·다음 실적까지 수익률 (2026-10-20 복원)."""
import os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from leaders_events import events_for


def _data():
    di = pd.bdate_range('2020-01-01', '2021-06-30')
    c = pd.Series(np.linspace(100, 200, len(di)), index=di)
    d = pd.DataFrame({'Open': c, 'High': c, 'Low': c, 'Close': c, 'Volume': 1})
    d.loc['2020-08-06', 'Open'] = d.loc['2020-08-05', 'Close'] * 1.12      # AMC 08-05 → 08-06 갭 +12%
    w = d.resample('W-FRI').last(); w.index = w.index - pd.Timedelta(days=4)
    return w, d


def test_amc_gap_and_forward_returns():
    w, d = _data()
    ek = pd.DataFrame({'earn_date': ['2020-08-05', '2020-11-04'], 'earn_time': ['AMC', 'BMO']})
    E = events_for('X', w, d, ek)
    first = E.iloc[0]
    assert abs(first.react_gap - 12.0) < 1e-6
    assert first.as_of == pd.Timestamp('2020-08-03')          # 반응일(목)이 속한 주의 월요일 라벨
    assert first.hold_wk == 13 and first.ret_to_next > 0
    assert first.dd_to_next <= 0


def test_too_early_event_skipped():
    w, d = _data()
    assert events_for('X', w, d, pd.DataFrame({'earn_date': ['2020-01-03'], 'earn_time': ['BMO']})) is None
