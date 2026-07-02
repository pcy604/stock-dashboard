"""
OpenDART(전자공시) API 클라이언트 — 공식 재무제표
─────────────────────────────────────────────────────────────────
키 파일: data/.dart_key  (opendart.fss.or.kr 에서 무료 발급, 만료 없음)
무료 한도: 하루 20,000회.

핵심 기능:
  corp_map()                     : 종목코드(6자리) → DART corp_code 매핑 (corpCode.zip 파싱)
  financials(corp_code, year, q) : 단일회사 주요재무 (매출·영업익·순익·자본·자산)

CLI:
  python dart_client.py map                 # 매핑 개수 확인
  python dart_client.py fin 005930 2024     # 삼성전자 2024 사업보고서 재무
"""
import io
import time
import json
import zipfile
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

DATA = Path('data')
_KEY_F = DATA / '.dart_key'
_CORP_CACHE = DATA / 'dart_corpmap.json'
BASE = "https://opendart.fss.or.kr/api"

# 사업보고서=11011(연간) · 반기=11012 · 1Q=11013 · 3Q=11014
REPRT = {'annual': '11011', 'half': '11012', 'q1': '11013', 'q3': '11014'}

# 재무 항목 매칭(계정명에 포함되면 채택). IFRS 표기 변형 대응.
_ACCOUNTS = {
    'revenue':     ['매출액', '수익(매출액)', '영업수익'],
    'op_income':   ['영업이익'],
    'net_income':  ['당기순이익'],
    'equity':      ['자본총계'],
    'assets':      ['자산총계'],
    'liabilities': ['부채총계'],
}


def _key():
    import os
    k = ''
    try:
        k = _KEY_F.read_text(encoding='utf-8').strip()
    except Exception:
        k = ''
    if not k:                       # 배포 환경: 파일 없으면 환경변수(Streamlit secrets)
        k = (os.environ.get('DART_KEY') or '').strip()
    if not k:
        raise RuntimeError("DART 키 없음 → data/.dart_key 파일 또는 환경변수 DART_KEY")
    return k


def corp_map(refresh=False):
    """{stock_code(6자리): corp_code(8자리)} 반환. 캐시 사용."""
    if not refresh and _CORP_CACHE.exists():
        try:
            return json.loads(_CORP_CACHE.read_text(encoding='utf-8'))
        except Exception:
            pass
    r = _get(f"{BASE}/corpCode.xml", {'crtfc_key': _key()})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    xml = zf.read(zf.namelist()[0]).decode('utf-8')
    root = ET.fromstring(xml)
    m = {}
    for e in root.iter('list'):
        sc = (e.findtext('stock_code') or '').strip()
        cc = (e.findtext('corp_code') or '').strip()
        if sc and len(sc) == 6 and sc.isdigit() and cc:
            m[sc] = cc
    _CORP_CACHE.write_text(json.dumps(m, ensure_ascii=False), encoding='utf-8')
    return m


def _to_num(s):
    try:
        return float(str(s).replace(',', '').strip())
    except Exception:
        return None


def _get(url, params, tries=6):
    """전송 재시도(DART가 연속 호출 시 keep-alive 연결을 끊음 → Connection: close + 백오프)."""
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=20,
                             headers={'Connection': 'close'})
            r.raise_for_status()
            return r
        except Exception as e:
            last = e
            time.sleep(min(0.6 * (i + 1), 3.0))
    raise last


def financials(corp_code, year, period='annual'):
    """단일회사 주요재무. 반환: {revenue, op_income, net_income, equity, assets} (원)."""
    r = _get(f"{BASE}/fnlttSinglAcnt.json",
             {'crtfc_key': _key(), 'corp_code': corp_code,
              'bsns_year': str(year), 'reprt_code': REPRT.get(period, '11011')})
    j = r.json()
    if j.get('status') != '000':
        return {'_status': j.get('status'), '_msg': j.get('message')}
    out = {k: None for k in _ACCOUNTS}
    for row in j.get('list', []):
        # 연결(CFS) 우선, 없으면 개별(OFS)
        nm = row.get('account_nm', '')
        val = _to_num(row.get('thstrm_amount'))
        for key, names in _ACCOUNTS.items():
            if out[key] is None and any(n in nm for n in names):
                # 연결재무제표 우선
                if row.get('fs_div', 'CFS') == 'CFS' or out[key] is None:
                    out[key] = val
    return out


_YOY_KEYS = {'net_income': ['당기순이익'], 'revenue': ['매출액', '수익(매출액)', '영업수익'],
             'op_income': ['영업이익']}


def financials_yoy(corp_code, year, period='annual'):
    """IS 항목의 당기 + 전년동기(frmtrm). {net_income, net_income_prev, revenue, ...}.
    DART 보고서가 전년동기 컬럼을 주므로 1콜로 YoY 계산 가능. 연결(CFS) 우선."""
    try:
        j = _get(f"{BASE}/fnlttSinglAcnt.json",
                 {'crtfc_key': _key(), 'corp_code': corp_code, 'bsns_year': str(year),
                  'reprt_code': REPRT.get(period, '11011')}).json()
    except Exception:
        return {}
    if j.get('status') != '000':
        return {}
    out = {}
    for pref in ('CFS', 'OFS'):        # 연결 우선, 없으면 개별
        for row in j.get('list', []):
            if row.get('fs_div') != pref:
                continue
            nm = row.get('account_nm', '')
            for key, names in _YOY_KEYS.items():
                if key not in out and any(n in nm for n in names):
                    out[key] = _to_num(row.get('thstrm_amount'))
                    out[key + '_prev'] = _to_num(row.get('frmtrm_amount'))
        if out:
            break
    return out


