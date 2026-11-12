import datetime as dt
import json
from pathlib import Path

import pandas as pd

import events


def test_second_thursday_known():
    assert events.second_thursday(2026, 11) == dt.date(2026, 11, 12)
    assert events.second_thursday(2026, 12) == dt.date(2026, 12, 10)


def test_calendar_file_dates_parse():
    cal = json.loads(Path(events.__file__).with_name('data').joinpath('events_calendar.json').read_text(encoding='utf-8'))
    for e in cal['events']:
        dt.date.fromisoformat(e['date'])
        assert e.get('src')


def test_build_marks_unreported_holdings():
    fq = pd.DataFrame({'sym': ['A'], 'year': [2026], 'q': [3]})
    ev = events.build(dt.date(2026, 11, 12), 10, {'A': '가', 'B': '나'}, fq)
    rep = [e for e in ev if '3분기' in e['name']][0]
    assert rep['hot'] and '나' in rep['detail'] and '가' not in rep['detail']
    assert any('옵션' in e['name'] and e['dday'] == 0 for e in ev)
