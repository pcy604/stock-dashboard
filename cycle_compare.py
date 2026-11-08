# -*- coding: utf-8 -*-
"""📈 사이클 비교 엔진 (2026-11-06, 차니 요구 — 반도체처럼 오르내림이 반복되는 종목에서
"이번 사이클은 저번과 어떻게 달랐나"를 보고 싶다는 요청)

설계 원칙: 고점·저점을 기계적으로 찾지 않는다. 반도체는 메모리·파운드리·장비 사이클이
서로 안 맞물려 규칙 하나로 맞히면 종목마다 다른 걸 잘못 집는다. 대신 **사용자가 차트를
보고 직접 구간(시작일·종료일)을 정하면**, 이 모듈은 그 구간을 시작일=0으로 맞춰(정규화)
겹쳐 보여 주고, 방향(상승/하락)별 기간·수익률의 평균·중앙값만 정직하게 집계한다.

가격 소스는 daily_store(FDR 캐시)다. price_store(주봉 전용)는 미국만 담고 있고,
배포 환경엔 그 테이블 자체가 없을 수도 있어(2026-11-07, 배포에서 실제로 'no such
table: prices' 발생) 쓰지 않는다 — daily_store는 한국·미국 둘 다, 그때그때 받는다.
"""
import numpy as np
import pandas as pd

import daily_store
import stock_extras as _sx     # 종목분석 탭의 '낙폭 회차'와 같은 정의(drawdown_episodes) — 여기서 새로 만들지 않는다


def load_close(sym: str, market: str, start: str = '2000-01-01', end: str = None):
    """일봉 종가 Series(인덱스=날짜). 가격이 없으면 None."""
    df = daily_store.get(sym, market, start, end)
    if df is None or not len(df):
        return None
    return df['Close'].dropna()


def build_segment(close: pd.Series, label: str, start, end):
    """구간 하나 → dict(라벨·시작·종료·기간(일)·수익률(%)·방향·정규화곡선) — 구간이 짧거나
    범위 밖이면 None(화면에서 조용히 버리지 말고 '건너뜀'으로 보여 줄 것)."""
    try:
        start, end = pd.Timestamp(start), pd.Timestamp(end)
    except Exception:
        return None
    if pd.isna(start) or pd.isna(end) or end <= start:
        return None
    seg = close.loc[(close.index >= start) & (close.index <= end)]
    if len(seg) < 2:
        return None
    base = float(seg.iloc[0])
    if base <= 0:
        return None
    norm = (seg / base - 1) * 100
    norm.index = pd.RangeIndex(len(norm))           # x = 시작일로부터 경과 거래일
    ret = float(norm.iloc[-1])
    return dict(label=str(label) or '구간', start=seg.index[0].date(), end=seg.index[-1].date(),
                days=len(seg) - 1, ret=round(ret, 1), direction='상승' if ret >= 0 else '하락', series=norm)


def auto_rows(close: pd.Series, months: int, thresh: float) -> pd.DataFrame:
    """수동 구간 입력이 귀찮다는 요청(2026-11-07) — 종목분석 탭 '낙폭 회차'(stock_extras.drawdown_episodes)와
    똑같은 정의로 'MDD thresh% 이상' 회차를 찾아 하락(고점→저점)·회복(저점→고점) 두 구간씩 표에 미리 채운다.
    months<=0 이면 전체 기간. 회복 전(진행 중)이면 종료일을 마지막 가격일로 두고 라벨에 표시."""
    if close is None or not len(close):
        return pd.DataFrame(columns=['라벨', '시작일', '종료일'])
    eps = _sx.drawdown_episodes(close, months if months and months > 0 else 1200, thresh)
    last = close.dropna().index.max()
    rows = []
    for i, e in enumerate(eps, 1):
        rows.append({'라벨': f"하락 {i} ({e['depth']:.0f}%)", '시작일': pd.Timestamp(e['peak_date']).date(),
                     '종료일': pd.Timestamp(e['trough_date']).date()})
        rec = e.get('recover_date')
        rows.append({'라벨': f"회복 {i}" + ('' if rec else ' (진행중)'),
                     '시작일': pd.Timestamp(e['trough_date']).date(),
                     '종료일': (pd.Timestamp(rec) if rec else last).date()})
    return pd.DataFrame(rows, columns=['라벨', '시작일', '종료일'])


def summarize(segments: list[dict]) -> pd.DataFrame:
    """구간 리스트 → 방향별(상승/하락) 구간수·평균·중앙값 기간(거래일)·수익률(%) 표. 진행 중 구간은 빼고 센다."""
    rows = []
    for d in ('상승', '하락'):
        sub = [s for s in segments if s['direction'] == d and not s.get('live')]
        if not sub:
            continue
        w = np.array([s['days'] for s in sub], float)
        r = np.array([s['ret'] for s in sub], float)
        rows.append({'방향': d, '구간수': len(sub),
                      '평균 기간(거래일)': round(float(w.mean()), 1), '중앙 기간(거래일)': round(float(np.median(w)), 1),
                      '평균 수익률(%)': round(float(r.mean()), 1), '중앙 수익률(%)': round(float(np.median(r)), 1),
                      '최장(거래일)': int(w.max()), '가장 큰 폭(%)': round(float(r.max() if d == '상승' else r.min()), 1)})
    return pd.DataFrame(rows)


