# -*- coding: utf-8 -*-
"""이익 개선폭 θ 스윕(차니 11-08 '스프레드 벌려 최적 n% 찾기') + 과적합 판정(DSR·PBO, 검증 공통 규칙 9번).
기준: 한국 실전 명세 · RS≥80 × (흑자전환 OR oi_g ≥ θ) × 5주선 × 시총 1,000억+ · 2018-06~. 보유 5(현행)·보유 10(첫 50%+25%×2) 두 체계."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q                       # noqa: E402
import live_v18_test as V8                     # noqa: E402
import live_v19_test as V9                     # noqa: E402
import overfit as OF                           # noqa: E402

TH = [0, 2.5, 5, 7.5, 10, 12.5, 15, 17.5, 20, 25, 30, 40]
SYS = {'보유5': {}, '보유10_S2': dict(max_pos=10, entry=V9.PYR['S2'])}


def filt(th):
    if th is None:
        return {}
    return dict(filters=[dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
                         dict(field='op_turn', op='==', value=1), dict(field='oi_g', op='>=', value=th),
                         dict(field='ma_gap:5', op='>', value=0)], logic='1 AND 2 AND (3 OR 4) AND 5')


def main(path):
    P, df = V9.load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    bench = V8.index_w('KOSPI')
    out = {}
    for sname, sover in SYS.items():
        rows, curves = [], {}
        for th in [None] + TH:
            s = json.loads(json.dumps(V8.LIVE)); s.update(sover); s.update(filt(th))
            r = Q.run(P, s, bench_px=bench, entry_block=blk)
            eq = r['equity']; eq = eq[eq.index >= V8.START]
            summ = V8.run(P, blk, bench, **sover, **filt(th))
            k = '흑자전환만' if th is None else f'θ{th}'
            rows.append(dict(key=k, **summ)); curves[k] = eq
            print(sname, k, summ, flush=True)
        idx = sorted(set.intersection(*[set(c.index) for c in curves.values()]))
        C = {k: (v.reindex(idx) / v.reindex(idx).iloc[0]).tolist() for k, v in curves.items()}
        b = bench.reindex(idx).ffill(); B = (b / b.iloc[0]).tolist()
        keys = [k for k in C if k != '흑자전환만']
        J = OF.judge(C, keys, B, {})
        out[sname] = dict(rows=rows, overfit={m: {x: J[m][x] for x in ('best_key', 'dsr', 'pbo', 'verdict', 'family_sr_pos_share')} for m in J})
        print(sname, json.dumps(out[sname]['overfit'], ensure_ascii=False), flush=True)
    json.dump(dict(made='2026-11-08', thetas=TH, systems=out), open(os.path.join(ROOT, 'results/oi_sweep_2026-11-08.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
