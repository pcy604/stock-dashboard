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
def multiple_band(close: pd.Series, shares: float, q: pd.DataFrame, years: int | None = 5):
    """월말 시총(종가×현재 주식수) ÷ 그 시점까지 **공시된** TTM 값.

    반환: {'main': 판단에 쓰는 밴드, 'pe'·'ps'·'pb': 각 밴드(없으면 키 없음), 'start'·'end': 표본 기간}
      각 밴드 = {'kind','series','pct':{10,25,50,75,90},'now','rank'(현재 백분위),'implied','why',...}
    · main: 최근 TTM 순이익 흑자면 P/E, 적자면 P/S(적자 구간의 P/E 는 뜻이 없다).
    · 2026-10-21 사용자 요청: 흑자 종목도 P/S·P/B 를 없애지 않고 셋 다 보여준다.
    · years=None → 가진 데이터 전부. 공시 시차 45일(분기말 직후엔 아직 모르는 숫자를 쓰지 않는다).
    """
    if close is None or close.empty or not shares or q.empty:
        return None
    t = ttm(q)
    known = t.copy()
    known.index = known.index + pd.Timedelta(days=45)      # 공시 시차
    m = close.resample('ME').last().dropna()
    if years:
        m = m[m.index >= m.index.max() - pd.DateOffset(years=years)]
    f = known.reindex(m.index, method='ffill')
    mcap = m * shares
    last = t.dropna(how='all').iloc[-1] if not t.dropna(how='all').empty else None
    if last is None:
        return None
    out = {}
    ni_ok = last.get('net_income') is not None and pd.notna(last.get('net_income')) and last['net_income'] > 0
    rv_ok = pd.notna(last.get('revenue')) and (last.get('revenue') or 0) > 0
    if ni_ok and 'net_income' in f:
        b = _band(mcap / f['net_income'].where(f['net_income'] > 0), 'P/E', '최근 TTM 순이익 흑자', m, shares, f, 'net_income')
        if b:
            out['pe'] = b
    if rv_ok and 'revenue' in f:
        b = _band(mcap / f['revenue'].where(f['revenue'] > 0), 'P/S',
                  '매출 기준' if ni_ok else '최근 TTM 순이익 적자 → P/E 대신 P/S', m, shares, f, 'revenue')
        if b:
            out['ps'] = b
    if 'equity' in f and f['equity'].notna().sum() >= 8:
        b = _band(mcap / f['equity'].where(f['equity'] > 0), 'P/B', '자본(잔액) 기준', m, shares, f, 'equity')
        if b:
            out['pb'] = b
    main = out.get('pe') if ni_ok else out.get('ps')
    if not main:
        return out or None
    out['main'] = main
    ok = [x['series'] for x in (out.get('pe'), out.get('ps'), out.get('pb')) if x]
    out['start'] = min(x.index.min() for x in ok)
    out['end'] = max(x.index.max() for x in ok)
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
    # 2026-10-21 — PBR·ROE 추가. 자본은 잔액이라 TTM 이 아니라 '마지막으로 공시된' 분기말 값.
    #   자본잠식(≤0)이면 PBR·ROE 둘 다 '-'(음수 배수는 싸 보이는 착시).
    eq = None
    if 'equity' in q:
        e = pd.to_numeric(q['equity'], errors='coerce').dropna()
        e = e[e.index <= t.index[-1]]
        eq = float(e.iloc[-1]) if len(e) else None
    ok_eq = eq is not None and eq > 0
    return {'PER': (mcap / ni) if ni and ni > 0 else None,
            'PBR': (mcap / eq) if ok_eq else None,
            'ROE': (ni / eq * 100) if ok_eq and ni is not None and pd.notna(ni) else None,
            'PSR': (mcap / rev) if rev and rev > 0 else None,
            '매출성장': g,
            '영업이익률': (op / rev * 100) if op is not None and pd.notna(op) and rev else None,
            '기준분기': str(t.index[-1].date())}