def _yoy_pct(cur, prev):
    """YoY %. 전년 적자면 '흑자전환'(흑자일 때)/None, 0이면 None."""
    if cur is None or prev is None or prev == 0:
        return None
    if prev < 0:
        return '흑자전환' if cur > 0 else None
    return round((cur / prev - 1) * 100, 1)


def canslim_growth(corp_code):
    """CANSLIM C·A용 공식 성장률. 반환:
    {c_growth(최근분기 순익 YoY), a_growth_y1, a_growth_y2(연간 순익 YoY), rev_growth, op_growth}."""
    from datetime import datetime as _dt
    y = _dt.now().year
    out = {'c_growth': None, 'a_growth_y1': None, 'a_growth_y2': None,
           'rev_growth': None, 'op_growth': None}
    # C: 최근 확정 분기(누적) 순이익 YoY
    for yy in (y, y - 1):
        for per in ('q3', 'half', 'q1'):
            fy = financials_yoy(corp_code, yy, per)
            if fy.get('net_income') is not None and fy.get('net_income_prev') is not None:
                out['c_growth'] = _yoy_pct(fy['net_income'], fy['net_income_prev'])
                break
        if out['c_growth'] is not None:
            break
    # A: 최근 확정 연도(Y-1) 사업보고서 → 순익/매출/영업익 YoY(g1), 그리고 Y-2 → g2
    a1 = financials_yoy(corp_code, y - 1, 'annual')
    if a1:
        out['a_growth_y1'] = _yoy_pct(a1.get('net_income'), a1.get('net_income_prev'))
        out['rev_growth'] = _yoy_pct(a1.get('revenue'), a1.get('revenue_prev'))
        out['op_growth'] = _yoy_pct(a1.get('op_income'), a1.get('op_income_prev'))
    a2 = financials_yoy(corp_code, y - 2, 'annual')
    if a2:
        out['a_growth_y2'] = _yoy_pct(a2.get('net_income'), a2.get('net_income_prev'))
    return out


def insiders(corp_code, limit=15):
    """임원·주요주주 특정증권 소유변동(내부자 매수/매도).
    [{date, name, position, change, holdings}] 최신순. change>0=취득 <0=처분."""
    try:
        j = _get(f"{BASE}/elestock.json", {'crtfc_key': _key(), 'corp_code': corp_code}).json()
    except Exception:
        return []
    if j.get('status') != '000':
        return []
    rows = []
    for x in j.get('list', []):
        rows.append({'date': x.get('rcept_dt'), 'name': x.get('repror'),
                     'position': x.get('isu_exctv_ofcps') or x.get('isu_main_shrholdr') or '-',
                     'change': _to_num(x.get('sp_stock_lmp_irds_cnt')),
                     'holdings': _to_num(x.get('sp_stock_lmp_cnt'))})
    rows.sort(key=lambda r: (r['date'] or ''), reverse=True)
    return rows[:limit]


_CF = {'op_cf': '영업활동', 'inv_cf': '투자활동', 'fin_cf': '재무활동'}


def cashflow(corp_code, year, period='annual'):
    """현금흐름표 {op_cf, inv_cf, fin_cf} (원). fnlttSinglAcntAll(전체재무제표) 사용."""
    out = {k: None for k in _CF}
    for fs in ('CFS', 'OFS'):        # 연결 우선, 없으면 개별
        try:
            r = _get(f"{BASE}/fnlttSinglAcntAll.json",
                     {'crtfc_key': _key(), 'corp_code': corp_code, 'bsns_year': str(year),
                      'reprt_code': REPRT.get(period, '11011'), 'fs_div': fs})
            j = r.json()
        except Exception:
            continue
        if j.get('status') != '000':
            continue
        for row in j.get('list', []):
            if row.get('sj_div') != 'CF':
                continue
            nm = row.get('account_nm', '')
            for key, kw in _CF.items():
                if out[key] is None and kw in nm:
                    out[key] = _to_num(row.get('thstrm_amount'))
        if any(out.values()):
            break
    return out


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'map'
    if cmd == 'map':
        m = corp_map()
        print(f"✅ corp_map: {len(m)}개 상장사 매핑")
        for c in ['005930', '000660', '009150']:
            print(f"  {c} -> {m.get(c)}")
    elif cmd == 'fin':
        code = sys.argv[2] if len(sys.argv) > 2 else '005930'
        year = sys.argv[3] if len(sys.argv) > 3 else '2024'
        cc = corp_map().get(code)
        print(f"{code} (corp_code={cc}) {year} 사업보고서:")
        print(json.dumps(financials(cc, year), ensure_ascii=False, indent=2))
