"""
KR 가치 스냅샷 내보내기 — market.db(DART 공식 재무) → results/value_kr.json
─────────────────────────────────────────────────────────────────
PER = 시총 ÷ 최근연 순이익(공식) · PBR = 시총 ÷ 자본 · PSR = 시총 ÷ 매출
ROE = 순이익/자본 · 성장 = 연간 YoY. pykrx(로그인 필요해짐) 대체 — 자체 DB 정공법.

실행: python value_export.py    (daily-refresh에서 ingest_dart 후)
"""
import sys
import json
from pathlib import Path
from datetime import datetime

import db

RETURNS = Path('results/returns.json')
OUT = Path('results/value_kr.json')


def run():
    con = db.get_conn()
    retmap = {s['sym']: s for s in json.loads(RETURNS.read_text(encoding='utf-8')).get('stocks', [])
              if s.get('market') == 'KR'}
    rows = []
    syms = [r[0] for r in con.execute(
        "SELECT DISTINCT sym FROM fundamentals WHERE market='KR' AND freq='annual'").fetchall()]
    for sym in syms:
        f = db.get_fundamentals(con, sym, 'KR', 'annual')      # 최신순
        if not f:
            continue
        cur = f[0]
        prev = f[1] if len(f) > 1 else {}
        meta = retmap.get(sym)
        if not meta or not meta.get('marcap'):
            continue
        mc = float(meta['marcap'])
        ni, eq, rv = cur.get('net_income'), cur.get('equity'), cur.get('revenue')

        def yoy(c, p):
            if c is None or p is None or p == 0:
                return None
            if p < 0:
                return '흑자전환' if c > 0 else None
            return round((c / p - 1) * 100, 1)

        rows.append({
            'sym': sym, 'name': meta['name'], 'marcap': meta['marcap'],
            'period': cur['period'],
            'per': round(mc / ni, 1) if ni and ni > 0 else None,
            'pbr': round(mc / eq, 2) if eq and eq > 0 else None,
            'psr': round(mc / rv, 2) if rv and rv > 0 else None,
            'roe': cur.get('roe'),
            'rev_growth': yoy(rv, prev.get('revenue')),
            'op_growth': yoy(cur.get('op_income'), prev.get('op_income')),
            'ret_12m': meta.get('ret_12m'),
        })
    OUT.write_text(json.dumps({
        'generated': datetime.now().isoformat(timespec='seconds'),
        'coverage': len(rows), 'stocks': rows,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"✅ value_kr.json: {len(rows)}종목 (DART 공식 재무 × 실시간 시총)")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    run()
