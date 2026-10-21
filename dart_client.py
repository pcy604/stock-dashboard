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
import re
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
# 대시보드가 이 값으로 '옛 모듈이 메모리에 남았는지' 판단해 다시 읽는다(코드만 바뀐 배포 대비). 동작을 바꾸면 올릴 것.
API_VERSION = 4

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


def _match(pairs, names):
    """계정명 매칭 — **정확일치 우선**, 없을 때만 부분일치.

    부분일치를 먼저 하면 DART 재무상태표에 '부채총계'보다 앞서 실리는
    **'자본과부채총계'**(=자산총계와 같은 값)가 `'부채총계' in nm`에 걸려
    부채총계 자리를 차지한다. 에코프로비엠 2026.2Q 실측 — 참값 부채 3.33조인데
    5.43조(=자산총계)로 기록되고 있었다. 자산=부채+자본이 깨지므로
    부채비율·부채/자본 지표가 전부 틀린다.
    (`자본총계`는 '자본과부채총계'의 부분문자열이 아니라 영향 없었음.)

    pairs = [(공백제거 계정명, 값)] 문서 순서. 정확일치도 문서 순서로 첫 건을
    쓰므로 기존 동작(BS의 자본총계가 SCE의 자본총계보다 먼저)은 그대로 유지된다."""
    for nm, val in pairs:
        if nm in names:
            return val
    for nm, val in pairs:
        if any(n in nm for n in names):
            return val
    return None


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


# ── 대화형 모드 + 회로 차단기 (2026-10-17) ─────────────────────────────
# 배치(CI)는 6회×20초 재시도로 끈질기게 받는 게 맞다. 그런데 **사람이 기다리는 화면**에서
# 같은 설정이면, DART 가 응답을 안 할 때 호출 1건이 2분+ 이고 분기표 1장이 10~24건이라
# '연간/분기' 버튼을 눌러도 몇 분간 아무 변화가 없다(2026-10-17 Streamlit Cloud 실측:
# _official_cached 2.5분 후 실패 → 공식 재무제표 섹션 자체가 안 뜸).
#   · set_interactive(True): 2회 × (연결 5초, 읽기 12초). 타임아웃은 재시도하지 않는다.
#   · 차단기: 대화형에서 연속 2건 실패 → 5분간 네트워크를 건너뛰고 즉시 실패(화면이 매번 기다리지 않게).
#   · health(): 마지막 실패 사유 — 화면에 '왜 없는지'를 정직하게 적기 위해.
_MODE = {'tries': 6, 'timeout': 20, 'interactive': False}
_HEALTH = {'fails': 0, 'open_until': 0.0, 'last_error': None, 'last_ok': None}


def set_interactive(on=True):
    _MODE.update({'tries': 2, 'timeout': (3, 12), 'interactive': True} if on
                 else {'tries': 6, 'timeout': 20, 'interactive': False})


def health():
    """{'ok': bool, 'blocked_sec': 남은 차단 초, 'last_error': str|None}"""
    left = max(0.0, _HEALTH['open_until'] - time.time())
    return {'ok': left == 0 and _HEALTH['fails'] == 0, 'blocked_sec': int(left),
            'last_error': _HEALTH['last_error']}


def _get(url, params, tries=None):
    """전송 재시도(DART가 연속 호출 시 keep-alive 연결을 끊음 → Connection: close + 백오프)."""
    if time.time() < _HEALTH['open_until']:
        raise RuntimeError(f"DART 응답 없음 — 잠시 건너뜀(최근 실패: {_HEALTH['last_error']})")
    tries = tries or _MODE['tries']
    last = None
    for i in range(tries):
        try:
            r = requests.get(url, params=params, timeout=_MODE['timeout'],
                             headers={'Connection': 'close'})
            r.raise_for_status()
            _HEALTH.update(fails=0, last_ok=time.time())
            return r
        except Exception as e:
            last = e
            # 응답 없는 서버(타임아웃)는 대화형이면 즉시, 배치면 두 번째에서 포기 — 연결 끊김(reset)만 끈질기게
            if isinstance(e, requests.exceptions.Timeout) and (_MODE['interactive'] or i >= 1):
                break
            time.sleep(min(0.6 * (i + 1), 3.0))
    _HEALTH['fails'] += 1
    # 예외 문구에 요청 URL(쿼리에 crtfc_key)이 실린다 — 화면·로그에 키가 새지 않게 URL 을 지운다
    _HEALTH['last_error'] = re.sub(r'url: \S+', 'url: (생략)', f'{type(last).__name__}: {last}')[:140]
    # 차단기: 2026-10-15~ DART 가 해외 서버(Streamlit Cloud·GitHub Actions)의 연결을 받지 않는다
    #   (ConnectTimeout 실측). 배치에서도 막아야 CI 가 호출마다 2분씩 기다리다 55분 제한에 잘리지 않는다
    #   (10-16 daily-refresh 취소 — CANSLIM KR 단계 9분 → 48분+). 실패 시 호출부는 네이버 폴백으로 간다.
    if _HEALTH['fails'] >= (2 if _MODE['interactive'] else 3):
        # 대화형 30분: 클라우드에서는 DART 가 '계속' 막혀 있어 5분마다 다시 두드리면 그때마다 첫 조회가 6초 늦다
        _HEALTH['open_until'] = time.time() + (1800 if _MODE['interactive'] else 3600)
    raise last


