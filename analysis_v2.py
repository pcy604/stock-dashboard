# -*- coding: utf-8 -*-
"""🔍 종목 분석 v2 (2026-11-10, 차니 합의) — 5축 화면의 '각 블록 첫 줄 판정'을 계산하는 순수 함수 모음.

화면(dashboard._tab_analysis)은 이 모듈이 돌려준 dict 만 그린다. 여기엔 streamlit 을 쓰지 않는다(테스트 가능하게).

축: 결론 → 수급·관심 → 펀더멘털 → 밸류에이션 → 촉매·리스크 → 매매 계획 → 원자료
판정 톤: 'good' 🟢 · 'mid' 🟡 · 'bad' 🔴 · 'na' (판정 불가 — 데이터 없음을 정직하게)

근거(대화 2026-11-10):
- 수급: 오닐 '선도 업종 안의 1·2등' — 업종 강도(업종 RS 순위) × 종목 RS 를 2×2 로.
- 펀더멘털: 지난 실적만 보면 사이클 기업이 바닥에서 '박살'로 보인다 → '앞으로'(컨센서스·리비전)를 대표로,
  사이클 기업은 자기 이익률 분포 안 위치로 읽는다(린치: 경기민감주는 P/E 해석이 뒤집힌다).
- 밸류: 히스토리컬 밸류(자기 과거 밴드)는 유지하되 '사업이 바뀌면 의미 약함' 경고. 매수 판정엔 넣지 않는다(참고).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

VERSION = 2
# 2026-11-13 차니 확정 순서(대가 분석법 정리 뒤): 수급 → 이익 방향 → 가격 → 정체 → 깨지는 조건·촉매 → 매매 계획 → 원자료.
#   정체(린치 유형)는 읽는 순서는 5번째지만 계산은 먼저(stock_snapshot.compute) — 유형이 가격 해석을 정한다.
AXES = ['수급', '이익 방향', '가격', '정체', '깨지는 조건·촉매', '매매 계획', '원자료']
AXIS_ICON = {'수급': '🌊', '이익 방향': '🏭', '가격': '⚖️', '정체': '🪪', '깨지는 조건·촉매': '⚡', '매매 계획': '🎯', '원자료': '📚'}
AXIS_ALIAS = {'펀더멘털': '이익 방향', '밸류': '가격', '촉매·리스크': '깨지는 조건·촉매'}   # 계정에 저장된 옛 이름 → 새 이름
DEFAULT_AXES = ['수급', '이익 방향', '가격', '정체', '깨지는 조건·촉매', '매매 계획']
DEFAULT_AXES_MOBILE = []


def _card(label, value, sub='', tone='na'):
    return {'label': label, 'value': value, 'sub': sub, 'tone': tone}


# ── 공통: 52주 고점(종가 기준)·날짜 ─────────────────────────────────────────
def high52(close: pd.Series) -> dict | None:
    """최근 252거래일 종가 최고 — 값·날짜·지금 낙폭·몇 주 전. 손절선(고점 −20%)·정류장과 같은 종가 기준."""
    c = pd.to_numeric(close, errors='coerce').dropna()
    c = c[c > 0]
    if len(c) < 20:
        return None
    w = c.tail(252)
    hi_d = w.idxmax()
    hi = float(w.max())
    now = float(c.iloc[-1])
    wk = int((pd.Timestamp(c.index[-1]) - pd.Timestamp(hi_d)).days // 7)
    return {'high': hi, 'date': pd.Timestamp(hi_d).date(), 'dd': (now / hi - 1) * 100, 'weeks': wk,
            'low': float(w.min()), 'low_date': pd.Timestamp(w.idxmin()).date()}


# ── 수급: 업종 온도 × 종목 RS ────────────────────────────────────────────────
def group_heat(base: pd.DataFrame, groups: dict, market: str | None = None, min_n: int = 3) -> pd.DataFrame:
    """업종(무리)별 RS 중앙값 → 순위. base = common_metrics 표(index=코드, 'RS'·'시장' 열).
    groups = {이름: [코드…]}. 명단 안 종목이 min_n 미만인 무리는 뺀다(우연 방지)."""
    if base is None or base.empty or 'RS' not in base.columns:
        return pd.DataFrame(columns=['group', 'med_rs', 'n', 'rank', 'of', 'pct'])
    rs = pd.to_numeric(base['RS'], errors='coerce')
    mk = base['시장'] if '시장' in base.columns else None
    rows = []
    for name, codes in (groups or {}).items():
        idx = [str(c) for c in codes if str(c) in rs.index]
        if market is not None and mk is not None:
            idx = [c for c in idx if mk.get(c) == market]
        v = rs.reindex(idx).dropna()
        if len(v) >= min_n:
            rows.append({'group': name, 'med_rs': float(v.median()), 'n': int(len(v))})
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=['group', 'med_rs', 'n', 'rank', 'of', 'pct'])
    df = df.sort_values('med_rs', ascending=False).reset_index(drop=True)
    df['rank'] = np.arange(1, len(df) + 1)
    df['of'] = len(df)
    df['pct'] = (df['rank'] / len(df) * 100).round(0)
    return df


def flow_quadrant(group_pct: float | None, stock_rs: float | None, top_pct: float = 30, rs_strong: float = 80) -> dict:
    """2×2 — 업종 상위 top_pct% 안 & 종목 RS ≥ rs_strong."""
    if stock_rs is None or pd.isna(stock_rs):
        return {'label': '판정 불가', 'tone': 'na', 'why': '종목 RS 없음(공통 지표 명단 밖)'}
    s = stock_rs >= rs_strong
    if group_pct is None or pd.isna(group_pct):
        return {'label': '종목 강함 · 업종 미상' if s else '종목 약함 · 업종 미상', 'tone': 'mid' if s else 'bad',
                'why': '업종 분류 없음 — 업종 강도 산출 불가'}
    g = group_pct <= top_pct
    if g and s:
        return {'label': '주도 업종의 주도주', 'tone': 'good', 'why': f'업종 상위 {group_pct:.0f}% · 종목 RS {stock_rs:.0f}'}
    if g and not s:
        return {'label': '업종 강세 · 종목 소외', 'tone': 'mid', 'why': f'업종 상위 {group_pct:.0f}% · 종목 RS {stock_rs:.0f}'}
    if s:
        return {'label': '종목 단독 강세 — 업종 수급 뒷받침 없음', 'tone': 'mid', 'why': f'업종 상위 {group_pct:.0f}% · 종목 RS {stock_rs:.0f}'}
    return {'label': '업종·종목 동반 약세', 'tone': 'bad', 'why': f'업종 상위 {group_pct:.0f}% · 종목 RS {stock_rs:.0f}'}


def volume_ratio(vol: pd.Series | None, a: int = 5, b: int = 20) -> float | None:
    if vol is None:
        return None
    v = pd.to_numeric(vol, errors='coerce').dropna()
    if len(v) < a + b:
        return None
    base = float(v.iloc[-(a + b):-a].mean())
    return float(v.tail(a).mean()) / base if base > 0 else None


# ── 펀더멘털: 앞으로(컨센서스·리비전) ────────────────────────────────────────
def forward_us(eps_trend: pd.DataFrame | None, eps_rev: pd.DataFrame | None) -> dict:
    """yfinance eps_trend(행 0q/+1q/0y/+1y · 열 current/7daysAgo/30daysAgo/90daysAgo) + eps_revisions(up/downLast30days).
    대표 = 내년(+1y) EPS 성장(올해 대비) + 올해·내년 추정치 90일 변화 + 30일 상향−하향 건수."""
    if eps_trend is None or len(eps_trend) == 0:
        return {'tone': 'na', 'value': '-', 'sub': '애널리스트 추정치 없음', 'growth': None, 'rev90': None, 'net30': None}

    def g(per, col):
        try:
            v = eps_trend.loc[per, col]
            return float(v) if v is not None and pd.notna(v) else None
        except Exception:
            return None
    cy, ny = g('0y', 'current'), g('+1y', 'current')
    growth = (ny / cy - 1) * 100 if (cy and ny and cy > 0) else None
    revs = []
    for per in ('0y', '+1y'):
        c0, c90 = g(per, 'current'), g(per, '90daysAgo')
        if c0 is not None and c90 not in (None, 0):
            revs.append((c0 / c90 - 1) * 100 * (1 if c90 > 0 else -1))
    rev90 = float(np.mean(revs)) if revs else None
    net30 = None
    if eps_rev is not None and len(eps_rev):
        try:
            up = sum(float(eps_rev.loc[p, 'upLast30days'] or 0) for p in ('0y', '+1y') if p in eps_rev.index)
            dn = sum(float(eps_rev.loc[p, 'downLast30days'] or 0) for p in ('0y', '+1y') if p in eps_rev.index)
            net30 = up - dn
        except Exception:
            net30 = None
    up_ok = (rev90 is not None and rev90 > 0) and (net30 is None or net30 >= 0)
    dn_bad = (rev90 is not None and rev90 < -3) or (net30 is not None and net30 < 0)
    tone = 'good' if up_ok and (growth is None or growth > 0) else ('bad' if dn_bad else 'mid')
    val = (f"내년 EPS {growth:+.0f}%" if growth is not None else '성장률 -')
    sub = ' · '.join(x for x in (f"추정치 90일 {rev90:+.1f}%" if rev90 is not None else None,
                                 f"30일 상향−하향 {net30:+.0f}건" if net30 is not None else None) if x)
    return {'tone': tone, 'value': val, 'sub': sub or '리비전 데이터 없음', 'growth': growth, 'rev90': rev90, 'net30': net30}


def forward_kr(hist_rows: list[dict] | pd.DataFrame | None) -> dict:
    """네이버·FnGuide 컨센서스 스냅샷 이력(eps_0y·eps_1y·op_0y·op_1y). 2026-10 말부터 쌓기 시작 — 짧으면 그만큼만 말한다."""
    h = pd.DataFrame(hist_rows) if hist_rows is not None and not isinstance(hist_rows, pd.DataFrame) else hist_rows
    if h is None or h.empty:
        return {'tone': 'na', 'value': '-', 'sub': '컨센서스 없음(커버 증권사 없음 또는 미수집)', 'growth': None, 'rev': None, 'span': 0}
    h = h.copy()
    h['date'] = pd.to_datetime(h['date'], errors='coerce')
    h = h.dropna(subset=['date']).sort_values('date')
    last = h.iloc[-1]

    def num(r, k):
        v = r.get(k) if hasattr(r, 'get') else None
        try:
            v = float(v)
        except Exception:
            return None
        return v if pd.notna(v) else None
    op0, op1 = num(last, 'op_0y'), num(last, 'op_1y')
    e0, e1 = num(last, 'eps_0y'), num(last, 'eps_1y')
    if op0 is not None and op1 is not None and op0 > 0:
        growth, gl = (op1 / op0 - 1) * 100, '내년 영업이익'
    elif e0 is not None and e1 is not None and e0 > 0:
        growth, gl = (e1 / e0 - 1) * 100, '내년 EPS'
    else:
        growth, gl = None, None
    span = int((h['date'].iloc[-1] - h['date'].iloc[0]).days)
    rev = None
    for k in ('op_1y', 'op_0y', 'eps_1y', 'eps_0y'):
        if k in h:
            s = pd.to_numeric(h[k], errors='coerce').dropna()
            if len(s) >= 2 and s.iloc[0] not in (0,):
                rev = (s.iloc[-1] / s.iloc[0] - 1) * 100 * (1 if s.iloc[0] > 0 else -1)
                break
    tone = 'na'
    if growth is not None or rev is not None:
        if (rev is None or rev >= 0) and (growth is None or growth > 0):
            tone = 'good'
        elif (rev is not None and rev < -3) or (growth is not None and growth < 0):
            tone = 'bad'
        else:
            tone = 'mid'
    val = f"{gl} {growth:+.0f}%" if growth is not None else '성장률 -'
    sub = (f"추정치 {span}일 {rev:+.1f}%" if rev is not None and span else "추정치 변화 이력 축적 중(2026-10~)")
    return {'tone': tone, 'value': val, 'sub': sub, 'growth': growth, 'rev': rev, 'span': span}


# ── 펀더멘털: 사이클 위치 ───────────────────────────────────────────────────
def cycle_position(qf: pd.DataFrame | None, min_q: int = 12) -> dict:
    """분기 재무(quarterly_frame) → 영업이익률(TTM) 이력. 사이클 기업 판정 + 지금 위치(자기 분포의 백분위).

    사이클 판정(둘 중 하나): ① TTM 영업이익률 표준편차 ≥ 8%p ② 적자 TTM 분기가 전체의 15% 이상이면서 흑자 분기도 있음.
    — 업종표 없이 이 회사 자기 이력으로만 판정한다(메모리·화학·해운이 아니어도 실제로 출렁이면 사이클)."""
    if qf is None or qf.empty or 'revenue' not in qf or 'op_income' not in qf:
        return {'cyclical': None, 'tone': 'na', 'value': '-', 'sub': '분기 재무 부족', 'pct': None, 'n': 0}
    q = qf[['revenue', 'op_income']].astype(float)
    r4 = q['revenue'].rolling(4, min_periods=4).sum()
    o4 = q['op_income'].rolling(4, min_periods=4).sum()
    opm = (o4 / r4 * 100).replace([np.inf, -np.inf], np.nan).dropna()
    opm = opm[r4.reindex(opm.index) > 0]
    n = int(len(opm))
    if n < min_q:
        return {'cyclical': None, 'tone': 'na', 'value': '-', 'sub': f'TTM 이익률 {n}개 분기 — {min_q}개 이상 필요', 'pct': None, 'n': n}
    sd = float(opm.std())
    neg = float((opm < 0).mean())
    cyc = bool(sd >= 8 or (neg >= 0.15 and (opm > 0).any()))
    now = float(opm.iloc[-1])
    pct = float((opm < now).mean() * 100)
    prev = float(opm.iloc[-5]) if n >= 5 else None
    # 방향은 '분기 단독' 이익률로 — TTM 은 바닥을 지나도 한동안 내려가 보여 사이클 전환을 늦게 잡는다
    qo = (q['op_income'] / q['revenue'] * 100).replace([np.inf, -np.inf], np.nan).dropna()
    rising = bool(len(qo) >= 3 and qo.iloc[-1] > qo.iloc[-3:-1].mean())
    yrs = n / 4
    if cyc:
        if pct <= 30:
            lab, tone = ('바닥권에서 회복 중' if rising else '바닥권'), ('good' if rising else 'mid')
        elif pct >= 80:
            lab, tone = ('천장권' if not rising else '천장권 — 아직 상승 중'), 'bad' if not rising else 'mid'
        else:
            lab, tone = ('중간 — 상승 국면' if rising else '중간 — 하강 국면'), ('good' if rising else 'mid')
        val = f"사이클 기업 · {lab}"
    else:
        lab, tone = ('이익률 개선 중' if rising else '이익률 둔화'), ('good' if rising else 'mid')
        val = f"안정형 · {lab}"
    sub = f"영업이익률(TTM) {now:.1f}% · 지난 {yrs:.0f}년 중 {pct:.0f} 백분위 · 1년 전 {prev:.1f}%" if prev is not None else \
          f"영업이익률(TTM) {now:.1f}% · {pct:.0f} 백분위"
    return {'cyclical': cyc, 'tone': tone, 'value': val, 'sub': sub, 'pct': pct, 'n': n, 'opm_now': now,
            'opm_sd': sd, 'neg_share': neg, 'rising': rising}


# ── 밸류 ────────────────────────────────────────────────────────────────────
def valuation_reading(band_pct: float | None, peg: float | None, per_vs_peer: float | None, cyclical: bool | None) -> dict:
    """band_pct = 지금 P/E 가 자기 과거 몇 % 기간보다 비싼가(0=역대 최저) · per_vs_peer = 이 종목 P/E ÷ 업종 중앙.
    사이클 기업은 P/E 해석을 뒤집지 않고 '판정 보류 + P/B·정상화 이익을 보라'고 말한다(바닥에선 P/E 가 높게 나온다)."""
    if cyclical:
        return {'tone': 'na', 'value': '사이클 기업 — P/E 해석 주의',
                'sub': '이익 바닥에서 P/E 가 높고 천장에서 낮게 형성(피터 린치) — P/B·자기 과거 밴드 병행 확인'}
    votes, why = [], []
    if peg is not None and peg > 0:
        votes.append(1 if peg < 1 else (-1 if peg > 2 else 0)); why.append(f"PEG {peg:.2f}")
    if band_pct is not None:
        votes.append(1 if band_pct <= 25 else (-1 if band_pct >= 75 else 0)); why.append(f"자기 과거 {band_pct:.0f}% 구간 상회")
    if per_vs_peer is not None and per_vs_peer > 0:
        votes.append(1 if per_vs_peer <= 0.8 else (-1 if per_vs_peer >= 1.25 else 0)); why.append(f"업종 대비 {per_vs_peer:.2f}배")
    if not votes:
        return {'tone': 'na', 'value': '판정 불가', 'sub': '적자 또는 멀티플 데이터 없음 — P/S 참고'}
    s = sum(votes)
    lab, tone = ('성장 대비 저평가', 'good') if s >= 1 else (('고평가', 'bad') if s <= -1 else ('중립', 'mid'))
    return {'tone': tone, 'value': lab, 'sub': ' · '.join(why)}


TONE_DOT = {'good': '🟢', 'mid': '🟡', 'bad': '🔴', 'na': '⚪'}
