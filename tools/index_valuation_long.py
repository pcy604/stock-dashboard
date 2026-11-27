# -*- coding: utf-8 -*-
"""지수 밸류에이션 장기판 (2026-11-28 차니: "2018년부터는 너무 짧다 — 더 있어야지").

  python tools/index_valuation_long.py     # CI(index-valuation-long) — 한국거래소·Shiller·multpl 에서 받는다
결과: results/index_valuation_long.json  {지수: {per: [[날짜, 값]...], pbr: [...], cape: [...], src}}

원천 (공식·장기 · 방법이 지수마다 하나로 고정되어 역사 비교가 된다)
  코스피·코스닥  한국거래소 지수 PER·PBR(pykrx get_index_fundamental) — 월말 값, 2000~ (코스닥 지수 PER 은 거래소 제공 시작부터)
  S&P500        PER = multpl.com 월별 표(Shiller 자료 기반, 1871~) · PBR = multpl 분기(1999~) · CAPE = multpl 월별(1881~)
실패한 원천은 비우고 이유를 남긴다(지어내지 않는다). 패널 합산판(index_valuation.json)은 2018~ 보조로 그대로 둔다.
"""
import json
import os
import re
import time
from datetime import date

import pandas as pd
import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results/index_valuation_long.json')
UA = {'User-Agent': 'Mozilla/5.0 (index-valuation-long; research)'}


def krx(ticker: str, start='20000101') -> dict:
    from pykrx import stock
    end = date.today().strftime('%Y%m%d')
    fr = []
    for y in range(int(start[:4]), date.today().year + 1, 3):         # 길게 한 번에 부르면 거래소가 끊는다 — 3년씩
        a, b = f'{y}0101', min(f'{y + 2}1231', end)
        try:
            d = stock.get_index_fundamental(a, b, ticker)
            if d is not None and len(d):
                fr.append(d)
        except Exception as e:
            print(f'  KRX {ticker} {a}~{b}: {str(e)[:80]}')
        time.sleep(1.0)
    if not fr:
        return {}
    d = pd.concat(fr)
    d = d[~d.index.duplicated()].sort_index()
    m = d.resample('ME').last()
    out = {}
    for col, key in (('PER', 'per'), ('PBR', 'pbr')):
        if col in m.columns:
            s = pd.to_numeric(m[col], errors='coerce')
            s = s[(s > 0) & (s < 200)].dropna()
            out[key] = [[str(i.date()), round(float(v), 2)] for i, v in s.items()]
    return out


def multpl(path: str) -> list:
    r = requests.get(f'https://www.multpl.com/{path}', headers=UA, timeout=30)
    r.raise_for_status()
    rows = re.findall(r'<td>([A-Z][a-z]{2} \d{1,2}, \d{4})</td>\s*<td>\s*(?:&#x2002;|&#8194;)?\s*([\d.]+)', r.text)
    out = sorted([str(pd.Timestamp(d).date()), float(v)] for d, v in rows)
    return out


def main():
    res = {}
    for name, tk in (('코스피', '1001'), ('코스닥', '2001')):
        try:
            d = krx(tk)
            d['src'] = '한국거래소 지수 PER·PBR(월말) · pykrx'
            res[name] = d
            print(name, {k: (len(v), v[0], v[-1]) for k, v in d.items() if isinstance(v, list) and v})
        except Exception as e:
            res[name] = dict(err=str(e)[:200])
            print(name, '실패', e)
    sp = dict(src='multpl.com(Shiller 자료 기반) · PER 월별 1871~ · PBR 분기 1999~ · CAPE 월별')
    for key, path in (('per', 's-p-500-pe-ratio/table/by-month'), ('pbr', 's-p-500-price-to-book/table/by-quarter'),
                      ('cape', 'shiller-pe/table/by-month')):
        try:
            sp[key] = multpl(path)
            print('S&P500', key, len(sp[key]), sp[key][:1], sp[key][-1:])
        except Exception as e:
            sp[f'err_{key}'] = str(e)[:200]
            print('S&P500', key, '실패', e)
        time.sleep(1.5)
    res['S&P500'] = sp
    json.dump(dict(made=str(date.today()), indices=res), open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print('저장', OUT)


if __name__ == '__main__':
    main()
