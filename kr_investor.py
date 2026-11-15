# -*- coding: utf-8 -*-
"""한국 종목 외국인·기관 순매매 (2026-11-16 · 종목 분석 수급 탭) — 네이버 금융 '외국인·기관 순매매' 페이지.

반환 DataFrame(최근 → 과거 아님, 날짜 오름차순): 날짜·종가·기관(주)·외국인(주)·외국인보유율(%)
금액(억원) = 순매매 주식수 × 그날 종가 ÷ 1e8 (근사 — 네이버 표는 주식수만 준다).
해외 서버에서 닿는 경로(네이버). 실패는 None — 화면은 '자료 없음'으로 정직하게.
"""
from __future__ import annotations

import io

import pandas as pd
import requests

URL = 'https://finance.naver.com/item/frgn.naver'
UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
      'Referer': 'https://finance.naver.com/'}


def _num(x):
    try:
        return float(str(x).replace(',', '').replace('%', '').replace('+', '').strip())
    except Exception:
        return None


def parse(html: str) -> pd.DataFrame:
    tbs = pd.read_html(io.StringIO(html))
    for t in tbs:
        cols = [' '.join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
        if any('외국인' in c for c in cols) and any('기관' in c for c in cols) and any('날짜' in c for c in cols):
            t.columns = cols
            c_d = next(c for c in cols if '날짜' in c)
            c_p = next(c for c in cols if '종가' in c)
            c_i = next(c for c in cols if '기관' in c)
            c_f = next(c for c in cols if '외국인' in c and '순매매' in c) if any('외국인' in c and '순매매' in c for c in cols) \
                else next(c for c in cols if '외국인' in c)
            c_r = next((c for c in cols if '보유율' in c), None)
            out = pd.DataFrame({'날짜': pd.to_datetime(t[c_d], format='%Y.%m.%d', errors='coerce'),
                                '종가': t[c_p].map(_num), '기관': t[c_i].map(_num), '외국인': t[c_f].map(_num),
                                '외국인보유율': t[c_r].map(_num) if c_r else None})
            return out.dropna(subset=['날짜', '종가']).sort_values('날짜').reset_index(drop=True)
    return pd.DataFrame()


def fetch(code: str, pages: int = 3, timeout: int = 8) -> pd.DataFrame | None:
    """최근 약 60거래일(페이지당 20일)."""
    fr = []
    try:
        for p in range(1, pages + 1):
            r = requests.get(URL, params={'code': str(code).zfill(6), 'page': p}, headers=UA, timeout=timeout)
            r.raise_for_status()
            r.encoding = 'euc-kr'
            d = parse(r.text)
            if d.empty:
                break
            fr.append(d)
    except Exception:
        if not fr:
            return None
    if not fr:
        return None
    return pd.concat(fr).drop_duplicates('날짜').sort_values('날짜').reset_index(drop=True)


def summary(df: pd.DataFrame | None, n: int = 20) -> dict | None:
    """최근 n일 외국인·기관 순매매 금액(억원 근사)·보유율 변화."""
    if df is None or df.empty:
        return None
    t = df.tail(n)
    amt = lambda c: float((t[c].fillna(0) * t['종가']).sum() / 1e8)
    hr = df['외국인보유율'].dropna() if '외국인보유율' in df else pd.Series(dtype=float)
    return {'n': len(t), 'frgn': amt('외국인'), 'inst': amt('기관'),
            'hold_now': float(hr.iloc[-1]) if len(hr) else None,
            'hold_chg': float(hr.iloc[-1] - hr.iloc[-min(len(hr), n)]) if len(hr) >= 2 else None,
            'hold_series': [round(float(x), 2) for x in hr.tail(60)],
            'asof': str(df['날짜'].iloc[-1].date())}
