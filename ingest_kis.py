"""
KIS 일봉 적재 → 중앙 DB (market.db)
─────────────────────────────────────────────────────────────────
유니버스는 FDR(KRX 상장목록·시총)에서, 일봉은 KIS 공식 시세에서.
토큰이 꺼져도 적재된 데이터는 DB에 영구 보존.

CLI (토큰 살아있는 동안 '뽕 뽑기' — 시총 큰 순으로 우선):
  python ingest_kis.py --top 300 --days 400     # 시총 상위 300개, 최근 400일
  python ingest_kis.py --min-marcap 5e11        # 시총 5천억↑ 전부
  python ingest_kis.py                          # 전체 (오래 걸림)
"""
import sys
import argparse
from datetime import datetime, timedelta

import db
import kis_client


def kr_universe():
    import FinanceDataReader as fdr
    lst = fdr.StockListing('KRX')
    cols = lst.columns
    rows = []
    for _, r in lst.iterrows():
        code = str(r.get('Code', '')).zfill(6)
        if not (code.isdigit() and len(code) == 6):
            continue
        def _int(v):
            try:
                return int(v) if v == v and v else None
            except Exception:
                return None
        rows.append({'sym': code, 'market': 'KR',
                     'name': str(r.get('Name', '')),
                     'sector': (str(r.get('Sector')) if 'Sector' in cols and r.get('Sector') == r.get('Sector') else None) or None,
                     'marcap': _int(r.get('Marcap')),
                     'listed_shares': _int(r.get('Stocks')) if 'Stocks' in cols else None})
    return rows


def run(days=400, top=None, min_marcap=None):
    con = db.get_conn()
    uni = kr_universe()
    uni.sort(key=lambda u: -(u['marcap'] or 0))          # 시총 큰 순 (중요 종목 먼저)
    if min_marcap:
        uni = [u for u in uni if (u['marcap'] or 0) >= min_marcap]
    if top:
        uni = uni[:top]
    db.upsert_universe(con, uni)
    print(f"유니버스 {len(uni)}종목 적재 대상 (시총순). 일봉 {days}일 수집 시작...")

    start = (datetime.now() - timedelta(days=days)).strftime('%Y%m%d')
    ok = fail = bars = 0
    t0 = datetime.now()
    for i, u in enumerate(uni, 1):
        try:
            b = kis_client.daily_prices(u['sym'], start=start)
            if b:
                for x in b:
                    x['sym'] = u['sym']; x['market'] = 'KR'
                db.upsert_prices(con, b)
                bars += len(b); ok += 1
        except Exception as e:
            fail += 1
            if fail <= 8:
                print(f"  ⚠️ {u['sym']} {u['name']}: {e}")
        if i % 50 == 0:
            el = (datetime.now() - t0).total_seconds()
            print(f"  {i}/{len(uni)}  ok={ok} fail={fail} bars={bars}  ({el:.0f}s, {i/el:.1f}/s)")
    db.set_meta(con, 'kis_prices_last',
                {'when': datetime.now().isoformat(), 'symbols': ok, 'bars': bars, 'days': days})
    print(f"\n✅ 완료: {ok}종목 · {bars:,}봉 적재 (실패 {fail})")
    print("DB 현황:", db.stats(con))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=400)
    ap.add_argument('--top', type=int, default=None, help="시총 상위 N개만")
    ap.add_argument('--min-marcap', type=float, default=None, help="시총 하한(원), 예: 5e11")
    a = ap.parse_args()
    run(days=a.days, top=a.top, min_marcap=a.min_marcap)
