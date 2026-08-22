"""
전 화면 스모크 테스트 — "탭이 백지가 되는" 사고를 CI에서 잡는다.

배경(2026-08-11): dashboard.py 741행의 KeyError 한 줄 때문에 그 아래 모든 탭이
렌더되지 않아 6개 탭 중 5개가 백지가 됐고, 며칠간 아무도 몰랐다. Streamlit은
스크립트를 위→아래로 한 번에 실행하므로 **예외 하나가 그 아래 전부를 죽인다.**

그래서 이 테스트가 지키는 것은 딱 두 가지다.
  1) 스크립트가 끝까지 실행되는가 (= 마지막 줄까지 도달했는가)
  2) 예외·에러 박스가 하나도 없는가

실행:  pytest tests/ -q          (네트워크 필요 — 실제 데이터 소스를 그대로 탄다)
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 기대하는 탭 구성 — 이름이 바뀌면 테스트도 같이 고쳐야 한다(의도한 변경인지 확인용)
# 💼 포트폴리오와 📒 성적표는 2026-08-22 제거했다(사유는 dashboard.py 상단 주석).
# 지운 탭이 되살아나면 그것도 회귀이므로, 있어야 할 목록과 **없어야 할 목록**을 같이 건다.
EXPECTED_TOP_TABS = ['🔎 종목 발굴', '🔍 종목 분석', '🌍 매크로']
EXPECTED_SUB = ['🚀 주도주', '🏆 CANSLIM', '🔥 상승 상위', '💎 가치 발굴 (KR)']
REMOVED_TABS = ['💼 포트폴리오', '📒 성적표 — 신호가 실제로 맞았나']


@pytest.fixture(scope='module')
def app():
    from streamlit.testing.v1 import AppTest
    os.chdir(ROOT)                       # 대시보드가 상대경로로 results/를 읽는다
    at = AppTest.from_file(str(ROOT / 'dashboard.py'), default_timeout=900)
    at.run()
    return at


def test_no_exception(app):
    """예외가 하나라도 있으면 그 아래 화면이 통째로 사라진다."""
    assert not app.exception, [e.value[:400] for e in app.exception]


def test_no_error_box(app):
    """st.error 는 사용자에게 '고장'으로 보인다. 스타일 용도로도 쓰지 않는다."""
    assert not app.error, [e.value[:300] for e in app.error]


def test_reached_last_line(app):
    """푸터(스크립트 마지막 블록)가 그려졌다 = 끝까지 실행됐다."""
    texts = [c.value for c in app.caption] + [m.value for m in app.markdown]
    assert any('출처: DART' in (t or '') for t in texts), '푸터 미도달 — 중간에서 죽었다'


def test_tab_structure(app):
    labels = [t.label for t in app.tabs]
    for want in EXPECTED_TOP_TABS + EXPECTED_SUB:
        assert want in labels, f'탭 없음: {want} (현재: {labels})'
    for gone in REMOVED_TABS:
        assert gone not in labels, f'제거한 탭이 되살아났다: {gone}'


def test_data_registry_matches_files():
    """레지스트리에 등록했는데 실제 파일이 없으면 감시가 헛돈다."""
    import data_freshness
    missing = [r['label'] for r in data_freshness.statuses() if r['state'] == 'missing']
    assert not missing, f'레지스트리에 있으나 파일 없음: {missing}'


def test_no_data_source_unwatched():
    """대시보드가 읽는 results/*.json 중 레지스트리에 없는 게 있으면 사각지대가 생긴다."""
    import re
    import data_freshness
    src = (ROOT / 'dashboard.py').read_text(encoding='utf-8')
    used = set(re.findall(r"results/[a-z_0-9]+\.json", src))
    watched = {s['path'] for s in data_freshness.SOURCES}
    # 화면이 쓰지만 감시 안 되는 것 (portfolio_latest 는 사용자 입력 산출물이라 제외)
    exempt = {'results/portfolio_latest.json', 'results/guru_chart_latest.png'}
    gap = used - watched - exempt
    assert not gap, f'감시 목록에 없는 데이터 소스: {sorted(gap)} → data_freshness.SOURCES 에 등록할 것'
