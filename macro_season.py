"""우라가미 4계절 — 상태 기계 정의 (2026-11-06 v2, 차니 요청: '무엇이 바뀌면 다음 계절로 가나 · 계절 안 어디쯤인가')

v1(점수 최댓값)의 문제
  · 달마다 점수 1위를 고르기만 해서 국면이 앞뒤로 튀었다(계절 '순서'가 없음).
  · 물가를 안 봐서 CPI 4% 인데도 '실적장세'였다.
  · '지금 계절의 어디쯤'과 '다음 계절까지 무엇이 남았나'를 말하지 못했다.

v2 정의 — 계절마다 공개 조건 3개. 모두 참이어야 그 계절의 조건이 '충족'된다.
  축(월말, 월간 지표는 발표 시차 1개월 반영)
    금리   Fed 기준금리 6개월 변화  ≤ −0.25%p 하락 · ≥ +0.25%p 상승 · 그 사이 횡보
    실적   산업생산 YoY            ≥ +1% 개선 · ≤ −1% 악화 · 그 사이 횡보 (삼의 법칙 0.5 발동 시 악화)
    주가   S&P500 월말 종가 > 200일선 그리고 12개월 수익 > 0 → 상승, 아니면 하락
    물가   CPI YoY ≥ 3.5%, 또는 ≥ 3.0% 이면서 3개월 전보다 +0.3%p 이상 → 과열 (긴축 압력)
  🌱 금융장세   ① 금리 하락        ② 물가 과열 아님        ③ 주가 상승
  ☀️ 실적장세   ① 실적 개선        ② 주가 상승            ③ 금리 하락 아님(인하 끝)
  🍂 역금융장세 ① 긴축(금리 상승 또는 물가 과열) ② 주가 하락 ③ 실적 악화 아님
  ❄️ 역실적장세 ① 실적 악화        ② 주가 하락            ③ 금리 상승 아님(긴축 끝)

전환 규칙
  · 순서대로 돈다: 🌱 → ☀️ → 🍂 → ❄️ → 🌱.
  · 다음 계절 조건 3개가 **2개월 연속** 충족되면 넘어간다.
  · 순서를 건너뛰는 이동(예: ☀️ → ❄️ 급락)은 그 계절 조건이 **3개월 연속** 충족될 때만.
  · 아무 조건도 안 맞으면 지금 계절에 머문다(판정이 달마다 튀지 않게).

계절 안 위치(0~100)
  = 50 × min(경과 개월 ÷ 그 계절 과거 중앙값, 1) + 50 × (다음 계절 조건 충족 수 ÷ 3)
  0~33 초입 · 34~66 중반 · 67~100 후반. 다음 계절 조건 3/3 이면 '전환 대기'(한 달 더 충족되면 확정).

이 정의는 매매 규칙이 아니다(참고 지도). 비중은 실전 판정(주봉 5주선·200일선)만 정한다.
"""
from __future__ import annotations

import os

import numpy as np
import pandas as pd

ORDER = ['FIN', 'EARN', 'RFIN', 'RERN']
NEXT = {k: ORDER[(i + 1) % 4] for i, k in enumerate(ORDER)}
CONFIRM_NEXT, CONFIRM_JUMP = 2, 3

# 임계값 — 화면 '경계선'과 같은 숫자를 쓴다
RATE_DN, RATE_UP = -0.25, 0.25
IP_UP, IP_DN = 1.0, -1.0
SAHM_ON = 0.5
CPI_HOT, CPI_WARM, CPI_RISE = 3.5, 3.0, 0.3

# 조건 이름(화면용) — (키, 설명)
COND = {
    'FIN':  [('rate_dn', '금리 하락'), ('not_hot', '물가 과열 아님'), ('px_up', '주가 상승')],
    'EARN': [('ip_up', '실적 개선'), ('px_up', '주가 상승'), ('not_rate_dn', '금리 하락 끝')],
    'RFIN': [('tight', '긴축(금리↑ 또는 물가 과열)'), ('px_dn', '주가 하락'), ('not_ip_dn', '실적 악화 아님')],
    'RERN': [('ip_dn', '실적 악화'), ('px_dn', '주가 하락'), ('not_rate_up', '긴축 끝')],
}

ROOT = os.path.dirname(os.path.abspath(__file__))
FRED_PQ = os.path.join(ROOT, 'data', 'research', 'macro_long_fred.parquet')
PX_PQ = os.path.join(ROOT, 'data', 'research', 'macro_long_px.parquet')


