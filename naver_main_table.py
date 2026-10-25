"""naver_main_table.py — 네이버 금융 종목 메인 '기업실적분석' 표, 단일 수집 지점.

2026-10-25 이전: consensus_snapshot.py·canslim_run.py·dashboard.py 세 곳이 같은
URL(finance.naver.com/item/main.naver)의 같은 표를 각자 다른 코드로 긁고 있었다.
헤더 파싱(연간/분기 (E) 컬럼 판별) 로직이 사실상 동일한데 따로 있다 보니 한쪽만
버그가 고쳐지고(dashboard.py — 분기 (E) 컬럼 처리) 나머지 둘은 안 고쳐진 채
드리프트하고 있었다. 표 가져오기 + 헤더 해석만 여기로 모으고, 각 호출부는
fetch()가 돌려준 표에서 자기가 필요한 행만 뽑는다. 세 곳을 한 번에 두드리는
요청 횟수 자체를 줄이는 게 아니라(용도가 다른 시점에 호출돼 캐싱 효과는 적다),
"같은 표인데 다르게 해석해서 다른 숫자가 나올" 위험을 없애는 게 목적이다.
"""
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime as _dt


def fetch(sym: str, timeout: int = 8):
    """표 + 헤더 해석. 실패하면 None.

    반환: {'date_heads': [...], 'n_annual': int, 'emap': {열idx: '0y'/'1y'/'0q'/'1q'}, 'rows': {th원문: [td원문,...]}}
    emap은 dashboard.py가 2026-10-20 고친 버전 기준(연간 (E) + 분기 (E) 둘 다 매핑) —
    세 호출부 중 가장 완전한 버전을 단일 기준으로 삼는다.
    """
    try:
        r = requests.get(f'https://finance.naver.com/item/main.naver?code={sym}',
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=timeout)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    soup = BeautifulSoup(r.text, 'html.parser')
    tb = soup.select_one('div.cop_analysis table')
    if tb is None:
        return None
    heads = [th.get_text(' ', strip=True) for th in tb.select('thead th')]
    date_heads = [h for h in heads if re.match(r'\d{4}\.\d{2}', h)]
    if not date_heads:
        return None
    n_annual = 4 if len(date_heads) >= 10 else max(len(date_heads) - 6, 0)
    ynow = _dt.now().year
    emap = {}
    for i, h in enumerate(date_heads[:n_annual]):
        if '(E)' in h:
            emap[i] = '0y' if int(h[:4]) <= ynow else '1y'
    q_e_idx = [i for i, h in enumerate(date_heads[n_annual:], start=n_annual) if '(E)' in h]
    for j, i in enumerate(q_e_idx[:2]):
        emap[i] = '0q' if j == 0 else '1q'
    rows = {}
    for row_el in tb.select('tbody tr'):
        th = row_el.select_one('th')
        if th:
            rows[th.get_text(strip=True)] = [td.get_text(strip=True) for td in row_el.select('td')]
    return {'date_heads': date_heads, 'n_annual': n_annual, 'emap': emap, 'rows': rows}


def row(table: dict, keyword: str):
    """keyword를 포함하는 첫 행(원문 문자열 리스트). 기존 세 호출부와 같은 부분일치 규칙
    (th.get_text() 안에 keyword가 들어있으면 매치) — 표의 실제 행 순서에 의존한다."""
    if table is None:
        return None
    for th_text, vals in table['rows'].items():
        if keyword in th_text:
            return vals
    return None


def num(s):
    """'1,234' → 1234.0, '-'/빈칸/파싱불가 → None."""
    if s is None:
        return None
    s = s.replace(',', '').strip()
    if not s or s == '-':
        return None
    try:
        return float(s)
    except Exception:
        return None
