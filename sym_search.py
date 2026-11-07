# -*- coding: utf-8 -*-
"""종목명·코드 검색 — 대시보드 여러 화면이 공유한다(2026-11-07, 종목분석 탭에서 분리).

원래 dashboard.py 안에 있었는데 사이클 비교(ui_cycle.py)에도 같은 검색이 필요해서 분리했다.
새 화면에 '예시 종목 버튼' 같은 걸 따로 만들지 말고 이 모듈을 쓸 것 — 검색창 하나면 된다.
"""
import pandas as pd
import streamlit as st


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def name_index():
    """종목명 → 코드 검색용 목록. 레포에 커밋된 파일만 읽는다(사이트에서 외부 접속 없음).
    KR: data/krx_listing_last.csv (krx_listing.py 가 매일 갱신) · US: data/us_marketcap.csv
    2026-10-14 신설 — 한국 종목을 코드로만 찾을 수 있었다."""
    rows = []
    try:
        k = pd.read_csv('data/krx_listing_last.csv', dtype={'Code': str})
        mk = k.get('Marcap', pd.Series([0] * len(k)))
        for c, n, m in zip(k['Code'].str.zfill(6), k['Name'].astype(str), mk):
            rows.append((c, n, 'KR', float(m or 0)))
    except Exception:
        pass
    try:
        u = pd.read_csv('data/us_marketcap.csv')
        for c, n, m in zip(u['Symbol'].astype(str), u['Name'].astype(str), u['marketcap']):
            rows.append((c, n, 'US', float(m or 0) * 1400))   # 시총 정렬용 대략 원화 환산
    except Exception:
        pass
    return rows


def resolve_symbol(q: str):
    """입력 → (확정 코드 or None, 후보 목록[(코드, 표시명)]). 코드·티커는 그대로 통과.
    확정 코드의 시장은 형식으로 안다: 6자리 숫자면 KR, 그 외는 US."""
    q = (q or '').strip()
    if not q:
        return None, []
    up = q.upper()
    base = up.replace('.KS', '').replace('.KQ', '')
    if (len(base) == 6 and base[:5].isdigit()) or (up.isascii() and up.replace('.', '').replace('-', '').isalnum()
                                                    and len(up) <= 6 and not any('가' <= ch <= '힣' for ch in q)):
        # 영문 6자 이하는 티커로 본다 — 단, 그런 티커가 없고 이름으로 맞는 게 있으면 아래로
        idx = name_index()
        if any(c == base for c, _, _, _ in idx) or (len(base) == 6 and base[:5].isdigit()):
            return base if len(base) == 6 and base[:5].isdigit() else up, []
    key = q.replace(' ', '').casefold()
    exact, part = [], []
    for c, n, m, cap in name_index():
        nk = n.replace(' ', '').casefold()
        if nk == key:
            exact.append((c, n, m, cap))
        elif key in nk:
            part.append((c, n, m, cap))
    if len(exact) == 1:
        return exact[0][0], []
    if not exact and len(part) == 1:          # 후보가 하나뿐이면 바로 연다 ('하이닉스' → SK하이닉스)
        return part[0][0], []
    cands = sorted(exact + part, key=lambda r: -r[3])[:15]
    if not cands and up.isascii():
        return up, []                    # 목록에 없는 티커 — 그대로 시도한다
    return None, [(c, f"{n} ({c} · {m})") for c, n, m, _ in cands]


def market_of(code: str) -> str:
    """해결된 코드 하나 → 'KR'|'US' (형식으로 판정, 6자리 숫자면 KR)."""
    return 'KR' if len(code) == 6 and code.isdigit() else 'US'
