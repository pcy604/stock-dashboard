# -*- coding: utf-8 -*-
"""클라이맥스(과열 고점) '관상' 검증 — 사전 등록 (2026-11-10, 차니 "삼성 21-01·에코프로 23·메모리 26-06 고점, 차트로 발라낼 수 있을 것 같은데")

이 파일 커밋 = 등록(결과 보기 전). 한국·수정주가 패널, 기준 = 실전 v1.9 그대로(RS<70 탈락 매도 유지 — 차니 11-10 결정).
신호(그 주 종가로 판정 → 다음 주 시가 체결, 보유 종목이 진입가 대비 +20% 이상일 때만 = min_gain 20):
  ext    40주선 대비 +70% 이상          vol    주간 거래량 ≥ 직전 52주 평균 × 3 그리고 주간 +10% 이상
  rsi    주봉 RSI(14) ≥ 85              streak 양봉(전주 대비 상승) 8주 연속
  accel  4주 수익 +50% 이상             combo  위 다섯 중 2개 이상 동시
행동: sell(전량 매도) · half(절반 덜기, 보유당 1번) · tight(그때부터 손절을 고점 −20% → −10% 로 조임)
본판 6 × 3 = 18. 구간: 학습 2018-06-01~2022-06-30 / 검증 2022-07-01~ (빈 계좌에서 따로) / 전체 2018-06-01~.
고르는 법: 학습 수익÷낙폭(Calmar) 최대 1개.
합격 기준(넷 다):
  ① 고른 조합이 v1.9 보다 Calmar 가 학습·검증 **둘 다** 높다
  ② 전체 구간 MDD 2%p 이상 개선, CAGR 하락 2%p 이하
  ③ 이웃: 문턱 한 칸(ext 50/100 · vol 2/5 · rsi 80/90 · streak 6/10 · accel 30/80 · combo 3), min_gain 0/40,
     (tight 이면) 조임 5/15 — 이웃들의 전체 Calmar 중앙 ≥ v1.9 전체 Calmar
  ④ 메커니즘: 사건 연구 — 주도주 국면(시총 1,000억+·RS≥80·40주선 위 20%+) 주 중 고른 신호가 뜬 주의 이후 26주 수익 중앙이
     신호 없는 주보다 낮다(신호가 '앞으로 약해짐'을 실제로 가른다)
  하나라도 실패 → 기각, 화면 프리셋은 넣지 않고 참고 기록만.
참고(판정에 안 씀): 차니가 든 세 고점(삼성 2021-01, 에코프로 2023-07, SK하이닉스·삼성 2026-06)에서 어느 신호가 언제 떴나.
결과: results/climax_top_2026_11_10.json
"""
import os, sys, json, time, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np
import pandas as pd
import ui_quant as U

TRAIN, TEST, FULL = ('2018-06-01', '2022-06-30'), ('2022-07-01', None), ('2018-06-01', None)
RULES = dict(ext=70, vol=3, rsi=85, streak=8, accel=50, combo=2)
NB = dict(ext=[50, 100], vol=[2, 5], rsi=[80, 90], streak=[6, 10], accel=[30, 80], combo=[3])
ACTIONS = ['sell', 'half', 'tight']
BASE = U.Q.merged(U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], 'KR'))
CASES = [('005930', '삼성전자', '2020-10-01', '2021-06-30'), ('086520', '에코프로', '2023-04-01', '2023-10-31'),
         ('247540', '에코프로비엠', '2023-04-01', '2023-10-31'), ('000660', 'SK하이닉스', '2026-03-01', '2026-09-30'),
         ('005930', '삼성전자', '2026-03-01', '2026-09-30')]


def spec(sig, win):
    s = copy.deepcopy(BASE)
    if sig:
        s['exit']['signals'] = list(s['exit']['signals']) + [sig]
    s['start'] = win[0]
    if win[1]:
        s['end'] = win[1]
    else:
        s.pop('end', None)
    return s


def run(sig, win):
    S = U._run('KR', json.dumps(spec(sig, win), sort_keys=True))['stats']
    c, m = float(S['CAGR']), float(S['MDD'])
    return dict(cagr=round(c, 2), mdd=round(m, 2), calmar=round(c / abs(m), 3) if m else 0.0)


def sig(rule, x, action, mg=20, x2=10):
    return dict(type='climax', rule=rule, x=x, action=action, min_gain=mg, x2=x2)


