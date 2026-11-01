# -*- coding: utf-8 -*-
"""🧮 포트폴리오 퀀트 백테스트 엔진 — 규칙은 전부 '명세(spec) dict' 로 받는다 (2026-11-01, 차니 요구 1~8)

하드코딩 금지: 필드·필터·순위·청산 신호는 이름+숫자로 조합한다. 새 지표는 FIELDS 에 한 줄 추가하면 화면에 바로 뜬다.

명세 예 (기본값은 DEFAULT_SPEC):
  market 'US'|'KR' · start/end 'YYYY-MM-DD' · rebalance 4(주) · max_pos 20
  filters  [{'field':'marcap','op':'>=','value':1e9}, {'field':'ma_gap:40','op':'>','value':0}, {'field':'per','op':'between','value':[0,25]}]
  rank     {'field':'rs','desc':True}
  weight   'equal'|'rank'|'mcap'|'inv_vol' · max_w 0.15 (종목 상한 X — 넘으면 리밸런싱 때 덜어냄 = 익절)
  exposure {'base':1.0, 'index':'SPX', 'ma':40, 'below':0.3, 'months':[1..12]}   (요구 1 — 주식 비중; 이평 아래·달력 밖이면 줄임)
  entry    {'init':0.5, 'pyramid':[[20,0.25],[40,0.25]]}   (요구 3 — 첫 매수는 목표 비중의 init, +n% 마다 목표의 x 만큼 추가, 목표 = 상한)
  exit     {'stop':15, 'trail':[[0,25],[50,20],[100,15]], 'min_hold':0, 'cooldown':4,
            'signals':[{'type':'ma_break','n':5}, {'type':'rsi_down','n':14,'level':70}, ...]}   (요구 4·5)
  cost 0.003
체결: 주봉(날짜 = 그 주 월요일). 판정은 그 주 종가 → 다음 주 시가 체결. 손절·래칫만 주중 스탑(저가가 선 아래면 그 선에, 갭이면 시가).
고점 = 보유 중 최고 **종가**. 상장폐지·패널 이탈(가격 끊김)은 마지막 종가에 정리.
"""
import json
import math
import numpy as np
import pandas as pd

# ── 필드 사전 (화면 선택지 = 이 목록) ─────────────────────────────────
#   key → (화면 이름, 단위, 설명). 'name:n' 형식은 숫자 파라미터를 받는다.
FIELDS = {
    'marcap':    ('시가총액', '억원/$B', '그 주 시총'),
    'per':       ('PER', '배', '시총 ÷ TTM 순이익 (적자면 빈값)'),
    'pbr':       ('PBR', '배', '시총 ÷ 자본총계'),
    'psr':       ('PSR', '배', '시총 ÷ TTM 매출'),
    'rev_yoy':   ('매출 YoY', '%', '최근 분기 매출의 전년 같은 분기 대비'),
    'op_yoy':    ('영업이익 YoY', '%', '전년 같은 분기 영업이익이 흑자일 때만'),
    'op_turn':   ('영업 흑자전환', '0/1', '이번 분기 흑자 & 전년 같은 분기 적자'),
    'acc':       ('이익 가속', '0/1', '매출·영업이익 성장률 동시 가속 (미국만)'),
    'rs':        ('RS 상대강도', '0~99', '0.4×13주+0.2×26·39·52주 수익률의 시장 내 백분위'),
    'ret:n':     ('n주 수익률', '%', '종가 기준'),
    'ma_gap:n':  ('n주선 대비 괴리', '%', '종가 ÷ n주 이평 − 1 (양수 = 이평 위)'),
    'dist_hi:n': ('n주 고점 대비', '%', '종가 ÷ n주 최고가 − 1 (0 = 신고가, 항상 0 이하)'),
    'nh:n':      ('n주 신고가', '0/1', '종가가 n주 최고 종가'),
    'vol_x:n':   ('거래량 배수', '배', '이번 주 거래량 ÷ 직전 n주 평균'),
    'rsi:n':     ('RSI', '0~100', 'n주 RSI'),
    'macd_hist': ('MACD 오실레이터', '', '12/26/9 주봉'),
}
EXIT_SIGNALS = {
    'ma_break':  ('n주선 이탈', 'n', '종가가 n주 이평 아래로 내려온 주'),
    'rsi_down':  ('RSI 매도', 'n,level', 'RSI(n)가 level 위에서 아래로 꺾인 주'),
    'macd_neg':  ('MACD 오실레이터 약세 전환', '', '히스토그램이 + 에서 − 로'),
    'doji_vol':  ('거래량 터진 도지', 'vol_x', '몸통 ≤ 고저폭 10% 이고 거래량 ≥ 직전 20주 평균 × vol_x'),
    'bear':      ('큰 음봉', 'pct', '주봉 (종가 ÷ 시가 − 1) ≤ −pct%'),
    'field':     ('펀더멘털·지표 조건', 'field,op,value', '예: 영업이익 YoY < 0, PER > 60'),
    'rank_out':  ('순위 이탈', 'm', '순위 필드로 상위 m 밖으로 밀림(리밸런싱 주에만)'),
}
OPS = ['>=', '<=', '>', '<', '==', 'between']

