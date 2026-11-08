# -*- coding: utf-8 -*-
"""지수 신호 '현금 비중 확대' 사전 등록 검증 (2026-11-08, 차니 요청) — 엔진 quant_engine.cash_state

질문: ① 지수 n일·n주선 이탈 시 현금 확대(재진입 4방식) ② 지수 신고가 뒤 n일·n주 정체 시 현금 확대(재진입 2방식)
      가 v1.9 실전 규칙(한국)과 같은 뼈대의 미국판에서 낙폭을 줄이는 값을 수익으로 얼마나 치르나.
기준선: v1.9 (한국 2018-06~, 소속 시장 5주선 신규 중지) / 미국판(같은 규칙, S&P500 40주선 신규 중지, 2015~)
현금 확대 수준 level ∈ {0(전량 현금), 0.5}
합격(결과 보기 전 고정): CAGR 하락 ≤ 3%p 그리고 MDD 개선 ≥ 5%p, 그리고 같은 규칙·재진입·수준에서 이웃 n 의 절반 이상도 합격.
결과: results/cash_gate_check.json
"""
import os, sys, json, time, itertools
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)
import ui_quant as U
import quant_engine as Q

GRID = []
for unit, ns in (('w', [5, 10, 20, 40]), ('d', [20, 60, 120, 200])):
    for n, re_, lv in itertools.product(ns, ['ma', 'confirm', 'rising', 'band'], [0.0, 0.5]):
        GRID.append(dict(rule='ma', unit=unit, n=n, reentry=re_, k=2 if unit == 'w' else 5, x=2.0, level=lv))
for unit, ns, hi, m_ in (('w', [4, 8, 13, 26], 52, 10), ('d', [20, 40, 60, 120], 252, 50)):
    for n, re_, lv in itertools.product(ns, ['new_high', 'ma'], [0.0, 0.5]):
        GRID.append(dict(rule='stall', unit=unit, n=n, hi=hi, m=m_, reentry=re_, level=lv))


def base_spec(m):
    s = U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], m)
    s['market'] = m
    s['start'] = '2018-06-01' if m == 'KR' else '2015-01-01'
    if m == 'US':
        s['exposure'].update(index='SPX', ma=40)
    return Q.merged(s)


def run(m, spec):
    r = U._run(m, json.dumps(spec, sort_keys=True))
    S = r['stats']
    return dict(cagr=round(S['CAGR'], 2), mdd=round(S['MDD'], 2), expo=round(float(r['exposure'].mean()) * 100, 1))


def main():
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), grid=len(GRID), markets={})
    for m, ix in (('KR', 'KOSPI'), ('US', 'SPX')):
        b = base_spec(m)
        B = run(m, b)
        rows = []
        for g in GRID:
            sp = json.loads(json.dumps(b)); sp['cash'] = dict(index=ix, **g)
            r = run(m, sp)
            r.update(g, dcagr=round(r['cagr'] - B['cagr'], 2), dmdd=round(r['mdd'] - B['mdd'], 2))
            r['pass1'] = r['dcagr'] >= -3 and r['dmdd'] >= 5
            rows.append(r)
            print(m, g, r['cagr'], r['mdd'], 'PASS' if r['pass1'] else '', flush=True)
        D = pd.DataFrame(rows)
        key = ['rule', 'unit', 'reentry', 'level']
        D['pass'] = False
        for _, G in D.groupby(key):
            G = G.sort_values('n')
            for i, (ix_, r) in enumerate(G.iterrows()):
                nb = G.iloc[[x for x in (i - 1, i + 1) if 0 <= x < len(G)]]
                D.loc[ix_, 'pass'] = bool(r.pass1 and nb.pass1.mean() >= 0.5)
        out['markets'][m] = dict(base=B, rows=D.to_dict('records'), n_pass=int(D['pass'].sum()))
        print(m, 'base', B, '합격', int(D['pass'].sum()), '/', len(D), flush=True)
    json.dump(out, open('results/cash_gate_check.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
