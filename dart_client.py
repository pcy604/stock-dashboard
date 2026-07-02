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
    'revenue':    ['매출액', '수익(매출액)', '영업수익'],
    'op_income':  ['영업이익'],
    'net_income': ['당기순이익'],
    'equity':     ['자본총계'],
    'assets':     ['자산총계'],
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
