# -*- coding: utf-8 -*-
"""수정 데이터 재측정 (2026-11-08) — 한국 수정주가(kr_adjust)·미국 시총 정합(us_capfix)·미국 비교 지수 SPXTR 뒤,
그동안 내린 결정들의 비교 순위가 바뀌었는지 다시 잰다. 판정 기준은 옛 결정 때와 같게 '같은 표본·같은 비용'.
결과: results/remeasure_2026_11_08.json"""
import os, sys, json, time, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import ui_quant as U

V19 = U.Q.merged(U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], 'KR'))


def var(**kw):
    s = copy.deepcopy(V19)
    for k, v in kw.items():
        if isinstance(v, dict) and isinstance(s.get(k), dict):
            s[k].update(v)
        else:
            s[k] = v
    return s


KR = {
    'v1.9 (현행: 보유10·50/25/25·RS<70 매도)': V19,
    'v1.8 (보유5·60%+40%·RS 매도 없음)': var(max_pos=5, entry=dict(init=0.6, pyramid=[[10, 0.4]]), exit=dict(signals=[])),
    'v1.9 − RS<70 매도': var(exit=dict(signals=[])),
    'v1.9 − 불타기(한 번에 100%)': var(entry=dict(init=1.0, pyramid=[])),
    'v1.9 보유 5': var(max_pos=5),
    'v1.9 − 지수 5주선 게이트': var(exposure=dict(index='', mode='entry')),
    'v1.9 − 종목 5주선 필터': var(filters=[f for f in V19['filters'] if not f['field'].startswith('ma_gap')]),
    'v1.9 − 손절(고점 −20%)': var(exit=dict(trail=[])),
}


def run(m, spec):
    r = U._run(m, json.dumps(spec, sort_keys=True))
    S = r['stats']
    return dict(CAGR=round(float(S['CAGR']), 2), MDD=round(float(S['MDD']), 2), Sharpe=round(float(S['Sharpe']), 2),
                BM_CAGR=round(float(S['BM_CAGR']), 2), BM_MDD=round(float(S['BM_MDD']), 2), sells=int(S['매도건수']),
                start=str(r['equity'].index[0].date()))


def main():
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), KR={}, US={})
    for k, s in KR.items():
        out['KR'][k] = run('KR', s); print('KR', k, out['KR'][k], flush=True)
    for k in [p for p in U.PRESETS if not p.startswith('실전 규칙 +')]:
        out['US'][k] = run('US', U.Q.merged(U._fill(U.PRESETS[k], 'US'))); print('US', k, out['US'][k], flush=True)
    json.dump(out, open('results/remeasure_2026_11_08.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