def _sahm(ur: pd.Series) -> pd.Series:
    import macro_flow as mf                  # 정의는 macro_flow.sahm_series 하나
    return mf.sahm_series(ur)


def load_long() -> dict:
    """커밋된 장기 시계열(macro-long 워크플로) → {fed, ip, ur, cpi: 월간, px: S&P500 일간}."""
    f = pd.read_parquet(FRED_PQ)
    f['date'] = pd.to_datetime(f['date'])
    g = {sid: d.set_index('date')['v'].astype(float).sort_index() for sid, d in f.groupby('sid')}
    px = pd.read_parquet(PX_PQ)['SPX'].dropna()
    return dict(fed=g.get('FEDFUNDS'), ip=g.get('INDPRO'), ur=g.get('UNRATE'), cpi=g.get('CPIAUCSL'), px=px)


def merge_latest(base: pd.Series | None, extra) -> pd.Series:
    """장기 파일 뒤에 더 최신 관측(화면의 FRED 실시간 [(date, v)] 또는 Series)을 붙인다."""
    b = base if base is not None else pd.Series(dtype=float)
    if extra is None or len(extra) == 0:
        return b
    e = extra if isinstance(extra, pd.Series) else pd.Series([v for _, v in extra], index=pd.to_datetime([t for t, _ in extra]))
    e = e.dropna().astype(float)
    return pd.concat([b[~b.index.isin(e.index)], e]).sort_index()


def signals(fed, ip, ur, cpi, px, lag_months: int = 1) -> pd.DataFrame:
    """월말 신호표. 월간 지표는 lag_months 만큼 밀어 '그 달 말에 알 수 있던 값'만 쓴다."""
    px = pd.to_numeric(pd.Series(px), errors='coerce').dropna()
    px = px[~px.index.duplicated(keep='last')].sort_index()
    me = px.resample('ME').last().dropna()
    ma = px.rolling(200).mean().resample('ME').last()
    mom = me / me.shift(12) - 1

    def m(s):
        if s is None or len(s) == 0:
            return pd.Series(np.nan, index=me.index)
        s = s.dropna().copy()
        s = s[~s.index.duplicated(keep='last')]
        s.index = (pd.to_datetime(s.index) + pd.DateOffset(months=lag_months)).to_period('M').to_timestamp('M')
        s = s[~s.index.duplicated(keep='last')]
        return s.reindex(me.index, method='ffill')

    f = m(fed)
    d = pd.DataFrame(index=me.index)
    d['close'] = me
    d['gap200'] = (me / ma - 1) * 100
    d['mom12'] = mom * 100
    d['fed'] = f
    d['fed6'] = f - f.shift(6)
    d['ipy'] = m((ip / ip.shift(12) - 1) * 100) if ip is not None else np.nan
    d['sahm'] = m(_sahm(ur)) if ur is not None else np.nan
    cy = (cpi / cpi.shift(12) - 1) * 100 if cpi is not None else None
    d['cpi'] = m(cy)
    d['cpi3'] = d['cpi'] - d['cpi'].shift(3)

    d['rate'] = np.where(d['fed6'] <= RATE_DN, '하락', np.where(d['fed6'] >= RATE_UP, '상승', '횡보'))
    g = np.where(d['ipy'] >= IP_UP, '개선', np.where(d['ipy'] <= IP_DN, '악화', '횡보'))
    d['growth'] = np.where(d['sahm'] >= SAHM_ON, '악화', g)
    d['px'] = np.where((me > ma) & (mom > 0), '상승', '하락')
    hot = (d['cpi'] >= CPI_HOT) | ((d['cpi'] >= CPI_WARM) & (d['cpi3'] >= CPI_RISE))
    d['infl'] = np.where(hot, '과열', np.where(d['cpi'] <= 2.5, '안정', '중립'))

    c = pd.DataFrame(index=d.index)
    c['rate_dn'] = d['rate'] == '하락'
    c['not_rate_dn'] = d['rate'] != '하락'
    c['not_rate_up'] = d['rate'] != '상승'
    c['ip_up'] = d['growth'] == '개선'
    c['ip_dn'] = d['growth'] == '악화'
    c['not_ip_dn'] = d['growth'] != '악화'
    c['px_up'] = d['px'] == '상승'
    c['px_dn'] = d['px'] == '하락'
    c['not_hot'] = d['infl'] != '과열'
    c['tight'] = (d['rate'] == '상승') | (d['infl'] == '과열')
    for k, conds in COND.items():
        d[f'n_{k}'] = sum(c[ck].astype(int) for ck, _ in conds)
    for col in c.columns:
        d[f'c_{col}'] = c[col]
    ok = d['fed6'].notna() & d['ipy'].notna() & ma.reindex(d.index).notna() & d['mom12'].notna() & d['cpi'].notna()
    return d[ok]


