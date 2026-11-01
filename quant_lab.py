# -*- coding: utf-8 -*-
"""🧪 전략 실험실 엔진 — 🪜 익절 래칫 + 🎮 매매 실험실을 하나로 (2026-11-01, 차니: "너무 복잡해서 나도 못 쓴다")

설계 원칙: 고를 것은 세 가지뿐.
  ① 전략 하나(카탈로그) — 각 전략은 숫자 1~2개만 묻는다
  ② (선택) 지수 필터 — 지수가 n일선 아래면 쉬기
  ③ (선택) 안전장치 — 보유 중 고점 대비 −x% 면 손절
결과는 '대박주 100'과 '평범한 종목 100'(무작위) 두 줄로만 보여 준다.

체결 규칙(모든 전략 공통, 일봉):
  · 신호는 그날 **종가**로 판정 → **다음 날 시가**에 사고판다(미래 정보 없음).
  · 안전장치·'판 가격 재매수'만 장중 스탑: 저가가 손절선 이하면 손절선에(갭이면 시가) 판다.
  · 편도 비용 0.3%. 현금 이자 없음. 고점 = 보유 중 최고 **종가**(CLAUDE.md 규칙).
"""
import numpy as np

COST = 0.003

# ── 전략 카탈로그 ─────────────────────────────────────────────────
# params: (키, 화면 이름, 최소, 최대, 기본, 간격)
STRATS = {
    'hold': dict(name='그냥 보유', kind='비교 기준',
                 desc='첫날 사서 끝까지 들고 있는다. 다른 전략은 이것과 비교한다.', params=[]),
    'trail': dict(name='고점 대비 손절 → 다시 오르면 재매수', kind='손절',
                  desc='보유 중 최고가에서 x% 빠지면 판다. 판 가격을 다시 넘으면 그 가격에 다시 산다(스탑 주문).',
                  params=[('pct', '고점 대비 손절(%)', 5, 50, 20, 5)]),
    'ma': dict(name='이동평균 추세', kind='추세 추종',
               desc='종가가 n일 이동평균 위면 보유, 아래로 내려가면 판다. 가장 오래된 추세 추종법.',
               params=[('n', '이동평균(일)', 10, 250, 50, 10)]),
    'cross': dict(name='골든크로스', kind='추세 추종',
                  desc='단기 이평이 장기 이평 위면 보유(골든크로스), 아래로 꺾이면(데드크로스) 판다.',
                  params=[('fast', '단기 이평(일)', 5, 100, 20, 5), ('slow', '장기 이평(일)', 20, 250, 100, 10)]),
    'donchian': dict(name='돌파 매매 (터틀)', kind='돌파',
                     desc='최근 n일 최고가를 넘으면 사고, 최근 m일 최저가를 깨면 판다. 1980년대 터틀 트레이더 규칙.',
                     params=[('n', '매수: n일 신고가', 10, 250, 55, 5), ('m', '매도: m일 신저가', 5, 120, 20, 5)]),
    'mom': dict(name='모멘텀', kind='모멘텀',
                desc='지난 n일 수익률이 플러스면 보유, 마이너스면 쉰다(시계열 모멘텀).',
                params=[('n', '비교 기간(일)', 20, 250, 120, 10)]),
    'rsi': dict(name='눌림목 매수 (RSI)', kind='역추세',
                desc='RSI(14)가 x 아래로 과매도되면 사고, y 위로 과열되면 판다. 추세가 아니라 반등을 노린다.',
                params=[('lo', '매수: RSI 아래', 10, 50, 30, 5), ('hi', '매도: RSI 위', 50, 90, 70, 5)]),
}
INDEX_NAME = {'SPX': 'S&P500', 'NDX': '나스닥100', 'RUT': '러셀2000', 'KOSPI': '코스피', 'KOSDAQ': '코스닥'}
INDEX_OF = {'US': 'SPX', 'KR': 'KOSPI'}
INDEX_CHOICES = {'US': ['SPX', 'NDX', 'RUT'], 'KR': ['KOSPI', 'KOSDAQ']}


def _ma(x, n):
    n = int(n)
    out = np.full(len(x), np.nan)
    if len(x) >= n:
        cs = np.cumsum(np.insert(np.nan_to_num(x, nan=0.0), 0, 0.0))
        out[n - 1:] = (cs[n:] - cs[:-n]) / n
    return out


def _roll(x, n, fn):
    n = int(n)
    out = np.full(len(x), np.nan)
    if len(x) > n:
        from numpy.lib.stride_tricks import sliding_window_view
        out[n:] = fn(sliding_window_view(x, n)[:-1], axis=1)      # 이번 날 제외한 직전 n일
    return out


