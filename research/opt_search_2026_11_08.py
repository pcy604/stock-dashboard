# -*- coding: utf-8 -*-
"""최적 조건 탐색 — 사전 등록 (2026-11-08, 차니 "퀀트 전략 돌려보고 최적 조건 찾아봐")

과적합을 막는 방법을 결과 보기 전에 고정한다(이 파일 커밋 = 등록).
  표본: 한국(실전 시장), 수정주가 패널. **학습 2018-06-01~2022-06-30 / 검증 2022-07-01~끝** — 따로 돌린다(검증은 빈 계좌에서 시작).
  뼈대(고정): 시총 1,000억+ · 영업 흑자전환 · 주봉 5주선 위 · RS 순 · 매주 · 소속 지수 5주선 아래 신규 중지 · 비용 0.3%
    (뼈대 4개는 빼면 크게 나빠짐이 재측정에서 확인됨 — 탐색 대상 아님)
  탐색 축(5개, 3×3×4×3×3 = 324):
    RS 하한 {70, 80, 90} · 보유 수 {5, 7, 10} · 손절(고점 대비) {15, 20, 25, 30} ·
    불타기 {없음(100%) · 50→+10%·+20%에 25% · 60→+10%에 40%} · RS 탈락 매도 {없음, RS<50, RS<70}
  고르는 법(학습 구간만 봄): 학습 수익÷낙폭(Calmar) 최대, 단 학습 CAGR > 코스피.
  합격 기준(검증 구간):
    ① 고른 조합의 검증 CAGR > 코스피 검증 CAGR 그리고 > 현행 v1.9 검증 CAGR
    ② 고른 조합의 검증 MDD 가 v1.9 검증 MDD 보다 5%p 넘게 나쁘지 않음
    ③ 학습 상위 10% 조합의 검증 CAGR 중앙이 전체 조합 검증 중앙보다 높음(순위가 이어지나 — 아니면 고르기 자체가 운)
    ④ 이웃 안정성: 고른 조합에서 축 하나만 한 칸 바꾼 이웃들의 검증 CAGR 중앙이 v1.9 검증 CAGR 이상
  넷 다 통과해야 '실전 후보'. 아니면 현행 유지 + 관찰.
결과: results/opt_search_2026_11_08.json
"""
import os, sys, json, time, copy, itertools
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np
import pandas as pd
import ui_quant as U

TRAIN = ('2018-06-01', '2022-06-30')
TEST = ('2022-07-01', None)
AX = dict(rs=[70, 80, 90], pos=[5, 7, 10], stop=[15, 20, 25, 30], pyr=['none', '50_25_25', '60_40'], rsx=[0, 50, 70])
PYR = {'none': dict(init=1.0, pyramid=[]), '50_25_25': dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
       '60_40': dict(init=0.6, pyramid=[[10, 0.4]])}
V19 = dict(rs=80, pos=10, stop=20, pyr='50_25_25', rsx=70)


def spec(c, start, end):
    s = U.Q.merged(U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], 'KR'))
    s['filters'] = [f if f['field'] != 'rs' else dict(f, value=c['rs']) for f in s['filters']]
    s['max_pos'] = c['pos']
    s['max_w'] = max(0.30, round(1 / c['pos'], 4))
    s['entry'] = PYR[c['pyr']]
    s['exit'] = dict(s['exit'], trail=[[0, c['stop']]],
                     signals=[dict(type='field', field='rs', op='<', value=c['rsx'])] if c['rsx'] else [])
    s['start'] = start
    if end:
        s['end'] = end
    return s


def run(c, win):
    r = U._run('KR', json.dumps(spec(c, *win), sort_keys=True))
    S = r['stats']
    return dict(cagr=float(S['CAGR']), mdd=float(S['MDD']), bm=float(S['BM_CAGR']), bm_mdd=float(S['BM_MDD']),
                calmar=float(S['CAGR']) / abs(float(S['MDD'])) if S['MDD'] else 0.0)


def main():
    keys = list(AX)
    combos = [dict(zip(keys, v)) for v in itertools.product(*AX.values())]
    rows = []
    t0 = time.time()
    for i, c in enumerate(combos):
        a, b = run(c, TRAIN), run(c, TEST)
        rows.append(dict(**c, tr_cagr=a['cagr'], tr_mdd=a['mdd'], tr_calmar=a['calmar'], tr_bm=a['bm'],
                         te_cagr=b['cagr'], te_mdd=b['mdd'], te_calmar=b['calmar'], te_bm=b['bm']))
        if i % 20 == 0:
            print(i, len(combos), round(time.time() - t0), flush=True)
    D = pd.DataFrame(rows)
    v19 = D[(D.rs == 80) & (D.pos == 10) & (D.stop == 20) & (D.pyr == '50_25_25') & (D.rsx == 70)].iloc[0]
    elig = D[D.tr_cagr > D.tr_bm]
    pick = elig.sort_values('tr_calmar', ascending=False).iloc[0]
    # 이웃
    nb = []
    for k in keys:
        vals = AX[k]; i = vals.index(pick[k])
        for j in (i - 1, i + 1):
            if 0 <= j < len(vals):
                q = D
                for kk in keys:
                    q = q[q[kk] == (vals[j] if kk == k else pick[kk])]
                nb.append(q.iloc[0])
    nbm = float(np.median([x.te_cagr for x in nb]))
    top = D.sort_values('tr_calmar', ascending=False).head(max(1, len(D) // 10))
    c1 = bool(pick.te_cagr > pick.te_bm and pick.te_cagr > v19.te_cagr)
    c2 = bool(pick.te_mdd >= v19.te_mdd - 5)
    c3 = bool(top.te_cagr.median() > D.te_cagr.median())
    c4 = bool(nbm >= v19.te_cagr)
    rho = float(D[['tr_calmar', 'te_calmar']].corr(method='spearman').iloc[0, 1])
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), train=TRAIN, test=TEST, n=len(D),
               pick={k: (pick[k].item() if hasattr(pick[k], 'item') else pick[k]) for k in D.columns},
               v19={k: (v19[k].item() if hasattr(v19[k], 'item') else v19[k]) for k in D.columns},
               checks=dict(c1_beats=c1, c2_mdd=c2, c3_rank_persist=c3, c4_neighbors=c4, passed=c1 and c2 and c3 and c4),
               neighbors_test_cagr_median=nbm, top10pct_test_median=float(top.te_cagr.median()), all_test_median=float(D.te_cagr.median()),
               spearman_train_test_calmar=rho, rows=D.round(3).to_dict('records'))
    json.dump(out, open('results/opt_search_2026_11_08.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
