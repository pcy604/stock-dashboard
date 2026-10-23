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


# ── 6) 분기 이익 추이 — 이익 가속(미국 신호와 같은 정의) + 몇 분기 연속인지 (2026-10-21, KR 포함) ─────
MAX_OIA = 10.0          # leaders_accel.MAX_OIA 와 같은 값(매출이 사업 규모를 대표 못 하는 회사 제외)


def earnings_trend(rows: list[dict], key: str = 'op_income', is_kr: bool = False) -> dict:
    """가속의 정의는 leaders_accel(미국 진입 신호)과 **같다** — 같은 이름에 정의가 둘이면 안 된다.
      매출 성장률   rv = 매출 YoY(%)
      이익 성장     oi = (영업익_t − 영업익_t−4) ÷ |매출_t|   ← 매출로 나눠 적자에서도 정의된다(적자 축소도 측정)
      가속          Δrv > 0 AND Δoi > 0 (직전 분기보다 둘 다 빨라짐), |Δoi| ≤ 10
    한 분기 가속은 잡음(기저효과·일회성)일 수 있어 **연속 분기 수**를 같이 낸다.
      1분기 = '확인 전' · 2분기 = 가속 · 3분기+ = 미너비니 'Code 33'(3분기 연속 가속)에 해당하는 강한 가속.
      (He & Narayanamoorthy 2020: 시장은 가속이 2~3분기 이어질 함의를 늦게 반영 — 연속은 그 확인)
    ⚠️ 연속 조건이 1분기 조건보다 수익이 나은지는 아직 백테스트 안 했다 → 화면 '상태'일 뿐 신호가 아니다.
    수준 판정(같은 분기 전년 대비): 흑자전환 · 적자전환 · 적자 축소 · 적자 확대 · 이익 증가 · 이익 감소.
    기저효과: 1년 전 분기 이익이 최근 8분기 |이익| 중앙값의 25% 미만이면 성장률이 부풀려진다고 표시.
    반환: {'state','tone','level','streak','acc_8q','base_warn','rows':[최신순], 'last'}"""
    q = quarterly_frame(rows)
    if q.empty or key not in q or q[key].notna().sum() < 5:
        return {'state': '데이터 부족', 'tone': 'na', 'detail': '분기 손익 5개 미만', 'rows': [], 'streak': 0}
    q = q.sort_index()
    v, rv = q[key], q.get('revenue')
    if rv is None:
        rv = pd.Series(float('nan'), index=q.index)
    days = pd.Series(q.index, index=q.index)
    ok4 = days.diff(4).dt.days.between(350, 380)          # 4분기 전이 정확히 1년 전(결손 분기 방지)
    ok1 = days.diff(1).dt.days.between(80, 100)
    min_rev = 1.4e10 if is_kr else 1e7                     # 미국 $10M 하한과 같은 규모(약 140억원)
    rabs = rv.abs().where(rv.abs() >= min_rev)
    oi = ((v - v.shift(4)) / rabs).where(ok4)
    rg = ((rv / rv.shift(4) - 1) * 100).where(ok4 & (rv.shift(4) > 0))
    oia = (oi - oi.shift(1)).where(ok1)
    rva = (rg - rg.shift(1)).where(ok1)
    acc = (rva > 0) & (oia > 0) & (oia.abs() <= MAX_OIA)

    tab = []
    for d in q.index[::-1][:8]:
        a, b = v.get(d), (v.shift(4).get(d) if ok4.get(d) else None)
        yoy = (a / b - 1) * 100 if (b is not None and pd.notna(a) and pd.notna(b) and a > 0 and b > 0) else None
        tab.append({'분기': f"{d.year}.{(d.month - 1) // 3 + 1}Q", '_d': d, 'op': a,
                    'prev': b if (b is not None and pd.notna(b)) else None, 'yoy': yoy,
                    'rev_yoy': None if pd.isna(rg.get(d)) else float(rg.get(d)),
                    'oi_pp': None if pd.isna(oi.get(d)) else float(oi.get(d)) * 100,     # 이익 증가폭 ÷ 매출(%p)
                    'acc': bool(acc.get(d)) if pd.notna(oia.get(d)) and pd.notna(rva.get(d)) else None})
    if not tab or tab[0]['op'] is None or pd.isna(tab[0]['op']) or tab[0]['prev'] is None:
        return {'state': '판정 불가', 'tone': 'na', 'detail': '1년 전 같은 분기 없음', 'rows': tab, 'streak': 0}
    a, b = tab[0]['op'], tab[0]['prev']
    if a > 0 and b <= 0:
        level = '흑자전환'
    elif a <= 0 and b > 0:
        level = '적자전환'
    elif a <= 0 and b <= 0:
        level = '적자 축소' if a > b else '적자 확대'
    else:
        level = '이익 증가' if a > b else '이익 감소'
    streak = 0
    for r in tab:
        if r['acc'] is not True:
            break
        streak += 1
    acc_8q = sum(1 for r in tab if r['acc'] is True)
    recent = [abs(x) for x in v.dropna().tail(8)]
    base_warn = bool(recent and b is not None and abs(b) < 0.25 * float(np.median(recent)))
    if streak >= 3:
        state, tone = f'이익 가속 · {streak}분기 연속', 'good'
    elif streak == 2:
        state, tone = '이익 가속 · 2분기 연속', 'good'
    elif streak == 1:
        state, tone = '가속 1분기 · 확인 전', 'mid'
    else:
        state = {'이익 증가': '이익 증가 · 감속'}.get(level, level)
        tone = {'흑자전환': 'good', '이익 증가': 'mid', '적자 축소': 'mid'}.get(level, 'bad')
    return {'state': state, 'tone': tone, 'level': level, 'streak': streak, 'acc_8q': acc_8q,
            'base_warn': base_warn, 'rows': tab, 'last': tab[0]}


