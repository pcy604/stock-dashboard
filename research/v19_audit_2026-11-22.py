# -*- coding: utf-8 -*-
"""v1.9 백테스트 엔진 감사 — 워크포워드 재검증 + 상폐충격 민감도 (2026-11-22, 백로그 #3)

  python research/v19_audit_2026-11-22.py [quant_panel_KR.parquet 경로]
결과: results/v19_audit_2026-11-22.json

세 가지를 묻는다.
 ① **워크포워드**: 기간을 겹치지 않게 잘라도 v1.9 가 KOSPI 를 이기나. 한 구간의 운으로
    전체 CAGR 이 만들어졌는지 본다(results/v19_bt.json 은 전체 기간 한 줄뿐이었다).
 ② **상폐충격**: 엔진은 가격이 끊긴 종목을 '마지막 종가에 전액' 턴다 = 낙관적이다.
    CLAUDE.md 규칙대로 크기를 잰다 — 연 부도율 r 을 가정해 주간 수익률에 (1−r)^(1/52) 를
    곱하고, 알파가 사라지는 손익분기 r 을 찾는다(leaders 쪽 consensus_alloc.simulate 와 같은 방식).
 ③ **1주 지연·거래비용**: 지연을 없애고/비용을 0 으로 돌려 성과가 얼마나 부풀는지.
    부풀지 않으면 그 장치가 실제로 안 걸려 있다는 뜻이다.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q                                   # noqa: E402
import live_v18_test as V8                                 # noqa: E402
import live_v19_test as V9                                 # noqa: E402

# v1.9 — ui_quant.py PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'] 를 글자 그대로 옮긴 것.
#   LIQ(한국 시총 하한) = 1e11, IDX 는 소속 시장 지수라 entry_block 으로 준다(exposure.index='').
#   RS 70 아래 매도(주도주 탈락)가 핵심 — 이게 빠지면 CAGR 이 8.8% 로 반토막 난다(감사 1차 시도).
V19 = dict(market='KR', start='2017-06-05',
           filters=[dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
                    dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
           rank=dict(field='rs', desc=True), rebalance=1, max_pos=10, max_w=0.30, trim='cap',
           entry=dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
           exposure=dict(index='', ma=5, below=0.0, mode='entry'),
           exit=dict(stop=0, trail=[[0, 20]], cooldown=2,
                     signals=[dict(type='field', field='rs', op='<', value=70)]))

WF = [('2017-06-05', '2019-07-01'), ('2019-07-01', '2021-07-01'),
      ('2021-07-01', '2023-07-01'), ('2023-07-01', '2026-11-09')]


def seg_stats(eq, a, b):
    e = eq[(eq.index >= pd.Timestamp(a)) & (eq.index < pd.Timestamp(b))]
    if len(e) < 10:
        return None
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return dict(CAGR=round(float((e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100, 2),
                MDD=round(float((e / e.cummax() - 1).min()) * 100, 2),
                weeks=int(len(e)), years=round(yrs, 2))


def shock(eq, r_year):
    """주간 수익률에 연 부도율 r 을 균등 분산해 곱한다. r=0 이면 원본."""
    if not r_year:
        return eq
    g = eq.pct_change().fillna(0.0) + 1.0
    return (g * (1 - r_year) ** (1 / 52)).cumprod() * float(eq.iloc[0])


def main(path):
    P, _ = V9.load(path)
    blk = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)
    bench = V8.index_w('KOSPI')

    def run(spec):
        return Q.run(P, spec, bench_px=bench, entry_block=blk)

    base = run(V19)
    eq, bm = base['equity'], base['bench'].dropna()
    full = seg_stats(eq, V19['start'], '2026-11-10')
    full_bm = seg_stats(bm, V19['start'], '2026-11-10')
    print(f"전체  전략 {full}  KOSPI {full_bm}", flush=True)

    # ── ① 워크포워드 ────────────────────────────────────────────────────
    wf = []
    for a, b in WF:
        s, m = seg_stats(eq, a, b), seg_stats(bm, a, b)
        beat = None if not (s and m) else bool(s['CAGR'] > m['CAGR'])
        wf.append(dict(start=a, end=b, strat=s, kospi=m, beat=beat))
        print(f"  {a}~{b}  전략 {s and s['CAGR']}%/{s and s['MDD']}%  "
              f"KOSPI {m and m['CAGR']}%/{m and m['MDD']}%  이김={beat}", flush=True)
    wf_beat = sum(1 for w in wf if w['beat'])

    # ── ② 상폐충격 손익분기 ──────────────────────────────────────────────
    sh = {}
    for r in (0.0, 0.005, 0.01, 0.02, 0.03, 0.05, 0.08):
        st = seg_stats(shock(eq, r), V19['start'], '2026-11-10')
        sh[f'{r:.3f}'] = st
        print(f"  부도율 연 {r*100:.1f}% → CAGR {st['CAGR']}% (KOSPI {full_bm['CAGR']}%)", flush=True)
    be = next((float(k) for k, v in sh.items() if v['CAGR'] <= full_bm['CAGR']), None)

    # ── ③ 지연·비용 장치가 실제로 걸려 있나 ───────────────────────────────
    nocost = seg_stats(run(dict(V19, cost=0.0))['equity'], V19['start'], '2026-11-10')
    print(f"  비용 0 → CAGR {nocost['CAGR']}% (기본 0.3% 일 때 {full['CAGR']}%)", flush=True)
    hicost = seg_stats(run(dict(V19, cost=0.01))['equity'], V19['start'], '2026-11-10')
    print(f"  비용 1.0% → CAGR {hicost['CAGR']}%", flush=True)

    T = base['trades']
    delay_ok = None
    if len(T):
        d = pd.to_datetime(T['날짜'])
        delay_ok = bool((d.isin(pd.DatetimeIndex(P.dates))).all())

    out = dict(made=str(pd.Timestamp.today().date()), rule='v1.9', market='KR',
               panel=os.path.basename(path), spec=V19,
               full=full, kospi=full_bm,
               walkforward=dict(periods=wf, beat=wf_beat, of=len(wf)),
               shock=dict(table=sh, breakeven_default_rate=be,
                          note='알파가 KOSPI 와 같아지는 연 부도율. 평시 실제 부도율 0.3~0.5%'),
               cost=dict(zero=nocost, base=full, one_pct=hicost,
                         base_minus_zero=round(nocost['CAGR'] - full['CAGR'], 2)),
               delay=dict(all_trades_on_panel_weeks=delay_ok,
                          note='체결가는 판정 다음 주 시가 — tests/test_quant_engine_golden.py 가 정확한 값으로 검증'),
               trades=int(len(T)))
    p = os.path.join(ROOT, 'results/v19_audit_2026-11-22.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('\n저장:', p)
    print(f"워크포워드 {wf_beat}/{len(wf)} 구간에서 KOSPI 상회 · 상폐 손익분기 연 {be}")


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
