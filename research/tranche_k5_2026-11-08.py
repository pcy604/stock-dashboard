# -*- coding: utf-8 -*-
"""차니 후속(11-08): '5주 만기 · 매주 20%' — tranche_test 와 같은 시뮬레이터·기준(사후 변형이라 앞 10개와 합쳐 과적합 판정)."""
import json, os, runpy, sys
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research'))
T = runpy.run_path(os.path.join(ROOT, 'research/tranche_test_2026-11-08.py'))
import quant_engine as Q, live_v18_test as V8, live_v19_test as V9, overfit as OF   # noqa: E401,E402

P, df = V9.load(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
blk = np.asarray(Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5), bool)
bench = V8.index_w('KOSPI'); M = T['prep'](P)
prev = json.load(open(os.path.join(ROOT, 'results/tranche_test_2026-11-08.json'), encoding='utf-8'))
R, curves = {}, {}
grid = [(5, 5, .20), (4, 5, .25), (6, 5, 1 / 6), (5, 3, .20), (5, 8, .20)]
for mode in ('TA', 'TB'):
    for K, N, f in grid:
        k = f'{mode}_K{K}_N{N}_{round(f * 100)}%'
        e = T['sim'](P, M, blk, K=K, N=N, frac=f, mode=mode)
        R[k] = T['stats'](e); R[k]['exposure'] = round(e.attrs['exposure'], 3); curves[k] = e
        print(k, R[k], flush=True)
for mode in ('TA', 'TB'):                      # 앞 10개도 같은 판정에 넣는다
    for K, N in [(10, 5), (8, 5), (13, 5), (10, 3), (10, 8)]:
        curves[f'{mode}_K{K}_N{N}_10%'] = T['sim'](P, M, blk, K=K, N=N, mode=mode)
idx = sorted(set.intersection(*[set(c.index) for c in curves.values()]))
CC = {k: (v.reindex(idx) / v.reindex(idx).iloc[0]).tolist() for k, v in curves.items()}
bb = bench.reindex(idx).ffill(); J = OF.judge(CC, list(CC), (bb / bb.iloc[0]).tolist(), {})
ov = {x: J['excess'][x] for x in ('best_key', 'dsr', 'pbo', 'verdict', 'family_sr_pos_share')}
print(json.dumps(ov, ensure_ascii=False))
json.dump(dict(made='2026-11-08', A=prev['A'], S2=prev['S2'], results=R, overfit_all20=ov),
          open(os.path.join(ROOT, 'results/tranche_k5_2026-11-08.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)
