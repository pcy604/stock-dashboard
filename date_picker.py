# -*- coding: utf-8 -*-
"""기간 고르기 — 사이트 공통 (2026-11-16 표준).

한 줄: [1년 3년 5년 10년 전체] [시작일] [종료일]. 날짜 칸은 처음부터 보인다('직접' 버튼 없음).
프리셋을 누르면 두 날짜가 그 값으로 바뀌고, 날짜를 직접 고치면 프리셋 선택이 풀린다.
기간 프리셋은 사이트 전체가 STD 하나를 쓴다(탭마다 1·2·3·5·7·10년이 제각각이던 것 정리).
"""
from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

STD = {'1년': 365, '3년': 1095, '5년': 1826, '10년': 3652, '전체': None}


def _span(lo: date, hi: date, days) -> tuple[date, date]:
    return (lo if days is None else max(lo, hi - timedelta(days=days))), hi


def period_range(label: str, presets: dict | None, key: str, lo, hi, default: str | None = None, where=None):
    """반환 (start_date, end_date). presets=None 이면 STD. lo·hi = 고를 수 있는 전체 범위(date).
    where = 이 줄을 넣을 자리(열·컨테이너). 기본은 현재 위치."""
    presets = dict(presets or STD)
    yrs = (hi - lo).days / 365.25 if hi and lo else 99
    opts = [k for k, v in presets.items() if v is None or v <= (hi - lo).days + 31] or list(presets)   # 이력보다 긴 프리셋은 숨김
    dflt = default if default in opts else opts[min(1, len(opts) - 1)]
    ks, ke = f'{key}_s', f'{key}_e'
    ss = st.session_state
    if ks not in ss or ke not in ss or not (lo <= ss[ks] <= hi) or not (lo <= ss[ke] <= hi):
        ss[ks], ss[ke] = _span(lo, hi, presets[dflt])
        ss[key] = dflt

    def _on_pick():
        p = ss.get(key)
        if p in presets:
            ss[ks], ss[ke] = _span(lo, hi, presets[p])

    def _on_date():
        ss[key] = None            # 날짜를 직접 고치면 프리셋 선택 해제

    box = where if where is not None else st
    c0, c1, c2 = box.columns([max(1.2, 0.45 * len(opts)), 1, 1], vertical_alignment='bottom')
    c0.segmented_control(label, opts, key=key, on_change=_on_pick)
    c1.date_input('시작일', min_value=lo, max_value=hi, key=ks, on_change=_on_date)
    c2.date_input('종료일', min_value=lo, max_value=hi, key=ke, on_change=_on_date)
    s, e = ss[ks], ss[ke]
    if s > e:
        s, e = e, s
    return s, e
