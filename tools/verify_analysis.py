# -*- coding: utf-8 -*-
"""종목 분석 실데이터 점검 (2026-10-21) — CI 러너(인터넷 됨)에서 DART·SEC·yfinance 실응답으로 새 기능을 확인한다.
작업 환경(Claude)에서는 외부 접속이 막혀 있어, 결과를 results/verify/analysis_check.json 으로 남겨 읽는다."""
import json, os, sys, traceback
from datetime import date, timedelta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
OUT = os.path.join(ROOT, 'results', 'verify', 'analysis_check.json')
R = {'date': date.today().isoformat()}


def step(name):
    def deco(fn):
        try:
            R[name] = fn()
        except Exception as e:
            R[name] = {'error': f"{type(e).__name__}: {e}"[:400], 'tb': traceback.format_exc()[-1500:]}
        print(name, json.dumps(R[name], ensure_ascii=False, default=str)[:1500])
        return fn
    return deco


import dart_client as D
import edgar_client as E


@step('dart_cb_raw')
def _():
    """최근 120일 CB·BW·EB 발행결정 공시 회사 + 첫 응답의 원래 필드명(파서가 기대하는 이름과 대조)."""
    end = date.today(); bgn = end - timedelta(days=89)
    j = D._get(f"{D.BASE}/list.json", {'crtfc_key': D._key(), 'pblntf_detail_ty': 'B001', 'bgn_de': bgn.strftime('%Y%m%d'),
                                        'end_de': end.strftime('%Y%m%d'), 'page_count': 100}).json()
    hits = [x for x in j.get('list') or [] if any(k in str(x.get('report_nm', '')).replace(' ', '')
            for k in ('전환사채권발행결정', '신주인수권부사채권발행결정', '교환사채권발행결정')) and x.get('stock_code')]
    out = {'status': j.get('status'), 'total': j.get('total_count'), 'hits': [(h['stock_code'], h['corp_name'], h['report_nm']) for h in hits[:10]]}
    for api in ('cvbdIsDecsn', 'bdwtIsDecsn', 'exbdIsDecsn'):
        for h in hits:
            r = D._get(f"{D.BASE}/{api}.json", {'crtfc_key': D._key(), 'corp_code': h['corp_code'],
                                                 'bgn_de': (end - timedelta(days=400)).strftime('%Y%m%d'), 'end_de': end.strftime('%Y%m%d')}).json()
            if r.get('list'):
                out[api] = {'corp': h['corp_name'], 'raw': r['list'][0]}
                break
    R['_cb_corps'] = [(h['corp_code'], h['stock_code'], h['corp_name']) for h in hits[:4]]
    return out


@step('dart_cb_parsed')
def _():
    import analysis_checks as AC
    import pandas as pd
    k = pd.read_csv('data/krx_listing_last.csv', dtype={'Code': str}).set_index('Code')
    out = []
    for cc, sym, nm in R.get('_cb_corps', [])[:3] + [(D.corp_map().get('006110'), '006110', '삼아알미늄')]:
        terms = D.dilution_terms(cc, years=4)
        ev = D.dilution_events(cc, days=365)
        sh = float(k.loc[sym, 'Stocks']) if sym in k.index else None
        px = float(k.loc[sym, 'Close']) if sym in k.index and 'Close' in k.columns else None
        s = AC.summarize_dilution(terms, shares_out=sh, price=px)
        out.append({'sym': sym, 'name': nm, 'n_terms': len(terms), 'terms': terms[:3], 'events': ev[:8],
                    'summary': {k2: v for k2, v in s.items() if k2 != 'rows'}})
    return out


@step('form4')
def _():
    out = {}
    for t in ('TSLA', 'NVDA', 'PLTR'):
        rows = E.form4_transactions(t, days=365, limit=30)
        out[t] = {'n': len(rows), 'codes': {c: sum(1 for r in rows if r['code'] == c) for c in {r['code'] for r in rows}},
                  'kinds': sorted({r['sec_kind'] for r in rows}), 'plan_share': sum(r['plan_10b5_1'] for r in rows) / max(len(rows), 1),
                  'tagged': sum(1 for r in rows if r['tags']), 'sample': [{k: r[k] for k in ('date', 'owner', 'role', 'sec_kind', 'code_label',
                  'shares', 'price', 'exercise_price', 'expiration', 'plan_10b5_1', 'tags')} for r in rows[:6]],
                  'notes': list(dict.fromkeys(r['notes'][:300] for r in rows if r['notes']))[:6]}
    return out


@step('trend_earn')
def _():
    import yfinance as yf
    import stock_extras as sx
    out = {}
    for s, y in (('TSLA', 'TSLA'), ('006110', '006110.KS'), ('005930', '005930.KS')):
        h = yf.Ticker(y).history(period='2y')
        t = sx.trend_template(h['Close'], h['High'], h['Low'])
        out[s] = {k: t.get(k) for k in ('n', 'state', 'from_high', 'from_low', 'weeks_since_high')}
    rows = E.statements('TSLA', 'quarter', 20)
    e = sx.earnings_trend(rows)
    out['TSLA_earn'] = {k: e.get(k) for k in ('state', 'level', 'streak', 'acc_8q', 'base_warn')}
    return out


R.pop('_cb_corps', None)
os.makedirs(os.path.dirname(OUT), exist_ok=True)
json.dump(R, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
