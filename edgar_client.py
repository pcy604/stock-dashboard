"""
SEC EDGAR API 클라이언트 — 미국 공식 재무 (DART의 미국판)
─────────────────────────────────────────────────────────────────
키 불필요. User-Agent 헤더만 필수(SEC 정책). 무료. 레이트리밋 ~10req/s.

  cik_map()          : ticker → CIK(10자리) 매핑 (company_tickers.json)
  facts(ticker)      : 연간 재무 {period: {revenue, net_income, assets, equity, eps}}
  filings(ticker)    : 최근 공시 목록 (10-K·10-Q·8-K …) — 링크 포함

CLI:
  python edgar_client.py facts AAPL
  python edgar_client.py filings AAPL 8-K
"""
import time
import json
import requests
from pathlib import Path

DATA = Path('data')
_CIK_CACHE = DATA / 'edgar_cik.json'
# SEC는 연락처 포함 User-Agent 요구 (없으면 403)
UA = {'User-Agent': 'stock-screener research pcy604604@gmail.com',
      'Accept-Encoding': 'gzip, deflate'}

# 매출은 회사마다 개념 태그가 다름 → 우선순위대로 시도
_REV = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
        'SalesRevenueNet', 'RevenueFromContractWithCustomerIncludingAssessedTax']


def _get(url, tries=4):
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=20)
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(0.4 * (i + 1))
    raise last


def cik_map(refresh=False):
    """{TICKER: cik10}. company_tickers.json 캐시."""
    if not refresh and _CIK_CACHE.exists():
        try:
            return json.loads(_CIK_CACHE.read_text(encoding='utf-8'))
        except Exception:
            pass
    j = _get("https://www.sec.gov/files/company_tickers.json").json()
    m = {v['ticker'].upper(): f"{int(v['cik_str']):010d}" for v in j.values()}
    _CIK_CACHE.write_text(json.dumps(m), encoding='utf-8')
    return m


def _annual_series(facts, concept):
    """us-gaap 개념의 연간(10-K, FY) 값 {fiscal_year: val}."""
    node = facts.get('us-gaap', {}).get(concept)
    if not node:
        return {}
    out = {}
    for unit, arr in node.get('units', {}).items():
        for x in arr:
            if x.get('form') == '10-K' and x.get('fp') == 'FY' and x.get('end'):
                out[x['end'][:4]] = x['val']       # end 날짜의 연도 기준
    return out


def facts(ticker):
    """연간 재무 {year: {revenue, net_income, assets, equity, eps}} (최신순)."""
    cik = cik_map().get(ticker.upper())
    if not cik:
        return {'_err': f'CIK 없음: {ticker}'}
    j = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
    f = j.get('facts', {})
    rev = {}
    for c in _REV:
        for y, v in _annual_series(f, c).items():
            rev.setdefault(y, v)
    ni = _annual_series(f, 'NetIncomeLoss')
    op = _annual_series(f, 'OperatingIncomeLoss')
    assets = _annual_series(f, 'Assets')
    liab = _annual_series(f, 'Liabilities')
    eq = _annual_series(f, 'StockholdersEquity')
    eps = _annual_series(f, 'EarningsPerShareDiluted')
    ocf = _annual_series(f, 'NetCashProvidedByUsedInOperatingActivities')
    icf = _annual_series(f, 'NetCashProvidedByUsedInInvestingActivities')
    fcf = _annual_series(f, 'NetCashProvidedByUsedInFinancingActivities')
    years = sorted(set(rev) | set(ni) | set(assets) | set(eq), reverse=True)
    out = {}
    for y in years:
        out[y] = {'revenue': rev.get(y), 'op_income': op.get(y), 'net_income': ni.get(y),
                  'assets': assets.get(y), 'liabilities': liab.get(y), 'equity': eq.get(y),
                  'eps': eps.get(y),
                  'op_cf': ocf.get(y), 'inv_cf': icf.get(y), 'fin_cf': fcf.get(y),
                  'roe': round(ni[y] / eq[y] * 100, 2) if (ni.get(y) and eq.get(y)) else None}
    return out


from datetime import datetime as _dt

# 통합 재무표용 개념 매핑 (우선순위대로)
_CONCEPTS = {
    'revenue':     ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet'],
    'cogs':        ['CostOfRevenue', 'CostOfGoodsAndServicesSold'],
    'gross':       ['GrossProfit'],
    'sga':         ['SellingGeneralAndAdministrativeExpense'],
    'op_income':   ['OperatingIncomeLoss'],
    'net_income':  ['NetIncomeLoss'],
    'eps':         ['EarningsPerShareDiluted'],
    'assets':      ['Assets'],
    'liabilities': ['Liabilities'],
    'equity':      ['StockholdersEquity'],
    'op_cf':       ['NetCashProvidedByUsedInOperatingActivities'],
    'inv_cf':      ['NetCashProvidedByUsedInInvestingActivities'],
    'fin_cf':      ['NetCashProvidedByUsedInFinancingActivities'],
    'capex':       ['PaymentsToAcquirePropertyPlantAndEquipment', 'PaymentsToAcquireProductiveAssets',
                    'PaymentsForCapitalImprovements', 'PaymentsToAcquireOtherPropertyPlantAndEquipment'],
}