def financials(corp_code, year, period='annual'):
    """단일회사 주요재무. 반환: {revenue, op_income, net_income, equity, assets} (원)."""
    r = _get(f"{BASE}/fnlttSinglAcnt.json",
             {'crtfc_key': _key(), 'corp_code': corp_code,
              'bsns_year': str(year), 'reprt_code': REPRT.get(period, '11011')})
    j = r.json()
    if j.get('status') != '000':
        return {'_status': j.get('status'), '_msg': j.get('message')}
    # 연결(CFS) 우선, 없으면 개별(OFS) — DART가 응답에서 CFS를 먼저 실어주므로 문서 순서로 충분
    pairs = [((row.get('account_nm') or '').replace(' ', '').strip(),
              _to_num(row.get('thstrm_amount'))) for row in j.get('list', [])]
    return {key: _match(pairs, names) for key, names in _ACCOUNTS.items()}


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


_STMT_KEYS = {
    'revenue':     ['매출액', '수익(매출액)', '영업수익'],
    'gross':       ['매출총이익'],
    # 분기·반기보고서의 순이익 명칭. '반기손이익(손실)'은 오타가 아니라 에코프로비엠이
    # 실제로 그렇게 제출한 계정명이고 DART가 원문 그대로 넘긴다(2026 반기 실측) —
    # 제출자 표기 흔들림을 목록으로 흡수한다.
    'net_income_q': ['분기순이익', '반기순이익', '분기손이익', '반기손이익',
                     '분기순손익', '반기순손익'],
    'eps':         ['기본주당순이익', '기본주당이익', '기본및희석주당순이익', '주당순이익'],
    'sga':         ['판매비와관리비', '판매비및관리비'],
    'op_income':   ['영업이익'],
    'net_income':  ['당기순이익'],
    'assets':      ['자산총계'], 'liabilities': ['부채총계'], 'equity': ['자본총계'],
    'op_cf':       ['영업활동현금흐름', '영업활동으로인한현금흐름'],
    'inv_cf':      ['투자활동현금흐름', '투자활동으로인한현금흐름'],
    'fin_cf':      ['재무활동현금흐름', '재무활동으로인한현금흐름'],
    # 아래는 포토카드(재무3표·밸류에이션)용으로 추가. 전부 실제 응답에서 계정명을
    # 확인하고 넣었다(에코프로비엠·삼성전자 2026 반기 대조).
    'cogs':        ['매출원가'],
    'cash':        ['현금및현금성자산'],
    'ar':          ['매출채권', '매출채권및기타채권'],
    'inventory':   ['재고자산'],
    'ppe':         ['유형자산'],
}

# 계정을 찾을 재무제표 구분. **부분일치가 다른 제표로 새는 것을 막는다.**
#   '현금및현금성자산'은 현금흐름표에 `기초현금및현금성자산`·`분기말현금및현금성자산`·
#   `현금및현금성자산의순증감`으로 여러 번 나온다 — BS로 못 박지 않으면 재무상태표의
#   현금 대신 기초잔액이나 증감액을 집어올 수 있다(정확일치가 먼저 걸려서 지금은
#   안 터지지만, 계정명에 주석번호를 붙이는 제출자 하나면 바로 터진다).
# BS=재무상태표 · IS/CIS=손익계산서 · CF=현금흐름표. None이면 제표 무관.
_STMT_SJ = {
    'assets': 'BS', 'liabilities': 'BS', 'equity': 'BS', 'cash': 'BS',
    'ar': 'BS', 'inventory': 'BS', 'ppe': 'BS',
    'op_cf': 'CF', 'inv_cf': 'CF', 'fin_cf': 'CF',
}


