# -*- coding: utf-8 -*-
"""흑자전환 OR 영업이익 YoY θ · 신호 재진입 · 52주 신고가 — 사전 등록 (2026-11-10, 차니 세 가지, 한국·미국 둘 다)

계기: 주성엔지니어링·피에스케이홀딩스(2026 반도체 주도주)가 1년 내내 '흑자전환 0' 이라 v1.9 후보에 한 번도 못 들어옴
(이미 흑자인 고성장 회사). 이 파일 커밋 = 등록(결과 보기 전). 기준 = 실전 v1.9 명세 그대로(시장만 바꿈, 미국은 S&P500 5주선 게이트).
구간: 학습 2018-06-01~2022-06-30 / 검증 2022-07-01~ / 전체 2018-06-01~. 시장 KR·US 각각 따로 판정.
  T1 흑자전환 OR 영업이익 YoY ≥ θ (op_yoy 는 전년 같은 분기 흑자일 때만 계산 → 흑자전환과 겹치지 않음)
     θ 스펙트럼 {20, 30, 50, 75, 100, 150, 200}%. 고르는 법: 학습 Calmar 최대 θ*.
     합격(넷 다): ① θ* 가 v1.9 보다 Calmar 학습·검증 둘 다 높다 ② 전체 MDD 2%p 넘게 나빠지지 않고 CAGR 1%p 넘게 낮지 않다
       ③ θ* 양옆 θ 의 전체 Calmar 평균 ≥ v1.9 ④ 폭: 7개 θ 중 4개 이상이 전체 Calmar 에서 v1.9 를 이긴다(한 점만 좋은 톱니 배제)
  T2 신호 재진입(차니 "신호 다시 뜨면 다시 사자") — 손절·래칫으로 판 종목이 26주 안에 v1.9 조건을 다시 만족하면
     냉각(2주) 없이, 그 주 신규 후보 중 **맨 앞**에 세운다(종목 수 상한·지수 게이트·현금은 그대로 지킨다).
     이웃: 우선권 기간 13·52주, '냉각 0 만(우선권 없음)'.  합격: T1 의 ①②, ③ 이웃 3개 전체 Calmar 중앙 ≥ v1.9,
     ④ (KR) 한국 5년 대박주 중 '매도 수익 곱이 손해' 종목 수가 v1.9 보다 적다 / (US) 매매 횟수 ≤ v1.9 × 2
  T3 52주 신고가 주에만 신규(nh:52 == 1) — **미국만**(한국은 2b1df73 에서 근소 탈락, 같은 기준으로 독립 표본 확인)
     이웃: 26·39주 신고가, 52주 고점 −5% 이내.  합격: T1 의 ①②, ③ 이웃 중앙 Calmar ≥ v1.9, ④ 매매 횟수 ≤ v1.9 × 3
결과: results/oiyoy_resignal_nh_2026_11_10.json
"""
import os, sys, json, time, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np
import pandas as pd
import ui_quant as U

WIN = dict(train=('2018-06-01', '2022-06-30'), test=('2022-07-01', None), full=('2018-06-01', None))
PRE = U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)']
THETA = [20, 30, 50, 75, 100, 150, 200]


def base(m):
    return U.Q.merged(U._fill(PRE, m))


def run(s, w, m):
    s = copy.deepcopy(s); s['start'] = w[0]
    if w[1]:
        s['end'] = w[1]
    else:
        s.pop('end', None)
    o = U._run(m, json.dumps(s, sort_keys=True))
    S = o['stats']; c, d = float(S['CAGR']), float(S['MDD'])
    return dict(cagr=round(c, 2), mdd=round(d, 2), calmar=round(c / abs(d), 3) if d else 0.0, n=int(len(o['trades']))), o['trades']


def three(s, m):
    r = {}
    for k, w in WIN.items():
        r[k], T = run(s, w, m)
        if k == 'full':
            r['_T'] = T
    return r


def winners_loss(T):
    R = json.load(open('results/winners_reverse.json', encoding='utf-8'))['markets']['KR']
    ws = {str(w['sym']) for w in R['winners']}
    T = T.copy(); T['코드'] = T['코드'].astype(str); T['날짜'] = pd.to_datetime(T['날짜'])
    t = T[(T['날짜'] >= pd.Timestamp(R['window'][0])) & T['코드'].isin(ws)]
    n = 0
    for _, x in t.groupby('코드'):
        s = x[x['구분'] == '매도']
        if len(s) and ((s['수익률'].fillna(0) / 100 + 1).prod() - 1) < 0:
            n += 1
    return n


