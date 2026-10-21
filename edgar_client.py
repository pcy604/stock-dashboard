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
# 대시보드가 이 값으로 '옛 모듈이 메모리에 남았는지' 판단해 다시 읽는다(코드만 바뀐 배포 대비). 동작을 바꾸면 올릴 것.
API_VERSION = 3
# SEC는 연락처 포함 User-Agent 요구 (없으면 403)
UA = {'User-Agent': 'stock-screener research pcy604604@gmail.com',
      'Accept-Encoding': 'gzip, deflate'}

# 매출은 회사마다 개념 태그가 다름 → 우선순위대로 시도
_REV = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues',
        'SalesRevenueNet', 'RevenueFromContractWithCustomerIncludingAssessedTax']


# 대화형 모드 (2026-10-17, dart_client 와 같은 이유) — 화면에서는 4회×30초를 기다리지 않는다.
_MODE = {'tries': 4, 'timeout': 30, 'interactive': False}


def set_interactive(on=True):
    _MODE.update({'tries': 2, 'timeout': (5, 20), 'interactive': True} if on
                 else {'tries': 4, 'timeout': 30, 'interactive': False})


def _get(url, tries=None):
    tries = tries or _MODE['tries']
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=_MODE['timeout'])
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            if _MODE['interactive'] and isinstance(e, requests.exceptions.Timeout):
                break
            time.sleep(0.4 * (i + 1))
    raise last


# companyfacts는 종목당 10~20MB — facts()/statements()가 같은 걸 두 번 받지 않게 메모이즈
_FACTS_MEMO = {}


def _companyfacts(cik):
    if cik not in _FACTS_MEMO:
        _FACTS_MEMO[cik] = _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json").json()
        if len(_FACTS_MEMO) > 12:                       # 메모리 보호
            _FACTS_MEMO.pop(next(iter(_FACTS_MEMO)))
    return _FACTS_MEMO[cik]


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


_NAME_CACHE = _CIK_CACHE.with_name('edgar_names.json')


def name_map(refresh=False):
    """{TICKER: 회사명}. company_tickers.json 의 title.

    2026-10-14 — us_marketcap.csv 의 Name 이 96% 티커였다('DELL', 'P'…). 그래서 CANSLIM
    US·흑자전환 표에 회사명 대신 티커만 떴고, 사명이 바뀐 종목(P = 구 Pure Storage,
    현 Everpure)은 무엇인지 알아볼 수 없었다. cik_map 과 같은 파일에 이름이 이미 있다."""
    if not refresh and _NAME_CACHE.exists():
        try:
            return json.loads(_NAME_CACHE.read_text(encoding='utf-8'))
        except Exception:
            pass
    j = _get("https://www.sec.gov/files/company_tickers.json").json()
    m = {v['ticker'].upper(): str(v.get('title') or '').strip() for v in j.values()}
    _NAME_CACHE.write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
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
    j = _companyfacts(cik)
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


def _days(a, b):
    try:
        return (_dt.strptime(b, '%Y-%m-%d') - _dt.strptime(a, '%Y-%m-%d')).days
    except Exception:
        return None


def _series(node, freq, additive=True):
    """concept node → {period_key: val}.
    annual: 10-K 연간. quarter: **모든 분기 완결** —
      · 잔액(instant): 10-Q/10-K 모두 수용 (10-Q 비교표·10-K 연말치)
      · 흐름(duration): ① 공시된 3개월 값 그대로 → ② 빈 분기만 같은 start 그룹에서 누적 차감
        (10-Q 누적 현금흐름의 3개월 환산, Q4(10-Q 미제출)=연간−9개월).
      · additive=False(EPS 등 비율): ②를 하지 않는다 — 주식수가 분기마다 달라 FY−9M 이 Q4 EPS 가
        아니다(2026-10-17: 예전에는 ②가 먼저 돌아 공시된 3개월 EPS 대신 차감값이 들어갔다)."""
    if not node:
        return {}
    if freq == 'annual':
        out = {}
        for arr in node.get('units', {}).values():
            for x in arr:
                end, form, start = x.get('end'), x.get('form'), x.get('start')
                if not end or form != '10-K':
                    continue
                if start and ((_days(start, end) or 0) < 300):
                    continue
                out[end[:4]] = x['val']
        return out

    inst, flows = {}, {}
    for arr in node.get('units', {}).values():
        for x in arr:
            end, form, start = x.get('end'), x.get('form'), x.get('start')
            if not end or form not in ('10-Q', '10-K'):
                continue
            if not start:                       # 잔액: 그대로 (분기말·연말)
                inst[end[:7]] = x['val']
            else:
                d = _days(start, end)
                if d is None or d > 400:
                    continue
                flows.setdefault(start, {}).setdefault(end, x['val'])
    if inst and not flows:
        return inst
    out = {}
    for start, m in flows.items():              # ① 공시된 3개월 값(차감 없음)이 우선
        for e, v in m.items():
            if 45 <= (_days(start, e) or 0) <= 135:
                out.setdefault(e[:7], v)
    if not additive:
        return out
    for start, m in flows.items():              # ② 빈 분기만 누적 차감 (같은 start = 같은 누적 묶음)
        prev_v, prev_end = 0.0, None
        for e in sorted(m):
            v = m[e]
            if prev_end:
                seg = _days(prev_end, e) or 0
                try:
                    if 45 <= seg <= 135:        # 3개월 구간만 채택
                        out.setdefault(e[:7], v - prev_v)
                except Exception:
                    pass
            prev_v, prev_end = v, e
    return out


