"""portfolio_rules_sim.load_spy — dy_SPY.csv 가 없어도 market.db 로 이어 간다(2026-10-20)."""
import os, sys
import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'research'))
import portfolio_rules_sim as S
import price_store

IDX = pd.date_range('2024-01-01', periods=10, freq='W-MON')


def _db(close=100.0):
    return pd.DataFrame({'Open': close, 'High': close, 'Low': close, 'Close': close, 'Volume': 1}, index=IDX)


def test_db_fallback_when_csv_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'ROOT', str(tmp_path))
    monkeypatch.setattr(price_store, 'get', lambda *a, **k: _db(123.0))
    s = S.load_spy(IDX)
    assert len(s) == len(IDX) and (s == 123.0).all()


def test_csv_preferred_and_monday_labels(tmp_path, monkeypatch):
    os.makedirs(tmp_path / 'data/leaders_cache')
    d = pd.DataFrame({'Close': 200.0}, index=pd.bdate_range('2024-01-01', '2024-03-15'))
    d.to_csv(tmp_path / 'data/leaders_cache/dy_SPY.csv')
    monkeypatch.setattr(S, 'ROOT', str(tmp_path))
    monkeypatch.setattr(price_store, 'get', lambda *a, **k: _db(200.0))
    s = S.load_spy(IDX)
    assert s.notna().all() and (s == 200.0).all()


def test_both_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(S, 'ROOT', str(tmp_path))
    monkeypatch.setattr(price_store, 'get', lambda *a, **k: None)
    with pytest.raises(FileNotFoundError):
        S.load_spy(IDX)