def run(sig: pd.DataFrame) -> pd.DataFrame:
    """상태 기계를 월별로 돌린다. 열: phase(확정 계절)·months(경과)·pending(전환 대기 계절)·streak."""
    phase, months = None, 0
    streak = {k: 0 for k in ORDER}
    rows = []
    for dt, r in sig.iterrows():
        for k in ORDER:
            streak[k] = streak[k] + 1 if r[f'n_{k}'] == 3 else 0
        new = None
        if phase is None:
            full = [k for k in ORDER if r[f'n_{k}'] == 3]
            new = full[0] if full else None
        else:
            nx = NEXT[phase]
            if streak[nx] >= CONFIRM_NEXT:
                new = nx
            else:
                jumps = [k for k in ORDER if k not in (phase, nx) and streak[k] >= CONFIRM_JUMP]
                new = jumps[0] if jumps else None
        if new is not None and new != phase:
            phase, months = new, 1
        elif phase is not None:
            months += 1
        nx = NEXT[phase] if phase else None
        rows.append(dict(date=dt, phase=phase, months=months if phase else 0,
                         next=nx, next_n=int(r[f'n_{nx}']) if nx else None,
                         pending=(nx if nx and r[f'n_{nx}'] == 3 else None)))
    out = pd.DataFrame(rows).set_index('date')
    return sig.join(out)


def spells(h: pd.DataFrame) -> pd.DataFrame:
    """완료된 계절 구간(시작·끝·개월). 마지막(진행 중) 구간은 done=False."""
    h = h[h['phase'].notna()]
    if h.empty:
        return pd.DataFrame(columns=['phase', 'start', 'end', 'months', 'done'])
    grp = (h['phase'] != h['phase'].shift()).cumsum()
    sp = h.groupby(grp).agg(phase=('phase', 'first'), start=('phase', lambda s: s.index[0]),
                            end=('phase', lambda s: s.index[-1]), months=('phase', 'size'))
    sp['done'] = True
    sp.iloc[-1, sp.columns.get_loc('done')] = False
    return sp.reset_index(drop=True)


def median_months(h: pd.DataFrame) -> dict:
    sp = spells(h)
    d = sp[sp['done']]
    return {k: (float(d.loc[d['phase'] == k, 'months'].median()) if (d['phase'] == k).any() else None) for k in ORDER}


def position(months: int, med: float | None, next_n: int | None) -> int | None:
    if med is None or next_n is None:
        return None
    return int(round(50 * min(months / med, 1.0) + 50 * next_n / 3))


def stage(pos: int | None, pending: bool) -> str:
    if pending:
        return '전환 대기'
    if pos is None:
        return '-'
    return '초입' if pos <= 33 else ('중반' if pos <= 66 else '후반')


def history(fed, ip, ur, cpi, px, lag_months: int = 1) -> pd.DataFrame:
    """월별 계절 + 위치·단계. 위치의 '중앙값'은 그 달까지 끝난 구간만 쓴다(미래 값 미사용)."""
    h = run(signals(fed, ip, ur, cpi, px, lag_months))
    if h.empty:
        return h
    sp = spells(h)
    pos, stg = [], []
    for dt, r in h.iterrows():
        if r['phase'] is None or (isinstance(r['phase'], float) and np.isnan(r['phase'])):
            pos.append(None); stg.append('-'); continue
        past = sp[(sp['end'] < dt) & (sp['phase'] == r['phase'])]
        med = float(past['months'].median()) if len(past) else None
        p = position(int(r['months']), med, r['next_n'])
        pos.append(p); stg.append(stage(p, r['pending'] is not None))
    h['pos'] = pos
    h['stage'] = stg
    return h


