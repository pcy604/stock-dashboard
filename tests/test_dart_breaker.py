"""dart_client 차단기 — DART 가 해외 서버 연결을 안 받을 때 CI·화면이 몇 분씩 멈추지 않게 (2026-10-17)"""
import time
import pytest
import requests
import dart_client as D


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    D._HEALTH.update(fails=0, open_until=0.0, last_error=None)
    monkeypatch.setattr(D.time, 'sleep', lambda s: None)
    calls = {'n': 0}

    def fake_get(*a, **k):
        calls['n'] += 1
        raise requests.exceptions.ConnectTimeout(
            "HTTPSConnectionPool(host='opendart.fss.or.kr', port=443): Max retries exceeded with url: "
            "/api/fnlttSinglAcntAll.json?crtfc_key=SECRETKEY123&corp_code=00126380")
    monkeypatch.setattr(D.requests, 'get', fake_get)
    yield calls
    D.set_interactive(False)
    D._HEALTH.update(fails=0, open_until=0.0, last_error=None)


def test_batch_opens_after_three_and_fails_fast(_reset):
    D.set_interactive(False)
    for _ in range(3):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            D._get('u', {})
    n = _reset['n']
    assert n == 6                                   # 배치: 타임아웃은 2회까지만 (예전 6회 × 20초)
    t0 = time.time()
    with pytest.raises(RuntimeError):
        D._get('u', {})                              # 차단 — 네트워크를 안 탄다
    assert _reset['n'] == n and time.time() - t0 < 0.1
    assert D.health()['blocked_sec'] > 3000


def test_interactive_one_try_and_key_never_in_error(_reset):
    D.set_interactive(True)
    for _ in range(2):
        with pytest.raises(requests.exceptions.ConnectTimeout):
            D._get('u', {})
    assert _reset['n'] == 2                          # 대화형: 타임아웃은 재시도 안 함
    h = D.health()
    assert 0 < h['blocked_sec'] <= 300
    assert 'SECRETKEY123' not in h['last_error'] and 'crtfc_key' not in h['last_error']
