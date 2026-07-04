"""
CANSLIM 스크리너 — 미국 (US)
─────────────────────────────────────────────────────────────────
KR(canslim_run.py)과 동일 스키마로 results/canslim_us_latest.json 생성.
C·A = SEC EDGAR 공식 재무 (분기/연간 순이익 YoY)
N   = 52주 신고가 거리, S = 거래량 배수·캔들, L = RS(12개월 수익률 백분위)
I   = 무료 일간 수급 소스 없음(13F는 분기) → None('?')
M   = SPY > 200일선

실행: python canslim_us_run.py [--top 250]   (daily-refresh에서 매일)
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

RETURNS = Path('results/returns.json')
OUT = Path('results/canslim_us_latest.json')

RS_PREFILTER = 60      # RS 백분위 사전필터 (대시보드 슬라이더로 정밀 조정)
N_PREFILTER = -20.0    # 신고가 거리 사전필터(%)
MIN_MARCAP = 2e9       # $2B


def _us_pool():
    d = json.loads(RETURNS.read_text(encoding='utf-8'))
    ss = [s for s in d.get('stocks', [])
          if s['market'] == 'US' and str(s['sym']).isalpha() and s.get('ret_12m') is not None]
    arr = sorted(ss, key=lambda s: s['ret_12m'])
    n = len(arr)
    for i, s in enumerate(arr):
        s['rs_pct'] = round((i + 1) / n * 100, 1)
    return ss


def _price_block(sym):
    """1년 일봉 → (n_dist_pct, vol_ratio, body_pct, is_bull). 실패 시 None."""
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=370)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym, start)
        if df is None or len(df) < 60:
            return None
        hi52 = float(df['High'].max())
        c = float(df['Close'].iloc[-1])
        n_dist = round((c / hi52 - 1) * 100, 1) if hi52 > 0 else None
        v60 = float(df['Volume'].tail(60).mean())
        v5 = float(df['Volume'].tail(5).mean())
        vol_ratio = round(v5 / v60, 2) if v60 > 0 else None
        last = df.iloc[-1]
        rng = float(last['High'] - last['Low'])
        body = abs(float(last['Close'] - last['Open']))
        body_pct = round(body / rng * 100, 0) if rng > 0 else 0
        return n_dist, vol_ratio, body_pct, bool(last['Close'] >= last['Open'])
    except Exception:
        return None


def _earnings(sym):
    """EDGAR: C(최근 분기 순익 YoY) + A(연간 y1/y2) + 매출·영업익 YoY."""
    import edgar_client

    def yoy(cur, prev):
        if cur is None or prev is None:
            return None
        if prev < 0:
            return '흑자전환' if cur > 0 else None
        if prev == 0:
            return None
        return round((cur / prev - 1) * 100, 1)

    c_g, c_q = None, ''
    try:
        q = edgar_client.statements(sym, 'quarter', 8)
        q = [r for r in q if r.get('net_income') is not None]
        if q:
            latest = q[0]
            ly, lm = int(latest['period'][:4]), int(latest['period'][5:7])
            prev = next((r for r in q[1:]
                         if int(r['period'][:4]) == ly - 1 and abs(int(r['period'][5:7]) - lm) <= 1), None)
            if prev:
                c_g = yoy(latest['net_income'], prev['net_income'])
                c_q = latest['period']
    except Exception:
        pass

    a1 = a2 = rev_g = op_g = None
    try:
        f = edgar_client.facts(sym)
        yrs = sorted(f.keys(), reverse=True)
        ni = [f[y].get('net_income') for y in yrs]
        rv = [f[y].get('revenue') for y in yrs]
        op = [f[y].get('op_income') for y in yrs]
        if len(ni) >= 2:
            a1 = yoy(ni[0], ni[1])
            rev_g = yoy(rv[0], rv[1])
            op_g = yoy(op[0], op[1])
        if len(ni) >= 3:
            a2 = yoy(ni[1], ni[2])
    except Exception:
        pass
    return c_g, c_q, a1, a2, rev_g, op_g


def _market_dir():
    try:
        import FinanceDataReader as fdr
        spy = fdr.DataReader('SPY', (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d'))
        ma200 = float(spy['Close'].rolling(200).mean().iloc[-1])
        ok = float(spy['Close'].iloc[-1]) > ma200
        return ok, ('상승추세 ✅' if ok else '하락추세 ⚠️')
    except Exception:
        return True, '판단불가'


def run(top=250):
    pool = _us_pool()
    cands = [s for s in pool
             if s['rs_pct'] >= RS_PREFILTER and (s.get('marcap') or 0) >= MIN_MARCAP]
    cands.sort(key=lambda s: -s['rs_pct'])
    cands = cands[:top]
    print(f"US 풀 {len(pool)} → RS{RS_PREFILTER}+·시총$2B+ 후보 {len(cands)}개. 가격/재무 검사...")

    hits = []
    for i, s in enumerate(cands, 1):
        pb = _price_block(s['sym'])
        if pb is None:
            continue
        n_dist, vol_ratio, body_pct, bull = pb
        if n_dist is None or n_dist != n_dist or n_dist < N_PREFILTER:   # None/NaN 차단
            continue
        c_g, c_q, a1, a2, rev_g, op_g = _earnings(s['sym'])
        hits.append({
            'sym': s['sym'], 'name': s['name'], 'market': 'US',
            'marcap': s.get('marcap'),
            'rs_pct': s['rs_pct'], 'n_dist_pct': n_dist,
            's_vol_ratio': vol_ratio, 's_body_pct': body_pct, 's_bull': bull,
            'c_growth_pct': c_g, 'c_quarter': c_q,
            'a_growth_y1': a1, 'a_growth_y2': a2,
            'i_inst_pct': None,                      # US 일간 수급 무료소스 없음
            'rev_growth': rev_g, 'op_growth': op_g,
        })
        if i % 25 == 0:
            print(f"  {i}/{len(cands)}  (통과 {len(hits)})")
        time.sleep(0.05)

    m_ok, m_dir = _market_dir()
    OUT.write_text(json.dumps({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'generated': datetime.now().isoformat(timespec='seconds'),
        'market_ok': m_ok, 'market_dir': m_dir,
        'stocks': hits,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ US CANSLIM: 후보 {len(hits)}개 (M: {m_dir}) → {OUT}")
    for h in hits[:8]:
        print(f"  {h['name'][:18]:<18} RS{h['rs_pct']:>5} N{h['n_dist_pct']:>6}% "
              f"C={h['c_growth_pct']} A={h['a_growth_y1']}/{h['a_growth_y2']}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=250)
    a = ap.parse_args()
    run(top=a.top)
