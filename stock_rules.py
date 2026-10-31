# -*- coding: utf-8 -*-
"""종목별 매매 규칙 엔진 — 오를수록 손절선(익절선)을 끌어올리는 '래칫' (2026-10-31, 차니 설계)

포트폴리오가 아니라 **한 종목**을 대상으로 한다. 연구(research/stock_ratchet.py)와 화면(🪜 익절 래칫)이 같은 함수를 쓴다.

판정·체결 (원칙 v1 과 같음)
- 판정은 **주봉 종가**만. 신호가 난 주의 **다음 주 종가**에 체결(delay=1). 0 으로 바꾸면 같은 주 종가.
- 손절·익절선은 전부 **보유 중 최고 종가(고점) 대비**다. 진입가 대비는 '초기 손절'과 '본전 보장'뿐.
- 비용: 매수·매도 각 cost% (기본 0.3%). 현금 이자 없음(종목 단위 비교라 단순하게).

규칙 (params dict)
  entry      : 'start'(창 첫 주) | 'nh52'(종가가 직전 52주 최고 종가 돌파) | 'ma30'(30주선 위 + 30주선 상승)
  init_stop  : 진입가 대비 초기 손절 % (0 = 없음)
  ladder     : [[수익%, 고점 대비 %], ...] — 진입 후 최고 수익이 '수익%' 이상이면 손절선 = 고점 × (1 − %).
               여러 단을 넘으면 가장 높은 단을 쓴다. 손절선은 내려가지 않는다(래칫).
  lock_be    : 최고 수익이 이 % 를 넘으면 손절선 ≥ 진입가(본전 보장). 0 = 끔
  min_hold   : 진입 후 이 주수 동안은 사다리(고점 대비) 손절을 쓰지 않는다(초기 손절은 살아 있음) — '최소보유 바닥'
  scale_out  : [수익%, 매도 비율] — 처음 그 수익에 닿으면 보유분의 비율만큼 한 번 익절. 비율 0 = 끔
  reentry    : 'none' | 'nh52' | 'prev_peak'(청산 때 고점 재돌파) | 'sell_px'(판 가격 재돌파 — 차니 10-31)  — 청산 후 다시 살지
  cooldown   : 청산 후 재진입 금지 주수
  delay      : 0 | 1
  cost       : 편도 비용 %
"""
import numpy as np

DEFAULT = dict(entry='start', init_stop=20.0, ladder=[[30.0, 25.0], [100.0, 20.0], [200.0, 15.0]], lock_be=0.0,
               min_hold=0, scale_out=[0.0, 0.0], reentry='none', cooldown=0, delay=1, cost=0.3)

# 연구·화면 공통 프리셋(이름 = 화면 표기). 바꾸면 research/stock_ratchet.py 결과도 다시 만들어야 한다.
PRESETS = {
    '매수보유':                 dict(init_stop=0, ladder=[]),
    '고점 -20% (현행)':         dict(init_stop=20, ladder=[[0, 20]]),
    '고점 -30%':                dict(init_stop=30, ladder=[[0, 30]]),
    '고점 -40%':                dict(init_stop=40, ladder=[[0, 40]]),
    '래칫 조이기 (-20→-25→-20→-15)': dict(init_stop=20, ladder=[[30, 25], [100, 20], [200, 15]]),
    '래칫 풀기 (-15→-25→-35)':  dict(init_stop=15, ladder=[[50, 25], [100, 35]]),
    '본전보장 +30% · 고점 -30%': dict(init_stop=20, ladder=[[0, 30]], lock_be=30),
    '최소보유 26주 · 고점 -35%': dict(init_stop=35, ladder=[[0, 35]], min_hold=26),
    '최소보유 52주 · 고점 -30%': dict(init_stop=40, ladder=[[0, 30]], min_hold=52),
    '고점 -30% · 신고가 재진입': dict(init_stop=30, ladder=[[0, 30]], reentry='nh52', cooldown=4),
    '+100% 절반 익절 · 고점 -35%': dict(init_stop=30, ladder=[[0, 35]], scale_out=[100, 0.5]),
    '고점 -20% · 신고가 재진입': dict(init_stop=20, ladder=[[0, 20]], reentry='nh52', cooldown=4),
    '래칫 조이기 · 신고가 재진입': dict(init_stop=20, ladder=[[30, 25], [100, 20], [200, 15]], reentry='nh52', cooldown=4),
    '최소보유 26주 · 고점 -35% · 재진입': dict(init_stop=35, ladder=[[0, 35]], min_hold=26, reentry='nh52', cooldown=4),
    # 차니안 (10-31): 진입가 −10% 손절 → 오르면 고점 대비 손절, 판 가격을 다시 넘으면 바로 재매수
    '차니안 고정 −10%·판값 재매수':  dict(init_stop=10, ladder=[[0, 10]], reentry='sell_px', cooldown=0),
    '차니안 고정 −20%·판값 재매수':  dict(init_stop=10, ladder=[[0, 20]], reentry='sell_px', cooldown=0),
    '차니안 고정 −30%·판값 재매수':  dict(init_stop=10, ladder=[[0, 30]], reentry='sell_px', cooldown=0),
    '차니안 넓히기 −10→−20→−30·판값 재매수': dict(init_stop=10, ladder=[[0, 10], [50, 20], [100, 30]], reentry='sell_px', cooldown=0),
}
ENTRIES = {'start': '창 첫 주 매수', 'nh52': '52주 신고가 돌파 시 매수', 'ma30': '30주선 위·상승 시 매수'}


