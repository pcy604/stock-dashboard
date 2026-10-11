"""
turnaround_run.py  —  흑자전환 스크리너
'테슬라 2019 Q3' 같은 종목 발굴
  - 흑자전환완료: 최근 1-2분기 흑자 + 직전 연속 적자
  - 흑자전환임박: 적자 지속이나 YoY 50%+ 개선 중
  - 적자개선중:   YoY 25~50% 개선 중

실행: python turnaround_run.py
결과: results/turnaround_latest.json
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')   # 2026-10-10: print 의 ✅ 하나로 죽었다

import json, time, socket, warnings, os
import pandas as pd
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
# ══════════════════════════════════════════════════════════════════
# 재무 소스: yfinance → DART(KR) · SEC EDGAR(US)   [2026-10-12 교체]
# ──────────────────────────────────────────────────────────────────
# 왜 바꿨나: yfinance 의 quarterly_financials 가 **전 종목 빈 값**을 준다.
#   실측 005930.KS / 000660.KS / AAPL 모두 shape=(0,0). 그래서 1,395종을
#   전부 훑고 0종이 나왔고, 파일 날짜만 신선한 채 한 달을 갔다.
#   우리 코드 문제가 아니라 외부 API 가 죽은 것이라 소스를 갈아끼운다.
#
# 아래 두 함수는 yfinance 와 **같은 모양**을 돌려준다
#   (index = 계정명, columns = 기간, 최신이 앞). 그래야 분류 로직을
#   손대지 않는다 — 검증된 판정식을 건드리는 게 가장 위험하다.
#
# ⚠️ KR 은 DART 가 1~3Q 를 당분기(3개월)로, 4Q 를 사업보고서(누적 FY)로 준다.
#    ingest_dart_quarterly.quarterly() 가 Q4 = FY − (Q1+Q2+Q3) 로 차분해 주므로
#    그걸 쓴다. 직접 pivot 하면 4분기가 연간값으로 섞여 흑자전환 판정이 통째로
#    틀어진다.
# ⚠️ DART 주요계정 API 에는 **매출총이익이 없다.** 그래서 KR 은 gm_improving
#    보너스(+1)가 항상 False 다. US(EDGAR)는 gross 가 있어 정상 동작한다.
#    점수가 시장 간 1점 차이로 비교되지 않게 화면 캡션에 적는다.
_KRQ = {}


def _kr_quarterly_all():
    """{sym: DataFrame} — DART 분기 손익. 한 번만 만들어 캐시한다."""
    global _KRQ
    if _KRQ:
        return _KRQ
    try:
        import ingest_dart_quarterly as Q
        d = Q.quarterly()
        if d is None or d.empty:
            print('  [KR] DART 분기재무가 비어 있다')
            return {}
        d = d.dropna(subset=['net_income'])
        d['_end'] = pd.to_datetime(
            d.year.astype(int).astype(str) + '-' + (d.q.astype(int) * 3).astype(str) + '-01')
        for sym, g in d.groupby('sym'):
            _KRQ[str(sym)] = g.sort_values('_end', ascending=False)
        print(f'  [KR] DART 분기재무 {len(_KRQ):,}종 적재')
    except Exception as e:
        print(f'  [KR] DART 적재 실패: {str(e)[:100]}')
    return _KRQ


def fetch_quarterly_fin(sym_yf: str):
    """yfinance 형식(index=계정명, columns=기간 최신순)으로 분기 손익을 돌려준다.

    소스만 DART/EDGAR 로 바뀌었고 반환 모양은 그대로다.
    """
    try:
        if sym_yf.endswith('.KS') or sym_yf.endswith('.KQ'):
            sym = sym_yf.split('.')[0]
            g = _kr_quarterly_all().get(sym)
            if g is None or g.empty:
                return None
            cols = list(g['_end'])
            data = {
                'Net Income':    [None if pd.isna(v) else float(v) for v in g['net_income']],
                'Total Revenue': [None if pd.isna(v) else float(v) for v in g['revenue']],
            }
            return pd.DataFrame(data, index=cols).T
        # ── US: EDGAR 분기재무 캐시 (leaders_build.fetch_fund 가 만든다) ──
        fp = os.path.join('data', 'leaders_cache', f'fq_{sym_yf}.csv')
        if not os.path.exists(fp):
            return None
        d = pd.read_csv(fp)
        if d.empty or 'netinc' not in d.columns:
            return None
        d['period_end'] = pd.to_datetime(d.period_end, errors='coerce')
        d = d.dropna(subset=['period_end']).sort_values('period_end', ascending=False)
        cols = list(d.period_end)
        data = {'Net Income': [None if pd.isna(v) else float(v) for v in d.netinc],
                'Total Revenue': [None if pd.isna(v) else float(v) for v in d.revenue]}
        if 'gross' in d.columns:
            data['Gross Profit'] = [None if pd.isna(v) else float(v) for v in d.gross]
        return pd.DataFrame(data, index=cols).T
    except Exception:
        return None


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
