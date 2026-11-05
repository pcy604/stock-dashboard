# -*- coding: utf-8 -*-
"""📈 사이클 비교 엔진 (2026-11-06, 차니 요구 — 반도체처럼 오르내림이 반복되는 종목에서
"이번 사이클은 저번과 어떻게 달랐나"를 보고 싶다는 요청)

설계 원칙: 고점·저점을 기계적으로 찾지 않는다. 반도체는 메모리·파운드리·장비 사이클이
서로 안 맞물려 규칙 하나로 맞히면 종목마다 다른 걸 잘못 집는다. 대신 **사용자가 차트를
보고 직접 구간(시작일·종료일)을 정하면**, 이 모듈은 그 구간을 시작일=0으로 맞춰(정규화)
겹쳐 보여 주고, 방향(상승/하락)별 기간·수익률의 평균·중앙값만 정직하게 집계한다.
"""
import numpy as np
import pandas as pd

import price_store


def load_close(sym: str, market: str):
    """주봉 종가 Series(인덱스=날짜). 가격이 없으면 None."""
    df = price_store.get(sym, market)
    if df is None or not len(df):
        return None
    return df['Close'].dropna()


def build_segment(close: pd.Series, label: str, start, end):
    """구간 하나 → dict(라벨·시작·종료·기간(주)·수익률(%)·방향·정규화곡선) — 구간이 짧거나
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
    norm.index = pd.RangeIndex(len(norm))           # x = 시작일로부터 경과 주
    ret = float(norm.iloc[-1])
    return dict(label=str(label) or '구간', start=seg.index[0].date(), end=seg.index[-1].date(),
                weeks=len(seg) - 1, ret=round(ret, 1), direction='상승' if ret >= 0 else '하락', series=norm)


def summarize(segments: list[dict]) -> pd.DataFrame:
    """구간 리스트 → 방향별(상승/하락) 구간수·평균·중앙값 기간(주)·수익률(%) 표."""
    rows = []
    for d in ('상승', '하락'):
        sub = [s for s in segments if s['direction'] == d]
        if not sub:
            continue
        w = np.array([s['weeks'] for s in sub], float)
        r = np.array([s['ret'] for s in sub], float)
        rows.append({'방향': d, '구간수': len(sub),
                      '평균 기간(주)': round(float(w.mean()), 1), '중앙 기간(주)': round(float(np.median(w)), 1),
                      '평균 수익률(%)': round(float(r.mean()), 1), '중앙 수익률(%)': round(float(np.median(r)), 1)})
    return pd.DataFrame(rows)


def detail_table(segments: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{'라벨': s['label'], '시작': s['start'], '종료': s['end'],
                          '기간(주)': s['weeks'], '수익률(%)': s['ret'], '방향': s['direction']}
                         for s in segments])
