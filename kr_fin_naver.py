"""
KR 재무제표 — 네이버 기업분석(navercomp.wisereport · FnGuide 집계) · 2026-10-17
─────────────────────────────────────────────────────────────────
왜: DART 가 해외 서버(Streamlit Cloud·GitHub Actions)의 연결을 받지 않는다(ConnectTimeout).
    이 소스는 해외 서버에서 닿는다(`?diag=net` 실측) → **집 PC 없이** 대차대조표·현금흐름표까지.

공시 대조(사람이 원문과 맞춘 결과 — tests/test_kr_fin_naver.py 에 고정):
  · 삼성전자 FY24·FY25 매출·매출총이익·판관비·영업이익·순이익·EPS·자산·부채·자본·영업CF·재무CF·Capex
    = IR 확정치 일치. 4Q25·3Q25·2Q26 분기 손익·자산·영업CF(3개월)·Capex(3개월) 일치.
  · SK하이닉스·삼양식품·에이피알 분기 매출·영업이익·순이익 = 저장된 DART 값 일치.

격자 함정 2개 (같은 이름, 다른 숫자):
  ① '영업이익' 은 FnGuide **표준화** 값이다. 회사 발표와 다를 수 있다
     (에이피알 2Q26: 표준화 1,855억 vs 발표·DART 1,906억). → '영업이익(발표기준)' 우선.
  ② 'CAPEX'(재무상태 묶음의 *CAPEX)는 분기 열이 **연초부터 누적**이다(삼성 2025/12 = 연간 47.5조).
     현금흐름표의 '유형자산의증가' 는 분기 3개월치 → 이것을 쓴다.
  참고: 삼성 IR 요약표의 '투자활동 현금흐름'은 순현금(단기금융상품 포함) 기준이라 법정 현금흐름표와 다르다
     (FY24 IR −53.4조 vs 법정 −85.4조). 이 모듈은 법정(공시) 값이다.

단위: 금액은 원(억원 × 1e8), EPS 는 원. 행 키는 dart_client.statements 와 같다.
"""
import re
import time

import requests

BASE = 'https://navercomp.wisereport.co.kr/v2/company'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
TIMEOUT = (5, 15)

# rpt: 0=손익 1=재무상태 2=현금흐름. 이름은 앞의 '....'(들여쓰기)를 뗀 계정명, 앞쪽이 우선.
_MAP = {
    0: {'revenue': ['매출액(수익)'], 'cogs': ['매출원가'], 'gross': ['매출총이익'],
        'sga': ['판매비와관리비'], 'op_income': ['영업이익(발표기준)', '영업이익'],
        'net_income': ['당기순이익'], 'eps': ['*(지배주주지분)주당순이익', '*주당순이익']},
    1: {'assets': ['자산총계'], 'liabilities': ['부채총계'], 'equity': ['자본총계']},
    2: {'op_cf': ['영업활동으로인한현금흐름'], 'inv_cf': ['투자활동으로인한현금흐름'],
        'fin_cf': ['재무활동으로인한현금흐름'], 'capex': ['유형자산의증가']},
}
_PER_SHARE = {'eps'}            # 억원 환산하지 않는 항목


def _num(v):
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', ''))
    except Exception:
        return None


def _period(yymm, freq):
    """'2026/06' → '2026.2Q'(분기) / '2025/12' → '2025'(연간). dart_client 와 같은 표기."""
    y, m = int(yymm[:4]), int(yymm[5:7])
    return str(y) if freq == 'annual' else f'{y}.{(m - 1) // 3 + 1}Q'


def parse(report_json, rpt, freq):
    """cF3002 응답 1개 → {period: {key: value}} (실적 열만 — 추정(E)·증감 열 제외)."""
    yymm = [re.sub(r'<.*', '', str(y)).strip() for y in report_json.get('YYMM') or []]
    idx = [i for i, y in enumerate(yymm) if re.fullmatch(r'\d{4}/\d{2}', y)]
    rows = report_json.get('DATA') or []
    by_name = {}
    for d in rows:                                    # 같은 이름이면 윗단계(LVL 작은 쪽)가 이긴다
        nm = str(d.get('ACC_NM') or '').lstrip('.').strip()
        if nm not in by_name or (d.get('LVL') or 9) < (by_name[nm].get('LVL') or 9):
            by_name[nm] = d
    out = {_period(yymm[i], freq): {} for i in idx}
    for key, names in _MAP[rpt].items():
        mult = 1.0 if key in _PER_SHARE else 1e8
        series = [[_num(by_name[nm].get(f'DATA{i + 1}')) for i in idx] for nm in names if nm in by_name]
        series = [s for s in series if any(v is not None for v in s)]
        if not series:
            continue
        for j, i in enumerate(idx):
            v = series[0][j]
            if v is None and key in _PER_SHARE:       # EPS: 지배주주 EPS 가 빈 칸이면 같은 기간의 기본 EPS 로
                v = next((s[j] for s in series[1:] if s[j] is not None), None)   # (삼성 1Q26: 지배 '-', 기본 7,123)
            out[_period(yymm[i], freq)][key] = (v * mult) if v is not None else None
    return out


