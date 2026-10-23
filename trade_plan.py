# -*- coding: utf-8 -*-
"""종합 매매 판단 (2026-10-23) — 종목 분석 탭 '🎯 매매 판단' 섹션의 계산 층.

사용자 요청: 낙폭 회차 → 다운사이드, 컨센서스·역사적 PER·PEG 목표가, 리버모어 피벗·CANSLIM·이평·RSI·MACD 로
매수 가능/관망/탈출 판정, 1차·2차 손절과 업사이드, "x% 빠지면 y%까지 갈 확률"(정류장 간격), 저점 대비 상승의
같은 통계, 기대수익·리스크, 포트 내 투입 가능 비중.

원칙 (화면에도 그대로 적는다)
  · 전부 **규칙 계산**이다. AI 판단·예측이 아니고 투자 권유가 아니다.
  · 확률은 **이 종목의 과거 빈도**다. 표본 수(n)를 항상 같이 낸다 — n 이 작으면 '참고 불가'.
  · 매매 원칙 v1: 위성은 가격 손절을 쓰지 않는다(백테스트에서 고점 −20% 손절이 CAGR 15.4% → 9.9%).
    그래서 1·2차 손절은 '트레이더식 참고선'으로 보이고, 위험은 **비중(총자산 1.5% = 위성 한 칸)**으로 관리한다.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


# ── 1) 정류장 — 스윙(지그재그) 통계 ─────────────────────────────────
def zigzag(close: pd.Series, theta: float = 10.0) -> list[dict]:
    """종가 지그재그: 직전 극점에서 theta% 이상 되돌리면 새 스윙. 반환 [{type:'H'|'L', date, price}] (오래된 순).
    마지막 극점은 '확정 안 된' 현재 진행 스윙의 출발점이다."""
    c = close.dropna()
    if len(c) < 3:
        return []
    th = theta / 100.0
    piv = []
    hi = lo = float(c.iloc[0])
    hi_d = lo_d = c.index[0]
    trend = 0                       # 1 상승 스윙 진행 중, -1 하락 스윙 진행 중
    for d, p in c.items():
        p = float(p)
        if trend >= 0:
            if p > hi:
                hi, hi_d = p, d
            if trend == 0 and p < lo:
                lo, lo_d = p, d
            if p <= hi * (1 - th):  # 고점에서 theta 이상 하락 → 고점 확정
                if trend == 0 and lo_d < hi_d:
                    piv.append({'type': 'L', 'date': lo_d, 'price': lo})
                piv.append({'type': 'H', 'date': hi_d, 'price': hi})
                trend, lo, lo_d = -1, p, d
                continue
        if trend <= 0:
            if p < lo:
                lo, lo_d = p, d
            if trend == 0 and p > hi:
                hi, hi_d = p, d
            if p >= lo * (1 + th):  # 저점에서 theta 이상 반등 → 저점 확정
                if trend == 0 and hi_d < lo_d:
                    piv.append({'type': 'H', 'date': hi_d, 'price': hi})
                piv.append({'type': 'L', 'date': lo_d, 'price': lo})
                trend, hi, hi_d = 1, p, d
    # 진행 중 스윙의 극점(아직 theta 되돌림 없음)
    if trend == 1:
        piv.append({'type': 'H?', 'date': hi_d, 'price': hi})
    elif trend == -1:
        piv.append({'type': 'L?', 'date': lo_d, 'price': lo})
    return piv


def swings(close: pd.Series, theta: float = 10.0) -> dict:
    """확정 스윙 크기 목록 + 현재 진행 스윙.
    declines: 고점→저점 하락폭(%, 양수) / rallies: 저점→고점 상승폭(%)
    current: {'dir': 'down'|'up', 'from': 출발 극점 가격, 'from_date', 'move': 지금까지 %(하락은 양수)}"""
    piv = zigzag(close, theta)
    dec, ral = [], []
    conf = [p for p in piv if p['type'] in ('H', 'L')]
    for a, b in zip(conf, conf[1:]):
        if a['type'] == 'H' and b['type'] == 'L':
            dec.append((1 - b['price'] / a['price']) * 100)
        elif a['type'] == 'L' and b['type'] == 'H':
            ral.append((b['price'] / a['price'] - 1) * 100)
    cur = None
    last = float(close.dropna().iloc[-1])
    ext = next((p for p in reversed(piv) if p['type'] in ('H?', 'L?')), None)
    if conf:
        lp = conf[-1]
        if lp['type'] == 'H':      # 고점 확정 뒤 → 하락 스윙 진행 중
            lo = ext['price'] if ext and ext['type'] == 'L?' else last
            cur = {'dir': 'down', 'from': lp['price'], 'from_date': lp['date'], 'move': (1 - last / lp['price']) * 100,
                   'reached': (1 - min(lo, last) / lp['price']) * 100, 'extreme': min(lo, last)}
        else:
            hi = ext['price'] if ext and ext['type'] == 'H?' else last
            cur = {'dir': 'up', 'from': lp['price'], 'from_date': lp['date'], 'move': (last / lp['price'] - 1) * 100,
                   'reached': (max(hi, last) / lp['price'] - 1) * 100, 'extreme': max(hi, last)}
    return {'declines': dec, 'rallies': ral, 'current': cur, 'theta': theta, 'pivots': piv}


def next_stops(sizes: list[float], now: float, levels=(10, 15, 20, 25, 30, 40, 50, 60, 80, 100)) -> dict:
    """버스 정류장: 지금까지 now% 움직인 스윙이 과거에 몇 %까지 갔나.
    반환 {'n': now% 이상 갔던 스윙 수, 'rows': [{level, hit, p}], 'median_final', 'p80_final'}"""
    base = [s for s in sizes if s >= now - 1e-9]
    n = len(base)
    rows = []
    for lv in levels:
        if lv <= now:
            continue
        hit = sum(1 for s in base if s >= lv)
        rows.append({'level': lv, 'hit': hit, 'p': (hit / n * 100) if n else None})
    return {'n': n, 'rows': rows,
            'median_final': float(np.median(base)) if n else None,
            'p80_final': float(np.percentile(base, 80)) if n else None}


def gap_map(sizes: list[float], step: float = 5.0, upto: float = 80.0) -> list[dict]:
    """정류장 간격: 'x% 를 넘긴 스윙이 x+step% 도 넘긴 비율' — 비율이 높은 구간 = 정류장 사이가 먼 곳(한번 넘으면 잘 안 멈춤)."""
    out = []
    x = step
    while x < upto:
        a = sum(1 for s in sizes if s >= x)
        b = sum(1 for s in sizes if s >= x + step)
        if a:
            out.append({'from': x, 'to': x + step, 'n': a, 'p': b / a * 100})
        x += step
    return out


# ── 2) 비슷한 상태에서 산 날의 앞으로 수익 분포 ─────────────────────
def forward_similar(close: pd.Series, horizon: int = 126, band: float = 5.0, gap: int = 20) -> dict | None:
    """지금처럼 52주 고점 대비 dd±band% 였던 날 → horizon 거래일 뒤 수익 분포.
    겹치는 표본을 줄이려고 gap 거래일 간격으로만 뽑는다(같은 사건을 매일 세지 않는다)."""
    c = close.dropna()
    if len(c) < 252 + horizon + 10:
        return None
    hi = c.rolling(252, min_periods=120).max()
    dd = (c / hi - 1) * 100
    now = float(dd.iloc[-1])
    fwd = c.shift(-horizon) / c - 1
    ok = (dd - now).abs() <= band
    ok &= fwd.notna()
    idx = list(np.flatnonzero(ok.values))
    pick, last = [], -10 ** 9
    for i in idx:
        if i - last >= gap:
            pick.append(i)
            last = i
    if not pick:
        return {'n': 0, 'dd_now': now}
    r = fwd.iloc[pick].values * 100
    return {'n': len(r), 'dd_now': now, 'median': float(np.median(r)), 'p10': float(np.percentile(r, 10)),
            'p90': float(np.percentile(r, 90)), 'win': float((r > 0).mean() * 100), 'horizon': horizon}


# ── 3) 기술 지표 ────────────────────────────────────────────────
def rsi(close: pd.Series, n: int = 14) -> float | None:
    c = close.dropna()
    if len(c) < n + 2:
        return None
    d = c.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    v = float((100 - 100 / (1 + rs)).iloc[-1])
    return v if v == v else 100.0


def macd(close: pd.Series) -> dict | None:
    c = close.dropna()
    if len(c) < 40:
        return None
    m = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    s = m.ewm(span=9, adjust=False).mean()
    h = m - s
    return {'macd': float(m.iloc[-1]), 'signal': float(s.iloc[-1]), 'hist': float(h.iloc[-1]),
            'hist_prev': float(h.iloc[-2]), 'above': bool(m.iloc[-1] > s.iloc[-1])}


def livermore(close: pd.Series, volume: pd.Series | None = None, base_days: int = 252, exclude: int = 10) -> dict:
    """리버모어 피벗(핵심 가격): 직전 base_days 중 마지막 exclude 일을 뺀 구간의 최고 종가.
    · 피벗 ~ +5% & 거래량 20일 평균의 1.4배↑ → '돌파 매수 구간'(그는 핵심 가격을 거래량과 함께 넘을 때만 샀다)
    · +5% 초과 → '연장(추격 금지)' · 피벗 −5% 이내 → '피벗 대기' · 그 아래 → '피벗 아래'
    피라미딩: 첫 매수가 맞았을 때(수익 중)만 추가 — 손실 중 추가(물타기) 금지."""
    c = close.dropna()
    if len(c) < 60:
        return {'state': '표본 부족'}
    win = c.iloc[-base_days:-exclude] if len(c) > base_days else c.iloc[:-exclude]
    pivot = float(win.max())
    p = float(c.iloc[-1])
    gap = (p / pivot - 1) * 100
    vr = None
    if volume is not None and len(volume.dropna()) > 25:
        v = volume.dropna()
        vr = float(v.iloc[-5:].mean() / v.iloc[-25:-5].mean()) if v.iloc[-25:-5].mean() > 0 else None
    if 0 <= gap <= 5:
        state = '돌파 매수 구간' if (vr or 0) >= 1.4 else '돌파 · 거래량 미확인'
    elif gap > 5:
        state = '연장 — 추격 금지'
    elif gap >= -5:
        state = '피벗 대기'
    else:
        state = '피벗 아래'
    return {'state': state, 'pivot': pivot, 'gap': gap, 'vol_ratio': vr,
            'adds': [pivot * 1.05, pivot * 1.10]}      # 피라미딩 추가 지점(첫 매수가 수익일 때만)


# ── 4) 목표가 ───────────────────────────────────────────────────
def targets(price: float, *, cons: dict | None = None, band: dict | None = None, eps_fwd: float | None = None,
            eps_ttm: float | None = None, hi52: float | None = None) -> list[dict]:
    """목표가 후보. 각 {'name','price','up','basis'} — 계산 못 하는 건 빠진다.
    band: multiple_band 의 P/E 밴드(pct 10~90). eps_fwd: 12MF EPS."""
    out = []

    def add(name, v, basis):
        if v and v > 0 and price:
            out.append({'name': name, 'price': float(v), 'up': (v / price - 1) * 100, 'basis': basis})
    cons = cons or {}
    if cons.get('mean'):
        add('컨센서스 평균', cons['mean'], f"애널 {cons.get('n') or '?'}명 평균" + (" ⚠️3명 미만" if (cons.get('n') or 0) < 3 else ''))
    if cons.get('high') and (cons.get('n') or 0) >= 3:
        add('컨센서스 최고', cons['high'], '가장 낙관적인 애널')
    if band and band.get('kind') == 'P/E' and eps_fwd and eps_fwd > 0:
        add('역사적 PER 고점(90분위)', band['pct'][90] * eps_fwd, f"PER {band['pct'][90]:.1f}배 × 12MF EPS")
        add('역사적 PER 중앙값', band['pct'][50] * eps_fwd, f"PER {band['pct'][50]:.1f}배 × 12MF EPS")
    elif band and band.get('implied'):
        add(f"역사적 {band['kind']} 고점(90분위)", band['implied'].get(90), f"{band['kind']} {band['pct'][90]:.1f}배 × 현재 실적")
        add(f"역사적 {band['kind']} 중앙값", band['implied'].get(50), f"{band['kind']} {band['pct'][50]:.1f}배 × 현재 실적")
    if eps_fwd and eps_ttm and eps_ttm > 0 and eps_fwd > eps_ttm:
        g = min((eps_fwd / eps_ttm - 1) * 100, 50.0)          # 린치: 적정 PER = 성장률(%) — 50% 상한
        if g >= 5:
            add('PEG 1 적정가(린치)', g * eps_fwd, f"성장률 {g:.0f}% = 적정 PER {g:.0f}배 × 12MF EPS (성장률 50% 상한)")
    if hi52:
        add('52주 고점 복귀', hi52, '직전 고점까지')
    return out


# ── 5) 판정 · 손절 · 비중 ──────────────────────────────────────────
def verdict(*, price, ma50, ma200, ma200_prev, tt_n, rsi_v, macd_d, canslim_grade, liv, dd52) -> dict:
    """체크리스트 → '매수 가능 영역' / '관망' / '탈출 검토 영역'. 반환 {'state','tone','checks':[(이름, ok|bad|na, 설명)]}"""
    ck = []

    def add(name, cond, txt, bad=None):
        ck.append((name, 'na' if cond is None else ('ok' if cond else ('bad' if bad is not False else 'warn')), txt))
    up = None if None in (price, ma50, ma200) else (price > ma50 > ma200)
    add('이평 정배열(주가>50일>200일)', up, f"50일선 {ma50:,.0f} · 200일선 {ma200:,.0f}" if ma50 and ma200 else '데이터 없음')
    add('200일선 상승 중', None if ma200_prev is None or ma200 is None else ma200 > ma200_prev,
        '장기 추세 방향', bad=False)
    add('추세 템플릿 6/8 이상', None if tt_n is None else tt_n >= 6, f"{tt_n}/8" if tt_n is not None else '표본 부족')
    if rsi_v is None:
        add('RSI 과열 아님(<75)', None, '데이터 없음')
    else:
        add('RSI 과열 아님(<75)', rsi_v < 75, f"RSI {rsi_v:.0f}" + (' · 과매도(<30)' if rsi_v < 30 else ''), bad=False)
    add('MACD 시그널 위', None if not macd_d else macd_d['above'],
        ('히스토그램 ' + ('증가' if macd_d['hist'] > macd_d['hist_prev'] else '감소')) if macd_d else '데이터 없음', bad=False)
    g = str(canslim_grade or '')[:1]
    add('CANSLIM A·B', None if not g else g in 'AB', f"등급 {canslim_grade}" if g else '점수 없음', bad=False)
    add('리버모어 피벗 근처(돌파·대기)', None if liv.get('state') == '표본 부족' else liv['state'] in ('돌파 매수 구간', '돌파 · 거래량 미확인', '피벗 대기'),
        f"{liv.get('state')} · 피벗 대비 {liv.get('gap', 0):+.1f}%" if liv.get('pivot') else liv.get('state'), bad=False)
    # 탈출 조건 — 하나라도면 '탈출 검토'
    exit_hits = []
    if None not in (price, ma200, ma50) and price < ma200 and ma50 < ma200:
        exit_hits.append('200일선 아래 + 데드 배열')
    if tt_n is not None and tt_n <= 3:
        exit_hits.append(f'추세 템플릿 {tt_n}/8')
    if dd52 is not None and dd52 <= -35 and macd_d and not macd_d['above']:
        exit_hits.append(f'고점 {dd52:.0f}% + MACD 하락')
    oks = sum(1 for _, s, _ in ck if s == 'ok')
    core = [s for n, s, _ in ck if n in ('이평 정배열(주가>50일>200일)', '추세 템플릿 6/8 이상')]
    if exit_hits:
        state, tone = '탈출 검토 영역', 'bad'
    elif all(s == 'ok' for s in core) and liv.get('state') in ('돌파 매수 구간', '돌파 · 거래량 미확인', '피벗 대기') \
            and (rsi_v is None or rsi_v < 75):
        state, tone = '매수 가능 영역', 'good'
    elif all(s == 'ok' for s in core):
        state, tone = '추세는 좋음 · 진입 자리 아님', 'mid'
    else:
        state, tone = '관망', 'mid'
    return {'state': state, 'tone': tone, 'checks': ck, 'exit': exit_hits, 'ok': oks}


def stops(price: float, *, ma50=None, ma200=None, last_low=None) -> dict:
    """트레이더식 참고 손절선.
    1차 = 매수가 −8%(오닐: 7~8% 이상 손실은 무조건 자른다)
    2차 = 추세 이탈선 — 200일선이 주가 아래면 200일선, 아니면 직전 스윙 저점(없으면 −15%)"""
    # 후보를 가까운 순으로 — 1차 = 가장 가까운 선, 2차 = 그보다 2% 이상 아래의 다음 선(겹치면 건너뛴다)
    cands = [(price * 0.92, '매수가 −8%(오닐 규칙: 7~8% 넘는 손실은 자른다)')]
    if ma200 and ma200 < price * 0.995:
        cands.append((ma200, '200일선(추세 이탈)'))
    if last_low and last_low < price * 0.995:
        cands.append((last_low, '직전 스윙 저점'))
    cands.append((price * 0.85, '매수가 −15%'))
    cands = sorted(cands, key=lambda x: -x[0])
    s1, why1 = cands[0]
    s2, why2 = next(((v, w) for v, w in cands[1:] if v <= s1 * 0.98), (s1 * 0.92, '1차 −8%'))
    return {'s1': s1, 's1_pct': (s1 / price - 1) * 100, 'why1': why1,
            's2': s2, 's2_pct': (s2 / price - 1) * 100, 'why2': why2}


def position_size(*, verdict_state: str, stop_pct: float, vol_annual: float | None,
                  risk_budget: float = 1.0, slot_cap: float = 1.5, trim_cap: float = 4.5) -> dict:
    """총자산 대비 투입 가능 비중(%).
    · 위험예산식: 한 번에 잃어도 되는 금액(총자산의 risk_budget%) ÷ 손절 거리
    · 원칙 v1 상한: 위성 한 칸 = 총자산 1.5%(위성 30% × 5%) · 한 종목 최대 4.5%(위성의 15%, 트림선)
    · 연 변동성 60%↑ 이면 절반
    · '탈출 검토'·'관망' → 0 (신규 매수 대상 아님)"""
    risk_size = risk_budget / max(abs(stop_pct), 1e-9) * 100
    half = vol_annual is not None and vol_annual >= 60
    base = min(risk_size, slot_cap) * (0.5 if half else 1.0)
    if verdict_state == '매수 가능 영역':
        rec = base
    elif verdict_state == '추세는 좋음 · 진입 자리 아님':
        rec = 0.0
    else:
        rec = 0.0
    return {'risk_size': risk_size, 'slot_cap': slot_cap, 'trim_cap': trim_cap, 'half': half, 'rec': rec}
