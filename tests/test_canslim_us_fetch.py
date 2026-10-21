"""CANSLIM US — 가격 수집 실패를 '조건 미달'과 구분하고, 캐시·재시도로 살아남는지 (2026-10-21).

10-20·10-21 정기 실행에서 후보가 250 → 1종으로 무너졌다. 원인은 조건이 아니라 Yahoo 차단이었다.
"""
import json
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

import canslim_us_run as C


def _daily(days=260, end=None, last_close=100.0):
    end = end or datetime.now()
    idx = pd.bdate_range(end=end, periods=days)
    c = np.linspace(80, last_close, days)
    return pd.DataFrame({'Open': c * 0.99, 'High': c * 1.01, 'Low': c * 0.98, 'Close': c,
                         'Volume': np.full(days, 1e6)}, index=idx)


def _setup(tmp_path, monkeypatch, n=20):
    monkeypatch.chdir(tmp_path)
    (tmp_path / 'results').mkdir()
    (tmp_path / 'data' / 'price_cache').mkdir(parents=True)
    stocks = [{'sym': f"S{chr(65 + i // 26)}{chr(65 + i % 26)}", 'name': f'Co{i}', 'market': 'US',
               'ret_12m': float(i), 'marcap': 1e10} for i in range(n)]
    (tmp_path / 'results' / 'returns.json').write_text(json.dumps({'stocks': stocks}), encoding='utf-8')
    monkeypatch.setattr(C, 'RETURNS', tmp_path / 'results' / 'returns.json')
    monkeypatch.setattr(C, 'OUT', tmp_path / 'results' / 'canslim_us_latest.json')
    monkeypatch.setattr(C, 'PRICE_CACHE', tmp_path / 'data' / 'price_cache')
    monkeypatch.setattr(C, 'RETRY_WAIT_S', 0)
    monkeypatch.setattr(C.time, 'sleep', lambda s: None)
    monkeypatch.setattr(C, '_earnings', lambda sym: dict(c_g=30, c_q='2026Q3', a1=25, a2=25, basis='OP',
                                                        c_gaap=30, a1_gaap=25, a2_gaap=25, oneoff=[],
                                                        rev_g=20, op_g=30))
    monkeypatch.setattr(C, '_market_dir', lambda: (True, '상승추세 ✅'))
    for k in C._SRC:
        C._SRC[k] = 0
    return [s['sym'] for s in stocks]


def _no_network(monkeypatch):
    import FinanceDataReader as fdr
    monkeypatch.setattr(fdr, 'DataReader', lambda *a, **k: (_ for _ in ()).throw(ConnectionError('429')))
    monkeypatch.setattr(C, '_ohlcv_yahoo', lambda sym: None)


def test_fetch_fail_is_not_condition_fail(tmp_path, monkeypatch):
    """전부 수집 실패면 후보 0이 아니라 '수집 실패 100%'로 기록돼야 한다."""
    _setup(tmp_path, monkeypatch)
    _no_network(monkeypatch)
    C.run(top=250)
    d = json.loads(C.OUT.read_text(encoding='utf-8'))
    assert d['n_cands'] > 0
    assert d['price_fail'] == d['n_cands']
    assert d['fetch_fail_pct'] == 100.0


def test_fresh_cache_used_without_network(tmp_path, monkeypatch):
    """같은 실행의 perf_run 캐시가 있으면 네트워크 없이도 후보가 나온다."""
    syms = _setup(tmp_path, monkeypatch)
    _no_network(monkeypatch)
    for s in syms:
        _daily().to_parquet(C.PRICE_CACHE / f"{s}.parquet")
    C.run(top=250)
    d = json.loads(C.OUT.read_text(encoding='utf-8'))
    assert d['price_fail'] == 0 and len(d['stocks']) == d['n_cands']
    assert d['price_src']['cache'] == d['n_cands']


def test_stale_cache_ignored(tmp_path, monkeypatch):
    """낡은 캐시로 신고가를 재면 안 된다 — 마지막 봉이 4일보다 오래면 버린다."""
    syms = _setup(tmp_path, monkeypatch)
    _no_network(monkeypatch)
    for s in syms:
        _daily(end=datetime.now() - timedelta(days=20)).to_parquet(C.PRICE_CACHE / f"{s}.parquet")
    C.run(top=250)
    d = json.loads(C.OUT.read_text(encoding='utf-8'))
    assert d['fetch_fail_pct'] == 100.0 and d['price_src']['cache'] == 0


def test_retry_pass_recovers(tmp_path, monkeypatch):
    """첫 바퀴에 막혀도 쉬었다가 다시 돌면 살아난다(속도제한은 잠깐이다)."""
    _setup(tmp_path, monkeypatch)
    import FinanceDataReader as fdr
    calls = {}

    def flaky(sym, start=None, *a, **k):
        calls[sym] = calls.get(sym, 0) + 1
        if calls[sym] == 1:
            raise ConnectionError('429')
        return _daily()
    monkeypatch.setattr(fdr, 'DataReader', flaky)
    monkeypatch.setattr(C, '_ohlcv_yahoo', lambda sym: None)
    C.run(top=250)
    d = json.loads(C.OUT.read_text(encoding='utf-8'))
    assert d['price_fail'] == 0 and len(d['stocks']) == d['n_cands']


def test_contract_blocks_fetch_failure(tmp_path, monkeypatch):
    """계약 검사가 '후보 부족'보다 먼저 '수집 실패'를 원인으로 짚는다."""
    import output_contracts as OC
    monkeypatch.setattr(OC, '_j', lambda p: {'date': datetime.now().strftime('%Y-%m-%d'), 'stocks': [{}],
                                             'n_cands': 250, 'price_fail': 249, 'fetch_fail_pct': 99.6})
    res = OC.c_canslim_us()
    msgs = [str(r) for r in res]
    assert any('수집 실패' in m for m in msgs), msgs
