# -*- coding: utf-8 -*-
"""매크로 탭 데이터 소스 신선도 진단 (2026-10-21) — 끊긴 계열을 바꾸기 전에 후보들의 마지막 관측일을 잰다.
산출물: data/research/diag_sources.json"""
import json, os, sys, time
import requests
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = os.environ.get('FRED_KEY', '')
FRED = ['DFF', 'FEDFUNDS', 'ECBDFR', 'ECBMRRFR', 'IRSTCI01JPM156N', 'IR3TIB01JPM156N', 'INTDSRJPM193N',
        'INTDSRKRM193N', 'IRSTCI01KRM156N', 'IR3TIB01KRM156N', 'IRSTCB01CNM156N', 'INTDSRCNM193N',
        'BOERUKM', 'IUDSOIA', 'IRSTCI01GBM156N',
        'WALCL', 'ECBASSETSW', 'JPNASSETS', 'DEXUSEU', 'DEXJPUS', 'DEXCHUS', 'DEXKOUS',
        'M2SL', 'MABMM301EZM189S', 'MYAGM2JPM189S', 'MYAGM2CNM189N', 'MABMM301JPM189S', 'MABMM301CNM189S',
        'MABMM301KRM189S', 'MABMM301GBM189S', 'T10Y2Y', 'T10Y3M', 'USREC', 'CPIAUCSL', 'CPILFESL', 'PCEPILFE',
        'IRLTLT01KRM156N', 'IRLTLT01JPM156N', 'IRLTLT01DEM156N']
ECB = {
    'ECB_DFR': 'FM/D.U2.EUR.4F.KR.DFR.LEV',
    'EZ_M2_YOY': 'BSI/M.U2.Y.V.M20.X.I.U2.2300.Z01.A',
    'EZ_M2_LVL': 'BSI/M.U2.Y.V.M20.X.1.U2.2300.Z01.E',
    'EZ_LISTED_SHARES_MV': 'SEC/M.I9.1000.F51100.M.1.Z01.E.Z',
    'EZ_LISTED_SHARES_MV2': 'SEC/M.I8.1000.F51100.M.1.Z01.E.Z',
}
YF = ['JPY=X', 'TWD=X', 'HKD=X', 'CNY=X', 'INR=X', 'EURUSD=X', 'GBPUSD=X', 'BRL=X', 'KRW=X', '^TWII', '^FTSE', '^STOXX50E', '^NSEI', '^BVSP']


def fred(sid):
    try:
        r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                         params=dict(series_id=sid, api_key=KEY, file_type='json', sort_order='desc', limit=3), timeout=20)
        if r.status_code != 200:
            return {'err': r.status_code}
        o = [x for x in r.json()['observations'] if x['value'] != '.']
        m = requests.get('https://api.stlouisfed.org/fred/series', params=dict(series_id=sid, api_key=KEY, file_type='json'), timeout=20).json()
        s = m.get('seriess', [{}])[0]
        return {'last': o[0]['date'] if o else None, 'value': o[0]['value'] if o else None,
                'title': s.get('title'), 'freq': s.get('frequency_short'), 'units': s.get('units_short'), 'start': s.get('observation_start')}
    except Exception as e:
        return {'err': str(e)[:80]}


def ecb(key):
    try:
        r = requests.get(f'https://data-api.ecb.europa.eu/service/data/{key}', params={'format': 'csvdata', 'lastNObservations': 3}, timeout=30)
        if r.status_code != 200:
            return {'err': r.status_code}
        lines = r.text.strip().split('\n')
        hdr = lines[0].split(',')
        last = lines[-1].split(',')
        d = dict(zip(hdr, last))
        return {'last': d.get('TIME_PERIOD'), 'value': d.get('OBS_VALUE'), 'title': d.get('TITLE', '')[:80], 'unit': d.get('UNIT', '')}
    except Exception as e:
        return {'err': str(e)[:80]}


def main():
    out = {'fred': {s: fred(s) for s in FRED}, 'ecb': {k: ecb(v) for k, v in ECB.items()}}
    import yfinance as yf
    out['yahoo'] = {}
    for s in YF:
        try:
            h = yf.Ticker(s).history(period='10y')['Close'].dropna()
            out['yahoo'][s] = {'start': str(h.index[0].date()), 'last': str(h.index[-1].date()), 'value': float(h.iloc[-1])}
        except Exception as e:
            out['yahoo'][s] = {'err': str(e)[:80]}
    os.makedirs(os.path.join(BASE, 'data', 'research'), exist_ok=True)
    json.dump(out, open(os.path.join(BASE, 'data', 'research', 'diag_sources.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])


if __name__ == '__main__':
    sys.exit(main())