def statements(ticker, freq='annual', n=6):
    """통합 재무표 rows(최신순). 각 row: period + 손익/대차/현금흐름 라인아이템."""
    cik = cik_map().get(ticker.upper())
    if not cik:
        return []
    try:
        j = _companyfacts(cik)
    except Exception:
        return []
    ug = j.get('facts', {}).get('us-gaap', {})
    ser = {}
    for key, concepts in _CONCEPTS.items():
        d = {}
        for c in concepts:
            for p, v in _series(ug.get(c), freq, additive=(key != 'eps')).items():
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
                     # Capex 는 유출 → 음수로 통일(EDGAR PaymentsToAcquire… 는 양수, DART 와 부호가 달랐다)
                     'capex': (-abs(g('capex')) if g('capex') is not None else None)})
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


def business_text(ticker, max_chars=90000):
    """최신 10-K(없으면 10-Q) 본문에서 세그먼트·손익 관련 구간 추출 (Gemini 입력용).
    문서가 크므로 'segment'·'cost of revenue'·'gross profit' 마커 주변 창을 모아 반환."""
    import re
    fl = filings(ticker, form='10-K', limit=1) or filings(ticker, form='10-Q', limit=1)
    if not fl:
        return None
    url = fl[0]['url']
    try:
        r = _get(url)
        html = r.text
    except Exception:
        return None
    txt = re.sub(r'<[^>]+>', ' ', html)
    txt = re.sub(r'&[a-zA-Z#0-9]+;', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt)
    low = txt.lower()
    # 세그먼트/손익 마커 주변 구간 수집
    markers = ['reportable segment', 'segment information', 'cost of revenue',
               'cost of revenues', 'cost of sales', 'gross profit', 'revenue by']
    spans = []
    for m in markers:
        i = 0
        while True:
            i = low.find(m, i)
            if i < 0:
                break
            spans.append((max(0, i - 1500), i + 3500))
            i += len(m)
    if not spans:
        chunk = txt[:max_chars]
    else:
        spans.sort()
        merged = [spans[0]]
        for s, e in spans[1:]:
            if s <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], e))
            else:
                merged.append((s, e))
        chunk = ' … '.join(txt[s:e] for s, e in merged)[:max_chars]
    return f"[출처: {fl[0]['form']} ({fl[0]['date']})]\n" + chunk


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


# ── Form 4 원문 — 파생상품(스톡옵션·RSU·워런트)·수령 조건·10b5-1 (2026-10-21) ─────────────
# yfinance 내부자 표는 '거래 문구'만 준다. 원문 XML 에는 거래 코드(P 장내매수·S 장내매도·A 부여·M 행사·F 세금 반납…),
# 파생상품 표(행사가·행사 가능일·만기·기초 주식 수), 각주(수령 조건), 10b5-1 계획 매매 표시(2023-04~)가 있다.
FORM4_CODE = {
    'P': '장내 매수', 'S': '장내 매도', 'A': '부여(보상)', 'M': '행사·전환(파생→주식)', 'F': '세금 납부용 반납',
    'G': '증여', 'C': '전환', 'X': '옵션 행사(내가격)', 'O': '옵션 행사(외가격)', 'D': '회사에 처분',
    'J': '기타', 'W': '상속', 'I': '재량 거래', 'K': '스왑', 'V': '자발 보고', 'E': '만료(매도 포지션)',
    'H': '만료·취소', 'Z': '신탁', 'L': '소액 취득', 'U': '공개매수 응모',
}


