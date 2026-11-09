# -*- coding: utf-8 -*-
"""재진입 · 월간 매수 · 52주 신고가만 — 사전 등록 (2026-11-10, 차니 세 가지 제안)

이 파일 커밋 = 등록(결과 보기 전). 한국·수정주가 패널, 기준 = 실전 v1.9(RS<70 매도 유지). 세 시험은 각각 따로 판정.
  A. 재진입(차니 "손절가에서 회복하면 무조건 다시 산다, 1~2% 비싸게 사는 건 괜찮다")
     손절·래칫 스탑으로 판 종목이 이후 주 고가로 '판 가격(스탑선) × (1+k%)' 를 회복하면 그 가격(갭이면 시가)에 판 때 비중만큼
     다시 산다 — 종목 수 상한·냉각·지수 게이트 무시(무조건), 현금 한도만. 판 뒤 W주 안에서만. 본판 k=1, W=26.
     이웃: k ∈ {0, 2} · W ∈ {13, 52}
  B. 월간 매수(차니 "주간 신호도 소음이면 월간으로") — 신규 편입을 4주마다(rebalance=4). 손절·래칫 스탑·불타기는 그대로 매주.
     본판 = RS<70 탈락 매도도 매주 판정. 이웃: rebalance 2·3주, 그리고 '탈락 매도도 4주마다'.
  C. 52주 신고가만(차니 "52주 신고가인 놈만 조지는 건?") — v1.9 조건에 '이번 주 종가 = 52주 최고 종가'를 더한다(신규 편입에만).
     이웃: 26주·39주 신고가, 52주 고점 대비 −5% 이내.
구간: 학습 2018-06-01~2022-06-30 / 검증 2022-07-01~ (빈 계좌에서 따로) / 전체 2018-06-01~.
합격(넷 다, 시험마다):
  ① 본판이 v1.9 보다 수익÷낙폭(Calmar) 학습·검증 **둘 다** 높다
  ② 전체 구간 MDD 가 v1.9 보다 2%p 넘게 나쁘지 않고, CAGR 이 1%p 넘게 낮지 않다
  ③ 이웃들의 전체 Calmar 중앙 ≥ v1.9 전체 Calmar
  ④ (A만) 메커니즘: 한국 5년 대박주(winners_reverse) 중 '매도 수익을 이어 곱해 손해로 끝난' 종목 수가 v1.9 보다 적다
     (B·C 는 ④ 대신: 매매 횟수가 v1.9 의 3배를 넘지 않는다 — 실전 비용·실행 가능성)
정직 기록: 엔진 동작 확인용으로 본판 셋의 '전체 구간' 숫자 1회씩은 등록 전에 봤다(A 19.07%/−39.47%, B 19.24%/−25.55%,
  C 27.93%/−28.6%; v1.9 20.85%/−25.38%). 학습·검증 분리값과 이웃은 보지 않았고, 기준은 그 숫자를 보고 바꾸지 않았다.
결과: results/reentry_monthly_nh_2026_11_10.json
"""
import os, sys, json, time, copy
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import numpy as np
import pandas as pd
import ui_quant as U

WIN = dict(train=('2018-06-01', '2022-06-30'), test=('2022-07-01', None), full=('2018-06-01', None))
BASE = U.Q.merged(U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], 'KR'))


def mk(mod):
    s = copy.deepcopy(BASE)
    mod(s)
    return s


def run(s, w):
    s = copy.deepcopy(s)
    s['start'] = w[0]
    if w[1]:
        s['end'] = w[1]
    else:
        s.pop('end', None)
    o = U._run('KR', json.dumps(s, sort_keys=True))
    S = o['stats']
    c, m = float(S['CAGR']), float(S['MDD'])
    return dict(cagr=round(c, 2), mdd=round(m, 2), calmar=round(c / abs(m), 3) if m else 0.0, n=int(len(o['trades']))), o['trades']


def winners_loss(T):
    R = json.load(open('results/winners_reverse.json', encoding='utf-8'))['markets']['KR']
    ws = {str(w['sym']) for w in R['winners']}
    T = T.copy(); T['코드'] = T['코드'].astype(str); T['날짜'] = pd.to_datetime(T['날짜'])
    t = T[(T['날짜'] >= pd.Timestamp(R['window'][0])) & T['코드'].isin(ws)]
    out = dict(bought=0, net_loss=0)
    for c, x in t.groupby('코드'):
        out['bought'] += 1
        sells = x[x['구분'] == '매도']
        if len(sells) and ((sells['수익률'].fillna(0) / 100 + 1).prod() - 1) < 0:
            out['net_loss'] += 1
    return out


def re_(k, w):
    return lambda s: s['exit'].__setitem__('reentry', dict(k=k, weeks=w))


def rb(n, sig=False):
    def f(s):
        s['rebalance'] = n
        if sig:
            s['exit']['sig_every'] = 'rebalance'
    return f


def flt(field, op, val):
    return lambda s: s['filters'].append(dict(field=field, op=op, value=val))


TESTS = {
    'A_재진입': dict(main=re_(1, 26), nb={'k0': re_(0, 26), 'k2': re_(2, 26), 'w13': re_(1, 13), 'w52': re_(1, 52)}),
    'B_월간': dict(main=rb(4), nb={'rb2': rb(2), 'rb3': rb(3), 'rb4_신호도4주': rb(4, True)}),
    'C_52주신고가': dict(main=flt('nh:52', '==', 1), nb={'nh26': flt('nh:26', '==', 1), 'nh39': flt('nh:39', '==', 1),
                                                       'hi5': flt('dist_hi:52', '>=', -5)}),
}


def main():
    t0 = time.time()
    v19 = {}
    for k, w in WIN.items():
        v19[k], T = run(BASE, w)
        if k == 'full':
            v19['winners'] = winners_loss(T)
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), v19=v19, tests={})
    for name, d in TESTS.items():
        s = mk(d['main'])
        r = {}
        for k, w in WIN.items():
            r[k], T = run(s, w)
            if k == 'full':
                r['winners'] = winners_loss(T)
        nb = {}
        for nn, f in d['nb'].items():
            nb[nn], _ = run(mk(f), WIN['full'])
        nbm = float(np.median([x['calmar'] for x in nb.values()]))
        c1 = r['train']['calmar'] > v19['train']['calmar'] and r['test']['calmar'] > v19['test']['calmar']
        c2 = r['full']['mdd'] >= v19['full']['mdd'] - 2 and r['full']['cagr'] >= v19['full']['cagr'] - 1
        c3 = nbm >= v19['full']['calmar']
        c4 = (r['winners']['net_loss'] < v19['winners']['net_loss']) if name.startswith('A') else (r['full']['n'] <= 3 * v19['full']['n'])
        out['tests'][name] = dict(main=r, neighbors=nb, neighbors_calmar_median=nbm,
                                  checks=dict(c1=bool(c1), c2=bool(c2), c3=bool(c3), c4=bool(c4), passed=bool(c1 and c2 and c3 and c4)))
        print(name, round(time.time() - t0), json.dumps(out['tests'][name]['checks']), flush=True)
    json.dump(out, open('results/reentry_monthly_nh_2026_11_10.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    print(json.dumps(out, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