def detail_table(segments: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{'라벨': s['label'], '시작': s['start'], '종료': s['end'],
                          '기간(거래일)': s['days'], '수익률(%)': s['ret'], '방향': s['direction'] + (' · 진행 중' if s.get('live') else '')}
                         for s in segments])


# ── 2026-11-08 고도화 (차니 "아주 맘에 든다, 좀만 더") ─────────────────────────────
# ① 자동 구간을 '낙폭 회차(저점→옛 고점 회복)'가 아니라 **지그재그 스윙**으로: 저점→다음 고점(상승) · 고점→다음 저점(하락).
#    옛 방식은 회복 구간이 '옛 고점을 되찾는 순간'에서 끊겨 실제 상승 사이클 길이·크기를 잘랐다.
# ② 마지막 꼭짓점 → 오늘 = 진행 중 구간. 과거 같은 방향 구간 분포 안에서 지금이 어디쯤인지(백분위)를 잰다.

def zigzag(close: pd.Series, pct: float):
    """종가 지그재그 — pct% 이상 되돌림이 나야 꼭짓점으로 인정. 반환 [(날짜, 'H'|'L', 가격)] 오래된 순.
    마지막 꼭짓점 뒤 진행 방향은 last_dir 로(1 상승 중 · -1 하락 중 · 0 판정 전)."""
    c = close.dropna()
    v, ix = c.values.astype(float), c.index
    th = pct / 100.0
    if len(v) < 3:
        return [], 0
    piv, trend = [], 0
    hi = lo = 0
    for i in range(1, len(v)):
        if trend == 0:
            if v[i] > v[hi]:
                hi = i
            if v[i] < v[lo]:
                lo = i
            if v[i] >= v[lo] * (1 + th) and lo < i:
                piv.append(lo); trend = 1; hi = i
            elif v[i] <= v[hi] * (1 - th) and hi < i:
                piv.append(hi); trend = -1; lo = i
        elif trend == 1:
            if v[i] > v[hi]:
                hi = i
            elif v[i] <= v[hi] * (1 - th):
                piv.append(hi); trend = -1; lo = i
        else:
            if v[i] < v[lo]:
                lo = i
            elif v[i] >= v[lo] * (1 + th):
                piv.append(lo); trend = 1; hi = i
    # 진행 중 방향의 극값까지는 아직 확정이 아니다 — 마지막 확정 꼭짓점까지만 꼭짓점으로 돌려준다
    out = []
    for k, i in enumerate(piv):
        nxt = piv[k + 1] if k + 1 < len(piv) else None
        typ = 'L' if (nxt is not None and v[nxt] > v[i]) or (nxt is None and trend == 1) else 'H'
        out.append((ix[i], typ, float(v[i])))
    return out, trend


def swing_rows(close: pd.Series, pct: float) -> pd.DataFrame:
    """지그재그 꼭짓점 사이를 구간 표로 — 마지막 꼭짓점 → 마지막 가격일은 '진행 중'."""
    piv, trend = zigzag(close, pct)
    rows, nu, nd = [], 0, 0
    last = close.dropna().index.max()
    for k in range(len(piv)):
        d0, t0, p0 = piv[k]
        if k + 1 < len(piv):
            d1, _, p1 = piv[k + 1]
            live = False
        else:
            d1, p1, live = last, float(close.dropna().iloc[-1]), True
            if d1 <= d0:
                break
        up = t0 == 'L'
        if up:
            nu += 1
        else:
            nd += 1
        lab = (f"상승 {nu}" if up else f"하락 {nd}") + (' (진행 중)' if live else '')
        rows.append({'라벨': lab, '시작일': pd.Timestamp(d0).date(), '종료일': pd.Timestamp(d1).date()})
    return pd.DataFrame(rows, columns=['라벨', '시작일', '종료일'])


def median_path(segments: list[dict]):
    """완료된 구간들의 경과일별 중앙 경로(구간 절반 이상이 살아 있는 날까지만)."""
    if not segments:
        return None
    L = max(len(s['series']) for s in segments)
    M = pd.DataFrame({i: s['series'].reindex(range(L)) for i, s in enumerate(segments)})
    alive = M.notna().sum(axis=1)
    med = M.median(axis=1)
    return med[alive >= max(2, (len(segments) + 1) // 2)]


def where_now(segments: list[dict], live: dict):
    """진행 중 구간이 과거 같은 방향(완료) 구간들 사이 어디쯤인가 — 기간·크기 백분위와 중앙값."""
    past = [s for s in segments if s['direction'] == live['direction'] and not s.get('live')]
    if not past:
        return None
    dd = np.array([s['days'] for s in past], float)
    rr = np.array([abs(s['ret']) for s in past], float)
    return dict(n=len(past), days_med=float(np.median(dd)), ret_med=float(np.median(rr)) * (1 if live['direction'] == '상승' else -1),
                days_pct=float((dd < live['days']).mean() * 100), ret_pct=float((rr < abs(live['ret'])).mean() * 100),
                days_max=float(dd.max()), ret_max=float(rr.max()) * (1 if live['direction'] == '상승' else -1))