def classify_security(title: str) -> str:
    t = (title or '').lower()
    if 'performance' in t or 'psu' in t:
        return '성과주식(PSU)'
    if 'restricted stock unit' in t or 'rsu' in t:
        return 'RSU'
    if 'restricted' in t:
        return '제한주식'
    if 'warrant' in t:
        return '워런트'
    if 'option' in t:
        return '스톡옵션'
    if 'common' in t or 'ordinary' in t or 'class a' in t or 'class b' in t:
        return '보통주'
    return title or '-'


_NUMW = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6, 'eight': 8, 'twelve': 12, 'sixteen': 16}


def vesting_tags(text: str) -> list:
    """각주(영문)에서 수령 조건을 한국어 꼬리표로 뽑는다 — 규칙 기반(AI 무료 한도 절약). 원문은 화면에 같이 둔다."""
    import re as _re
    t = ' '.join(str(text or '').split())
    lo = t.lower()
    tags = []
    m = _re.search(r'(\d+|one|two|three|four|five|six|eight|twelve|sixteen)\s+(?:substantially\s+)?(?:equal\s+)?'
                   r'(annual|quarterly|monthly|semi-annual)\s+installments', lo)
    if m:
        n = _NUMW.get(m.group(1), m.group(1))
        tags.append(f"{n}회 균등 분할({ {'annual': '매년', 'quarterly': '분기마다', 'monthly': '매달', 'semi-annual': '반년마다'}[m.group(2)] })")
    m = _re.search(r'(\d+(?:\.\d+)?)%\s+of\s+the\s+(?:shares|units|award|option|rsus?)[^.]{0,80}?vest', lo)
    if m:
        tags.append(f"{m.group(1)}%씩 수령")
    m = _re.search(r'(first|one-year|1-year|second|two-year|third|three-year)\s+anniversary', lo)
    if m and 'installment' not in lo:
        y = {'first': 1, 'one-year': 1, '1-year': 1, 'second': 2, 'two-year': 2, 'third': 3, 'three-year': 3}[m.group(1)]
        tags.append(f"{y}년 뒤 수령(클리프)")
    m = _re.search(r'1/(\d+)(?:th|rd|nd|st)?\s+of\s+the\s+(?:total\s+)?(?:shares|units|restricted stock units|rsus?|option)[^.]{0,160}?'
                   r'every\s+(quarter|month|year)', lo)
    if m and not any('균등 분할' in x for x in tags):
        tags.append(f"{m.group(1)}회 분할({ {'quarter': '분기마다', 'month': '매달', 'year': '매년'}[m.group(2)] })")
    m = _re.search(r'fully vested (?:on|by) ([A-Za-z]+\.? \d{1,2}, \d{4})', t, _re.I)
    if m:
        tags.append(f"전부 수령 완료 {m.group(1)}")
    elif _re.search(r'(?:is|was|were|are|be) (?:immediately |)fully vested(?! on| by)|vested in full (?:upon|at|on the date of) grant|immediately vest', lo):
        tags.append('즉시 수령')
    if 'relative total shareholder return' in lo or 'relative tsr' in lo:
        tags.append('성과 조건: 상대 주주수익률(TSR)')
    elif 'performance' in lo and any(k in lo for k in ('goal', 'metric', 'criteria', 'condition', 'target')):
        tags.append('성과 조건부')
    if _re.search(r'stock price|closing price[^.]{0,60}(?:equals|exceeds|at least)', lo) and 'performance' in lo:
        tags.append('주가 목표 조건')
    if _re.search(r'continued (?:service|employment)', lo):
        tags.append('재직 조건')
    if 'change in control' in lo or 'change of control' in lo:
        tags.append('경영권 변동 시 가속 수령')
    m = _re.search(r'10b5-1[^.]{0,120}?adopted[^.]{0,60}?on\s+([A-Za-z]+\.? \d{1,2}, \d{4})', t, _re.I)
    if m:
        tags.append(f"10b5-1 계획(채택 {m.group(1)})")
    elif '10b5-1' in lo:
        tags.append('10b5-1 계획')
    if 'withh' in lo and 'tax' in lo:
        tags.append('세금 원천징수')
    if 'weighted average' in lo:
        tags.append('가중평균 체결가')
    return list(dict.fromkeys(tags))


