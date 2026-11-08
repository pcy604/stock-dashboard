# -*- coding: utf-8 -*-
"""차니 '10주 묶음' 전략 시뮬레이터 + 판정 — research/tranche_prereg_2026-11-08.md

엔진(quant_engine)과 같은 패널·필터·RS 순위·소속 시장 5주선 게이트·체결 규칙(금요일 종가 판정 → 다음 주 시가)을 쓰고,
보유 단위만 '종목'이 아니라 '로트(묶음에서 산 한 덩어리)'로 둔다.
"""
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

COST, STOP, COOL, CAP = 0.003, 0.20, 2, 0.30


def prep(P):
    S = Q.merged(json.loads(json.dumps(V8.LIVE)))
    C = P.base('close').values.astype(float)
    O = P.base('open').values.astype(float)
    O = np.where(np.isfinite(O), O, C)
    conds = [np.asarray(Q._cond(P.get(f['field']), f['op'], f['value']).fillna(False).values, bool) for f in S['filters']]
    ok = np.logical_and.reduce(conds)
    rk = P.get('rs').values.astype(float)
    return C, O, ok, rk


def sim(P, M, blk, K=10, N=5, frac=0.10, mode='TA'):
    C, O, ok, rk = M
    D = P.dates
    t0 = int(np.searchsorted(D, pd.Timestamp(V8.START)))
    T = len(D)
    cash, lots = 1.0, []                     # lot: dict(j, u, cost, t)
    peak, cool, last = {}, {}, {}
    eq = np.full(T, np.nan)
    inv = np.full(T, np.nan)                 # 주식 비중(노출) — 결과 해석용

    def px_c(t, j):
        v = C[t, j]
        if np.isfinite(v):
            last[j] = v
            return v
        return last.get(j, np.nan)

    for t in range(t0, T):
        held = {l['j'] for l in lots}
        val = {j: px_c(t, j) for j in held}
        E = cash + sum(l['u'] * val[l['j']] for l in lots if np.isfinite(val[l['j']]))
        eq[t] = E
        inv[t] = 1 - cash / E if E > 0 else np.nan
        if t + 1 >= T:
            break
        po = lambda j: O[t + 1, j] if np.isfinite(O[t + 1, j]) else val.get(j, last.get(j, np.nan))   # noqa: E731
        sells = set()
        # ① 손절(고점 −20%) — 종목 단위
        for j in held:
            c = val[j]
            if not np.isfinite(c):
                continue
            peak[j] = max(peak.get(j, c), c)
            if c <= peak[j] * (1 - STOP):
                sells.add(j)
        for j in sells:
            p = po(j)
            for l in [l for l in lots if l['j'] == j]:
                cash += l['u'] * p * (1 - COST); lots.remove(l)
            peak.pop(j, None); cool[j] = t + 1 + COOL
        # ② 만기
        for l in [l for l in lots if t - l['t'] >= K and not l.get('perm')]:
            p = po(l['j'])
            if not np.isfinite(p):
                continue
            if mode == 'TA':
                cash += l['u'] * p * (1 - COST); lots.remove(l)
            else:                                            # TB: 원금 넘는 이익분만 덜고 계속 보유
                v = l['u'] * p
                if v > l['cost']:
                    cut = (v - l['cost']) / p
                    l['u'] -= cut; cash += cut * p * (1 - COST)
                l['perm'] = True
        if not any(l['j'] in val for l in lots):
            pass
        # ③ 이번 주 묶음
        cand = np.where(ok[t] & np.isfinite(rk[t]) & np.isfinite(C[t]) & ~blk[t])[0]
        cand = [j for j in cand[np.argsort(-rk[t, cand])] if cool.get(j, -1) <= t + 1][:N]
        if not cand:
            continue
        E2 = cash + sum(l['u'] * (val.get(l['j']) if np.isfinite(val.get(l['j'], np.nan)) else 0) for l in lots)
        each = frac * E2 / N
        hold_v = {}
        for l in lots:
            hold_v[l['j']] = hold_v.get(l['j'], 0) + l['u'] * (val.get(l['j']) or 0)
        want = {j: max(0.0, min(each, CAP * E2 - hold_v.get(j, 0))) for j in cand}
        need = sum(want.values()) * (1 + COST)
        # ④ 현금 부족 → 평가수익률 가장 약한 종목부터 통째로 매도(이번 주 매수 대상은 제외)
        if cash < need:
            agg = {}
            for l in lots:
                a = agg.setdefault(l['j'], [0.0, 0.0]); a[0] += l['u'] * (val.get(l['j']) or 0); a[1] += l['cost']
            order = sorted([j for j in agg if j not in want], key=lambda j: agg[j][0] / agg[j][1] if agg[j][1] else 0)
            for j in order:
                if cash >= need:
                    break
                p = po(j)
                if not np.isfinite(p):
                    continue
                for l in [l for l in lots if l['j'] == j]:
                    cash += l['u'] * p * (1 - COST); lots.remove(l)
                peak.pop(j, None)
        scale = min(1.0, cash / need) if need > 0 else 0
        for j, a in want.items():
            a *= scale
            p = O[t + 1, j]
            if a <= 0 or not np.isfinite(p) or p <= 0:
                continue
            u = a / (p * (1 + COST)); cash -= a
            lots.append(dict(j=j, u=u, cost=a, t=t + 1))
            peak.setdefault(j, p)
    out = pd.Series(eq, index=D).dropna()
    out.attrs['exposure'] = float(np.nanmean(inv))
    return out


