"""💬 VOC — 입력 검증 · REST 호출 모양 · 화면 렌더 (2026-11-20)."""
import pytest
import voc_store as V


class _R:
    def __init__(self, data=None): self._d = data or []
    def raise_for_status(self): pass
    def json(self): return self._d


def _cfg(monkeypatch, calls):
    monkeypatch.setattr(V._U, '_cfg', lambda: {'url': 'https://x.supabase.co', 'key': 'sb_secret_k', 'master_key': 'm'})
    for verb in ('post', 'get', 'patch'):
        monkeypatch.setattr(V.requests, verb, lambda url, _v=verb, **kw: calls.append((_v, url, kw)) or _R(
            [{'id': 1, 'display': '익명', 'area': '전체', 'kind': '버그', 'title': 't1', 'body': 'b', 'status': '접수',
              'reply': None, 'votes': 2, 'created_at': '2026-11-20T10:00:00+00:00', 'updated_at': '2026-11-20T10:00:00+00:00'}]))


def test_clean_rejects_bad_input():
    with pytest.raises(ValueError):
        V.clean('전체', '버그', ' ', '')
    with pytest.raises(ValueError):
        V.clean('전체', '없는분류', '제목', '')
    assert len(V.clean('전체', '버그', 'x' * 500, '')['title']) == V.MAX_TITLE


def test_rest_calls(monkeypatch):
    calls = []
    _cfg(monkeypatch, calls)
    V.submit('s_abc', '익명', '전체', '기능 요청', '배당 열 추가', '본문')
    assert calls[-1][0] == 'post' and calls[-1][1].endswith('/rest/v1/voc') and calls[-1][2]['json'][0]['uid'] == 's_abc'
    assert 'uid' not in V.items()[0] and 'uid' not in calls[-1][2]['params']['select']
    V.set_status(1, '진행', '작업 중')
    assert calls[-1][2]['json']['status'] == '진행' and calls[-1][2]['params'] == {'id': 'eq.1'}
    with pytest.raises(ValueError):
        V.set_status(1, '이상한상태')


def test_render_headless(monkeypatch, tmp_path):
    from streamlit.testing.v1 import AppTest
    app = tmp_path / 'a.py'
    app.write_text(
        "import sys; sys.path.insert(0, %r)\n"
        "import streamlit as st, table_ui, voc_store as V; table_ui.install(st)\n"
        "V.ready = lambda: True\n"
        "V.items = lambda limit=300: [dict(id=1, display='익명', area='전체', kind='버그', title='t1', body='b', status='접수', reply='r',"
        " votes=2, created_at='2026-11-20T10:00:00+00:00', updated_at='2026-11-20T10:00:00+00:00', images=['https://x/a.webp'])]\n"
        "import ui_voc; ui_voc.render(st, ['🏠 종합'], True, 's_x')\n" % str(__import__('pathlib').Path(__file__).parents[1]))
    at = AppTest.from_file(str(app), default_timeout=60).run()
    assert not at.exception and not at.error
    assert not [c.value for c in at.caption if c.value.startswith('`')]
    assert any('t1' in m.value for m in at.markdown)


def test_image_upload_and_submit(monkeypatch):
    """이미지 → webp 축소 → Storage(서버 키) → URL 이 voc.images 로. 이미지가 아니면 거절."""
    import io
    from PIL import Image
    calls = []
    _cfg(monkeypatch, calls)
    buf = io.BytesIO()
    Image.new('RGB', (3200, 1000), 'red').save(buf, 'PNG')
    url = V.upload(buf.getvalue())
    verb, u, kw = calls[-1]
    assert verb == 'post' and '/storage/v1/object/voc/' in u and kw['headers']['Content-Type'] == 'image/webp'
    assert max(Image.open(io.BytesIO(kw['data'])).size) == V.IMG_PX
    assert url.startswith('https://x.supabase.co/storage/v1/object/public/voc/') and url.endswith('.webp')
    with pytest.raises(ValueError):
        V.img_bytes(b'not an image')
    V.submit('s_a', '익명', '전체', '버그', '캡처 첨부', '', images=[url] * 5)
    assert calls[-1][2]['json'][0]['images'] == [url] * V.MAX_IMG
    V.submit('s_a', '익명', '전체', '버그', '글만', '')
    assert 'images' not in calls[-1][2]['json'][0]          # 마이그레이션 전 DB 에서도 글 접수는 된다


def test_items_falls_back_without_images_column(monkeypatch):
    import importlib
    importlib.reload(V)                 # 헤드리스 렌더 테스트가 같은 프로세스에서 V.items 를 바꿔 둔다
    seen = []

    class R400(_R):
        status_code = 400
    monkeypatch.setattr(V._U, '_cfg', lambda: {'url': 'https://x.supabase.co', 'key': 'k', 'master_key': 'm'})
    monkeypatch.setattr(V.requests, 'get', lambda url, **kw: seen.append(kw['params']['select']) or
                        (R400() if 'images' in kw['params']['select'] else _R([{'id': 1}])))
    assert V.items() == [{'id': 1}] and seen == [V._SEL + ',images', V._SEL]