def _rsi(c, n=14):
    d = np.diff(c, prepend=c[0])
    up, dn = np.clip(d, 0, None), np.clip(-d, 0, None)
    a = 1 / n
    ru = np.zeros(len(c)); rd = np.zeros(len(c))
    for t in range(1, len(c)):
        ru[t] = ru[t - 1] + a * (up[t] - ru[t - 1]); rd[t] = rd[t - 1] + a * (dn[t] - rd[t - 1])
    r = 100 - 100 / (1 + ru / np.where(rd == 0, np.nan, rd))
    r[:n] = np.nan
    return r


def want(key, p, h, l, c):
    """그날 종가 기준 '보유하고 싶다' 상태(1/0). None = 신호 없음(그냥 보유·trail 은 따로)."""
    n = len(c)
    if key == 'ma':
        m = _ma(c, p['n']); return np.where(np.isfinite(m), (c > m).astype(float), 0.0)
    if key == 'cross':
        f, s = _ma(c, p['fast']), _ma(c, p['slow']); return np.where(np.isfinite(s), (f > s).astype(float), 0.0)
    if key == 'mom':
        k = int(p['n']); w = np.zeros(n); w[k:] = (c[k:] > c[:-k]).astype(float); return w
    if key in ('donchian', 'rsi'):
        if key == 'donchian':
            buy, sell = c > _roll(h, p['n'], np.max), c < _roll(l, p['m'], np.min)
        else:
            r = _rsi(c); buy, sell = r < p['lo'], r > p['hi']
        w = np.zeros(n); s = 0.0
        for t in range(n):
            if s == 0 and buy[t]:
                s = 1.0
            elif s == 1 and sell[t]:
                s = 0.0
            w[t] = s
        return w
    return None


def run(o, h, l, c, ix, start, key, p=None, idx_ma=0, stop=0.0):
    """한 종목 실행. 반환 dict(eq=자산곡선, buys=[(t,가격)], sells=[(t,가격)], exposure)."""
    p = p or {}
    o, h, l, c = (np.asarray(x, float) for x in (o, h, l, c))
    n = len(c)
    w = want(key, p, h, l, c)
    if w is None:
        w = np.ones(n)
    if idx_ma and ix is not None:
        m = _ma(ix, idx_ma)
        w = w * np.where(np.isfinite(m) & (ix < m), 0.0, 1.0)
    trail = p.get('pct', 0) if key == 'trail' else 0
    stop_pct = max(trail, 0) or stop
    eq, held = 1.0, 0
    pos = False; peak = 0.0; level = None; blocked = False
    curve, buys, sells = [], [], []
    for t in range(start, n):
        if not (np.isfinite(o[t]) and np.isfinite(c[t])):
            curve.append(eq); continue
        px = o[t]
        if pos:                                              # 어제 종가 → 오늘 시가
            eq *= o[t] / c[t - 1] if np.isfinite(c[t - 1]) else 1.0
        tgt = (w[t - 1] if t > start else 1.0) if not blocked else 0.0
        # ① 시가 체결: 신호 변화
        if pos and tgt == 0:
            eq *= 1 - COST; pos = False; sells.append((t, o[t]))
        elif not pos and tgt == 1 and not (key == 'trail' and level is not None):
            eq *= 1 - COST; pos = True; peak = o[t]; buys.append((t, o[t]))
        # ② 장중 스탑: 손절 / (trail) 판 가격 재매수
        if pos and stop_pct and l[t] <= peak * (1 - stop_pct / 100):
            sp = min(o[t], peak * (1 - stop_pct / 100))
            eq *= (sp / px) * (1 - COST); pos = False; sells.append((t, sp)); level = sp; px = sp
            if key != 'trail':
                blocked = True                              # 안전장치 손절 뒤엔 신호가 0으로 꺼졌다 켜질 때까지 쉰다
        elif not pos and key == 'trail' and level is not None and h[t] >= level and tgt == 1 and (not sells or sells[-1][0] < t):
            bp = max(o[t], level)
            eq *= 1 - COST; pos = True; peak = bp; buys.append((t, bp)); px = bp; level = None
        # ③ 종가까지
        if pos:
            eq *= c[t] / px
            peak = max(peak, c[t]); held += 1
        if blocked and w[t] == 0:
            blocked = False
        curve.append(eq)
    return dict(eq=np.array(curve), buys=buys, sells=sells, exposure=held / max(1, n - start))


def summary(o, h, l, c, ix, start, key, p=None, idx_ma=0, stop=0.0):
    r = run(o, h, l, c, ix, start, key, p, idx_ma, stop)
    eq = r['eq']
    w = np.asarray(c[start:], float) / o[start]
    return dict(mult=float(eq[-1]), bh=float(c[-1] / o[start]),
                mdd=float((eq / np.maximum.accumulate(eq) - 1).min()),
                bh_mdd=float((w / np.maximum.accumulate(w) - 1).min()),
                trades=len(r['buys']), exposure=r['exposure'])
