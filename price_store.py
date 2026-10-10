"""
price_store.py — 주봉 가격의 단일 보관소 (market.db · prices 테이블)
─────────────────────────────────────────────────────────────────
왜 만들었나 (2026-10-10):
  가격만 DB 밖에 있었다. data/leaders_cache 에 종목당 CSV 2장(일봉·주봉)씩
  2,900종 = 843MB. 그리고 weekly-accel 워크플로가 **매주 그걸 통째로 지우고**
  Yahoo 에서 2,900종을 다시 받았다(수정주가가 소급 변경되므로 증분은 과거를
  어긋나게 한다 — 이유 자체는 옳다).

  그런데 Yahoo 가 그걸 못 버틴다. 실측으로 ~300종에서 끊겼고 universe 가
  2,429 → 242종으로 무너졌다. 그 결과 이익 가속 신호가 09-14 이후 0종이 됐고
  화면은 한 달째 09-07 에 멈춰 있었다. **신호가 없었던 게 아니라 볼 종목이
  없었다.**

  파일이 DB 밖에 있으면 '마지막으로 받은 날' 을 물어볼 곳이 없다 → 전체
  재수집 외에 방법이 없다 → 레이트리밋. 보관소를 DB 로 옮기면 종목별 최종
  날짜를 질의할 수 있고, 그래야 증분이 가능해진다.

일봉을 저장하지 않는 이유:
  일봉 CSV 가 용량의 83%(2,900종 환산 714MB)인데, 읽는 곳은 단 한 군데였다 —
  leaders_build.py 가 실적 발표일 전후 3일로 earn_react_gap · earn_react_d2
  두 열을 만드는 것뿐이다. 그 결과는 이미 factor_weekly 에 93.1% 적재돼 있다.
  그래서 일봉은 **수집 중 메모리에서만** 쓰고 버린다. 714MB → 0.

⚠️ 수정주가 소급 변경은 여전히 유효한 문제다. 증분으로 바꾼다고 사라지지
   않는다. 분할이 난 종목은 과거 전체가 바뀌므로 **그 종목만 전수 재수집**해야
   한다(data/us_splits.csv 로 추적 중). 분할 없는 종목의 소급분은 배당
   재투자분이라 주 단위에서 무시할 수 있는 크기다.
   → 상장폐지·티커 변경은 splits 에 안 잡힌다. 그건 유니버스 쪽에서 거른다.
"""
import os
import sqlite3
import pandas as pd

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'market.db')
_COLS = ('Open', 'High', 'Low', 'Close', 'Volume')


def _conn(db=None):
    c = sqlite3.connect(db or DB, timeout=60)
    c.execute('PRAGMA journal_mode=WAL')
    return c


def ensure(db=None):
    """테이블·인덱스 보장. 스키마는 이미 있었지만 0행인 채 방치돼 있었다."""
    c = _conn(db)
    c.execute("""CREATE TABLE IF NOT EXISTS prices (
        sym TEXT NOT NULL, market TEXT NOT NULL, date TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume INTEGER,
        PRIMARY KEY (sym, market, date))""")
    # 'A 종목의 마지막 날짜'와 '특정 주차 전체'를 자주 묻는다
    c.execute('CREATE INDEX IF NOT EXISTS ix_prices_date ON prices(date)')
    c.commit()
    return c


def put(sym, df, market='US', db=None, conn=None):
    """주봉 DataFrame(인덱스=날짜, 열=Open..Volume) 저장. 같은 날짜는 덮어쓴다."""
    if df is None or not len(df):
        return 0
    c = conn or ensure(db)
    d = df.copy()
    d.index = pd.to_datetime(d.index)
    rows = [(sym, market, ts.strftime('%Y-%m-%d'),
             *(None if pd.isna(r[k]) else float(r[k]) for k in _COLS[:4]),
             None if pd.isna(r['Volume']) else int(r['Volume']))
            for ts, r in d.iterrows()]
    c.executemany('INSERT OR REPLACE INTO prices VALUES (?,?,?,?,?,?,?,?)', rows)
    if conn is None:
        c.commit(); c.close()
    return len(rows)


def get(sym, market='US', db=None, conn=None):
    """주봉 DataFrame. 없으면 None — 기존 pd.read_csv(px_*.csv) 자리에 그대로 들어간다."""
    c = conn or _conn(db)
    try:
        d = pd.read_sql_query(
            'SELECT date, open, high, low, close, volume FROM prices '
            'WHERE sym=? AND market=? ORDER BY date', c, params=(sym, market))
    finally:
        if conn is None:
            c.close()
    if not len(d):
        return None
    d['date'] = pd.to_datetime(d['date'])
    d = d.set_index('date')
    d.columns = list(_COLS)
    return d


def last_date(market='US', db=None, conn=None):
    """{sym: 마지막 날짜}. **증분 수집의 핵심** — CSV 시절엔 물어볼 곳이 없었다."""
    c = conn or _conn(db)
    try:
        rows = c.execute('SELECT sym, MAX(date) FROM prices WHERE market=? GROUP BY sym',
                         (market,)).fetchall()
    finally:
        if conn is None:
            c.close()
    return dict(rows)


def drop_sym(sym, market='US', db=None, conn=None):
    """분할 등으로 과거가 소급 변경된 종목을 전수 재수집하기 전에 비운다."""
    c = conn or ensure(db)
    c.execute('DELETE FROM prices WHERE sym=? AND market=?', (sym, market))
    if conn is None:
        c.commit(); c.close()


def stats(db=None):
    c = _conn(db)
    try:
        n, s, lo, hi = c.execute(
            'SELECT COUNT(*), COUNT(DISTINCT sym), MIN(date), MAX(date) FROM prices').fetchone()
    finally:
        c.close()
    return dict(rows=n or 0, syms=s or 0, first=lo, last=hi)
