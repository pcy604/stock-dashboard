# -*- coding: utf-8 -*-
"""🎮 일봉 매매 엔진 — '종목 게임'과 '지수 게임'을 따로 둔다 (2026-10-31, 차니 설계)

게임 A (종목): 주도주 필터로 고른 종목을 언제 들고 언제 내리나 — 손절·익절 사다리·재매수. **스탑 주문으로 체결**:
  · 손절: 그날 저가가 손절선 이하 → 손절선에 매도(시가가 이미 아래면 시가 = 갭).
  · 재매수(판 가격 재돌파): 다음 날부터 고가가 판 가격 이상 → 판 가격에 매수(시가가 이미 위면 시가).
  · 고점은 보유 중 최고 **종가**(CLAUDE.md 규칙). 손절선은 내려가지 않는다.
게임 B (지수): 종목이 A 에서 '보유' 상태일 때 실제로 얼마나 담을지(0~100%)를 지수 기준으로 정한다.
  · 지수 이평: 지수 종가가 n일 이평 아래면 0%(다음 날 시가에 매도, 위로 오면 시가에 재매수)
  · 상대 약세: 종목 L일 수익률 − 지수 L일 수익률이 x일 연속 음수면 약세 비중, y일 연속 양수면 강세 비중
  · 실제 비중 = A 보유 여부 × 이평 비중 × 상대 비중 (최대 100%, 레버리지 없음)
비용 편도 cost%. 현금 이자 없음.
"""
import numpy as np

DEF_A = dict(entry='start', init_stop=10.0, ladder=[[0.0, 10.0]], atr_k=0.0, min_hold=0,
             reentry='sell_px', confirm_ma=0, cost=0.3)
DEF_B = dict(index='auto', ma_n=0, rel_L=0, rel_x=10, rel_y=5, w_base=1.0, w_weak=0.5, w_strong=1.0)

PRESETS_A = {
    '그냥 보유':                     dict(init_stop=0, ladder=[], reentry='none'),
    '차니안 −10% · 판 가격 재매수':   dict(init_stop=10, ladder=[[0, 10]], reentry='sell_px'),
    '차니안 −20% · 판 가격 재매수':   dict(init_stop=10, ladder=[[0, 20]], reentry='sell_px'),
    '차니안 −30% · 판 가격 재매수':   dict(init_stop=10, ladder=[[0, 30]], reentry='sell_px'),
    'ATR×3 · 판 가격 재매수':         dict(init_stop=0, ladder=[], atr_k=3.0, reentry='sell_px'),
    '고점 −20% · 확인 재매수(50일선)': dict(init_stop=20, ladder=[[0, 20]], reentry='sell_px', confirm_ma=50),
}
PRESETS_B = {
    '지수 대비 없음':           dict(),
    '지수 5일선 위에서만':      dict(ma_n=5),
    '지수 20일선 위에서만':     dict(ma_n=20),
    '지수 200일선 위에서만':    dict(ma_n=200),
    '상대 약세 10일 → 50%':     dict(rel_L=20, rel_x=10, rel_y=5, w_weak=0.5),
}
INDEX_OF = {'US': 'SPX', 'KR': 'KOSPI'}
INDEX_CHOICES = {'US': ['SPX', 'NDX', 'RUT'], 'KR': ['KOSPI', 'KOSDAQ']}


def _overlay(c, ix, b):
    """지수 게임 비중 m[t] — t일 종가로 정하고 t+1일 시가부터 적용."""
    n = len(c)
    m = np.ones(n)
    if b['ma_n'] and ix is not None:
        k = int(b['ma_n'])
        ma = np.convolve(np.nan_to_num(ix, nan=0.0), np.ones(k) / k, 'full')[:n]
        ma[:k - 1] = np.nan
        m = np.where(np.isfinite(ma) & (ix < ma), 0.0, 1.0)
    if b['rel_L'] and ix is not None:
        L = int(b['rel_L'])
        rs = np.full(n, np.nan)
        rs[L:] = (c[L:] / c[:-L] - 1) - (ix[L:] / ix[:-L] - 1)
        w = np.full(n, float(b['w_base'])); neg = pos = 0; cur = float(b['w_base'])
        for t in range(n):
            if np.isfinite(rs[t]):
                neg = neg + 1 if rs[t] < 0 else 0
                pos = pos + 1 if rs[t] > 0 else 0
                if neg >= b['rel_x']:
                    cur = float(b['w_weak'])
                elif pos >= b['rel_y']:
                    cur = float(b['w_strong'])
            w[t] = cur
        m = m * w
    return np.clip(m, 0, 1)


