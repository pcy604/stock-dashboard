# -*- coding: utf-8 -*-
"""기간 선택 공통 위젯 (2026-11-07) — 프리셋 버튼 + '직접'(시작일·종료일 날짜로 소프트하게).

사용자 지적: 날짜 관련 항목이 전부 'N개월/N년' 고정 프리셋만 있어서 원하는 구간을 못 짚었다
(사이클 비교에서 먼저 나온 요청 — 사이트 전체에 같은 패턴 적용). 매크로 탭(dashboard.py:3722)에
이미 있던 '직접' 패턴을 그대로 공용 함수로 뽑았다 — 새 디자인 아니라 기존 관례를 재사용.
"""
from datetime import timedelta

import streamlit as st


def period_range(label: str, presets: dict, key: str, lo, hi, default: str | None = None):
    """프리셋(일수 또는 None=전체) + '직접'. 반환 (start_date, end_date) — 둘 다 date.

    presets: {'3개월': 91, '1년': 365, '전체': None, ...} — 값이 None 이면 그 프리셋은 lo 부터.
    lo·hi: 고를 수 있는 전체 범위(date). '직접' 고르면 그 안에서 날짜 입력 두 칸이 뜬다.
    """
    opts = list(presets) + ['직접']
    dflt = default if default in opts else opts[0]
    pick = st.segmented_control(label, opts, default=dflt, key=key) or dflt
    if pick == '직접':
        c1, c2 = st.columns(2)
        days0 = next((v for v in presets.values() if v), 365)
        start = c1.date_input('시작일', value=max(lo, hi - timedelta(days=days0)), min_value=lo, max_value=hi, key=f'{key}_s')
        end = c2.date_input('종료일', value=hi, min_value=lo, max_value=hi, key=f'{key}_e')
        if start > end:
            st.caption('⚠️ 시작일이 종료일보다 늦습니다 — 자동으로 맞바꿈')
            start, end = end, start
        return start, end
    days = presets[pick]
    return (lo if days is None else max(lo, hi - timedelta(days=days))), hi