def parse_form4(xml_text: str, url: str = '') -> list:
    """Form 4 XML(ownershipDocument) → 거래 행 리스트."""
    import xml.etree.ElementTree as ET
    root = ET.fromstring(xml_text.encode('utf-8') if isinstance(xml_text, str) else xml_text)

    def tx(node, path):
        e = node.find(path) if node is not None else None
        if e is None:
            return None
        v = e.find('value')
        s = (v.text if v is not None else e.text) or ''
        return s.strip() or None

    def num(node, path):
        s = tx(node, path)
        try:
            return float(s.replace(',', '')) if s else None
        except ValueError:
            return None

    fn = {f.get('id'): ' '.join((f.text or '').split()) for f in root.iter('footnote')}
    owners = []
    for ro in root.findall('reportingOwner'):
        rel = ro.find('reportingOwnerRelationship')
        role = []
        if rel is not None:
            if (tx(rel, 'isDirector') or '').lower() in ('1', 'true'):
                role.append('이사')
            if (tx(rel, 'isOfficer') or '').lower() in ('1', 'true'):
                role.append(tx(rel, 'officerTitle') or '임원')
            if (tx(rel, 'isTenPercentOwner') or '').lower() in ('1', 'true'):
                role.append('10% 주주')
        owners.append((tx(ro, 'reportingOwnerId/rptOwnerName') or '-', ' · '.join(role) or '-'))
    owner, role = owners[0] if owners else ('-', '-')
    plan = (tx(root, 'aff10b5One') or '').lower() in ('1', 'true')
    rows = []
    for tbl, kind in (('nonDerivativeTable/nonDerivativeTransaction', '주식'),
                      ('derivativeTable/derivativeTransaction', '파생')):
        for t in root.findall(tbl):
            ids = [f.get('id') for f in t.iter('footnoteId')]
            notes = ' '.join(fn.get(i, '') for i in dict.fromkeys(ids))
            code = tx(t, 'transactionCoding/transactionCode')
            title = tx(t, 'securityTitle')
            rows.append({
                'date': tx(t, 'transactionDate'), 'owner': owner, 'role': role, 'table': kind,
                'security': title, 'sec_kind': classify_security(title), 'code': code,
                'code_label': FORM4_CODE.get(code or '', code or '-'),
                'shares': num(t, 'transactionAmounts/transactionShares'),
                'price': num(t, 'transactionAmounts/transactionPricePerShare'),
                'ad': tx(t, 'transactionAmounts/transactionAcquiredDisposedCode'),
                'after': num(t, 'postTransactionAmounts/sharesOwnedFollowingTransaction'),
                'exercise_price': num(t, 'conversionOrExercisePrice'),
                'exercisable': tx(t, 'exerciseDate'), 'expiration': tx(t, 'expirationDate'),
                'underlying': num(t, 'underlyingSecurity/underlyingSecurityShares'),
                'plan_10b5_1': plan or ('10b5-1' in notes), 'notes': notes, 'tags': vesting_tags(notes), 'url': url})
    return rows


def form4_transactions(ticker, days=365, limit=30, workers=6):
    """최근 Form 4 원문을 받아 거래 행으로. 발행사 submissions 의 '4'·'4/A'(최신순)에서 limit 건."""
    from concurrent.futures import ThreadPoolExecutor
    from datetime import date, timedelta
    cik = cik_map().get(ticker.upper())
    if not cik:
        return []
    j = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()
    r = j.get('filings', {}).get('recent', {})
    cut = (date.today() - timedelta(days=days)).isoformat()
    jobs = []
    for i in range(len(r.get('accessionNumber', []))):
        if r['form'][i] not in ('4', '4/A') or r['filingDate'][i] < cut:
            continue
        doc = r['primaryDocument'][i].split('/')[-1]          # 'xslF345X05/form4.xml' → 원문 'form4.xml'
        acc = r['accessionNumber'][i].replace('-', '')
        jobs.append(f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc}/{doc}")
        if len(jobs) >= limit:
            break

    def one(u):
        try:
            return parse_form4(_get(u).text, u.replace(u.split('/')[-1], ''))
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(one, jobs))
    if jobs and sum(1 for x in res if x is None) > len(jobs) * 0.5:
        raise RuntimeError(f"Form 4 원문 {len(jobs)}건 중 절반 넘게 실패")
    out = [row for x in res if x for row in x]
    out.sort(key=lambda x: x['date'] or '', reverse=True)
    return out