def _acnt_all(corp_code, year, reprt):
    for fs in ('CFS', 'OFS'):
        try:
            j = _get(f"{BASE}/fnlttSinglAcntAll.json",
                     {'crtfc_key': _key(), 'corp_code': corp_code, 'bsns_year': str(year),
                      'reprt_code': reprt, 'fs_div': fs}).json()
        except Exception:
            continue
        if j.get('status') == '000':
            return j
    return None


def _extract_all(j):
    rows = j.get('list', [])
    # 공백 정규화 ('재무활동 현금흐름' 대응)
    pairs = [((row.get('account_nm') or '').replace(' ', '').strip(),
              _to_num(row.get('thstrm_amount')), (row.get('sj_div') or '')) for row in rows]

    def _pick(key, names):
        sj = _STMT_SJ.get(key)
        # 손익은 IS·CIS(포괄손익) 어느 쪽으로도 오므로 제표를 안 건다.
        cand = [(n, v) for n, v, s in pairs if sj is None or s == sj]
        return _match(cand, names)

    out = {key: _pick(key, names) for key, names in _STMT_KEYS.items()}
    # 매출액 계정을 아예 안 싣고 매출원가·매출총이익만 싣는 제출자가 있다
    # (에코프로비엠 2026 반기 실측 — 매출 None인데 매출총이익 52.2B은 있음).
    # 항등식으로 되살린다. 원문에 매출액이 있으면 그쪽이 우선.
    if out['revenue'] is None and out['gross'] is not None and out['cogs'] is not None:
        out['revenue'] = out['gross'] + out['cogs']
    out['capex'] = None
    for nm, val, sj in pairs:
        if sj == 'CF' and '유형자산' in nm and '취득' in nm:
            out['capex'] = val
            break
    return out


# 분기보고서에 3개월치로 실림 → Q4 = FY − (1~3Q). 잔액항목(자산·현금·재고 등)은
# 기말치라 여기 넣으면 안 된다.
_IS_KEYS = ['revenue', 'gross', 'cogs', 'sga', 'op_income', 'net_income']
_CF_KEYS = ['op_cf', 'inv_cf', 'fin_cf', 'capex']                   # 분기보고서에 누적으로만 실림


def statements(corp_code, freq='annual', n=5):
    """통합 재무표 rows(최신순). 분기는 **3개월 환산**:
    손익은 분기보고서의 당기 3개월치 그대로, 현금흐름은 누적 차감,
    Q4는 연간−(1~3Q 합/3Q 누적)으로 도출. 잔액(자산/부채/자본)은 기말치."""
    from datetime import datetime as _d
    y = _d.now().year
    rows = []
    if freq == 'annual':
        for yy in range(y - 1, y - 1 - n, -1):
            j = _acnt_all(corp_code, yy, '11011')
            if j:
                e = _extract_all(j); e['period'] = str(yy)
                e.pop('net_income_q', None)   # 분기 전용 폴백 키 — 연간 행엔 남기지 않는다
                rows.append(e)
        return _capex_out(rows)

    for yy in (y, y - 1, y - 2):
        reps = {}
        for code, lab in (('11013', '1Q'), ('11012', '2Q'), ('11014', '3Q'), ('11011', 'FY')):
            j = _acnt_all(corp_code, yy, code)
            if j:
                r_ = _extract_all(j)
                if r_.get('net_income') is None and r_.get('net_income_q') is not None:
                    r_['net_income'] = r_['net_income_q']       # '분기/반기순이익' 폴백
                reps[lab] = r_

        out_q = []
        if 'FY' in reps:                        # 4Q = 연간 − (1~3Q)
            q4 = dict(reps['FY'])
            for k in _IS_KEYS:
                a = reps['FY'].get(k)
                vals = [reps.get(l, {}).get(k) for l in ('1Q', '2Q', '3Q')]
                q4[k] = (a - sum(vals)) if (a is not None and all(v is not None for v in vals)) else None
            for k in _CF_KEYS:
                a, b = reps['FY'].get(k), reps.get('3Q', {}).get(k)
                q4[k] = (a - b) if (a is not None and b is not None) else None
            q4['period'] = f'{yy}.4Q'
            # EPS는 차감으로 못 만든다 — 주식수가 분기마다 달라 FY−(1~3Q)가 4Q EPS가
            # 아니다. dict(reps['FY'])를 복사해 왔으므로 그대로 두면 **연간 EPS가 4Q
            # EPS인 척** 남는다. 틀린 값보다 빈 값이 낫다.
            q4['eps'] = None
            out_q.append(q4)
        for cur, prev in (('3Q', '2Q'), ('2Q', '1Q'), ('1Q', None)):
            if cur not in reps:
                continue
            e = dict(reps[cur])                 # 손익=3개월치 그대로 · 잔액=기말치
            if prev is not None:
                pv = reps.get(prev)
                for k in _CF_KEYS:              # 현금흐름만 누적 차감
                    a = reps[cur].get(k)
                    b = pv.get(k) if pv else None
                    e[k] = (a - b) if (a is not None and b is not None) else None
            e['period'] = f'{yy}.{cur}'
            out_q.append(e)
        for e in out_q:
            e.pop('net_income_q', None)
            rows.append(e)
            if len(rows) >= n:
                return _capex_out(rows)
    return _capex_out(rows)


