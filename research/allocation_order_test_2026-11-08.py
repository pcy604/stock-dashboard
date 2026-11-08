# -*- coding: utf-8 -*-
"""자산배분실 오더 검증 — research/allocation_order_prereg_2026-11-08.md"""
import json, os, sys
import numpy as np, pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q, live_v18_test as V8, live_v19_test as V9, overfit as OF   # noqa: E401,E402

BASE = dict(max_pos=10, entry=V9.PYR['S2'])
EXIT = json.loads(json.dumps(V8.LIVE['exit'])); EXIT['signals'] = [dict(type='field', field='rs', op='<', value=70)]


def daily(name):
    s = pd.read_parquet(os.path.join(ROOT, 'data/research/macro_long_px.parquet'))[name].dropna(); s.index = pd.to_datetime(s.index); return s


def main(path):
    P, df = V9.load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    bench = V8.index_w('KOSPI')
    V = {'B': None,
         'E1_코스피5주_50': ('KOSPI', 5, .5, False), 'E2_코스피5주_25': ('KOSPI', 5, .25, False), 'E3_코스피5주_0': ('KOSPI', 5, 0., False),
         'E4_코스닥5주_50': ('KOSDAQ', 5, .5, False), 'E5_코스피10주_50': ('KOSPI', 10, .5, False), 'E6_코스피5일_50': ('KOSPI', 5, .5, True)}
    R, C = {}, {}
    for k, v in V.items():
        s = json.loads(json.dumps(V8.LIVE)); s.update(BASE); s['exit'] = EXIT
        kw = dict(bench_px=bench, entry_block=blk)
        if v:
            ix, ma, below, dly = v
            s['exposure'] = dict(index=ix, ma=ma, below=below, mode='scale', daily=dly)
            kw['index_px'] = V8.index_w(ix)
            if dly:
                kw['index_px_daily'] = daily(ix)
        r = Q.run(P, s, **kw); eq = r['equity']; eq = eq[eq.index >= V8.START]; C[k] = eq
        def seg(a, b=None):
            e = eq[(eq.index >= a) & ((eq.index < b) if b else True)]; y = (e.index[-1] - e.index[0]).days / 365.25
            return round(float((e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1), round(float((e / e.cummax() - 1).min()) * 100, 1)
        c, m = seg(V8.START); c1, m1 = seg(V8.START, V8.SPLIT); c2, m2 = seg(V8.SPLIT)
        R[k] = dict(cagr=c, mdd=m, p1=c1, p1_mdd=m1, p2=c2, p2_mdd=m2, calmar=round(c / abs(m), 3), trades=int(len(r['trades'])),
                    avg_expo=round(float(np.nanmean(r['exposure'][r['exposure'].index >= V8.START])), 3))
        print(k, R[k], flush=True)
    B = R['B']
    ok1 = {k: bool((x['mdd'] - B['mdd'] >= 5 and B['cagr'] - x['cagr'] <= 3) or (x['cagr'] >= B['cagr'] and x['mdd'] - B['mdd'] >= -3)) for k, x in R.items() if k != 'B'}
    ok2 = {k: bool(x['p1_mdd'] >= B['p1_mdd'] and x['p2_mdd'] >= B['p2_mdd']) for k, x in R.items() if k != 'B'}
    idx = sorted(set.intersection(*[set(c.index) for c in C.values()]))
    CC = {k: (v.reindex(idx) / v.reindex(idx).iloc[0]).tolist() for k, v in C.items()}
    bb = bench.reindex(idx).ffill(); J = OF.judge(CC, list(CC), (bb / bb.iloc[0]).tolist(), {})
    nb = sum(ok1[k] for k in ('E2_코스피5주_25', 'E4_코스닥5주_50', 'E5_코스피10주_50'))
    verdict = dict(main=ok1, periods=ok2, E1_neighbors=f'{nb}/3', overfit={x: J['excess'][x] for x in ('best_key', 'dsr', 'pbo', 'verdict')},
                   adopt_E1=bool(ok1['E1_코스피5주_50'] and ok2['E1_코스피5주_50'] and nb >= 2))
    print(json.dumps(verdict, ensure_ascii=False, indent=1))
    json.dump(dict(made='2026-11-08', results=R, verdict=verdict), open(os.path.join(ROOT, 'results/allocation_order_test_2026-11-08.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