# ── 7) 실적 발표 — 분기별 실적 vs 발표 직전 컨센서스 · 다음 발표 시기 (2026-10-23) ─────
def _qend(per: str) -> pd.Timestamp:
    y, q = int(per[:4]), int(per[5])
    return pd.Period(f"{y}Q{q}", freq='Q').end_time.normalize()


def _qlabel(ts) -> str:
    ts = pd.Timestamp(ts)
    return f"{ts.year}.{(ts.month - 1) // 3 + 1}Q"


def announce_date_for(qend, events: list[dict], max_days=100):
    """분기말 뒤 max_days 안의 첫 발표. events=[{'date':'YYYY-MM-DD','kind':...}] — 잠정실적(공정공시)이 있으면 그 날짜가 우선."""
    lo, hi = pd.Timestamp(qend), pd.Timestamp(qend) + pd.Timedelta(days=max_days)
    c = [e for e in events if e.get('date') and lo < pd.Timestamp(e['date']) <= hi]
    if not c:
        return None, None
    pre = [e for e in c if e.get('kind') == '잠정실적']
    e = min(pre or c, key=lambda e: e['date'])
    return pd.Timestamp(e['date']), e.get('kind')


def earnings_quarters(qf: pd.DataFrame, events: list[dict] | None = None, cons_q: dict | None = None,
                      eps_hist: list[dict] | None = None, today=None, n=4) -> dict:
    """최근 n개 분기의 실적 vs 컨센서스 + 다음 발표 시기.
    qf: quarterly_frame(분기말 인덱스; revenue·op_income·net_income)
    events: 발표 이벤트(KR=DART 잠정실적·정기보고서, US=yfinance 발표일 → kind='발표')
    cons_q: {'2026.3Q': {'op','rev','eps','date'}} 발표 직전 컨센서스(KR 스냅샷)
    eps_hist: [{'date','est','rep'}] (US yfinance) — 발표일로 분기에 붙인다
    반환 {'rows':[최신순], 'next': {...}, 'wins','losses'}"""
    today = pd.Timestamp(today or pd.Timestamp.today().normalize())
    events = events or []
    cons_q = cons_q or {}
    eps_hist = eps_hist or []
    rows = []
    q = qf.sort_index() if qf is not None and not qf.empty else pd.DataFrame()
    for qe in list(q.index[::-1][:n]):
        per = _qlabel(qe)
        r = q.loc[qe]
        ad, kind = announce_date_for(qe, events)
        e = next((x for x in eps_hist if pd.notna(x.get('date')) and
                  pd.Timestamp(qe) < pd.Timestamp(x['date']) <= pd.Timestamp(qe) + pd.Timedelta(days=100)), None)
        if ad is None and e is not None:
            ad, kind = pd.Timestamp(e['date']), '발표'
        c = cons_q.get(per) or {}
        op, op_c = r.get('op_income'), c.get('op')
        rv, rv_c = r.get('revenue'), c.get('rev')
        gap = lambda a, b: ((a - b) / abs(b) * 100) if (a is not None and b and pd.notna(a)) else None
        row = {'분기': per, '발표일': ad, '발표 근거': kind,
               '매출': rv, '매출 컨센서스': rv_c, '매출 차이(%)': gap(rv, rv_c),
               '영업이익': op, '영업이익 컨센서스': op_c, '영업이익 차이(%)': gap(op, op_c),
               'EPS': (e or {}).get('rep'), 'EPS 컨센서스': (e or {}).get('est') if e else c.get('eps'),
               'EPS 차이(%)': None}
        if row['EPS'] is not None and row['EPS 컨센서스']:
            row['EPS 차이(%)'] = gap(row['EPS'], row['EPS 컨센서스'])
        # 승패 기준: EPS 서프라이즈가 있으면 그것, 없으면 영업이익 차이
        key = row['EPS 차이(%)'] if row['EPS 차이(%)'] is not None else row['영업이익 차이(%)']
        row['판정'] = None if key is None else ('상회' if key > 0 else '하회')
        rows.append(row)
    wins = sum(1 for r in rows if r['판정'] == '상회')
    losses = sum(1 for r in rows if r['판정'] == '하회')
    # 다음 발표: 최신 실적 분기의 다음 분기 → 전년 같은 분기 발표일 + 1년(추정)
    nxt = {}
    if not q.empty:
        nq_end = (pd.Period(q.index.max(), freq='Q') + 1).end_time.normalize()
        ly_end = (pd.Period(nq_end, freq='Q') - 4).end_time.normalize()
        ly_ad, ly_kind = announce_date_for(ly_end, events)
        if ly_ad is None:
            e = next((x for x in eps_hist if pd.notna(x.get('date')) and
                      ly_end < pd.Timestamp(x['date']) <= ly_end + pd.Timedelta(days=100)), None)
            if e:
                ly_ad, ly_kind = pd.Timestamp(e['date']), '발표'
        nxt = {'분기': _qlabel(nq_end), '전년 동기': _qlabel(ly_end), '전년 발표일': ly_ad, '전년 근거': ly_kind,
               '예상': (ly_ad + pd.DateOffset(years=1)) if ly_ad is not None else None,
               '법정 마감(KR)': nq_end + pd.Timedelta(days=90 if nq_end.month == 12 else 45)}
    return {'rows': rows, 'next': nxt, 'wins': wins, 'losses': losses}