def event_study(P, rule, x):
    mc, rs, gap = P.base('marcap'), P.get('rs'), P.get('ma_gap:40')
    c = P.base('close')
    lead = (mc >= 1e11) & (rs >= 80) & (gap >= 20)
    S = U.Q.climax_matrix(P, rule, x).fillna(False)
    f26 = (c.shift(-26) / c - 1) * 100
    mdd26 = (c[::-1].rolling(26, min_periods=10).min()[::-1].shift(-1) / c - 1) * 100
    up26 = (c[::-1].rolling(26, min_periods=10).max()[::-1].shift(-1) / c - 1) * 100
    win = c.index >= pd.Timestamp('2014-06-01')
    out = {}
    for nm, M in (('신호', lead & S), ('신호 없음', lead & ~S)):
        M = M.loc[win]
        v, d, u = f26.loc[win][M].stack(), mdd26.loc[win][M].stack(), up26.loc[win][M].stack()
        out[nm] = dict(n=int(v.notna().sum()), fwd26_med=round(float(v.median()), 2), mdd26_med=round(float(d.median()), 2),
                       up50_pct=round(float((u >= 50).mean() * 100), 1), dn30_pct=round(float((d <= -30).mean() * 100), 1))
    return out


def cases(P):
    out = []
    for sym, nm, a, b in CASES:
        if sym not in P.syms:
            out.append(dict(종목=nm, 메모='패널에 없음')); continue
        c = P.base('close')[sym]
        seg = c.loc[a:b].dropna()
        if not len(seg):
            out.append(dict(종목=nm, 메모='구간 데이터 없음')); continue
        pk = seg.idxmax()
        row = dict(종목=nm, 고점주=str(pk.date()), 고점=float(seg.max()))
        for r, x in RULES.items():
            M = U.Q.climax_matrix(P, r, x)[sym].loc[a:b].fillna(False)
            hits = M[M].index
            row[r] = ', '.join(f"{h.date()}({(c[h] / seg.max() - 1) * 100:+.0f}%)" for h in hits[:4]) or '-'
        out.append(row)
    return out


def main():
    t0 = time.time()
    v19 = {k: run(None, w) for k, w in (('train', TRAIN), ('test', TEST), ('full', FULL))}
    rows = []
    for r, x in RULES.items():
        for a in ACTIONS:
            g = sig(r, x, a)
            rows.append(dict(rule=r, x=x, action=a, **{f'{k}_{m}': v for k, w in (('tr', TRAIN), ('te', TEST), ('fu', FULL))
                                                      for m, v in run(g, w).items()}))
            print(r, a, round(time.time() - t0), flush=True)
    D = pd.DataFrame(rows)
    pick = D.sort_values('tr_calmar', ascending=False).iloc[0]
    # 이웃
    nbs = []
    for x in NB[pick.rule]:
        nbs.append(('x', x, run(sig(pick.rule, x, pick.action), FULL)))
    for mg in (0, 40):
        nbs.append(('min_gain', mg, run(sig(pick.rule, pick.x, pick.action, mg=mg), FULL)))
    if pick.action == 'tight':
        for x2 in (5, 15):
            nbs.append(('x2', x2, run(sig(pick.rule, pick.x, pick.action, x2=x2), FULL)))
    nb_med = float(np.median([n[2]['calmar'] for n in nbs]))
    P = U._panel('KR')
    ev = event_study(P, pick.rule, pick.x)
    ev_all = {r: event_study(P, r, x) for r, x in RULES.items()}
    c1 = bool(pick.tr_calmar > v19['train']['calmar'] and pick.te_calmar > v19['test']['calmar'])
    c2 = bool(pick.fu_mdd >= v19['full']['mdd'] + 2 and pick.fu_cagr >= v19['full']['cagr'] - 2)
    c3 = bool(nb_med >= v19['full']['calmar'])
    c4 = bool(ev['신호']['fwd26_med'] < ev['신호 없음']['fwd26_med'])
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), v19=v19, pick=pick.to_dict(),
               checks=dict(c1_both_halves=c1, c2_full_mdd_cagr=c2, c3_neighbors=c3, c4_mechanism=c4,
                           passed=c1 and c2 and c3 and c4),
               neighbors=[dict(param=a, value=b, **c) for a, b, c in nbs], neighbors_calmar_median=nb_med,
               event_study=ev_all, cases=cases(P), rows=D.to_dict('records'))
    json.dump(out, open('results/climax_top_2026_11_10.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps({k: v for k, v in out.items() if k != 'rows'}, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
