# -*- coding: utf-8 -*-
"""KR 분기재무(fundamentals_q)를 레포에 실을 수 있는 크기로 export/import.

    python export_kr_fundq.py export   # market.db → data/kr_fundamentals_q.parquet
    python export_kr_fundq.py stat     # 파일 현황

## 왜 필요한가

주도주 KR-U6(leaders_kr6.py)는 '흑자전환 OR 이익폭증' 판정에 **분기 재무**가 필요하고,
그건 지금 `data/market.db`(574MB, gitignore)의 fundamentals_q 테이블에만 있다.
그래서 KR-U6는 로컬에서 손으로 돌릴 수밖에 없었고, 실제로 leaders_kr6.json 이
US(leaders_ab.json)보다 며칠씩 뒤처진 채 대시보드에 떠 있었다.

fundamentals_q는 42,751행 × 1,437종목뿐이라 **parquet(zstd)로 0.75MB**다. market.db
전체를 옮길 이유가 없다 — 이 표만 떼어 레포에 실으면 러너가 그대로 읽는다.

## 왜 CSV가 아니라 parquet인가

`.git` 이 이미 978MB인 레포다(대부분 매시간 커밋된 대용량 JSON). 같은 실수를 반복하지
않으려면 커밋되는 파일은 작고 압축돼 있어야 한다. 같은 데이터가 CSV로는 3MB 남짓이다.
"""
import os
import sqlite3
import sys
from pathlib import Path

DB = Path('data/market.db')
OUT = Path('data/kr_fundamentals_q.parquet')
UNI = Path('data/kr_universe.parquet')
TABLE = 'fundamentals_q'


def export():
    import pandas as pd
    if not DB.exists():
        raise SystemExit(f'{DB} 없음 — 로컬에서만 실행 가능(러너는 load 쪽만 씀)')
    con = sqlite3.connect(DB)
    try:
        df = pd.read_sql(f'SELECT * FROM {TABLE}', con)
        uni = pd.read_sql('SELECT sym, name, listed_shares, marcap FROM universe', con)
    finally:
        con.close()
    if df.empty:
        raise SystemExit(f'{TABLE} 비어 있음 — 먼저 `python ingest_dart_quarterly.py` 실행')
    # 정렬해 두면 같은 데이터일 때 parquet 바이트가 안정돼 무의미한 diff가 안 생긴다.
    df = df.sort_values(['sym', 'year', 'q']).reset_index(drop=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUT, compression='zstd', index=False)
    print(f'{OUT} — {len(df):,}행 · {df.sym.nunique():,}종목 · '
          f'{df.year.min()}~{df.year.max()} · {OUT.stat().st_size/1e6:.2f} MB')

    # universe도 같이 내보낸다. 없으면 KR-P1 후보표에 종목명 대신 코드만 뜨고,
    # 더 나쁘게는 KR-U6의 **시총 필터가 통째로 안 걸려** 규칙 자체가 달라진다
    # (shares_map()이 빈 dict를 반환한다).
    uni = uni[uni.sym.astype(str).str.fullmatch(r'\d{6}')].sort_values('sym').reset_index(drop=True)
    uni.to_parquet(UNI, compression='zstd', index=False)
    print(f'{UNI} — {len(uni):,}종목 · {UNI.stat().st_size/1e3:.0f} KB')


def load_universe():
    """{sym: (name, listed_shares, marcap)}. market.db 우선, 없으면 export 폴백."""
    import pandas as pd
    if DB.exists():
        try:
            with sqlite3.connect(DB) as c:
                rows = c.execute('SELECT sym, name, listed_shares, marcap FROM universe').fetchall()
            if rows:
                return {r[0]: (r[1], r[2], r[3]) for r in rows}
        except Exception:
            pass
    if UNI.exists():
        d = pd.read_parquet(UNI)
        return {r.sym: (r.name, r.listed_shares, r.marcap) for r in d.itertuples()}
    return {}


def load():
    """러너·로컬 공통 읽기 경로. market.db가 있으면 그쪽이 원본이므로 우선한다."""
    import pandas as pd
    if DB.exists():
        con = sqlite3.connect(DB)
        try:
            df = pd.read_sql(f'SELECT * FROM {TABLE}', con)
            if not df.empty:
                return df
        except Exception:
            pass
        finally:
            con.close()
    if OUT.exists():
        return pd.read_parquet(OUT)
    return None


def stat():
    import pandas as pd
    print(f'market.db      : {"있음" if DB.exists() else "없음"}'
          + (f' ({DB.stat().st_size/1e6:.0f} MB)' if DB.exists() else ''))
    if OUT.exists():
        d = pd.read_parquet(OUT)
        print(f'{OUT.name} : {len(d):,}행 · {d.sym.nunique():,}종목 · '
              f'{d.year.min()}~{d.year.max()} · {OUT.stat().st_size/1e6:.2f} MB')
    else:
        print(f'{OUT.name} : 없음 — `python export_kr_fundq.py export` 필요')


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'stat'
    {'export': export, 'stat': stat}.get(cmd, stat)()