def simulate(o, h, l, c, ix, start, a=None, b=None):
    """o,h,l,c: 일봉 배열 · ix: 같은 날짜에 맞춘 지수 종가(없으면 None) · start: 창 첫날 인덱스.
    반환 dict(eq, trades, exposure)"""
    A = dict(DEF_A); A.update(a or {})
    B = dict(DEF_B); B.update(b or {})
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    n = len(c)
    cost = A['cost'] / 100
    m = _overlay(c, ix, B)
    lad = sorted([tuple(map(float, x)) for x in (A['ladder'] or [])])
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    atr = np.r_[np.nan, np.convolve(tr, np.ones(20) / 20, 'full')[:n - 1]]
    atr[:21] = np.nan
    ma_c = None
    if A['confirm_ma']:
        k = int(A['confirm_ma'])
        ma_c = np.convolve(c, np.ones(k) / k, 'full')[:n]; ma_c[:k - 1] = np.nan
    hi252 = np.full(n, np.nan)
    if A['entry'] == 'nh52':
        for t in range(252, n):
            hi252[t] = np.max(c[t - 252:t])

    eq, f = 1.0, 0.0
    inA = False; pos = None; level = None; exit_t = -1; pend_buy = False
    trades, curve, held = [], [], 0
    first = True
    for t in range(start, n):
        if not (np.isfinite(o[t]) and np.isfinite(c[t])):
            curve.append(eq); continue
        pc = c[t - 1] if t > 0 and np.isfinite(c[t - 1]) else o[t]
        mt = m[t - 1] if t > 0 else 1.0
        # ① 시가: 어제 결정된 진입·지수 비중 반영
        eq *= 1 + f * (o[t] / pc - 1)
        if first and A['entry'] == 'start':
            first = False; pend_buy = True
        if pend_buy and not inA:
            inA = True; pend_buy = False
            pos = dict(entry=o[t], peak=o[t], t0=t,
                       stop=o[t] * (1 - A['init_stop'] / 100) if A['init_stop'] else 0.0)
            if A['atr_k'] and np.isfinite(atr[t]):
                pos['stop'] = max(pos['stop'], o[t] - A['atr_k'] * atr[t])
        nf = mt if inA else 0.0
        if nf != f:
            eq *= 1 - abs(nf - f) * cost; f = nf
        px = o[t]
        # ② 장중: 손절 스탑 / 재매수 스탑
        if inA and pos['stop'] and l[t] <= pos['stop']:
            p = min(o[t], pos['stop'])
            eq *= 1 + f * (p / px - 1); eq *= 1 - f * cost
            trades.append(dict(i0=pos['t0'], i1=t, buy=pos['entry'], sell=p, ret=p / pos['entry'] - 1))
            level = pos['stop']; exit_t = t; inA = False; pos = None; f = 0.0; px = p
        elif (not inA and level is not None and A['reentry'] == 'sell_px' and not A['confirm_ma']
              and t > exit_t and h[t] >= level):
            p = max(o[t], level)
            inA = True; pos = dict(entry=p, peak=p, t0=t, stop=p * (1 - A['init_stop'] / 100) if A['init_stop'] else 0.0)
            if A['atr_k'] and np.isfinite(atr[t]):
                pos['stop'] = max(pos['stop'], p - A['atr_k'] * atr[t])
            f = mt; eq *= 1 - f * cost; px = p
        # ③ 종가까지
        eq *= 1 + f * (c[t] / px - 1)
        # ④ 종가 판정: 고점·손절선 갱신, 다음 날 진입 예약
        if inA:
            pos['peak'] = max(pos['peak'], c[t])
            g = pos['peak'] / pos['entry'] - 1
            if t - pos['t0'] >= A['min_hold']:
                for th, trl in lad:
                    if g * 100 >= th:
                        pos['stop'] = max(pos['stop'], pos['peak'] * (1 - trl / 100))
                if A['atr_k'] and np.isfinite(atr[t]):
                    pos['stop'] = max(pos['stop'], pos['peak'] - A['atr_k'] * atr[t])
            held += 1
        else:
            if first and A['entry'] == 'nh52' and np.isfinite(hi252[t]) and c[t] > hi252[t]:
                first = False; pend_buy = True
            elif level is not None and A['reentry'] == 'sell_px' and A['confirm_ma'] and t > exit_t:
                if c[t] > level and np.isfinite(ma_c[t]) and c[t] > ma_c[t]:
                    pend_buy = True
        curve.append(eq)
    if inA:
        trades.append(dict(i0=pos['t0'], i1=None, buy=pos['entry'], sell=c[n - 1], ret=c[n - 1] / pos['entry'] - 1))
    return dict(eq=np.array(curve), trades=trades, exposure=held / max(1, n - start))


def summarize(o, h, l, c, ix, start, a=None, b=None):
    r = simulate(o, h, l, c, ix, start, a, b)
    eq = r['eq']
    bh = c[-1] / o[start]
    w = np.asarray(c[start:], float) / o[start]
    return dict(mult=float(eq[-1]), bh=float(bh), mdd=float((eq / np.maximum.accumulate(eq) - 1).min()),
                bh_mdd=float((w / np.maximum.accumulate(w) - 1).min()), n_trades=len(r['trades']),
                exposure=round(r['exposure'], 3), capture=np.nan)