def _capex_out(rows):
    """Capex 는 현금 **유출**이므로 음수로 통일(2026-10-17). 제출자·소스마다 부호가 달라
    (EDGAR PaymentsToAcquire… 는 양수) 같은 표에서 KR 은 빨강·US 는 초록으로 칠해지던 것."""
    for e in rows:
        if e.get('capex') is not None:
            e['capex'] = -abs(e['capex'])
    return rows


def business_text(corp_code, max_chars=80000):
    """최신 사업/정기보고서 원문에서 '사업의 내용'부터 텍스트 추출 (AI 요약 입력용)."""
    import io
    import re
    import zipfile
    from datetime import datetime as _d, timedelta as _td
    end = _d.now().strftime('%Y%m%d')
    bgn = (_d.now() - _td(days=400)).strftime('%Y%m%d')
    j = _get(f"{BASE}/list.json", {'crtfc_key': _key(), 'corp_code': corp_code,
                                   'pblntf_ty': 'A', 'bgn_de': bgn, 'end_de': end,
                                   'page_count': 20}).json()
    lst = j.get('list', []) if j.get('status') == '000' else []
    if not lst:
        return None
    tgt = next((x for x in lst if '사업보고서' in x.get('report_nm', '')), lst[0])
    r = _get(f"{BASE}/document.xml", {'crtfc_key': _key(), 'rcept_no': tgt['rcept_no']})
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    best = max(zf.namelist(), key=lambda n: zf.getinfo(n).file_size)
    xml = zf.read(best).decode('utf-8', 'replace')
    txt = re.sub(r'<[^>]+>', ' ', xml)
    txt = re.sub(r'&[a-zA-Z#0-9]+;', ' ', txt)
    txt = re.sub(r'\s+', ' ', txt)
    i = txt.find('사업의 내용')
    if i > 0:
        txt = txt[i:]
    return (f"[출처: {tgt.get('report_nm')} ({tgt.get('rcept_dt')})]\n" + txt[:max_chars]) if txt else None


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


# ── 잠재 희석: 전환사채(CB)·신주인수권부사채(BW)·교환사채(EB) (2026-10-21) ─────────────
# 한국 중소형주에서 CB·BW 는 '조용한 물량'이다. 전환가가 주가보다 낮아지면 전환 → 신주 → 매도 압력.
# 주가가 떨어지면 전환가를 낮추는 리픽싱(최저 70%)으로 주식 수가 더 늘어난다.
# 원천: OpenDART 주요사항보고서 구조화 API (cvbdIsDecsn · bdwtIsDecsn · exbdIsDecsn) + 공시검색(list.json).
# ⚠️ '발행 결정' 기준이다. 이미 전환·상환된 분량은 이 API 로 차감할 수 없다 → 화면에 '최대치'로 적는다.
_DIL_API = {'CB': 'cvbdIsDecsn', 'BW': 'bdwtIsDecsn', 'EB': 'exbdIsDecsn'}
_DIL_KEYS = {   # 같은 뜻의 필드가 종류마다 이름이 다르다 — 앞에서부터 있는 것을 쓴다
    'price':  ('cv_prc', 'ex_prc'),
    'shares': ('cvisstk_cnt', 'nstk_isstk_cnt', 'extg_stkcnt'),
    'ratio':  ('cvisstk_tisstk_vs', 'nstk_isstk_tisstk_vs', 'extg_tisstk_vs'),
    'start':  ('cvrqpd_bgd', 'expd_bgd', 'exrqpd_bgd'),
    'end':    ('cvrqpd_edd', 'expd_edd', 'exrqpd_edd'),
    'floor':  ('act_mktprcfl_cvprc_lwtrsprc',),
}
# 공시 제목(report_nm)으로 고르는 사건 — 결정 외에 '실제로 물량이 나오는 중'인지 보여준다
_DIL_EVENTS = [
    ('전환청구', ('전환청구권행사',)),
    ('신주인수권 행사', ('신주인수권행사',)),
    ('가액 조정(리픽싱)', ('전환가액의조정', '행사가액의조정', '교환가액의조정', '행사가액조정', '전환가액조정')),
    ('CB 발행결정', ('전환사채권발행결정',)),
    ('BW 발행결정', ('신주인수권부사채권발행결정',)),
    ('EB 발행결정', ('교환사채권발행결정',)),
    ('스톡옵션 부여', ('주식매수선택권부여',)),
    ('유상증자', ('유상증자결정',)),
]


