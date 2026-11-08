# -*- coding: utf-8 -*-
"""주도주 교체 규칙 검증 — research/rotation_prereg_2026-11-08.md"""
import json, os, sys
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q, live_v18_test as V8, live_v19_test as V9, overfit as OF   # noqa: E401,E402

SYS = {'보유5': dict(max_pos=5), '보유10': dict(max_pos=10, entry=V9.PYR['S2'])}


def ex(sig):
    e = json.loads(json.dumps(V8.LIVE['exit'])); e['signals'] = sig; return e


def main(path):
    P, df = V9.load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    bench = V8.index_w('KOSPI'); out = {}
    for sn, so in SYS.items():
        n = so['max_pos']
        V = {'없음': []}
        for x in (60, 70, 80):
            V[f'RS<{x}'] = [dict(type='field', field='rs', op='<', value=x)]
        for k in (2, 3):
            V[f'상위{k * n}밖'] = [dict(type='rank_out', m=k * n)]
        R, C = {}, {}
        for vk, sig in V.items():
            s = json.loads(json.dumps(V8.LIVE)); s.update(so); s['exit'] = ex(sig)
            r = Q.run(P, s, bench_px=bench, entry_block=blk); eq = r['equity']; C[vk] = eq[eq.index >= V8.START]
            R[vk] = V8.run(P, blk, bench, **so, exit=ex(sig)); print(sn, vk, R[vk], flush=True)
        b = R['없음']
        ok1 = {k: bool(v['cagr'] >= b['cagr'] and v['mdd'] - b['mdd'] >= -3) for k, v in R.items() if k != '없음'}
        ok2 = {k: bool(v['p1'] >= b['p1'] - 2 and v['p2'] >= b['p2'] - 2) for k, v in R.items() if k != '없음'}
        idx = sorted(set.intersection(*[set(c.index) for c in C.values()]))
        CC = {k: (v.reindex(idx) / v.reindex(idx).iloc[0]).tolist() for k, v in C.items()}
        bb = bench.reindex(idx).ffill(); J = OF.judge(CC, list(CC), (bb / bb.iloc[0]).tolist(), {})
        out[sn] = dict(results=R, main=ok1, periods=ok2,
                       overfit={x: J['excess'][x] for x in ('best_key', 'dsr', 'pbo', 'verdict')})
        print(sn, json.dumps(dict(main=ok1, periods=ok2, overfit=out[sn]['overfit']), ensure_ascii=False), flush=True)
    json.dump(out, open(os.path.join(ROOT, 'results/rotation_test_2026-11-08.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
