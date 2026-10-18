"""종목 분석 탭 보강 계산 (2026-10-19) — 화면 코드와 분리한 순수 함수들.

1) 멀티플 밴드   multiple_band()      — P/E · P/S · P/B 의 과거 분포와 현재 위치
2) 낙폭 회차     drawdown_episodes()  — 최근 N개월 고점 대비 X% 이상 하락이 몇 번이었나
3) 신호 이력     accel_history()      — 이 종목의 이익 가속 신호(주도주 진입 규칙) 이력
4) 동종업계      peer_table()         — 같은 업종·비슷한 시총 종목과 멀티플·성장률 비교

원칙: 없는 데이터를 있는 척하지 않는다. 계산할 수 없으면 None 과 이유를 돌려준다.
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))


# ── 공통: 분기 재무 → TTM ────────────────────────────────────────────
def quarterly_frame(rows: list[dict]) -> pd.DataFrame:
    """분기 rows(period='YYYY-MM' 또는 'YYYY.QQ') → 분기말 날짜 인덱스 DataFrame(오래된 순).
    revenue·net_income 은 흐름(3개월), equity 는 잔액."""
    out = []
    for r in rows or []:
        p = str(r.get('period') or '')
        try:
            if '.' in p and p.endswith('Q'):          # KR '2026.2Q'
                y, q = p.split('.')
                end = pd.Period(f"{y}Q{q[0]}", freq='Q').end_time.normalize()
            else:                                      # US '2026-06'
                end = pd.Period(p[:7], freq='M').end_time.normalize()
        except Exception:
            continue
        out.append({'end': end, 'revenue': r.get('revenue'), 'net_income': r.get('net_income'),
                    'op_income': r.get('op_income'), 'equity': r.get('equity')})
    if not out:
        return pd.DataFrame()
    d = pd.DataFrame(out).drop_duplicates('end').set_index('end').sort_index()
    return d.astype(float)


def ttm(q: pd.DataFrame) -> pd.DataFrame:
    """연속 4개 분기가 모두 있을 때만 TTM 을 낸다(구멍 난 분기를 0 으로 메우지 않는다)."""
    if q.empty:
        return q
    t = pd.DataFrame(index=q.index)
    for c in ('revenue', 'net_income', 'op_income'):
        if c in q:
            t[c] = q[c].rolling(4, min_periods=4).sum()
    if 'equity' in q:
        t['equity'] = q['equity']
    # 분기 간격이 끊긴 곳(4분기 창이 1년을 넘는 곳)은 TTM 무효
    span = pd.Series(q.index, index=q.index).diff(3).dt.days
    t[span > 370] = np.nan
    return t


# ── 1) 멀티플 밴드 ────────────────────────────────────────────────
def multiple_band(close: pd.Series, shares: float, q: pd.DataFrame, years: int = 5):
    """월말 시총(종가×현재 주식수) ÷ 그 시점까지 **공시된** TTM 값.

    반환: {'kind': 'P/E'|'P/S'|'P/B', 'series': 월별 멀티플, 'pct': {10,25,50,75,90},
           'now': 현재값, 'rank': 현재 백분위, 'implied': {분위: 주가}, 'why': 선택 이유}
    · 최근 TTM 순이익이 적자면 P/E 대신 P/S 를 쓴다(적자 구간의 P/E 는 뜻이 없다).
    · 공시 시차 45일 — 분기말 직후엔 아직 모르는 숫자를 쓰지 않는다(미래 정보 누설 방지).
    """
    if close is None or close.empty or not shares or q.empty:
        return None
    t = ttm(q)
    known = t.copy()
    known.index = known.index + pd.Timedelta(days=45)      # 공시 시차
    m = close.resample('ME').last().dropna()
    m = m[m.index >= m.index.max() - pd.DateOffset(years=years)]
    f = known.reindex(m.index, method='ffill')
    mcap = m * shares
    last = t.dropna(how='all').iloc[-1] if not t.dropna(how='all').empty else None
    if last is None:
        return None
    out = {}
    ni_ok = last.get('net_income') is not None and pd.notna(last.get('net_income')) and last['net_income'] > 0
    if ni_ok:
        s = mcap / f['net_income'].where(f['net_income'] > 0)
        kind, why = 'P/E', '최근 TTM 순이익 흑자'
    elif pd.notna(last.get('revenue')) and last.get('revenue', 0) > 0:
        s = mcap / f['revenue'].where(f['revenue'] > 0)
        kind, why = 'P/S', '최근 TTM 순이익 적자 → P/E 대신 P/S'
    else:
        return None
    out['main'] = _band(s, kind, why, m, shares, f, 'net_income' if kind == 'P/E' else 'revenue')
    if 'equity' in f and f['equity'].notna().sum() >= 8:
        sb = mcap / f['equity'].where(f['equity'] > 0)
        out['pb'] = _band(sb, 'P/B', '자본(잔액) 기준', m, shares, f, 'equity')
    return out


def _band(s, kind, why, m, shares, f, base_col):
    s = s.replace([np.inf, -np.inf], np.nan).dropna()
    if len(s) < 12:
        return None
    pct = {p: float(np.nanpercentile(s, p)) for p in (10, 25, 50, 75, 90)}
    now = float(s.iloc[-1])
    rank = float((s < now).mean() * 100)
    base_now = f[base_col].dropna()
    implied = {}
    if not base_now.empty and shares:
        b = float(base_now.iloc[-1])
        implied = {p: v * b / shares for p, v in pct.items()}
    below10 = float((s < pct[10]).mean() * 100)
    return dict(kind=kind, why=why, series=s, pct=pct, now=now, rank=rank,
                implied=implied, n=len(s), below10=below10)


# ── 2) 낙폭 회차 ──────────────────────────────────────────────────
def drawdown_episodes(close: pd.Series, months: int = 12, thresh: float = 20.0):
    """최근 months 개월 안에서 '고점 대비 thresh% 이상 하락'한 회차.

    한 회차 = 고점에서 thresh% 이상 빠진 순간부터 **그 고점을 회복할 때까지**.
    회복 전의 추가 하락은 같은 회차로 묶는다(안 묶으면 횟수가 부풀려진다).
    반환: [{peak_date, peak, trough_date, trough, depth, recover_date, days_to_recover}] (오래된 순)
    """
    if close is None or close.empty:
        return []
    c = close.dropna()
    start = c.index.max() - pd.DateOffset(months=months)
    c = c[c.index >= start]
    if len(c) < 5:
        return []
    eps, peak, peak_d, in_ep, cur = [], c.iloc[0], c.index[0], False, None
    for d, v in c.items():
        if v >= peak:
            if in_ep:
                cur['recover_date'] = d
                cur['days_to_recover'] = (d - cur['trough_date']).days
                eps.append(cur)
                in_ep, cur = False, None
            peak, peak_d = v, d
            continue
        dd = (v / peak - 1) * 100
        if not in_ep and dd <= -thresh:
            in_ep = True
            cur = dict(peak_date=peak_d, peak=float(peak), trough_date=d, trough=float(v),
                       depth=dd, recover_date=None, days_to_recover=None)
        elif in_ep and v < cur['trough']:
            cur.update(trough_date=d, trough=float(v), depth=dd)
    if in_ep:
        eps.append(cur)
    return eps


def drawdown_series(close: pd.Series) -> pd.Series:
    c = close.dropna()
    return (c / c.cummax() - 1) * 100


# ── 3) 이익 가속 신호 이력 ────────────────────────────────────────
def accel_history(sym: str, path: str | None = None):
    """leaders_accel.json 의 주차별 신호에서 이 종목만. US 전용 규칙이다."""
    p = path or os.path.join(BASE, 'results', 'leaders_accel.json')
    try:
        d = json.load(open(p, encoding='utf-8'))
    except Exception:
        return None
    rows = []
    for wk, lst in (d.get('weeks') or {}).items():
        for r in lst:
            if r.get('sym') == sym:
                rows.append({'주차': wk, '회차': r.get('n'), '그주상승': r.get('up'),
                             '종가': r.get('close'), '매출가속': r.get('rva'), '이익가속': r.get('oia'),
                             '이후13주': r.get('f13'), '이후52주': r.get('f52')})
    rows.sort(key=lambda x: x['주차'], reverse=True)
    return dict(rows=rows, signal_week=d.get('signal_week'), generated=d.get('generated'),
                in_universe=None)


# ── 4) 동종업계 ───────────────────────────────────────────────────
def peer_candidates(sym: str, is_kr: bool, n: int = 4):
    """같은 업종(KR: 표준산업분류 / US: SEC SIC) 안에서 시총이 가장 가까운 n 종목."""
    try:
        if is_kr:
            sec = json.load(open(os.path.join(BASE, 'data', 'sectors.json'), encoding='utf-8'))
            lst = pd.read_csv(os.path.join(BASE, 'data', 'krx_listing_last.csv'), dtype={'Code': str})
            ind = sec.get(sym)
            if not ind:
                return None, []
            same = [k for k, v in sec.items() if v == ind and k != sym]
            u = lst[lst.Code.isin(same + [sym])][['Code', 'Name', 'Marcap']]
            u.columns = ['sym', 'name', 'mcap']
        else:
            dom = pd.read_csv(os.path.join(BASE, 'data', 'us_domicile.csv'))
            cap = pd.read_csv(os.path.join(BASE, 'data', 'us_marketcap.csv'))
            row = dom[dom.sym == sym]
            if row.empty or pd.isna(row.sic.iloc[0]):
                return None, []
            sic = row.sic.iloc[0]
            ind = row.sic_desc.iloc[0]
            same = dom[(dom.sic == sic)].sym.tolist()
            u = cap[cap.Symbol.isin(same)][['Symbol', 'Name', 'marketcap']]
            u.columns = ['sym', 'name', 'mcap']
        me = u[u.sym == sym]
        if me.empty:
            return ind, u[u.sym != sym].sort_values('mcap', ascending=False).head(n).to_dict('records')
        m0 = float(me.mcap.iloc[0])
        o = u[u.sym != sym].copy()
        o['gap'] = (np.log(o.mcap.clip(lower=1)) - np.log(max(m0, 1))).abs()
        return ind, o.sort_values('gap').head(n).to_dict('records')
    except Exception:
        return None, []


def peer_metrics(mcap: float, q: pd.DataFrame) -> dict:
    """시총과 분기 재무로 PER·PSR·매출성장·영업이익률(TTM)."""
    t = ttm(q).dropna(subset=['revenue'])
    if t.empty:
        return {}
    last = t.iloc[-1]
    prev = t[t.index <= t.index[-1] - pd.DateOffset(months=11)]
    g = None
    if not prev.empty and prev.revenue.iloc[-1] and prev.revenue.iloc[-1] > 0:
        g = (last.revenue / prev.revenue.iloc[-1] - 1) * 100
    ni, rev, op = last.get('net_income'), last.get('revenue'), last.get('op_income')
    return {'PER': (mcap / ni) if ni and ni > 0 else None,
            'PSR': (mcap / rev) if rev and rev > 0 else None,
            '매출성장': g,
            '영업이익률': (op / rev * 100) if op is not None and pd.notna(op) and rev else None,
            '기준분기': str(t.index[-1].date())}
