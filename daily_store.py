# -*- coding: utf-8 -*-
"""일봉 캐시 — 퀀트 백테스트의 '탈출만 일봉으로'(quant_engine exit.daily) 전용 (2026-11-06).

price_store.py 가 일봉을 저장하지 않는 이유(전 종목 714MB·Yahoo 레이트리밋, price_store.py 상단 주석)는
여기엔 해당 없다 — 이 캐시는 **그 백테스트가 실제로 들고 있던 종목만**(보통 수십~수백 종, 전 유니버스 아님)
담는다. 그래도 느리고 외부 서버에 의존한다는 점은 같다 — 실패하면 호출부가 주봉으로 되돌아간다
(이 모듈은 절대 예외를 올리지 않는다. 없으면 None).
"""
import os
import sqlite3

import pandas as pd

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'daily_cache.db')
_COLS = ('Open', 'High', 'Low', 'Close', 'Volume')


def _conn():
    c = sqlite3.connect(DB, timeout=60)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('CREATE TABLE IF NOT EXISTS daily (sym TEXT, market TEXT, date TEXT, open REAL, high REAL, '
              'low REAL, close REAL, volume REAL, PRIMARY KEY (sym, market, date))')
    return c


def get(sym: str, market: str, start: str, end: str = None):
    """일봉 DataFrame(Open·High·Low·Close·Volume, 인덱스=날짜) — 캐시에 없는 뒤쪽 구간만 FDR로 받아 채운다.
    완전히 실패하면 None(호출부가 주봉으로 폴백할 신호)."""
    end = end or pd.Timestamp.today().strftime('%Y-%m-%d')
    try:
        c = _conn()
        try:
            have = pd.read_sql_query('SELECT date, open, high, low, close, volume FROM daily '
                                     'WHERE sym=? AND market=? ORDER BY date', c, params=(sym, market))
            last = have['date'].max() if len(have) else None
            if last is None or last < end:
                import FinanceDataReader as fdr
                df = fdr.DataReader(sym, last or start, end)
                if df is not None and len(df):
                    df = df[list(_COLS)].dropna(subset=['Close'])
                    rows = [(sym, market, ts.strftime('%Y-%m-%d'),
                             *(None if pd.isna(r[k]) else float(r[k]) for k in _COLS))
                            for ts, r in df.iterrows()]
                    c.executemany('INSERT OR REPLACE INTO daily VALUES (?,?,?,?,?,?,?,?)', rows)
                    c.commit()
                have = pd.read_sql_query('SELECT date, open, high, low, close, volume FROM daily '
                                         'WHERE sym=? AND market=? ORDER BY date', c, params=(sym, market))
        finally:
            c.close()
    except Exception:
        return None
    if not len(have):
        return None
    have['date'] = pd.to_datetime(have['date'])
    have = have.set_index('date')
    have.columns = list(_COLS)
    return have.loc[(have.index >= pd.Timestamp(start)) & (have.index <= pd.Timestamp(end))]