def _series(node, freq):
    """concept node → {period_key: val}. freq='annual'(10-K, 흐름은 연간) or 'quarter'(10-Q, 3개월)."""
    if not node:
        return {}
    out = {}
    for arr in node.get('units', {}).values():
        for x in arr:
            end = x.get('end')
            if not end:
                continue
            form, start = x.get('form'), x.get('start')
            if freq == 'annual':
                if form != '10-K':
                    continue
                if start:                       # 흐름 항목: 연간 기간만
                    try:
                        if (_dt.strptime(end, '%Y-%m-%d') - _dt.strptime(start, '%Y-%m-%d')).days < 300:
                            continue
                    except Exception:
                        continue
                out[end[:4]] = x['val']         # 키=연도
            else:
                if form != '10-Q':
                    continue
                if start:                       # 흐름 항목: 3개월만(누적 제외)
                    try:
                        d = (_dt.strptime(end, '%Y-%m-%d') - _dt.strptime(start, '%Y-%m-%d')).days
                        if not (60 < d < 100):
                            continue
                    except Exception:
                        continue
                out[end[:7]] = x['val']         # 키=YYYY-MM
    return out


def statements(ticker, freq='annual', n=6):
    """통합 재무표 rows(최신순). 각 row: period + 손익/대차/현금흐름 라인아이템."""
    cik = cik_map().get(ticker.upper())
    if not cik:
        return []
    try:
        j = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
    except Exception:
        return []
    ug = j.get('facts', {}).get('us-gaap', {})
    ser = {}
    for key, concepts in _CONCEPTS.items():
        d = {}
        for c in concepts:
            for p, v in _series(ug.get(c), freq).items():
                d.setdefault(p, v)
        ser[key] = d
    keyset = set()
    for k in ('revenue', 'net_income', 'op_income', 'assets'):
        keyset |= set(ser[k])
    periods = sorted(keyset, reverse=True)[:n]
    rows = []
    for p in periods:
        g = lambda k: ser[k].get(p)
        rev, gp, cogs = g('revenue'), g('gross'), g('cogs')
        if gp is None and rev is not None and cogs is not None:
            gp = rev - cogs
        rows.append({'period': p, 'revenue': rev, 'gross': gp, 'sga': g('sga'),
                     'op_income': g('op_income'), 'net_income': g('net_income'), 'eps': g('eps'),
                     'assets': g('assets'), 'liabilities': g('liabilities'), 'equity': g('equity'),
                     'op_cf': g('op_cf'), 'inv_cf': g('inv_cf'), 'fin_cf': g('fin_cf'),
                     'capex': g('capex')})
    return rows


def filings(ticker, form=None, limit=15):
    """최근 공시 목록 [{date, form, title, url}]. form='8-K' 등으로 필터."""
    cik = cik_map().get(ticker.upper())
    if not cik:
        return []
    j = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    r = j.get('filings', {}).get('recent', {})
    cik_int = int(cik)
    out = []
    for i in range(len(r.get('accessionNumber', []))):
        if form and r['form'][i] != form:
            continue
        acc = r['accessionNumber'][i].replace('-', '')
        doc = r['primaryDocument'][i]
        out.append({'date': r['filingDate'][i], 'form': r['form'][i],
                    'title': r.get('primaryDocDescription', [''] * (i + 1))[i],
                    'url': f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc}/{doc}"})
        if len(out) >= limit:
            break
    return out


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'facts'
    tkr = sys.argv[2] if len(sys.argv) > 2 else 'AAPL'
    if cmd == 'facts':
        f = facts(tkr)
        print(f"{tkr} 연간 재무 (EDGAR 공식):")
        for y, d in list(f.items())[:5]:
            g = lambda v: f'${v/1e9:.1f}B' if isinstance(v, (int, float)) and v else '-'
            print(f"  {y}: 매출 {g(d['revenue'])} 순익 {g(d['net_income'])} "
                  f"자산 {g(d['assets'])} 자본 {g(d['equity'])} ROE {d['roe']}% EPS {d['eps']}")
    elif cmd == 'filings':
        form = sys.argv[3] if len(sys.argv) > 3 else None
        for x in filings(tkr, form=form):
            print(f"  {x['date']} [{x['form']}] {x['url']}")
