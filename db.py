"""
중앙 시장 데이터 스토어 (SQLite) — 신뢰 가능한 단일 원천(single source of truth)
─────────────────────────────────────────────────────────────────
지금까지: 테이블별로 FDR/yfinance/네이버를 매번 따로 긁어옴 → 들쭉날쭉·재가공 불가.
앞으로: 공식 API(KIS·DART·data.go.kr)로 이 DB에 적재 → 대시보드는 여기서만 읽음.

  universe      : 종목 마스터 (코드·시장·이름·섹터·시총·상장주식수)
  prices        : 일봉 OHLCV (공식 시세)
  fundamentals  : 분기/연간 재무 (매출·영업익·순익·자본·EPS 등, DART 원천)
  meta          : 적재 이력 (source별 마지막 갱신 시각)

사용:
  from db import get_conn, upsert_prices, upsert_universe, upsert_fundamentals
  con = get_conn()          # 없으면 스키마 생성
"""
import sqlite3
import json
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path('data/market.db')

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS universe (
    sym            TEXT NOT NULL,
    market         TEXT NOT NULL,          -- KR / US
    name           TEXT,
    sector         TEXT,
    marcap         INTEGER,                -- 시가총액(원 / USD)
    listed_shares  INTEGER,
    updated        TEXT,
    PRIMARY KEY (sym, market)
);

CREATE TABLE IF NOT EXISTS prices (
    sym     TEXT NOT NULL,
    market  TEXT NOT NULL,
    date    TEXT NOT NULL,                 -- YYYY-MM-DD
    open    REAL, high REAL, low REAL, close REAL,
    volume  INTEGER,
    PRIMARY KEY (sym, market, date)
);
CREATE INDEX IF NOT EXISTS idx_prices_sym ON prices(sym, market);
CREATE INDEX IF NOT EXISTS idx_prices_date ON prices(date);

CREATE TABLE IF NOT EXISTS fundamentals (
    sym        TEXT NOT NULL,
    market     TEXT NOT NULL,
    period     TEXT NOT NULL,              -- 2024, 2024Q3 등
    freq       TEXT NOT NULL,              -- annual / quarter
    revenue    REAL, op_income REAL, net_income REAL,
    equity     REAL, assets REAL,
    eps        REAL, per REAL, pbr REAL, roe REAL,
    source     TEXT,                       -- dart / kis / naver
    updated    TEXT,
    PRIMARY KEY (sym, market, period, freq)
);
CREATE INDEX IF NOT EXISTS idx_fund_sym ON fundamentals(sym, market);

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT,
    updated TEXT
);
"""


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    return con


def upsert_universe(con, rows):
    """rows: [{sym, market, name, sector, marcap, listed_shares}]"""
    now = _now()
    con.executemany(
        """INSERT INTO universe (sym, market, name, sector, marcap, listed_shares, updated)
           VALUES (:sym, :market, :name, :sector, :marcap, :listed_shares, :updated)
           ON CONFLICT(sym, market) DO UPDATE SET
             name=excluded.name, sector=excluded.sector, marcap=excluded.marcap,
             listed_shares=excluded.listed_shares, updated=excluded.updated""",
        [{**{'name': None, 'sector': None, 'marcap': None, 'listed_shares': None}, **r, 'updated': now}
         for r in rows])
    con.commit()
    return len(rows)


def upsert_prices(con, rows):
    """rows: [{sym, market, date, open, high, low, close, volume}]"""
    con.executemany(
        """INSERT INTO prices (sym, market, date, open, high, low, close, volume)
           VALUES (:sym, :market, :date, :open, :high, :low, :close, :volume)
           ON CONFLICT(sym, market, date) DO UPDATE SET
             open=excluded.open, high=excluded.high, low=excluded.low,
             close=excluded.close, volume=excluded.volume""",
        rows)
    con.commit()
    return len(rows)


def upsert_fundamentals(con, rows):
    now = _now()
    keys = ['revenue', 'op_income', 'net_income', 'equity', 'assets', 'eps', 'per', 'pbr', 'roe']
    con.executemany(
        """INSERT INTO fundamentals (sym, market, period, freq, revenue, op_income, net_income,
             equity, assets, eps, per, pbr, roe, source, updated)
           VALUES (:sym, :market, :period, :freq, :revenue, :op_income, :net_income,
             :equity, :assets, :eps, :per, :pbr, :roe, :source, :updated)
           ON CONFLICT(sym, market, period, freq) DO UPDATE SET
             revenue=excluded.revenue, op_income=excluded.op_income, net_income=excluded.net_income,
             equity=excluded.equity, assets=excluded.assets, eps=excluded.eps, per=excluded.per,
             pbr=excluded.pbr, roe=excluded.roe, source=excluded.source, updated=excluded.updated""",
        [{**{k: None for k in keys}, 'source': None, **r, 'updated': now} for r in rows])
    con.commit()
    return len(rows)


def set_meta(con, key, value):
    con.execute("INSERT INTO meta (key, value, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value, _now()))
    con.commit()


def get_fundamentals(con, sym, market='KR', freq='annual'):
    """종목의 연도별 재무 [{period, revenue, op_income, net_income, equity, assets, roe}] (최신순)."""
    cur = con.execute(
        """SELECT period, revenue, op_income, net_income, equity, assets, eps, per, pbr, roe
           FROM fundamentals WHERE sym=? AND market=? AND freq=? ORDER BY period DESC""",
        (sym, market, freq))
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def get_universe_name(con, sym, market='KR'):
    row = con.execute("SELECT name FROM universe WHERE sym=? AND market=?", (sym, market)).fetchone()
    return row[0] if row else None


def stats(con):
    out = {}
    for t in ['universe', 'prices', 'fundamentals']:
        out[t] = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    out['symbols_with_prices'] = con.execute(
        "SELECT COUNT(DISTINCT sym||market) FROM prices").fetchone()[0]
    return out


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    con = get_conn()
    print(f"✅ DB 생성: {DB_PATH.resolve()}")
    print("현황:", stats(con))
