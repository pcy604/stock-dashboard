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


def main():
    url = ('https://api.worldbank.org/v2/country/' + ';'.join(CODES) +
           '/indicator/CM.MKT.LCAP.CD?format=json&per_page=2000&date=2015:2026')
    r = requests.get(url, timeout=40)
    r.raise_for_status()
    rows = r.json()[1] or []
    out = {}
    for x in rows:
        c, v, y = x['countryiso3code'] or x['country']['id'], x['value'], x['date']
        if v is None:
            continue
        if c not in out or int(y) > out[c]['year']:
            out[c] = {'usd': float(v), 'year': int(y), 'name': x['country']['value']}
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