def with_theta(m, th):
    s = base(m)
    fl = s['filters']
    i_turn = next(i for i, f in enumerate(fl) if f['field'] == 'op_turn') + 1
    fl.append(dict(field='op_yoy', op='>=', value=float(th)))
    n = len(fl)
    others = [str(i) for i in range(1, n) if i != i_turn]
    s['logic'] = ' AND '.join(others) + f' AND ({i_turn} OR {n})'
    return s


def with_resig(m, weeks=26, pri=True):
    s = base(m)
    s['exit']['cooldown'] = 0
    if pri:
        s['exit']['reentry_signal'] = dict(weeks=weeks)
    return s


def with_nh(m, f, op, v):
    s = base(m)
    s['filters'].append(dict(field=f, op=op, value=v))
    return s


def clean(r):
    return {k: v for k, v in r.items() if k != '_T'}


def judge12(r, v):
    c1 = r['train']['calmar'] > v['train']['calmar'] and r['test']['calmar'] > v['test']['calmar']
    c2 = r['full']['mdd'] >= v['full']['mdd'] - 2 and r['full']['cagr'] >= v['full']['cagr'] - 1
    return bool(c1), bool(c2)


def main():
    t0 = time.time()
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), markets={})
    for m in ('KR', 'US'):
        v = three(base(m), m)
        vw = winners_loss(v['_T']) if m == 'KR' else None
        M = dict(v19=clean(v), v19_winners_loss=vw)
        # T1
        rows = {th: three(with_theta(m, th), m) for th in THETA}
        best = max(THETA, key=lambda th: rows[th]['train']['calmar'])
        r = rows[best]; c1, c2 = judge12(r, v)
        i = THETA.index(best); nb = [THETA[j] for j in (i - 1, i + 1) if 0 <= j < len(THETA)]
        c3 = float(np.mean([rows[x]['full']['calmar'] for x in nb])) >= v['full']['calmar']
        c4 = sum(rows[x]['full']['calmar'] > v['full']['calmar'] for x in THETA) >= 4
        M['T1'] = dict(rows={th: clean(x) for th, x in rows.items()}, pick=best,
                       checks=dict(c1=c1, c2=c2, c3=bool(c3), c4=bool(c4), passed=bool(c1 and c2 and c3 and c4)))
        print(m, 'T1', round(time.time() - t0), M['T1']['checks'], flush=True)
        # T2
        r = three(with_resig(m), m); c1, c2 = judge12(r, v)
        nbs = {'w13': run(with_resig(m, 13), WIN['full'], m)[0], 'w52': run(with_resig(m, 52), WIN['full'], m)[0],
               'cool0_only': run(with_resig(m, pri=False), WIN['full'], m)[0]}
        c3 = float(np.median([x['calmar'] for x in nbs.values()])) >= v['full']['calmar']
        if m == 'KR':
            wl = winners_loss(r['_T']); c4 = wl < vw
        else:
            wl = None; c4 = r['full']['n'] <= 2 * v['full']['n']
        M['T2'] = dict(main=clean(r), neighbors=nbs, winners_loss=wl,
                       checks=dict(c1=c1, c2=c2, c3=bool(c3), c4=bool(c4), passed=bool(c1 and c2 and c3 and c4)))
        print(m, 'T2', round(time.time() - t0), M['T2']['checks'], flush=True)
        # T3 (US only)
        if m == 'US':
            r = three(with_nh(m, 'nh:52', '==', 1), m); c1, c2 = judge12(r, v)
            nbs = {'nh26': run(with_nh(m, 'nh:26', '==', 1), WIN['full'], m)[0],
                   'nh39': run(with_nh(m, 'nh:39', '==', 1), WIN['full'], m)[0],
                   'hi5': run(with_nh(m, 'dist_hi:52', '>=', -5), WIN['full'], m)[0]}
            c3 = float(np.median([x['calmar'] for x in nbs.values()])) >= v['full']['calmar']
            c4 = r['full']['n'] <= 3 * v['full']['n']
            M['T3'] = dict(main=clean(r), neighbors=nbs,
                           checks=dict(c1=c1, c2=c2, c3=bool(c3), c4=bool(c4), passed=bool(c1 and c2 and c3 and c4)))
            print(m, 'T3', round(time.time() - t0), M['T3']['checks'], flush=True)
        out['markets'][m] = M
    json.dump(out, open('results/oiyoy_resignal_nh_2026_11_10.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)


if __name__ == '__main__':
    main()
