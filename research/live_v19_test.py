# -*- coding: utf-8 -*-
"""실전 v1.9 후보 검증 — research/live_v19_prereg_2026-11-08.md 기준 그대로.  python research/live_v19_test.py [패널 경로]"""
import json
import os
import sys

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q                                   # noqa: E402
import live_v18_test as V8                                 # noqa: E402
from quant_panel import kr_oi_g                            # noqa: E402

PYR = {'S1': dict(init=0.6, pyramid=[[10, 0.4]]),
       'S2': dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
       'S3': dict(init=0.34, pyramid=[[10, 0.33], [20, 0.33]])}


def load(path):
    P, df = V8.load_panel(path)                            # acc 다시 붙인 패널
    q = pd.read_parquet(os.path.join(ROOT, 'data/kr_fundamentals_q.parquet'))
    q['sym'] = q.sym.astype(str).str.zfill(6)
    q['end'] = pd.to_datetime(q.year.astype(int).astype(str) + '-' + (q.q.astype(int) * 3).astype(str) + '-01') + pd.offsets.MonthEnd(0)
    from tools.kr_filing_dates import known as _known
    q['known'], _ = _known(q.sym, q.year, q.q)
    q = q.sort_values(['sym', 'end']).reset_index(drop=True)
    q['oi_g'] = kr_oi_g(q)
    q = q[['sym', 'known', 'oi_g']].dropna(subset=['known']).sort_values('known')
    df = df.drop(columns=[c for c in ('oi_g',) if c in df.columns]).sort_values('date')
    df = pd.merge_asof(df, q, left_on='date', right_on='known', by='sym', direction='backward').drop(columns=['known'])
    sm = df.loc[df['market'].isin(['KOSPI', 'KOSDAQ']), ['sym', 'date', 'market']].copy()
    sm['market'] = sm['market'].astype('category')
    P = Q.Panel(df.drop(columns=['market'])); P.sym_market = sm
    return P, df


def main(path):
    P, df = load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    bench = V8.index_w('KOSPI')
    R = {}

    def go(k, **o):
        R[k] = V8.run(P, blk, bench, **o); print(f'{k:16s} {R[k]}', flush=True)

    go('A')
    for s, e in PYR.items():
        for n in (10, 8, 12):
            go(f'{s}_n{n}', max_pos=n, entry=e)
    A = R['A']

    def q4_1(x):
        return x['mdd'] - A['mdd'] >= 5 and A['cagr'] - x['cagr'] <= 3

    def q4_2(x):
        return x['p1_mdd'] >= A['p1_mdd'] and x['p2_mdd'] >= A['p2_mdd'] and A['p1'] - x['p1'] <= 5 and A['p2'] - x['p2'] <= 5
    ok = {s: dict(main=bool(q4_1(R[f'{s}_n10'])), periods=bool(q4_2(R[f'{s}_n10'])),
                  neighbors=bool(q4_1(R[f'{s}_n8']) and q4_1(R[f'{s}_n12']))) for s in PYR}
    win = [s for s in PYR if all(ok[s].values())]
    adopt = max(win, key=lambda s: R[f'{s}_n10']['calmar']) if win else None
    V = dict(Q4=dict(checks=ok, adopt=adopt))
    base = dict(max_pos=10, entry=PYR[adopt]) if adopt else {}
    bk = f'{adopt}_n10' if adopt else 'A'
    for th in (10, 5, 20):
        f = [dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
             dict(field='op_turn', op='==', value=1), dict(field='oi_g', op='>=', value=th), dict(field='ma_gap:5', op='>', value=0)]
        go(f'OI{th}', filters=f, logic='1 AND 2 AND (3 OR 4) AND 5', **base)
    B = R[bk]
    m1 = {th: V8.ok1(R[f'OI{th}'], B) for th in (10, 5, 20)}
    V['Q5'] = dict(base=bk, main={str(k): v for k, v in m1.items()}, periods=V8.ok2(R['OI10'], B),
                   adopt=bool(m1[10] and V8.ok2(R['OI10'], B) and (m1[5] or m1[20])))
    share = float((df.loc[df.date >= V8.START, 'oi_g'] >= 10).mean())
    out = dict(made=str(pd.Timestamp.today().date()), prereg='research/live_v19_prereg_2026-11-08.md',
               panel_end=str(df.date.max().date()), oi_g10_share=round(share * 100, 2), results=R, verdict=V)
    json.dump(out, open(os.path.join(ROOT, 'results/live_v19_test_2026-11-08.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(json.dumps(V, ensure_ascii=False, indent=1), 'oi_g≥10 share', round(share * 100, 2))


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
