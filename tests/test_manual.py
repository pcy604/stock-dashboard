"""사용설명서(manual.py) — 공개 문서 금칙어 · 탭 이름 · 자동 원천 · 모듈 버전."""
import re
from pathlib import Path

import manual

ROOT = Path(__file__).resolve().parents[1]


def test_no_private_words_in_public_manual():
    doc = manual.build_html()
    assert not [w for w in manual.FORBIDDEN if w in doc]


def test_tab_names_match_dashboard():
    """한눈에 카드의 '열기' 버튼은 탭 이름이 글자까지 같아야 작동한다."""
    src = (ROOT / 'dashboard.py').read_text(encoding='utf-8')
    for tab, *_ in manual.CAPS:
        assert f'"{tab}"' in src, tab


def test_axis_names_match_analysis_v2():
    import analysis_v2
    text = ' '.join(f for _t, _q, _d, feats in manual.caps() for f, _g in feats)
    for ax in analysis_v2.DEFAULT_AXES:
        assert ax in text, ax


def test_rule_values_come_from_live_plan():
    c = manual.ctx()
    assert c['rs_min'] != '-' and c['slots'] != '-'
    assert not re.findall(r'\{[a-z_]+\}', manual.build_html())          # 채워지지 않은 자리표시자 없음


def test_cron_kst():
    assert manual.cron_kst('30 21 * * 0-4') == '평일 06:30'
    assert manual.cron_kst('23 9 * * 6') == '토 18:23'
    assert manual.cron_kst('50 6 * * 1-5') == '평일 15:50'
    assert manual.cron_kst('0 22 * * 0') == '월 07:00'


def test_schedules_resolve():
    for k, _s, wf, _l in manual.DATA_ROWS:
        assert manual.schedule(wf) != '수시', k


def test_release_notes_shape():
    rows = manual.notes()
    assert rows and all(re.fullmatch(r'\d{4}-\d\d-\d\d', r['date']) and r['area'] and r['text'] for r in rows)


def test_manual_version_matches_ui_home():
    src = (ROOT / 'ui_home.py').read_text(encoding='utf-8')
    m = re.search(r"_MN_VER = '([^']+)'", src)
    assert m and m.group(1) == manual.VERSION
