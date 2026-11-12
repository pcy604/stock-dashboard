"""경영실 — 버전 일치(클라우드 옛 모듈 재적재) · 이력 한 줄 요약 · 자동 KPI(무사고 연속 주·사고 집계)."""
import datetime as dt
import re
from pathlib import Path

import gov
import ui_gov


def test_version_matches_dashboard():
    src = Path(__file__).resolve().parents[1].joinpath('dashboard.py').read_text(encoding='utf-8')
    m = re.search(r"getattr\(_UG, 'VERSION', None\) != '([^']+)'", src)
    assert m and m.group(1) == ui_gov.VERSION


def test_diff_lines():
    assert gov.diff(None, {'title': 'A'}).startswith('추가')
    assert gov.diff({'a': 1}, None) == '삭제'
    d = gov.diff({'status': '열림', 'progress': 40, 'updated_at': 'x'}, {'status': '종결', 'progress': 100, 'updated_at': 'y'})
    assert d == 'progress: 40 → 100 · status: 열림 → 종결'
    assert gov.diff({'deleted': False}, {'deleted': True}) == '🗑 숨김'
    assert gov.diff({'a': 1}, {'a': 1}) == '(변화 없음)'


def test_week_of_is_monday():
    assert gov.week_of(dt.date(2026, 11, 12)) == dt.date(2026, 11, 9)
    assert gov.week_of(dt.date(2026, 11, 15)) == dt.date(2026, 11, 9)


def test_default_kpi_keys_unique():
    keys = [k[0] for k in gov.DEFAULT_KPIS]
    assert len(keys) == len(set(keys))
    assert {'wau', 'lab_excess', 'clean_streak', 'lab_mdd'} <= set(keys)


def test_auto_incidents_and_streak(monkeypatch):
    wk = gov.week_of()
    # 외부 호출은 전부 끈다 — 사고·연속 주 계산만 본다
    monkeypatch.setattr(ui_gov, '_lab_perf', lambda: None)
    monkeypatch.setattr(ui_gov, '_ci_rate', lambda: (None, ''))
    monkeypatch.setattr(gov, 'usage', lambda days=7: [])
    monkeypatch.setattr(gov, 'bot_users', lambda: None)
    w1, w2, w3 = (wk - dt.timedelta(weeks=i) for i in (1, 2, 3))
    vals = [{'week': w1.isoformat(), 'key': 'incidents', 'value': 0},
            {'week': w2.isoformat(), 'key': 'incidents', 'value': 0},
            {'week': w2.isoformat(), 'key': 'overrides', 'value': 0},
            {'week': w3.isoformat(), 'key': 'incidents', 'value': 2}]
    out = ui_gov.compute_auto('me', [], vals)
    assert out['incidents'][0] == 0
    assert out['clean_streak'][0] == 3          # 이번 주 + 지난 2주, 3주 전 사고에서 멈춤
    issue = [{'created_at': wk.isoformat() + 'T01:00:00+00:00', 'meta': {'type': '사고'}},
             {'created_at': wk.isoformat() + 'T01:00:00+00:00', 'meta': {'type': '버그'}}]
    out = ui_gov.compute_auto('me', issue, vals)
    assert out['incidents'][0] == 1 and out['clean_streak'][0] == 0
