"""
turnaround_run.py  —  흑자전환 스크리너
'테슬라 2019 Q3' 같은 종목 발굴
  - 흑자전환완료: 최근 1-2분기 흑자 + 직전 연속 적자
  - 흑자전환임박: 적자 지속이나 YoY 50%+ 개선 중
  - 적자개선중:   YoY 25~50% 개선 중

실행: python turnaround_run.py
결과: results/turnaround_latest.json
"""
import json, time, socket, warnings, os
import pandas as pd
import yfinance as yf
import FinanceDataReader as fdr
from pathlib import Path
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

warnings.filterwarnings('ignore')
socket.setdefaulttimeout(15)

CACHE_DIR   = Path('data/fin_cache')
RESULT_PATH = Path('results/turnaround_latest.json')
CACHE_DIR.mkdir(parents=True, exist_ok=True)
RESULT_PATH.parent.mkdir(exist_ok=True)

DATE_STR        = date.today().isoformat()
MIN_MARCAP_KR   = 100_000_000_000   # 1000억
MIN_MARCAP_US   = 3_000_000_000     # $3B
CACHE_TTL_DAYS  = 7                 # 재무 캐시 유효기간


# ── 유니버스 ─────────────────────────────────────────────────────────
def get_kr_tickers():
    """weekly_run.py와 동일: fdr.StockListing('KRX') 사용"""
    try:
        krx = fdr.StockListing('KRX')
        filtered = krx[krx['Marcap'] >= MIN_MARCAP_KR].sort_values('Marcap', ascending=False)
        return list(zip(
            filtered['Code'].astype(str).str.zfill(6),
            filtered['Name'].astype(str),
            filtered['Marcap'].astype(int),
        ))
    except Exception as e:
        print(f"  [KR 유니버스 오류] {e}")
        return []

def get_us_tickers():
    """weekly_run.py와 동일: data/us_marketcap.csv 사용"""
    try:
        csv_path = os.path.join(os.path.dirname(__file__), 'data', 'us_marketcap.csv')
        df = pd.read_csv(csv_path)
        df = df[df['country'] == 'United States'].copy()
        df['marketcap'] = pd.to_numeric(df['marketcap'], errors='coerce')
        df = df.dropna(subset=['marketcap', 'Symbol'])
        df = df[df['marketcap'] >= MIN_MARCAP_US]
        df = df.sort_values('marketcap', ascending=False)
        df['Symbol'] = df['Symbol'].astype(str).str.strip()
        df = df[df['Symbol'].str.replace('-', '').str.isalpha() & (df['Symbol'].str.len() <= 5)]
        return list(zip(
            df['Symbol'],
            df['Name'].astype(str),
            df['marketcap'].astype(int),
        ))
    except Exception as e:
        print(f"  [US 유니버스 오류] {e}")
        return []


# ── 재무 데이터 fetch + 캐시 ─────────────────────────────────────────
def _cache_path(sym_yf: str) -> Path:
    return CACHE_DIR / f"{sym_yf.replace('.', '_')}_fin.parquet"

def fetch_quarterly_fin(sym_yf: str):
    cp = _cache_path(sym_yf)
    if cp.exists():
        age = (datetime.now() - datetime.fromtimestamp(cp.stat().st_mtime)).days
        if age < CACHE_TTL_DAYS:
            try:
                return pd.read_parquet(cp)
            except Exception:
                pass
    try:
        time.sleep(0.12)
        t   = yf.Ticker(sym_yf)
        qf  = t.quarterly_financials
        if qf is None or qf.empty:
            return None
        qf.to_parquet(cp)
        return qf
    except Exception:
        return None


