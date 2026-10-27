"""segment_xbrl.py — 미국 종목 사업부문 숫자를 **SEC XBRL 원본**에서 직접 읽는다 (2026-10-20).

왜: 부문 숫자를 Gemini 가 10-K 글에서 뽑았더니 ① 연간 보고서만 읽어 최신 분기(10-Q)가 빠졌고
   ② 숫자 품질을 보장할 길이 없었다. 부문 숫자는 공시 XBRL 에 '차원(dimension)'으로 태그돼 있다:
     Revenues / GrossProfit / OperatingIncomeLoss  ×  StatementBusinessSegmentsAxis = <부문>
     (NVDA 처럼 ConsolidationItemsAxis = OperatingSegments 가 같이 붙는 회사도 있다)
   companyfacts API 는 차원 값을 빼고 주므로, 최신 10-Q/10-K 의 XBRL 인스턴스(_htm.xml)를 직접 읽는다.

검산: 같은 기간·차원 없는 연결 매출과 부문 매출 합을 비교해 차이(%)를 돌려준다(화면에 경고로 쓴다).
AI 는 숫자에 관여하지 않는다.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import date

_REV = ('Revenues', 'RevenueFromContractWithCustomerExcludingAssessedTax',
        'RevenueFromContractWithCustomerIncludingAssessedTax', 'SalesRevenueNet')
_PROFIT = {'gross_profit': ('GrossProfit',), 'op_income': ('OperatingIncomeLoss',)}
_SEG_AXIS = 'StatementBusinessSegmentsAxis'
_PROD_AXIS = 'ProductOrServiceAxis'
_OK_EXTRA = {('ConsolidationItemsAxis', 'OperatingSegmentsMember')}     # 부문 값에 같이 붙어도 되는 차원
_SKIP_MEMBER = re.compile(r'Eliminat|Intersegment|Reconcil|Corporate|Consolidat|Adjust', re.I)


def _local(tag):
    return tag.rsplit('}', 1)[-1]


def _d(s):
    try:
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def pretty(member: str) -> str:
    """'tsla:EnergyGenerationAndStorageSegmentMember' → 'Energy Generation And Storage'."""
    m = member.split(':')[-1]
    m = re.sub(r'(Segment)?Member$', '', m)
    m = re.sub(r'Segments?$', '', m) or m
    return re.sub(r'(?<=[a-z0-9])(?=[A-Z])', ' ', m).strip()


def parse(xml_bytes) -> dict | None:
    """XBRL 인스턴스 → {period_end, form, fy, fp, periods:{'q'|'ytd'|'fy': {...}}}.
    각 기간: {start, end, days, axis, segments:[{member,name,revenue,gross_profit,op_income}], total_revenue, check_pct}"""
    root = ET.fromstring(xml_bytes)
    ctx = {}
    for c in root.iter():
        if _local(c.tag) != 'context':
            continue
        dims, st, en = [], None, None
        for e in c.iter():
            t = _local(e.tag)
            if t == 'explicitMember':
                dims.append((e.get('dimension', '').split(':')[-1], (e.text or '').strip()))
            elif t == 'startDate':
                st = _d(e.text or '')
            elif t == 'endDate':
                en = _d(e.text or '')
        ctx[c.get('id')] = (dims, st, en)

    dei, facts, conc = {}, [], []
    for el in root:
        cr = el.get('contextRef')
        if not cr:
            continue
        name = _local(el.tag)
        if el.tag.startswith('{http://xbrl.sec.gov/dei'):
            dei[name] = (el.text or '').strip()
            continue
        if name == 'ConcentrationRiskPercentage1':          # 주요 고객 비중(2026-10-23)
            dims, st, en = ctx.get(cr, ([], None, None))
            try:
                conc.append((dims, st, en, float(el.text)))
            except Exception:
                pass
            continue
        if name not in _REV and not any(name in v for v in _PROFIT.values()):
            continue
        dims, st, en = ctx.get(cr, ([], None, None))
        if not st or not en:
            continue
        try:
            val = float(el.text)
        except Exception:
            continue
        facts.append((name, dims, st, en, val))

    pe = _d(dei.get('DocumentPeriodEndDate', ''))
    if not pe:
        ends = [f[3] for f in facts]
        pe = max(ends) if ends else None
    if not pe:
        return None
    # 문서 기준일 ±7일(52-53주 회계연도) 안에서 끝나는 값만
    facts = [f for f in facts if abs((f[3] - pe).days) <= 7]

    def _bucket(st, en):
        n = (en - st).days
        if 80 <= n <= 100:
            return 'q'
        if 350 <= n <= 380:
            return 'fy'
        if 150 <= n <= 290:
            return 'ytd'
        return None

    out = {'period_end': pe.isoformat(), 'form': dei.get('DocumentType'),
           'fy': dei.get('DocumentFiscalYearFocus'), 'fp': dei.get('DocumentFiscalPeriodFocus'), 'periods': {}}
    for axis in (_SEG_AXIS, _PROD_AXIS):
        per = {}
        for name, dims, st, en, val in facts:
            b = _bucket(st, en)
            if not b:
                continue
            key = None
            if not dims:
                key = '__total__'
            else:
                main = [m for a, m in dims if a == axis]
                rest = [(a, m.split(':')[-1]) for a, m in dims if a != axis]
                if len(main) == 1 and all(r in _OK_EXTRA for r in rest) and not _SKIP_MEMBER.search(main[0]):
                    key = main[0]
            if key is None:
                continue
            p = per.setdefault(b, {'start': st, 'end': en, 'rows': {}})
            row = p['rows'].setdefault(key, {})
            if name in _REV:
                # 매출 개념이 여럿이면 우선순위 높은 것(_REV 앞쪽)만
                prev = row.get('_rev_rank')
                rank = _REV.index(name)
                if prev is None or rank < prev:
                    row['revenue'], row['_rev_rank'] = val, rank
            else:
                for k, names in _PROFIT.items():
                    if name in names:
                        row.setdefault(k, val)
        res = {}
        for b, p in per.items():
            segs = [{'member': m, 'name': pretty(m), 'revenue': r.get('revenue'),
                     'gross_profit': r.get('gross_profit'), 'op_income': r.get('op_income')}
                    for m, r in p['rows'].items() if m != '__total__' and r.get('revenue')]
            if len(segs) < 2:            # 부문 1개면 '구조'가 아니다
                continue
            segs.sort(key=lambda s: -(s['revenue'] or 0))
            tot = (p['rows'].get('__total__') or {}).get('revenue')
            ssum = sum(s['revenue'] for s in segs)
            res[b] = {'start': p['start'].isoformat(), 'end': p['end'].isoformat(),
                      'days': (p['end'] - p['start']).days, 'axis': axis, 'segments': segs,
                      'total_revenue': tot, 'seg_sum': ssum,
                      'check_pct': (ssum / tot - 1) * 100 if tot else None}
        if res:
            out['periods'] = res
            break                         # 사업부문 축이 있으면 그걸 쓰고, 없을 때만 제품 축
    # ── 지역별 매출 · 주요 고객 (2026-10-23) — 같은 공시 파일, AI 없음 ──
    try:
        out['geo'] = _geo(facts, _bucket)
        out['customers'] = _customers(conc, pe)
    except Exception:
        pass
    return out if (out['periods'] or out.get('geo') or out.get('customers')) else None


_GEO_AXIS = 'StatementGeographicalAxis'
_GEO_KO = {'US': '미국', 'CN': '중국', 'TW': '대만', 'KR': '한국', 'JP': '일본', 'DE': '독일', 'GB': '영국', 'IN': '인도',
           'CA': '캐나다', 'MX': '멕시코', 'SG': '싱가포르', 'HK': '홍콩', 'NL': '네덜란드', 'FR': '프랑스', 'IE': '아일랜드',
           'BR': '브라질', 'AU': '호주', 'IL': '이스라엘', 'CH': '스위스', 'MY': '말레이시아', 'VN': '베트남'}


def geo_name(member: str) -> str:
    m = member.split(':')
    if len(m) == 2 and m[0] == 'country':
        return _GEO_KO.get(m[1], m[1])
    n = pretty(member)
    rep = {'Non Us': '미국 외', 'Americas': '미주', 'Europe': '유럽', 'Asia Pacific': '아시아·태평양', 'EMEA': '유럽·중동·아프리카',
           'Europe Middle East And Africa': '유럽·중동·아프리카', 'Greater China': '중화권', 'Rest Of World': '기타 지역',
           'Other Countries': '기타 국가', 'Asia': '아시아', 'North America': '북미', 'Latin America': '중남미'}
    return rep.get(n, n)


def _geo(facts, bucket) -> dict | None:
    """매출 × StatementGeographicalAxis — 연간(fy) 우선, 없으면 누적(ytd)·분기(q). 지역은 회사가 겹치게 나누기도 한다
    (미주 안에 미국) → 합이 연결 매출과 다르면 check_pct 로 드러낸다."""
    per = {}
    for name, dims, st, en, val in facts:
        if name not in _REV:
            continue
        b = bucket(st, en)
        if not b:
            continue
        main = [m for a, m in dims if a == _GEO_AXIS]
        rest = [(a, m.split(':')[-1]) for a, m in dims if a != _GEO_AXIS]
        if dims and not (len(main) == 1 and all(r in _OK_EXTRA for r in rest)):
            continue
        key = main[0] if main else '__total__'
        rank = _REV.index(name)
        row = per.setdefault(b, {}).setdefault(key, (rank, val, st, en))
        if rank < row[0]:
            per[b][key] = (rank, val, st, en)
    for b in ('fy', 'ytd', 'q'):
        rows = per.get(b) or {}
        regs = [(m, v[1]) for m, v in rows.items() if m != '__total__' and v[1] > 0]
        if len(regs) < 2:
            continue
        tot = (rows.get('__total__') or (None, None))[1]
        regs.sort(key=lambda x: -x[1])
        any_v = next(iter(rows.values()))
        return {'basis': b, 'start': any_v[2].isoformat(), 'end': any_v[3].isoformat(), 'total': tot,
                'regions': [{'member': m, 'name': geo_name(m), 'revenue': v, 'pct': (v / tot * 100) if tot else None} for m, v in regs],
                'check_pct': (sum(v for _, v in regs) / tot - 1) * 100 if tot else None}
    return None


def _customers(conc, pe) -> list | None:
    """ConcentrationRiskPercentage1 × MajorCustomersAxis, 매출 기준만. 고객 이름은 대부분 'Customer A' 처럼 익명."""
    out = {}
    for dims, st, en, v in conc:
        if not en or abs((en - pe).days) > 7:
            continue
        d = {a: m for a, m in dims}
        cust = d.get('MajorCustomersAxis')
        bench = (d.get('ConcentrationRiskByBenchmarkAxis') or '').split(':')[-1]
        if not cust or not re.search(r'Revenue|Sales', bench, re.I):
            continue
        days = (en - st).days if st else 0
        k = cust
        if k not in out or days > out[k]['days']:            # 같은 고객이면 긴 기간(연간)을 쓴다
            out[k] = {'member': cust, 'name': pretty(cust), 'pct': v * 100 if v <= 1 else v, 'days': days}
    rows = sorted(out.values(), key=lambda r: -r['pct'])
    return rows or None


def latest(ticker: str) -> dict | None:
    """최신 10-Q/10-K 의 부문 숫자. {..parse.., filing:{date,form,url,acc}}. 네트워크 실패는 raise."""
    import edgar_client as E
    fl = [f for f in E.filings(ticker, limit=40) if f['form'] in ('10-Q', '10-K')]
    for f in fl[:2]:                      # 최신 것에 부문 태그가 없으면 하나 더 본다
        base = f['url'].rsplit('/', 1)[0]
        idx = E._get(base + '/index.json').json()
        names = [it['name'] for it in idx.get('directory', {}).get('item', [])]
        inst = next((n for n in names if n.endswith('_htm.xml')), None) or next(
            (n for n in names if n.endswith('.xml') and not re.search(r'_(cal|def|lab|pre)\.xml$|FilingSummary', n)), None)
        if not inst:
            continue
        r = parse(E._get(f'{base}/{inst}').content)
        if r:
            r['filing'] = {'date': f['date'], 'form': f['form'], 'url': f['url'], 'acc': base.rsplit('/', 1)[-1]}
            return r
    return None