def full(p):
    q = dict(DEFAULT)
    q.update(p or {})
    return q


def _entry_ok(kind, c, i, hi52, ma30, ma30_prev):
    if kind == 'start':
        return True
    if kind == 'nh52':
        return not np.isnan(hi52[i]) and c[i] > hi52[i]
    if kind == 'ma30':
        return not np.isnan(ma30[i]) and c[i] > ma30[i] and ma30[i] > ma30_prev[i]
    return False


def simulate(close, start, p):
    """close: 주봉 종가 1차원 배열(NaN = 상장 전/폐지 후). start: 창 첫 주 인덱스(앞쪽은 52주 고가 계산용).
    반환: dict(eq=창 구간 자산곡선(1.0 시작), trades=[...], exposure=보유 주 비율)"""
    p = full(p)
    c = np.asarray(close, float)
    n = len(c)
    # 직전 52주 최고 종가(이번 주 제외)
    hi52 = np.full(n, np.nan)
    for i in range(52, n):
        w = c[i - 52:i]
        if np.isfinite(w).sum() >= 40:
            hi52[i] = np.nanmax(w)
    ma30 = np.full(n, np.nan)
    for i in range(29, n):
        w = c[i - 29:i + 1]
        if np.isfinite(w).all():
            ma30[i] = w.mean()
    ma30_prev = np.r_[np.full(4, np.nan), ma30[:-4]]
    ladder = sorted([tuple(map(float, x)) for x in (p['ladder'] or [])])
    cost = p['cost'] / 100.0
    d = int(p['delay'])
    so_g, so_f = float(p['scale_out'][0]), float(p['scale_out'][1])

    cash, sh = 1.0, 0.0
    eq = []
    trades = []
    held = 0
    pos = None                    # dict(entry, peak, stop, wk, so_done, i0)
    pend = None                   # ('buy'|'sell'|'part', 신호 주)
    last_exit = None              # (주 인덱스, 청산 때 고점)
    first = True
    for i in range(start, n):
        px = c[i]
        if not np.isfinite(px):   # 상장폐지·결측 → 보유분은 마지막 가격에 묶인다(실제로는 손실일 수 있음)
            eq.append(eq[-1] if eq else 1.0)
            continue
        # ① 대기 주문 체결
        if pend and i - pend[1] >= d:
            kind = pend[0]
            if kind == 'buy' and pos is None:
                sh = cash * (1 - cost) / px; cash = 0.0
                pos = dict(entry=px, peak=px, stop=px * (1 - p['init_stop'] / 100) if p['init_stop'] else 0.0,
                           wk=0, so_done=so_f <= 0, i0=i)
            elif kind in ('sell', 'part') and pos is not None:
                frac = so_f if kind == 'part' else 1.0
                cash += sh * frac * px * (1 - cost); sh *= (1 - frac)
                if kind == 'sell':
                    trades.append(dict(i0=pos['i0'], i1=i, buy=pos['entry'], sell=px, ret=px / pos['entry'] - 1,
                                       why=pend[2], peak=pos['peak']))
                    last_exit = (i, pos['peak'], px); pos = None; sh = 0.0
            pend = None
        # ② 보유 중: 고점·손절선 갱신 → 손절 판정
        if pos is not None:
            pos['wk'] += 1
            pos['peak'] = max(pos['peak'], px)
            g = pos['peak'] / pos['entry'] - 1
            stop = pos['stop']
            if pos['wk'] > p['min_hold']:
                for th, tr in ladder:
                    if g * 100 >= th:
                        stop = max(stop, pos['peak'] * (1 - tr / 100))
            if p['lock_be'] and g * 100 >= p['lock_be']:
                stop = max(stop, pos['entry'])
            pos['stop'] = stop
            if not pos['so_done'] and px / pos['entry'] - 1 >= so_g / 100:
                pos['so_done'] = True
                if pend is None:
                    pend = ('part', i, '부분 익절')
            if stop and px <= stop and (pend is None or pend[0] == 'part'):
                why = '초기 손절' if g * 100 < (ladder[0][0] if ladder else 1e9) and pos['wk'] <= max(1, p['min_hold']) else '고점 대비 손절'
                if p['lock_be'] and abs(stop - pos['entry']) < 1e-9:
                    why = '본전 보장'
                pend = ('sell', i, why)
        # ③ 미보유: 진입 판정
        elif pend is None:
            ok = False
            if first:
                ok = _entry_ok(p['entry'], c, i, hi52, ma30, ma30_prev)
            elif p['reentry'] != 'none' and last_exit and i - last_exit[0] >= p['cooldown']:
                if p['reentry'] == 'nh52':
                    ok = _entry_ok('nh52', c, i, hi52, ma30, ma30_prev)
                elif p['reentry'] == 'prev_peak':
                    ok = px > last_exit[1]
                elif p['reentry'] == 'sell_px':
                    ok = px > last_exit[2]
            if ok:
                first = False
                pend = ('buy', i, '진입')
                if d == 0:        # 같은 주 체결
                    sh = cash * (1 - cost) / px; cash = 0.0
                    pos = dict(entry=px, peak=px, stop=px * (1 - p['init_stop'] / 100) if p['init_stop'] else 0.0,
                               wk=0, so_done=so_f <= 0, i0=i)
                    pend = None
        if pos is not None:
            held += 1
        eq.append(cash + sh * px)
    if pos is not None:
        lp = c[np.isfinite(c)][-1]
        trades.append(dict(i0=pos['i0'], i1=None, buy=pos['entry'], sell=lp, ret=lp / pos['entry'] - 1, why='보유 중', peak=pos['peak']))
    eq = np.array(eq)
    return dict(eq=eq, trades=trades, exposure=held / max(1, n - start))