def stats(eq):
    def seg(a, b=None):
        e = eq[(eq.index >= a) & ((eq.index < b) if b else True)]
        y = (e.index[-1] - e.index[0]).days / 365.25
        return round(float((e.iloc[-1] / e.iloc[0]) ** (1 / y) - 1) * 100, 1), round(float((e / e.cummax() - 1).min()) * 100, 1)
    c, m = seg(V8.START); c1, m1 = seg(V8.START, V8.SPLIT); c2, m2 = seg(V8.SPLIT)
    return dict(cagr=c, mdd=m, p1=c1, p1_mdd=m1, p2=c2, p2_mdd=m2, calmar=round(c / abs(m), 3))


def main(path):
    P, df = V9.load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    blk = np.asarray(blk, bool)
    bench = V8.index_w('KOSPI')
    M = prep(P)
    A = V8.run(P, blk, bench)
    S2 = V8.run(P, blk, bench, max_pos=10, entry=V9.PYR['S2'])
    print('A ', A); print('S2', S2)
    R, curves = {}, {}
    grid = [(10, 5), (8, 5), (13, 5), (10, 3), (10, 8)]
    for mode in ('TA', 'TB'):
        for K, N in grid:
            k = f'{mode}_K{K}_N{N}'
            e = sim(P, M, blk, K=K, N=N, mode=mode)
            R[k] = stats(e); R[k]['exposure'] = round(e.attrs['exposure'], 3); curves[k] = e
            print(k, R[k], flush=True)

    def ok1(x):
        return bool((x['mdd'] - A['mdd'] >= 5 and A['cagr'] - x['cagr'] <= 3) or (x['cagr'] >= A['cagr'] and x['mdd'] - A['mdd'] >= -3))

    def ok2(x):
        return bool(x['p1'] >= A['p1'] - 5 and x['p2'] >= A['p2'] - 5 and x['p1_mdd'] >= A['p1_mdd'] and x['p2_mdd'] >= A['p2_mdd'])
    V = {}
    for mode in ('TA', 'TB'):
        main_ = R[f'{mode}_K10_N5']
        nb = [ok1(R[f'{mode}_K{K}_N{N}']) for K, N in grid[1:]]
        V[mode] = dict(main=ok1(main_), periods=ok2(main_), neighbors=f'{sum(nb)}/4',
                       adopt=bool(ok1(main_) and ok2(main_) and sum(nb) >= 3),
                       vs_S2=dict(cagr=round(main_['cagr'] - S2['cagr'], 1), mdd=round(main_['mdd'] - S2['mdd'], 1)))
    idx = sorted(set.intersection(*[set(c.index) for c in curves.values()]))
    CC = {k: (v.reindex(idx) / v.reindex(idx).iloc[0]).tolist() for k, v in curves.items()}
    bb = bench.reindex(idx).ffill()
    J = OF.judge(CC, list(CC), (bb / bb.iloc[0]).tolist(), {})
    V['overfit'] = {x: J['excess'][x] for x in ('best_key', 'dsr', 'pbo', 'verdict', 'family_sr_pos_share')}
    print(json.dumps(V, ensure_ascii=False, indent=1))
    json.dump(dict(made='2026-11-08', prereg='research/tranche_prereg_2026-11-08.md', A=A, S2=S2, results=R, verdict=V),
              open(os.path.join(ROOT, 'results/tranche_test_2026-11-08.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=float)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
