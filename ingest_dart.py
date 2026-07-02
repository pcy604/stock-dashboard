"""
DART 공식 재무 적재 → 중앙 DB (fundamentals)
─────────────────────────────────────────────────────────────────
종목별 최근 N개년 사업보고서(연간)에서 매출·영업익·순익·자본·자산 + ROE 저장.
DART 무료 한도 20,000회/일 → 최근 3년 × 2,600사 ≈ 7,800회로 여유.

CLI:
  python ingest_dart.py --top 20 --years 3      # 시총 상위 20개 (검증용)
  python ingest_dart.py --years 3               # 전 상장사 (본 적재)
"""
import sys
import time
import argparse
from datetime import datetime

import db
import dart_client


def kr_by_marcap():
    """FDR로 KR 상장목록 + 시총 → 시총 큰 순 [(code, name, marcap)]"""
    import FinanceDataReader as fdr
    lst = fdr.StockListing('KRX')
    rows = []
    for _, r in lst.iterrows():
        code = str(r.get('Code', '')).zfill(6)
        if not (code.isdigit() and len(code) == 6):
            continue
        try:
            mc = int(r['Marcap']) if r.get('Marcap') == r.get('Marcap') and r.get('Marcap') else 0
        except Exception:
            mc = 0
        rows.append((code, str(r.get('Name', '')), mc))
    rows.sort(key=lambda x: -x[2])
    return rows


def run(years=3, top=None, pause=0.03):
    con = db.get_conn()
    cmap = dart_client.corp_map()
    uni = [u for u in kr_by_marcap() if u[0] in cmap]     # DART 등록된 상장사만
    if top:
        uni = uni[:top]
    # universe(종목명·시총)도 함께 적재 → DB 자체완결
    db.upsert_universe(con, [{'sym': c, 'market': 'KR', 'name': n, 'marcap': m or None}
                             for c, n, m in uni])
    this_year = datetime.now().year
    yrs = [this_year - 1 - i for i in range(years)]        # 최근 확정연도부터 과거로
    print(f"대상 {len(uni)}사 · 연도 {yrs} · DART 재무 수집 시작...")

    ok = empty = fail = nrows = 0
    t0 = datetime.now()
    for i, (code, name, mc) in enumerate(uni, 1):
        cc = cmap[code]
        frows = []
        for y in yrs:
            try:
                f = dart_client.financials(cc, y, 'annual')
                if not any(f.get(k) for k in ('revenue', 'net_income', 'op_income')):
                    continue
                ni, eq = f.get('net_income'), f.get('equity')
                frows.append({'sym': code, 'market': 'KR', 'period': str(y), 'freq': 'annual',
                              'revenue': f.get('revenue'), 'op_income': f.get('op_income'),
                              'net_income': ni, 'equity': eq, 'assets': f.get('assets'),
                              'roe': round(ni / eq * 100, 2) if (ni and eq) else None,
                              'source': 'dart'})
            except Exception:
                fail += 1
        if frows:
            db.upsert_fundamentals(con, frows); ok += 1; nrows += len(frows)
        else:
            empty += 1
        if i % 100 == 0:
            el = (datetime.now() - t0).total_seconds()
            print(f"  {i}/{len(uni)}  ok={ok} empty={empty} fail={fail} rows={nrows}  ({el:.0f}s)")
        time.sleep(pause)

    db.set_meta(con, 'dart_fund_last',
                {'when': datetime.now().isoformat(), 'companies': ok, 'rows': nrows, 'years': yrs})
    print(f"\n✅ DART 재무 적재 완료: {ok}사 · {nrows}행 (빈값 {empty}, 실패 {fail})")
    print("DB 현황:", db.stats(con))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', type=int, default=3)
    ap.add_argument('--top', type=int, default=None, help="시총 상위 N개만")
    a = ap.parse_args()
    run(years=a.years, top=a.top)