# ── 5) 추세 판정 — 미너비니 Trend Template (2026-10-21) ─────────────
def trend_template(close: pd.Series, high: pd.Series | None = None, low: pd.Series | None = None) -> dict:
    """'고점 대비 −20%' 는 **보유 중 청산선**이지 추세 판정이 아니다. 저점에서 3배 오른 종목을
    '추세 이탈'이라 부르면 뜻이 뒤집힌다(2026-10-21 삼아알미늄). 추세는 업계 표준 하나로 잰다 —
    마크 미너비니 Trend Template 8조건(오닐 계열 주도주 선별에 쓰는 기준):
      ① 주가 > 150일선·200일선 ② 150일선 > 200일선 ③ 200일선이 1개월 전보다 위(상승 중)
      ④ 50일선 > 150일선·200일선 ⑤ 주가 > 50일선 ⑥ 52주 저점 대비 +30% 이상
      ⑦ 52주 고점 대비 −25% 이내 ⑧ (RS 상위 30%) — 여기선 RS 대신 '1년 수익률 > 0' 으로 대체
    반환: {'n': 충족 수, 'of': 8, 'items': [(이름, 통과?, 설명)], 'state': 문장, 'tone',
           'high_date', 'weeks_since_high', 'from_low', 'from_high'}"""
    c = close.dropna()
    if len(c) < 210:
        return {'n': None, 'of': 8, 'items': [], 'state': '표본 부족(200거래일 미만)', 'tone': 'na'}
    h = (high if high is not None else c).dropna().reindex(c.index).fillna(c)
    l = (low if low is not None else c).dropna().reindex(c.index).fillna(c)
    p = float(c.iloc[-1])
    m50, m150, m200 = (float(c.rolling(n).mean().iloc[-1]) for n in (50, 150, 200))
    m200_1m = float(c.rolling(200).mean().iloc[-22])
    h52, l52 = h.tail(252), l.tail(252)
    hi, lo = float(h52.max()), float(l52.min())
    hi_d = h52.idxmax()
    fl, fh = (p / lo - 1) * 100, (p / hi - 1) * 100
    r1 = (p / float(c.iloc[-253]) - 1) * 100 if len(c) > 252 else None
    items = [('주가 > 150·200일선', p > m150 and p > m200, f"150일선 {(p/m150-1)*100:+.0f}% · 200일선 {(p/m200-1)*100:+.0f}%"),
             ('150일선 > 200일선', m150 > m200, f"{(m150/m200-1)*100:+.1f}%"),
             ('200일선 상승 중', m200 > m200_1m, f"1개월 새 {(m200/m200_1m-1)*100:+.1f}%"),
             ('50일선 > 150·200일선', m50 > m150 and m50 > m200, f"50일선/150일선 {(m50/m150-1)*100:+.1f}%"),
             ('주가 > 50일선', p > m50, f"{(p/m50-1)*100:+.1f}%"),
             ('52주 저점 대비 +30% 이상', fl >= 30, f"{fl:+.0f}%"),
             ('52주 고점 대비 −25% 이내', fh >= -25, f"{fh:+.0f}%"),
             ('1년 수익률 > 0 (RS 대용)', (r1 or 0) > 0, f"{r1:+.0f}%" if r1 is not None else '데이터 없음')]
    n = sum(1 for _, ok, _ in items if ok)
    if n == 8:
        state, tone = '상승 추세', 'good'
    elif n >= 6:
        state, tone = '상승 추세 · 일부 이탈', 'mid'
    elif n >= 4:
        state, tone = '추세 약화', 'mid'
    else:
        state, tone = '하락·바닥 국면', 'bad'
    return {'n': n, 'of': 8, 'items': items, 'state': state, 'tone': tone,
            'high_date': pd.Timestamp(hi_d), 'weeks_since_high': int((c.index[-1] - pd.Timestamp(hi_d)).days // 7),
            'from_low': fl, 'from_high': fh}


# ── 6) 분기 이익 추이 — 적자 축소·흑자전환까지 (2026-10-21, KR 포함) ─────
def earnings_trend(rows: list[dict], key: str = 'op_income') -> dict:
    """분기 영업이익(3개월치) 추이로 상태를 판정한다. 같은 분기 전년 대비(YoY)로만 본다 — 계절성.
    · 적자 → 흑자 = '흑자전환'(가장 강한 신호) · 적자 폭이 YoY 로 줄면 '적자 축소'(개선이지 가속은 아니다)
    · 흑자 → 적자 = '적자전환' · 적자 폭이 커지면 '적자 확대'
    · 흑자 → 흑자: YoY 성장률이 직전 분기보다 커졌으면 '이익 가속', 플러스면 '이익 증가', 아니면 '이익 감소'
    적자 기저의 성장률(%)은 뜻이 없어서 계산하지 않는다(−10 → +5 를 '+150%'라 부르지 않는다).
    반환: {'state','tone','detail','rows':[{분기, 영업이익, YoY(%), 매출YoY(%)}] 최신순, 'streak'}"""
    q = quarterly_frame(rows)
    if q.empty or key not in q or q[key].notna().sum() < 5:
        return {'state': '데이터 부족', 'tone': 'na', 'detail': '분기 손익 5개 미만', 'rows': []}
    q = q.sort_index()
    v = q[key]
    rv = q.get('revenue')
    yo = v.shift(4)
    # 4분기 전이 정확히 1년 전인지(분기 결손 방지)
    span = pd.Series(q.index, index=q.index).diff(4).dt.days
    valid = span.between(350, 380)

    def g(a, b):
        if pd.isna(a) or pd.isna(b) or b <= 0 or a <= 0:
            return None
        return (a / b - 1) * 100

    tab = []
    for d in q.index[::-1][:8]:
        a, b = v.get(d), yo.get(d)
        ok = bool(valid.get(d))
        tab.append({'분기': f"{d.year}.{(d.month - 1) // 3 + 1}Q", '_d': d, 'op': a,
                    'yoy': g(a, b) if ok else None, 'prev': b if ok else None,
                    'rev_yoy': g(rv.get(d), rv.shift(4).get(d)) if (rv is not None and ok) else None})
    if not tab or tab[0]['op'] is None or pd.isna(tab[0]['op']) or tab[0]['prev'] is None:
        return {'state': '판정 불가', 'tone': 'na', 'detail': '1년 전 같은 분기 없음', 'rows': tab}
    a, b = tab[0]['op'], tab[0]['prev']
    if a > 0 and b <= 0:
        state, tone = '흑자전환', 'good'
    elif a <= 0 and b > 0:
        state, tone = '적자전환', 'bad'
    elif a <= 0 and b <= 0:
        state, tone = ('적자 축소', 'mid') if a > b else ('적자 확대', 'bad')
    else:
        g0, g1 = tab[0]['yoy'], (tab[1]['yoy'] if len(tab) > 1 else None)
        if g0 is not None and g0 > 0 and g1 is not None and g0 > g1:
            state, tone = '이익 가속', 'good'
        elif g0 is not None and g0 > 0:
            state, tone = '이익 증가', 'good' if g0 >= 25 else 'mid'
        else:
            state, tone = '이익 감소', 'bad'
    # 연속 개선 분기 수(YoY 로 영업이익이 늘어난 분기 — 적자 축소 포함)
    streak = 0
    for r in tab:
        if r['prev'] is None or r['op'] is None or pd.isna(r['op']) or not (r['op'] > r['prev']):
            break
        streak += 1
    return {'state': state, 'tone': tone, 'rows': tab, 'streak': streak, 'last': tab[0]}