def parse_kdate(s):
    """'2026년 03월 15일' · '2026-03-15' · '20260315' · '2026.03.15' → 'YYYY-MM-DD' (실패 None)."""
    m = re.search(r'(\d{4})\D{0,3}(\d{1,2})\D{0,3}(\d{1,2})', str(s or ''))
    if not m:
        return None
    y, mo, d = (int(x) for x in m.groups())
    if not (1990 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_dilution_row(kind, x):
    """DART 응답 한 줄 → 표준 dict. 숫자는 '1,234'·'-' 를 견딘다."""
    def pick(k):
        for f in _DIL_KEYS[k]:
            v = x.get(f)
            if v not in (None, '', '-'):
                return v
        return None
    rno = str(x.get('rcept_no') or '')
    return {'kind': kind, 'rcept_no': rno, 'decided': parse_kdate(x.get('bddd')) or parse_kdate(rno[:8]),
            'round': str(x.get('bd_tm') or '').strip() or None,
            'amount': _to_num(x.get('bd_fta')), 'price': _to_num(pick('price')),
            'floor': _to_num(pick('floor')), 'shares': _to_num(pick('shares')),
            'ratio': _to_num(pick('ratio')), 'start': parse_kdate(pick('start')), 'end': parse_kdate(pick('end')),
            'url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}" if rno else None}


def dilution_terms(corp_code, years=4):
    """CB·BW·EB 발행 결정 조건 [{kind, decided, round, amount, price, floor, shares, ratio, start, end, url}].
    같은 회차의 정정 공시는 마지막 것만 남긴다."""
    from datetime import date, timedelta
    end = date.today()
    bgn = end - timedelta(days=365 * years)
    out = []
    for kind, api in _DIL_API.items():
        j = _get(f"{BASE}/{api}.json", {'crtfc_key': _key(), 'corp_code': corp_code,
                                        'bgn_de': bgn.strftime('%Y%m%d'), 'end_de': end.strftime('%Y%m%d')}).json()
        if j.get('status') not in ('000', '013'):          # 013 = 조회된 데이터 없음
            raise RuntimeError(f"DART {api}: {j.get('status')} {j.get('message')}")
        for x in j.get('list') or []:
            out.append(parse_dilution_row(kind, x))
    seen = {}
    for r in sorted(out, key=lambda r: r['rcept_no']):
        seen[(r['kind'], r['round'] or r['rcept_no'])] = r       # 정정은 접수번호가 뒤라 덮어쓴다
    return sorted(seen.values(), key=lambda r: r['rcept_no'], reverse=True)


def classify_event(report_nm):
    nm = re.sub(r'\s+', '', str(report_nm or ''))
    for label, keys in _DIL_EVENTS:
        if any(k in nm for k in keys):
            return label
    return None


def dilution_events(corp_code, days=365, max_pages=5):
    """최근 공시 제목에서 희석 관련 사건 [{date, label, title, url}] (전환청구·리픽싱·발행결정·스톡옵션·유상증자)."""
    from datetime import date, timedelta
    end = date.today()
    bgn = end - timedelta(days=days)
    out = []
    for page in range(1, max_pages + 1):
        j = _get(f"{BASE}/list.json", {'crtfc_key': _key(), 'corp_code': corp_code, 'bgn_de': bgn.strftime('%Y%m%d'),
                                        'end_de': end.strftime('%Y%m%d'), 'page_no': page, 'page_count': 100}).json()
        if j.get('status') == '013':
            break
        if j.get('status') != '000':
            raise RuntimeError(f"DART list: {j.get('status')} {j.get('message')}")
        for x in j.get('list') or []:
            lab = classify_event(x.get('report_nm'))
            if lab:
                rno = str(x.get('rcept_no') or '')
                out.append({'date': parse_kdate(x.get('rcept_dt')), 'label': lab,
                            'title': str(x.get('report_nm') or '').strip(),
                            'url': f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rno}"})
        if page >= int(j.get('total_page') or 1):
            break
    return out
