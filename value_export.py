"""
KR 가치 스냅샷 내보내기 — market.db(DART 공식 재무) → results/value_kr.json
─────────────────────────────────────────────────────────────────
PER = 시총 ÷ 최근연 순이익(공식) · PBR = 시총 ÷ 자본 · PSR = 시총 ÷ 매출
ROE = 순이익/자본 · 성장 = 연간 YoY. pykrx(로그인 필요해짐) 대체 — 자체 DB 정공법.

2026-07-16 수정: 시총을 results/returns.json(screen_precompute.py 산출,
주 1회도 안 도는 워크플로라 최대 3주 이상 정체돼 있었음 — 실측 확인)에서
가져오던 걸 fdr.StockListing('KRX') 직접 조회로 교체. "실시간 시총"이라는
캡션이 실제로는 그렇지 않았음 — 이 표의 PER/PBR가 며칠~몇 주 전 시총 기준
숫자였던 것. 이제 daily-refresh가 이 스크립트를 돌릴 때마다 그날 종가 기준
시총으로 계산됨 (12개월 수익률만 여전히 returns.json 기준 — 가격추이 캐시라
스크립트당 250+종목 히스토리 재조회는 비용이 커 별도 유지).

실행: python value_export.py    (daily-refresh에서 ingest_dart 후)
"""
import sys
import json
from pathlib import Path
from datetime import datetime

import db

RETURNS = Path('results/returns.json')
OUT = Path('results/value_kr.json')


def _live_marcap_map():
    """오늘 종가 기준 KRX 전종목 시총 (KRX 로그인 불필요, fdr가 매번 새로 가져옴)."""
    import FinanceDataReader as fdr
    krx = fdr.StockListing('KRX')
    return {str(r['Code']): {'marcap': int(r['Marcap']), 'name': r['Name']}
            for _, r in krx.iterrows() if r.get('Marcap')}


def run():
    con = db.get_conn()
    retmap = {s['sym']: s for s in json.loads(RETURNS.read_text(encoding='utf-8')).get('stocks', [])
              if s.get('market') == 'KR'}
    live = _live_marcap_map()
    rows = []
    syms = [r[0] for r in con.execute(
        "SELECT DISTINCT sym FROM fundamentals WHERE market='KR' AND freq='annual'").fetchall()]
    for sym in syms:
        f = db.get_fundamentals(con, sym, 'KR', 'annual')      # 최신순
        if not f:
            continue
        cur = f[0]
        prev = f[1] if len(f) > 1 else {}
        live_row = live.get(sym)
        meta = retmap.get(sym)   # ret_12m 등 부가정보만 여기서
        if not live_row:
            continue
        mc = float(live_row['marcap'])
        name = live_row['name']
        ni, eq, rv = cur.get('net_income'), cur.get('equity'), cur.get('revenue')

        def yoy(c, p):
            if c is None or p is None or p == 0:
                return None
            if p < 0:
                return '흑자전환' if c > 0 else None
            return round((c / p - 1) * 100, 1)

        rows.append({
            'sym': sym, 'name': name, 'marcap': live_row['marcap'],
            'period': cur['period'],
            'per': round(mc / ni, 1) if ni and ni > 0 else None,
            'pbr': round(mc / eq, 2) if eq and eq > 0 else None,
            'psr': round(mc / rv, 2) if rv and rv > 0 else None,
            'roe': cur.get('roe'),
            'rev_growth': yoy(rv, prev.get('revenue')),
            'op_growth': yoy(cur.get('op_income'), prev.get('op_income')),
            'ret_12m': meta.get('ret_12m') if meta else None,
        })
    OUT.write_text(json.dumps({
        'generated': datetime.now().isoformat(timespec='seconds'),
        'coverage': len(rows), 'stocks': rows,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"✅ value_kr.json: {len(rows)}종목 (DART 공식 재무 × 당일 실시간 시총)")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    run()