def forward(h: pd.DataFrame, months=(3, 6, 12)) -> pd.DataFrame:
    """계절별 '그 뒤 N개월' S&P500 가격 수익률 — 정의가 그럴듯한지 검산용(매매 근거 아님)."""
    d = h[h['phase'].notna()].copy()
    out = []
    for k in ORDER:
        x = d[d['phase'] == k]
        row = {'계절': k, '개월 수': len(x), '구간 수': int((spells(h)['phase'] == k).sum())}
        for n in months:
            fw = (h['close'].shift(-n) / h['close'] - 1).reindex(x.index) * 100
            fw = fw.dropna()
            row[f'{n}개월 평균(%)'] = round(float(fw.mean()), 1) if len(fw) else None
            row[f'{n}개월 상승(%)'] = round(float((fw > 0).mean() * 100)) if len(fw) else None
        out.append(row)
    return pd.DataFrame(out)


def now(h: pd.DataFrame) -> dict:
    """화면 카드용 — 지금 계절·위치·조건 충족표·경계선."""
    if h.empty or h['phase'].isna().all():
        return {}
    r = h.iloc[-1]
    med = median_months(h)
    ph, nx = r['phase'], r['next']
    p = position(int(r['months']), med.get(ph), r['next_n'])
    since = h.index[len(h) - int(r['months'])]

    def cond_rows(k):
        return [dict(key=ck, name=nm, ok=bool(r[f'c_{ck}'])) for ck, nm in COND[k]]

    # 경계선 — 축마다 지금 값과 다음 임계까지 거리
    lines = []
    if r['fed6'] == r['fed6']:
        lines.append(dict(axis='금리', val=f"6개월 {r['fed6']:+.2f}%p", word=r['rate'],
                          edge=f"하락 ≤ {RATE_DN:+.2f} · 상승 ≥ {RATE_UP:+.2f}",
                          dist=min(abs(r['fed6'] - RATE_DN), abs(r['fed6'] - RATE_UP))))
    if r['ipy'] == r['ipy']:
        lines.append(dict(axis='실적', val=f"산업생산 YoY {r['ipy']:+.1f}%" + (f" · 삼의 법칙 {r['sahm']:.2f}" if r['sahm'] == r['sahm'] else ''),
                          word=r['growth'], edge=f"개선 ≥ {IP_UP:+.0f}% · 악화 ≤ {IP_DN:+.0f}% · 삼의 법칙 ≥ {SAHM_ON}",
                          dist=min(abs(r['ipy'] - IP_UP), abs(r['ipy'] - IP_DN))))
    lines.append(dict(axis='주가', val=f"200일선 {r['gap200']:+.1f}% · 12개월 {r['mom12']:+.1f}%", word=r['px'],
                      edge='200일선 위 그리고 12개월 수익 +', dist=min(abs(r['gap200']), abs(r['mom12']))))
    if r['cpi'] == r['cpi']:
        lines.append(dict(axis='물가', val=f"CPI YoY {r['cpi']:.1f}% · 3개월 {r['cpi3']:+.1f}%p", word=r['infl'],
                          edge=f"과열 ≥ {CPI_HOT}% (또는 ≥ {CPI_WARM}% 이면서 3개월 +{CPI_RISE}%p)",
                          dist=abs(r['cpi'] - CPI_HOT)))
    return dict(phase=ph, next=nx, months=int(r['months']), since=f"{since:%Y-%m}", asof=f"{h.index[-1]:%Y-%m}",
                median=med.get(ph), pos=p, stage=stage(p, r['pending'] is not None),
                pending=r['pending'], next_n=int(r['next_n']),
                conds={k: cond_rows(k) for k in ORDER}, n={k: int(r[f'n_{k}']) for k in ORDER},
                lines=lines, rate=r['rate'], growth=r['growth'], px=r['px'], infl=r['infl'])


_FRED_KEYS = (('fed', 'FEDFUNDS'), ('ip', 'INDPRO'), ('ur', 'UNRATE'), ('cpi', 'CPIAUCSL'))


def current(fetch=None, px_extra=None):
    """장기 파일 + 더 최신 관측으로 계절 이력과 지금 카드. 화면·CI(verdict.build) 공용.
    fetch(series_id, n) -> [(date, v)] (실패 시 []) · px_extra = S&P500 일간 Series(Yahoo 등)."""
    L = load_long()
    if fetch is not None:
        for k, sid in _FRED_KEYS:
            try:
                L[k] = merge_latest(L[k], fetch(sid, 24))
            except Exception:
                pass
    if px_extra is not None and len(px_extra):
        L['px'] = merge_latest(L['px'], px_extra)
    h = history(**L)
    return h, now(h)
