# -*- coding: utf-8 -*-
"""전략 저장소 — 네트워크 없이 도는 부분(익명 이름 · 성과 축약 · SQL 문구)."""
import strategy_store as S


def test_anon_name_stable_and_short():
    a, b = S.anon_name('user-one'), S.anon_name('USER-ONE ')
    assert a == b and a.startswith('익명 #') and len(a) == len('익명 #') + 4


def test_slim_stats_keeps_only_known_keys():
    out = S.slim_stats({'CAGR': 20.661, 'MDD': -27.65, 'secret': 1}, '2018-06-04 00:00:00', None)
    assert out['CAGR'] == 20.661 and out['MDD'] == -27.65 and 'secret' not in out
    assert out['start'] == '2018-06-04' and out['end'] is None


def test_sql_enables_rls():
    assert 'create table if not exists strategies' in S.SQL and 'enable row level security' in S.SQL


def test_public_list_does_not_select_uid():
    import inspect
    src = inspect.getsource(S.public_list)
    assert "'select': 'id,name,market,spec,stats,display,created_at'" in src and 'uid,' not in src
