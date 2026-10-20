# -*- coding: utf-8 -*-
"""
국가별 주식시장 시가총액 — 세계은행 CM.MKT.LCAP.CD (상장 내국기업 시총, 현재 달러) (2026-10-20)

화면(세계 증시 강도판)은 이 연말 값에 '그 뒤 대표 지수 변동률'을 곱해 오늘 값을 추정한다.
연말 값 자체는 공식 통계다. 대만은 세계은행 자료에 없어 대만증권거래소(TWSE) 연보 값을 쓰지 못하면 빈칸으로 둔다.

산출물: data/world_mcap.json  {국가코드: {"usd": 값, "year": 연도}}
CLI:    python tools/fetch_world_mcap.py
"""
import json
import os
import sys

import requests

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'data', 'world_mcap.json')
CODES = ['USA', 'KOR', 'JPN', 'HKG', 'CHN', 'IND', 'DEU', 'GBR', 'BRA', 'EMU', 'TWN']
# 세계은행에 없는 나라 — 거래소 공식 연말 값(현지 통화). 출처를 같이 적는다.
MANUAL = {
    'TWN': {'local': 94.36e12, 'ccy': 'TWD', 'year': 2025, 'name': 'Taiwan',
            'source': 'TWSE 상장사 시가총액 2025년 말 NT$94.36조 (중화민국 교무위원회 OCAC 2026-01 보도, TWSE 연보)'},
}


def main():
    url = ('https://api.worldbank.org/v2/country/' + ';'.join(CODES) +
           '/indicator/CM.MKT.LCAP.CD?format=json&per_page=2000&date=2015:2026')
    rows, last = None, None
    for i in range(4):                 # 세계은행 API 는 가끔 느리거나 HTML 오류 페이지를 준다
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            rows = r.json()[1] or []
            break
        except Exception as e:
            last = e
            print(f'  재시도 {i + 1}: {str(e)[:100]}', flush=True)
            import time; time.sleep(10 * (i + 1))
    if rows is None:
        print(f'::error::세계은행 API 실패 — {last}')
        return 1
    out = {}
    for x in rows:
        c, v, y = x['countryiso3code'] or x['country']['id'], x['value'], x['date']
        if v is None:
            continue
        if c not in out or int(y) > out[c]['year']:
            out[c] = {'usd': float(v), 'year': int(y), 'name': x['country']['value']}
    for c, v in MANUAL.items():
        if c not in out:
            out[c] = v
    miss = [c for c in CODES if c not in out]
    print(json.dumps(out, ensure_ascii=False, indent=1))
    print('없음:', miss)
    if len(out) < 6:
        print('::error::세계은행 시총이 6개국 미만 — 저장하지 않는다')
        return 1
    out['_meta'] = {'source': 'World Bank CM.MKT.LCAP.CD', 'missing': miss}
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.exit(main())