DEFAULT_SPEC = dict(
    market='US', start='2015-01-01', end=None, rebalance=4, max_pos=20,
    filters=[dict(field='marcap', op='>=', value=1e9)],
    rank=dict(field='rs', desc=True),
    weight='equal', max_w=0.10,
    exposure=dict(base=1.0, index='', ma=40, below=0.0, months=list(range(1, 13))),
    entry=dict(init=1.0, pyramid=[]),
    exit=dict(stop=0, trail=[], min_hold=0, cooldown=0, signals=[dict(type='rank_out', m=40)]),
    cost=0.003,
)


def merged(spec):
    out = json.loads(json.dumps(DEFAULT_SPEC))
    for k, v in (spec or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out


# ── 지표 계산 (행 = 주, 열 = 종목) ──────────────────────────────────────
BASE_COLS = ('open', 'high', 'low', 'close', 'volume', 'marcap', 'per', 'pbr', 'psr', 'rev_yoy', 'op_yoy', 'op_turn', 'acc')
_MAX_DERIVED = 24        # 파생 행렬 캐시 상한(종목×주 float32 ≈ 6~8MB 씩) — 무한 증가가 배포 앱 메모리 초과 원인(2026-11-01)


class Panel:
    """긴 표(종목·주 행)를 받자마자 넓은 float32 행렬로 바꾸고 긴 표는 버린다.
    2026-11-01 메모리 초과 수정: 긴 표(문자열 열 포함 시장당 300~400MB)를 계속 들고 있던 것 + 파생 행렬 무한 캐시가 원인."""

    def __init__(self, df):
        df = df[[c for c in ('sym', 'name', 'date') + BASE_COLS if c in df.columns]]
        self.names = df.drop_duplicates('sym', keep='last').set_index('sym')['name'].to_dict() if 'name' in df.columns else {}
        cols = [c for c in BASE_COLS if c in df.columns]
        w = (df.drop_duplicates(['date', 'sym'], keep='last').set_index(['date', 'sym'])[cols]
             .astype('float32').unstack('sym').sort_index())
        self.dates = pd.DatetimeIndex(w.index)
        self.syms = pd.Index(sorted(df['sym'].unique()))
        self._base = {c: w[c].reindex(columns=self.syms) for c in cols}
        del w
        self._m = {}

    def base(self, col):
        return self._base[col]

    def get(self, key):
        if key in self._m:
            self._m[key] = self._m.pop(key)                 # 최근 사용을 뒤로(LRU)
            return self._m[key]
        name, _, p = key.partition(':')
        n = int(float(p)) if p else None
        c = self.base('close')
        if name in ('open', 'high', 'low', 'close', 'volume', 'marcap', 'per', 'pbr', 'psr', 'rev_yoy', 'op_yoy', 'op_turn', 'acc'):
            return self.base(name)
        if name == 'ret':
            v = (c / c.shift(n) - 1) * 100
        elif name == 'ma':
            v = c.rolling(n, min_periods=n).mean()
        elif name == 'ma_gap':
            v = (c / self.get(f'ma:{n}') - 1) * 100
        elif name == 'dist_hi':
            v = ((c / self.base('high').rolling(n, min_periods=max(4, n // 2)).max() - 1) * 100).clip(upper=0)
        elif name == 'nh':
            v = (c >= c.rolling(n, min_periods=max(4, n // 2)).max()).astype(float).where(c.notna())
        elif name == 'vol_x':
            vv = self.base('volume')
            v = vv / vv.shift(1).rolling(n, min_periods=max(2, n // 2)).mean()
        elif name == 'rsi':
            d = c.diff()
            up, dn = d.clip(lower=0), (-d).clip(lower=0)
            ru, rd = up.ewm(alpha=1 / n, adjust=False).mean(), dn.ewm(alpha=1 / n, adjust=False).mean()
            v = 100 - 100 / (1 + ru / rd.replace(0, np.nan))
        elif name == 'macd_hist':
            m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
            v = m - m.ewm(span=9, adjust=False).mean()
        elif name == 'rs':
            r = {k: c / c.shift(k) - 1 for k in (13, 26, 39, 52)}
            sc = 0.4 * r[13] + 0.2 * r[26] + 0.2 * r[39] + 0.2 * r[52]
            v = sc.rank(axis=1, pct=True) * 99
        else:
            raise KeyError(f'모르는 필드: {key}')
        v = v.astype('float32')
        self._m[key] = v
        while len(self._m) > _MAX_DERIVED:
            self._m.pop(next(iter(self._m)))
        return v


def _cond(M, op, val):
    if op == 'between':
        lo, hi = val
        return (M >= lo) & (M <= hi)
    return {'>=': M >= val, '<=': M <= val, '>': M > val, '<': M < val, '==': M == val}[op]


def _exit_matrix(P, sig):
    t = sig.get('type')
    c, o, h, l = P.base('close'), P.base('open'), P.base('high'), P.base('low')
    if t == 'ma_break':
        m = P.get(f"ma:{int(sig.get('n', 5))}")
        return (c < m) & (c.shift(1) >= m.shift(1))
    if t == 'rsi_down':
        r = P.get(f"rsi:{int(sig.get('n', 14))}"); lv = float(sig.get('level', 70))
        return (r < lv) & (r.shift(1) >= lv)
    if t == 'macd_neg':
        m = P.get('macd_hist')
        return (m < 0) & (m.shift(1) >= 0)
    if t == 'doji_vol':
        body, rng = (c - o).abs(), (h - l)
        return (body <= 0.1 * rng) & (rng > 0) & (P.get('vol_x:20') >= float(sig.get('vol_x', 2)))
    if t == 'bear':
        return (c / o - 1) * 100 <= -abs(float(sig.get('pct', 7)))
    if t == 'field':
        return _cond(P.get(sig['field']), sig.get('op', '<'), sig.get('value', 0))
    return None                                         # rank_out 은 리밸런싱 때 따로


def run(panel: Panel, spec, index_px: pd.Series = None, bench_px: pd.Series = None):
    """반환 dict(equity, bench, exposure, trades(DataFrame), holdings(DataFrame), stats, last_pf)"""
    S = merged(spec)
    P = panel
    dates = P.dates
    t0 = int(np.searchsorted(dates, pd.Timestamp(S['start'])))
    t1 = len(dates) if not S.get('end') else int(np.searchsorted(dates, pd.Timestamp(S['end']), side='right'))
    O, H, L, C = (P.base(k).values for k in ('open', 'high', 'low', 'close'))
    O = np.where(np.isfinite(O), O, C)
    ok = np.ones(C.shape, bool)
    for f in S['filters']:
        ok &= _cond(P.get(f['field']), f['op'], f['value']).fillna(False).values
    rk = P.get(S['rank']['field']).values
    rk = rk if S['rank'].get('desc', True) else -rk
    sigs = []
    for sg in S['exit']['signals']:
        M = _exit_matrix(P, sg)
        if M is not None:
            sigs.append((EXIT_SIGNALS[sg['type']][0] + (f" {sg.get('n', '')}".rstrip() if sg['type'] == 'ma_break' else ''), M.fillna(False).values))
    rank_out = [s for s in S['exit']['signals'] if s.get('type') == 'rank_out']
    vol = P.get('ret:1').rolling(26, min_periods=8).std().values if S['weight'] == 'inv_vol' else None
    mc = P.base('marcap').values

    # 노출(요구 1): 지수 이평 · 달력
    ex = S['exposure']
    expo = np.full(len(dates), float(ex.get('base', 1.0)))
    if ex.get('index') and index_px is not None and ex.get('ma'):
        ix = index_px.reindex(dates, method='ffill')
        below = (ix < ix.rolling(int(ex['ma']), min_periods=int(ex['ma'])).mean()).fillna(False).values
        expo = np.where(below, expo * float(ex.get('below', 0.0)), expo)
    months = set(ex.get('months') or range(1, 13))
    fri = dates + pd.Timedelta(days=4)
    expo = np.where([m in months for m in fri.month], expo, 0.0)

    cost = float(S['cost'])
    tr_l = sorted([tuple(map(float, x)) for x in (S['exit'].get('trail') or [])])
    pyr = sorted([tuple(map(float, x)) for x in (S['entry'].get('pyramid') or [])])
    init = float(S['entry'].get('init', 1.0))
    max_w, max_pos = float(S['max_w']), int(S['max_pos'])
    cash, pos, cool, tws = 1.0, {}, {}, {}
    pend = []            # (kind, j, frac_of_equity or None, reason) — 다음 주 시가
    eq_s, ex_s, trades = [], [], []

    def val(t):
        return cash + sum(p['u'] * (C[t, j] if np.isfinite(C[t, j]) else p['last']) for j, p in pos.items())

    def log(t, j, side, px, amt, why, ret=None):
        trades.append(dict(날짜=dates[t], 종목=P.names.get(P.syms[j], P.syms[j]),
                           코드=P.syms[j], 구분=side, 가격=float(px), 금액비중=round(amt * 100, 2), 사유=why,
                           수익률=None if ret is None else round(ret * 100, 1)))

    for t in range(t0, t1):
        E = val(t - 1) if t > t0 else 1.0
        # ① 시가 체결 — 지난주 결정
        for kind, j, w, why in pend:
            px = O[t, j]
            if not np.isfinite(px) or px <= 0:
                continue
            if kind == 'sell' and j in pos:
                p = pos.pop(j); amt = p['u'] * px
                cash += amt * (1 - cost); cool[j] = t + int(S['exit'].get('cooldown', 0))
                log(t, j, '매도', px, amt / max(E, 1e-12), why, px / p['avg'] - 1)
            elif kind == 'trim' and j in pos:
                p = pos[j]; cur = p['u'] * px; cut = max(0.0, cur - w * E)
                if cut > 0:
                    p['u'] -= cut / px; cash += cut * (1 - cost)
                    log(t, j, '덜기', px, cut / E, why, px / p['avg'] - 1)
            elif kind in ('buy', 'add'):
                amt = min(w * E, cash / (1 + cost))
                if amt <= E * 1e-4:
                    continue
                cash -= amt * (1 + cost)
                if j in pos:
                    p = pos[j]; p['avg'] = (p['avg'] * p['u'] + amt) / (p['u'] + amt / px); p['u'] += amt / px
                    if kind == 'add' and '노출 복원' not in why:
                        p['adds'] += 1; p['iw'] += amt / E / max(expo[t - 1], 1e-9)
                else:
                    pos[j] = dict(u=amt / px, avg=px, entry=px, peak=px, t0=t, adds=0, stop=0.0, last=px, tw=tws.get(j, max_w),
                                  iw=amt / E / max(expo[t - 1], 1e-9))     # iw = 노출 100% 일 때의 의도 비중
                    if S['exit'].get('stop'):
                        pos[j]['stop'] = px * (1 - float(S['exit']['stop']) / 100)
                log(t, j, '매수' if kind == 'buy' else '불타기', px, amt / E, why)
        pend = []
        # ② 주중 스탑(손절·래칫)
        for j in list(pos):
            p = pos[j]
            if p['stop'] and np.isfinite(L[t, j]) and L[t, j] <= p['stop'] and t - p['t0'] >= 0:
                px = min(O[t, j], p['stop']) if np.isfinite(O[t, j]) else p['stop']
                amt = p['u'] * px; cash += amt * (1 - cost)
                why = '손절(스탑)' if p['peak'] <= p['entry'] * 1.0001 or not tr_l else '래칫(스탑)'
                log(t, j, '매도', px, amt / max(val(t), 1e-12), why, px / p['avg'] - 1)
                pos.pop(j); cool[j] = t + int(S['exit'].get('cooldown', 0))
        # ③ 종가: 고점·래칫 갱신, 패널 이탈 정리
        for j in list(pos):
            p = pos[j]
            if np.isfinite(C[t, j]):
                p['last'] = C[t, j]; p['peak'] = max(p['peak'], C[t, j])
                g = p['peak'] / p['entry'] - 1
                if t - p['t0'] >= int(S['exit'].get('min_hold', 0)):
                    for th, trl in tr_l:
                        if g * 100 >= th:
                            p['stop'] = max(p['stop'], p['peak'] * (1 - trl / 100))
            elif t + 1 < len(dates) and not np.isfinite(C[t + 1:min(t + 5, len(dates)), j]).any():
                amt = p['u'] * p['last']; cash += amt * (1 - cost)
                log(t, j, '매도', p['last'], amt / max(val(t), 1e-12), '가격 끊김(상폐·이탈)', p['last'] / p['avg'] - 1)
                pos.pop(j)
        E = val(t)
        eq_s.append(E)
        stock_w = 1 - cash / E if E > 0 else 0
        ex_s.append(stock_w)
        if t + 1 >= t1:
            break
        # ④ 다음 주 주문 결정
        sold = set()
        for j, p in pos.items():                                     # 청산 신호(요구 5)
            if t - p['t0'] < int(S['exit'].get('min_hold', 0)):
                continue
            for nm, M in sigs:
                if M[t, j]:
                    pend.append(('sell', j, None, nm)); sold.add(j); break
        tgt_e = expo[t]
        if tgt_e <= 0 and pos:                                       # 노출 0 → 전부 정리
            for j in pos:
                if j not in sold:
                    pend.append(('sell', j, None, '노출 0 (지수·달력)')); sold.add(j)
        elif stock_w > tgt_e + 0.02 and pos:                         # 노출 축소 → 비례 덜기
            f = tgt_e / stock_w
            for j, p in pos.items():
                if j not in sold:
                    pend.append(('trim', j, p['u'] * C[t, j] / E * f if np.isfinite(C[t, j]) else 0, '노출 축소'))
        for j, p in pos.items():                                     # 불타기(요구 3)
            if j in sold or not np.isfinite(C[t, j]):
                continue
            g = C[t, j] / p['entry'] - 1
            w_now = p['u'] * C[t, j] / E
            if p['adds'] < len(pyr) and g * 100 >= pyr[p['adds']][0] and tgt_e > 0:
                add = min(pyr[p['adds']][1] * p.get('tw', max_w), max_w - w_now)
                if add > 0.001:
                    pend.append(('add', j, add, f"불타기 +{pyr[p['adds']][0]:.0f}%"))
            elif w_now > max_w * 1.05:                               # 상한 초과 → 덜기(익절)
                pend.append(('trim', j, max_w, f'상한 {max_w * 100:.0f}% 초과 익절'))
        if (t - t0) % int(S['rebalance']) == 0 and tgt_e > 0:        # 리밸런싱: 신규 편입
            cand = np.where(ok[t] & np.isfinite(rk[t]) & np.isfinite(C[t]))[0]
            order = cand[np.argsort(-rk[t, cand])]
            for r in rank_out:
                top = set(order[:int(r.get('m', max_pos * 2))])
                for j in pos:
                    if j not in sold and j not in top and t - pos[j]['t0'] >= int(S['exit'].get('min_hold', 0)):
                        pend.append(('sell', j, None, f"순위 이탈(상위 {int(r.get('m', max_pos * 2))} 밖)")); sold.add(j)
            for j, p in pos.items():                                 # 노출이 돌아오면 줄였던 종목을 의도 비중까지 복원
                if j in sold or not np.isfinite(C[t, j]):
                    continue
                want = min(p['iw'] * tgt_e, max_w) - p['u'] * C[t, j] / E
                if want > 0.2 * p['iw'] * tgt_e:
                    pend.append(('add', j, want, '노출 복원'))
            free = max_pos - (len(pos) - len(sold))
            new = [j for j in order if j not in pos and cool.get(j, -1) <= t][:max(0, free)]
            if new:
                n_all = len(pos) - len(sold) + len(new)
                if S['weight'] == 'rank':
                    raw = np.array([max_pos - i for i in range(len(new))], float)
                elif S['weight'] == 'mcap':
                    raw = np.array([mc[t, j] if np.isfinite(mc[t, j]) else 0 for j in new])
                elif S['weight'] == 'inv_vol':
                    raw = np.array([1 / vol[t, j] if vol is not None and np.isfinite(vol[t, j]) and vol[t, j] > 0 else 0 for j in new])
                else:
                    raw = np.ones(len(new))
                share = tgt_e * len(new) / max(n_all, max_pos) if S['weight'] == 'equal' else tgt_e * len(new) / max_pos
                tw = np.minimum(raw / raw.sum() * share if raw.sum() > 0 else raw, max_w)
                rank_of = {j: i + 1 for i, j in enumerate(order[:max_pos * 3])}
                for j, w in zip(new, tw):
                    if w > 0:
                        tws[j] = float(w)                            # 목표 비중 — 불타기 단위·상한의 기준
                        pend.append(('buy', j, w * init, f"편입(순위 {rank_of.get(j, '-')})"))

    idx = dates[t0:t0 + len(eq_s)]
    eq = pd.Series(eq_s, index=idx)
    T = pd.DataFrame(trades)
    bench = None
    if bench_px is not None:
        b = bench_px.reindex(idx, method='ffill')
        bench = b / b.iloc[0]
    return dict(equity=eq, bench=bench, exposure=pd.Series(ex_s, index=idx), trades=T,
                holdings=_holdings(P, pos, C, len(eq_s) + t0 - 1, val(len(eq_s) + t0 - 1)),
                stats=stats(eq, bench, T))



def _holdings(P, pos, C, t, E):
    rows = []
    per = P.base('per').values
    for j, p in pos.items():
        px = C[t, j] if np.isfinite(C[t, j]) else p['last']
        rows.append(dict(종목=P.names.get(P.syms[j], P.syms[j]), 코드=P.syms[j], 비중=p['u'] * px / E * 100,
                         평단=p['avg'], 현재가=px, 수익률=(px / p['avg'] - 1) * 100, 고점대비=(px / p['peak'] - 1) * 100,
                         손절선=p['stop'] or None, 불타기=p['adds'], PER=per[t, j] if np.isfinite(per[t, j]) else None))
    return pd.DataFrame(rows).sort_values('비중', ascending=False) if rows else pd.DataFrame()


def stats(eq, bench=None, T=None):
    if len(eq) < 2:
        return {}
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / max(yrs, 1e-9)) - 1
    dd = (eq / eq.cummax() - 1).min()
    r = eq.pct_change().dropna()
    out = dict(CAGR=cagr * 100, MDD=dd * 100, Sharpe=(r.mean() / r.std() * math.sqrt(52)) if r.std() > 0 else None,
               Calmar=(cagr / -dd) if dd < 0 else None, 최종배수=float(eq.iloc[-1] / eq.iloc[0]), 기간년=yrs)
    if bench is not None and len(bench.dropna()) > 1:
        b = bench.dropna()
        out['BM_CAGR'] = ((b.iloc[-1] / b.iloc[0]) ** (1 / max(yrs, 1e-9)) - 1) * 100
        out['BM_MDD'] = (b / b.cummax() - 1).min() * 100
    if T is not None and len(T):
        s = T[T.구분 == '매도']
        out['매도건수'] = int(len(s))
        out['승률'] = float((s.수익률 > 0).mean() * 100) if len(s) else None
        w, l_ = s[s.수익률 > 0].수익률, s[s.수익률 <= 0].수익률
        out['손익비'] = float(w.mean() / -l_.mean()) if len(w) and len(l_) and l_.mean() < 0 else None
    return out
