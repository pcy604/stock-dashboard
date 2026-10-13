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
import trajectory

RETURNS = Path('results/returns.json')
OUT = Path('results/value_kr.json')


def _live_marcap_map():
    """오늘 종가 기준 KRX 전종목 시총 (KRX 로그인 불필요, fdr가 매번 새로 가져옴)."""
    import FinanceDataReader as fdr
    import krx_listing
    krx = krx_listing.stock_listing('KRX', tradable=True)
    return {str(r['Code']): {'marcap': int(r['Marcap']), 'name': r['Name']}
            for _, r in krx.iterrows() if r.get('Marcap')}


def _ttm_map():
    """{sym: (TTM 순이익, '2026Q2')} — 최근 4개 분기 합. 4분기가 연속으로 다 있고
    최신 분기 말이 200일 이내일 때만. (2026-10-14 신설)

    왜: PER 을 '최근 연간(FY2025)' 순이익으로 나눴다. 10월이면 2026년 상반기 실적이
    이미 나와 있는데 9개월 전 숫자를 썼다 — 이익이 급증하는 종목(삼성전자 PER 33.9,
    하이닉스 28.6)은 실제보다 비싸 보이고, 이익이 꺾이는 종목은 싸 보인다.
    가치 발굴에서 정확히 반대로 틀리는 방향이다."""
    try:
        import pandas as pd
        from datetime import date
        import ingest_dart_quarterly as Q
        q = Q.quarterly()
        if q is None or q.empty:
            return {}
        q = q.dropna(subset=['net_income']).sort_values(['sym', 'year', 'q'])
        out = {}
        for sym, g in q.groupby('sym'):
            g = g.tail(4)
            if len(g) < 4:
                continue
            idx = [int(y) * 4 + int(qq) for y, qq in zip(g.year, g.q)]
            if idx != list(range(idx[0], idx[0] + 4)):          # 연속 4분기가 아니면 버린다
                continue
            ly, lq = int(g.year.iloc[-1]), int(g.q.iloc[-1])
            if (date.today() - date(ly, lq * 3, 28)).days > 200:
                continue
            out[str(sym).zfill(6)] = (float(g.net_income.sum()), f"{ly}Q{lq}")
        return out
    except Exception as e:
        print(f"  [warn] TTM 계산 실패 — 연간 PER 로 대체: {str(e)[:80]}")
        return {}


def run():
    con = db.get_conn()
    ttm = _ttm_map()
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

        # 펀더멘털 벡터(궤적): 스칼라 위치가 아니라 방향·속도 (밸류 함정 판별)
        traj = trajectory.compute(f)

        rows.append({
            'sym': sym, 'name': name, 'marcap': live_row['marcap'],
            'period': cur['period'],
            # PER: 최근 4분기(TTM) 우선, 없으면 최근 연간. 근거를 per_basis 에 남긴다.
            'per': (round(mc / ttm[sym][0], 1) if ttm[sym][0] > 0 else None) if sym in ttm
                   else (round(mc / ni, 1) if ni and ni > 0 else None),
            'per_basis': f"TTM {ttm[sym][1]}" if sym in ttm else f"FY{cur['period']}",
            'per_fy': round(mc / ni, 1) if ni and ni > 0 else None,
            'pbr': round(mc / eq, 2) if eq and eq > 0 else None,
            'psr': round(mc / rv, 2) if rv and rv > 0 else None,
            'roe': cur.get('roe'),
            'rev_growth': yoy(rv, prev.get('revenue')),
            'op_growth': yoy(cur.get('op_income'), prev.get('op_income')),
            'ret_12m': meta.get('ret_12m') if meta else None,
            'traj': traj,   # {d_roe,d_opm,growth_accel,traj_score,verdict,...} or None
        })
    OUT.write_text(json.dumps({
        'generated': datetime.now().isoformat(timespec='seconds'),
        'coverage': len(rows), 'stocks': rows,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"✅ value_kr.json: {len(rows)}종목 (DART 공식 재무 × 당일 실시간 시총)")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    run()
