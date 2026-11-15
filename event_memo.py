# -*- coding: utf-8 -*-
"""차트 구간 메모 (2026-11-16, P3) — 대세 상승·하락 구간마다 '그동안 무슨 일이 있었나'를 사실로만 요약.

AI 문장 생성 없음 — 같은 기간 지수 수익률 · 실적 발표 서프라이즈 · 주요 공시(8-K 항목) 집계.
원천: 구간 = cycle_compare.swing_rows(차트 바탕색과 같은 꼭짓점 기준) · 실적 = yfinance earnings_dates(최근 약 3년) ·
공시 = SEC submissions items(미국만). 자료가 없는 부분은 '자료 없음'으로 적는다(채우지 않는다).
"""
from __future__ import annotations

import pandas as pd

ITEM_NAME = {'1.01': '주요 계약', '1.02': '계약 해지', '1.03': '파산·회생', '2.01': '인수·매각', '2.03': '차입',
             '2.05': '구조조정', '2.06': '자산 손상', '3.02': '지분 발행', '4.02': '재무제표 정정',
             '5.02': '경영진 변동', '7.01': '공정공시', '8.01': '기타 주요 사항'}
SKIP = {'2.02', '9.01', '5.07', '7.01'}          # 실적 보도자료·첨부·주총 결과·공정공시는 집계에서 뺀다(따로 셈)


def _ts(x):
    t = pd.Timestamp(x)
    return t.tz_localize(None) if t.tzinfo else t


def _ret(s: pd.Series, a, b):
    s = s.dropna()
    try:
        va, vb = s.loc[:a].iloc[-1], s.loc[:b].iloc[-1]
        return (vb / va - 1) * 100 if va else None
    except Exception:
        return None


def build(close: pd.Series, rows: pd.DataFrame, earn: pd.DataFrame | None = None,
          index_close: pd.Series | None = None, filings: list[dict] | None = None,
          index_name: str = '지수', since=None) -> list[dict]:
    """rows = swing_rows 결과(라벨·시작일·종료일). 반환 [{no, label, start, end, ret, days, mkt, memo}] — since 이후 겹치는 구간만."""
    c = pd.to_numeric(close, errors='coerce').dropna()
    c.index = pd.to_datetime(c.index).tz_localize(None) if getattr(pd.to_datetime(c.index), 'tz', None) else pd.to_datetime(c.index)
    ic = None
    if index_close is not None and len(index_close):
        ic = pd.to_numeric(index_close, errors='coerce').dropna()
        ic.index = pd.to_datetime(ic.index).tz_localize(None) if getattr(pd.to_datetime(ic.index), 'tz', None) else pd.to_datetime(ic.index)
    ed = None
    if earn is not None and len(earn):
        e = earn.copy()
        dc = next((k for k in e.columns if 'date' in k.lower()), e.columns[0])
        e['_d'] = pd.to_datetime(e[dc], errors='coerce', utc=True).dt.tz_localize(None)
        sc = next((k for k in e.columns if 'surprise' in k.lower()), None)
        e['_s'] = pd.to_numeric(e[sc], errors='coerce') if sc else None
        ed = e.dropna(subset=['_d'])
        ed = ed[ed['_s'].notna()] if sc else ed.iloc[0:0]
    fl = []
    for f in filings or []:
        try:
            fl.append((_ts(f['date']), [i.strip() for i in str(f.get('items') or '').split(',') if i.strip()]))
        except Exception:
            pass
    e_lo = ed['_d'].min() if ed is not None and len(ed) else None
    out = []
    for r in rows.to_dict('records'):
        a, b = _ts(r['시작일']), _ts(r['종료일'])
        if since is not None and b < _ts(since):
            continue
        ret = _ret(c, a, b)
        if ret is None:
            continue
        days = int(((c.index >= a) & (c.index <= b)).sum())
        mkt = _ret(ic, a, b) if ic is not None and len(ic) and ic.index[0] <= a else None
        parts = [f"{index_name} {mkt:+.0f}%" if mkt is not None else f"{index_name} 자료 없음"]
        if ed is not None and e_lo is not None and b >= e_lo:
            w = ed[(ed['_d'] >= a) & (ed['_d'] <= b)]
            if len(w):
                beat = int((w['_s'] > 0).sum())
                parts.append(f"실적 {len(w)}회 중 예상 상회 {beat}회(평균 서프라이즈 {w['_s'].mean():+.0f}%)")
            else:
                parts.append('실적 발표 없음')
        else:
            parts.append('실적 자료 없음(약 3년 이전)')
        if fl:
            cnt = {}
            for d, its in fl:
                if a <= d <= b:
                    for i in its:
                        if i in ITEM_NAME and i not in SKIP:
                            cnt[ITEM_NAME[i]] = cnt.get(ITEM_NAME[i], 0) + 1
            if cnt:
                parts.append('공시 ' + ' · '.join(f"{k} {v}" for k, v in sorted(cnt.items(), key=lambda x: -x[1])[:3]))
        out.append({'label': str(r['라벨']), 'start': a.date(), 'end': b.date(), 'ret': ret, 'days': days,
                    'mkt': mkt, 'memo': ' · '.join(parts)})
    for i, o in enumerate(out, 1):
        o['no'] = i
    return out