# ── 흑자전환 분석 ────────────────────────────────────────────────────
def analyze(sym: str, name: str, marcap: int, market: str):
    sym_yf = f"{sym}.KS" if market == 'KR' else sym
    qf = fetch_quarterly_fin(sym_yf)
    if qf is None or qf.empty:
        return None

    try:
        # Net Income
        ni_row = None
        for key in ('Net Income', 'Net Income Common Stockholders'):
            if key in qf.index:
                ni_row = qf.loc[key]
                break
        if ni_row is None:
            return None
        ni = ni_row.sort_index(ascending=False).dropna()
        if len(ni) < 5:
            return None
        niv = [float(v) for v in ni.values]
        q0, q1, q2, q3 = niv[0], niv[1], niv[2], niv[3]
        q4 = niv[4] if len(niv) > 4 else None

        # TTM
        ttm      = sum(niv[:4])
        ttm_1y   = sum(niv[4:8]) if len(niv) >= 8 else None

        # Revenue YoY
        rev_growth = None
        for key in ('Total Revenue', 'Revenue'):
            if key in qf.index:
                rv = qf.loc[key].sort_index(ascending=False).dropna()
                if len(rv) >= 5:
                    rv0, rv4 = float(rv.iloc[0]), float(rv.iloc[4])
                    if rv4 > 0:
                        rev_growth = (rv0 / rv4 - 1) * 100
                break

        # Gross Margin trend
        gm_improving = False
        if 'Gross Profit' in qf.index and 'Total Revenue' in qf.index:
            gp = qf.loc['Gross Profit'].sort_index(ascending=False).dropna()
            rv = qf.loc['Total Revenue'].sort_index(ascending=False).dropna()
            if len(gp) >= 5 and len(rv) >= 5:
                gm0 = float(gp.iloc[0]) / float(rv.iloc[0]) if float(rv.iloc[0]) > 0 else 0
                gm4 = float(gp.iloc[4]) / float(rv.iloc[4]) if float(rv.iloc[4]) > 0 else 0
                gm_improving = gm0 > gm4 + 0.03

        # YoY improvement (같은 분기 대비)
        yoy_imp = None
        if q4 is not None and q4 < 0:
            if q0 >= 0:
                yoy_imp = 100.0
            else:
                yoy_imp = (q0 - q4) / abs(q4) * 100

        # ── 분류 ──────────────────────────────────────────────────────
        prev_neg = sum(1 for q in (q1, q2, q3) if q < 0)

        if q0 > 0 and prev_neg >= 1:
            status, score = '흑자전환완료', 5
        elif q0 > 0 and q1 < 0:
            status, score = '흑자전환완료', 4
        elif q0 < 0 and yoy_imp is not None and yoy_imp >= 50:
            status, score = '흑자전환임박', 3
        elif q0 < 0 and yoy_imp is not None and yoy_imp >= 25:
            status, score = '적자개선중', 2
        else:
            return None

        # 보너스
        if rev_growth and rev_growth > 20:       score += 1
        if gm_improving:                          score += 1
        if ttm_1y is not None and ttm > ttm_1y:  score += 1

        def _fm(v):
            if v is None: return '-'
            if market == 'KR':
                b = v / 1e8
                return f"{b:.0f}억" if abs(b) < 10000 else f"{b/10000:.1f}조"
            return f"${v/1e6:.0f}M" if abs(v) < 1e9 else f"${v/1e9:.2f}B"

        return {
            'sym':         sym,
            'name':        name,
            'market':      market,
            'marcap':      int(marcap) if marcap else 0,
            'status':      status,
            'score':       score,
            'q0_ni':       _fm(q0),
            'q1_ni':       _fm(q1),
            'q2_ni':       _fm(q2),
            'q3_ni':       _fm(q3),
            'ttm_ni':      _fm(ttm),
            'ttm_1y_ni':   _fm(ttm_1y) if ttm_1y is not None else '-',
            'yoy_imp_pct': round(yoy_imp, 1) if yoy_imp is not None else None,
            'rev_growth':  round(rev_growth, 1) if rev_growth is not None else None,
            'gm_improving': gm_improving,
            'q0_date':     str(ni.index[0])[:10],
        }
    except Exception:
        return None


# ── 메인 ─────────────────────────────────────────────────────────────
def main():
    print(f"[{DATE_STR}] 흑자전환 스크리너 시작")
    results = []

    # KR
    print("  KR 유니버스 로딩...")
    kr_list = get_kr_tickers()
    print(f"  KR {len(kr_list)}개 분석 중...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(analyze, s, n, c, 'KR'): s for s, n, c in kr_list}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result(timeout=30)
                if r: results.append(r)
            except Exception:
                pass
            if i % 100 == 0:
                print(f"  KR {i}/{len(kr_list)} | 발굴 {len(results)}개")

    kr_cnt = len(results)
    print(f"  KR 완료: 흑자전환 {kr_cnt}개")

    # US
    print("  US 유니버스 로딩...")
    us_list = get_us_tickers()
    print(f"  US {len(us_list)}개 분석 중...")
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(analyze, s, n, c, 'US'): s for s, n, c in us_list}
        for i, fut in enumerate(as_completed(futs), 1):
            try:
                r = fut.result(timeout=30)
                if r: results.append(r)
            except Exception:
                pass
            if i % 100 == 0:
                print(f"  US {i}/{len(us_list)} | 발굴 {len(results)-kr_cnt}개")

    us_cnt = len(results) - kr_cnt
    print(f"  US 완료: 흑자전환 {us_cnt}개")

    # 저장
    results.sort(key=lambda x: x['score'], reverse=True)
    out = {
        'date':   DATE_STR,
        'total':  len(results),
        'kr':     kr_cnt,
        'us':     us_cnt,
        'stocks': results,
    }
    with open(RESULT_PATH, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 완료: {RESULT_PATH}")
    for st in ('흑자전환완료', '흑자전환임박', '적자개선중'):
        sub = [r for r in results if r['status'] == st]
        print(f"  [{st}] {len(sub)}개")
        for r in sub[:3]:
            yoy = f"YoY{r['yoy_imp_pct']:+.0f}%" if r['yoy_imp_pct'] else ''
            rev = f" 매출YoY{r['rev_growth']:+.0f}%" if r['rev_growth'] else ''
            print(f"    {r['market']} {r['name']} ({r['sym']}) "
                  f"점수:{r['score']} Q0:{r['q0_ni']} Q-1:{r['q1_ni']} {yoy}{rev}")


if __name__ == '__main__':
    main()