def summarize(close, start, p):
    """한 종목 요약: 전략 배수 · 매수보유 배수 · 포착률 · 거래 수 · 보유 비율 · 자산곡선 최대 낙폭"""
    r = simulate(close, start, p)
    c = np.asarray(close, float)
    w = c[start:]
    fin = w[np.isfinite(w)]
    bh = fin[-1] / fin[0] if len(fin) else np.nan
    eq = r['eq']
    mult = eq[-1] if len(eq) else np.nan
    dd = float((eq / np.maximum.accumulate(eq) - 1).min()) if len(eq) else np.nan
    bh_eq = w / fin[0] if len(fin) else w
    bh_dd = float(np.nanmin(bh_eq / np.fmax.accumulate(np.nan_to_num(bh_eq, nan=0.0)) - 1)) if len(fin) else np.nan
    return dict(mult=float(mult), bh=float(bh), capture=float(np.log(mult) / np.log(bh)) if bh and bh > 1 and mult > 0 else np.nan,
                n_trades=len(r['trades']), exposure=round(r['exposure'], 3), mdd=dd, bh_mdd=bh_dd)


def aggregate(rows):
    """여러 종목 요약 → 한 줄. 배수는 기하평균(동일 비중 포트폴리오를 매년 다시 맞춘 것에 가깝다)도 같이 낸다."""
    import pandas as pd
    D = pd.DataFrame(rows)
    if D.empty:
        return {}
    lm = np.log(D['mult'].clip(lower=1e-6))
    return dict(n=len(D), mult_med=float(D['mult'].median()), mult_mean=float(D['mult'].mean()),
                mult_geo=float(np.exp(lm.mean())), bh_med=float(D['bh'].median()), bh_mean=float(D['bh'].mean()),
                beat_bh=float((D['mult'] > D['bh']).mean()), capture_med=float(D['capture'].median()),
                trades_med=float(D['n_trades'].median()), exposure_med=float(D['exposure'].median()),
                mdd_med=float(D['mdd'].median()), bh_mdd_med=float(D['bh_mdd'].median()),
                lose=float((D['mult'] < 1).mean()))