def _session(code):
    s = requests.Session()
    s.headers.update(UA)
    url = f'{BASE}/c1030001.aspx?cmp_cd={code}'
    r = s.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    m = re.search(r"encparam\s*[:=]\s*['\"]([^'\"]+)['\"]", r.text)
    if not m:
        raise RuntimeError('네이버 기업분석: encparam 없음(페이지 구조 변경?)')
    return s, m.group(1), url


def _report(s, enc, referer, code, frq, rpt):
    r = s.get(f'{BASE}/cF3002.aspx', timeout=TIMEOUT, headers={'Referer': referer},
              params={'cmp_cd': code, 'frq': frq, 'rpt': rpt, 'finGubun': 'MAIN',
                      'frqTyp': frq, 'cn': '', 'encparam': enc})
    r.raise_for_status()
    return r.json()


def statements(code, freq='annual', n=5):
    """dart_client.statements 와 같은 모양의 rows(최신순). 실패 시 예외(호출부가 폴백)."""
    code = str(code).zfill(6)
    frq = 0 if freq == 'annual' else 1
    s, enc, ref = _session(code)
    merged = {}
    for rpt in (0, 1, 2):
        for p, kv in parse(_report(s, enc, ref, code, frq, rpt), rpt, freq).items():
            merged.setdefault(p, {}).update(kv)
        time.sleep(0.15)                              # 연달아 두드리지 않는다
    rows = []
    for p in sorted(merged, key=_order, reverse=True):
        e = {k: merged[p].get(k) for k in ('revenue', 'cogs', 'gross', 'sga', 'op_income', 'net_income',
                                           'eps', 'assets', 'liabilities', 'equity',
                                           'op_cf', 'inv_cf', 'fin_cf', 'capex')}
        if all(e[k] is None for k in ('revenue', 'op_income', 'net_income', 'assets')):
            continue
        if e['capex'] is not None:
            e['capex'] = -abs(e['capex'])            # 유출 = 음수 (dart/edgar 와 통일)
        e['period'] = p
        e['_src'] = 'naver'
        rows.append(e)
    if not rows:
        raise RuntimeError(f'네이버 기업분석: {code} 재무 없음')
    return rows[:n]


def _order(p):
    return (int(p[:4]), int(p[5]) if '.' in p else 9)


if __name__ == '__main__':
    import sys
    for fq in ('annual', 'quarter'):
        for r in statements(sys.argv[1] if len(sys.argv) > 1 else '005930', fq):
            print(fq, r['period'], {k: (round(v / 1e8) if isinstance(v, float) and k != 'eps' else v)
                                    for k, v in r.items() if k not in ('period', '_src')})


def consensus(code, this_year=None):
    """연간 손익의 추정(E) 열 → {'eps_0y','op_0y','eps_1y','op_1y'} (EPS 원 · 영업이익 억원).

    2026-10-19 — 컨센서스 스냅샷은 finance.naver.com 종목 메인의 '기업실적분석' 표를 긁었는데,
    해외 러너에는 같은 주소가 그 표 없이(130KB) 내려와 07-24 이후 석 달간 0종목이었다.
    이 API(navercomp.wisereport)는 해외 러너에서도 닿고(KR 분기재무가 이미 쓴다) 같은 FnGuide 추정치를 준다.
    12월 결산이 아닌 회사의 추정 열(예: 2027/03(E))은 연도 대응이 달라 받지 않는다.
    """
    this_year = this_year or __import__('datetime').date.today().year
    s, enc, ref = _session(code)
    js = _report(s, enc, ref, code, 0, 0)
    yymm = [re.sub(r'<.*', '', str(y)).strip() for y in js.get('YYMM') or []]
    est = {i: int(y[:4]) for i, y in enumerate(yymm) if re.fullmatch(r'\d{4}/12\(E\)', y)}
    if not est:
        return None
    by = {}
    for d in js.get('DATA') or []:
        nm = str(d.get('ACC_NM') or '').lstrip('.').strip()
        if nm not in by or (d.get('LVL') or 9) < (by[nm].get('LVL') or 9):
            by[nm] = d
    out = {}
    for i, yr in est.items():
        lab = '0y' if yr <= this_year else ('1y' if yr == this_year + 1 else None)
        if not lab:
            continue
        for key, names in (('eps', ['*(지배주주지분)주당순이익', '*주당순이익']),
                           ('op', ['영업이익(발표기준)', '영업이익'])):
            v = next((_num(by[n].get(f'DATA{i + 1}')) for n in names
                      if n in by and _num(by[n].get(f'DATA{i + 1}')) is not None), None)
            if v is not None:
                out[f'{key}_{lab}'] = v
    return out or None
