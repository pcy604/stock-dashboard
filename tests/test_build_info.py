"""배포 빌드 대조 (2026-11-06 — 배포가 10-31 에 멈춘 채 일주일을 몰랐다)."""
import build_info as B


def test_stamp_roundtrip():
    b = dict(sha='ee06066abcdef0123456789', ts=1762410000, at='2025-11-06 06:20')
    p = B.parse_stamp('...이해상충 ...\n' + B.stamp(b) + '\n')
    assert p['sha'] == b['sha'][:12] and p['at'] == b['at']


def test_local_build_reads_repo():
    b = B.local_build()
    assert len(b.get('sha', '')) == 40


def test_lag_verdict():
    now = 10_000_000
    main = [('c3' * 20, now - 60), ('c2' * 20, now - 3600), ('c1' * 20, now - 7200)]
    assert B.lag_verdict({'sha': 'c3c3c3c3', 'ts': now - 60}, main, now)['ok']
    v = B.lag_verdict({'sha': 'c2c2c2c2', 'ts': now - 3600}, main, now)
    assert v['ok'] and v['behind'] == 1                       # 새 커밋 1분 전 — 아직 유예
    v = B.lag_verdict({'sha': 'c1c1c1c1', 'ts': now - 7200}, main, now)
    assert not v['ok'] and v['behind'] == 2 and v['lag_min'] == 60
    v = B.lag_verdict({'sha': 'deadbeef', 'ts': now - 9 * 86400}, main, now)   # 목록 밖 = 아주 옛 빌드
    assert not v['ok']
    assert not B.lag_verdict(None, main, now)['ok']           # 표시 자체가 없으면 실패


def test_dashboard_prints_stamp_that_keepalive_parses():
    src = open('dashboard.py', encoding='utf-8').read()
    assert '_bi.stamp(_bi.local_build())' in src
    ka = open('tools/keepalive.py', encoding='utf-8').read()
    assert 'build_info.parse_stamp' in ka and 'lag_verdict' in ka
