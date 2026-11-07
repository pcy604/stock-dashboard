# -*- coding: utf-8 -*-
"""실전 v1.8 후보 3건 검증 — research/live_v18_prereg_2026-11-07.md 의 기준 그대로.

  python research/live_v18_test.py [quant_panel_KR.parquet 경로]
결과: results/live_v18_test_2026-11-07.json
"""
import json
import os
import sys
import time

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q                       # noqa: E402
from quant_panel import kr_acc                 # noqa: E402

START, SPLIT = '2018-06-01', '2022-01-01'
LIVE = dict(market='KR', start=START,
            filters=[dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
                     dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
            rank=dict(field='rs', desc=True), rebalance=1, max_pos=5, max_w=0.30, trim='cap',
            entry=dict(init=0.6, pyramid=[[10, 0.4]]),
            exposure=dict(index='', ma=5, below=0.0, mode='entry'),
            exit=dict(stop=0, trail=[[0, 20]], cooldown=2, signals=[]))


def index_w(name):
    s = pd.read_parquet(os.path.join(ROOT, 'data/research/macro_long_px.parquet'))[name].dropna()
    s.index = pd.to_datetime(s.index)
    return s.resample('W-MON', label='left', closed='left').last()


def load_panel(path):
    df = pd.read_parquet(path)
    df['date'] = pd.to_datetime(df['date'])
    # 한국 이익가속 — 패널이 옛 빌드(acc=0)여도 같은 정의로 다시 붙인다
    q = pd.read_parquet(os.path.join(ROOT, 'data/kr_fundamentals_q.parquet'))
    q['sym'] = q.sym.astype(str).str.zfill(6)
    q['end'] = pd.to_datetime(q.year.astype(int).astype(str) + '-' + (q.q.astype(int) * 3).astype(str) + '-01') + pd.offsets.MonthEnd(0)
    from tools.kr_filing_dates import known as _known
    q['known'], _ = _known(q.sym, q.year, q.q)
    q = q.sort_values(['sym', 'end']).reset_index(drop=True)
    q['acc'] = kr_acc(q)
    q = q[['sym', 'known', 'acc']].dropna(subset=['known']).sort_values('known')
    df = df.drop(columns=['acc']).sort_values('date')
    df = pd.merge_asof(df, q, left_on='date', right_on='known', by='sym', direction='backward').drop(columns=['known'])
    df['acc'] = df['acc'].fillna(0).astype(int)
    sm = df.loc[df['market'].isin(['KOSPI', 'KOSDAQ']), ['sym', 'date', 'market']].copy()
    sm['market'] = sm['market'].astype('category')
    P = Q.Panel(df.drop(columns=['market']))
    P.sym_market = sm
    return P, df


def run(P, blk, bench, **over):
    s = json.loads(json.dumps(LIVE))
    for k, v in over.items():
        s[k] = v
    r = Q.run(P, s, bench_px=bench, entry_block=blk)
    eq = r['equity']

    def seg(a, b=None):
        e = eq[(eq.index >= a) & ((eq.index < b) if b else True)]
        if len(e) < 10:
            return None, None
        yrs = (e.index[-1] - e.index[0]).days / 365.25
        cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
        mdd = (e / e.cummax() - 1).min()
        return round(float(cagr) * 100, 1), round(float(mdd) * 100, 1)
    c, m = seg(START)
    c1, m1 = seg(START, SPLIT)
    c2, m2 = seg(SPLIT)
    T = r['trades']
    return dict(cagr=c, mdd=m, p1=c1, p1_mdd=m1, p2=c2, p2_mdd=m2,
                calmar=round(c / abs(m), 3) if c is not None and m else None,
                trades=int(len(T)))


def ok1(x, a):
    return bool(x['cagr'] > a['cagr'] and (x['mdd'] - a['mdd']) >= -3.0)


def ok2(x, a):
    return bool(x['p1'] > a['p1'] and x['p2'] > a['p2'])


def main(path):
    t0 = time.time()
    P, df = load_panel(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': index_w('KOSPI'), 'KOSDAQ': index_w('KOSDAQ')}, 5)
    bench = index_w('KOSPI')
    acc_share = float(df.loc[df.date >= START, 'acc'].mean())
    R = {}

    def go(k, **o):
        R[k] = run(P, blk, bench, **o)
        print(f"{k:28s} {R[k]}  ({time.time() - t0:.0f}s)", flush=True)

    go('A')
    go('T0_none', trim='none')
    go('T20_target', trim='target')
    for n in (10, 15, 20):
        go(f'B{n}', max_pos=n, max_new=5)
    orf = [dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
           dict(field='op_turn', op='==', value=1), dict(field='acc', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)]
    go('C', filters=orf, logic='1 AND 2 AND (3 OR 4) AND 5')
    for n in (3, 10):
        go(f'A_s{n}', max_pos=n)
        go(f'C_s{n}', max_pos=n, filters=orf, logic='1 AND 2 AND (3 OR 4) AND 5')

    A = R['A']
    V = {}
    b_ok = {n: ok1(R[f'B{n}'], A) for n in (10, 15, 20)}
    b_full = [n for n in (10, 15, 20) if b_ok[n] and ok2(R[f'B{n}'], A) and sum(b_ok[m] for m in (10, 15, 20) if m != n) >= 1]
    V['Q1'] = dict(pass_main={str(k): v for k, v in b_ok.items()}, adopt=(max(b_full, key=lambda n: R[f'B{n}']['calmar']) if b_full else None))
    c_ok = ok1(R['C'], A) and ok2(R['C'], A) and all(R[f'C_s{n}']['cagr'] > R[f'A_s{n}']['cagr'] for n in (3, 10))
    V['Q2'] = dict(adopt=bool(c_ok), main=ok1(R['C'], A), periods=ok2(R['C'], A),
                   slots={str(n): bool(R[f'C_s{n}']['cagr'] > R[f'A_s{n}']['cagr']) for n in (3, 10)})
    t_ok = ok1(R['T20_target'], A) and ok2(R['T20_target'], A)
    V['Q3'] = dict(adopt='T20' if t_ok else 'T30')
    if V['Q1']['adopt'] and V['Q2']['adopt']:
        n = V['Q1']['adopt']
        go('BC', max_pos=n, max_new=5, filters=orf, logic='1 AND 2 AND (3 OR 4) AND 5')
        V['combo'] = dict(adopt=ok1(R['BC'], A))
    out = dict(made=str(pd.Timestamp.today().date()), prereg='research/live_v18_prereg_2026-11-07.md',
               panel_end=str(df.date.max().date()), acc_share_kr=round(acc_share * 100, 2), results=R, verdict=V)
    os.makedirs(os.path.join(ROOT, 'results'), exist_ok=True)
    json.dump(out, open(os.path.join(ROOT, 'results/live_v18_test_2026-11-07.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(V, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
