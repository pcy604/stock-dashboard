"""통합 스크리너 대시보드
실행: python -m streamlit run dashboard.py
"""
import io
import json
import numpy as np
import os
import socket
import time
import re
import requests
from collections import defaultdict

# 2026-10-17 — 응답 없는 외부 서버 하나가 화면 전체를 세웠다. stooq 를 타임아웃 없는
#   pd.read_csv(URL) 로 읽다가 Streamlit Cloud 에서 응답이 안 와 'Running _fetch_spx_yoy_cached()'
#   에서 영원히 멈췄고, 그 아래(종목 발굴 표·종목 분석 검색창)가 아예 그려지지 않았다.
#   라이브러리(FDR 네이버·야후 등) 내부 호출도 timeout 을 안 주는 곳이 많아 두 겹으로 막는다:
#   ① 소켓 기본값 — urllib·pd.read_csv(URL) 경로  ② requests 기본값 — timeout 을 안 준 호출만.
#   read 타임아웃은 '바이트 사이 대기'라 큰 파일을 받는 데는 영향이 없다.
socket.setdefaulttimeout(20)
if not getattr(requests.Session.request, '_default_timeout', False):
    _orig_session_request = requests.Session.request

    def _session_request(self, method, url, *a, **kw):
        if len(a) <= 6 and kw.get('timeout') is None:     # 7번째 위치 인자가 timeout
            kw['timeout'] = 20
        return _orig_session_request(self, method, url, *a, **kw)

    _session_request._default_timeout = True
    requests.Session.request = _session_request
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, timedelta
from contextlib import contextmanager

st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")


@contextmanager
def guard(section: str):
    """섹션 격리. Streamlit은 스크립트를 위→아래로 한 번에 실행하므로 한 탭에서
    예외가 나면 그 아래 모든 탭이 통째로 렌더되지 않는다(2026-08-11 주도주 탭
    KeyError로 5개 탭이 백지가 된 사고). 탭마다 이 가드를 씌워 고장을 국소화한다."""
    try:
        yield
    except Exception as e:
        st.error(f"⚠️ **{section}** 섹션을 그리지 못했습니다 — 다른 탭은 정상입니다.")
        st.caption(f"`{type(e).__name__}: {e}`")


# ── 표에 숫자 강도 색 입히기 ─────────────────────────────────────────
# ⚠️ 2026-10-15 폐기 → table_ui.py (+ 초록 / − 빨강, |값|이 클수록 진하게, 부호 의미 있는 열만).
#   아래는 08월 규칙의 기록이다 — 초록 단색은 '크기'만 보여 줘서 하락(−)이 연한 초록으로
#   '조금 좋은 것'처럼 읽혔다. _shade 는 더 이상 호출되지 않는다.
# (구) 규칙은 하나다: **그 열 안에서 값이 클수록 진한 초록.**
#   · 색조는 초록 하나만 쓴다. 붉은색은 안 쓴다 — 음수라고 나쁜 게 아니고,
#     이 색은 좋고 나쁨이 아니라 **크기**를 나타낸다.
#   · 기준은 열마다 따로 잡는다. 열이 담는 게 서로 다르기 때문이다
#     (YTD 는 수백 %, RS 는 1 근처, 시총은 조 단위).
#     그 표 안의 5~95 분위로 정규화하고 바깥값은 양 끝에서 멈춘다 —
#     이상치 하나가 나머지를 전부 연하게 뭉개는 걸 막는다.
#   · 회차·주차·코드처럼 **크기가 의미 없는 열은 칠하지 않는다.**
#   · 결측은 칠하지 않는다. 없는 값을 있는 것처럼 보이면 안 된다.
_C_2DP = ('PER', 'PBR', 'PSR', 'PEG', 'RS4', 'RS13', '시총($B)', '종가')

# 색을 칠하지 않는 열 — 순번·식별자·날짜. 크다고 진할 이유가 없다.
_NO_SHADE = {'회차', '주차', '코드', '종목', '연도', '달', '연월',
             '그 해 회차', '신호', '표본', '신호 수', '첫 신호', '마지막 신호'}

_GREEN = (22, 112, 74)     # 단일 색조
_ALPHA_MAX = 0.40          # 이보다 진하면 글자가 배경에 먹힌다


def _shade(v, lo, hi):
    """그 열의 lo~hi 안에서 값이 클수록 진한 초록."""
    if v is None or v != v or hi <= lo:
        return ''
    t = (float(v) - lo) / (hi - lo)
    t = max(0.0, min(1.0, t))
    a = 0.04 + t * (_ALPHA_MAX - 0.04)      # 최솟값도 아주 연하게는 보이도록
    r, g, b = _GREEN
    return f'background-color: rgba({r},{g},{b},{a:.3f})'


# ── 열 설명 — 표 머리에 마우스를 올리면 계산식이 뜬다 ─────────────────
# 화면에 약어가 많은데 어디에도 정의가 없었다. 표 밖 캡션에 길게 쓰는 대신
# 그 열 자리에 붙인다.
_COL_HELP = {
    '회차': '이 종목이 **올해** 몇 번째로 낸 신호인지. 해가 바뀌면 1로 돌아갑니다.',
    '그주상승': '신호가 난 그 주의 종가 상승률(%). 이 규칙은 +10% 이상일 때만 신호를 냅니다.',
    '시총($B)': '신호 시점의 시가총액(십억 달러). 주식수 × 그 주 종가.',
    '종가': '신호가 난 주의 종가(달러).',
    '고점대비': '(종가 ÷ 52주 최고가 − 1) × 100. 0%면 신고가, 음수면 그만큼 내려와 있습니다.',
    'YTD': '연초 첫 거래일 종가 대비 수익률(%). 신호 시점 기준입니다.',
    '52주고': '최근 52주 중 가장 높았던 **주봉 종가**. 장중 고가가 아닙니다.',
    '52주저': '최근 52주 중 가장 낮았던 **주봉 종가**.',
    '저점대비': '(종가 ÷ 52주 최저가 − 1) × 100. 바닥에서 얼마나 올라왔는지입니다.',
    '매출가속': '매출 성장률의 **전분기 대비 변화**(%p). '
              '이번 분기 YoY − 직전 분기 YoY. 양수여야 신호가 켜집니다.',
    '이익가속': '영업이익 성장률의 전분기 대비 변화(%p). '
              '성장률 = (영업익 − 4분기 전 영업익) ÷ |매출|. '
              '적자에서도 정의되도록 매출로 나눕니다. 양수여야 신호가 켜집니다.',
    '매출YoY': '매출의 전년 동기 대비 성장률(%).',
    'GPM': '매출총이익률 = 매출총이익 ÷ 매출 × 100.',
    'ΔGPM': 'GPM 의 전분기 대비 변화(%p).',
    'OPM': '영업이익률 = 영업이익 ÷ 매출 × 100.',
    'ΔOPM': 'OPM 의 전분기 대비 변화(%p).',
    '영업익($M)': '그 분기 영업이익(백만 달러).',
    'RS4': '최근 4주 상대강도 = 종목 수익률 ÷ SPY 수익률. 1보다 크면 시장을 이깁니다.',
    'RS13': '최근 13주 상대강도. 같은 방식입니다.',
    'PER': '주가수익비율 = 시가총액 ÷ 최근 4분기 순이익. '
           '**적자면 계산되지 않아 빈칸입니다.**',
    'PSR': '주가매출비율 = 시가총액 ÷ 최근 4분기 매출.',
    'PEG': 'PER ÷ 순이익 YoY 성장률(%). '
           '**빈칸이 많은 게 정상입니다** — 적자이거나 전년 대비 역성장이면 정의되지 않습니다. '
           '이 규칙은 흑자전환 직전 종목을 자주 잡습니다. '
           '⚠️ 정식 PEG 는 EPS 성장률을 쓰지만 이 DB 에 EPS 시계열이 없어 순이익으로 대신합니다.',
    '이후1주': '신호 주 종가 대비 1주 뒤 수익률(%).',
    '이후4주': '신호 주 종가 대비 4주 뒤 수익률(%).',
    '이후13주': '신호 주 종가 대비 13주 뒤 수익률(%).',
    '이후26주': '신호 주 종가 대비 26주 뒤 수익률(%).',
    '이후52주': '신호 주 종가 대비 52주 뒤 수익률(%). 아직 1년이 안 지났으면 빈칸입니다.',
    '이후104주': '신호 주 종가 대비 2년 뒤 수익률(%).',
    '첫 신호': '그 종목이 처음으로 이 규칙의 신호를 낸 주.',
    '마지막 신호': '가장 최근에 신호를 낸 주.',
    '신호 수': '그 종목이 전 기간에 낸 신호 횟수.',
    '진입가': '첫 신호 주의 종가(달러).',
    '현재가': '가장 최근 주의 종가(달러).',
    '수익률': '(현재가 ÷ 진입가 − 1) × 100. 첫 신호에 사서 지금까지 들고 있었을 때입니다.',
    '최고': '첫 신호 이후 최대 상승폭(%). 주봉 종가 기준입니다.',
    '최저': '첫 신호 이후 최대 하락폭(%). 들고 있었다면 견뎌야 했던 폭입니다.',
    '주차': '신호가 난 주의 월요일 날짜.',
}


def col_help() -> dict:
    """st.dataframe 의 column_config. 표에 없는 열은 Streamlit 이 알아서 무시한다."""
    return {c: st.column_config.Column(help=h) for c, h in _COL_HELP.items()}


def color_table(df: pd.DataFrame):
    """표시 포맷만 입힌 Styler. **색은 table_ui 가 st.dataframe 단계에서 칠한다**
    (+ 초록 / − 빨강, |값|이 클수록 진하게 — 2026-10-15 사용자 규칙).

    빈 칸은 'None' 이 아니라 '-' 로 낸다 — 없는 데이터를 있는 척하지 않되,
    파이썬 내부 표현을 화면에 흘리지도 않는다."""
    fmt = {c: ('{:,.2f}' if c in _C_2DP else '{:,.1f}')
           for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}
    for c in ('회차', '신호', '표본', '신호 수'):
        if c in fmt:
            fmt[c] = '{:,.0f}'
    return df.style.format(fmt, na_rep='-')


def num(d: dict, key: str, fmt: str = '{}', dash: str = '-'):
    """JSON에 없는 키를 '-'로 안전 표시. 데이터 스키마가 코드보다 늦게 따라올 때 대비."""
    v = (d or {}).get(key)
    if v is None:
        return dash
    try:
        return fmt.format(v)
    except (ValueError, TypeError):
        return dash

st.markdown("""
<style>
/* ══════════════════════════════════════════════════════════════════════
   디자인 토큰 (2026-09-07 재작성)

   왜 토큰인가: 색이 코드 곳곳에 하드코딩돼 있었다(#1f6b45·#a03028·#52514e…).
   같은 '좋음'을 뜻하는 초록이 화면마다 미묘하게 달랐고, 다크 모드에서는
   대비가 무너졌다. 여기 한 곳에서만 정의하고 나머지는 var() 로 참조한다.

   색 원칙 — 강조색은 하나(청록빛 남색), 나머지는 의미색이다.
     · accent  : 이 도구가 계산한 것, 눌러야 하는 것
     · pos/neg : 수익/손실. **이 둘만 빨강·초록을 쓴다.**
     · warn    : 주의해서 볼 것(회차 초과·데이터 낡음)
   히트맵처럼 셀마다 색을 칠하면 어디를 볼지 알 수 없어진다. 색은 아껴 쓴다.
   ══════════════════════════════════════════════════════════════════════ */
/* 글꼴은 .streamlit/config.toml [theme] font 가 static/fonts/PretendardVariable.woff2 로 직접 서빙(2026-10-24). */

:root {
  --ink:      #16181D;   /* 본문 */
  --ink-2:    #4B5058;   /* 보조 설명 */
  --ink-3:    #767C86;   /* 캡션·단위 */
  --line:     #E3E5EA;   /* 구분선 */
  --line-2:   #F0F1F4;   /* 표 내부 얇은 선 */
  --surface:  #FFFFFF;
  --surface-2:#F7F8FA;   /* 표 헤더·카드 바닥 */
  --accent:   #1F4E79;   /* 단일 강조 — 계산된 값·주요 액션 */
  --accent-2: #EAF0F7;
  --pos:      #16704A;   /* 수익 */
  --pos-bg:   #E8F3EE;
  --neg:      #A32C2C;   /* 손실 */
  --neg-bg:   #FBECEC;
  --warn:     #8A5D0F;   /* 주의 */
  --warn-bg:  #FBF3E2;
}

/* ── 타이포 ───────────────────────────────────────────────────────────
   Pretendard: 한글과 라틴 숫자의 높이가 맞아 표에서 줄이 흔들리지 않는다.
   CDN 이 막히면 시스템 폰트로 조용히 내려간다(그래도 레이아웃은 유지된다). */
html, body, [class*="css"], .stApp,
[data-testid="stMarkdownContainer"], [data-testid="stDataFrame"] {
  font-family: 'Pretendard', 'Pretendard Variable', -apple-system,
               'Segoe UI', 'Malgun Gothic', system-ui, sans-serif !important;
}
html, body, [class*="css"] { font-size: 14px !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {
  line-height: 1.68 !important; color: var(--ink); }

/* 숫자는 폭이 고정돼야 세로로 자릿수가 맞는다 — 표·지표 어디서든 */
[data-testid="stDataFrame"], [data-testid="stTable"],
[data-testid="stMetricValue"], [data-testid="stMetricDelta"] {
  font-variant-numeric: tabular-nums !important;
  font-feature-settings: 'tnum' 1 !important; }

h1 { font-size: 22px !important; font-weight: 700 !important; letter-spacing: -.02em !important;
     margin-bottom: 8px !important; color: var(--ink) !important; }
h2 { font-size: 17.5px !important; font-weight: 660 !important; letter-spacing: -.015em !important;
     margin-bottom: 6px !important; color: var(--ink) !important; }
h3 { font-size: 15px !important; font-weight: 640 !important; letter-spacing: -.01em !important;
     margin-bottom: 5px !important; color: var(--ink) !important; }
/* 섹션 제목 위에 숨 쉴 자리 — 앞 블록에 붙어 있으면 어디서 끊기는지 안 보인다 */
h2, h3 { margin-top: 1.7rem !important; }

/* 캡션이 화면의 절반이다. 읽히는 회색 + 넉넉한 행간. */
[data-testid="stCaptionContainer"] p {
  font-size: 12.5px !important; line-height: 1.66 !important; color: var(--ink-3) !important; }
section[data-testid="stSidebar"] * { font-size: 12px !important; }

/* ── 지표(Metric) — 카드로 묶는다 ─────────────────────────────────────
   숫자 5개가 배경 없이 떠 있으면 어디까지가 한 묶음인지 안 보인다. */
[data-testid="stMetric"] {
  background: var(--surface-2); border: 1px solid var(--line);
  border-radius: 6px; padding: 12px 14px 10px !important; }
[data-testid="stMetricValue"] {
  font-size: 21px !important; font-weight: 700 !important;
  letter-spacing: -.02em !important; color: var(--ink) !important; }
[data-testid="stMetricLabel"] p, [data-testid="stMetric"] label {
  font-size: 11.5px !important; font-weight: 500 !important;
  color: var(--ink-3) !important; letter-spacing: .01em !important; }
[data-testid="stMetricDelta"] { font-size: 11.5px !important; }

/* ── 표 ───────────────────────────────────────────────────────────────
   헤더가 본문과 구분돼야 열을 훑을 수 있다. 셀 배경색은 코드가 칠하므로
   여기서는 뼈대만 잡는다. */
.stDataFrame, .stDataFrame td, .stDataFrame th { font-size: 12.5px !important; }
[data-testid="stDataFrame"] { margin: 0.4rem 0 0.7rem !important;
  border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
[data-testid="stDataFrame"] thead th {
  background: var(--surface-2) !important; font-weight: 600 !important;
  color: var(--ink-2) !important; border-bottom: 1px solid var(--line) !important; }

/* ── 탭 — 밑줄형. 현재 위치가 한눈에 보이게 ── */
.stTabs [data-baseweb="tab-list"] { gap: 2px; border-bottom: 1px solid var(--line); }
.stTabs [data-baseweb="tab"] {
  font-size: 14px !important; font-weight: 600 !important;
  padding: 8px 16px !important; color: var(--ink-3) !important; }
.stTabs [aria-selected="true"] { color: var(--accent) !important; }

/* ── 읽는 폭 제한 ─────────────────────────────────────────────
   layout="wide"는 표에는 좋지만 2000px 모니터에서 글줄이 1800px씩 흘러
   눈이 쉴 곳이 없어진다(2026-08-13 "화면이 꽉 차서 숨쉬기 힘들다").
   폭을 잡아 가운데로 모으면 표는 여전히 넉넉하고 문장은 읽히는 길이가 된다. */
.block-container { max-width: 1400px !important; margin: 0 auto !important;
  padding-top: 2.2rem !important; padding-left: 2.5rem !important;
  padding-right: 2.5rem !important; padding-bottom: 4rem !important; }

/* ── 세로 리듬: 촘촘하되 답답하지 않게 ── */
[data-testid="stVerticalBlock"] { gap: 0.85rem !important; }
[data-testid="stVerticalBlockBorderWrapper"] { gap: 0.85rem !important; }
/* 구분선은 '섹션이 바뀐다'는 신호 — 붙여두면 신호가 죽는다 */
hr { margin: 1.8rem 0 !important; border: none !important;
     border-top: 1px solid var(--line) !important; }
div[data-testid="stSlider"] { padding-top: 0 !important; padding-bottom: 0.1rem !important; }
[data-testid="stRadio"] > label { margin-bottom: 0 !important; }
[data-testid="stExpander"] details { padding: 0 !important;
  border: 1px solid var(--line) !important; border-radius: 6px !important; }
[data-testid="stExpander"] summary { font-weight: 560 !important; }
/* 테두리 카드 안쪽 여백 — 글이 선에 닿아 있으면 답답하다 */
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
  padding: 0.5rem 0.7rem !important; }

/* 알림 박스 — 의미색으로 통일 */
[data-testid="stAlert"] { border-radius: 6px !important; font-size: 13px !important; }

/* ── 모바일 반응형 (≤640px) ───────────────────────────────────
   Streamlit은 좁은 화면에서 st.columns를 자동으로 쌓지 않아 카드/표가
   찌그러진다. 좁은 화면에선 컬럼을 세로로 쌓고 여백·탭을 조정.
   이 앱의 주 사용처가 폰이다. */
@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"] > div { flex: 1 1 100% !important; min-width: 100% !important; }
  .block-container { padding-left: 0.7rem !important; padding-right: 0.7rem !important;
    padding-top: 2.5rem !important; }
  .stTabs [data-baseweb="tab"] { padding: 6px 10px !important; font-size: 12.5px !important; }
  [data-testid="stMetric"] { padding: 10px 12px 8px !important; }
  [data-testid="stMetricValue"] { font-size: 18px !important; }
  .stDataFrame, .stDataFrame td, .stDataFrame th { font-size: 11px !important; }
  [data-testid="stTable"] { overflow-x: auto !important; display: block !important; }
}

/* ══════════════════════════════════════════════════════════════════════
   C · 카드 대시보드 테마 (2026-10-19, 사용자 선택 — 디자인 캔버스 시안 C)
   회색 바탕 위 흰 카드, 큰 숫자, 단일 파랑 강조, 의미색은 수익/손실에만.
   위 토큰을 덮어쓴다(같은 이름 → 기존 화면 코드는 손대지 않아도 따라온다).
   ⚠️ 초록 글자는 #15803D — 흰 바탕 4.5:1. 셀 배경 초록(#16A34A)과 다르다.
   ══════════════════════════════════════════════════════════════════════ */
:root {
  --ink:#111827; --ink-2:#374151; --ink-3:#4B5563;
  --line:#E5E7EB; --line-2:#F3F4F6;
  --surface:#FFFFFF; --surface-2:#F9FAFB; --page:#EEF0F3;
  --accent:#2453C8; --accent-2:#EEF3FF;
  --pos:#15803D; --pos-bg:#DCFCE7; --neg:#DC2626; --neg-bg:#FEE2E2;
  --warn:#B45309; --warn-bg:#FEF3C7;
  --hero:#111827; --hero-2:#1F2937;
  --radius:16px; --radius-sm:10px;
  --mono:'Pretendard', -apple-system, 'Malgun Gothic', sans-serif;   /* 2026-10-24 이름만 남김 — 숫자 정렬은 tabular-nums */
}
.stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"] { background: var(--page) !important; }
h1 { font-size: 26px !important; font-weight: 800 !important; letter-spacing: -.025em !important; }
h2 { font-size: 19px !important; font-weight: 750 !important; }
h3 { font-size: 16px !important; font-weight: 700 !important; }

/* 지표 = 흰 카드, 큰 고정폭 숫자 */
[data-testid="stMetric"] { background: var(--surface) !important; border: none !important;
  border-radius: var(--radius) !important; padding: 16px 18px 14px !important;
  box-shadow: 0 1px 2px rgba(17,24,39,.05); }
[data-testid="stMetricValue"] { font-family: var(--mono) !important; font-size: 23px !important;
  font-weight: 700 !important; letter-spacing: -.01em !important; }
[data-testid="stMetricLabel"] p, [data-testid="stMetric"] label { font-size: 12.5px !important;
  color: var(--ink-3) !important; font-weight: 500 !important; }

/* 테두리 컨테이너 = 카드 (선 대신 흰 면) */
[data-testid="stVerticalBlockBorderWrapper"]:has(> div > [data-testid="stVerticalBlock"]) {
  background: var(--surface); border: none !important; border-radius: var(--radius) !important;
  box-shadow: 0 1px 2px rgba(17,24,39,.05); }

/* 표 = 둥근 흰 카드 */
[data-testid="stDataFrame"] { border: none !important; border-radius: 14px !important;
  background: var(--surface); box-shadow: 0 1px 2px rgba(17,24,39,.05); padding: 4px; }

/* 탭 = 알약형. 선택된 탭은 짙은 면 */
.stTabs [data-baseweb="tab-list"] { gap: 4px !important; border-bottom: none !important;
  flex-wrap: wrap; }
.stTabs [data-baseweb="tab"] { border-radius: var(--radius-sm) !important; padding: 10px 14px !important;
  color: var(--ink-3) !important; background: transparent; min-height: 44px; }
/* 선택된 탭 — 검은 면 대신 연한 파랑 면 + 파랑 글자(2026-10-19 사용자 피드백) */
.stTabs [aria-selected="true"] { background: var(--accent-2) !important; color: var(--accent) !important;
  box-shadow: inset 0 0 0 1px rgba(36,83,200,.18); }
.stTabs [aria-selected="true"] p, .stTabs [aria-selected="true"] div { color: var(--accent) !important; font-weight: 700 !important; }
.stTabs [data-baseweb="tab"]:hover { background: rgba(17,24,39,.04); }
.stTabs button[data-baseweb="tab"] { border-radius: 10px !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"] { display: none !important; }

/* 펼침·알림·입력도 같은 곡률 */
[data-testid="stExpander"] details { background: var(--surface); border: none !important;
  border-radius: var(--radius) !important; box-shadow: 0 1px 2px rgba(17,24,39,.05); }
[data-testid="stAlert"] { border-radius: 12px !important; }
.stButton > button, .stDownloadButton > button, [data-testid="stFormSubmitButton"] > button {
  border-radius: var(--radius-sm) !important; min-height: 44px; font-weight: 600 !important; }
[data-baseweb="input"], [data-baseweb="select"] > div { border-radius: var(--radius-sm) !important; }

/* 종목 분석 머리 카드 (stock_hero) */
.mo-hero { background: var(--surface); color: var(--ink); border: 1px solid var(--line);
  border-radius: 18px; padding: 20px 24px; box-shadow: 0 1px 2px rgba(17,24,39,.04);
  display: flex; flex-wrap: wrap; align-items: center; gap: 14px 32px; margin: 4px 0 10px; }
.mo-hero .t { flex: 1 1 320px; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.mo-hero .k { font-family: var(--mono); font-size: 12.5px; color: var(--ink-3); }
.mo-hero .n { font-size: 26px; font-weight: 800; letter-spacing: -.02em; line-height: 1.2; }
.mo-hero .d { font-size: 13px; color: var(--ink-2); line-height: 1.5; margin-top: 2px; }
.mo-hero .p { display: flex; flex-direction: column; gap: 2px; text-align: right; }
.mo-hero .pv { font-family: var(--mono); font-size: 30px; font-weight: 700; }
.mo-hero .up { font-family: var(--mono); font-size: 14px; color: var(--pos); }
.mo-hero .dn { font-family: var(--mono); font-size: 14px; color: var(--neg); }
.mo-hero .s { display: flex; align-items: center; gap: 10px; background: var(--surface-2);
  border: 1px solid var(--line); border-radius: 14px; padding: 10px 14px; }
.mo-hero .dot { width: 10px; height: 10px; border-radius: 50%; }
.mo-hero .s b { display: block; font-size: 14px; }
.mo-hero .s span { font-size: 12px; color: var(--ink-3); }
.mo-hero .chips { flex-basis: 100%; display: flex; flex-wrap: wrap; gap: 6px; padding-top: 12px;
  border-top: 1px solid var(--line-2); }
.mo-hero .chip { font-size: 12.5px; padding: 4px 10px; border-radius: 999px; background: var(--surface-2);
  border: 1px solid var(--line); color: var(--ink-2); }
.mo-hero .chip b { font-family: var(--mono); font-weight: 700; }
.mo-hero .chip.pos b { color: var(--pos); } .mo-hero .chip.neg b { color: var(--neg); }
.mo-hero a.chip.bot { margin-left: auto; color: var(--accent); background: var(--accent-2); text-decoration: none; font-weight: 600; }
.mo-kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 6px 0 10px; }
.mo-kpi { background: var(--surface); border: 1px solid var(--line); border-left: 5px solid var(--line);
  border-radius: 12px; padding: 12px 14px; display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.mo-kpi .l { font-size: 12.5px; color: var(--ink-3); font-weight: 600; }
.mo-kpi .v { font-family: var(--mono); font-size: 24px; font-weight: 700; color: var(--ink); line-height: 1.2; }
.mo-kpi .s { font-size: 12px; color: var(--ink-3); line-height: 1.35; word-break: keep-all; }  /* 2026-10-21 '…' 잘림 → 줄바꿈 */
.mo-kpi.good { border-left-color: #16A34A; } .mo-kpi.good .v { color: var(--pos); }
.mo-kpi.mid  { border-left-color: #F59E0B; } .mo-kpi.mid .v  { color: var(--warn); }
.mo-kpi.bad  { border-left-color: #DC2626; } .mo-kpi.bad .v  { color: var(--neg); }
.mo-kpi.na   { border-left-color: #D1D5DB; }
.mo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(132px, 1fr)); gap: 8px; margin: 4px 0 6px; }
.mo-chip { background: var(--surface); border-radius: var(--radius-sm); padding: 9px 12px 8px; box-shadow: 0 0 0 1px var(--line) inset; }
.mo-chip .l { font-size: 11.5px; color: var(--ink-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mo-chip .v { font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--ink); margin-top: 2px; white-space: nowrap; }
.mo-chip .v.na { color: #9CA3AF; font-weight: 400; }
.mo-chip .v.pos { color: var(--pos); } .mo-chip .v.neg { color: var(--neg); }
.mo-gh { font-size: 12px; font-weight: 700; color: var(--ink-2); margin: 10px 0 2px; letter-spacing: .02em; }
/* ══════════════════════════════════════════════════════════════════════
   D · 표준화 (2026-10-24 디자인 재점검) — 탭마다 다르게 보이던 것을 한 규격으로.
   · 글꼴 1종(Pretendard, 테마가 서빙) + 숫자는 어디서나 고정폭 숫자(tabular-nums)
   · 곡률 1종(12px) · 그림자 1종 — 표·차트·카드·펼침이 같은 '흰 카드'
   · 제목 3단: ## 섹션 / ### 소제목 / ####·#####·###### 는 전부 같은 '작은 제목'
   ══════════════════════════════════════════════════════════════════════ */
:root { --radius:12px; --radius-sm:10px; --shadow:0 1px 2px rgba(17,24,39,.06); }
.stApp, .stApp * { font-variant-numeric: tabular-nums; }
[data-testid="stMarkdownContainer"] h4, [data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h6 { font-size: 14.5px !important; font-weight: 700 !important;
  color: var(--ink) !important; letter-spacing: -.01em !important; margin: .2rem 0 .1rem !important;
  padding: 0 !important; }
/* 표: 카드 안쪽 여백(4px)이 격자 높이를 깎아 마지막 행이 잘리고, 그걸 메우려던 여유분이 빈 행이 됐다 */
[data-testid="stDataFrame"] { padding: 0 !important; border-radius: var(--radius) !important;
  overflow: hidden; box-shadow: var(--shadow) !important; }
/* 차트도 표와 같은 흰 카드 */
/*   안쪽 여백·overflow:hidden 을 주면 Streamlit 이 잡은 높이에서 그만큼 잘려 x축 눈금이 사라졌다(10-24 TSLA 실화면) → 둘 다 없음 */
[data-testid="stPlotlyChart"] { background: var(--surface); border-radius: var(--radius); box-shadow: var(--shadow); }
/* 줄바꿈 — 마지막 줄에 한두 글자만 남는 것(고아 글자)을 막는다. 짧은 글은 줄 길이를 고르게 */
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li,
[data-testid="stCaptionContainer"], .mo-note, .mo-kpi .s { text-wrap: pretty; word-break: keep-all; }
h1, h2, h3, h4, h5, h6, [data-testid="stMetricLabel"] p, [data-testid="stMetricValue"] > div,
.mo-kpi .l, .mo-kpi .v, .mo-chip .l, .mo-chip .v, .ob2-q, .ob2-d { text-wrap: balance; word-break: keep-all; }
/* 지표 카드 — 값이 한글 문장이어도 잘리지 않게, 한 줄 안의 카드 높이는 같게 */
[data-testid="stMetric"] { border-radius: var(--radius) !important; box-shadow: var(--shadow) !important;
  min-height: 96px; height: 100%; box-sizing: border-box; }
[data-testid="stMetricValue"] { font-size: 21px !important; }
[data-testid="stMetricValue"] > div { white-space: normal !important; overflow: visible !important;
  text-overflow: clip !important; word-break: keep-all; line-height: 1.25; }
.mo-hero { border-radius: var(--radius) !important; }
/* 카드 3종(지표·판정·칩)을 한 모양으로 — 흰 면 + 옅은 1px 선 + 같은 곡률. 판정 카드만 왼쪽 색 막대가 뜻을 가진다 */
[data-testid="stMetric"] { border: 1px solid var(--line) !important; box-shadow: none !important; }
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * { white-space: normal !important;
  overflow: visible !important; text-overflow: clip !important; }
.mo-chip { box-shadow: none; border: 1px solid var(--line); border-radius: var(--radius-sm); }
/* 표 가로 스크롤바는 얇게 — 자리를 차지하는 환경(윈도)에서도 행을 거의 가리지 않게 */
[data-testid="stDataFrame"] .dvn-scroller::-webkit-scrollbar { height: 6px; width: 6px; }
[data-testid="stDataFrame"] .dvn-scroller::-webkit-scrollbar-thumb { background: #CBD0D8; border-radius: 6px; }
.mo-kpi { border-radius: var(--radius); }
.mo-kpi .v { font-size: 21px; word-break: keep-all; }
.mo-chip .v { white-space: normal; word-break: keep-all; }
.mo-chip .l { white-space: normal; overflow: visible; text-overflow: clip; word-break: keep-all; line-height: 1.35; }
.mo-grid.one { grid-template-columns: 1fr; }
[data-testid="stExpander"] details { border-radius: var(--radius) !important; box-shadow: var(--shadow) !important; }
/* 긴 설명은 첫 문장만 — 나머지는 '자세히'로 접는다(table_ui.caption) */
/* 마크다운 표(시황 리포트 본문 등)도 데이터 표와 같은 카드 모양 */
[data-testid="stMarkdownContainer"] table { border-collapse: separate !important; border-spacing: 0;
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--radius); overflow: hidden;
  font-size: 13px; margin: 4px 0 8px; }
[data-testid="stMarkdownContainer"] th { background: var(--surface-2); color: var(--ink-3) !important;
  font-weight: 500 !important; font-size: 12.5px; border: none !important; border-bottom: 1px solid var(--line) !important;
  padding: 7px 12px !important; text-align: left; }
[data-testid="stMarkdownContainer"] td { border: none !important; border-top: 1px solid var(--line-2) !important;
  padding: 6px 12px !important; }
[data-testid="stMarkdownContainer"] td:not(:first-child) { text-align: right; }
.mo-note { font-size: 12.5px; line-height: 1.66; color: var(--ink-3); margin: -2px 0 2px; }
.mo-note details > summary { cursor: pointer; color: var(--accent); font-weight: 600; list-style: none;
  display: inline; margin-left: 4px; }
.mo-note details > summary::-webkit-details-marker { display: none; }
.mo-note details[open] > summary { display: block; margin: 0 0 2px; }
.mo-note code { font-size: 11.5px; }
@media (max-width: 640px) { .mo-hero { padding: 18px; } .mo-hero .n { font-size: 22px; }
  .mo-hero .pv { font-size: 26px; } }
</style>
""", unsafe_allow_html=True)

# ── Plotly 기본 템플릿 — 카드 테마와 같은 색·글꼴 (2026-10-19) ─────────────
import plotly.io as _pio
_pio.templates['market_os'] = go.layout.Template(layout=dict(
    font=dict(family="Pretendard, 'Malgun Gothic', sans-serif", size=12, color='#374151'),
    colorway=['#2453C8', '#15803D', '#DC2626', '#B45309', '#111827', '#7C8AA5'],
    paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
    xaxis=dict(gridcolor='#E5E7EB', zeroline=False, linecolor='#E5E7EB'),
    yaxis=dict(gridcolor='#E5E7EB', zeroline=False, linecolor='#E5E7EB'),
    hoverlabel=dict(font_family="Pretendard, sans-serif", bgcolor='#111827', font_color='#F9FAFB'),
    legend=dict(bgcolor='rgba(0,0,0,0)')))
_pio.templates.default = 'plotly_white+market_os'

# Streamlit Cloud 컨테이너의 파일시스템은 휘발성이다(슬립·재배포 시 초기화). 여기에
# 파일로 저장하는 기능 — 보유종목·API키·구루 채널 — 은 "저장됐다"고 표시된 뒤 조용히
# 사라진다. 조용히 실패하는 대신 사실대로 알리려고 환경을 구분한다.
IS_CLOUD = str(Path(__file__).resolve()).replace('\\', '/').startswith('/mount/src')

PERF_JSON        = Path('results/perf_latest.json')
SCREENER_JSON    = Path('results/screener_latest.json')
CANSLIM_JSON     = Path('results/canslim_latest.json')
# TURNAROUND_JSON 제거: 정의만 있고 쓰는 화면이 없었다. 파일도 06-01에
# 멈춰 있어, 남겨두면 '살아 있는 데이터'로 오인돼 감시 목록만 오염시킨다.
MDD_JSON         = Path('results/mdd.json')


@st.cache_data(ttl=1800)
def _mdd_map() -> dict:
    """sym → 현재 고점대비 낙폭%(cur_dd) · 1y/역대 MDD. mdd.json(주 1회 갱신) 기반."""
    d = load_json(MDD_JSON) or {}
    return {s['sym']: s for s in d.get('stocks', [])}


def _mdd_col(sym: str, mmap: dict):
    """고점대비 낙폭(%) — **숫자**로 돌려준다(2026-10-15. 문자열이면 정렬·필터·색이 안 된다)."""
    r = mmap.get(sym)
    return float(r['cur_dd']) if r and r.get('cur_dd') is not None else None


@st.cache_data(ttl=1800)
def _traj_map() -> dict:
    """sym → 펀더멘털 궤적(판정·ΔROE·궤적점수). value_kr.json 기반 — KR만."""
    d = load_json(Path('results/value_kr.json')) or {}
    return {s['sym']: s['traj'] for s in d.get('stocks', []) if s.get('traj')}


def _income_sankey(row, unit_div, unit, seg=None):
    """손익계산서 1개 기간 → 폭포(waterfall) 차트.

    2026-10-19 — Sankey 를 버렸다. 이유 둘:
      ① 매출원가가 매출의 80%+ 인 회사(TSLA 등)는 화면 대부분이 분홍 띠 하나가 되고
         이익 쪽은 실처럼 가늘어져 읽히지 않는다.
      ② 순이익 > 영업이익(영업외수익·세금 환급)이면 Sankey 는 '없는 흐름'을 그린다
         — TSLA 2026-06 은 영업이익 0.4B 에서 순이익 1.1B 가 흘러나오는 그림이었다.
    폭포는 둘 다 정직하게 보인다: 차감은 내려가는 빨강, 가산은 올라가는 초록.
    합계 막대(매출총이익·영업이익·순이익)에는 매출 대비 마진(%)을 같이 쓴다.
    seg 인자는 호환용(쓰지 않음) — 사업부문 구성은 아래 '사업부문' 절이 맡는다."""
    rv = row.get('revenue')
    gross = row.get('gross')
    op = row.get('op_income')
    ni = row.get('net_income')
    if not rv or gross is None or op is None:
        return None
    cogs = rv - gross
    sga = gross - op                         # 판관비·R&D 등 영업비용 합계(잔차라 항상 맞는다)
    d = unit_div
    # (이름, 시작, 끝, 종류) — 종류: rev 매출 / cost 차감 / gain 가산 / total 남은 이익
    steps = [('매출', 0, rv, 'rev'), ('매출원가', rv, gross, 'cost'), ('매출총이익', 0, gross, 'total'),
             ('판관비·R&D', gross, op, 'cost'), ('영업이익', 0, op, 'total')]
    if ni is not None:
        steps += [('영업외·세금', op, ni, 'gain' if ni >= op else 'cost'), ('순이익', 0, ni, 'total')]
    COL = {'rev': '#374151', 'cost': '#DC2626', 'gain': '#15803D', 'total': '#2453C8'}
    xs = [k for k, *_ in steps]
    fig = go.Figure(go.Bar(
        x=xs, base=[min(a0, b0) / d for _, a0, b0, _ in steps],
        y=[max(abs(b0 - a0), rv * 0.002) / d for _, a0, b0, _ in steps],   # 0 에 가까워도 선은 보이게
        marker=dict(color=[('#B91C1C' if (t == 'total' and b0 < 0) else COL[t]) for _, a0, b0, t in steps],
                    line=dict(width=0)),   # 적자 합계는 진한 빨강
        width=0.62,
        customdata=[(b0 - a0) / d if t in ('cost', 'gain') else b0 / d for _, a0, b0, t in steps],
        hovertemplate='%{x}: %{customdata:,.1f}' + unit + '<extra></extra>'))
    for i, (k, a0, b0, t) in enumerate(steps):          # 이음선 — 다음 막대 시작점까지 점선
        if i + 1 < len(steps):
            lvl = b0 if t != 'total' else b0
            fig.add_shape(type='line', x0=i + 0.31, x1=i + 0.69, y0=lvl / d, y1=lvl / d,
                          line=dict(color='#9CA3AF', width=1, dash='dot'))
    for i, (k, a0, b0, t) in enumerate(steps):          # 값 라벨 — 항상 막대 윗변 위
        v = (b0 - a0) if t in ('cost', 'gain') else b0
        _x = v / d
        _f = ',.0f' if abs(_x) >= 100 else ',.1f'       # 억·M 단위의 큰 수는 소수점 없이
        txt = f"<b>{_x:+{_f}}</b>" if t in ('cost', 'gain') else f"<b>{_x:{_f}}</b>"
        if t == 'total':
            txt += f"  <span style='color:#6B7280'>{b0/rv*100:.1f}%</span>"
        fig.add_annotation(x=i, y=max(a0, b0, 0) / d, text=txt, showarrow=False, yanchor='bottom',
                           yshift=4, font=dict(family="Pretendard, sans-serif", size=12,
                                               color=('#B91C1C' if (t == 'total' and b0 < 0) else (COL[t] if t != 'rev' else '#111827'))))
    hi = max(rv, 0) / d
    lo = min(0, op, ni if ni is not None else 0) / d
    fig.update_layout(
        height=320, showlegend=False, bargap=0.3,
        margin=dict(l=8, r=8, t=16, b=8),
        yaxis=dict(title=None, ticksuffix=unit, range=[lo * 1.15 if lo < 0 else 0, hi * 1.14],
                   gridcolor='#F3F4F6', zeroline=True, zerolinecolor='#D1D5DB',
                   tickfont=dict(size=11, color='#6B7280')),
        xaxis=dict(tickfont=dict(size=12, color='#374151'), linecolor='rgba(0,0,0,0)'))
    return fig


def _traj_col(sym: str, tmap: dict):
    """'📈 개선 5/7' 축약 — 다른 탭 표에 한 열로 얹는 용도."""
    t = tmap.get(sym)
    if not t:
        return '-'
    lab = {'improving': '📈', 'deteriorating': '📉', 'stable': '➖'}.get(t.get('verdict'), '')
    return f"{lab} {t.get('traj_score')}/7"


SIG_COLS_PAST = ['past_sig_52w','past_sig_vol','past_sig_ma5','past_sig_cup','past_sig_maconv','past_sig_rsimacd']
SIG_COLS_NOW  = ['now_sig_52w', 'now_sig_vol', 'now_sig_ma5', 'now_sig_cup', 'now_sig_maconv', 'now_sig_rsimacd']
SIG_LABELS    = ['52주신고가','거래량폭발','5일라이딩','컵위드핸들','이평수렴','RSI/MACD']


# ── 공통 헬퍼 ────────────────────────────────────────────────────────
def _dfh(n, cap=620):
    """dataframe 높이 — 행 27px에 딱 맞게(빈 필러 행 방지), 길면 내부 스크롤. row_height=25과 세트."""
    return int(min(25 * n + 36, cap))




@st.cache_data(ttl=3600, show_spinner=False)
def _usdkrw() -> float:
    """원/달러 — 포트폴리오에서 KR·US 를 같은 통화로 더하기 위해. 실패 시 1400 가정."""
    try:
        import FinanceDataReader as fdr
        v = fdr.DataReader('USD/KRW', (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d'))['Close'].dropna()
        if len(v):
            return float(v.iloc[-1])
    except Exception:
        pass
    try:
        import yfinance as yf
        v = yf.Ticker('KRW=X').history(period='10d')['Close'].dropna()
        if len(v):
            return float(v.iloc[-1])
    except Exception:
        pass
    return 1400.0


def cap_usd_b(marcap, market):
    """시총을 $B 로. KR·US 가 한 표에 섞일 때 **같은 단위여야 정렬·필터가 성립한다**
    (원화 원 단위와 달러를 한 열에 두면 삼성전자가 NVDA 보다 '큰' 숫자가 된다)."""
    if not marcap:
        return None
    try:
        v = float(marcap)
    except (TypeError, ValueError):
        return None
    return v / 1e9 if market == 'US' else v / _usdkrw() / 1e9


def cap_caption() -> str:
    # 2026-10-26 사용자 규칙: 한국 = 억원, 미국 = $B, 섞인 표는 값은 각자 단위 · 머리행에 두 단위
    return "시총 — 한국 = 억원 · 미국 = $B (두 시장이 섞인 표는 머리행에 '억원·$B', 기본 순서는 달러 환산 시총)"


def _ni_usd_m(v):
    """'$480M' · '$-414M' · '9.9조' · '-382억' → 미국달러 백만($M). KR 은 원/달러 환산."""
    if v is None:
        return None
    import re as _re
    m = _re.match(r'^\s*(-?)\$?(-?)([\d,.]+)\s*(조|억|B|M|K)?\s*$', str(v))
    if not m:
        return None
    x = float(m.group(3).replace(',', '')) * (-1 if '-' in m.group(1) + m.group(2) else 1)
    u = m.group(4) or ''
    if u in ('조', '억'):
        return round(x * (1e12 if u == '조' else 1e8) / _usdkrw() / 1e6, 1)
    return round(x * {'B': 1e3, 'M': 1, 'K': 1e-3, '': 1e-6}[u], 1)


def fmt_cap(marcap, market):
    if not marcap:
        return 'N/A'
    if market == 'US':
        b = marcap / 1e9
        return f"${b:.0f}B" if b < 1000 else f"${b/1000:.1f}T"
    if marcap >= 1e12:
        return f"{marcap/1e12:.1f}조"
    return f"{int(marcap//1e8):,}억"

def tag(v):
    return '✅' if v else '·'

def color_ret(val):
    """+ 초록 / − 빨강 (2026-10-15 통일 — 구 규칙은 한국식 빨강=상승·파랑=하락이었다)."""
    try:
        v = float(str(val).replace('%','').replace('+',''))
        if v >= 10:  return 'color:#15803d;font-weight:bold'
        if v > 0:    return 'color:#16a34a'
        if v <= -10: return 'color:#b91c1c;font-weight:bold'
        if v < 0:    return 'color:#dc2626'
    except:
        pass
    return ''

def color_sig(val):
    if val == '✅': return 'color:#2ecc71;font-weight:bold'
    return 'color:#444'

@st.cache_data(ttl=60)
def load_json(path):
    if not Path(path).exists():
        return None
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        # 스크래퍼가 저장한 HTML 이스케이프(&amp; 등) 종목명 복원
        import html as _html
        if isinstance(data, dict) and isinstance(data.get('stocks'), list):
            for _s in data['stocks']:
                if isinstance(_s, dict) and isinstance(_s.get('name'), str):
                    _s['name'] = _html.unescape(_s['name'])
        return data
    except Exception:
        return None

# ── 전역 규칙: 표의 모든 숫자는 소수 1자리 (2026-08-16, 2026-08-17 수정) ──
#   1차 시도(데이터 round)는 실패했다. 값이 0.1이어도 화면엔 0.100000 으로 나왔는데,
#   원인은 데이터가 아니라 **pandas Styler 의 기본 표시 정밀도가 6자리**였기 때문이다
#   (pd.get_option('styler.format.precision') == 6). 그래서 옵션 자체를 1로 낮춘다.
#   호출부에서 .format({...}) 을 명시한 열은 그 포맷이 그대로 우선한다.
pd.set_option('styler.format.precision', 1)
pd.set_option('styler.format.na_rep', '-')      # 결측은 '-' (nan/None 을 화면에 흘리지 않는다)
pd.set_option('styler.format.thousands', ',')   # 천 단위 쉼표 (2026-10-21)

#   숫자 열 %.1f 기본 포맷 · 부호 색(+초록/−빨강, 클수록 진하게) · 🔎 필터는 전부
#   table_ui 한 곳에서 st.dataframe 을 감싸 처리한다(2026-10-15). 표마다 따로 하지 않는다.
import analysis_checks as _ac_dil
if not hasattr(_ac_dil, 'summarize_dilution'):   # 클라우드가 옛 모듈을 들고 있으면
    import importlib as _il0
    _ac_dil = _il0.reload(_ac_dil)
import table_ui as _tui
if getattr(_tui, 'API_VERSION', 0) < 7:          # (7 = tkey·시총 두 단위, 2026-10-26) 클라우드가 옛 모듈을 메모리에 들고 있으면 다시 읽는다
    import importlib as _il
    _tui = _il.reload(_tui)
_tui.install(st)


# ── 표 출처·마지막 갱신 (2026-10-19 표 규칙 ④) ─────────────────────────
#   모든 표 밑에 '출처 · 마지막 갱신'을 단다. 산출물은 파일 **안의** 날짜를 쓴다
#   (파일 mtime 은 Streamlit Cloud 에서 clone 시각이라 거짓이다).
@st.cache_data(ttl=600, show_spinner=False)
def _asof_of(path: str) -> str | None:
    d = load_json(Path(path)) or {}
    if not isinstance(d, dict):
        return None
    for k in ('generated', 'updated', 'date', 'asof', 'generated_at', 'run'):   # run = research CI 산출물(2026-10-26 '갱신 미상' 7곳)
        if d.get(k):
            v = str(d[k]).replace('T', ' ')[:16]
            if d.get('signal_week'):
                v += f" (데이터 주차 {d['signal_week']})"
            return v
    return None


def _stat_grid(groups, one: bool = False):
    """키-값 묶음을 칩 격자로 — 2열 세로 표 대신(2026-10-19 '억지로 키운 표' 정리).
    groups: [(묶음이름, [(라벨, 표시값, 부호색 여부), ...]), ...]. 값 '-' 는 흐리게 그대로 보인다."""
    import html as _h
    out = []
    for g, items in groups:
        chips = []
        for it in items:
            k, v = it[0], it[1]
            signed = len(it) > 2 and it[2]
            cls = 'na' if v in (None, '-', '') else ''
            if signed and not cls:
                t = str(v).lstrip()
                cls = 'neg' if t.startswith('-') or t.startswith('−') else ('pos' if t not in ('0', '0.0%') else '')
            chips.append(f"<div class='mo-chip'><div class='l'>{_h.escape(k)}</div>"
                         f"<div class='v {cls}'>{_h.escape(str(v if v not in (None, '') else '-'))}</div></div>")
        # one=True: 한 줄에 하나씩(옆 표와 높이를 맞출 때 — 2+1 로 남는 빈 칸 없이, 2026-10-24)
        out.append((f"<div class='mo-gh'>{_h.escape(g)}</div>" if g else '') + f"<div class='mo-grid{' one' if one else ''}'>{''.join(chips)}</div>")
    st.markdown(''.join(out), unsafe_allow_html=True)


def _tsrc(label: str, path: str | None = None, asof: str | None = None, live: bool = False):
    if live and asof is None:
        import datetime as _dt
        asof = (_dt.datetime.utcnow() + _dt.timedelta(hours=9)).strftime('%Y-%m-%d %H:%M KST 조회')
    elif path and asof is None:
        asof = _asof_of(path)
    _tui.src(label, asof)
_tui.begin_run(st)

# 화면에서 DART·EDGAR 를 부를 때는 빨리 포기한다 — 응답 없는 서버를 몇 분씩 기다리면
#   '연간/분기' 같은 버튼이 안 먹는 것처럼 보인다(2026-10-17). 자세한 이유는 dart_client._MODE.
def _fresh_module(mod):
    """코드만 바뀐 배포에서 클라우드 프로세스가 **이전 버전 모듈**을 메모리에 들고 있었다
    (2026-10-17 실측: dart_client 에 새 함수가 없음 → 새 재시도 정책이 적용 안 됨).
    파일 수정시각이 처음 읽었을 때와 다르면 다시 읽는다(같은 모듈 객체를 갱신 → 함수 안 import 도 새 코드)."""
    import importlib
    try:
        mt = os.path.getmtime(mod.__file__)
        seen = getattr(mod, '_loaded_mtime', None)
        if seen is not None and seen != mt:
            mod = importlib.reload(mod)
        mod._loaded_mtime = mt
    except Exception:
        pass
    return mod


_DC_ERR = None
_kfn = None
try:
    import dart_client as _dc
    import edgar_client as _ec
    _dc = _fresh_module(_dc)
    _ec = _fresh_module(_ec)
    import kr_fin_naver as _kfn
    _kfn = _fresh_module(_kfn)
    import importlib                            # 처음 본 프로세스인데 옛 모듈인 경우(위 시각 비교가 못 잡음)
    if getattr(_dc, 'API_VERSION', 0) < 4:
        _dc = importlib.reload(_dc)
    if getattr(_ec, 'API_VERSION', 0) < 3:
        _ec = importlib.reload(_ec)
    _dc.set_interactive(True)
    _ec.set_interactive(True)
except Exception as _e:
    _dc = None
    _DC_ERR = f'{type(_e).__name__}: {_e}'


@st.cache_data(ttl=600, show_spinner=False)
def _data_status():
    """산출물별 실제 데이터 날짜·주기·상태 (data_freshness 레지스트리 단일 원천)."""
    try:
        import data_freshness
        # 2026-10-10: statuses() → ranked(). 중요도(이게 멈추면 같이 멈추는
        # 산출물 수)로 정렬되고 deps·upstream_bad 가 붙는다. 평면 목록이던
        # 화면이 "뭔 말인지 모르겠다"가 된 이유가 순서와 연결이 없어서였다.
        return data_freshness.ranked()
    except Exception:
        return []


def file_key(path) -> str:
    """캐시 키용 파일 지문 (수정시각+크기).

    왜 필요한가: 산출물 JSON의 `generated`(날짜)를 캐시 키로 쓰다가
    **같은 날 두 번 빌드하면 키가 겹쳐 옛 결과가 계속 나오는** 사고가 났다.
    f1/f4 열을 추가·재발행했는데도 화면은 '재빌드가 필요하다'를 띄웠다.
    날짜가 아니라 파일이 바뀌었는지로 키를 잡는다.
    """
    try:
        s = Path(path).stat()
        return f'{int(s.st_mtime)}:{s.st_size}'
    except Exception:
        return '0:0'


def data_stamp(path: str, prefix: str = '데이터 기준') -> str:
    """화면에 '이 숫자는 언제 것인가'를 붙인다. 정지 상태면 눈에 띄게 경고한다.

    이걸 만든 이유: 🔥상승 상위가 18일 지난 수익률을 '1개월 상승 상위'로 보여주는데
    화면 어디에도 기준일이 없었다. 숫자 옆에 날짜가 없으면 사용자는 최신이라고 읽는다.
    """
    for r in _data_status():
        if r['path'] == path:
            if r['date'] is None:
                return f"⚠️ {prefix} 확인 불가 ({r['note']})"
            # 클라우드는 UTC, 데이터 날짜는 KST라 갓 갱신된 파일이 -1일로 나온다 → 0으로 눕힌다
            age = f"{r['age']}일 전" if (r['age'] or 0) > 0 else '오늘'
            base = f"{prefix} **{r['date']}** ({age}) · 갱신 주기 {r['cycle']}"
            if r['state'] != 'ok':
                return (f"🔴 **갱신 정지** — {base}. 허용 {r['max_age']}일을 넘겼습니다. "
                        f"이 화면 숫자는 그날 기준이니 최신 시세로 다시 확인하세요.")
            return base
    return ''


def file_mtime(path):
    p = Path(path)
    if not p.exists():
        return None
    ts = p.stat().st_mtime
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')

def update_badge(path):
    t = file_mtime(path)
    if t:
        st.caption(f"🕐 마지막 업데이트: **{t}**")


def _get_secret(name, default=''):
    """배포 환경(Streamlit Secrets) → 환경변수 → 로컬파일 순으로 키 조회.
       클라우드 공개 배포 시 키가 코드에 남지 않도록 분리."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    import os
    if os.environ.get(name):
        return os.environ[name]
    _f = Path('data') / f'.{name.lower()}'
    if _f.exists():
        try:
            return _f.read_text(encoding='utf-8').strip()
        except Exception:
            pass
    return default

FRED_KEY = _get_secret('FRED_KEY')


# ── 🩺 외부 소스 연결 진단 (?diag=net) ─────────────────────────────────
# 클라우드 서버에서 어떤 소스가 막혔는지 '이 서버 기준'으로 본다(내 PC 에서 되는 것과 다르다).
# 키는 절대 화면에 내보내지 않는다 — 예외 메시지에 URL(쿼리 포함)이 실리므로 가린다.
if st.query_params.get('diag') == 'net':
    import re as _re

    def _redact(m):
        return _re.sub(r'(crtfc_key|api_key)=[^&\s\'"]+', r'\1=***', str(m))

    def _probe(name, url, **kw):
        t0 = time.time()
        try:
            r = requests.get(url, timeout=(5, 10), **kw)
            return {'소스': name, '결과': f'HTTP {r.status_code}', '초': round(time.time() - t0, 2),
                    '응답 앞부분': _redact(r.text[:160].replace('\n', ' '))}
        except Exception as e:
            return {'소스': name, '결과': type(e).__name__, '초': round(time.time() - t0, 2),
                    '응답 앞부분': _redact(e)[:200]}
    try:
        _dk = _dc._key() if _dc else ''
    except Exception:
        _dk = ''
    st.subheader('🩺 외부 소스 연결 진단 — 이 서버(Streamlit Cloud) 기준')
    # 병렬 + 전체 마감 20초: DNS·TLS 단계 정지는 requests 타임아웃이 못 잡는다(2026-10-17 진단이 2분+ 멈춤)
    import concurrent.futures as _cf
    _UA = {'User-Agent': 'Mozilla/5.0'}
    _jobs = [   # (이름, URL, requests 인자)
        ('서버 공인 IP', 'https://api.ipify.org', {}),
        ('DART API', 'https://opendart.fss.or.kr/api/company.json',
         {'params': {'crtfc_key': _dk, 'corp_code': '00126380'}}),
        ('DART 웹', 'https://dart.fss.or.kr/', {}),
        ('SEC EDGAR', 'https://data.sec.gov/submissions/CIK0001318605.json',
         {'headers': {'User-Agent': 'stock-screener research pcy604604@gmail.com'}}),
        ('네이버 금융', 'https://finance.naver.com/item/main.naver?code=005930', {'headers': _UA}),
        ('FRED', 'https://api.stlouisfed.org/fred/series/observations',
         {'params': {'series_id': 'SP500', 'api_key': FRED_KEY, 'file_type': 'json', 'limit': 1}}),
        ('stooq', 'https://stooq.com/q/d/l/?s=^spx&i=m', {}),
        # KR 재무제표 대체 소스 후보(2026-10-17) — DART 가 막힌 해외 서버에서 닿는지
        ('네이버 기업분석', 'https://navercomp.wisereport.co.kr/v2/company/c1010001.aspx?cmp_cd=005930', {'headers': _UA}),
        ('FnGuide', 'https://comp.fnguide.com/SVO2/ASP/SVD_Finance.asp?pGB=1&gicode=A005930', {'headers': _UA}),
        ('KRX 정보', 'https://data.krx.co.kr/', {'headers': _UA}),
    ]
    _ex = _cf.ThreadPoolExecutor(max_workers=len(_jobs))
    _futs = [(n, _ex.submit(_probe, n, u, **kw)) for n, u, kw in _jobs]
    _done, _ = _cf.wait([f for _, f in _futs], timeout=20)
    _rows = [f.result() if f in _done else {'소스': n, '결과': 'HANG >20s', '초': 20.0,
                                            '응답 앞부분': '20초 안에 끝나지 않음(DNS·TLS·응답 단계 정지)'}
             for n, f in _futs]
    _ex.shutdown(wait=False)
    _tsrc('외부 소스 직접 측정(이 서버)', live=True)
    st.dataframe(pd.DataFrame(_rows), filters=False, color=False, hide_index=True)
    st.code('\n'.join(f"{r['소스']:<10} | {r['결과']:<22} | {r['초']:>6} | {r['응답 앞부분'][:110]}" for r in _rows))
    st.json({'DART 키 설정됨': bool(_dk), 'dart_client.health()': _dc.health() if _dc else None,
             'dart_client 로드 오류': _DC_ERR})
    st.stop()

# ── 🧾 재무 원값 확인 (?diag=fin&sym=005930) — 화면 표와 **같은 함수**의 출력을 글자로 ─────
# 표는 캔버스로 그려져 대조가 어렵다. 공시 원문과 숫자를 맞춰 보기 위한 검증용 출력.
if st.query_params.get('diag') == 'fin':
    _sym = (st.query_params.get('sym') or '005930').strip().upper()
    _kr = len(_sym) == 6 and _sym[:5].isdigit()
    st.subheader(f'🧾 재무 원값 — {_sym} ({"DART" if _kr else "EDGAR"} · 화면과 같은 함수)')
    _keys = ['period', 'revenue', 'gross', 'op_income', 'net_income', 'eps', 'sga', 'assets',
             'liabilities', 'equity', 'op_cf', 'inv_cf', 'fin_cf', 'capex']
    for _fq in ('annual', 'quarter'):
        _t0 = time.time()
        try:
            if _kr:                               # 화면과 같은 순서: DART → 막혔으면 네이버 기업분석
                _cc = _dc.corp_map().get(_sym)
                _rf = _dc.statements(_cc, _fq, 5) if _cc else []
                if not _rf:
                    _rf = _kfn.statements(_sym, _fq, 5)
            else:
                _rf = _ec.statements(_sym, _fq, 6)
            _er = None
        except Exception as _e:
            _rf, _er = [], f'{type(_e).__name__}: {_e}'
        _txt = [' | '.join(_keys)] + [' | '.join(str(r.get(k)) for k in _keys) for r in _rf]
        st.code(f'[{_fq}] {time.time() - _t0:.1f}s err={_er}\n' + '\n'.join(_txt))
    st.json({'dart_client.health()': _dc.health() if _dc else None, 'dart_client 로드 오류': _DC_ERR})
    st.stop()

@st.cache_data(ttl=3600, max_entries=48)
def _fetch_fred_cached(series_id: str, limit: int):
    """실패 시 예외 → 캐시에 실패가 박제되지 않음 (핵심: 빈 결과 1시간 캐싱 버그 방지)."""
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = dict(series_id=series_id, api_key=FRED_KEY, file_type='json',
                  sort_order='desc', limit=limit)
    last = None
    for _ in range(2):                       # 일시 오류 재시도
        try:
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            obs = r.json()['observations']
            data = [(o['date'], float(o['value'])) for o in obs if o['value'] != '.']
            if data:
                return sorted(data)
            last = RuntimeError('empty')
        except Exception as e:
            last = e
    raise last


@st.cache_resource(show_spinner=False)
def _fail_memo() -> dict:
    """외부 소스 실패 시각 (프로세스 공용). 실패는 캐시에 안 남기므로(빈 값 박제 방지)
    그대로 두면 **화면을 다시 그릴 때마다** 죽은 서버를 타임아웃까지 기다린다 — 10분은 건너뛴다."""
    return {}


def _recently_failed(key: str, ttl: int = 600) -> bool:
    t = _fail_memo().get(key)
    return t is not None and time.time() - t < ttl


def _mark_failed(key: str):
    _fail_memo()[key] = time.time()


def fetch_fred(series_id: str, limit: int = 24):
    if _recently_failed(f'fred:{series_id}'):
        return []
    try:
        return _fetch_fred_cached(series_id, limit)
    except Exception:
        _mark_failed(f'fred:{series_id}')
        return []

@st.cache_data(ttl=3600, show_spinner=False)
def _fetch_spx_yoy_cached():
    """S&P500 1년 수익률(%). 1순위 FRED SP500(일간·API 키) → 2순위 stooq 월간 CSV(8초 제한).
    2026-10-17: stooq 를 타임아웃 없이 읽다 화면 전체가 멈춘 사고 이후 순서를 바꿨다."""
    try:
        d = _fetch_fred_cached('SP500', 400)                 # 최신 400 거래일 ≈ 1.6년
        s = pd.Series([v for _, v in d], index=pd.to_datetime([a for a, _ in d])).sort_index()
        prev = s[s.index <= s.index[-1] - pd.DateOffset(years=1)]
        if len(prev):
            return round((float(s.iloc[-1]) / float(prev.iloc[-1]) - 1) * 100, 2)
    except Exception:
        pass
    r = requests.get('https://stooq.com/q/d/l/?s=^spx&i=m', timeout=8)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=['Date']).sort_values('Date').tail(15)
    if len(df) < 13:
        raise RuntimeError('short')
    return round((float(df['Close'].iloc[-1]) / float(df['Close'].iloc[-13]) - 1) * 100, 2)


def fetch_spx_yoy():
    if _recently_failed('spx_yoy'):
        return None
    try:
        return _fetch_spx_yoy_cached()
    except Exception:
        _mark_failed('spx_yoy')
        return None

# 2026-10-21 — compute_macro_signal(Fed·M2·SPX YoY → 현금 10~70%) 삭제.
#   검증 목록 1-5 에서 기각된 규칙이 종목분석 M 칸에 남아 있었다. 판정은 verdict.py.


# ── 탭 구성 ──────────────────────────────────────────────────────────
# ── 📸 온보딩 카드 — 처음 온 사람이 탭을 누르기 전에 먼저 보는 30초 설명 ──
#    세션 첫 렌더에서만 펼쳐두고, 이후 상호작용부터는 접힌다(매일 쓰는 사람 방해 금지).
#
#    ⚠️ 2026-09-07 재작성 — SVG(1160px 고정) → 반응형 HTML.
#    그전에는 docs/onboarding_card.svg 를 st.image 로 띄웠는데, 고정 레이아웃이라
#    폰(375px)에서 331px 로 줄어 글자가 안 읽혔다. 그래서 "같은 내용 텍스트로 보기"
#    라는 두 번째 사본을 따로 두고 있었다 — 한 내용을 두 곳에서 관리하니 수치가
#    어긋나기 시작했다(카드에는 7,551건·+12.5%, 실제는 7,559건·+12.8%).
#    HTML 로 바꾸면 폰에서도 그대로 읽히고 사본도 하나로 준다.
_first_visit = 'seen_onboard' not in st.session_state
# 2026-10-15 — 폰에서는 펼친 사용설명이 2~3화면을 차지해 탭(종목 검색)이 한참 아래로 밀렸다.
try:
    _UA = st.context.headers.get('User-Agent', '') or ''
except Exception:
    _UA = ''
IS_MOBILE = any(k in _UA for k in ('Mobi', 'Android', 'iPhone', 'iPad'))


# 2026-10-21 모바일 실화면 — plotly 도구 막대(확대·저장 아이콘)가 터치 기기에선 늘 떠 있어 범례를 가렸다.
#   모든 차트 공통: 폰에서는 숨기고, PC 는 마우스를 올렸을 때만. 한 번만 감싼다(스크립트 재실행마다 겹치지 않게).
# 2026-10-24 — 버전 표식: 클라우드 프로세스가 옛 래퍼를 들고 있으면 새 규격이 안 먹는다(table_ui 와 같은 사고) → 버전이 다르면 다시 감싼다.
if getattr(st.plotly_chart, '_mo_wrapped', 0) != 2:
    _orig_plotly_chart = st._main.plotly_chart
    CHART_H = {'S': 260, 'M': 320, 'L': 420}     # 차트 높이 3단(작게·보통·크게)

    def _plotly_chart(fig, *a, **kw):
        try:
            _ua = st.context.headers.get('User-Agent', '') or ''
        except Exception:
            _ua = ''
        _mob = any(k in _ua for k in ('Mobi', 'Android', 'iPhone', 'iPad'))
        cfg = dict(kw.pop('config', None) or {})
        cfg.setdefault('displayModeBar', False if _mob else 'hover')
        cfg.setdefault('displaylogo', False)
        # 2026-10-24 차트 규격 — 높이가 230·240·284·300·310·380·420·430 으로 10가지였다. 3단으로 맞춘다.
        #   여러 줄짜리(서브플롯·행 수에 비례해 키운) 차트는 그대로 둔다. 범례·제목 글꼴 크기도 하나로.
        try:
            _h = getattr(fig.layout, 'height', None)
            _multi = bool(getattr(fig, '_grid_ref', None)) and len(fig._grid_ref) > 1
            if isinstance(_h, (int, float)) and not _multi and _h <= 480:
                fig.update_layout(height=CHART_H['S'] if _h <= 270 else CHART_H['M'] if _h <= 360 else CHART_H['L'])
            fig.update_layout(legend_font_size=12, font_size=12, title_font_size=14)
        except Exception:
            pass
        return _orig_plotly_chart(fig, *a, config=cfg, **kw)
    _plotly_chart._mo_wrapped = 2
    st.plotly_chart = _plotly_chart
st.session_state['seen_onboard'] = True

# 2026-10-21 — 30초 투어로 재작성: 글로 읽는 설명서 → 탭 5단계 카드 + 바로가기 버튼.
#   옛 카드는 '화면은 셋'·'주봉 신호' 등 탭 재편 전 내용이 남아 있었다. 숫자(종목 수 등)는 일부러 안 넣는다 — 낡는다.
_OB_CSS = """
<style>
  .ob2 { font-family:'Pretendard',-apple-system,'Malgun Gothic',system-ui,sans-serif; color:var(--ink); }
  .ob2-hero { position:relative; overflow:hidden; border-radius:var(--radius,16px); padding:26px 28px 22px;
              background:linear-gradient(135deg,var(--hero,#111827) 0%,var(--hero-2,#1F2937) 100%); color:#F9FAFB; }
  .ob2-hero::after { content:""; position:absolute; right:-60px; top:-60px; width:220px; height:220px;
              border-radius:50%; background:radial-gradient(circle,rgba(126,162,255,.35),transparent 70%); }
  .ob2-kick { font-size:11px; font-weight:700; letter-spacing:.14em; color:#93B4FF; margin-bottom:8px; }
  .ob2-hero h3 { font-size:24px !important; font-weight:800 !important; letter-spacing:-.03em; margin:0 0 8px; color:#fff !important; line-height:1.3; }
  .ob2-hero p { font-size:14px; color:#D1D5DB; margin:0; max-width:640px; line-height:1.6; }
  .ob2-hero p b { color:#fff; }
  .ob2-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; position:relative; z-index:1; }
  .ob2-chip { font-size:12px; padding:5px 11px; border-radius:999px; border:1px solid rgba(255,255,255,.18);
              background:rgba(255,255,255,.06); color:#E5E7EB; }
  .ob2-sec { display:flex; align-items:baseline; justify-content:space-between; margin:22px 2px 10px; }
  .ob2-sec b { font-size:15px; font-weight:750; letter-spacing:-.02em; color:var(--ink); }
  .ob2-sec span { font-size:12px; color:var(--ink-3); }
  .ob2-step { height:100%; box-sizing:border-box; border:1px solid var(--line); border-radius:var(--radius-sm,10px);
              background:var(--surface); padding:14px 14px 12px; position:relative; }
  .ob2-step.on { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-2); }
  .ob2-top { display:flex; align-items:center; justify-content:space-between; margin-bottom:10px; }
  .ob2-n { width:24px; height:24px; border-radius:50%; background:var(--accent); color:#fff; font-size:12px;
           font-weight:800; display:flex; align-items:center; justify-content:center; font-family:var(--mono); }
  .ob2-t { font-size:11px; color:var(--ink-3); font-family:var(--mono); }
  .ob2-q { font-size:15px; font-weight:750; letter-spacing:-.02em; color:var(--ink); margin-bottom:2px; }
  .ob2-tab { font-size:12px; color:var(--accent); font-weight:650; margin-bottom:8px; }
  .ob2-d { font-size:12.5px; color:var(--ink-2); line-height:1.55; }
  .ob2-bar { height:4px; border-radius:4px; background:var(--line-2); margin-top:12px; overflow:hidden; }
  .ob2-bar i { display:block; height:100%; background:var(--accent); border-radius:4px; }
  .ob2-rules { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(220px,1fr)); }
  .ob2-rule { border-radius:var(--radius-sm,10px); padding:13px 15px; background:var(--surface);
              border:1px solid var(--line); font-size:12.5px; color:var(--ink-2); line-height:1.55; }
  .ob2-rule > b:first-child { display:block; font-size:13.5px; color:var(--ink); margin-bottom:3px; }
  .ob2-rule.warn { border-left:4px solid var(--warn); }
  .ob2-rule.pos  { border-left:4px solid var(--pos); }
  .ob2-rule.acc  { border-left:4px solid var(--accent); }
  .ob2-foot a { color:var(--accent); font-weight:650; text-decoration:none; }
  .ob2-foot { font-size:11.5px; color:var(--ink-3); margin-top:12px; line-height:1.6; }
</style>
"""

_OB_HERO = """
<div class="ob2"><div class="ob2-hero">
  <div class="ob2-kick">QUICK TOUR · 30 SEC</div>
  <h3>시장 → 종목 → 내 계좌,<br>위에서 아래로 좁혀 갑니다</h3>
  <p>공식 공시(DART · SEC EDGAR)와 시장 가격을 매일 자동으로 모아
     <b>지금 들어가도 되나 · 뭘 살까 · 얼마에 자를까</b>를 숫자로 답하는 리서치 도구입니다.</p>
  <div class="ob2-chips">
    <span class="ob2-chip">🇰🇷 🇺🇸 한 화면</span>
    <span class="ob2-chip">📄 공식 공시 기반</span>
    <span class="ob2-chip">⏱ 매일 자동 갱신</span>
    <span class="ob2-chip">🔒 보유 종목은 암호화</span>
  </div>
</div>
<div class="ob2-sec"><b>다섯 단계, 탭 순서 그대로</b><span>카드 아래 버튼으로 바로 이동</span></div></div>
"""

# (탭 이름, 질문, 설명, 예상 초) — 탭 이름은 아래 st.tabs 와 글자까지 같아야 버튼이 작동한다
_OB_STEPS = [
    ("🏠 종합", "이번 주, 들어가도 되나?", "코어 ON/OFF · 목표 현금비중 · 이번 주 할 일을 한 장에.", 5),
    ("🌍 매크로", "왜 그렇게 판정했나?", "글로벌 돈의 흐름과 경기 국면. 사계절·달걀 위 현재 위치.", 7),
    ("🔎 종목 발굴", "그럼 뭘 살까?", "이익이 가속하는 주도주 후보. 신호 목록이지 포트폴리오가 아닙니다.", 7),
    ("🔍 종목 분석", "이 종목, 진짜 맞나?", "코드 입력(NVDA · 005930) → 차트 · 재무 3표 · 멀티플 · AI 요약.", 6),
    ("🛡️ 내 포트폴리오", "내 계좌는 원칙대로인가?", "보유 종목을 손절선 · 비중 원칙에 대 봅니다. 비밀번호로만 열립니다.", 5),
]

_OB_RULES = """
<div class="ob2"><div class="ob2-sec"><b>지키는 원칙 세 줄</b><span>도구보다 먼저</span></div>
<div class="ob2-rules">
  <div class="ob2-rule acc"><b>판정 → 후보 → 검증</b>시장이 OFF 면 후보가 좋아 보여도 비중을 줄입니다.</div>
  <div class="ob2-rule warn"><b>손절가를 먼저</b>사기 전에 자를 가격부터. 기준은 진입가가 아니라 <b>보유 중 고점 대비</b>.</div>
  <div class="ob2-rule pos"><b>숫자는 확률</b>점수·신호는 보장이 아니며 매수 권유가 아닙니다. <code>-</code> 는 오류가 아니라 '데이터 없음'.</div>
</div>
<div class="ob2-foot">📲 매일 아침 요약은 텔레그램 <a href="https://t.me/buza_alarm_bot" target="_blank">@buza_alarm_bot</a> 으로 받을 수 있습니다.
   다시 보려면 이 칸을 언제든 펼치세요.</div></div>
"""


def _ob_go(name):
    st.session_state['main_tab'] = name


_ob_cur = st.session_state.get('main_tab') or _OB_STEPS[0][0]
with st.expander("⚡ 처음이신가요? — 30초 투어 (5단계 · 원칙 · 전체 설명서)",
                 expanded=_first_visit and not IS_MOBILE
                 and not (st.query_params.get('sym') or st.query_params.get('watch'))):   # 봇 링크로 온 사람은 바로 종목 화면
    st.html(_OB_CSS + _OB_HERO)
    _tot = sum(s[3] for s in _OB_STEPS)
    _acc = 0
    for _i, (_col, (_tab, _q, _d, _sec)) in enumerate(zip(st.columns(len(_OB_STEPS)), _OB_STEPS), 1):
        _acc += _sec
        with _col:
            st.html(_OB_CSS + f"""<div class="ob2"><div class="ob2-step{' on' if _tab == _ob_cur else ''}">
              <div class="ob2-top"><span class="ob2-n">{_i}</span><span class="ob2-t">~{_sec}s</span></div>
              <div class="ob2-q">{_q}</div><div class="ob2-tab">{_tab}</div>
              <div class="ob2-d">{_d}</div>
              <div class="ob2-bar"><i style="width:{round(_acc / _tot * 100)}%"></i></div></div></div>""")
            st.button("지금 여기" if _tab == _ob_cur else "열기 →", key=f'ob_go_{_i}', on_click=_ob_go,
                      args=(_tab,), width='stretch', disabled=_tab == _ob_cur)
    st.html(_OB_CSS + _OB_RULES)
    # 구 '프로젝트 종합' 탭에 있던 전체 사용설명서 — 탭을 없애면서 여기로 이관
    with st.expander("📚 전체 사용설명서 — 개념 사전 · 데이터 신뢰등급 · 자주 묻는 것"):
        try:
            st.markdown(Path('GUIDE.md').read_text(encoding='utf-8'))
        except Exception:
            st.caption("GUIDE.md 없음 — 저장소에서 확인.")

# 탭 순서 = 의사결정 순서. 내 돈이 어떻게 되고 있나(포트폴리오) → 뭘 살까(발굴) →
# 이게 맞나(분석) → 지금 사도 되나(매크로). 구루 인사이트는 2026-08-11 페이지에서 제거
# (구루 유튜브 요약은 2026-09-07 폐기 — buza-bot 으로 이관했다),
# 프로젝트 종합도 같은 날 제거하고 사용설명서만 상단 온보딩으로 이관했다.
# 💼 포트폴리오 탭은 2026-08-22 제거했다. 지운 이유는 세 가지다.
#   1. data/portfolio.json 이 전체 git 이력에 한 번도 존재한 적이 없다 —
#      가드레일·매도점검·종목별수익률은 입력이 없어 처음부터 빈 화면이었다.
#   2. 매도 점검 3룰이 이 프로젝트 자신의 백테스트와 충돌한다.
#      시간매도 26주 11.0% / 52주 11.3%, 고정손절 −20% 8.2% / −25% 16.9%,
#      분할익절(피라미딩 계열) 20.5~22.3% — 주도주의 −30% 트레일 25.4% 보다 전부 열등하다.
#      한 대시보드에 모순된 청산 체계가 둘 있었다.
#   3. 📒 성적표는 구 신호 6종(52주신고가·거래량폭발·5일라이딩·컵핸들·이평수렴·RSI/MACD)만
#      채점했다. 정작 주력인 주도주 L/S 는 채점 대상이 아니었다 — 안 쓰는 신호의 채점기였다.
# 목표는 주당 주식 공부 2시간, 시대의 주도주를 진득하게. 이 탭은 그 반대로 작동했다.
# 복원이 필요하면 커밋 이력에 그대로 남아 있다.
# 2026-10-10 — 🛡️ 포트폴리오 탭 복원. 08-22 에 '입력이 없어 빈 화면'이라는
#   이유로 지웠는데, 입력이 없던 진짜 원인은 **보유 종목을 넣을 화면 자체가
#   없었기 때문**이다(data/portfolio.json 은 git 이력에 한 번도 존재한 적이 없다).
#   엔진(guardrail.evaluate)과 헬퍼(_fetch_pf_price·_pf_trail)는 내내 살아 있었다.
# 2026-10-19 — 표의 종목·코드 칸 클릭 → 종목 분석 탭으로. 탭에 key 를 줘야 코드에서 고를 수 있다.
_MAIN_TAB_ANALYSIS = "🔍 종목 분석"


def _goto_analysis(code):
    code = str(code).strip()
    if code.upper() == str(st.session_state.get('analyze_sym') or '').upper():
        return              # 2026-10-21 — 같은 종목 더블클릭이 화면 전체를 두 번 다시 그리던 것(렉) 방지
    st.session_state['analyze_sym'] = str(code).strip().upper() if not str(code).strip().isdigit() else str(code).strip()
    st.session_state.pop('sym8_cands', None)
    st.session_state['main_tab'] = _MAIN_TAB_ANALYSIS


_tui.set_nav(_goto_analysis)


# ── 봇 → 대시보드 딥링크 (2026-10-20) ─────────────────────────────────
#   ?sym=TSLA          : 종목 분석 탭을 그 종목으로 바로 연다(봇 요약·리포트의 '대시보드에서 보기')
#   ?watch=SATL,AXTI   : 봇 감시 목록을 이 화면에 칩으로(서버에 저장하지 않는다 — 목록은 링크에만 실린다)
def _dl_code(x):
    x = str(x or '').strip().upper()
    for suf in ('.KS', '.KQ'):
        x = x.replace(suf, '')
    return x if re.fullmatch(r'[0-9A-Z.\-]{1,12}', x) else ''


_dl_sym = _dl_code(st.query_params.get('sym')) if st.query_params.get('diag') is None else ''
if _dl_sym and st.session_state.get('_dl_done') != _dl_sym:
    st.session_state['_dl_done'] = _dl_sym          # 같은 링크로 한 번만 — 그 뒤 사용자가 다른 종목을 고르면 그대로 둔다
    _goto_analysis(_dl_sym)
_dl_watch = [c for c in (_dl_code(t) for t in str(st.query_params.get('watch') or '').split(',')) if c][:30]
if _dl_watch:
    st.session_state['bot_watch'] = _dl_watch
    # 2026-10-20: 감시 목록 링크로 들어오면 대시보드 첫 화면이 아니라 '종목 분석'에서 첫 종목을 바로 연다
    #   (예전엔 칩만 종목 분석 탭 안에 깔아 둬서, 사용자 눈에는 그냥 대시보드가 열린 것으로 보였다)
    _wk = ','.join(_dl_watch)
    if not _dl_sym and st.session_state.get('_dl_watch_done') != _wk:
        st.session_state['_dl_watch_done'] = _wk
        _goto_analysis(_dl_watch[0])
_tui.set_fx(lambda: _usdkrw())   # 한국 종목이 섞인 표의 시총($B) → 억원 (2026-10-19)


# ── 이번 주 판정 — 단일 출처 (2026-10-21) ─────────────────────────────
#   results/macro.json(CI 06:00, verdict.py) 을 먼저 읽고, 없거나 낡았으면 **같은 함수**로 라이브 계산.
#   상단 배지·🏠 종합·🌍 매크로·종목분석 M·시황 리포트·주간 포트폴리오·executor 가 전부 이 값을 쓴다.
def _verdict_now():
    v = load_json(Path('results/macro.json')) or {}
    a = _V.age_days(v)
    if v.get('core') and a is not None and a <= 4:
        return dict(v, _src='file')
    px, kx = fetch_index_history('SPY', 400), fetch_index_history('KS11', 400)
    sw = _V.core_switch(px.iloc[:, 0]) if not px.empty else {}
    kw = _V.core_switch(kx.iloc[:, 0]) if not kx.empty else {}
    return dict(asof=sw.get('date'), core=sw, kr_core=kw, alloc=_V.alloc(sw.get('on') if sw else None),
                canslim_m=dict(US=_V.market_dir(sw), KR=_V.market_dir(kw)), phase=v.get('phase') or {},
                greed=v.get('greed') or {}, flow=v.get('flow') or {}, econ=v.get('econ') or {},
                history=v.get('history') or [], changed=False, generated=v.get('generated'),
                _src='live', _file_asof=v.get('asof'))


@st.cache_data(ttl=600, show_spinner=False)
def _ops_counts():
    """(정답 점검 틀림 수, 갱신 정지 수) — 상단 배지·종합 탭용. 10분 캐시(파일 수십 개를 읽는다)."""
    try:
        import tools.known_answers as _ka
        ka = sum(1 for r in _ka.run() if not r['ok'])
    except Exception:
        ka = None
    try:
        import data_freshness as _dfm
        stl = sum(1 for r in _dfm.statuses() if r['state'] != 'ok')
    except Exception:
        stl = None
    return ka, stl


def _status_bar(v):
    """모든 탭 위 한 줄 — 같은 판정을 어느 탭에서 보든 같은 값으로."""
    c, a, ph, g = v.get('core') or {}, v.get('alloc') or {}, v.get('phase') or {}, v.get('greed') or {}
    if c:
        sw = (f"<b style='color:{'#15803d' if c['on'] else '#b91c1c'}'>코어 {'ON' if c['on'] else 'OFF'}</b> "
              f"S&P500 200일선 {c['gap']:+.1f}%")
    else:
        sw = "<b style='color:#6b7280'>코어 판정 불가</b>"
    al = (f"목표 코어 {a['core_now']} · 위성 {a['satellite']} · 현금 {a['cash_total']}" if a.get('cash_total') is not None else "목표 비중 —")
    ka, stl = _ops_counts()
    bad = (ka or 0) + (stl or 0)
    dat = ("<span style='color:#15803d'>데이터 정상</span>" if bad == 0 and ka is not None
           else f"<span style='color:#b91c1c'>데이터 점검 {bad}건</span>")
    bits = [sw, al]
    if ph.get('name'):
        bits.append(f"국면 {ph.get('emoji', '')} {ph['name']} <span style='color:#9ca3af'>(참고)</span>")
    if g.get('word'):
        bits.append(f"경고 {g.get('n', 0)}/3 <span style='color:#9ca3af'>(참고)</span>")
    bits += [dat, f"<span style='color:#9ca3af'>{v.get('asof') or '-'} 종가 기준</span>"]
    st.markdown("<div style='font-size:13px;padding:7px 12px;border:1px solid #e5e7eb;border-radius:8px;"
                "background:#fafafa;color:#374151;margin:2px 0 6px'>" + " &nbsp;·&nbsp; ".join(bits) + "</div>",
                unsafe_allow_html=True)
    if v.get('changed'):
        st.warning(f"⚠️ 이번 주 코어 스위치 전환 — {'OFF → ON: 코어 복귀' if c.get('on') else 'ON → OFF: 코어를 현금으로'}. 🏠 종합 탭 '할 일' 참고")


# 자리만 잡고 맨 끝에서 채운다 — 라이브 계산(macro.json 이 낡았을 때)이 아래 탭 전부를 붙잡지 않게
_status_slot = st.container()
_VERDICT = {}

# 2026-10-21 탭 재편 — 톱다운 의사결정 순서: 이번 주 판정·할 일·시황(종합) → 왜(매크로) → 무엇을(발굴)
#   → 이게 맞나(분석) → 내 계좌(포트폴리오). 📰 시황 리포트는 매일 읽는 요약이라 종합으로 흡수했다.
tab_home, tab4, tab_screen, tab7, tab_pf = st.tabs(key='main_tab', on_change='rerun', tabs=[
    "🏠 종합", "🌍 매크로", "🔎 종목 발굴", "🔍 종목 분석", "🛡️ 내 포트폴리오"])
tab_rep = tab_home
try:
    import access as _acc0
    _acc0.track_session(st.session_state.get('main_tab') or '🏠 종합')   # 2026-10-21 사용량 측정(키 없으면 무동작)
except Exception:
    pass

# 종목 발굴 — 발굴·분석·추천을 한 탭에 서브탭으로 통합
# 순서 주의: 서브탭 핸들(t_gain…)은 아래 6개 블록이 전부 의존하므로 **무조건 먼저** 만든다.
# 매크로 스트립처럼 실패할 수 있는 계산을 먼저 두면, 그게 죽는 순간 핸들이 미정의가 되어
# 서브탭 6개가 통째로 NameError로 날아간다. 스트립은 자리(container)만 잡아두고 뒤에서 채운다.
_MDDM = {}

with tab_screen:                           # 데이터를 건드리지 않는 순수 레이아웃 → 가드 불필요
    _GMKT = st.radio("시장", ["전체", "KR", "US"], horizontal=True, key="screen_mkt")
    # 2026-10-21 매크로 요약 스트립 삭제 — 같은 판정이 모든 탭 위 상단 배지에 있다(중복 제거)
    # 서브탭 순서 = 신뢰도 순서. 검증된 규칙(주도주·CANSLIM)을 앞에, 참고용 탐색을 뒤에.
    # 성적표는 2026-08-11 포트폴리오 탭으로 이관했다(실적 공시는 한 곳에서).
    # 2026-08-12 통폐합: ⚡타이밍 발굴 서브탭 제거.
    #   · 계절성·고점대비 낙폭 → 🔥상승 상위의 필터로 흡수(같은 데이터를 두 화면에서 보던 중복)
    #   · 🧮 사이징 계산기 → 💼포트폴리오로 이동(발굴이 아니라 집행 단계의 도구다)
    # 2026-10-23 재편(차니): 종목 발굴 = '매수 관점의 보물찾기'. 왼쪽 = 가격이 먼저 말하는 것,
    #   가운데 = 둘이 겹치는 결론, 오른쪽 = 숫자(펀더멘털)가 먼저 말하는 것. 그룹 3개 × 하위 탭.
    #   핸들 이름(t_gain·t_52·t_lead·tab3·t_turn·t_value)은 아래 블록들이 그대로 쓰므로 바꾸지 않는다.
    st.caption("🔥 모멘텀 = 시장이 먼저 고른 종목 · 🚀 주도주 = 모멘텀 × 펀더멘털 교집합(결론) "
               "· 💎 펀더멘털 = 숫자가 먼저 좋아진 종목 — 시장 필터는 위 하나로 전 서브탭 공통")
    _cand_slot = st.container()           # 📌 후보 바구니 — 공통 표 함수가 정의된 뒤 채운다
    _g_mom, _g_core, _g_fund = st.tabs(["🔥 모멘텀", "🚀 주도주", "💎 펀더멘털"])
    with _g_mom:
        t_gain, t_52 = st.tabs(["상승 상위", "52주 신고가"])
    with _g_core:
        t_core, tab3 = st.tabs(["교집합 후보", "CANSLIM"])
    with _g_fund:
        t_lead, t_turn, t_value = st.tabs(["이익가속", "흑자전환", "가치 발굴 (KR)"])

# 서브탭 공통 조회맵 — 실패해도 빈 맵으로 진행(표의 부가 열만 '-'가 된다)
try:
    _MDDM = _mdd_map()            # sym → 고점대비 낙폭
except Exception:
    _MDDM = {}

# ── 종목 목록 표 표준 (2026-10-26) ─────────────────────────────────────
# 모든 서브탭의 종목 목록은 같은 뼈대: [No.·종목·코드·(시장)·시총·업종] + 탭 고유 ≤5 + [RS·1개월·52주고점대비·매출YoY·영업익YoY·PER].
# 공통 열은 common_metrics 한 곳에서만 계산한다 — 탭마다 다른 정의·이름이 생기지 않게. 정의는 common_metrics.COLS.
import common_metrics as _cm


@st.cache_data(ttl=3600, show_spinner=False)
def _cm_base():
    return _cm.build(_usdkrw())


try:
    _CMB, _CMM = _cm_base()
except Exception:
    _CMB, _CMM = pd.DataFrame(), {}


# ── 📌 후보 등록 (2026-10-26) — 발굴 표에서 고른 종목을 한 바구니에. 다음 단계(매매판단·주간 주문표)의 입력 ──
#   로그인하면 내 계정(user_store, 암호화)에 같이 저장되고, 아니면 이 세션에만 남는다.
def _cand_store_load():
    if 'cand_list' in st.session_state:
        return st.session_state['cand_list']
    st.session_state['cand_list'] = []
    try:
        import access as _accm
        import user_store as _usm
        _em = _accm.email()
        if _em and _usm.ready():
            _d = _usm.load(_em) or {}
            st.session_state['cand_list'] = _d.get('candidates') or []
            st.session_state['_cand_blob'] = {k: v for k, v in _d.items() if not k.startswith('_')}
    except Exception:
        pass
    return st.session_state['cand_list']


def _cand_store_save(lst):
    st.session_state['cand_list'] = lst
    try:
        import access as _accm
        import user_store as _usm
        _em = _accm.email()
        if _em and _usm.ready():
            _blob = st.session_state.get('_cand_blob')
            if _blob is None:                       # 포트폴리오를 덮지 않게 먼저 읽는다
                _blob = {k: v for k, v in (_usm.load(_em) or {}).items() if not k.startswith('_')}
            _blob['candidates'] = lst
            _usm.save(_em, _blob)
            st.session_state['_cand_blob'] = _blob
            return '내 계정에 저장됨'
    except Exception as e:
        return f'⚠️ 계정 저장 실패 — 이 세션에만 남습니다 ({str(e)[:60]})'
    return '이 세션에만 남습니다(로그인하면 계정에 저장)'


def _cand_register(rows, key: str):
    """표 아래 '📌 후보로 담기' — 어느 탭에서 담았는지(출처 탭)·담은 날을 같이 남긴다."""
    rows = [r for r in (rows.to_dict('records') if isinstance(rows, pd.DataFrame) else rows) if r.get('코드')]
    if not rows:
        return
    have = {c['code'] for c in _cand_store_load()}
    opts = {f"{r.get('종목') or r['코드']} ({r['코드']})": r for r in rows if str(r['코드']) not in have}
    with st.expander(f"📌 후보로 담기 — 지금 바구니 {len(have)}종", expanded=False):
        pick = st.multiselect("담을 종목", list(opts), key=f'cand_pick_{key}', placeholder='종목을 고르세요')
        if st.button("담기", key=f'cand_btn_{key}', disabled=not pick):
            lst = list(_cand_store_load())
            for k in pick:
                r = opts[k]
                lst.append({'code': str(r['코드']), 'name': r.get('종목') or str(r['코드']), 'from': key,
                            'added': datetime.now().strftime('%Y-%m-%d')})
            st.session_state['cand_msg'] = f"✅ {len(pick)}종 담음 — " + _cand_store_save(lst)
            st.rerun()


_CAND_FROM = {'core': '교집합', 'gain': '상승 상위', 'h52': '52주 신고가', 'canslim': 'CANSLIM',
              'accel': '이익가속', 'turn': '흑자전환', 'value': '가치 발굴'}


def _cand_panel():
    """종목 발굴 맨 위 — 담아 둔 후보를 같은 표준 표로."""
    lst = _cand_store_load()
    with st.expander(f"📌 후보 바구니 — {len(lst)}종", expanded=bool(st.session_state.get('cand_msg'))):
        if st.session_state.get('cand_msg'):
            st.caption(st.session_state.pop('cand_msg'))
        if not lst:
            st.caption("아래 각 표 밑 '📌 후보로 담기'에서 종목을 담으면 여기에 모입니다. 다음 단계(🎯 매매판단·주간 주문표)의 입력입니다.")
            return
        _r = pd.DataFrame([{'코드': c['code'], '종목': c.get('name'), '담은 탭': _CAND_FROM.get(c.get('from'), c.get('from')),
                            '담은 날': c.get('added')} for c in lst])
        _std_table(_r, ['담은 탭', '담은 날'], src='내가 담은 후보', note='담은 순서')
        rm = st.multiselect("뺄 종목", [f"{c.get('name')} ({c['code']})" for c in lst], key='cand_rm')
        if st.button("빼기", key='cand_rm_btn', disabled=not rm):
            keep = [c for c in lst if f"{c.get('name')} ({c['code']})" not in rm]
            st.session_state['cand_msg'] = f"🗑 {len(lst) - len(keep)}종 뺌 — " + _cand_store_save(keep)
            st.rerun()


def _std_table(rows, specific, *, sort_by=None, ascending=False, src=None, path=None,
               column_config=None, styler=None, note=None):
    """탭의 종목 목록을 표준 뼈대로 그린다. rows = DataFrame(코드 + 탭 고유 열, 선택: 종목)."""
    if not isinstance(rows, pd.DataFrame):
        rows = pd.DataFrame(rows)
    df = _cm.frame(rows, _CMB, specific, market=_GMKT, sort_by=sort_by, ascending=ascending)
    if df.empty:
        st.info("조건에 맞는 종목이 없습니다.")
        return df
    cfg = _cm.help_config(st, df)
    cfg.update(column_config or {})
    if src:
        _tsrc(src + ' · ' + _cm.source_label(_CMM), path=path)
    import sys as _sys
    _fr = _sys._getframe(1)                       # 부른 자리(줄 번호)가 표의 필터 키 — 서브탭마다 달라야 한다
    if getattr(st, '_tbl_ver', 0) >= 7:
        st.dataframe(df, hide_index=True, column_config=cfg, tkey=f'std:{_fr.f_lineno}')
    else:                                          # 옛 래퍼가 메모리에 남은 프로세스 — tkey 를 모른다
        st.dataframe(df, hide_index=True, column_config=cfg, key=f'std_{_fr.f_lineno}')
    cap = cap_caption()
    if not _CMM.get('rs_exact', True):
        cap += " · ⚠️ RS 는 9개월 수익률이 다음 주간 갱신부터 들어와 그 전까지 3·6·12개월로 근사"
    st.caption(cap + (f" · {note}" if note else ""))
    return df

with _cand_slot, guard('후보 바구니'):
    _cand_panel()

# ════════════════════════════════════════════════════════════════════
# 종목 발굴 서브탭 콘텐츠: 주도주(t_lead) · 계절성(t_seas) · MDD 바닥(t_mdd)
# ════════════════════════════════════════════════════════════════════

# ── 🚀 주도주 · 교집합 후보 (2026-10-23 신설) ─────────────────────────
# 정의: RS 강도 상위 20% × (이번 주 이익가속 또는 최근 흑자전환). 52주 신고가 '전에' 걸리게 하려는 것.
# ⚠️ 검증 전이다 — research/rs_accel_bt.py(CI research-rs) 결과가 합격일 때만 '규칙'으로 승격한다.
with t_core, guard('주도주 교집합'):
    _rj = load_json(Path('results/returns.json')) or {}
    _acj = load_json(Path('results/leaders_accel.json')) or {}
    _taj = load_json(Path('results/turnaround_latest.json')) or {}
    _bt = load_json(Path('results/rs_accel_bt.json')) or {}
    _btv = ((_bt.get('variants') or {}).get('rs80_fund') or {})
    if _btv.get('verdict', {}).get('pass'):
        st.success(f"✅ 백테스트 합격 ({_bt.get('factor_ver')} · {_bt.get('period', ['', ''])[0]}~) — "
                   f"CAGR {_btv['CAGR']}% · MDD {_btv['MDD']}% · SPY {_bt['SPY']['CAGR']}%")
    elif _btv:
        st.warning(f"🧪 **백테스트 불합격 — 참고용 후보** ({_bt.get('factor_ver')} · {(_bt.get('period') or ['-'])[0]}~): 이 정의를 그대로 담으면 "
                   f"CAGR {_btv.get('CAGR')}% · MDD {_btv.get('MDD')}% (SPY {(_bt.get('SPY') or {}).get('CAGR')}%). "
                   "성적이 나쁜 신호도 지우지 않고 보여줍니다.")
    else:
        st.info("🧪 **검증 전 후보입니다.** RS × 이익가속/흑자전환 백테스트(전 종목·상폐 포함)가 끝나면 "
                "이 자리에 합격/불합격이 표시됩니다. 그 전까지는 '살 종목'이 아니라 '볼 종목' 목록입니다.")
    st.caption("**RS** = 3개월 40% · 6·9·12개월 각 20% 가중 수익률의 시장 내 백분위(99 = 최상위, 백테스트와 같은 식) · "
               "**근거** = '이익 가속 중'(매출·영업이익 성장률 동시 가속, 주간 급등 조건 없음, 🇺🇸) 또는 "
               "'흑자전환'(이번 분기 영업흑자 + 전년 같은 분기 영업적자, 🇰🇷🇺🇸) — 백테스트 rs80_fund 와 같은 정의")
    if _CMB.empty:
        st.warning("기간 수익률 데이터 없음 — returns.json 갱신(weekly-profile) 후 다시 열어 주세요.")
    else:
        _acc = {r['sym']: r for r in (_acj.get('acc_now') or [])}
        _tas = {r['sym']: r for r in (_taj.get('stocks') or []) if r.get('status') == '흑자전환완료'}
        _rsmin = st.slider("RS 하한", 50, 95, 80, 5, key="core_rs")
        _rows = []
        for sym, r in _CMB[_CMB.RS >= _rsmin].iterrows():
            _a, _t = _acc.get(sym), _tas.get(sym)
            if not (_a or _t) or (_GMKT != '전체' and r['시장'] != _GMKT):
                continue
            _rows.append({'코드': sym, '종목': r['종목'],
                          '근거': ' + '.join(x for x, y in (('이익 가속 중', _a), ('흑자전환', _t)) if y),
                          '이익가속(%p)': (_a or {}).get('oia'), '매출가속(%p)': (_a or {}).get('rva'),
                          '_n': 2 if (_a and _t) else 1, '_rs': r['RS']})
        _rows.sort(key=lambda x: (-x['_n'], -x['_rs']))
        _c = st.columns(3)
        _c[0].metric("교집합 후보", f"{len(_rows):,}종")
        _c[1].metric("이익 가속 중 (🇺🇸)", f"{len(_acc):,}종" if _acc else "—")
        _c[2].metric("흑자전환 (🇰🇷🇺🇸)", f"{len(_tas):,}종")
        if _rows:
            _std_table(pd.DataFrame(_rows), ['근거', '이익가속(%p)', '매출가속(%p)'],
                       src='leaders_accel.json(이익 가속 중) · turnaround_latest.json(흑자전환)',
                       path='results/returns.json',
                       note="정렬: 근거 2개 → RS 높은 순")
            _cand_register(_rows, 'core')
        else:
            st.info("조건을 모두 통과한 종목이 없습니다 — RS 하한을 낮춰 보세요.")

    # ── 🔬 백테스트 상세 (2026-10-24 차니 요청) — 판정 숫자가 어떻게 나왔는지 100에서부터 따라가게 ──
    _dt = load_json(Path('results/rs_accel_detail.json')) or {}
    with st.expander("🔬 백테스트 상세 — 100으로 시작하면 실제로 무슨 일이 있었나", expanded=False):
        if not _dt.get('variants'):
            st.info("상세 결과를 만드는 중입니다(GitHub 서버의 research-rs 작업). 끝나면 이 자리에 자동으로 나옵니다.")
        else:
            _ru = _dt.get('rules') or {}
            st.markdown("**운용 규칙** (판정 숫자와 똑같은 규칙)\n"
                        + "\n".join(f"- **{k}** — {v}" for k, v in [
                            ('시작', _ru.get('start')), ('자산배분', _ru.get('slots')), ('매수', _ru.get('entry')),
                            ('만석일 때', _ru.get('full')), ('손절·익절', _ru.get('exit')),
                            ('리밸런싱', _ru.get('rebalance')), ('현금', _ru.get('cash')),
                            ('비용', _ru.get('cost')), ('대표 회차', _ru.get('seeds'))] if v))
            _vk = {v['label']: k for k, v in sorted(_dt['variants'].items(), key=lambda kv: kv[0] != 'rs80_fund')}
            _vsel = _vk[st.radio("전략", list(_vk), horizontal=True, key="core_bt_v")]
            _V = _dt['variants'][_vsel]; _sm = _V['summary']; _sp = _dt['spy']
            _m = st.columns(6)
            _m[0].metric("100 →", f"{_sm['final']:,.0f}", f"SPY {_sm['spy_final']:,.0f}", delta_color="off")
            _m[1].metric("연수익(CAGR)", f"{_V['stats']['CAGR']}%", f"SPY {_sp['stats']['CAGR']}%", delta_color="off")
            _m[2].metric("최대낙폭(MDD)", f"{_V['stats']['MDD']}%", f"SPY {_sp['stats']['MDD']}%", delta_color="off")
            _m[3].metric("거래 수 · 승률", f"{_sm['trades']:,}건", f"승률 {_sm['win_rate']}%", delta_color="off")
            _m[4].metric("평균 이익 / 손실", f"{_sm['avg_win']:+.0f}% / {_sm['avg_loss']:+.0f}%")
            _m[5].metric("평균 보유", f"{_sm['avg_wk']:.0f}주", f"평균 {_sm['avg_pos']:.0f}종목 · 현금 {_sm['avg_cash']:.0f}%",
                         delta_color="off")
            st.caption(f"기간 {_dt['period'][0]} ~ {_dt['period'][1]}"
                       + (f" ({_dt['eval_start_reason']})" if _dt.get('eval_start_reason') else "")
                       + f" · 시계열 {_dt['factor_ver']} · {_dt['universe']:,}종 · "
                       f"대표 회차 = 10회 CAGR {_V['seed_cagrs'][0]}~{_V['seed_cagrs'][-1]}% 중 중앙값에 가장 가까운 회차 · "
                       f"상위 10개 거래가 전체 수익의 {_sm['top10_share']:.0f}%")
            _x = pd.DatetimeIndex(_dt['dates'])
            _f = go.Figure()
            _f.add_trace(go.Scatter(x=_x, y=_V['curve'], mode='lines', name='전략', line=dict(color='#0e5a6b', width=1.8),
                                    hovertemplate='%{x|%Y-%m-%d}<br>전략 %{y:,.0f}<extra></extra>'))
            _f.add_trace(go.Scatter(x=_x, y=_sp['curve'], mode='lines', name='SPY', line=dict(color='#9ca3af', width=1.4),
                                    hovertemplate='%{x|%Y-%m-%d}<br>SPY %{y:,.0f}<extra></extra>'))
            for _e in _V['dd5']:
                _f.add_vrect(x0=_e['peak'], x1=_e['recover'] or _dt['dates'][-1], fillcolor='#a03028', opacity=0.07,
                             line_width=0)
            _f.update_yaxes(type='log', title='자산(시작 100, 로그)')
            _f.update_layout(height=320, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                             title="자산 곡선 — 빨간 띠 = 낙폭 상위 5회",
                             legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
            st.plotly_chart(_f, use_container_width=True)

            st.markdown("**낙폭 상위 5회** — 고점에서 바닥까지, 다시 고점을 넘기까지")
            _ddr = []
            for _n, (_e, _se) in enumerate(zip(_V['dd5'], _sp['dd5'] + [None] * 5), 1):
                _ddr.append({'순위': _n, '고점': _e['peak'], '바닥': _e['trough'], '회복': _e['recover'] or '미회복',
                             '낙폭(%)': _e['depth'], '하락(주)': _e['wk_down'], '회복까지(주)': _e['wk_total'],
                             'SPY 같은 순위 낙폭(%)': (_se or {}).get('depth'),
                             'SPY 고점→바닥': f"{_se['peak']} → {_se['trough']}" if _se else '-'})
            _tsrc('research/rs_accel_detail.py (GitHub Actions research-rs)', path='results/rs_accel_detail.json')
            st.dataframe(pd.DataFrame(_ddr), use_container_width=True, hide_index=True, filters=False,
                         column_config={'낙폭(%)': st.column_config.NumberColumn(format='%.1f'),
                                        'SPY 같은 순위 낙폭(%)': st.column_config.NumberColumn(format='%.1f')})

            st.markdown("**연도별 수익률**")
            _yr = sorted(set(_V['yearly']) | set(_sp['yearly']))
            _yrow = [{'연도': str(y), '전략(%)': _V['yearly'].get(str(y), _V['yearly'].get(y)),
                      'SPY(%)': _sp['yearly'].get(str(y), _sp['yearly'].get(y))} for y in _yr]
            for _r in _yrow:
                _r['차이(%p)'] = (round(_r['전략(%)'] - _r['SPY(%)'], 1)
                                 if _r['전략(%)'] is not None and _r['SPY(%)'] is not None else None)
            _tsrc('research/rs_accel_detail.py', path='results/rs_accel_detail.json')
            st.dataframe(pd.DataFrame(_yrow), use_container_width=True, hide_index=True, filters=False,
                         column_config={c: st.column_config.NumberColumn(format='%+.1f')
                                        for c in ('전략(%)', 'SPY(%)', '차이(%p)')})

            st.markdown("**거래 원장** — 이 회차에서 실제로 사고판 모든 종목")
            _tr = pd.DataFrame([{'종목': t['name'] or t['sym'], '코드': t['sym'], '매수일': t['buy'], '매도일': t['sell'],
                                 '매수가($)': t['buy_px'], '보유중 최고가($)': t['peak_px'], '매도가($)': t['sell_px'],
                                 '보유(주)': t['wk'], '수익률(%)': t['ret'], '매수 비중(%)': t['weight'],
                                 '계좌 기여(%p)': t['contrib'], '청산 사유': t['why']} for t in _V['trades']])
            _tsrc('research/rs_accel_detail.py', path='results/rs_accel_detail.json')
            st.dataframe(_tr, use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_tr)),
                         column_config={'수익률(%)': st.column_config.NumberColumn(format='%+.1f'),
                                        '계좌 기여(%p)': st.column_config.NumberColumn(format='%+.2f'),
                                        '매수가($)': st.column_config.NumberColumn(format='%,.2f'),
                                        '보유중 최고가($)': st.column_config.NumberColumn(format='%,.2f'),
                                        '매도가($)': st.column_config.NumberColumn(format='%,.2f'),
                                        '매수 비중(%)': st.column_config.NumberColumn(format='%.1f')})
            st.caption("계좌 기여 = (매도 금액 − 매수 금액 − 비용) ÷ 매수 시점 총자산. '보유 중' = 기간 끝까지 들고 있던 종목(마지막 주 가격으로 평가). "
                       "가격은 수정주가(분할 반영)라 당시 실제 호가와 다를 수 있습니다.")

    # ── 🧪 RS순 강건성 (2026-10-24 차니 지정) — 144개 조합 전부 + 시작 월 골라 100 으로 다시 맞춰 보기 ──
    _rb = load_json(Path('results/robust_rs.json')) or {}
    with st.expander("🧪 RS순 우선 강건성 — 144개 조합 전부 · 시작 시점 직접 선택", expanded=False):
        if not _rb.get('grid'):
            st.info("격자 결과를 만드는 중입니다(GitHub 서버 research-rs 작업). 끝나면 이 자리에 자동으로 나옵니다.")
        else:
            _sm = _rb['summary']; _spc = _rb['spy']['stats']['CAGR']
            st.caption("**질문:** 교집합을 '동시 신호 RS 높은 순'으로 채운 24.7%가 우연인가? RS 정의 3 × 슬롯 3 × 청산 16 = "
                       f"{_sm['n']}개 조합을 한 번에 전부 돌렸다(골라 보여주지 않음). 상폐충격 = 보유 종목이 연 1% 확률로 0원이 되는 가정, 3회 중앙값.")
            _m = st.columns(4)
            _m[0].metric("SPY 초과 조합", f"{_sm['beat_spy']} / {_sm['n']}", f"SPY {_spc}%", delta_color="off")
            _m[1].metric("상폐충격 후에도 초과", f"{_sm['beat_spy_shock']} / {_sm['n']}")
            _m[2].metric("조합 중앙 CAGR", f"{_sm['median_cagr']:.1f}%", f"충격 후 {_sm['median_shock']:.1f}%", delta_color="off")
            _m[3].metric("RS순 − 무작위 순서", f"{_sm['rs_minus_ref']:+.1f}%p", "같은 정의·슬롯, 고점 -20% 기준 중앙", delta_color="off")
            _ex = _rb['exits']; _rsn = _rb['rs_defs']
            _met = st.radio("표에 보일 값", ["SPY 대비 CAGR 차이(%p)", "상폐충격 후 SPY 대비(%p)", "MDD(%)", "샤프"],
                            horizontal=True, key="rb_met")
            _G = pd.DataFrame(_rb['grid'])
            _val = {"SPY 대비 CAGR 차이(%p)": _G.CAGR - _spc, "상폐충격 후 SPY 대비(%p)": _G.shock1 - _spc,
                    "MDD(%)": _G.MDD, "샤프": _G.Sharpe}[_met]
            _G['_v'] = _val.round(2)
            _G['_c'] = _G.rs.map({'w': '가중', 'r13': '13주', 'm121': '12-1'}) + ' · ' + _G.slots.astype(str) + '칸'
            _pv = _G.pivot_table(index='exit', columns='_c', values='_v')
            _pv = _pv.reindex(index=list(_ex)).rename(index=_ex)
            _pv = _pv[[c for r in ('가중', '13주', '12-1') for c in _pv.columns if c.startswith(r)]]
            _pv.index.name = '청산 규칙'
            _tsrc('research/robust_rs.py (GitHub Actions research-rs)', path='results/robust_rs.json')
            st.dataframe(_pv.reset_index(), use_container_width=True, hide_index=True, filters=False,
                         color=_met != "MDD(%)" and _met != "샤프",
                         column_config={c: st.column_config.NumberColumn(format='%+.1f' if '%p' in _met else '%.2f')
                                        for c in _pv.columns})
            st.caption("RS 정의 — " + " · ".join(f"**{ {'w': '가중', 'r13': '13주', 'm121': '12-1'}[k] }** = {v}" for k, v in _rsn.items())
                       + ". 진입 문턱(RS ≥ 80)과 우선순위가 같은 정의를 쓴다. 칸 = 최대 보유 종목 수(비중 = 1/칸).")

            st.markdown("**조합 하나 골라 보기** — 시작 월을 고르면 그 달 첫 주 자산을 100 으로 다시 맞춘다")
            _c = st.columns(4)
            _rk = _c[0].selectbox("RS 정의", list(_rsn), format_func=lambda k: {'w': '가중(현행)', 'r13': '13주', 'm121': '12-1개월'}[k],
                                  key="rb_rs")
            _ns = _c[1].selectbox("최대 종목 수", _rb['slots'], index=1, key="rb_ns")
            _ek = _c[2].selectbox("청산", list(_ex), index=list(_ex).index('t20'), format_func=lambda k: _ex[k], key="rb_ex")
            _dx = pd.DatetimeIndex(_rb['dates'])
            _months = sorted({(t.year, t.month) for t in _dx})
            _mo = _c[3].selectbox("시작 월", _months, format_func=lambda m: f"{m[0]}-{m[1]:02d}", key="rb_mo")
            _cv = pd.Series(_rb['curves'][f"{_rk}|{_ns}|{_ek}"], index=_dx)
            _sp = pd.Series(_rb['spy']['curve'], index=_dx).ffill()
            _i0 = int(np.argmax((_dx.year == _mo[0]) & (_dx.month == _mo[1])))
            _a = _cv.iloc[_i0:] / _cv.iloc[_i0] * 100; _b = _sp.iloc[_i0:] / _sp.iloc[_i0] * 100
            _yr = max(1e-9, (_a.index[-1] - _a.index[0]).days / 365.25)
            _cg = lambda x: ((x.iloc[-1] / x.iloc[0]) ** (1 / _yr) - 1) * 100
            _md = lambda x: (x / x.cummax() - 1).min() * 100
            _gr = next(r for r in _rb['grid'] if r['key'] == f"{_rk}|{_ns}|{_ek}")
            _m = st.columns(5)
            _m[0].metric("100 →", f"{_a.iloc[-1]:,.0f}", f"SPY {_b.iloc[-1]:,.0f}", delta_color="off")
            _m[1].metric("연수익(이 기간)", f"{_cg(_a):.1f}%", f"SPY {_cg(_b):.1f}%", delta_color="off")
            _m[2].metric("최대낙폭(이 기간)", f"{_md(_a):.1f}%", f"SPY {_md(_b):.1f}%", delta_color="off")
            _m[3].metric("거래 · 평균 보유", f"{_gr['trades']:,}건", f"{_gr['avg_wk']}주 · 승률 {_gr['win']}%", delta_color="off")
            _m[4].metric("상폐충격 후 CAGR(전체)", f"{_gr['shock1']:.1f}%", f"충격 없음 {_gr['CAGR']:.1f}%", delta_color="off")
            _f = go.Figure()
            _f.add_trace(go.Scatter(x=_a.index, y=_a.values, mode='lines', name='전략', line=dict(color='#0e5a6b', width=1.8),
                                    hovertemplate='%{x|%Y-%m-%d}<br>전략 %{y:,.0f}<extra></extra>'))
            _f.add_trace(go.Scatter(x=_b.index, y=_b.values, mode='lines', name='SPY', line=dict(color='#9ca3af', width=1.4),
                                    hovertemplate='%{x|%Y-%m-%d}<br>SPY %{y:,.0f}<extra></extra>'))
            _f.update_yaxes(type='log', title='자산(시작 월 = 100, 로그)')
            _f.update_layout(height=300, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                             title=f"{_mo[0]}-{_mo[1]:02d} 시작 · {_rsn[_rk]} · {_ns}칸 · {_ex[_ek]}",
                             legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
            st.plotly_chart(_f, use_container_width=True)
            st.markdown("**연도별 수익률 — 처음부터**")
            _yrow = []
            for _y, _g in _cv.groupby(_cv.index.year):
                _gs = _sp.loc[_g.index]
                if len(_g) < 5:
                    continue
                _yrow.append({'연도': str(_y), '전략(%)': round((_g.iloc[-1] / _g.iloc[0] - 1) * 100, 1),
                              'SPY(%)': round((_gs.iloc[-1] / _gs.iloc[0] - 1) * 100, 1)})
            for _r in _yrow:
                _r['차이(%p)'] = round(_r['전략(%)'] - _r['SPY(%)'], 1)
            _tsrc('research/robust_rs.py', path='results/robust_rs.json')
            st.dataframe(pd.DataFrame(_yrow), use_container_width=True, hide_index=True, filters=False,
                         column_config={c: st.column_config.NumberColumn(format='%+.1f') for c in ('전략(%)', 'SPY(%)', '차이(%p)')})
            st.caption(f"기간 {_rb['period'][0]} ~ {_rb['period'][1]} · 시계열 {_rb['factor_ver']} · {_rb['universe']:,}종 · "
                       "연도별 첫 해는 평가 시작 주부터. 주봉 종가 체결·1주 지연·편도 0.3%·현금 기준금리 이자.")

    # ── 🛡️ 손절선 올려 잡기·재매수·냉각·불타기 (2026-10-24 차니 설계) — 810조합 전부 ──
    _lc = load_json(Path('results/loss_cut_grid.json')) or {}
    with st.expander("🛡️ 손절선 올려 잡기 · 재매수 · 냉각 · 불타기 — 810개 조합 전부", expanded=False):
        if not _lc.get('grid'):
            st.info("격자 결과를 만드는 중입니다(GitHub 서버 research-rs 작업). 끝나면 이 자리에 자동으로 나옵니다.")
        else:
            _dm = _lc['dims']; _sm = _lc['summary']; _sps = _lc['spy']['stats']
            st.caption("**규칙** — 손절선 = max(진입가 × (1−초기%), 보유 중 최고가 × (1−고점%)) · 판 뒤 26주 안에 '청산가 재돌파' 또는 "
                       "'청산 후 저점 대비 +20/30% 반등'이면 다음 주 같은 비중 재매수(종목당 3회) · 냉각 = 판 돈을 k주 동안 다른 종목에 안 씀 · "
                       "불타기 = 진입가 대비 +step% 마다(그 주 신고가) 첫 매수금액의 50% 를 다음 주 추가. 종목 선택은 교집합 RS 높은 순 그대로.")
            _m = st.columns(4)
            _m[0].metric("SPY 수익 초과", f"{_sm['beat_spy']} / {_sm['n']}", f"SPY {_sps['CAGR']}%", delta_color="off")
            _m[1].metric("낙폭도 SPY 이하", f"{_sm['mdd_le_spy']} / {_sm['n']}", f"SPY MDD {_sps['MDD']}%", delta_color="off")
            _m[2].metric("둘 다", f"{_sm['both']} / {_sm['n']}")
            _m[3].metric("조합 중앙", f"{_sm['median_cagr']:.1f}%", f"MDD {_sm['median_mdd']:.1f}%", delta_color="off")
            _G = pd.DataFrame(_lc['grid'])
            _lab = {'init': ('초기 손절', lambda k: f"진입가 -{k}%"), 'trail': ('고점 대비', lambda k: f"고점 -{k}%"),
                    're': ('재매수', lambda k: _dm['re'][k]), 'cd': ('냉각', lambda k: f"{k}주"),
                    'py': ('불타기', lambda k: _dm['py'][k]), 'slots': ('최대 종목 수', lambda k: f"{k}칸")}
            _er = []
            for _d, (_nm, _f) in _lab.items():
                for _k, _v in _sm['effects'][_d].items():
                    _er.append({'항목': _nm, '값': _f(int(_k) if _k.isdigit() else _k), '중앙 CAGR(%)': _v['CAGR'],
                                '중앙 MDD(%)': _v['MDD'], '중앙 수익÷낙폭': _v['Calmar']})
            st.markdown("**항목별 효과** — 그 값을 쓴 조합들의 중앙값(다른 항목은 전부 섞여 있다)")
            _tsrc('research/loss_cut_grid.py (GitHub Actions research-rs)', path='results/loss_cut_grid.json')
            st.dataframe(pd.DataFrame(_er), use_container_width=True, hide_index=True, filters=False, color=False,
                         column_config={'중앙 CAGR(%)': st.column_config.NumberColumn(format='%.1f'),
                                        '중앙 MDD(%)': st.column_config.NumberColumn(format='%.1f'),
                                        '중앙 수익÷낙폭': st.column_config.NumberColumn(format='%.2f')})
            _f = go.Figure()
            _f.add_trace(go.Scatter(x=_G.MDD, y=_G.CAGR, mode='markers', name='810개 조합',
                                    marker=dict(size=5, color='#0e5a6b', opacity=0.45), text=_G.key,
                                    hovertemplate='%{text}<br>MDD %{x:.1f}% · CAGR %{y:.1f}%<extra></extra>'))
            _f.add_trace(go.Scatter(x=[_sps['MDD']], y=[_sps['CAGR']], mode='markers+text', name='SPY', text=['SPY'],
                                    textposition='top center', marker=dict(size=11, color='#a03028', symbol='diamond')))
            for _ns, _rv in _lc['ref'].items():
                _f.add_trace(go.Scatter(x=[_rv['MDD']], y=[_rv['CAGR']], mode='markers+text', name=f'현행 {_ns}칸(고점 -20%만)',
                                        text=[f'현행 {_ns}칸'], textposition='bottom center',
                                        marker=dict(size=10, color='#ca8a04', symbol='square')))
            _f.add_vline(x=_sps['MDD'], line=dict(color='#a03028', width=1, dash='dot'))
            _f.add_hline(y=_sps['CAGR'], line=dict(color='#a03028', width=1, dash='dot'))
            _f.update_xaxes(title='최대낙폭 MDD(%) — 오른쪽일수록 덜 빠짐', ticksuffix='%')
            _f.update_yaxes(title='연수익 CAGR(%)', ticksuffix='%')
            _f.update_layout(height=340, margin=dict(l=8, r=8, t=34, b=8), title="수익 vs 낙폭 — 점선 오른쪽 위 = SPY를 수익·낙폭 모두 이김",
                             legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
            st.plotly_chart(_f, use_container_width=True)

            st.markdown("**조합 하나 골라 보기** — 시작 월을 고르면 그 달 첫 주 자산을 100 으로 다시 맞춘다")
            _c = st.columns(7)
            _ns = _c[0].selectbox("종목 수", _dm['slots'], index=1, key="lc_ns", format_func=lambda k: f"{k}칸")
            _x = _c[1].selectbox("초기 손절", _dm['init'], index=1, key="lc_x", format_func=lambda k: f"-{k}%")
            _y = _c[2].selectbox("고점 대비", _dm['trail'], index=1, key="lc_y", format_func=lambda k: f"-{k}%")
            _rk = _c[3].selectbox("재매수", list(_dm['re']), key="lc_re", format_func=lambda k: _dm['re'][k])
            _cd = _c[4].selectbox("냉각", _dm['cd'], key="lc_cd", format_func=lambda k: f"{k}주")
            _pk = _c[5].selectbox("불타기", list(_dm['py']), key="lc_py", format_func=lambda k: _dm['py'][k])
            _dx = pd.DatetimeIndex(_lc['dates'])
            _months = sorted({(t.year, t.month) for t in _dx})
            _mo = _c[6].selectbox("시작 월", _months, key="lc_mo", format_func=lambda m: f"{m[0]}-{m[1]:02d}")
            _key = f"{_ns}|{_x}|{_y}|{_rk}|{_cd}|{_pk}"
            _gr = next(r for r in _lc['grid'] if r['key'] == _key)
            _cv = pd.Series(_lc['curves'][_key], index=_dx)
            _rf = pd.Series(_lc['curves'][f"ref|{_ns}"], index=_dx)
            _sp = pd.Series(_lc['spy']['curve'], index=_dx).ffill()
            _i0 = int(np.argmax((_dx.year == _mo[0]) & (_dx.month == _mo[1])))
            _a, _r, _b = (z.iloc[_i0:] / z.iloc[_i0] * 100 for z in (_cv, _rf, _sp))
            _yr = max(1e-9, (_a.index[-1] - _a.index[0]).days / 365.25)
            _cg = lambda z: ((z.iloc[-1] / z.iloc[0]) ** (1 / _yr) - 1) * 100
            _md = lambda z: (z / z.cummax() - 1).min() * 100
            _m = st.columns(5)
            _m[0].metric("100 →", f"{_a.iloc[-1]:,.0f}", f"현행 {_r.iloc[-1]:,.0f} · SPY {_b.iloc[-1]:,.0f}", delta_color="off")
            _m[1].metric("연수익(이 기간)", f"{_cg(_a):.1f}%", f"현행 {_cg(_r):.1f}% · SPY {_cg(_b):.1f}%", delta_color="off")
            _m[2].metric("최대낙폭(이 기간)", f"{_md(_a):.1f}%", f"현행 {_md(_r):.1f}% · SPY {_md(_b):.1f}%", delta_color="off")
            _m[3].metric("거래 · 평균 보유", f"{_gr['trades']:,}건", f"{_gr['avg_wk']}주 · 승률 {_gr['win']}%", delta_color="off")
            _m[4].metric("평균 현금 비중", f"{_gr['avg_cash']:.0f}%",
                         (f"상폐충격 후 CAGR {_gr['shock1']:.1f}%" if _gr.get('shock1') == _gr.get('shock1') and _gr.get('shock1') is not None
                          else "상폐충격: 상위 10개만 계산"), delta_color="off")
            _f = go.Figure()
            for _z, _nm, _col, _w in ((_a, '이 조합', '#0e5a6b', 1.8), (_r, f'현행({_ns}칸·고점 -20%만)', '#ca8a04', 1.2),
                                      (_b, 'SPY', '#9ca3af', 1.2)):
                _f.add_trace(go.Scatter(x=_z.index, y=_z.values, mode='lines', name=_nm, line=dict(color=_col, width=_w),
                                        hovertemplate='%{x|%Y-%m-%d}<br>' + _nm + ' %{y:,.0f}<extra></extra>'))
            _f.update_yaxes(type='log', title='자산(시작 월 = 100, 로그)')
            _f.update_layout(height=300, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                             title=f"{_mo[0]}-{_mo[1]:02d} 시작 · {_ns}칸 · 진입가 -{_x}% / 고점 -{_y}% · {_dm['re'][_rk]} · 냉각 {_cd}주 · {_dm['py'][_pk]}",
                             legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
            st.plotly_chart(_f, use_container_width=True)
            st.markdown("**연도별 수익률 — 처음부터**")
            _yrow = []
            for _yy, _g in _cv.groupby(_cv.index.year):
                if len(_g) < 5:
                    continue
                _gr_, _gs = _rf.loc[_g.index], _sp.loc[_g.index]
                _yrow.append({'연도': str(_yy), '이 조합(%)': round((_g.iloc[-1] / _g.iloc[0] - 1) * 100, 1),
                              '현행(%)': round((_gr_.iloc[-1] / _gr_.iloc[0] - 1) * 100, 1),
                              'SPY(%)': round((_gs.iloc[-1] / _gs.iloc[0] - 1) * 100, 1)})
            for _rr in _yrow:
                _rr['SPY 대비(%p)'] = round(_rr['이 조합(%)'] - _rr['SPY(%)'], 1)
            _tsrc('research/loss_cut_grid.py', path='results/loss_cut_grid.json')
            st.dataframe(pd.DataFrame(_yrow), use_container_width=True, hide_index=True, filters=False,
                         column_config={c: st.column_config.NumberColumn(format='%+.1f')
                                        for c in ('이 조합(%)', '현행(%)', 'SPY(%)', 'SPY 대비(%p)')})
            st.caption(f"기간 {_lc['period'][0]} ~ {_lc['period'][1]} · 시계열 {_lc['factor_ver']} · {_lc['universe']:,}종 · 1주 지연 체결 · 편도 0.3% · "
                       "⚠️ 810개 중 가장 좋은 조합은 우연일 가능성이 크다 — 항목별 효과(중앙값)와 이웃 조합이 같은 방향인지로 판단할 것.")

    # ── 🔥 불타기 재검증 (2026-10-24 차니 지적: 수익금 플레이어 관점) ──
    _pg = load_json(Path('results/pyramid_grid.json')) or {}
    with st.expander("🔥 불타기 재검증 — 재원(현금·예비·약한 종목 정리) × 시점·금액·종목당 상한", expanded=False):
        if not _pg.get('grid'):
            st.info("결과를 만드는 중입니다(GitHub 서버 research-rs 작업).")
        else:
            _sps = _pg['spy']['stats']
            st.caption("지난 810조합의 불타기는 '남는 현금'으로만 사서 대부분 실행되지 못했다(측정 결함). 이번엔 재원을 바꿔 다시 쟀다. "
                       "불타기 = 진입가 대비 +step% 마다(그 주 신고가) 첫 매수의 50/100% 를 다음 주 추가, 최대 3회, 추가 시점에 종목당 상한 적용. "
                       "상위5 = 수익금 상위 5종목이 순수익금에서 차지한 비중(100% 초과 = 나머지가 합쳐서 손실).")
            _bn = _pg['bases']; _fn = _pg['funds']
            _er = []
            for _k, _v in _pg['effects'].items():
                _b, _f = _k.split('|')
                _er.append({'기준 전략': _bn[_b], '재원': _fn[_f], '불타기 없음 CAGR(%)': _v['none_CAGR'], '불타기 없음 MDD(%)': _v['none_MDD'],
                            '불타기 중앙 CAGR(%)': _v['on_CAGR'], '불타기 중앙 MDD(%)': _v['on_MDD'],
                            '수익 늘어난 조합': f"{_v['better_cagr']}/{_v['n']}", '수익÷낙폭 나아진 조합': f"{_v['better_calmar']}/{_v['n']}",
                            '상위5 비중(%)': _v['on_top5'], '최대 비중(%)': _v['on_maxw']})
            _tsrc('research/pyramid_grid.py (GitHub Actions research-rs)', path='results/pyramid_grid.json')
            st.dataframe(pd.DataFrame(_er), use_container_width=True, hide_index=True, filters=False, color=False,
                         column_config={c: st.column_config.NumberColumn(format='%.1f') for c in
                                        ('불타기 없음 CAGR(%)', '불타기 없음 MDD(%)', '불타기 중앙 CAGR(%)', '불타기 중앙 MDD(%)', '상위5 비중(%)', '최대 비중(%)')})
            st.markdown("**조합 골라 보기** — 같은 기준 전략의 '불타기 없음'과 나란히, 시작 월 = 100")
            _c = st.columns(6)
            _b = _c[0].selectbox("기준 전략", list(_bn), index=1, key="pg_b", format_func=lambda k: _bn[k])
            _f = _c[1].selectbox("재원", list(_fn), key="pg_f", format_func=lambda k: _fn[k])
            _stp = _c[2].selectbox("불타기 시점", _pg['dims']['step'], index=1, key="pg_s", format_func=lambda k: f"+{k}%마다")
            _ad = _c[3].selectbox("추가 금액", _pg['dims']['add'], key="pg_a", format_func=lambda k: f"첫 매수의 {int(k*100)}%")
            _cp = _c[4].selectbox("종목당 상한", _pg['dims']['cap'], index=1, key="pg_c", format_func=lambda k: f"계좌의 {k}%")
            _dx = pd.DatetimeIndex(_pg['dates'])
            _months = sorted({(t.year, t.month) for t in _dx})
            _mo = _c[5].selectbox("시작 월", _months, key="pg_mo", format_func=lambda m: f"{m[0]}-{m[1]:02d}")
            _k1 = f"{_b}|{_f}|{_stp}_{_ad}_{_cp}"
            _k0 = f"{_b}|{'cash' if _f == 'sell_weakest' else _f}|none"
            _g1 = next(r for r in _pg['grid'] if r['key'] == _k1); _g0 = next(r for r in _pg['grid'] if r['key'] == _k0)
            _i0 = int(np.argmax((_dx.year == _mo[0]) & (_dx.month == _mo[1])))
            _a1, _a0, _sb = (pd.Series(z, index=_dx).ffill().iloc[_i0:] for z in (_pg['curves'][_k1], _pg['curves'][_k0], _pg['spy']['curve']))
            _a1, _a0, _sb = (z / z.iloc[0] * 100 for z in (_a1, _a0, _sb))
            _yr = max(1e-9, (_a1.index[-1] - _a1.index[0]).days / 365.25)
            _cg = lambda z: ((z.iloc[-1] / z.iloc[0]) ** (1 / _yr) - 1) * 100
            _md = lambda z: (z / z.cummax() - 1).min() * 100
            _m = st.columns(5)
            _m[0].metric("100 → (불타기)", f"{_a1.iloc[-1]:,.0f}", f"없음 {_a0.iloc[-1]:,.0f} · SPY {_sb.iloc[-1]:,.0f}", delta_color="off")
            _m[1].metric("연수익(이 기간)", f"{_cg(_a1):.1f}%", f"없음 {_cg(_a0):.1f}% · SPY {_cg(_sb):.1f}%", delta_color="off")
            _m[2].metric("최대낙폭(이 기간)", f"{_md(_a1):.1f}%", f"없음 {_md(_a0):.1f}% · SPY {_md(_sb):.1f}%", delta_color="off")
            _m[3].metric("상위 5종목 수익금 비중", f"{_g1['top5']}%", f"없음 {_g0['top5']}%", delta_color="off")
            _m[4].metric("한 종목 최대 비중", f"{_g1['max_w']}%", f"평균 최대 {_g1['avg_max_w']}% · 정리 매도 {_g1['funding_sells']}건", delta_color="off")
            _fig = go.Figure()
            for _z, _nm, _col, _w in ((_a1, '불타기', '#0e5a6b', 1.8), (_a0, '불타기 없음', '#ca8a04', 1.2), (_sb, 'SPY', '#9ca3af', 1.2)):
                _fig.add_trace(go.Scatter(x=_z.index, y=_z.values, mode='lines', name=_nm, line=dict(color=_col, width=_w),
                                          hovertemplate='%{x|%Y-%m-%d}<br>' + _nm + ' %{y:,.0f}<extra></extra>'))
            _fig.update_yaxes(type='log', title='자산(시작 월 = 100, 로그)')
            _fig.update_layout(height=300, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                               title=f"{_bn[_b]} · {_fn[_f]} · +{_stp}%마다 {int(_ad*100)}% · 상한 {_cp}%",
                               legend=dict(orientation='h', yanchor='bottom', y=1.0, xanchor='right', x=1))
            st.plotly_chart(_fig, use_container_width=True)
            st.caption(f"기간 {_pg['period'][0]} ~ {_pg['period'][1]} · SPY {_sps['CAGR']}% / MDD {_sps['MDD']}% · 1주 지연 · 편도 0.3%")

    # ── ✅ 후보 A·B 사전 등록 재확인 + 코어·위성 결합표 (2026-10-26) ──
    _ca = load_json(Path('results/confirm_ab.json')) or {}
    with st.expander("✅ 위성 후보 A·B 사전 등록 재확인 · 코어+위성 결합표", expanded=False):
        if not _ca.get('cands'):
            st.info("결과를 만드는 중입니다(GitHub 서버 research-rs 작업).")
        else:
            _sps = _ca['spy']
            st.caption("A = 교집합 RS순 · 20칸 · 손절 max(진입가 -15%, 고점 -15%) · 청산가 재돌파 재매수 · 냉각 4주 · 불타기 없음 / "
                       "B = A + 불타기(+30%마다 첫 매수의 50%, 최대 3회, 종목당 상한 25%). 합격 기준은 결과 보기 전에 커밋했다(research/confirm_ab.py).")
            _rows = []
            for _k, _v in _ca['cands'].items():
                _r = {'후보': _k, 'CAGR(%)': _v['center']['CAGR'], 'MDD(%)': _v['center']['MDD'], '수익÷낙폭': _v['center']['Calmar'],
                      '이웃 유지': f"{_v['nb_ok']}/{_v['nb_n']}", '상폐충격 후 CAGR(%)': round(_v['shock1'], 1),
                      'RS 가중(%)': _v['rs']['w']['CAGR'], 'RS 13주(%)': _v['rs']['r13']['CAGR'], 'RS 12-1(%)': _v['rs']['m121']['CAGR'],
                      '무작위 순서 중앙(%)': round(_v['random']['median'], 1), '판정': '✅ 합격' if _v['passed'] else '❌ 불합격'}
                _rows.append(_r)
            _tsrc('research/confirm_ab.py (GitHub Actions research-rs)', path='results/confirm_ab.json')
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True, filters=False, color=False,
                         column_config={c: st.column_config.NumberColumn(format='%.1f') for c in
                                        ('CAGR(%)', 'MDD(%)', '상폐충격 후 CAGR(%)', 'RS 가중(%)', 'RS 13주(%)', 'RS 12-1(%)', '무작위 순서 중앙(%)')}
                         | {'수익÷낙폭': st.column_config.NumberColumn(format='%.2f')})
            for _k, _v in _ca['cands'].items():
                st.caption(f"**{_k}** 기준별: " + " · ".join(f"{'✅' if ok else '❌'} {nm}" for nm, ok in _v['criteria'].items()))
            st.caption(f"SPY 같은 구간 {_sps['CAGR']}% / MDD {_sps['MDD']}% · 수익÷낙폭 {_sps['Calmar']}")
            st.markdown(f"**코어+위성 결합표** — 코어 = SPY + 40주선 스위치(아래면 현금) 단독 {_ca['core']['CAGR']}% / MDD {_ca['core']['MDD']}% · 13주마다 비중 복원")
            _bn = {'A': '위성 A', 'B': '위성 B', 'cur': '위성 현행(20칸·고점 -20%)'}
            _br = []
            for _sk, _rws in _ca['blend'].items():
                for _r in _rws:
                    if _r['w'] == 0:
                        continue
                    _br.append({'위성': _bn.get(_sk, _sk), '위성 비중(%)': int(_r['w'] * 100), 'CAGR(%)': _r['CAGR'], 'MDD(%)': _r['MDD'],
                                '수익÷낙폭': _r['Calmar'], 'MDD -20% 이내': '✅' if _r['MDD'] >= -20 else '',
                                'SPY 수익 초과': '✅' if _r['CAGR'] > _sps['CAGR'] else ''})
            _tsrc('research/confirm_ab.py', path='results/confirm_ab.json')
            st.dataframe(pd.DataFrame(_br), use_container_width=True, hide_index=True, color=False,
                         column_config={'CAGR(%)': st.column_config.NumberColumn(format='%.1f'),
                                        'MDD(%)': st.column_config.NumberColumn(format='%.1f'),
                                        '수익÷낙폭': st.column_config.NumberColumn(format='%.2f')})

# ── 🔥 상승 상위 (기간 상승률 + 주봉 신호 + 실적증감 + 계절성 + 낙폭 필터) ──
with t_gain, guard('상승 상위'):
    st.caption("기간 상승률 상위 + 주봉 신호 · 향후 2개월 계절성. 실적(매출·영업익 YoY)·PER·RS 는 오른쪽 공통 열.")
    _retj = load_json(Path('results/returns.json'))
    _perf = load_json(PERF_JSON) or {}
    if not _retj or not _retj.get('stocks'):
        st.error("기간 수익률 데이터 없음 → `python screen_precompute.py` 실행 후 새로고침")
    else:
        _PERIODS = {'1주': ('perf', 'ret_1w'), '1개월': ('ret', 'ret_1m'), '3개월': ('ret', 'ret_3m'),
                    '6개월': ('ret', 'ret_6m'), '1년': ('ret', 'ret_12m'), 'YTD': ('ret', 'ret_ytd')}
        _gmkt = _GMKT
        _gc1, _gc3, _gc4 = st.columns([1.2, 1, 1])
        _gper = _gc1.selectbox("상승률 기간", list(_PERIODS.keys()), index=1, key="gain_per")
        _gsig = _gc3.checkbox("신호 있는 종목만", value=False, key="gain_sigonly")
        _gn = _gc4.slider("표시 종목수", 10, 60, 30, key="gain_n")
        # ⚡타이밍 발굴에서 흡수한 두 필터 — 같은 데이터를 별도 화면으로 두던 중복 제거
        with st.expander("⚡ 타이밍 필터 — 계절성 승률 · 고점대비 낙폭 (구 '타이밍 발굴')"):
            _tf1, _tf2 = st.columns(2)
            _gwr = _tf1.slider("당월 계절성 최소 승률 %  (0 = 끄기)", 0, 90, 0, 5, key="gain_seaswr",
                               help="이번 달에 과거 몇 %의 확률로 올랐는지. 표본 3년 미만은 자동 제외.")
            _gdd = _tf2.slider("52주 고점대비 범위 %", -90, 0, (-90, 0), key="gain_ddrange",
                               help="바닥 탐색용. 예: -60~-25 로 좁히면 크게 조정받은 종목만 남는다. 표의 '52주고점대비' 열과 같은 값.")
        _src, _retkey = _PERIODS[_gper]

        # 2026-10-21 위닝점수(옛 주봉 신호 6종 샤프 가중 점수) 폐지 — 원칙 v1 어디에도 안 쓰였다

        # perf 맵: 1주 수익률 + 현재 신호
        _SIGL = [('now_sig_52w', '52주신고가'), ('now_sig_vol', '거래량'), ('now_sig_maconv', '이평수렴'),
                 ('now_sig_cup', '컵핸들'), ('now_sig_ma5', '5주라이딩'), ('now_sig_rsimacd', 'RSI/MACD')]
        _perfmap = {}
        for s in _perf.get('stocks', []):
            sigs = [lab for k, lab in _SIGL if s.get(k)]
            _perfmap[s['sym']] = {'ret_1w': s.get('ret_1w'), 'sigs': sigs, 'nsig': len(sigs)}

        # 계절성: 당월 + 익월 평균
        from datetime import datetime as _gdt
        _cmo = _gdt.now().month; _nmo = _cmo % 12 + 1
        _seasj = load_json(Path('results/seasonality.json')) or {}
        _seasmap, _seaswr = {}, {}
        for s in _seasj.get('stocks', []):
            m = s.get('months', {})
            vals = [m[str(x)]['ret'] for x in (_cmo, _nmo) if m.get(str(x))]
            if vals:
                _seasmap[s['sym']] = round(sum(vals) / len(vals), 1)
            _cur = m.get(str(_cmo))
            if _cur and _cur.get('n', 0) >= 3:          # 표본 3년 미만은 우연이라 승률로 안 쓴다
                _seaswr[s['sym']] = _cur['wr']

        _retc = f'{_gper}상승(%)'
        _grows = []
        for s in _retj['stocks']:
            if _gmkt != "전체" and s['market'] != _gmkt:
                continue
            pm = _perfmap.get(s['sym'], {})
            ret = pm.get('ret_1w') if _src == 'perf' else s.get(_retkey)
            if ret is None:
                continue
            if _gsig and pm.get('nsig', 0) == 0:
                continue
            if _gwr > 0 and _seaswr.get(s['sym'], -1) < _gwr:
                continue
            _dd_v = _CMB['52주고점대비(%)'].get(s['sym']) if not _CMB.empty else None
            if (_gdd[0], _gdd[1]) != (-90, 0):
                if _dd_v is None or not (_gdd[0] <= _dd_v <= _gdd[1]):
                    continue
            _grows.append({'종목': s['name'], '코드': s['sym'], _retc: ret,
                           '신호': ', '.join(pm.get('sigs', [])[:3]) or None,
                           '향후2M계절성(%)': _seasmap.get(s['sym'])})
        _grows.sort(key=lambda r: -(r[_retc] if r[_retc] is not None else -999))
        _grows = _grows[:_gn]
        # (구) 여기서 점수·계절성을 문자열로 바꿨다 → 정렬·필터가 깨져서 2026-10-15 제거.
        #     표시 포맷은 column_config 가 맡는다.

        st.subheader(f"🔥 {_gper} 상승 상위 — {len(_grows)}종 · 정렬: {_gper} 상승률")
        _std_table(pd.DataFrame(_grows), [_retc, '신호', '향후2M계절성(%)'],
                   src='FinanceDataReader·yfinance(주가) → returns.json·seasonality.json', path='results/returns.json',
                   column_config={'신호': st.column_config.TextColumn('신호', help='주봉 기준 현재 뜬 기술 신호(최대 3개)')},
                   note="⚠️ 상승률 상위 = '이미 오른' 종목 — 추격 주의")
        _cand_register(_grows, 'gain')


# ── 주도주 (섹터/전체 상대강도) ──
# 시장 선택 플래그. 라디오 위젯보다 먼저 읽지만, 첫 렌더에서는 위젯 기본값(미국)과
# 같은 값이 나오므로 문제되지 않는다. guard() 안에서 정의하면 예외 시 NameError 다.
# 2026-10-15 — 탭 자체 미국/한국 라디오 폐지 → 상단 공통 시장 필터(전체면 두 시장을 위아래로).
#   두 규칙은 검증 수준이 달라(미국 8년 백테스트+청산 연구 / 한국 가격 백테스트) 한 표로 섞지 않고 구획을 나눈다.
_LEAD_US = _GMKT != "KR"
_LEAD_KR = _GMKT != "US"

with t_lead, guard('주도주'):
    if _LEAD_US and _LEAD_KR:
        st.caption("🇺🇸 미국 이익 가속 신호 목록입니다. 한국 규칙(KR-U6 / KR-P1)은 상폐 포함 백테스트에서 기각돼 "
                   "맨 아래 🗄️ 기각된 규칙으로 옮겼습니다(원칙 v1.2).")
    if _LEAD_US:
        st.markdown("## 🇺🇸 미국 — 이익 가속")
    if _LEAD_US:
        # ── ⚡ 이익 가속 신호 (2026-08-23 신설) ────────────────────────
        # L/S 규칙(+20% 급등·거래량<1.5·재무)은 8년간 TSLA 0회·NVDA 0회·WDC 0회였다.
        # 대박 시작점을 역산하니 시작점은 '급등한 주'가 아니었고(NVDA 그 주 −7.0%),
        # 공통점은 수준이 아니라 **성장률의 기울기 변화**에 있었다.
        # 이 화면의 일은 포트폴리오 운용이 아니라 **주도주가 신호에 걸리게 하는 것**이다.
        _ac = load_json(Path('results/leaders_accel.json'))
        if _ac:
            _acp = _ac['perf']
            st.markdown("### ⚡ 이익 가속 — 성장률이 빨라지는 종목")
            st.caption(f"**{_ac['rule']['text']}** · 기준 주차 {_ac['signal_week']} · "
                       f"생성 {_ac['generated']}")
            _m = st.columns(5)
            _m[0].metric("신호 1건 평균 (1년)", f"{_acp['mean']}%",
                         f"기저 {_acp['base_mean']}%")
            _m[1].metric("시장 대비 초과 (평균)", f"{_acp['alpha_mean']}%")
            _m[2].metric("2배 이상", f"{_acp['w2']}%", f"기저 {_acp['base_w2']}%")
            _m[3].metric("4배 이상", f"{_acp['w4']}%", f"기저 {_acp['base_w4']}%")
            _m[4].metric("10배 이상", f"{_acp['w10']}%", f"기저 {_acp['base_w10']}%")
            st.caption(
                f"신호 {_acp['n']:,}건 중 1년이 지난 {_acp['n_scored']:,}건 기준. "
                f"상위 10% {_acp['p90']}% · 상위 1% {_acp['p99']}% · 최대 {_acp['mx']}%. "
                f"**중앙값은 {_acp['median']}%로 낮습니다 — 이 분포는 U자이고, 등가중으로 담으면 "
                f"받는 것은 평균입니다.** 중앙값으로 판정하면 꼬리를 통째로 놓친다.")
            _btj = load_json(Path('results/rs_accel_bt.json')) or {}
            _bts = ((_btj.get('variants') or {}).get('star') or {})
            _yrs = list((_ac.get('by_year') or {}).items()) if isinstance(_ac.get('by_year'), dict) else []
            _yrs = [(y, v) for y, v in _yrs if v.get('n', 0) >= 30]
            with st.expander("⚠️ 이 신호를 쓸 때 알아야 할 것"):
                if _bts:
                    st.markdown(
                        f"- **신호 목록이지 매수 규칙이 아닙니다.** 이 신호를 20칸 포트폴리오로 담으면(고점 −20% 손절) "
                        f"CAGR **{_bts.get('CAGR')}%** · MDD {_bts.get('MDD')}% 로 SPY {(_btj.get('SPY') or {}).get('CAGR')}% 에 "
                        f"못 미쳤습니다({_btj.get('factor_ver')} · {(_btj.get('period') or ['-'])[0]}~, 무작위 순서 10회 중앙값). "
                        "현재 후보 체계는 🚀 주도주 → 교집합 후보입니다.")
                st.markdown(
                    "- **상위 5% 거래가 전체 수익의 94%를 만듭니다.** 꼬리에 전적으로 의존합니다.")
                if _yrs:
                    st.markdown(
                        "- **연도 편차가 극심하다** — 신호 1년 뒤 시장 대비 초과(알파): "
                        + " · ".join(f"{y} {v['alpha']:+.1f}%" for y, v in _yrs)
                        + f". {len(_yrs)}개 해 중 {sum(1 for _, v in _yrs if v['alpha'] < 0)}개 해가 마이너스 — "
                        "위험선호 장세(2020·2025)에 몰려 있다.")
                st.markdown(
                    "- 문턱을 +25%로 조이면 모든 지표가 좋아지지만(알파평균 +36.8%) "
                    "주도주를 놓칩니다. **+10%를 택한 이유는 포착입니다** — 급등 +10%면 "
                    "NVDA 13회·TSLA 21회·PLTR 10회·MU 22회가 걸리는데, +20%로 올리면 "
                    "1·8·4·3회로 줄어듭니다.")
                st.markdown(
                    "- 유니버스에 상장폐지 종목이 없습니다 — 모든 숫자가 낙관 편향입니다.")
                st.markdown(
                    "- 근거: He & Narayanamoorthy(2020, JAE) *Earnings Acceleration and "
                    "Stock Returns* · Minervini SEPA. 단 Minervini 의 '매출 20%↑' 같은 "
                    "**수준 조건은 여기서 독이다**(알파 −23.3%) — NVDA 는 대상승 시작 시점 "
                    "매출 YoY 가 +3.0%였고 이후 1년 내내 역성장했다.")
            _cd = _ac['candidates']
            st.markdown(f"**이번 주 신호 {len(_cd)}종** — 이익 가속 + 그 주 주봉 종가 +{_ac['rule'].get('surge', 10):g}% 이상 · 칸 수 제한 없이 전부")
            if _cd:
                _sig = [{'코드': m['sym'], '종목': m['name'], '회차': m['n'], '그주상승(%)': m['up'],
                         '매출가속(%p)': m['rva'], '이익가속(%p)': m['oia'], 'OPM(%)': m['opm']} for m in _cd]
                _std_table(pd.DataFrame(_sig), ['회차', '그주상승(%)', '매출가속(%p)', '이익가속(%p)', 'OPM(%)'],
                           src='Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json',
                           column_config={'회차': st.column_config.NumberColumn(format='%d', help='그 해 안에서 이 종목이 몇 번째로 신호를 냈나'),
                                          '그주상승(%)': st.column_config.NumberColumn(format='%+.1f', help='신호 주 주봉 종가 상승률'),
                                          '매출가속(%p)': st.column_config.NumberColumn(format='%+.1f', help='매출 성장률의 분기 대비 변화'),
                                          '이익가속(%p)': st.column_config.NumberColumn(format='%+.1f', help='영업이익 성장률의 분기 대비 변화'),
                                          'OPM(%)': st.column_config.NumberColumn(format='%.1f', help='최근 분기 영업이익률')},
                           note='정렬: 산출 순서 · 신호 뒤 성적은 아래 주차별 조회에')
                _cand_register(_sig, 'accel')
            else:
                st.info("이번 주 조건 충족 종목 없음")
            # 신호 회차별 성적 — 그 해 안에서 센 회차 기준.
            # 전 구간 누적은 6년 전 신호까지 끌고 와 세므로 지금 판단에 쓸 수 없다.
            if _ac.get('by_step_y'):
                with st.expander("🔥 같은 해에 몇 번째 신호인가 — 회차별 성적"):
                    _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                    st.dataframe(pd.DataFrame([{
                        '그 해 회차': v['lbl'], '신호': v['n'], '평균': v['mean'],
                        '시장대비': v['alpha'], '중앙값': v['median'],
                        '2배+%': v['w2'], '10배+%': v['w10']}
                        for v in _ac['by_step_y']]),
                        use_container_width=True, hide_index=True, row_height=25)
                    st.markdown(
                        "- 같은 해에 신호가 **반복될수록 시장 대비 성적이 좋아집니다** "
                        "(1회 +6.5% → 3회 +19.3% → 4-5회 +22.5% → 6-9회 +42.6%).")
                    st.markdown(
                        "- **다만 +42.6%를 기대값으로 삼으면 안 됩니다.** 같은 구간의 "
                        "중앙값은 +6.5%이고, GME·BTU 두 종목을 빼면 +19.7%, "
                        "회복장(2019~2021)까지 빼면 **+9.8%에 중앙값은 음수**가 됩니다.")
                    st.markdown(
                        "- **이기는 비율은 회차와 거의 무관합니다.** 1회에도 58%가 시장에 "
                        "지고 6-9회에도 53%가 집니다. 바뀌는 건 이겼을 때의 크기이고, "
                        "**지는 폭도 같이 커집니다** — 반토막 확률이 7.5%에서 16.2%로 "
                        "두 배가 됩니다.")
                    st.markdown(
                        "- 회차는 **해가 바뀌면 1로 돌아갑니다.** 6년에 걸쳐 띄엄띄엄 뜬 신호와 "
                        "한 해에 몰린 신호는 다르게 봐야 하기 때문입니다.")
                    st.markdown(
                        "- ⚠️ 6-9회 구간은 198건 · 100종목뿐입니다. 한 해에 6번 이상 걸리는 "
                        "종목 자체가 드물어 앞으로도 표본이 빨리 늘지 않습니다.")


            # ── 이익 가속: 종목 심층 조회 ─────────────────────────────
            # weeks 를 종목별로 역인덱스하면 추가 파일 없이 심층조회가 된다.
            # 2026-08-25: 나란히 있던 L/S 심층조회는 제거했다(규칙 자체가 폐기).
            @st.cache_data(show_spinner=False)
            def _accel_bysym(_fkey: str):
                _d = load_json(Path('results/leaders_accel.json')) or {}
                out = {}
                for _w, _rows in (_d.get('weeks') or {}).items():
                    for _m in _rows:
                        e = out.setdefault(_m['sym'], {'name': _m.get('name') or _m['sym'],
                                                       'rows': []})
                        e['rows'].append(dict(_m, d=_w))
                for e in out.values():
                    e['rows'].sort(key=lambda x: x['d'])
                return out

            _ab = _accel_bysym(file_key('results/leaders_accel.json'))
            if _ab:
                st.markdown("#### 🔍 종목 심층 조회 — 이 종목이 언제 걸렸나")
                _ao = sorted(_ab, key=lambda x: (-len(_ab[x]['rows']), x))
                _ap = st.selectbox(
                    f"종목 검색 — 이익 가속 신호 이력이 있는 {len(_ao)}종",
                    _ao, index=0, key="accel_sym",
                    format_func=lambda x: f"{x} · {_ab[x]['name'][:28]} "
                                          f"({len(_ab[x]['rows'])}회 신호)")
                _ar = _ab[_ap]['rows']
                _c = st.columns(4)
                _c[0].metric("총 신호", f"{len(_ar)}회")
                _c[1].metric("최초 신호", _ar[0]['d'])
                _c[2].metric("최근 신호", _ar[-1]['d'])
                _f52 = [r['f52'] for r in _ar if r.get('f52') is not None]
                _c[3].metric("신호당 1년 평균",
                             f"{sum(_f52)/len(_f52):.1f}%" if _f52 else "—",
                             help="1년이 지난 신호만 집계합니다")

                # ── 가격 곡선 + 신호 지점 ──────────────────────────────
                # 청산 마커가 없는 이유: 이건 신호 목록이고 매매 규칙이 아니다.
                # 청산은 사람이 정하므로 화면이 정할 수 없다. ▲만 찍는다.
                # 곡선은 두 규칙이 공유하는 results/price_curves.json 에서 읽는다
                # (2026-08-25 통합 — 674종이 두 파일에 중복 저장돼 있었다).
                _pc = load_json(Path('results/price_curves.json')) or {}
                _cv = (_pc.get('curves') or {}).get(_ap)
                if _cv and _pc.get('dates'):
                    _AD = pd.to_datetime(_pc['dates'])
                    _apx = pd.Series(_cv['c'], index=_AD[_cv['i']]).astype(float)
                    _f = go.Figure()
                    _f.add_trace(go.Scatter(
                        x=_apx.index, y=_apx.values, mode='lines', name='주봉 종가',
                        line=dict(color='#12161b', width=1.4),
                        hovertemplate='%{x|%Y-%m-%d}<br>$%{y:,.2f}<extra></extra>'))
                    # 올해 회차로 색을 나눈다 — 같은 해에 반복될수록 성적이 좋다
                    # 그 해 몇 번째인지로 나눈다. 반복될수록 진하게 — 색은 크기다.
                    for _lo, _hi, _cl, _lb in [(1, 2, '#8FC4AC', '올해 1-2회'),
                                               (3, 5, '#3E8F6B', '올해 3-5회'),
                                               (6, 10**9, '#125C3D', '올해 6회+')]:
                        _pts = [r for r in _ar if _lo <= (r.get('n') or 0) <= _hi
                                and r['close'] is not None]
                        if not _pts:
                            continue
                        _f.add_trace(go.Scatter(
                            x=pd.to_datetime([r['d'] for r in _pts]),
                            y=[r['close'] for r in _pts], mode='markers+text',
                            marker=dict(symbol='triangle-up', size=12, color=_cl,
                                        line=dict(color='white', width=1)),
                            text=[str(r.get('n') or '') for r in _pts],
                            textposition='bottom center',
                            textfont=dict(size=9, color=_cl), name=_lb,
                            customdata=[[r['up'], r['oia'], r['rva'],
                                         r['f52'] if r.get('f52') is not None else float('nan')]
                                        for r in _pts],
                            hovertemplate=('%{x|%Y-%m-%d} · %{text}회차<br>'
                                           '$%{y:,.2f} · 그주 %{customdata[0]:+.1f}%<br>'
                                           '매출가속 %{customdata[2]:.1f} · '
                                           '이익가속 %{customdata[1]:.1f}<br>'
                                           '이후 1년 %{customdata[3]:+.1f}%<extra></extra>')))
                    _f.update_yaxes(type='log', title='주봉 종가(로그)')
                    _f.update_layout(
                        height=430, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                        title=f"{_ap} · {_ab[_ap]['name']}  —  ▲ 이익 가속 신호 (숫자 = 회차)",
                        legend=dict(orientation='h', yanchor='bottom', y=1.0,
                                    xanchor='right', x=1))
                    st.plotly_chart(_f, use_container_width=True)
                    st.caption(
                        "로그 축입니다 — 기울기가 같으면 상승률이 같습니다. "
                        "**▲ 숫자는 그 해 몇 번째 신호인지**이고, 반복될수록 진한 초록입니다. "
                        "같은 해에 신호가 쌓인 구간일수록 성적이 좋았습니다. "
                        "**청산 마커가 없는 이유는 이 규칙에 청산이 없기 때문입니다** — 신호 목록이고 "
                        "매매 규칙이 아니라, 언제 팔지는 사용자가 정합니다. "
                        "곡선은 첫 신호 26주 전부터 그립니다.")

                    # ── MDD(고점 대비 낙폭) 곡선 ───────────────────────
                    # 2026-08-25 청산 연구에서 나온 것: 주도주는 정점에 닿기 전에
                    # 중앙 -23% 를 견디고, 절반이 -25% 를 한 번 겪는다. 그래서 이 화면의
                    # 일은 "이 종목이 얼마나 흔들렸나"를 신호 위치와 같은 축에서 보이는 것.
                    # ⚠️ 주봉 종가 기준이라 장중 낙폭은 이보다 깊다(prices 테이블이 비어 있다).
                    _ddc = (_apx / _apx.cummax() - 1) * 100
                    # ⚠️ x 축은 리스트가 아니라 DatetimeIndex 로 넘긴다 — Timestamp 리스트는
                    #    이미지 렌더러(kaleido)에서 직렬화가 깨진다(2026-08-25 확인).
                    _sig_dt = pd.to_datetime([r['d'] for r in _ar if r.get('close')])
                    _sig_dd = [float(_ddc.get(_t, float('nan'))) for _t in _sig_dt]
                    # 신호로 샀다면 진입가 대비 이후 1년간 최악 낙폭 — 손절선을 정하는 근거
                    _wr = []
                    for _r in _ar:
                        _c0 = _r.get('close')
                        if not _c0:
                            continue
                        _fw = _apx[_apx.index > pd.Timestamp(_r['d'])].iloc[:52]
                        if len(_fw):
                            _wr.append(_fw.min() / _c0 - 1)
                    _fd = go.Figure()
                    _fd.add_trace(go.Scatter(
                        x=_ddc.index, y=_ddc.values, mode='lines', name='고점 대비 낙폭',
                        line=dict(color='#0e5a6b', width=1.2), fill='tozeroy',
                        fillcolor='rgba(14,90,107,0.16)',
                        hovertemplate='%{x|%Y-%m-%d}<br>고점 대비 %{y:.1f}%<extra></extra>'))
                    if len(_sig_dt):        # DatetimeIndex 는 truthy 판정이 안 된다
                        _fd.add_trace(go.Scatter(
                            x=_sig_dt, y=_sig_dd, mode='markers', name='신호 시점',
                            marker=dict(symbol='triangle-up', size=9, color='#1f6b45',
                                        line=dict(color='white', width=1)),
                            hovertemplate='%{x|%Y-%m-%d}<br>살 때 이미 고점 대비 '
                                          '%{y:.1f}%<extra></extra>'))
                    # 참고선은 **같은 축(고점 대비)** 의 값이어야 한다. 채택 손절선(-25%)은
                    # '진입가 대비'라 이 축에 그으면 축을 섞는다 — 그건 아래 지표 카드로 뺐다.
                    # add_hline 의 주석은 위치를 어디로 줘도 곡선을 덮는다(종목마다 모양이
                    # 다르다). 그래서 선을 트레이스로 넣어 이름을 **범례**로 뺀다.
                    _fd.add_trace(go.Scatter(
                        x=_ddc.index[[0, -1]], y=[-23, -23],   # 리스트 아님(직렬화)
                        mode='lines', line=dict(color='#a03028', width=1, dash='dash'),
                        name='정점 전 견딘 낙폭 중앙 -23%', hoverinfo='skip'))
                    _fd.update_yaxes(title='고점 대비 낙폭(%)', ticksuffix='%',
                                     rangemode='tozero')
                    _fd.update_layout(
                        height=250, margin=dict(l=8, r=8, t=34, b=8), hovermode='x unified',
                        title=f"{_ap} — 고점 대비 낙폭(MDD) · ▲ 신호 시점",
                        legend=dict(orientation='h', yanchor='bottom', y=1.0,
                                    xanchor='right', x=1))
                    st.plotly_chart(_fd, use_container_width=True)
                    _mc = st.columns(3)
                    _mc[0].metric("이 구간 최대 낙폭", f"{_ddc.min():.0f}%")
                    _mc[1].metric("살 때 이미 빠져 있던 정도(중앙)",
                                  f"{pd.Series(_sig_dd).median():.0f}%" if _sig_dd else "—",
                                  help="이 규칙은 신고가가 아니라 낙폭 한가운데서 산다 — "
                                       "전 종목 중앙 -10.8%")
                    _mc[2].metric("신호 후 1년 최악(진입가 대비, 중앙)",
                                  f"{pd.Series(_wr).median()*100:.0f}%" if _wr else "—",
                                  help="이 종목을 신호마다 샀다면 1년 안에 최대 이만큼 물렸다. "
                                       "손절선을 이보다 좁게 잡으면 이 종목은 못 들고 간다.")
                    st.caption(
                        "위 곡선은 **그 시점까지의 최고가 대비** 얼마나 내려와 있는지다(0%가 신고가). "
                        "▲ 가 0% 근처가 아니라 골짜기에 찍히는 게 이 규칙의 특징입니다 — "
                        "**이 규칙은 신고가가 아니라 낙폭 한가운데서 삽니다.** 오른쪽 지표는 "
                        "'이 종목을 신호마다 샀다면 1년 안에 최대 얼마나 물렸나'로, **손절 폭**을 "
                        "정하는 근거다. 다만 **이긴 종목을 파는 규칙은 아니다** — 고점 대비 트레일은 "
                        "측정한 모든 폭에서 안 파는 것보다 나빴습니다. "
                        "붉은 점선은 같은 축의 기준값으로, 주도주 1,843개가 정점에 닿기까지 "
                        "견뎠던 낙폭의 중앙값입니다. "
                        "⚠️ 주봉 종가 기준이라 장중 낙폭은 이보다 깊다.")

                    # ── 익절 판정 (2026-09-13 확정) ─────────────────────
                    # 규칙: 52주 최소보유 + 진입 후 최고가 33주 미갱신 → 매도.
                    # 낙폭이 아니라 **시간 정체**를 본다. 주도주는 정점 전에 중앙 -23% 를
                    # 견디며 오르므로(08-25 해부) 낙폭으로 재면 살아있는 종목을 자른다.
                    # 반면 2배 이상 간 트레이드는 최고가까지 중앙 73주 — 큰 놈은 계속
                    # 신고가를 갱신하며 간다. 그래서 '신고가 없는 기간'이 전진 정지의 신호다.
                    # 근거: leaders_accel_take.py (알파 15.0% vs 무매도 10.6%, 워크포워드 통과)
                    TAKE_FLOOR, TAKE_DRY = 52, 33
                    st.markdown("##### ✂️ 익절 판정 — 1년 버티고, 최고가 33주 미갱신이면 매도")
                    _eo = [r['d'] for r in _ar if r.get('close')]
                    if _eo:
                        _ent = st.selectbox(
                            "진입 주차 — 어느 신호에서 샀다고 볼지", _eo,
                            index=len(_eo) - 1, key=f"take_ent_{_ap}")
                        _seg = _apx[_apx.index >= pd.Timestamp(_ent)].dropna()
                        if len(_seg) >= 2:
                            _pk_d = _seg.idxmax()
                            _pk_v = float(_seg.loc[_pk_d])
                            _held = len(_seg) - 1
                            _dry = len(_seg) - 1 - _seg.index.get_loc(_pk_d)
                            _now = float(_seg.iloc[-1])
                            _k = st.columns(4)
                            _k[0].metric("보유 경과", f"{_held}주",
                                         f"{_held * 12 / 52:.1f}개월", delta_color="off")
                            _k[1].metric("진입 후 최고가", f"${_pk_v:,.2f}",
                                         f"{_pk_d:%Y-%m-%d}", delta_color="off")
                            _k[2].metric("최고가 미갱신", f"{_dry}주",
                                         f"문턱 {TAKE_DRY}주", delta_color="off")
                            _k[3].metric("최고가 대비 현재", f"{_now / _pk_v - 1:+.0%}",
                                         f"${_now:,.2f}", delta_color="off")
                            if _held < TAKE_FLOOR:
                                st.info(f"**보유** — 최소 보유 {TAKE_FLOOR}주에 "
                                        f"{TAKE_FLOOR - _held}주 모자란다({_held}주). "
                                        "이 구간에서는 익절 판정을 켜지 않는다 — "
                                        "1년 안에 파는 규칙은 전부 알파를 깎았다.")
                            elif _dry >= TAKE_DRY:
                                st.error(f"**매도 신호** — 보유 {_held}주, 최고가 미갱신 "
                                         f"{_dry}주로 문턱 {TAKE_DRY}주를 넘었다. "
                                         "전진이 멈췄다는 뜻이다.")
                            else:
                                st.success(f"**보유** — 최고가 미갱신 {_dry}주로 문턱 "
                                           f"{TAKE_DRY}주 미만. 앞으로 {TAKE_DRY - _dry}주 "
                                           "안에 신고가를 다시 내면 계속 간다.")
                        st.caption(
                            "⚠️ **여기서 '현재'는 이 곡선의 마지막 주차다.** 가격 곡선은 "
                            "(첫 신호 −26주) ~ (마지막 신호 +104주) 창으로만 저장되므로, "
                            "오래전에만 신호가 났던 종목은 곡선이 이미 끊겨 있어 실제 오늘이 아니다. "
                            "⚠️ 이 규칙은 **트레이드 단위 백테스트**(알파 15.0% · 무매도 10.6% · "
                            "앞뒤 두 구간 모두 통과)에서 나왔고, 자본 제약(칸 수)은 넣지 않았다. "
                            "5칸에 52주 최소보유면 연 5종밖에 못 산다.")
                _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                # 2026-10-26 — 한 종목의 신호 이력(시점별 한 줄)이라 종목 목록 표준과 다르다. 28열 → 신호 시점 판단에 쓰는 11열로.
                st.dataframe(pd.DataFrame([{
                    '주차': r['d'], '회차': r['n'], '그주상승(%)': r['up'], '종가(현지)': r['close'],
                    '52주고점대비(%)': r['dd'], '매출가속(%p)': r['rva'], '이익가속(%p)': r['oia'],
                    '매출YoY(%)': r['revy'], 'OPM(%)': r['opm'], 'PER(배)': r.get('per'),
                    '이후4주(%)': r.get('f4'), '이후13주(%)': r.get('f13'), '이후52주(%)': r.get('f52'),
                    '이후104주(%)': r.get('f104')} for r in _ar]), hide_index=True,
                    column_config={'주차': st.column_config.TextColumn(help='신호가 난 주'),
                                   '52주고점대비(%)': st.column_config.NumberColumn(format='%+.1f', help='그 주 기준'),
                                   'PER(배)': st.column_config.NumberColumn(format='%.1f', help='그 주 기준')})
                st.caption(
                    "회차는 이 종목이 이익 가속 신호를 몇 번째로 낸 것인지다. "
                    "실측상 11회를 넘어가면 시장 대비 초과수익이 꺾인다.")

                # ── 이익 가속: 주차별 조회 ────────────────────────────
                # 2026-10-19 — 신호 0종 주차는 목록에서 빠져 '09-07 에서 멈춘' 것처럼 보였다.
                #   실제 산출은 매주 돌고 있었다. 최근 26주는 0종이어도 싣고,
                #   그 주 조건별 통과 수(깔때기)를 같이 보여 '진짜 없음'과 '데이터 고장'을 가른다.
                _wk = _ac.get('weeks') or {}
                _fn = _ac.get('funnel') or {}
                _wks = sorted(set(_wk) | set((_ac.get('dates') or [])[-26:]), reverse=True)
                st.markdown("#### 📅 주차별 조회 — 그 주에 함께 걸렸던 종목 전부")
                st.caption(f"최신 산출 주차 **{_ac.get('signal_week', '?')}** · "
                           f"생성 {_ac.get('generated', '?')} · 유니버스 {_ac.get('universe', 0):,}종 "
                           "— 매주 토요일 새벽(KST) 자동 갱신. 0종인 주도 목록에 나옵니다.")
                _wpick = st.selectbox(
                    f"주차 선택 — 최근 26주 + 신호가 있었던 주 ({len(_wks)}주)",
                    _wks, index=0, key="accel_wk",
                    format_func=lambda w: f"{w}  ({len(_wk.get(w, []))}종)")
                _wr = _wk.get(_wpick, [])
                if _wpick in _fn:
                    _f = _fn[_wpick]
                    _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                    st.dataframe(pd.DataFrame([{
                        '유니버스': _f['universe'], '유동성 통과': _f['liquid'],
                        '재무 확인됨': _f['acc_known'], '이익·매출 가속': _f['acc'],
                        '주간 +10%': _f['surge'], '최종 신호': _f['final']}]),
                        use_container_width=True, hide_index=True, row_height=25)
                    if not _wr:
                        st.info("이 주는 조건을 모두 통과한 종목이 없습니다. "
                                "'재무 확인됨'이 유동성 통과의 절반 아래면 시장이 아니라 "
                                "재무 데이터 수집 문제를 의심하십시오.")
                _wf = [r['f52'] for r in _wr if r.get('f52') is not None]
                _wc = st.columns(4)
                _wc[0].metric("그 주 신호", f"{len(_wr)}종")
                _wc[1].metric("1년 평균", f"{sum(_wf)/len(_wf):.1f}%" if _wf else "미도래")
                _wc[2].metric("1년 승률",
                              f"{sum(1 for x in _wf if x > 0)/len(_wf)*100:.0f}%" if _wf else "—")
                _wc[3].metric("2배 이상",
                              f"{sum(1 for x in _wf if x >= 100)/len(_wf)*100:.0f}%" if _wf else "—")
                # ── 그 주 코호트의 이후 1년 분포 ────────────────────
                # 평균 하나로는 U자 분포가 안 보인다. 종목별 막대로 흩어짐을 그대로 보여준다.
                _wd = [(r['sym'], r['f52']) for r in _wr if r.get('f52') is not None]
                if _wd:
                    _wd.sort(key=lambda x: -x[1])
                    _fw = go.Figure(go.Bar(
                        x=[x[0] for x in _wd], y=[x[1] for x in _wd],
                        marker_color=['#1f6b45' if v >= 100 else
                                      '#7fae95' if v > 0 else '#a03028' for _, v in _wd],
                        hovertemplate='%{x}<br>이후 1년 %{y:+.1f}%<extra></extra>'))
                    _fw.add_hline(y=0, line_width=1, line_color='#7c8290')
                    _fw.add_hline(y=100, line_width=1, line_dash='dot', line_color='#1f6b45',
                                  annotation_text='2배', annotation_position='right')
                    _fw.update_layout(height=300, margin=dict(l=8, r=8, t=34, b=8),
                                      title=f"{_wpick} 코호트 · 이후 1년 수익률 ({len(_wd)}종)",
                                      yaxis_title='이후 1년 (%)', showlegend=False)
                    st.plotly_chart(_fw, use_container_width=True)
                    st.caption(
                        "**진한 초록 = 2배 이상.** 평균 하나로는 이 분포가 안 보인다 — "
                        "몇 종목이 전체를 끌고 가고 나머지는 시장에 집니다. 등가중으로 담으면 "
                        "받는 것은 평균이지만, 그 평균은 소수 종목이 만듭니다.")
                if _wr:
                    _std_table(pd.DataFrame([{'코드': r['sym'], '종목': r['name'], '회차': r['n'], '그주상승(%)': r['up'],
                                              '이후13주(%)': r.get('f13'), '이후52주(%)': r.get('f52'),
                                              '이후104주(%)': r.get('f104')} for r in _wr]),
                               ['회차', '그주상승(%)', '이후13주(%)', '이후52주(%)', '이후104주(%)'],
                               src='Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json',
                               column_config={'이후13주(%)': st.column_config.NumberColumn(format='%+.1f', help='신호 주 종가 → 13주 뒤'),
                                              '이후52주(%)': st.column_config.NumberColumn(format='%+.1f', help='신호 주 종가 → 52주 뒤'),
                                              '이후104주(%)': st.column_config.NumberColumn(format='%+.1f', help='신호 주 종가 → 104주 뒤')},
                               note='탭 고유 열 = 그 주 기준 · 오른쪽 공통 열 = 지금 기준')
                st.caption(
                    "그 주에 함께 걸린 종목 전부다. **한 종목이 걸렸다는 사실만으로는 "
                    "조건의 실효를 판단할 수 없다** — 같은 주 전 종목의 타율을 함께 봐야 합니다. "
                    "위 지표가 그 코호트 성적입니다.")

            # 기간별 성적 — 표 셋을 따로 두면 화면이 지저분해진다. 한 곳에서 전환한다.
            if _ac.get('by_year') or _ac.get('by_moy'):
                with st.expander("📅 기간별 성적 — 신호 1건당 1년 후"):
                    _per = st.radio("기간", ["연도별", "달별", "연-월"],
                                    horizontal=True, key="accel_period",
                                    label_visibility="collapsed")
                    if _per == "연도별" and _ac.get('by_year'):
                        _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                        st.dataframe(pd.DataFrame([{
                            '연도': y, '신호': v['n'], '평균': v['mean'],
                            '시장대비': v['alpha'], '2배+%': v['w2'], '4배+%': v['w4']}
                            for y, v in sorted(_ac['by_year'].items())]),
                            use_container_width=True, hide_index=True, row_height=25)
                        st.caption("2020년과 2025년이 전체 성적의 대부분을 만듭니다. "
                                   "그 두 해를 빼면 시장을 이기지 못합니다.")
                    elif _per == "달별" and _ac.get('by_moy'):
                        _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                        st.dataframe(pd.DataFrame([{
                            '달': f"{v['mo']}월", '신호': v['n'], '평균': v['mean'],
                            '시장대비': v['alpha'], '2배+%': v['w2']}
                            for v in _ac['by_moy']]),
                            use_container_width=True, hide_index=True,
                            row_height=25, height=_dfh(12))
                        st.caption("⚠️ 계절성으로 읽으면 위험합니다. 달마다 표본이 "
                                   "300~800건인데 한 해가 결과를 통째로 끌고 갑니다. "
                                   "'4월에 사라'가 아니라 '4월 신호는 이랬다'로 읽으십시오.")
                    elif _ac.get('by_month'):
                        _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json')
                        st.dataframe(pd.DataFrame([{
                            '연월': v['ym'], '신호': v['n'], '평균': v['mean'],
                            '시장대비': v['alpha'], '중앙값': v['med'], '2배+%': v['w2']}
                            for v in _ac['by_month']]),
                            use_container_width=True, hide_index=True,
                            row_height=25, height=_dfh(20))
                        st.caption("한 달 표본은 평균 60건 안팎입니다. "
                                   "한두 종목이 평균을 흔듭니다.")

            # ── 기간별 신호 경과 ─────────────────────────────────
            # "이번 달·분기에 걸린 종목이 지금 어떻게 됐나" 를 종목 한 줄로 답한다.
            if _ac.get('roster'):
                st.markdown("#### 📆 기간별 신호 경과 — 그때 걸린 종목이 지금 어떻게 됐나")
                _rc1, _rc2 = st.columns([2, 3])
                _span = _rc1.selectbox(
                    "기간", ["이번 달", "최근 3개월", "상반기", "하반기", "올해", "직전 연도"],
                    key="roster_span")
                _sw = _rc2.selectbox("정렬", ["수익률 높은 순", "수익률 낮은 순",
                                            "신호 많은 순", "최근 신호 순"], key="roster_sort")
                _today = pd.Timestamp(_ac.get('signal_week') or pd.Timestamp.today())
                _y = _today.year
                if _span == "이번 달":
                    _lo, _hi = _today.replace(day=1), _today
                elif _span == "최근 3개월":
                    _lo, _hi = _today - pd.Timedelta(days=92), _today
                elif _span == "상반기":
                    _lo, _hi = pd.Timestamp(_y, 1, 1), pd.Timestamp(_y, 6, 30)
                elif _span == "하반기":
                    _lo, _hi = pd.Timestamp(_y, 7, 1), pd.Timestamp(_y, 12, 31)
                elif _span == "올해":
                    _lo, _hi = pd.Timestamp(_y, 1, 1), _today
                else:
                    _lo, _hi = pd.Timestamp(_y - 1, 1, 1), pd.Timestamp(_y - 1, 12, 31)

                _rs = [x for x in _ac['roster']
                       if x.get('first') and _lo <= pd.Timestamp(x['first']) <= _hi]
                _key = {'수익률 높은 순': lambda x: -(x.get('ret') if x.get('ret') is not None else -1e9),
                        '수익률 낮은 순': lambda x: (x.get('ret') if x.get('ret') is not None else 1e9),
                        '신호 많은 순': lambda x: -x.get('n', 0),
                        '최근 신호 순': lambda x: x.get('last') or ''}[_sw]
                _rs = sorted(_rs, key=_key, reverse=(_sw == '최근 신호 순'))

                if not _rs:
                    st.info(f"{_span}에 신호가 난 종목이 없습니다.")
                else:
                    _win = [x for x in _rs if (x.get('ret') or 0) > 0]
                    _k = st.columns(4)
                    _k[0].metric("종목 수", f"{len(_rs)}종")
                    _rets = [x['ret'] for x in _rs if x.get('ret') is not None]
                    _k[1].metric("첫 신호 이후 평균",
                                 f"{sum(_rets)/len(_rets):+.1f}%" if _rets else "—")
                    _k[2].metric("플러스 종목",
                                 f"{len(_win)/len(_rs)*100:.0f}%" if _rs else "—",
                                 help="첫 신호 시점 종가와 최신 종가를 비교한 값입니다.")
                    _k[3].metric("2배 이상",
                                 f"{sum(1 for x in _rs if (x.get('ret') or 0) >= 100)}종")
                    _rost = [{'코드': x['sym'], '종목': x['name'], '첫 신호': x['first'], '신호 수(건)': x['n'],
                              '첫 신호 이후(%)': x.get('ret'), '최고(%)': x.get('best'), '최저(%)': x.get('worst')} for x in _rs]
                    _std_table(pd.DataFrame(_rost), ['첫 신호', '신호 수(건)', '첫 신호 이후(%)', '최고(%)', '최저(%)'],
                               src='Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json', path='results/leaders_accel.json',
                               column_config={'첫 신호 이후(%)': st.column_config.NumberColumn(format='%+.1f'),
                                              '최고(%)': st.column_config.NumberColumn(format='%+.1f', help='첫 신호 이후 최대 상승'),
                                              '최저(%)': st.column_config.NumberColumn(format='%+.1f', help='첫 신호 이후 최대 하락 — 들고 있었다면 견뎌야 했던 폭')},
                               note=f'정렬: {_sw}')
                    _cand_register(_rost, 'accel_r')
                    st.caption(
                        "**수익률**은 그 종목의 **첫 신호 주 종가**와 최신 종가를 비교한 값입니다. "
                        "**최고·최저**는 그 사이에 겪었을 최대 상승과 최대 하락으로, "
                        "들고 있었다면 견뎌야 했던 폭입니다. "
                        "신호가 여러 번 난 종목은 나중 신호에서 샀다면 결과가 다릅니다.")
                st.divider()


            st.divider()

# ── 🗄️ 기각된 규칙 (2026-10-26 차니 결정) — 기각된 규칙은 지우지 않고(성적이 나쁜 신호도 남긴다는 원칙) 한곳으로 모으되,
#   기본은 접어 둔다. 켜야 그린다(계산도 그때만).
with t_lead:
    st.divider()
    st.markdown("#### 🗄️ 기각된 규칙")
    _show_rej = st.toggle("한국 KR-U6 / KR-P1 — 상폐 포함 백테스트에서 KOSPI 에 져서 기각(원칙 v1.2) · 관찰 기록 보기",
                          value=False, key="show_rejected")
if _LEAD_KR and _show_rej:
    with t_lead, guard('주도주 KR'):
        st.markdown("##### 🇰🇷 한국 — KR-U6 / KR-P1 · 기각 · 관찰 기록")
        # 2026-10-20: 원칙 v1.2(10-14)에서 KR 위성은 기각됐는데 화면은 매수 후보처럼 보였다 → 맨 위에 못 박는다.
        st.warning(
            "**백테스트 기각 · 참고용 — 매수 대상 아님.** 상장폐지 649종을 넣은 2014~2026 검증에서 "
            "KR-P1 은 CAGR **4.3%** · MDD **-66%** 로 KOSPI(**9.3%** · -39%)에 졌다. "
            "원인은 시장 구조(거래 가능한 한국 종목 전체가 KOSPI 보다 연 9%p 뒤짐, 신호 우위는 +1%p 남짓). "
            "**원칙 v1.2: 한국 노출은 지수(코스피200 등)로 갖는다.** 아래 신호·원장은 관찰 기록으로만 남긴다. "
            "근거 `research/kr_bt/RESULTS_2026-10-14.md`", icon="🚫")
        # 2026-08-16: 미국 규칙⑥ 원문을 KR에 이식한 KR-U6 추가. 실측에서 KR-P1보다 우수해
        # 기본값으로 둔다(평균 11.5% vs 9.6% · 손익비 3.53 vs 3.05 · 꼬리의존 36% vs 47%).
        _kr_rule = st.radio(
            "규칙", ["🇺🇸 규칙⑥ 이식 (KR-U6)", "📈 52주 신고가 (KR-P1)"],
            horizontal=True, key="kr_rule",
            help="KR-U6 = 미국 규칙⑥ 조건 그대로(RS13>1.5 · 흑자전환/이익폭증 · OPM>0 · 대형주). "
                 "KR-P1 = 52주 신고가 기반 자체 규칙.")

    if st.session_state.get('kr_rule', '🇺🇸').startswith('🇺🇸'):
      with t_lead, guard('주도주 KR-U6'):
        st.caption(data_stamp('results/leaders_kr6.json'))
        _u6 = load_json(Path('results/leaders_kr6.json'))
        if not _u6:
            st.warning("KR-U6 데이터 없음 → 로컬에서 `python leaders_kr6.py publish` 실행 후 커밋.")
        else:
            _b30 = _u6['backtest']['trail30']['US그대로']
            st.markdown(
                f"<div style='background:#f0fdf4;border:1px solid #86efac;border-left:4px solid #16a34a;"
                f"border-radius:10px;padding:13px 17px'>"
                f"<b style='color:#15803d'>미국 규칙⑥ 원문을 그대로 이식</b>"
                f"<span style='color:#6b7280;font-size:12.5px'> · 손절만 KR에 맞춰 -30%</span>"
                f"<div style='font-size:13px;color:#374151;margin-top:6px'>"
                f"진입 조건은 미국판과 <b>완전히 동일</b>합니다 — RS13&gt;1.5 · (흑자전환 OR 이익폭증) · "
                f"OPM&gt;0 · 시총 2.8조↑ · 거래대금 70억↑. 이익폭증 4종 정의도 원문 그대로입니다."
                f"</div></div>", unsafe_allow_html=True)
            st.markdown(f"**규칙** `{_u6['rule']}`  \n기간 {_u6['period']} · 생성 {_u6['generated']}")

            _c1, _c2, _c3, _c4 = st.columns(4)
            _c1.metric("거래당 평균수익", f"{_b30['avg']}%")
            _c2.metric("승률", f"{_b30['winrate']}%", f"중앙값 {_b30['med']}%", delta_color="off")
            _c3.metric("손익비", f"{_b30['payoff']}", "KR-P1은 3.05", delta_color="off")
            _c4.metric("상위 1% 의존", f"{_b30['tail']}%", "KR-P1은 46.7%", delta_color="off")

            st.markdown(f"**이번 후보 {_u6['n']}종** — 최근 10주 내 진입 신호, 아직 트레일링 미도달")
            if _u6['candidates']:
                _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr6.json', path='results/leaders_kr6.json')
                st.dataframe(pd.DataFrame([{
                    '종목': c['name'][:18], '코드': c['sym'], '진입일': c['entry_date'],
                    '진입가': f"{c['entry_px']:,.0f}", '현재가': f"{c['close']:,.0f}",
                    '수익률': f"{c['ret']:+.1f}%",
                    '시총': (f"{c['marcap_jo']}조" if c.get('marcap_jo') else '-'),
                    '거래대금': (f"{c['adv_eok']:,}억" if c.get('adv_eok') else '-'),
                    '트레일링 손절가': f"{c['stop']:,.0f}", '경과': f"{c['days']}일",
                } for c in _u6['candidates']]), use_container_width=True, hide_index=True,
                    row_height=25, height=_dfh(len(_u6['candidates'])))
            else:
                st.info("현재 조건 충족 종목 없음 — 연 29건 빈도라 비어 있는 주가 많습니다.")

            with st.expander("🔬 손절폭이 전부였다 — 진입 조건은 미국판이 더 좋다"):
                st.markdown("규칙⑥을 **-20%(미국 운용값)로 그대로 쓰면 KR에서 망가집니다.** "
                            "손절만 -30%로 바꾸면 오히려 KR 자체 규칙(KR-P1)을 넘는다:")
                _rows = []
                for tr_key, tr_lab in (('trail20', '-20% (미국 운용값)'), ('trail30', '-30% (KR 조정)')):
                    for lab, v in _u6['backtest'][tr_key].items():
                        _rows.append({'손절폭': tr_lab, '임계값': lab, '거래': f"{v['n']:,}",
                                      '승률': f"{v['winrate']}%", '평균수익': f"{v['avg']}%",
                                      '손익비': v['payoff'], '상위1% 의존': f"{v['tail']}%"})
                _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr6.json', path='results/leaders_kr6.json')
                st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                             row_height=25, height=_dfh(6))
                st.markdown("- **-20% → -30%로 바꾸는 것만으로 평균 3.46% → 11.50%.** "
                            "미국 시장에서 검증된 손절폭이 한국에서는 노이즈에 털린다.")
                st.markdown("- **시총 컷을 낮추면 급격히 나빠진다**: 2.8조 11.5% → 3천억 5.2% → 1천억 5.1%. "
                            "동시에 상위 1% 의존도가 36% → 88% → 91%로 폭증합니다. "
                            "**이 규칙은 대형주에서만 작동합니다.**")
                st.caption("⚠️ n=235는 표본이 작다(연 29건). 상위 1% 거래 2~3건이 수익의 36%를 만듭니다. "
                           "적은 표본 + 꼬리 의존은 '운이었을 가능성'을 배제하지 못합니다.")

            with st.expander("📌 에코프로는 잡히나 — 사례 점검"):
                st.markdown("""
**잡힙니다.** 규칙⑥ 이식판이 2023년에 세 번 진입했습니다:

| 진입일 | 결과 |
|---|---|
| 2023-02-13 | **+208%** |
| 2023-04-14 | −10% |
| 2023-05-12 | +81% |

2023-02-06 종가 28,685원 기준 추정 시총 **3.62조** — 미국 기준 시총 컷($2B=2.8조)을 통과합니다.
에코프로비엠도 2023-02-21 진입 **+44%**.

> 시총 컷 때문에 코스닥 중소형을 놓칠 거라는 우려가 있었지만, **에코프로는 이미 대형주였습니다.**
> 오히려 컷을 낮추면 성과가 무너집니다(위 표).
""")
            with st.expander("⚠️ 한계"):
                for c in _u6.get('caveats', []):
                    st.markdown(f"- {c}")
    else:
      with t_lead, guard('주도주 KR-P1'):
        st.caption(data_stamp('results/leaders_kr.json'))
        _kr = load_json(Path('results/leaders_kr.json'))
        if not _kr:
            st.warning("KR 주도주 데이터 없음 → 로컬에서 `python leaders_kr.py publish` 실행 후 커밋.")
        else:
            _kbt = _kr['backtest'].get(str(int(_kr['params']['trail'])), {})
            st.markdown(
                f"<div style='background:#fffbeb;border:1px solid #fcd34d;border-left:4px solid #d97706;"
                f"border-radius:10px;padding:13px 17px'>"
                f"<b style='color:#92400e'>검증 등급 C — 연구용</b>"
                f"<span style='color:#6b7280;font-size:12.5px'> · 미국 규칙⑥(등급 A−)과 같은 무게로 쓰면 안 됩니다</span>"
                f"<div style='font-size:13px;color:#374151;margin-top:6px'>"
                f"KR은 <b>분기 재무가 없어</b> 규칙⑥의 핵심 조건인 '이익 변곡'을 넣지 못했습니다"
                f"(보유 재무: 연간 2023~2025, 835종). 그래서 <b>가격만으로</b> 만든 규칙입니다. "
                f"검증 자료가 아직 없습니다.</div></div>", unsafe_allow_html=True)
            st.markdown(f"**진입** `{_kr['rule']}`  \n"
                        f"**유동성 컷** 20일 평균 거래대금 "
                        f"{_kr['params'].get('min_adv_eok', '-')}억 이상 (체결 가능한 신호만)  \n"
                        f"유니버스 {_kr['universe']:,}종 · 기간 {_kr['period']} · 생성 {_kr['generated']}")

            _k1, _k2, _k3, _k4 = st.columns(4)
            _k1.metric("거래당 평균수익", f"{_kbt.get('avg','-')}%",
                       help="왕복 비용 0.3% 차감 + 거래대금 컷 적용 후. 컷을 빼면 12.0%로 오르지만 "
                            "그건 체결 불가능한 소형주 신호를 포함한 값이라 쓰지 않는다.")
            _k2.metric("승률", f"{_kbt.get('winrate','-')}%", f"중앙값 {_kbt.get('med','-')}%",
                       delta_color="off", help="중앙값이 음수 = 전형적 거래는 손실입니다. 소수의 대박이 전부를 만듭니다")
            _k3.metric("손익비", f"{_kbt.get('payoff','-')}")
            _k4.metric("상위 1% 의존도", f"{_kbt.get('top1pct_share','-')}%",
                       help="전체 수익 중 상위 1% 거래가 차지하는 비중. 높을수록 몇 건을 놓치면 무너집니다")

            st.markdown(f"**이번 후보 {_kr['n']}종** — 최근 8주 내 신고가 돌파 후 아직 트레일링에 안 걸린 종목")
            if _kr['candidates']:
                _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr.json', path='results/leaders_kr.json')
                st.dataframe(pd.DataFrame([{
                    '종목': c['name'][:18], '코드': c['sym'], '돌파일': c['entry_date'],
                    '돌파가': f"{c['entry_px']:,.0f}", '현재가': f"{c['close']:,.0f}",
                    '수익률': f"{c['ret']:+.1f}%", '고점대비': f"{c['ret']-c['peak_gain']:+.1f}%",
                    '거래대금': (f"{c['adv_eok']:,}억" if c.get('adv_eok') else '-'),
                    '트레일링 손절가': f"{c['stop']:,.0f}", '경과': f"{c['days']}일",
                } for c in _kr['candidates']]), use_container_width=True, hide_index=True,
                    row_height=25, height=_dfh(len(_kr['candidates'])))
            else:
                st.info("이번 주 조건 충족 종목 없음")

            with st.expander("📉 손절폭을 왜 -30%로 정했나 · 기각된 조건"):
                st.caption("전 종목 1,476종·2018~2026 백테스트. 넓힐수록 단조 개선됐다.")
                _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr.json', path='results/leaders_kr.json')
                st.dataframe(pd.DataFrame([{
                    '트레일링': k + '%', '거래': f"{v['n']:,}", '승률': f"{v['winrate']}%",
                    '평균수익': f"{v['avg']}%", '중앙값': f"{v['med']}%",
                    '손익비': v['payoff'], '보유(중앙)': f"{v['hold_d']}일",
                    '상위1% 의존': f"{v['top1pct_share']}%",
                } for k, v in sorted(_kr['backtest'].items(), key=lambda x: int(x[0]))]),
                    use_container_width=True, hide_index=True, row_height=25, height=_dfh(6))
                st.markdown("**검증에서 기각된 조건** (넣으면 오히려 나빠짐)")
                st.markdown("- ~~상대강도 RS13 ≥ 1.2~~ — 평균 11.9% → 10.5%")
                st.markdown("- ~~상대강도 RS13 ≥ 1.5~~ — 평균 11.9% → 8.4%")
                st.markdown("- ~~상대강도 RS13 ≥ 2.0~~ — 평균 11.9% → 3.7%, 손익비 3.09 → 2.54")
                st.caption("US 규칙⑥의 **핵심 조건인 RS13>1.5가 KR에서는 단조로 성과를 깎았다.** "
                           "52주 신고가 자체가 이미 강한 모멘텀 필터라, RS를 겹치면 '이미 너무 오른 것'만 "
                           "남아 되돌림이 커지는 것으로 보인다. 같은 아이디어가 시장을 건너면 뒤집힐 수 있다는 증거.")

            with st.expander("📊 이익 변곡 필터 — 수익은 그대로, 거래는 68% 감소"):
                _ab = _kr.get('earn_ab', {})
                if _ab:
                    _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr.json', path='results/leaders_kr.json')
                    st.dataframe(pd.DataFrame([
                        {'규칙': '가격만 (52주 신고가)', '거래': f"{_ab['price_only']['n']:,}",
                         '승률': f"{_ab['price_only']['winrate']}%",
                         '평균수익': f"{_ab['price_only']['avg']}%",
                         '손익비': _ab['price_only']['payoff'],
                         '상위1% 의존': f"{_ab['price_only']['tail']}%"},
                        {'규칙': '+ 이익 변곡 (채택)', '거래': f"{_ab['with_earn']['n']:,}",
                         '승률': f"{_ab['with_earn']['winrate']}%",
                         '평균수익': f"{_ab['with_earn']['avg']}%",
                         '손익비': _ab['with_earn']['payoff'],
                         '상위1% 의존': f"{_ab['with_earn']['tail']}%"}]),
                        use_container_width=True, hide_index=True, row_height=25, height=_dfh(2))
                st.markdown("**평균수익은 개선되지 않았다** (9.79% → 9.60%). "
                            "이 분산에서는 구분할 수 없는 차입니다.")
                st.markdown("그런데도 켜는 이유는 '수익'이 아니라 **선별성**이다:")
                st.markdown("- 거래가 **5,079 → 1,599건으로 68% 감소**. 연 590건은 개인이 다룰 수 없고, "
                            "연 186건은 다룰 수 있습니다. **실행 가능성이 곧 전략의 일부다.**")
                st.markdown("- 손익비 2.96 → 3.05, 상위 1% 의존도 49.3% → 46.7%로 **꼬리 의존이 완화**됩니다.")
                st.markdown("- **에코프로 2023-02-06 진입(+256%)은 필터를 통과한다** — 잡고 싶은 걸 죽이지 않는다.")
                st.caption("판정은 **공시 시차**를 반영한다: 2023Q1 실적은 3/31이 아니라 5월 중순에야 "
                           "알 수 있으므로, 분기말+50일(사업보고서 90일) 이후부터만 참조합니다. "
                           "이걸 안 하면 미래를 훔쳐보는 백테스트가 됩니다.")

            with st.expander("💧 유동성 컷을 왜 넣었나 — 백테스트 수익을 깎는데도"):
                _sp = _kr.get('adv_spectrum', {})
                if _sp:
                    _tsrc('FinanceDataReader(KRX 주가)·DART(재무) → leaders_kr.json', path='results/leaders_kr.json')
                    st.dataframe(pd.DataFrame([{
                        '거래대금 컷': f"{k}억", '거래': f"{v['n']:,}",
                        '평균수익': f"{v['avg']}%", '손익비': v['payoff'],
                        '상위1% 의존': f"{v['tail']}%",
                    } for k, v in sorted(_sp.items(), key=lambda x: int(x[0]))]),
                        use_container_width=True, hide_index=True, row_height=25, height=_dfh(6))
                st.markdown("컷을 올릴수록 백테스트 수익은 **단조로 떨어진다** (12.0% → 6.4%). "
                            "그런데도 넣는 이유:")
                st.markdown("- 컷 없는 **12.0% 안에는 실제로는 체결할 수 없는 소형주 신호가 섞여 있습니다.** "
                            "낮아진 9.8%가 '진짜 값'입니다.")
                st.markdown("- 필터가 성과를 깎는다고 빼면 **백테스트만 예뻐지고 실전은 그대로**다.")
                st.markdown("- 10억은 개인 자금 규모에서 체결 가능한 최소선으로 잡았다.")
                st.caption("⚠️ 다만 컷을 올릴수록 **상위 1% 의존도가 44% → 70%로 오른다.** "
                           "유동성을 요구할수록 소수의 대박에 더 기대게 됩니다 — 분산이 더 중요해집니다.")

            with st.expander("⚠️ 이 숫자를 믿으면 안 되는 이유 (반드시 읽을 것)"):
                for c in _kr.get('caveats', []):
                    st.markdown(f"- {c}")
                st.caption("특히 **중앙값이 -11%**다. 셋 중 둘은 손실로 끝나고, 수익의 44%가 상위 1% 거래에서 나옵니다. "
                           "몇 건의 대박을 놓치면 전체가 마이너스가 되는 구조라 **분산과 규율 없이는 재현되지 않는다.**")

            with st.expander("📚 사례 연구 — 2023 에코프로로 검증한 것"):
                st.markdown("""
**진입은 쉬웠다.** 52주 신고가 규칙이 **2023-02-06, 28,685원**에 잡았다. 고점(7/25)까지 **8.8배**.

**문제는 전부 청산 쪽이었다.** 그 상승 구간에 최대 **-32.2%** 눌림이 있었다.

| 손절폭 | 거래 | 누적수익 | 1%리스크 비중 | 포트 기여 |
|---|---|---|---|---|
| -7% (구 룰) | 6 | +188% | 14% | +27% |
| **-10%** | 3 | +393% | 10% | **+39%** |
| -20% | 2 | +430% | 5% | +21% |
| -30% | 2 | +315% | 3% | +10% |

매수후보유는 2024년 말 +97%, 오늘 +218% (고점 대비 **-64%**) — **안 팔면 대부분 토해낸다.**

> ⚠️ **주의**: 이 표만 보면 -10%가 답 같지만, **전 종목 1,476종으로 보면 -30%가 최고다**
> (평균 11.9% vs 2.3%). 단일 종목으로 파라미터를 정하면 안 된다는 반례로 남겨둔다.

**기저율**: 2023년 KR 1,350종 중 고점 10배 이상은 **5종(0.4%)**, 연말까지 유지한 건 **1종**.
"내년에 하나 나옵니다"는 맞지만 "그게 뭔지 미리 안다"는 틀리다. → 한 종목을 맞히는 게 아니라
**후보 여러 개를 규칙으로 태우는 것**이 유일한 방법.
""")

    # ── 포워드 원장 (두 규칙 공통) ──────────────────────────────────
    # 백테스트는 '지금 시점에서 과거를 다시 계산'이라 생존편향·데이터 개정·규칙
    # 사후조정이 섞인다. 원장은 '신호를 낸 그날 이후'만 쌓아 그 오염이 안 들어온다.
    with t_lead, guard('주도주 KR 포워드 원장'):
        _kp = load_json(Path('results/leaders_kr_paper.json'))
        st.divider()
        st.markdown("#### 📒 포워드 원장 — 신호를 낸 뒤 실제로 어떻게 됐나")
        if not _kp:
            st.info("아직 원장이 없습니다 → `python leaders_kr_paper.py update` "
                    "(weekly-profile이 매주 자동 실행)")
        else:
            st.caption(f"시작 {_kp.get('started','-')} · 갱신 {_kp.get('updated','-')} — "
                       f"위 백테스트와 달리 **사후 계산이 아니라 발행 이후 누적**입니다.")
            _rows, _closed_all = [], 0
            for _rn, _pos in (_kp.get('positions') or {}).items():
                _cl = [r for r in _pos.values() if r.get('state') == 'closed' and r.get('ret') is not None]
                _op = [r for r in _pos.values() if r.get('state') != 'closed' and r.get('ret') is not None]
                _w = [r['ret'] for r in _cl if r['ret'] > 0]
                _l = [r['ret'] for r in _cl if r['ret'] <= 0]
                _closed_all += len(_cl)
                _rows.append({
                    '규칙': _rn, '누적': len(_pos), '보유': len(_op), '청산': len(_cl),
                    '청산 평균': (f"{sum(r['ret'] for r in _cl)/len(_cl):+.1f}%" if _cl else '—'),
                    '승률': (f"{len(_w)/len(_cl)*100:.0f}%" if _cl else '—'),
                    # 손익비는 이익·손실 표본이 둘 다 있어야 의미가 있다. 한쪽만으로
                    # 계산하면 큰 수가 찍혀 오해를 만든다.
                    '손익비': (f"{(sum(_w)/len(_w))/abs(sum(_l)/len(_l)):.2f}" if _w and _l else '—'),
                    '보유 평균(미실현)': (f"{sum(r['ret'] for r in _op)/len(_op):+.1f}%" if _op else '—'),
                })
            _tsrc('leaders_kr.json 신호의 포워드 기록 → leaders_kr_paper.json', path='results/leaders_kr_paper.json')
            st.dataframe(pd.DataFrame(_rows), use_container_width=True, hide_index=True,
                         row_height=25, height=_dfh(len(_rows)))
            if _closed_all < 30:
                st.warning(f"청산 표본 **{_closed_all}건** — 30건 미만이면 승률·손익비는 노이즈입니다. "
                           f"이 표는 백테스트를 대체하지 않고, 백테스트가 실전에서 재현되는지만 봅니다.")
            _cur_rule = 'KR-U6' if st.session_state.get('kr_rule', '🇺🇸').startswith('🇺🇸') else 'KR-P1'
            _p = (_kp.get('positions') or {}).get(_cur_rule) or {}
            if _p:
                with st.expander(f"{_cur_rule} 원장 상세 {len(_p)}종"):
                    _tsrc('leaders_kr.json 신호의 포워드 기록 → leaders_kr_paper.json', path='results/leaders_kr_paper.json')
                    st.dataframe(pd.DataFrame([{
                        '종목': r.get('name', s)[:18], '코드': s,
                        '상태': ('청산' if r.get('state') == 'closed' else '보유'),
                        '최초포착': r.get('first_seen'), '진입일': r.get('entry_date'),
                        '진입가': (f"{r['entry_px']:,.0f}" if r.get('entry_px') else '-'),
                        '현재가': (f"{r['close']:,.0f}" if r.get('close') else '-'),
                        '수익률': (f"{r['ret']:+.1f}%" if r.get('ret') is not None else '-'),
                        '고점수익': (f"{r['peak_gain']:+.1f}%" if r.get('peak_gain') is not None else '-'),
                        '경과': (f"{r['days']}일" if r.get('days') else '-'),
                        '청산일': r.get('exit_date') or '-',
                    } for s, r in sorted(_p.items(),
                                         key=lambda x: -(x[1].get('ret') or -999))]),
                        use_container_width=True, hide_index=True, row_height=25,
                        height=_dfh(len(_p)))

# ── 종목 프로파일 (계절성 + MDD 통합) ──
# ── 💎 가치 발굴 — 기본적 분석 기준 (뭘 살까) ──
# ── 📈 52주 신고가 (2026-10-14 · 2026-10-19 주간 그래프·연속 경신·AI 공통점) ─────────────
@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _sector_map():
    """sym → 업종. KR 표준산업분류(sectors.json) · US SEC SIC 설명(us_domicile.csv)."""
    out = {}
    try:
        out.update(json.load(open('data/sectors.json', encoding='utf-8')))
    except Exception:
        pass
    try:
        _d = pd.read_csv('data/us_domicile.csv', usecols=['sym', 'sic_desc'])
        out.update({str(a): b for a, b in zip(_d.sym, _d.sic_desc) if isinstance(b, str)})
    except Exception:
        pass
    return out


@st.cache_data(ttl=3600 * 24, show_spinner=False)
def _h52_ai(week: str, mkt: str, payload: str) -> str:
    """버튼용 — 같은 주·같은 묶음이면 하루 캐시(Gemini 무료 한도 하루 20건). 코드는 new_high_ai.py 와 공용."""
    import new_high_ai as _nha
    key = ''
    try:
        key = st.secrets.get('GEMINI_KEY', '')
    except Exception:
        pass
    text, _ok = _nha.generate(week, mkt, payload, key=key or None)
    return text


with t_52, guard('52주 신고가'):
    st.caption("주봉 기준 — '경신'은 그 주 **고가**가 직전 52주 고가를 넘은 것. 장중 실시간이 아니라 매일 06시(KST) 갱신. "
               "커버: 한국 시총 1,000억+ · 미국 $3억+.")
    _p52 = load_json(PERF_JSON) or {}
    _s52 = _p52.get('stocks') or []
    _has_d = any(x.get('dist52') is not None for x in _s52)
    _has_nh = any('nh' in x for x in _s52)
    _mk52 = _GMKT
    _SEC52 = _sector_map()
    _cs52 = {}
    for _f in (CANSLIM_JSON, Path('results/canslim_us_latest.json')):
        for _x in (load_json(_f) or {}).get('stocks', []):
            _cs52[_x['sym']] = _x

    def _cg(sym):
        cg = (_cs52.get(sym) or {}).get('c_growth_pct')
        return cg if isinstance(cg, str) else (f"{cg:+.0f}%" if cg is not None else '-')

    # ── ① 주간 신고가 경신 종목 수 ───────────────────────────────
    st.markdown("##### 📊 주간 52주 신고가 경신 종목 수 — 막대를 누르면 그 주 종목이 아래에 나옵니다")
    if not _has_nh:
        st.info("주간 이력은 다음 자동 갱신(매일 06시)부터 채워집니다.")
    else:
        _wk = {}
        for x in _s52:
            if _mk52 != "전체" and x.get('market') != _mk52:
                continue
            for _d, _c in x.get('nh') or []:
                _wk.setdefault(_d, []).append((x, _c))
        _last = max(_wk) if _wk else None
        if _last:
            _weeks = pd.date_range(end=pd.Timestamp(_last), periods=52, freq='W-FRI')
            _wl = [str(w.date()) for w in _weeks]
            _kr_n = [sum(1 for x, _ in _wk.get(w, []) if x.get('market') == 'KR') for w in _wl]
            _us_n = [sum(1 for x, _ in _wk.get(w, []) if x.get('market') == 'US') for w in _wl]
            _sel = st.session_state.get('h52_week') or _last
            if _sel not in _wl:
                _sel = _last
            _fw = go.Figure()
            _op = [1.0 if w == _sel else 0.45 for w in _wl]
            if _mk52 != "US":
                _fw.add_trace(go.Bar(x=_weeks, y=_kr_n, name='🇰🇷 한국', marker=dict(color='#2453C8', opacity=_op),
                                     hovertemplate='%{x|%Y-%m-%d} 주 · 한국 %{y}종<extra></extra>'))
            if _mk52 != "KR":
                _fw.add_trace(go.Bar(x=_weeks, y=_us_n, name='🇺🇸 미국', marker=dict(color='#7C8AA5', opacity=_op),
                                     hovertemplate='%{x|%Y-%m-%d} 주 · 미국 %{y}종<extra></extra>'))
            _fw.update_layout(barmode='stack', height=240, margin=dict(l=8, r=8, t=8, b=8), bargap=0.25,
                              legend=dict(orientation='h', y=1.12, x=0, yanchor='bottom'),
                              yaxis=dict(title=None, gridcolor='#F3F4F6'), xaxis=dict(tickformat='%m/%d'))
            _ev = st.plotly_chart(_fw, use_container_width=True, on_select='rerun', selection_mode='points',
                                  key=f"h52_chart_{st.session_state.get('h52_ck', 0)}")
            try:
                _pts = (_ev.selection or {}).get('points') if isinstance(_ev.selection, dict) else _ev.selection.points
                if _pts:
                    _new_sel = str(pd.Timestamp(_pts[0]['x']).date())
                    if _new_sel != st.session_state.get('h52_week'):
                        st.session_state['h52_week'] = _new_sel
                        st.rerun()
            except Exception:
                pass
            _tot = [a + b for a, b in zip(_kr_n, _us_n)]
            _avg = sum(_tot[-13:]) / 13
            st.caption(f"최근 13주 평균 {_avg:.0f}종/주 · 최대 {max(_tot)}종({_wl[_tot.index(max(_tot))]}) · "
                       f"이번 주({_last}, 진행 중일 수 있음) {_tot[-1]}종. 숫자가 늘면 시장 폭이 넓어지는 것 — "
                       "지수만 오르고 신고가 종목이 줄면 소수 대형주 장세. ⚠️ 지금 커버 명단 기준이라 그 사이 상장폐지된 종목은 빠져 있다.")

            # ── ② 선택한 주의 신고가 종목 ──────────────────────────
            _items = sorted(_wk.get(_sel, []), key=lambda t: -(cap_usd_b(t[0].get('marcap'), t[0].get('market')) or 0))
            _cA, _cB = st.columns([3, 1])
            _cA.markdown(f"##### 🗓 {_sel} 주 신고가 경신 — {len(_items)}종")
            if _cB.button("이번 주로", key="h52_reset", disabled=_sel == _last):
                st.session_state['h52_week'] = _last
                st.session_state['h52_ck'] = st.session_state.get('h52_ck', 0) + 1   # 그래프 선택도 비운다
                st.rerun()
            if _items:
                _wrows = []
                for x, c in _items:
                    cur = x.get('curr_price')
                    _wrows.append({
                        '종목': ('🆕 ' if x.get('young') else '') + str(x.get('name')), '코드': x.get('sym'),
                        '그주 이후(%)': round((cur / c - 1) * 100, 1) if (cur and c) else None,
                        '연속(주)': x.get('nh_streak'), '8주중(회)': x.get('nh_8w')})
                _std_table(pd.DataFrame(_wrows), ['그주 이후(%)', '연속(주)', '8주중(회)'],
                           src='FinanceDataReader·yfinance(주가) → perf_latest.json(주차별 경신 이력)',
                           path='results/perf_latest.json',
                           column_config={'그주 이후(%)': st.column_config.NumberColumn(format='%+.1f', help='그 주 종가 → 현재가 수익률'),
                                          '연속(주)': st.column_config.NumberColumn(format='%d', help='이번 주까지 연속 52주 신고가 경신 주 수'),
                                          '8주중(회)': st.column_config.NumberColumn(format='%d', help='최근 8주 중 52주 신고가 경신 주 수')},
                           note='정렬: 시총 큰 순')
                _cand_register(_wrows, 'h52w')
                # 업종 묶음(숫자) — AI 없이도 보이는 사실
                _secs = pd.Series([_SEC52.get(x.get('sym'), '기타·미분류') for x, _ in _items]).value_counts()
                st.caption("업종 상위: " + " · ".join(f"**{k}** {v}" for k, v in _secs.head(6).items()))

                # ── ③ AI 공통점 요약 — 06시 자동 생성분은 누르지 않아도 보인다 ────────────
                _auto = ((load_json(Path('results/new_high_ai.json')) or {}).get('weeks') or {}).get(_sel)
                _ktxt = f"h52_ai_txt_{_sel}_{_mk52}"
                if _auto and not st.session_state.get(_ktxt):
                    with st.container(border=True):
                        st.markdown(f"**🤖 AI 공통점 요약 — {_sel} 주 ({_auto.get('n')}종, 한·미 전체)**")
                        st.markdown(_auto.get('text', ''))
                        st.caption(f"매일 06시 자동 생성({_auto.get('generated', '-')}) · Gemini · 표의 숫자·업종만 근거, "
                                   "원인 추정은 '~로 보인다'로 표시 · 매수 신호가 아니다.")
                _blab = (f"🔄 지금 다시 요약 ({_mk52} · {len(_items)}종)" if _auto
                         else f"🤖 AI 공통점 요약 — {_sel} 주 {len(_items)}종")
                if st.button(_blab, key=f"h52_ai_{_sel}_{_mk52}"):
                    import new_high_ai as _nha
                    _cgm = {k: _cg(k) for k in (x.get('sym') for x, _ in _items)}
                    with st.spinner("AI 가 공통점을 정리하는 중..."):
                        st.session_state[_ktxt] = _h52_ai(_sel, _mk52, _nha.payload(_items, _SEC52, _cgm))
                _txt = st.session_state.get(_ktxt)
                if _txt:
                    with st.container(border=True):
                        st.markdown(f"**🤖 AI 공통점 요약 — {_sel} 주 ({'한·미 전체' if _mk52 == '전체' else _mk52})**")
                        st.markdown(_txt)
                        st.caption("Gemini · 표의 숫자·업종만 근거로 쓰도록 제한 · 원인 추정은 '~로 보인다' · 매수 신호가 아니다.")
                if any(x.get('young') for x, _ in _items):
                    st.caption("🆕 = 상장 1년 미만 — 52주 이력이 없어 **상장 후 최고가**를 신고가로 본다(상장 8주 이후부터).")

    st.divider()
    # ── ④ 지금 고점 근처 종목 (필터) ─────────────────────────────
    st.markdown("##### 🎯 지금 52주 고점 근처 종목")
    _c1, _c2, _c3, _c4, _c5 = st.columns([1.3, 1.1, 1.2, 1.1, 1.1])
    _rng = _c1.slider("고점 대비 범위 (%)", -15.0, 0.0, -3.0, 0.5, key="h52_rng",
                      help="0 = 신고가, -3 = 고점에서 3% 이내", disabled=not _has_d)
    _only_new = _c2.checkbox("이번 주 신고가 경신만", value=False, key="h52_new", disabled=not _has_d)
    _persist = _c3.selectbox("신고가 지속", ["전체", "연속 2주+", "연속 3주+", "연속 4주+", "최근 8주 중 4회+"],
                             key="h52_persist", disabled=not _has_nh,
                             help="연속 n주+ = 이번 주까지 n주 연속으로 52주 신고가를 새로 쓴 종목. "
                                  "최근 8주 중 4회+ = 끊겼다 이어져도 자주 새로 쓰는 종목.")
    _min_cap = _c4.selectbox("최소 시총", ["전체", "1천억/1B$+", "1조/10B$+"], key="h52_cap")
    _sort52 = _c5.selectbox("정렬", ["고점 근접순", "연속 경신순", "시총순", "4주 상승률", "12주 상승률"], key="h52_sort")
    _rows52 = []
    for x in _s52:
        if _mk52 != "전체" and x.get('market') != _mk52:
            continue
        d = x.get('dist52')
        if _has_d:
            if d is None or d < _rng:
                continue
            if _only_new and not x.get('new_high'):
                continue
        elif not x.get('now_sig_52w'):
            continue
        if _persist.startswith("연속"):
            if (x.get('nh_streak') or 0) < int(_persist.split()[1][0]):
                continue
        elif _persist.startswith("최근 8주") and (x.get('nh_8w') or 0) < 4:
            continue
        cap = x.get('marcap') or 0
        kr = x.get('market') == 'KR'
        if _min_cap.startswith("1천억") and cap < (1e11 if kr else 1e9):
            continue
        if _min_cap.startswith("1조") and cap < (1e12 if kr else 1e10):
            continue
        _rows52.append({
            '종목': ('🆕 ' if x.get('young') else '') + str(x.get('name')), '코드': x.get('sym'), '시장': x.get('market'),
            '시총($B)': cap_usd_b(cap, x.get('market')), '_cap': cap_usd_b(cap, x.get('market')) or 0,
            '업종': _SEC52.get(x.get('sym'), '-'),
            '현재가': x.get('curr_price'), '52주고': x.get('hi52'),
            '고점대비': d, '경신': '🔺' if x.get('new_high') else '',
            '연속(주)': x.get('nh_streak'), '8주중(회)': x.get('nh_8w'),
            '4주(%)': x.get('ret_4w'), '12주(%)': x.get('ret_12w'),
            '함께 뜬 신호': ', '.join(l for l in (x.get('sigs_now') or []) if '52주' not in str(l)) or None,
        })
    _key = {"고점 근접순": lambda r: -(r['고점대비'] if r['고점대비'] is not None else -99),
            "연속 경신순": lambda r: (-(r['연속(주)'] or 0), -(r['8주중(회)'] or 0)),
            "시총순": lambda r: -r['_cap'], "4주 상승률": lambda r: -(r['4주(%)'] or -999),
            "12주 상승률": lambda r: -(r['12주(%)'] or -999)}[_sort52]
    _rows52.sort(key=_key)
    _n_kr = sum(1 for r in _rows52 if r['시장'] == 'KR'); _n_us = len(_rows52) - _n_kr
    _m1, _m2, _m3, _m4 = st.columns(4)
    _m1.metric("해당 종목", f"{len(_rows52)}개")
    _m2.metric("KR / US", f"{_n_kr} / {_n_us}")
    _m3.metric("이번 주 경신", f"{sum(1 for r in _rows52 if r['경신'])}개")
    _m4.metric("기준일", _p52.get('date', '-'))
    if not _has_d:
        st.info("고점 대비 거리·경신 여부는 다음 자동 갱신부터 채워집니다. 지금은 '신고가 -3% 이내' 신호만 보여줍니다.")
    if _rows52:
        _spec52 = (['연속(주)', '8주중(회)'] if _has_nh else []) + ['4주(%)', '12주(%)', '함께 뜬 신호']
        _std_table(pd.DataFrame(_rows52), _spec52,
                   src='FinanceDataReader·yfinance(주가) → perf_latest.json', path='results/perf_latest.json',
                   column_config={'연속(주)': st.column_config.NumberColumn(format='%d', help='이번 주까지 연속으로 52주 신고가를 새로 쓴 주 수'),
                                  '8주중(회)': st.column_config.NumberColumn(format='%d', help='최근 8주 중 52주 신고가를 새로 쓴 주 수'),
                                  '4주(%)': st.column_config.NumberColumn(format='%+.1f'),
                                  '12주(%)': st.column_config.NumberColumn(format='%+.1f'),
                                  '함께 뜬 신호': st.column_config.TextColumn(width=120)},
                   note=f"정렬: {_sort52} · 🆕 = 상장 1년 미만(신고가 = 상장 후 최고가)")
        _cand_register(_rows52, 'h52')
    else:
        st.write("조건에 맞는 종목이 없습니다.")
    st.caption("⚠️ 신고가는 **탐색 출발점**이지 매수 신호가 아닙니다. 상장폐지 종목까지 넣은 12.5년 검증에서 "
               "한국 52주 신고가 돌파 포트폴리오(KR-P1)는 KOSPI에 못 미쳤습니다(CAGR 4.3% vs 9.3%). "
               "실적이 받쳐주는지(오른쪽 매출·영업익 YoY 열)를 보고 🚀 주도주 → CANSLIM · 🔍 종목 분석으로 이어서 보세요.")


with t_value, guard('가치 발굴'):
    st.caption(data_stamp('results/value_kr.json'))
    st.caption("💎 공식 재무(DART·네이버)로 '싸고(저PER·저PBR) 돈 잘 버는(ROE·영업익 성장)' 한국 종목 — 가격이 아니라 가치 기준. "
               "PER 은 오른쪽 공통 열(지금 시총 ÷ 최근 4분기 순이익)로 거른다.")
    # 2026-10-15 — '전체'면 KR 표를 그대로 보여주되 US 가 비어 있다는 사실을 숨기지 않는다.
    #   US 를 채우려면 EDGAR 기반 PER·PBR·ROE 벌크 산출(value_export 의 US 판)이 필요하다 — 데이터 과제.
    if _GMKT != "KR":
        st.warning("🇺🇸 **US 가치 스크린 데이터가 아직 없습니다** — 아래 표는 KR 만입니다. "
                   "(US 개별 종목 밸류는 🔍 종목 분석에서 공식 멀티플로 확인)")
    if _GMKT != "US":
        _vj = load_json(Path('results/value_kr.json'))
        try:
            import consensus_snapshot as _cs
            _REVM = _cs.revision_map()          # sym → 애널 추정 리비전 방향(시계열 축적분)
        except Exception:
            _REVM = {}
        if not _vj or not _vj.get('stocks'):
            st.warning("가치 데이터 없음 → `python value_export.py` 실행 후 새로고침.")
        else:
            _vc1, _vc2, _vc3, _vc4, _vc5 = st.columns(5)
            _vper = _vc1.slider("PER ≤", 1, 30, 10, key="val_per")
            _vpbr = _vc2.slider("PBR ≤", 0.2, 5.0, 1.5, 0.1, key="val_pbr")
            _vroe = _vc3.slider("ROE ≥ %", 0, 30, 8, key="val_roe")
            _vgrw = _vc4.slider("영업익 성장 ≥ %", -50, 100, 0, key="val_grw",
                                help="'흑자전환'은 항상 통과")
            _vvec = _vc5.selectbox("궤적(벡터)", ["전체", "개선만(함정 제외)", "개선 가속만"], key="val_vec",
                                   help="위치가 싸도 펀더멘털이 악화 중이면 밸류 함정 — 벡터로 거른다")
            def _fmt_growth(v):
                # 숫자·'흑자전환' 문자열 혼재 컬럼 → 균일 문자열 (Arrow 직렬화 오류 방지)
                # 2026-10-15 — 숫자로 둔다(정렬·필터·색). 문자열 판정은 매출 성장에 의미가 없어 결측 처리.
                return float(v) if isinstance(v, (int, float)) else None
            _vrows = []
            for s in _vj['stocks']:
                # PER 은 공통 열과 같은 값으로 거른다(표에 보이는 PER = 필터 PER). 공통 값이 없을 때만 value_kr 값
                _cper = _CMB['PER(배)'].get(s['sym']) if not _CMB.empty and s['sym'] in _CMB.index else None
                _per = _cper if _cper == _cper and _cper is not None else s.get('per')
                _pbr, _roe = s.get('pbr'), s.get('roe')
                if not (_per and 0 < _per <= _vper and _pbr and 0 < _pbr <= _vpbr):
                    continue
                if _roe is None or _roe < _vroe:
                    continue
                _og9 = s.get('op_growth')
                _og_ok = (_og9 == '흑자전환') or (isinstance(_og9, (int, float)) and _og9 >= _vgrw)
                if not _og_ok:
                    continue
                _tr = s.get('traj') or {}
                _verd = _tr.get('verdict')
                if _vvec == "개선만(함정 제외)" and _verd == 'deteriorating':
                    continue
                if _vvec == "개선 가속만" and _verd != 'improving':
                    continue
                _vrows.append({'종목': s['name'], '코드': s['sym'], 'PER': _per,
                               'PBR(배)': _pbr, 'ROE(%)': _roe,
                               'ΔROE(%p)': _tr.get('d_roe'),
                               '판정': _tr.get('verdict_label') or None,
                               '컨센리비전': ({'up': '📈 상향', 'down': '📉 하향', 'flat': '➖ 유지'}
                                          .get((_REVM.get(s['sym']) or {}).get('dir')))})
            _vrows.sort(key=lambda r: r['PER'])     # 다른 축은 표 머리를 눌러 정렬 · 밸류 함정은 '궤적' 필터로
            _ntrap = sum(1 for s in _vj['stocks'] if (s.get('traj') or {}).get('verdict') == 'deteriorating')
            st.subheader(f"💎 저평가·우량 — {len(_vrows)}개 (PER≤{_vper} · PBR≤{_vpbr} · ROE≥{_vroe}% · 영업익≥{_vgrw}%)")
            if _vrows:
                _std_table(pd.DataFrame(_vrows[:50]), ['PBR(배)', 'ROE(%)', 'ΔROE(%p)', '판정', '컨센리비전'],
                           src='DART·네이버(재무)·KRX 상장목록 → value_kr.json', path='results/value_kr.json',
                           column_config={'PBR(배)': st.column_config.NumberColumn(format='%.2f'),
                                          'ΔROE(%p)': st.column_config.NumberColumn(format='%+.1f', help='ROE 전년 대비 변화(속도)'),
                                          '판정': st.column_config.TextColumn(help='위치(ROE·마진) + 속도(Δ) + 가속(Δ²) 벡터 판정 — 악화 = 밸류 함정 가능'),
                                          '컨센리비전': st.column_config.TextColumn(help='애널리스트 올해 EPS 추정의 4주 변화')},
                           note='정렬: PER 낮은 순 · 상위 50종')
                _cand_register(_vrows[:50], 'value')
                st.caption(f"커버리지 {_vj.get('coverage')}종목(DART 공식재무 × 실시간 시총). "
                           f"**위치(스칼라) + 속도(Δ, 전년대비) + 가속(Δ²)** = 벡터 판정. "
                           f"판정: 📈개선 가속 / ➖정체 / 📉악화(함정). ⚠️ 현재 전체 밸류 유니버스 중 **{_ntrap}종목이 '싸지만 악화 중'**(함정) — "
                           f"위치만 보면 안 보이던 것. **컨센리비전**=애널 추정(올해EPS) 4주 변화 "
                           f"({'축적 {}주차 — 방향 판독까지 몇 주 더'.format(len(_REVM)) if _REVM else '스냅샷 축적 시작 — 다음 주부터 방향'}).")
            else:
                st.info("조건 통과 종목 없음 — 기준을 완화해보세요.")



# ════════════════════════════════════════════════════════════════════
with tab3, guard('CANSLIM'):
    # 2026-10-15 — 탭 자체 KR/US 라디오 폐지 → 상단 공통 시장 필터. '전체'면 두 시장을 한 표에.
    #   RS(L) 은 **각 시장 안의 백분위**라서 시장을 섞어도 '그 시장에서 상위 몇 %'로 읽으면 된다.
    _CS_SETS = [(m, p) for m, p in (('KR', CANSLIM_JSON), ('US', Path('results/canslim_us_latest.json')))
                if _GMKT in ("전체", m)]
    _CS = {m: load_json(p) for m, p in _CS_SETS}
    _TRAJM = _traj_map()                             # 궤적(KR만) — US는 '-'
    st.header("🏆 CANSLIM 스크리너" + ("" if _GMKT == "전체" else f" ({'한국' if _GMKT == 'KR' else '미국'})"))
    for _m, _p in _CS_SETS:
        st.caption(f"{_m} · " + data_stamp(str(_p)))
    if 'US' in _CS:
        st.caption("US: C·A=SEC EDGAR 공식 재무 · **영업이익 기준**(오닐의 '일회성 제외 EPS' 근사 — 부채 소멸 손실·평가손익·세금 효과가 "
                   "순이익을 왜곡하던 것, 예: LITE -26,876%) · 영업이익 계정이 없는 금융·리츠는 순이익 · "
                   "'일회성' 열 = 순이익 성장과 50%p 넘게 갈린 글자 · I(기관 수급)는 무료 일간 소스가 없어 공란(13F는 분기 지연)")

    _missing = [m for m, d in _CS.items() if d is None]
    for _m in _missing:
        st.error(f"{_m} 데이터 없음 → `python {'canslim_run.py' if _m == 'KR' else 'canslim_us_run.py'}` 실행 후 새로고침")
    _CS = {m: d for m, d in _CS.items() if d is not None}
    canslim = {'stocks': [dict(x, _mkt=m) for m, d in _CS.items() for x in d.get('stocks', [])]} if _CS else None
    if canslim is not None:
        _mc = st.columns(max(len(_CS), 1) * 2)
        for _i, (_m, _d) in enumerate(_CS.items()):
            _mc[_i * 2].metric(f"{_m} 기준일 · 시장방향(M)", f"{_d['date']} · {_d['market_dir']}")
            _mc[_i * 2 + 1].metric(f"{_m} 후보 (N+RS 사전필터)", f"{len(_d['stocks'])}개")
            if not _d['market_ok']:
                st.warning(f"⚠️ {'KOSPI' if _m == 'KR' else 'S&P500'} 하락추세 — {_m} 신규매수 주의")
        _MOK = {m: bool(d['market_ok']) for m, d in _CS.items()}

    if canslim is not None:
        with st.expander("⚙️ CANSLIM 기준 조정 (슬라이더로 실시간)", expanded=False):
            th_N    = st.slider("N  52주 신고가 허용거리 (%)", -30, 0, -5, key="th_N",
                                help="예: -5 = 신고가 대비 5% 이내")
            th_S    = st.slider("S  거래량 배수 (60일 평균 대비)", 1.0, 4.0, 1.5, 0.1, key="th_S")
            th_Sb   = st.slider("S  캔들 몸통 비율 (%)", 10, 70, 40, key="th_Sb")
            th_Sbull = st.checkbox("S  양봉 필수", value=True, key="th_Sbull")
            th_L    = st.slider("L  상대강도 RS 하한 (백분위)", 40, 95, 70, key="th_L",
                                help="표의 RS 열과 같은 값 — 3개월 40%·6·9·12개월 각 20% 가중 수익률의 그 시장 안 백분위")
            st.divider()
            th_C    = st.slider("C  분기 순이익 성장 (%)", 0, 150, 20, key="th_C",
                                help="전년 동기 대비 성장 — KR 순이익 · US 영업이익(일회성 제외 근사)")
            th_A1   = st.slider("A  연간 성장 — 최근년 (%)", -50, 150, 20, key="th_A1")
            th_A2   = st.slider("A  연간 성장 — 전년 (%)", -50, 150, 20, key="th_A2")
            th_I    = st.slider("I  기관+외인 순매수 하한 (억원·20일)", -2000, 10000, 0, 100, key="th_I",
                                help="최근 20거래일 기관+외국인 합산 순매수 (양수=매집, pykrx)")
            st.divider()
            st.caption("**필수 통과 항목 설정**")
            req_S = st.checkbox("S 통과 필수", value=False, key="req_S")
            req_C = st.checkbox("C 통과 필수", value=False, key="req_C")
            req_A = st.checkbox("A 통과 필수", value=False, key="req_A")
            # 2026-10-14 — I(수급) 소스 pykrx 가 KRX 로그인을 요구하면서 KR·US 전 종목이 공란이다.
            #   공란인데 7점 만점으로 세면 '최고 6점'이 '7점 중 6점'처럼 보이고, I 필수를 켜면
            #   결과가 0개가 된다. 데이터가 없으면 I 를 점수와 필터에서 뺀다(있는 척하지 않는다).
            _i_live = any(_s.get('i_inst_pct') is not None for _s in canslim.get('stocks', []))
            req_I = st.checkbox("I 통과 필수", value=False, key="req_I", disabled=not _i_live,
                                help=None if _i_live else "I(기관·외인 수급) 데이터 소스가 중단돼 지금은 쓸 수 없습니다")
            _SC3 = '점수/7' if _i_live else '점수/6'
            if not _i_live:
                req_I = False
                st.caption("⚠️ I(수급) 데이터 없음 — 점수는 6점 만점")

        rows3 = []
        for s in canslim['stocks']:
            _mk3   = s['_mkt']
            n_dist = s.get('n_dist_pct')
            vol    = s.get('s_vol_ratio')
            body   = s.get('s_body_pct')
            bull   = s.get('s_bull', False)
            # L 은 표의 공통 RS(백테스트와 같은 가중식)로 판정한다 — 전에는 12개월 백분위라 표마다 RS 가 달랐다
            _crs = _CMB['RS'].get(s['sym']) if not _CMB.empty and s['sym'] in _CMB.index else None
            rs     = _crs if _crs is not None and _crs == _crs else (s.get('rs_pct') or 0)
            c_g    = s.get('c_growth_pct')
            a_y1   = s.get('a_growth_y1')
            a_y2   = s.get('a_growth_y2')
            i_inst = s.get('i_inst_pct')

            def _ge(v, th):        # 숫자 비교 ('흑자전환' 문자열=통과)
                return (v == '흑자전환') or (isinstance(v, (int, float)) and v >= th)
            n_ok = n_dist is not None and n_dist >= th_N
            s_ok = (vol is not None and vol >= th_S and
                    body is not None and body >= th_Sb and
                    (not th_Sbull or bull))
            l_ok = rs >= th_L
            c_ok = _ge(c_g, th_C)
            a_ok = _ge(a_y1, th_A1) and _ge(a_y2, th_A2)
            i_ok = i_inst is not None and i_inst >= th_I

            if not n_ok or not l_ok: continue
            if req_S and not s_ok:   continue
            if req_C and not c_ok:   continue
            if req_A and not a_ok:   continue
            if req_I and not i_ok:   continue

            m_ok = _MOK.get(_mk3, True)
            score = sum([m_ok, n_ok, l_ok, s_ok, c_ok, a_ok] + ([i_ok] if _i_live else []))

            # 2026-10-15 격자 재설계 — (구) 셀 하나에 '✅ +23%' 처럼 판정과 값을 붙여 문자열로 냈다.
            #   그러면 숫자로 정렬·필터·색이 안 된다. 값은 숫자 열로, 판정은 '통과' 열 하나로 분리한다.
            def _n(v):
                return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
            _conv = [f"{lab} {v}" for lab, v in (('C', c_g), ('A최근', a_y1), ('A전년', a_y2))
                     if isinstance(v, str)]                       # 흑자전환/적자전환 은 숫자가 아니라 사건
            _pass = [l for l, ok in (('M', m_ok), ('C', c_ok), ('A', a_ok), ('N', n_ok),
                                     ('S', s_ok), ('L', l_ok), ('I', i_ok and _i_live)) if ok]
            rows3.append({
                '종목': s['name'], '코드': s['sym'], '시장': _mk3,
                _SC3: score,
                '통과': ' '.join(_pass) + (f" · {' · '.join(_conv)}" if _conv else ''),
                'C 분기(%)': _n(c_g),
                'A 최근년(%)': _n(a_y1),
                'S 거래량(배)': _n(vol),
                '_rs': rs, '_score': score,
                '_ok': {'C': c_ok, 'A': a_ok, 'S': s_ok, 'I': i_ok},
            })

        df3 = pd.DataFrame(rows3) if rows3 else pd.DataFrame()

        if df3.empty:
            st.warning("조건을 충족하는 종목이 없습니다. 슬라이더를 완화해보세요.")
        else:
            df3 = df3.sort_values(['_score', '_rs'], ascending=False).reset_index(drop=True)
            _nk = int((df3['시장'] == 'KR').sum()); _nu = len(df3) - _nk
            st.subheader(f"총 {len(df3)}종 (KR {_nk} · US {_nu}) · 정렬: 점수 → RS")
            _std_table(df3, [_SC3, '통과', 'C 분기(%)', 'A 최근년(%)', 'S 거래량(배)'],
                       src='FinanceDataReader·yfinance(주가)·DART·SEC EDGAR(재무) → canslim_latest.json',
                       path='results/canslim_latest.json',
                       column_config={
                           _SC3: st.column_config.NumberColumn(format='%d', help='M·C·A·N·S·L(·I) 중 현재 슬라이더 기준 통과 수'),
                           '통과': st.column_config.TextColumn(help='통과한 글자 — M 시장 · C 분기 · A 연간 · N 신고가 · S 거래량 · L 상대강도 · I 수급. 뒤의 \'C 흑자전환\' 등은 숫자 대신 사건'),
                           'C 분기(%)': st.column_config.NumberColumn(format='%+.0f', help='최근 분기 이익 YoY — KR 순이익 · US 영업이익(일회성 제외 근사)'),
                           'A 최근년(%)': st.column_config.NumberColumn(format='%+.0f', help='최근 연간 이익 YoY'),
                           'S 거래량(배)': st.column_config.NumberColumn(format='%.1f', help='거래량 ÷ 60일 평균')},
                       note="N(신고가 근접) = 오른쪽 52주고점대비 · L(상대강도) = RS 열")
            _cand_register(df3, 'canslim')
            with st.expander("📖 CANSLIM 각 항목 기준·설명", expanded=False):
                _tsrc('CANSLIM 기준(William O\'Neil) · 본 대시보드 설정', asof='고정 기준표')
                st.dataframe(pd.DataFrame([
                    {'글자': 'C', '이름': '분기 실적', '컬럼': 'C 분기(%)',
                     '기준': '최근 분기 순이익 YoY ≥ +20% (흑자전환 포함)', '출처': 'DART 공식(폴백 네이버)'},
                    {'글자': 'A', '이름': '연간 실적', '컬럼': 'A 최근년(%) (전년은 판정에만)',
                     '기준': '연간 순이익 YoY ≥ +20% × 2개년 (최근년/전년)', '출처': 'DART 공식(폴백 네이버)'},
                    {'글자': 'N', '이름': '신고가 근접', '컬럼': '52주고점대비(%)',
                     '기준': '52주 신고가 대비 거리 — 0%에 가까울수록(신고가 부근) 강함', '출처': '주가'},
                    {'글자': 'S', '이름': '수급(거래량)', '컬럼': 'S 거래량(배)',
                     '기준': '거래량이 평균 대비 몇 배 터졌나 (≥1.5x + 양봉 몸통)', '출처': '주가·거래량'},
                    {'글자': 'L', '이름': '주도주(상대강도)', '컬럼': 'RS',
                     '기준': 'RS = 3개월 40%·6·9·12개월 각 20% 가중 수익률의 시장 내 백분위(0~99). 90 = 상위 10%', '출처': '주가(상대비교)'},
                    {'글자': 'I', '이름': '기관 수급', '컬럼': '(소스 중단 — 판정 제외)',
                     '기준': '최근 20거래일 기관+외국인 합산 순매수(억원) > 0 = 매집', '출처': 'KRX(pykrx)'},
                    {'글자': 'M', '이름': '시장 방향', '컬럼': '상단 배지',
                     '기준': '지수가 상승추세인가 — 하락장에선 아무리 좋아도 무리하지 않음', '출처': '지수'},
                ]), use_container_width=True, hide_index=True, row_height=25, height=_dfh(7))
                st.caption("오닐 CANSLIM: '이익이 급증(C·A)하는 신고가 부근(N) 주도주(L)를 "
                           "거래량(S)·기관(I)이 받쳐주고 시장(M)이 우호적일 때 산다.'")

            st.divider()
            with st.expander("📊 항목별 통과율 (현재 슬라이더 기준)", expanded=False):
                total3 = len(rows3)
                pr_counts = {
                    'C 분기실적': sum(1 for r in rows3 if r['_ok']['C']),
                    'A 연간실적': sum(1 for r in rows3 if r['_ok']['A']),
                    'S 거래량':   sum(1 for r in rows3 if r['_ok']['S']),
                    'I 기관수급': sum(1 for r in rows3 if r['_ok']['I']),
                }
                pr_df = pd.DataFrame({
                    '항목': list(pr_counts.keys()),
                    '통과수': list(pr_counts.values()),
                    '통과율(%)': [round(v/total3*100, 1) for v in pr_counts.values()],
                })
                _tsrc('FinanceDataReader·yfinance(주가)·DART·SEC EDGAR(재무) → canslim_latest.json', path='results/canslim_latest.json')
                st.dataframe(pr_df, use_container_width=False, hide_index=True,
                             row_height=25, height=_dfh(len(pr_df)))


# ════════════════════════════════════════════════════════════════════
# 탭4: 글로벌 매크로
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, max_entries=48)
def _fetch_fred_history_cached(series_id: str, limit: int):
    """실패 시 예외 → 빈 DataFrame이 캐시에 박제되지 않음."""
    data = _fetch_fred_cached(series_id, limit)      # 재시도·성공만 캐싱 공유
    df = pd.DataFrame(data, columns=['date', series_id])
    df['date'] = pd.to_datetime(df['date'])
    return df.set_index('date')


def fetch_fred_history(series_id: str, limit: int = 60):
    try:
        return _fetch_fred_history_cached(series_id, limit)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, max_entries=48)
def _fetch_index_history_cached(symbol: str, days: int):
    import FinanceDataReader as fdr
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    df = fdr.DataReader(symbol, start)[['Close']].rename(columns={'Close': symbol})
    if df is None or df.empty:
        raise RuntimeError('empty')
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def fetch_index_history(symbol: str, days: int = 365):
    if _recently_failed(f'idx:{symbol}'):
        return pd.DataFrame()
    try:
        return _fetch_index_history_cached(symbol, days)
    except Exception:
        _mark_failed(f'idx:{symbol}')
        return pd.DataFrame()

@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _world_index_closes():
    """세계 지수 종가 — FDR 먼저, 안 되면 yfinance. 실패한 지수는 빈칸(None)으로 남긴다."""
    import index_strength as _is
    # 3년 — 52주 창(252일) 위에서 '마지막 신고가'를 1년 넘게 거슬러 찾으려면 이만큼 필요하다
    # 2026-10-21 — 10년: 비교 차트 기간 선택 + 국가 시총의 연말 기준점(영국 2022 등)을 찾으려면 길어야 한다
    start = (datetime.now() - timedelta(days=3700)).strftime('%Y-%m-%d')
    out, src = {}, {}
    for fsym, ysym, name, region in _is.INDICES:
        s = None
        if fsym:
            try:
                import FinanceDataReader as fdr
                d = fdr.DataReader(fsym, start)
                if d is not None and len(d) > 30:
                    s = d['Close']; src[name] = 'FDR'
            except Exception:
                s = None
        if s is None:
            try:
                d = yf.Ticker(ysym).history(start=start, auto_adjust=False)
                if d is not None and len(d) > 30:
                    s = d['Close']; src[name] = 'Yahoo'
            except Exception:
                s = None
        if s is not None:
            s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
        out[(name, region)] = s
    return out, src


def _world_strength_panel():
    """🌍 세계 증시 강도판 — 기간별 수익률 히트맵 + 52주 신고가 갱신 (2026-10-19 사용자 요청)."""
    import index_strength as _is
    st.subheader("🌍 세계 증시 강도판 — 지금 어디가 제일 강한가")
    with st.spinner("세계 지수 로딩..."):
        closes, src = _world_index_closes()
    df = _is.table(closes)
    miss = [n for (n, _), v in closes.items() if v is None]
    if df.empty:
        st.info("지수 데이터를 받지 못했습니다(FDR·Yahoo 모두 실패).")
        return
    # 2026-10-20 — 히트맵(plotly)을 다른 탭과 같은 표(table_ui)로 바꿨다. 색 규칙도 표 공통 규칙을 따른다.
    import macro_flow as _mfw
    _wb = load_json(Path('data/world_mcap.json')) or {}
    _fx = _mo_fx_closes()
    _act = {}
    try:   # 한국 = KRX 상장목록 시총 합(거래소 실측) ÷ 원/달러
        _kl = pd.read_csv('data/krx_listing_last.csv', usecols=['Marcap'])
        _kfx = _mfw.usd_per_local(_fx.get('KRW'), False)
        if len(_kl) > 2000 and len(_kfx):
            _act['KOR'] = (float(_kl['Marcap'].sum()) * float(_kfx.iloc[-1]),
                           (open('data/krx_listing_last.csv.asof').read().strip()
                            if os.path.exists('data/krx_listing_last.csv.asof') else '날짜 미상'))
    except Exception:
        pass
    _cm = _mfw.country_mcap(_wb, {n: v for (n, _), v in closes.items()}, fx=_fx, actual=_act)
    per = [k for k, _ in _is.PERIODS]
    t = pd.DataFrame({'지수': df['지수'], '지역': df['지역'],
                      '국가 시총($T)': df['지수'].map(lambda n: _cm[n][0] if n in _cm else np.nan),
                      '실측/추정': df['지수'].map(lambda n: ('실측' if not _cm[n][2] else f"추정({_cm[n][1][:4]})") if n in _cm else '-')})
    for k in per:
        t[f'{k}(%)'] = df[k].astype(float)
    t['고점대비(%)'] = df['고점대비'].astype(float)
    t['신고가 후(일)'] = df['신고가후']
    t['3개월 신고가(회)'] = df['신고가3m']
    t['마지막 신고가'] = df['신고가일'].map(lambda d: d.strftime('%Y-%m-%d') if d is not None and not pd.isna(d) else '-')
    _asof = df['기준일'].max()
    st.dataframe(t, filters=False,
                 src='FinanceDataReader·Yahoo(지수 종가: ' + ', '.join(sorted(set(src.values()))) + ') · 국가 시총: 세계은행 CM.MKT.LCAP.CD · TWSE 연보 · KRX 상장목록 · Yahoo 환율',
                 asof=_asof.strftime('%Y-%m-%d') if hasattr(_asof, 'strftime') else None,
                 column_config={'국가 시총($T)': st.column_config.NumberColumn('국가 시총($T)', format='%.2f'),
                                **{f'{k}(%)': st.column_config.NumberColumn(f'{k}(%)', format='%+.1f') for k in per},
                                '고점대비(%)': st.column_config.NumberColumn('고점대비(%)', format='%+.1f'),
                                '신고가 후(일)': st.column_config.NumberColumn('신고가 후(일)', format='%d'),
                                '3개월 신고가(회)': st.column_config.NumberColumn('3개월 신고가(회)', format='%d')})
    _how = sorted({v[1] for v in _cm.values()})
    st.caption("**국가 시총** — 한국은 KRX 상장목록 시총 합(거래소 실측, 매일)을 원/달러로 나눈 값. "
               "나머지는 **추정**: 연말 공식 값(세계은행, 대만은 TWSE 연보) × 그 뒤 대표 지수 변동 × 그 뒤 환율 변동. "
               "지수가 시장 전체를 다 담지 못하고 신규 상장·상장폐지를 반영하지 못해 수 % 오차가 날 수 있다. "
               "같은 나라 지수는 같은 값(미국 4개는 S&P500, 한국 2개는 KRX 합). "
               "괄호 = 기준 연말. 유로스톡스50 '-' = 유로존 시총 공식 값이 2018년(세계은행)·2022년(ECB)에서 끊겨, 지수 하나로 8년을 끌어오면 오차가 너무 커서 비움. "
               "기준: " + (' / '.join(_how) if _how else '자료 없음') + ".")
    st.caption("순서 = **강도 순위**(고점대비 · 3개월 · 6개월 수익률의 순위 평균). "
               "**3개월 신고가(회)** = 최근 63거래일 중 52주 신고가를 새로 쓴 날 수 — 많을수록 추세가 살아 있다. "
               "**신고가 후(일)** 가 '-' 면 최근 2년 안에 52주 신고가가 없었다는 뜻. "
               "⚠️ 각국 통화 기준(환율 미반영) · 종가 기준 신고가(장중 아님)."
               + (f" ⚠️ 못 받은 지수: {', '.join(miss)}." if miss else ""))
    _index_compare_chart(closes)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _mo_fx_closes_cached():
    import macro_flow as _mfx
    syms = {c: v[0] for c, v in _mfx.FX_SYMBOL.items()}
    d = yf.download(list(syms.values()), period='10y', auto_adjust=True, progress=False, threads=True)
    c = d['Close'] if isinstance(d.columns, pd.MultiIndex) else d
    out = {ccy: c[sym].dropna() for ccy, sym in syms.items() if sym in c.columns and c[sym].notna().sum() > 100}
    if len(out) < 4:
        raise RuntimeError('환율 대부분 실패')
    return out


def _mo_fx_closes():
    """{통화: Yahoo 환율 원시 시계열}. 실패하면 빈 dict(국가 시총은 환율 보정이 필요한 나라를 '-'로 둔다)."""
    if _recently_failed('mo_fx'):
        return {}
    try:
        return _mo_fx_closes_cached()
    except Exception:
        _mark_failed('mo_fx')
        return {}


def _index_compare_chart(closes):
    """지수·자산 비교 — 시작일 = 100 으로 맞춰 같은 출발선에서 본다 (2026-10-21 사용자 요청)."""
    import macro_flow as _mfc
    st.markdown("##### 📈 비교 차트 — 시작일을 100으로")
    pool = {n: v for (n, _), v in closes.items() if v is not None and len(v) > 30}
    _ac = _mo_asset_closes()
    for nm, sym, _ in _mfc.ASSETS:
        if sym in ('SPY', '^KS11'):          # 지수와 중복
            continue
        if _ac.get(sym) is not None and len(_ac[sym]) > 30:
            pool[nm] = _ac[sym]
    if not pool:
        st.info("비교할 시세를 받지 못했습니다.")
        return
    pool = {k: _mfc._clean(v) for k, v in pool.items()}
    first = min(v.index[0] for v in pool.values()).date()
    today = max(v.index[-1] for v in pool.values()).date()
    c0, c1, c2 = st.columns([2.2, 1.2, 2.6])
    preset = c0.segmented_control('기간', ['3개월', '6개월', '1년', '3년', '5년', '직접'], default='1년', key='cmp_p')
    cur = c1.segmented_control('통화', ['현지', '달러', '원화'], default='현지', key='cmp_c',
                               help='달러·원화 = 각 지수를 그 통화로 환산(Yahoo 환율). 원화 기준이 우리 계좌에 실제로 찍히는 수익이다')
    _d = {'3개월': 91, '6개월': 182, '1년': 365, '3년': 1095, '5년': 1826}
    if preset == '직접':
        d1, d2 = c2.columns(2)
        start = d1.date_input('시작일', value=today - timedelta(days=365), min_value=first, max_value=today, key='cmp_s')
        end = d2.date_input('종료일', value=today, min_value=first, max_value=today, key='cmp_e')
    else:
        start, end = max(first, today - timedelta(days=_d.get(preset or '1년', 365))), today
    default = [n for n in ('S&P500', '나스닥', '코스피', '닛케이225', '대만 가권', '비트코인') if n in pool]
    sel = st.multiselect('비교 대상', list(pool), default=default, key='cmp_sel')
    if not sel or start >= end:
        st.caption("대상을 고르고 시작일이 종료일보다 앞서게 해 주세요.")
        return
    fx = _mo_fx_closes()
    ccy_of = {n: v[2] for n, v in _mfc.INDEX_COUNTRY.items()}
    krw = _mfc.usd_per_local(fx.get('KRW'), False) if fx.get('KRW') is not None else pd.Series(dtype=float)
    fig = go.Figure(); rows = []; miss = []
    for n in sel:
        sr = pool[n]
        loc = ccy_of.get(n, 'USD')          # 자산(금·BTC 등)은 달러 표시
        if cur != '현지' and loc != 'USD':
            sym, direct = _mfc.FX_SYMBOL.get(loc, (None, True))
            f = _mfc.usd_per_local(fx.get(loc), direct) if fx.get(loc) is not None else pd.Series(dtype=float)
            if not len(f):
                miss.append(n); continue
            sr = (sr * f.reindex(sr.index.union(f.index)).ffill().reindex(sr.index)).dropna()
        if cur == '원화':
            if not len(krw):
                miss.append(n); continue
            sr = (sr / krw.reindex(sr.index.union(krw.index)).ffill().reindex(sr.index)).dropna()
        w = sr[(sr.index >= pd.Timestamp(start)) & (sr.index <= pd.Timestamp(end))]
        if len(w) < 5:
            miss.append(n); continue
        y = w / float(w.iloc[0]) * 100
        fig.add_trace(go.Scatter(x=y.index, y=y.values, mode='lines', name=n, line=dict(width=2),
                                 hovertemplate=f'{n} %{{y:.1f}}<extra></extra>'))
        r = w.pct_change().dropna()
        rows.append({'대상': n, '기간 수익률(%)': float(y.iloc[-1] - 100),
                     '기간 최대낙폭(%)': float((w / w.cummax() - 1).min() * 100),
                     '연환산 변동성(%)': float(r.std() * np.sqrt(252) * 100) if len(r) > 5 else np.nan})
    fig.add_hline(y=100, line_color='rgba(120,124,134,.55)', line_width=1)
    fig.update_layout(height=380, margin=dict(l=8, r=8, t=10, b=8), hovermode='x unified',
                      legend=dict(orientation='h', y=1.08, x=0), yaxis_title=f'시작일 {start} = 100')
    st.plotly_chart(fig, use_container_width=True)
    if rows:
        tb = pd.DataFrame(rows).sort_values('기간 수익률(%)', ascending=False)
        st.dataframe(tb, filters=False,
                     src=f"FinanceDataReader·Yahoo(종가) · {'현지 통화' if cur == '현지' else cur + ' 환산(Yahoo 환율)'} · {start} ~ {end}",
                     asof=str(end),
                     column_config={c: st.column_config.NumberColumn(c, format='%+.1f' if '수익률' in c or '낙폭' in c else '%.1f')
                                    for c in tb.columns if c != '대상'})
    if miss:
        st.caption(f"⚠️ 기간 안 시세나 환율이 부족해 뺀 대상: {', '.join(miss)}")


def _fred_latest(series_id: str):
    d = fetch_fred(series_id, 2)
    return d[-1][1] if d else None

def _fred_yoy(series_id: str):
    d = fetch_fred(series_id, 14)
    if len(d) >= 13 and d[-13][1] > 0:
        return round((d[-1][1] / d[-13][1] - 1) * 100, 2)
    return None

def _plotly_line(dfs, labels, colors, title, yformat='{:,.2f}', height=260):
    fig = go.Figure()
    for df, label, color in zip(dfs, labels, colors):
        if df.empty: continue
        col = df.columns[0]
        fig.add_trace(go.Scatter(
            x=df.index, y=df[col], mode='lines', name=label,
            line=dict(color=color, width=1.8),
            hovertemplate=f'{label}: %{{y:{yformat}}}<extra></extra>',
        ))
    fig.update_layout(
        title=dict(text=title, font=dict(size=13), x=0, xanchor='left'),
        height=height + 34, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#4B5563', size=10),
        margin=dict(l=0, r=0, t=34, b=34),
        legend=dict(orientation='h', y=-0.22, x=0, yanchor='top'),   # 범례를 하단으로 → 제목과 겹침 방지
        hovermode='x unified',
    )
    fig.update_xaxes(gridcolor='rgba(128,128,128,0.2)', showgrid=True)
    fig.update_yaxes(gridcolor='rgba(128,128,128,0.2)', showgrid=True)
    return fig

# ════════════════════════════════════════════════════════════════════
# 사이클 국면 엔진 — 우라가미 4계절 · 코스톨라니 달걀 · 하워드 막스 시계추
#
#   세 렌즈는 같은 사이클을 다른 축에서 본다. 하나로 합치면 정보가 죽으므로 따로 낸다.
#     · 우라가미: (금리 방향 × 실적 방향 × 주가 추세) → 장세 4계절
#     · 코스톨라니: 금리의 사이클 위치 → 지금 무슨 자산을 들 때인가
#     · 막스: 위험선호의 진자 위치 → 남들이 얼마나 겁먹었나(역발상 눈금)
#   판정은 전부 공개 임계값이다. 맞추려는 게 아니라 '어디쯤인지'와 '무엇이 바뀌면
#   국면이 넘어가는지'를 눈에 보이게 하는 게 목적이다.
# ════════════════════════════════════════════════════════════════════
# 2026-10-21 — 판정 계산(_pctile·_yoy_series·macro_inputs·200일선·SEASONS·EGG·macro_regime)은
#   verdict.py 로 옮겼다. 화면·CANSLIM M·시황 리포트·주간 포트폴리오·executor 가 같은 함수를 쓴다.
import verdict as _V
from verdict import _pctile, _yoy_series, SEASONS, EGG, macro_regime


@st.cache_data(ttl=3600, show_spinner=False)
def macro_inputs():
    return _V.macro_inputs(fetch_fred)


def macro_price_state():
    """S&P500(SPY) 200일선 — verdict.core_switch. 옛 키(spx·ma200·above_ma·pos52·mom12) 그대로."""
    df = fetch_index_history('SPY', 400)
    return {} if df.empty else _V.as_price_state(_V.core_switch(df.iloc[:, 0]))


def macro_triggers(d, px):
    """국면을 넘기는 관측 가능한 방아쇠. (방향, 지표, 현재, 임계, 넘었나, 뜻)"""
    T = []
    def add(side, name, cur, thr, hit, why, fmt='{:+,.2f}'):
        T.append(dict(side=side, name=name, val=cur,
                      cur=('-' if cur is None else fmt.format(cur)),
                      thr=thr, hit=(None if cur is None else hit), why=why))
    hy, sp = d.get('hy'), d.get('spread')
    add('악화', 'HY 하이일드 스프레드', hy, '≥ 5.00%', (hy is not None and hy >= 5.0),
        '신용경색 신호. 5%를 넘으면 이익 사이클이 꺾이며 ❄️역실적장세로 넘어가는 경우가 많습니다.', '{:.2f}%')
    add('악화', '10Y-2Y 금리차', sp, '< 0.00%', (sp is not None and sp < 0),
        '재역전은 경기 침체 선행. 역전 해소 직후 침체가 오는 패턴도 있어 방향을 같이 봅니다.')
    add('악화', '실업률 상승폭(12개월 최저 대비)', d.get('sahm'), '≥ +0.50%p',
        (d.get('sahm') is not None and d['sahm'] >= 0.5),
        '삼의 법칙. 발동하면 성장을 "악화"로 강제 전환한다 — 실적장세 종료 신호.', '{:+,.2f}')
    add('악화', '산업생산 YoY', d.get('ip_yoy'), '< 0.0%',
        (d.get('ip_yoy') is not None and d['ip_yoy'] < 0),
        '이익 사이클의 대용치. 마이너스로 내려가면 ☀️실적장세가 유지되지 않는다.', '{:+.1f}%')
    add('악화', 'CPI YoY (재인플레)', d.get('cpi_yoy'), '≥ 3.5%',
        (d.get('cpi_yoy') is not None and d['cpi_yoy'] >= 3.5),
        '물가가 다시 오르면 인하 기대가 되감기며 🍂역금융장세로 밀린다.', '{:+.1f}%')
    add('개선', 'Fed 6개월 변화', d.get('fed_6m'), '≤ -0.50%p',
        (d.get('fed_6m') is not None and d['fed_6m'] <= -0.5),
        '인하 사이클 확인. 🌱금융장세의 방아쇠 — 실적보다 금리가 주가를 정하기 시작한다.')
    add('개선', 'M2 YoY (유동성)', d.get('m2_yoy'), '≥ +5.0%',
        (d.get('m2_yoy') is not None and d['m2_yoy'] >= 5),
        '통화량 팽창. 유동성 장세의 연료.', '{:+.1f}%')
    add('개선', '산업생산 YoY', d.get('ip_yoy'), '≥ +2.0%',
        (d.get('ip_yoy') is not None and d['ip_yoy'] >= 2),
        '이익 사이클 회복. ☀️실적장세 진입 조건 — 주도주 전략이 가장 잘 먹히는 구간.', '{:+.1f}%')
    _sm = None if not px else (px.get('spx', 0) / px.get('ma200', 1) - 1) * 100
    add('개선', 'S&P500 200일선 이격', _sm, '> 0.0%', (_sm is not None and _sm > 0),
        '추세 확인선. 아래면 어떤 매수 신호도 한 단계 낮춰 본다.', '{:+.1f}%')
    return T


# ════════════════════════════════════════════════════════════════════
# 매크로 v2 (2026-10-20) — 두 축: 돈의 흐름 · 경제  →  사이클 지도  →  욕심 조절 원칙
#   설계: Figma 'STOCK DASHBOARD — 매크로 탭 v2' · 계산: macro_flow.py · 검증: research/macro_regime_*
#   비중을 바꾸는 확정 규칙은 200일선 하나다. 나머지는 '참고 경고'로만 보이고 비중에 쓰지 않는다.
# ════════════════════════════════════════════════════════════════════
import macro_flow as _mf

@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _mo_asset_closes_cached():
    syms = [s for _, s, _ in _mf.ASSETS] + [_mf.FX_KRW]
    d = yf.download(syms, period='10y', auto_adjust=True, progress=False, threads=True)   # 비교 차트 기간 선택용 10년
    c = d['Close'] if isinstance(d.columns, pd.MultiIndex) else d
    out = {s: c[s].dropna() for s in syms if s in c.columns}
    if sum(len(v) > 30 for v in out.values()) < 3:
        raise RuntimeError('자산 시세 대부분 실패')
    return out


def _mo_asset_closes():
    if _recently_failed('mo_assets'):
        return {}
    try:
        return _mo_asset_closes_cached()
    except Exception:
        _mark_failed('mo_assets')
        return {}


_MO_FRED = _V.MO_FRED      # 2026-10-21 verdict.py 로 이관 — CI 의 macro.json 과 같은 목록


def _mo_series():
    return {k: _mf.to_series(fetch_fred(k, n)) for k, n in _MO_FRED.items()}


def _mo_last(s, fmt='{:,.2f}'):
    return fmt.format(float(s.iloc[-1])) if len(s) else '-'


def _macro_v2_top(_PX, _RG):
    """① 이번 주 판정 · ② 축 1 돈의 흐름 · ③ 축 2 경제. 반환: 욕심 판정에 쓴 값들."""
    with st.spinner("두 축 지표 수집 중..."):
        S = _mo_series()
        closes = _mo_asset_closes()
    # 2026-10-21 — 두 축·욕심 경고 계산은 verdict.axes 하나(CI 의 results/macro.json 과 같은 함수)
    core_on = (bool(_PX.get('above_ma')) if _PX else None)
    gap200 = ((_PX['spx'] / _PX['ma200'] - 1) * 100) if _PX else None
    _A = _V.axes(S, closes, core_on, _RG.get('phase'))
    at, flow, rows, ew, esub = _A['at'], _A['flow'], _A['rows'], _A['ew'], _A['esub']
    c1, dx, dxy_gap, dxy_13, G = _A['c1'], _A['dx'], _A['dxy_gap'], _A['dxy_13'], _A['G']

    # ── ① 이번 주 판정 — 2026-10-20 다른 탭과 같은 st.metric 카드로 통일(사용자 피드백)
    st.subheader("이번 주 판정")
    st.caption("매주 월요일 아침에 이 한 줄만 보면 된다. 비중을 바꾸는 확정 규칙은 코어 스위치(200일선) 하나다.")
    nl, nl13 = _A['nl'], _A['nl13']
    _flow_short = {'위험자산으로 유입': '유입', '위험자산에서 이탈': '이탈'}.get(flow['word'], flow['word'])
    k1, k2, k3, k4 = st.columns(4)
    k1.metric('코어 스위치 · 확정 규칙', '판정 불가' if core_on is None else ('ON' if core_on else 'OFF'),
              None if gap200 is None else f"200일선 {'위' if core_on else '아래'} {gap200:+.1f}%",
              delta_color='normal' if core_on is not None else 'off',
              help='S&P500(SPY) 종가가 200일 이평 위면 코어 보유, 아래면 코어를 현금으로 — 원칙 v1의 유일한 확정 비중 규칙')
    k2.metric('욕심 신호 · 검증 결과 반영', G['word'], f"참고 경고 {G['n']} / 3", delta_color='off', delta_arrow='off',
              help='참고 경고 = 신용 스프레드 13주 확대 · 우라가미 역국면 · 강달러. 백테스트에서 비중 규칙으로 살아남지 못해 표시만 한다(아래 욕심 조절 원칙).')
    k3.metric('돈의 흐름 · 축 1', f"위험자산 {_flow_short}",
              f"200일선 위 {flow['up']}/{flow['n']} · 순유동성 13주 " + ('-' if nl13 is None else f"{nl13:+.1f}%"),
              delta_color='off', delta_arrow='off', help='자산 8종 중 200일선 위에 있는 수와, 연준 순유동성 13주 변화')
    k4.metric('경기 · 축 2', ew, esub, delta_color='off', delta_arrow='off',
              help='선행 지표 경고 3개 이상이면 꺾일 조짐, 동행 경고 2개 이상이면 둔화')

    # ── ② 축 1 · 돈의 흐름
    st.subheader("축 1 · 돈의 흐름")
    st.caption("돈이 어느 나라·어느 자산으로 가고 있나, 공급은 늘고 있나")
    _world_strength_panel()
    st.markdown("##### 자산군 흐름 — 돈이 주식 밖으로 빠지나")
    if len(at):
        t = at[['자산', '1주(%)', '1개월(%)', '3개월(%)', '1년(%)', '200일선 이격(%)']]
        _asof = max([d for d in at['asof'] if d is not None], default=None)
        st.dataframe(t, filters=False, src='Yahoo Finance (ETF·선물·지수·BTC-USD 종가, 코스피는 원/달러로 나눠 달러 기준)',
                     asof=_asof.strftime('%Y-%m-%d') if _asof is not None else None,
                     column_config={c: st.column_config.NumberColumn(c, format='%+.1f') for c in t.columns if c != '자산'})
        st.caption("200일선 이격이 + 면 그 자산으로 돈이 들어오는 중. 위험자산(주식·구리·비트코인)이 함께 +이고 "
                   "장기채·달러가 − 면 '위험 선호', 반대면 '안전자산 도피'다. 비트코인은 유동성에 가장 먼저 반응하는 자산으로 본다.")
    else:
        st.info("자산 시세를 받지 못했습니다(Yahoo). 잠시 후 새로고침하세요.")

    # 유동성·신용·심리 — st.metric (값 · 변화 · 판정은 help)
    st.markdown("##### 유동성 · 신용 · 심리")
    tiles = []
    if nl13 is not None:
        tiles.append(('순유동성 13주', f"{nl13:+.1f}%", f"잔액 {float(nl.iloc[-1]) / 1000:,.2f}조$", nl13 > 0,
                      '연준 총자산 − 재무부 계좌(TGA) − 역레포. 늘면 시장에 돈이 풀리는 중'))
    ri = S['DFII10']
    if len(ri) > 63:
        d = float(ri.iloc[-1] - ri.iloc[-64])
        tiles.append(('실질금리 10Y', f"{float(ri.iloc[-1]):.2f}%", f"3개월 {d:+.2f}%p", d < 0,
                      '물가연동국채 10년 금리 — 성장주 할인율. 내리면 완화'))
    if dxy_gap is not None and dxy_gap == dxy_gap:
        tiles.append(('달러 인덱스', f"{float(dx.iloc[-1]):.1f}", f"200일선 {dxy_gap:+.1f}%", not G['ref'].get('C8'),
                      f"13주 {dxy_13:+.1f}%. 200일선 위 + 13주 상승이면 '강달러' 참고 경고(신흥국·원자재 역풍)"))
    hy = S['BAMLH0A0HYM2']
    if len(hy):
        p = _pctile(list(hy.values), float(hy.iloc[-1]))
        tiles.append(('하이일드 스프레드', f"{float(hy.iloc[-1]):.2f}%", f"최근 {max(1, len(hy) // 250)}년 하위 {p}%", p < 50,
                      '낮을수록 신용 평온(=탐욕 쪽). FRED가 ICE 지수를 최근 3년치만 제공한다'))
    vx, v3 = S['VIXCLS'], S['VXVCLS']
    if len(vx) and len(v3):
        r = float(vx.iloc[-1]) / float(v3.iloc[-1])
        tiles.append(('VIX ÷ VIX3M', f"{r:.2f}", f"VIX {float(vx.iloc[-1]):.1f}", r <= 1,
                      '1 초과 = 단기 공포가 3개월 공포보다 큼(패닉). 1 미만 = 평시'))
    bt = _mf._clean(closes.get('BTC-USD')) if closes else pd.Series(dtype=float)
    if len(bt) >= 200:
        g = _mf.ma_gap(bt)
        tiles.append(('비트코인 200일선', f"{g:+.1f}%", '위험선호' if g > 0 else '위험회피', g > 0,
                      '유동성의 신흥 바로미터 — 유동성 변화에 가장 먼저 반응하는 자산으로 본다'))
    if tiles:
        cols = st.columns(len(tiles))
        for c, (lab, val, dl, good, hp) in zip(cols, tiles):
            # 좋음/나쁨으로 색을 정한다 — 숫자 부호가 아니라 뜻으로(금리↓ = 좋음)
            c.metric(lab, val, dl, delta_color=('normal' if good else 'inverse'), delta_arrow='off', help=hp)
        st.caption("출처: FRED (WALCL·WTREGEN·RRPONTSYD·DFII10·BAMLH0A0HYM2·VIXCLS·VXVCLS), Yahoo (DX-Y.NYB·BTC-USD) · "
                   f"마지막 갱신: {', '.join(sorted({s.index[-1].strftime('%Y-%m-%d') for k, s in S.items() if k in ('WALCL', 'DFII10', 'VIXCLS') and len(s)}))} 관측 · "
                   "변화 칸 색 = 초록 좋음 / 빨강 나쁨(뜻 기준)")

    # ── ③ 축 2 · 경제 — 다른 탭과 같은 표(table_ui)
    st.subheader("축 2 · 경제")
    st.caption("선행 → 동행 → 물가·금리 순서로 읽는다. 선행이 먼저 꺾이고 실업률은 가장 늦다")
    _sum = ' · '.join(f"{g} {_mf.group_summary(rows, g)[0]}" for g in ('선행', '동행', '물가·금리'))
    _ico = {'pos': '🟢', 'muted': '⚪', 'warn': '🟡', 'neg': '🔴'}
    et = pd.DataFrame([{'구분': r['묶음'], '지표': r['지표'] + (f"({r['unit'].strip()})" if r['unit'].strip() else ''),
                        '현재': r['num'], '판정': f"{_ico.get(r['tone'], '⚪')} {r['판정']}",
                        '설명': r['설명'], '판정 기준': r['기준'], '관측일': r['관측일']} for r in rows])
    st.markdown(f"**요약** — {_sum}")
    st.dataframe(et, filters=False, color=False,
                 src='FRED (ICSA·T10Y3M·CFNAI·NEWORDER·XTEXVA01KRM667S·GDPNOW·INDPRO·PAYEMS·UNRATE·PCEPILFE·CPIAUCSL·FEDFUNDS·DGS10)',
                 asof=max([r['관측일'] for r in rows if r['관측일'] != '-'], default=None),
                 column_config={'현재': st.column_config.NumberColumn('현재', format='%.2f')})
    st.caption("단위는 지표 이름 괄호 안. 관측일은 행마다 다르다 — 월간 지표는 발표까지 1~2개월 걸린다. "
               "ISM 제조업지수는 라이선스 문제로 FRED에서 받을 수 없어 CFNAI·신규수주로 대신한다.")
    return dict(core_on=core_on, gap200=gap200, c1=c1, dxy_gap=dxy_gap, dxy_13=dxy_13, G=G)


def _regime_history_panel():
    """국면 이력 — 지금 쓰는 4계절 판정 규칙을 지난 10년에 그대로 적용해 S&P500 위에 칠한다(2026-10-21).
    판정이 그럴듯한지 눈으로 검산하는 용도다. 월간 지표는 발표 시차 1개월을 반영한다."""
    import macro_svg as _msv
    with st.spinner("국면 이력 계산 중..."):
        fed = _mf.to_series(fetch_fred('FEDFUNDS', 170))
        ip = _mf.to_series(fetch_fred('INDPRO', 170))
        ur = _mf.to_series(fetch_fred('UNRATE', 170))
        spx = fetch_index_history('SPY', 4300)
    if spx.empty or fed.empty or ip.empty:
        st.info("국면 이력에 필요한 시계열(FRED·지수)을 받지 못했습니다.")
        return
    h = _mf.regime_history(fed, ip, ur, spx.iloc[:, 0])
    if h.empty:
        st.info("국면 이력을 계산할 만큼 자료가 쌓이지 않았습니다.")
        return
    fig = go.Figure()
    seg_start = h.index[0]; cur = h['phase'].iloc[0]
    bounds = []
    for dt, ph in h['phase'].items():
        if ph != cur:
            bounds.append((seg_start, dt, cur)); seg_start, cur = dt, ph
    bounds.append((seg_start, h.index[-1] + pd.offsets.MonthEnd(0), cur))
    for x0, x1, ph in bounds:
        fig.add_vrect(x0=x0 - pd.offsets.MonthBegin(1), x1=x1, fillcolor=_msv.SEASON_COLOR[ph], opacity=0.13,
                      line_width=0, layer='below')
    fig.add_trace(go.Scatter(x=h.index, y=h['close'], mode='lines', name='S&P500(SPY)', line=dict(width=2, color='#16181D'),
                             customdata=[SEASONS[p]['name'] for p in h['phase']],
                             hovertemplate='%{x|%Y-%m} · %{customdata}<br>%{y:,.1f}<extra></extra>'))
    for k in _msv.SEASON_ORDER:          # 범례용
        fig.add_trace(go.Scatter(x=[None], y=[None], mode='markers', name=f"{SEASONS[k]['emoji']} {SEASONS[k]['name']}",
                                 marker=dict(size=12, symbol='square', color=_msv.SEASON_COLOR[k], opacity=.45)))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=10, b=8), hovermode='x unified',
                      legend=dict(orientation='h', y=1.1, x=0), yaxis=dict(type='log', title='SPY (로그)'))
    st.plotly_chart(fig, use_container_width=True, key='mac_pc_3325')
    fw = _mf.regime_forward(h, 3)
    if len(fw):
        fw.index = [f"{SEASONS[k]['emoji']} {SEASONS[k]['name']}" for k in fw.index]
        fw = fw.reset_index().rename(columns={'index': '국면'})
        st.dataframe(fw, filters=False,
                     src=f"FRED(FEDFUNDS·INDPRO·UNRATE, 발표 시차 1개월) · FinanceDataReader(SPY) · {h.index[0]:%Y-%m}~{h.index[-1]:%Y-%m} 월말",
                     asof=f"{h.index[-1]:%Y-%m-%d}",
                     column_config={'개월 수': st.column_config.NumberColumn('개월 수', format='%d'),
                                    '다음 3개월 평균(%)': st.column_config.NumberColumn('다음 3개월 평균(%)', format='%+.1f'),
                                    '다음 3개월 상승 비율(%)': st.column_config.NumberColumn('다음 3개월 상승 비율(%)', format='%.0f')})
    st.caption("배경색 = 그 달 판정 국면, 선 = S&P500. 같은 규칙을 과거에 그대로 적용했다(미래 값 미사용). "
               "표의 '다음 3개월'은 국면 판정 뒤 지수가 실제로 어떻게 움직였나 — 10년·개월 수가 작아 통계적 결론이 아니라 검산용이다. "
               "비중 규칙의 근거는 아래 '욕심 조절 원칙'(1988~2026 검증)이다.")


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _ecb_series_cached(key: str, start: str):
    """ECB Data Portal(무료·키 없음) 시계열 → Series. 실패는 예외(캐시에 안 남김)."""
    r = requests.get(f'https://data-api.ecb.europa.eu/service/data/{key}',
                     params={'format': 'csvdata', 'startPeriod': start}, timeout=12)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(pd.to_numeric(df['OBS_VALUE'], errors='coerce').values,
                  index=pd.to_datetime(df['TIME_PERIOD'])).dropna().sort_index()
    if s.empty:
        raise RuntimeError('empty')
    return s


def _ecb_series(key: str, start: str = '2014-01'):
    if _recently_failed(f'ecb:{key}'):
        return pd.Series(dtype=float)
    try:
        return _ecb_series_cached(key, start)
    except Exception:
        _mark_failed(f'ecb:{key}')
        return pd.Series(dtype=float)


def _det_fig(series: dict, ytitle: str, step: bool = False, height: int = 300, yfmt: str = '.2f'):
    fig = go.Figure()
    for lab, sr in series.items():
        if sr is None or len(sr) == 0:
            continue
        fig.add_trace(go.Scatter(x=sr.index, y=sr.values, mode='lines', name=lab,
                                 line=dict(width=2, shape='hv' if step else 'linear'),
                                 hovertemplate=f'{lab} %{{y:{yfmt}}}<extra></extra>'))
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=10, b=8), hovermode='x unified',
                      legend=dict(orientation='h', y=1.12, x=0), yaxis_title=ytitle)
    return fig


def _last_dates(series: dict) -> str:
    return ' · '.join(f"{k} {v.index[-1]:%Y-%m-%d}" for k, v in series.items() if v is not None and len(v))


def _macro_detail_charts():
    """상세 지표 차트 (2026-10-21 전면 정비).
    고친 것: ① limit=60(일간 계열이면 두 달치)로 받아 금리·스프레드가 잘려 보이던 것 → 기간 선택(2·5·10년)
    ② 끊긴 FRED 계열 교체 — PBoC(2023-11 중단)·유로존/일본/중국 M2(2017~2023 중단)·BoK 할인율(IMF)
       → 일본·한국은 익일물 콜금리(OECD, 매월), 영국 SONIA, 유로존 M2 는 ECB Data Portal, 유동성은 G3 중앙은행 총자산."""
    with st.expander("📊 상세 지표 차트 — 정책금리 · 장기금리 · 수익률곡선 · 물가 · 유동성"):
        yrs = {'2년': 2, '5년': 5, '10년': 10}[st.segmented_control('기간', ['2년', '5년', '10년'], default='5년', key='det_rng') or '5년']
        cut = pd.Timestamp.now() - pd.DateOffset(years=yrs)
        _cut = lambda x: x[x.index >= cut] if len(x) else x
        F = lambda sid, n: _cut(_mf.to_series(fetch_fred(sid, n)))
        t1, t2, t3, t4, t5 = st.tabs(['🏦 정책금리', '📈 10년 국채', '📉 수익률곡선', '🔥 물가', '💧 유동성'])
        with t1, st.spinner("금리 로딩..."):
            S = {'미국 Fed': F('DFF', 3700), '유로존 ECB 예치금리': F('ECBDFR', 3700), '영국 SONIA': F('IUDSOIA', 2600),
                 '일본 콜금리': F('IRSTCI01JPM156N', 130), '한국 콜금리': F('IRSTCI01KRM156N', 130)}
            st.plotly_chart(_det_fig(S, '%', step=True), use_container_width=True, key='mac_pc_3396')
            st.caption("출처: FRED (DFF · ECBDFR · IUDSOIA · OECD IRSTCI01JPM156N · IRSTCI01KRM156N) · 마지막 관측: " + _last_dates(S) +
                       ". 일본·한국은 익일물 콜금리(정책금리를 따라가는 시장 금리, 월간). "
                       "중국 인민은행 금리는 FRED 계열이 2023-11에 끊겨 뺐다.")
        with t2, st.spinner("국채 로딩..."):
            S = {'미국': F('DGS10', 2700), '독일': F('IRLTLT01DEM156N', 130), '일본': F('IRLTLT01JPM156N', 130),
                 '한국': F('IRLTLT01KRM156N', 130)}
            st.plotly_chart(_det_fig(S, '%'), use_container_width=True, key='mac_pc_3403')
            st.caption("출처: FRED (DGS10 일간 · OECD 장기금리 월간) · 마지막 관측: " + _last_dates(S) +
                       ". 장기금리는 성장주 할인율 — 실질금리는 축 1 카드에 있다.")
        with t3, st.spinner("수익률곡선 로딩..."):
            S = {'10Y−2Y': F('T10Y2Y', 2700), '10Y−3M': F('T10Y3M', 2700)}
            fig = _det_fig(S, '%p')
            rec = F('USREC', 140)
            if len(rec):
                on = rec[rec > 0]
                for dt in on.index:
                    fig.add_vrect(x0=dt, x1=dt + pd.offsets.MonthEnd(1), fillcolor='#A32C2C', opacity=.08, line_width=0, layer='below')
            fig.add_hline(y=0, line_color='rgba(120,124,134,.6)', line_width=1)
            st.plotly_chart(fig, use_container_width=True, key='mac_pc_3415')
            last = {k: float(v.iloc[-1]) for k, v in S.items() if len(v)}
            st.caption("출처: FRED (T10Y2Y · T10Y3M · USREC) · 마지막 관측: " + _last_dates(S) +
                       ". 빨간 띠 = NBER 경기침체. 0 아래(역전)는 침체 선행으로 알려졌지만, 우리 검증(1988~2026)에선 비중 신호로 탈락했다(주변값 1/3). "
                       + ' · '.join(f"지금 {k} {v:+.2f}%p" for k, v in last.items()))
        with t4, st.spinner("물가 로딩..."):
            yo = lambda sid: (lambda x: (x / x.shift(12) - 1) * 100)(_mf.to_series(fetch_fred(sid, 140)))
            S = {k: _cut(v).dropna() for k, v in {'CPI': yo('CPIAUCSL'), '근원 CPI': yo('CPILFESL'), '근원 PCE': yo('PCEPILFE')}.items()}
            fig = _det_fig(S, 'YoY %', yfmt='.1f')
            fig.add_hline(y=2, line_color='rgba(22,112,74,.6)', line_dash='dot', annotation_text='연준 목표 2%')
            st.plotly_chart(fig, use_container_width=True, key='mac_pc_3425')
            st.caption("출처: FRED (CPIAUCSL · CPILFESL · PCEPILFE) · 마지막 관측: " + _last_dates(S) + ". 연준이 목표로 보는 것은 근원 PCE다.")
        with t5, st.spinner("유동성 로딩..."):
            fed = _mf.to_series(fetch_fred('WALCL', 560)) / 1e6                 # 백만 달러 → 조 달러
            ecb = _mf.to_series(fetch_fred('ECBASSETSW', 560))                  # 백만 유로
            boj = _mf.to_series(fetch_fred('JPNASSETS', 130))                   # 억 엔
            eur = _mf.to_series(fetch_fred('DEXUSEU', 2700)); jpy = _mf.to_series(fetch_fred('DEXJPUS', 2700))
            me = lambda x: x.resample('ME').last() if len(x) else pd.Series(dtype=float)
            _cv = lambda a, f: (a * f.reindex(a.index, method='ffill')) if len(a) and len(f) else pd.Series(dtype=float)
            g3 = pd.DataFrame({'Fed': me(fed), 'ECB': _cv(me(ecb), me(eur)) / 1e6,
                               'BoJ': _cv(me(boj) * 1e8, 1 / me(jpy) if len(jpy) else pd.Series(dtype=float)) / 1e12})
            g3 = _cut(g3).dropna(how='all').ffill()      # 월간(BoJ)·주간(Fed·ECB) 발표 시차로 마지막 달이 빠져 합계가 꺼지지 않게
            fig = go.Figure()
            for c in ['Fed', 'ECB', 'BoJ']:
                if c in g3 and g3[c].notna().any():
                    fig.add_trace(go.Scatter(x=g3.index, y=g3[c], name=c, stackgroup='g3', mode='lines',
                                             hovertemplate=f'{c} %{{y:.2f}}조$<extra></extra>'))
            fig.update_layout(height=280, margin=dict(l=8, r=8, t=10, b=8), hovermode='x unified',
                              legend=dict(orientation='h', y=1.12, x=0), yaxis_title='조 달러')
            st.markdown("**G3 중앙은행 총자산** — 돈을 찍어 푸는 규모(달러 환산)")
            st.plotly_chart(fig, use_container_width=True, key='mac_pc_3445')
            m2u = _mf.to_series(fetch_fred('M2SL', 140)); m2u = (m2u / m2u.shift(12) - 1) * 100
            m2e = _ecb_series('BSI/M.U2.Y.V.M20.X.I.U2.2300.Z01.A', f"{cut:%Y-%m}")
            S = {'미국 M2': _cut(m2u).dropna(), '유로존 M2': _cut(m2e)}
            fig2 = _det_fig(S, 'YoY %', height=260, yfmt='.1f')
            fig2.add_hline(y=0, line_color='rgba(120,124,134,.6)', line_width=1)
            st.markdown("**M2 증가율**")
            st.plotly_chart(fig2, use_container_width=True, key='mac_pc_3452')
            st.caption("출처: FRED (WALCL · ECBASSETSW · JPNASSETS · DEXUSEU · DEXJPUS · M2SL), ECB Data Portal (유로존 M2 연간 증가율) · "
                       "마지막 관측: " + _last_dates({'Fed': fed, 'ECB': ecb, 'BoJ': boj, **S}) +
                       ". 일본·중국 M2는 무료 공개 계열이 2017~2023년에 끊겨 뺐다(예전 차트의 끊긴 선이 그것). 순유동성(Fed−TGA−역레포)은 축 1 카드에 있다.")


def _macro_rules_section(V, _RG):
    """④ 욕심 조절 원칙 — 백테스트로 검증한 것만 비중에 쓴다."""
    st.subheader("욕심 조절 원칙 — 백테스트로 검증한 것만 비중에 쓴다")
    st.caption("합격 기준(결과 보기 전에 고정): 200일선보다 Calmar +0.05 이상 · MDD 악화 없음 · 세 구간 중 2개 이상 · 주변값 과반")
    G = V['G']
    now = {
        'B0': '—',
        'B1': '-' if V['gap200'] is None else f"{'위' if V['core_on'] else '아래'} {V['gap200']:+.1f}%",
        'C1': '-' if V['c1'] is None else f"{V['c1']:+.2f}%p · {'경고' if G['ref']['C1'] else '평온'}",
        'C6': f"{SEASONS[_RG['phase']]['name']} · {'경고' if G['ref']['C6'] else '아님'}" if _RG.get('phase') else '-',
        'C8': '-' if V['dxy_gap'] is None or V['dxy_gap'] != V['dxy_gap'] else f"200일선 {V['dxy_gap']:+.1f}% · {'경고' if G['ref']['C8'] else '아님'}",
        'C5': '-', 'C3': '-', 'C2': '-', 'C7': f"{_RG.get('pend', '-')}",
    }
    t = pd.DataFrame([{'신호': n, '지금': now.get(k, '-'), 'CAGR(%)': c, 'MDD(%)': m, 'Calmar': ca, '판정': v, '쓰는 법': u}
                      for k, n, c, m, ca, v, u in _mf.RULES])
    st.dataframe(t, filters=False, color=False,
                 src='research/macro_regime_bt.py · S&P500 총수익 주봉 1988-01~2026-09 · 달러 기준 · 1주 지연 · 비용 0.1% · 200일선 위에 덧씌운 결과',
                 asof='2026-10-20 검증',
                 column_config={'CAGR(%)': st.column_config.NumberColumn('CAGR(%)', format='%.2f'),
                                'MDD(%)': st.column_config.NumberColumn('MDD(%)', format='%.1f'),
                                'Calmar': st.column_config.NumberColumn('Calmar', format='%.3f')})
    st.caption("**읽는 법** — Calmar = CAGR ÷ |MDD|, 클수록 같은 낙폭에서 더 번다. 200일선은 매수보유보다 CAGR을 2.8%p 내주고 MDD를 25%p 줄였다. "
               "그 위에 매크로 신호를 더 얹어 사전 기준을 통과하고 검산까지 버틴 것은 **아직 없다**. "
               "⚠️ **원화 기준 검산** (2004년 이후): S&P500 매수보유의 원화 MDD는 −55%가 아니라 **약 −28% 수준**에 그쳤다 — 위기 때 달러가 올라 자동 헤지가 된다. "
               "그래서 원화 투자자에게는 200일선 스위치도 Calmar를 낮췄다(0.42 → 0.38). 원칙 v1 자산배분을 원화 기준으로 다시 검증한다.")



with tab4, guard('매크로'):
    st.header("🌍 매크로")
    st.caption("돈은 어디로 흐르고, 경기는 어디로 가나 — 두 축을 보고, 욕심을 얼마나 부릴지 정한다. "
               "시세 3시간 · FRED 1시간 캐시 · 지표마다 관측일을 따로 적는다(월간 지표는 1~2개월 늦다).")

    with st.spinner("사이클 지표 수집 중..."):
        _MI = macro_inputs()
        _PX = macro_price_state()
    _RG = macro_regime(_MI, _PX)
    _S = SEASONS[_RG['phase']]

    # ── 결론 먼저 (2026-10-21 사용자 피드백) — 지금 국면 → 이번 주 판정 → 근거(두 축) 순서
    st.subheader("지금 국면")
    st.caption("두 축(돈의 흐름 · 경제)이 만나는 곳. 지도는 '어디쯤인가'를 보여줄 뿐, 비중은 아래 검증된 원칙이 정한다.")

    # ── ① 국면 대형 카드 ──────────────────────────────────────────
    _SCOL = {'FIN': '#16a34a', 'EARN': '#ca8a04', 'RFIN': '#ea580c', 'RERN': '#2563eb'}
    _SBG  = {'FIN': '#f0fdf4', 'EARN': '#fefce8', 'RFIN': '#fff7ed', 'RERN': '#eff6ff'}
    _c, _bg = _SCOL[_RG['phase']], _SBG[_RG['phase']]
    _conf_txt = ('확신 높음' if _RG['conf'] >= 2 else
                 ('경계선 — ' + SEASONS[_RG['second']]['name'] + '과 혼재' if _RG['conf'] == 0 else '보통'))
    st.markdown(
        f"<div style='background:{_bg};border:1px solid {_c}44;border-left:6px solid {_c};"
        f"border-radius:12px;padding:18px 22px;margin-bottom:10px'>"
        f"<div style='font-size:26px;font-weight:800;color:{_c};line-height:1.25'>"
        f"{_S['emoji']} {_S['name']}<span style='font-size:14px;font-weight:600;color:#6b7280'>"
        f"&nbsp;&nbsp;{_S['sub']}&nbsp;·&nbsp;{_conf_txt}</span></div>"
        f"<div style='font-size:14px;color:#374151;margin-top:8px'>{_S['desc']}</div>"
        f"<div style='font-size:12.5px;color:#6b7280;margin-top:10px'>"
        f"판정 근거 — 금리 <b>{_RG['rate_dir']}</b>(6개월 {_MI.get('fed_6m','-')}%p) &nbsp;·&nbsp; "
        f"실적 <b>{_RG['growth']}</b>(산업생산 YoY {_MI.get('ip_yoy','-')}%) &nbsp;·&nbsp; "
        f"주가 <b>{_RG['px_dir']}</b>(200일선 {'위' if _PX.get('above_ma') else '아래'})</div>"
        f"</div>", unsafe_allow_html=True)

    # st.success/st.error 는 '성공/실패' 알림으로 읽히므로 쓰지 않는다.
    # 색 면적도 줄인다 — 큰 색 블록이 나란히 서면 화면이 소리를 지른다.
    # 흰 바탕 + 왼쪽 4px 액센트만으로 대비를 준다.
    _w1, _w2 = st.columns(2, gap='medium')
    for _col, _ttl, _txt, _ac in (
            (_w1, '이 국면에서 통하는 것', _S['works'], '#16a34a'),
            (_w2, '이 국면에서 안 통하는 것', _S['fails'], '#dc2626')):
        _col.markdown(
            f"<div style='background:#ffffff;border:1px solid #e8e8e4;border-left:4px solid {_ac};"
            f"border-radius:10px;padding:15px 18px'>"
            f"<div style='font-size:12px;font-weight:800;letter-spacing:.4px;color:{_ac}'>{_ttl}</div>"
            f"<div style='font-size:13.5px;color:#374151;margin-top:8px;line-height:1.6'>{_txt}</div></div>",
            unsafe_allow_html=True)

    # ── 사이클 도식 — 우라가미 4계절 바퀴 · 코스톨라니 달걀 (2026-10-21: 알약 목록 → 도는 그림)
    #    막스 시계추는 뺐다 — 1988~2026 검증에서 '탐욕'이 매도 근거가 못 됐고(욕심 조절 원칙 C7),
    #    위험 심리는 축 1의 하이일드 스프레드·VIX 기간구조 카드가 이미 보여준다.
    import macro_svg as _msv
    _conf_s = ('확신 높음' if _RG['conf'] >= 2 else ('경계선' if _RG['conf'] == 0 else '확신 보통'))
    _D1, _D2 = st.columns(2, gap='medium')
    with _D1.container(border=True):
        st.markdown("##### 🗓️ 우라가미 4계절 — 지금 무슨 장인가")
        st.markdown(_msv.season_wheel(_RG['phase'], _RG['scores'], SEASONS, _conf_s), unsafe_allow_html=True)
        st.caption(f"시계 방향으로 돈다: 금융장세(봄) → 실적장세(여름) → 역금융장세(가을) → 역실적장세(겨울). "
                   f"점수 = 금리 방향·실적 방향·주가 추세 3축 부합도. 1·2위 차이가 확신도"
                   + (f" — 지금은 {SEASONS[_RG['second']]['name']}와 혼재." if _RG['conf'] == 0 else "."))
    with _D2.container(border=True):
        st.markdown("##### 🥚 코스톨라니 달걀 — 무슨 자산을 들 때인가")
        _ei = _RG['egg_i']
        _code = EGG[_ei][0] if _ei is not None else None
        st.markdown(_msv.kostolany_egg(_code, flat=bool(_RG.get('egg_flat'))), unsafe_allow_html=True)
        if _ei is None:
            st.caption("금리 데이터가 없어 판정하지 못했습니다.")
        elif _RG.get('egg_flat'):
            _nb = [EGG[j][0] for j in (_ei - 1, _ei + 1) if 0 <= j < len(EGG)]
            st.caption(f"금리 {_MI.get('fed','-')}%가 최근 10년의 {_MI.get('fed_pct','-')}% 지점, 6·12개월 변화가 작아 "
                       f"**방향 미확정** — 금리가 움직이는 쪽에 따라 {' 또는 '.join(_nb)}로 갈린다. 지금은 4계절을 우선해 본다.")
        else:
            st.caption(f"{EGG[_ei][1]} — {EGG[_ei][2]} (금리 {_MI.get('fed','-')}%, 10년 분포의 {_MI.get('fed_pct','-')}% 지점, "
                       f"6개월 {_MI.get('fed_6m','-')}%p)")

    _MV = _macro_v2_top(_PX, _RG)

    # ── 국면 이력 · 궤적 · 전이 감시판
    st.subheader("국면은 어떻게 흘러왔나")
    _tb0, _tb1, _tb2 = st.tabs(['🗓️ 국면 이력 — S&P500 위에 그린 10년', '🌀 사이클 궤적 — 지난 2년',
                                '🚨 전이 감시판 — 무엇이 바뀌면 넘어가나'])
    with _tb0:
        _regime_history_panel()
    with _tb1:
        # ── ③ 사이클 궤적 ────────────────────────────────────────────
        _ip_h, _ff_h = _MI.get('ip_hist'), _MI.get('fed_hist')
        if _ip_h and _ff_h and len(_ff_h) >= 30:
            _ffd = {dt: v for dt, v in _ff_h}
            _ffk = sorted(_ffd)
            _d6 = {_ffk[i]: round(_ffd[_ffk[i]] - _ffd[_ffk[i - 6]], 2) for i in range(6, len(_ffk))}
            _pts = [(dt, y, _d6[dt]) for dt, y in _ip_h if dt in _d6][-24:]
            if len(_pts) >= 4:
                # 마크 규격(dataviz): 선 2px 실선 · 마커 지름 ≥8px · 격자는 표면에서 한 단계
                # 떨어진 실선 헤어라인(점선 금지) · 텍스트에는 시리즈 색을 입히지 않는다.
                # 시간 방향은 '오래된 구간=옅은 파랑 / 최근 6개월=진한 파랑 3px'로 표현한다
                # (무지개 램프 대신 같은 계열 두 단계 — 순차 인코딩).
                _CY_OLD, _CY_NEW, _CY_NOW = '#9ec5f4', '#2a78d6', '#eb6834'
                _INK, _MUTED, _GRID = '#0b0b0b', '#898781', '#e1e0d9'
                _xs = [p[1] for p in _pts]; _ys = [p[2] for p in _pts]
                _xr = max(abs(min(_xs)), abs(max(_xs))) * 1.18 + 0.35
                _yr = max(abs(min(_ys)), abs(max(_ys))) * 1.25 + 0.15
                _fig_cy = go.Figure()
                # 현재 사분면만 아주 옅게 깔아 '지금 여기'를 배경으로 알린다
                _qx = [0, _xr] if _xs[-1] >= 0 else [-_xr, 0]
                _qy = [0, _yr] if _ys[-1] >= 0 else [-_yr, 0]
                _fig_cy.add_shape(type='rect', x0=_qx[0], x1=_qx[1], y0=_qy[0], y1=_qy[1],
                                  fillcolor='rgba(42,120,214,0.045)', line_width=0, layer='below')
                _cut = max(0, len(_pts) - 7)          # 최근 6개월 강조 (구간이므로 -7부터 이어붙임)
                _fig_cy.add_trace(go.Scatter(
                    x=_xs[:_cut + 1], y=_ys[:_cut + 1], mode='lines',
                    line=dict(color=_CY_OLD, width=2, shape='spline', smoothing=0.6),
                    hoverinfo='skip', showlegend=False))
                _fig_cy.add_trace(go.Scatter(
                    x=_xs, y=_ys, mode='markers',
                    marker=dict(size=9, color=_CY_OLD, line=dict(color='#ffffff', width=2)),
                    text=[p[0][:7] for p in _pts],
                    hovertemplate='%{text}<br>산업생산 YoY %{x:.2f}%<br>금리 6개월 %{y:+.2f}%p<extra></extra>',
                    showlegend=False))
                _fig_cy.add_trace(go.Scatter(
                    x=_xs[_cut:], y=_ys[_cut:], mode='lines',
                    line=dict(color=_CY_NEW, width=3, shape='spline', smoothing=0.6),
                    hoverinfo='skip', name='최근 6개월'))
                _fig_cy.add_trace(go.Scatter(
                    x=[_xs[0]], y=[_ys[0]], mode='markers+text',
                    marker=dict(size=11, color='#ffffff', line=dict(color=_CY_OLD, width=3)),
                    text=[f"  {_pts[0][0][:7]} 시작"], textposition='middle right',
                    textfont=dict(size=12, color=_MUTED), hoverinfo='skip', showlegend=False))
                _fig_cy.add_trace(go.Scatter(
                    x=[_xs[-1]], y=[_ys[-1]], mode='markers+text',
                    marker=dict(size=17, color=_CY_NOW, line=dict(color='#ffffff', width=3)),
                    text=[f"현재 {_pts[-1][0][:7]}  "], textposition='middle left',
                    textfont=dict(size=14, color=_INK, family='sans-serif'),
                    hovertemplate=f'현재 {_pts[-1][0][:7]}<br>산업생산 YoY %{{x:.2f}}%<br>금리 6개월 %{{y:+.2f}}%p<extra></extra>',
                    showlegend=False))
                # 2026-10-21 개선 — 6개월마다 월 표기 + 흐름 방향 화살표(점만 있으면 어느 쪽으로 도는지 안 보인다)
                for _i in range(len(_pts) - 7, 0, -6):
                    _fig_cy.add_annotation(x=_xs[_i], y=_ys[_i], text=_pts[_i][0][:7], showarrow=False, yshift=14,
                                           font=dict(size=11, color=_MUTED))
                for _i in range(max(1, len(_pts) - 6), len(_pts)):
                    if (_xs[_i], _ys[_i]) != (_xs[_i - 1], _ys[_i - 1]):
                        _fig_cy.add_annotation(x=_xs[_i], y=_ys[_i], ax=_xs[_i - 1], ay=_ys[_i - 1], xref='x', yref='y',
                                               axref='x', ayref='y', text='', showarrow=True, arrowhead=3, arrowsize=1.1,
                                               arrowwidth=1.6, arrowcolor=_CY_NEW, opacity=.9)
                _fig_cy.add_hline(y=0, line_color='#c3c2b7', line_width=1)
                _fig_cy.add_vline(x=0, line_color='#c3c2b7', line_width=1)
                for _tx, _ty, _ta, _tv, _tt in [
                        (_xr, _yr, 'right', 'top', '☀️ 실적장세<br><span style="font-size:11px">성장↑ 금리↑</span>'),
                        (-_xr, _yr, 'left', 'top', '🍂 역금융장세<br><span style="font-size:11px">성장↓ 금리↑</span>'),
                        (-_xr, -_yr, 'left', 'bottom', '🌱 금융 / ❄️ 역실적<br><span style="font-size:11px">성장↓ 금리↓ · 주가로 구분</span>'),
                        (_xr, -_yr, 'right', 'bottom', '🔁 회복 초입<br><span style="font-size:11px">성장↑ 금리↓</span>')]:
                    _fig_cy.add_annotation(x=_tx, y=_ty, text=_tt, showarrow=False,
                                           xanchor=_ta, yanchor=_tv, align=('right' if _ta == 'right' else 'left'),
                                           font=dict(size=13, color=_MUTED))
                _fig_cy.update_layout(height=420, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                      font=dict(color=_MUTED, size=12), showlegend=False,
                                      margin=dict(l=10, r=10, t=16, b=46),
                                      hoverlabel=dict(font_size=13),
                                      xaxis_title=dict(text='실적 사이클 — 산업생산 YoY (%)', font=dict(size=13)),
                                      yaxis_title=dict(text='금리 방향 — Fed 6개월 변화 (%p)', font=dict(size=13)),
                                      xaxis_range=[-_xr, _xr], yaxis_range=[-_yr, _yr])
                _fig_cy.update_xaxes(gridcolor=_GRID, zeroline=False, ticksuffix='%', tickfont=dict(size=12))
                _fig_cy.update_yaxes(gridcolor=_GRID, zeroline=False, tickfont=dict(size=12))
                st.plotly_chart(_fig_cy, use_container_width=True, key='mac_pc_3648')
                _c1, _c2 = st.columns([3, 2])
                _c1.markdown(
                    "<span style='display:inline-block;width:22px;height:3px;background:#2a78d6;"
                    "vertical-align:middle;border-radius:2px'></span> <b>최근 6개월</b> &nbsp;&nbsp;"
                    "<span style='display:inline-block;width:22px;height:2px;background:#9ec5f4;"
                    "vertical-align:middle;border-radius:2px'></span> 그 이전 &nbsp;&nbsp;"
                    "<span style='display:inline-block;width:11px;height:11px;background:#eb6834;"
                    "border-radius:50%;vertical-align:middle'></span> <b>현재</b>",
                    unsafe_allow_html=True)
                with _c2.popover("📋 값으로 보기"):
                    _tsrc('FRED API(산업생산·정책금리)', live=True)
                    st.dataframe(pd.DataFrame([{'월': p[0][:7], '산업생산 YoY(%)': round(p[1], 2),
                                                '금리 6개월(%p)': p[2]} for p in reversed(_pts)]),
                                 use_container_width=True, hide_index=True, row_height=25, height=260)
                st.caption("지금 어디 있느냐보다 **어느 쪽으로 움직이는 중이냐**가 중요하다.")
                with st.expander("이 그림 읽는 법"):
                    st.caption("사이클은 보통 **시계 반대 방향**으로 돈다: "
                               "회복 초입 → 실적장세 → 역금융 → 역실적 → 다시 회복.")
                    st.caption("좌하단은 금융장세와 역실적장세가 겹치므로 "
                               "주가 추세(200일선)로 가른다.")
        else:
            st.caption("궤적 표시에 필요한 시계열(FEDFUNDS·INDPRO)을 불러오지 못했습니다.")

        # ── ④ 전이 감시판 ────────────────────────────────────────────
    with _tb2:
        st.caption("예측이 아니라 **체크리스트**다 — 임계를 넘으면 국면이 그쪽으로 움직인다.")
        _TR = macro_triggers(_MI, _PX)
        _tw1, _tw2 = st.columns(2)
        for _col, _side, _hdr in ((_tw1, '악화', '⬇️ 악화 쪽 방아쇠'), (_tw2, '개선', '⬆️ 개선 쪽 방아쇠')):
            with _col:
                st.markdown(f"**{_hdr}**")
                # 색 의미는 '좋다/나쁘다'로 통일한다. 개선 방아쇠가 발동한 건 좋은 일이므로
                # 빨강으로 칠하면 안 된다(발동=빨강으로 두면 호재가 경고처럼 읽힌다).
                _bad = (_side == '악화')
                _rows = [t for t in _TR if t['side'] == _side]
                _tsrc('FRED API(금리·스프레드·실업률) · FinanceDataReader(지수)', live=True)
                st.dataframe(pd.DataFrame([{
                    '상태': ('❓ 자료없음' if t['hit'] is None else
                            (('🔴 발동' if _bad else '🟢 발동') if t['hit'] else
                             ('🟢 아직' if _bad else '⚪ 아직'))),
                    # 숫자는 숫자로, 단위는 지표 이름 괄호에(표 규칙 2026-10-19)
                    '지표': t['name'] + ('(%p)' if t['thr'].endswith('%p') else ('(%)' if t['thr'].endswith('%') else '')),
                    '현재': t['val'], '임계': t['thr'].rstrip('%p').rstrip('%')} for t in _rows]),
                    filters=False, color=False,
                    column_config={'현재': st.column_config.NumberColumn('현재', format='%+.2f')})
                for t in _rows:
                    if t['hit']:
                        st.caption(f"{'🔴' if _bad else '🟢'} **{t['name']}** — {t['why']}")
        with st.expander("각 방아쇠가 무슨 뜻인지 (전체)"):
            for t in _TR:
                st.markdown(f"- **[{t['side']}] {t['name']}** (현재 {t['cur']} / 임계 {t['thr']}) — {t['why']}")

    _macro_rules_section(_MV, _RG)

    _macro_detail_charts()

# ════════════════════════════════════════════════════════════════════
# 탭5: 추천 포트폴리오
# ════════════════════════════════════════════════════════════════════
def _signal_score(s):
    score = 0
    is52  = s.get('sig_52w',     False)
    isMac = s.get('sig_maconv',  False)
    isCup = s.get('sig_cup',     False)
    isMa5 = s.get('sig_ma5',    False)
    isRsi = s.get('sig_rsimacd', False)

    if is52 and isMac: score += 5
    elif is52:         score += 4
    elif isMac:        score += 4
    if isCup: score += 2
    if isMa5: score += 1
    if isRsi: score += 1

    dist = s.get('dist_52w') or 0
    if   0   <= dist <= 5:  score += 2
    elif -5  <= dist <  0:  score += 1
    elif dist > 40:          score -= 2
    elif dist > 20:          score -= 1

    has_primary = is52 or isMac
    return score, has_primary





# ════════════════════════════════════════════════════════════════════
# 탭7: 종목 분석 (차트 + 지표 + 재무)
# ════════════════════════════════════════════════════════════════════
def _rsi(closes: pd.Series, period=14) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float('nan'))
    return 100 - (100 / (1 + rs))

def _macd(closes: pd.Series, fast=12, slow=26, sig=9):
    ema_f = closes.ewm(span=fast,  adjust=False).mean()
    ema_s = closes.ewm(span=slow,  adjust=False).mean()
    line  = ema_f - ema_s
    signal= line.ewm(span=sig, adjust=False).mean()
    return line, signal, line - signal

def _fib(high: float, low: float):
    d = high - low
    return {
        '0% (고점)':      high,
        '23.6%':          high - d * 0.236,
        '38.2%':          high - d * 0.382,
        '50%':            high - d * 0.5,
        '61.8% (황금비)': high - d * 0.618,
        '78.6%':          high - d * 0.786,
        '100% (저점)':    low,
    }

def _fib_ext(high: float, low: float):
    d = high - low
    return {
        '100% (고점)':       high,
        '127.2% (+1목표)':   low + d * 1.272,
        '141.4%':            low + d * 1.414,
        '161.8% (황금비)':   low + d * 1.618,
        '200%':              low + d * 2.0,
        '261.8%':            low + d * 2.618,
    }

def _tf_signal(rsi_val, macd_val, sig_val, price, ma20, ma50):
    score, reasons = 0, []
    if rsi_val is not None and not pd.isna(rsi_val):
        if 50 < rsi_val < 70:  score += 1; reasons.append(f'RSI {rsi_val:.0f} 상승')
        elif rsi_val >= 70:              reasons.append(f'RSI {rsi_val:.0f} 과매수')
        elif rsi_val < 30:    score -= 1; reasons.append(f'RSI {rsi_val:.0f} 과매도')
        else:                             reasons.append(f'RSI {rsi_val:.0f} 중립')
    if macd_val > sig_val:  score += 1; reasons.append('MACD 골든크로스')
    else:                   score -= 1; reasons.append('MACD 데드크로스')
    if ma20 and price > ma20: score += 1; reasons.append('MA20 위')
    elif ma20:                score -= 1; reasons.append('MA20 아래')
    if ma50 and price > ma50: score += 1; reasons.append('MA50 위')
    elif ma50:                score -= 1; reasons.append('MA50 아래')
    label = '🟢 매수적정' if score >= 3 else ('🔴 매도위험' if score <= -2 else '🟡 중립관망')
    return label, score, reasons

@st.cache_data(ttl=1800, show_spinner=False, max_entries=48)
def _fetch_stock_data_cached(sym: str, days: int):
    """실패는 raise → 캐시에 안 남는다. (2026-10-17 전: 실패도 (None, …) 로 30분 캐시돼
    일시 오류 한 번이면 그 종목이 30분 동안 '데이터 없음'으로 고정됐다.)"""
    import FinanceDataReader as fdr

    # 2026-09-10: 우선주 코드는 끝자리가 영문이다(00088K). isdigit() 만 보면
    # 그것들이 US 로 새어 나가 미국 화면에 섞인다 — 앞 5자리로 판정한다.
    is_kr = len(sym) == 6 and sym[:5].isdigit()
    code  = sym.replace('.KS','').replace('.KQ','')
    fdr_sym = code if is_kr else sym
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    try:
        hist = fdr.DataReader(fdr_sym, start)
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        # 2026-10-20 사고: 장 시작 전·중에 소스가 '오늘' 행을 종가 NaN 으로 붙여 와 현재가가 $nan 이 됐고
        #   52주·수익률·시총 정합이 전부 nan 으로 번졌다. 종가가 없는(또는 0 이하인) 행은 봉이 아니다.
        hist = hist[pd.to_numeric(hist['Close'], errors='coerce') > 0] if 'Close' in hist.columns else hist
        for c in ['Open','High','Low','Close','Volume']:
            if c not in hist.columns: hist[c] = 0.0

        info = {}
        if is_kr:
            try:
                import krx_listing
                krx = krx_listing.stock_listing('KRX', verbose=False)
                row = krx[krx['Code'] == code]
                if not row.empty:
                    r = row.iloc[0]
                    info = {'longName': str(r.get('Name', code)),
                            'sector':   str(r.get('Sector', '')),
                            'currency': 'KRW',
                            'marketCap': int(r.get('Marcap', 0))}
            except: pass
        else:
            try:
                sp = fdr.StockListing('S&P500')
                row = sp[sp['Symbol'] == sym]
                if not row.empty:
                    r = row.iloc[0]
                    info = {'longName': str(r.get('Name', sym)),
                            'sector':   str(r.get('Sector', '')),
                            'currency': 'USD'}
            except: pass

        earn = {'annual': None, 'quarterly': None, 'naver': None}
        insid = fin_est = None
        yf_sym = _yf_code(code, True) if is_kr else sym   # KOSDAQ 은 .KQ (2026-10-20: 전부 .KS 라 코스닥 종목 yfinance 가 통째로 비었다)
        try:
            t = yf.Ticker(yf_sym)
            yi = t.info or {}
            if yi and (yi.get('trailingPE') or yi.get('longName')):
                info.update({k: v for k, v in yi.items() if v is not None})
            def _first_nonempty(*attrs):
                for a in attrs:
                    try:
                        d = getattr(t, a)
                        if d is not None and hasattr(d, 'empty') and not d.empty:
                            return d
                    except Exception:
                        pass
                return None
            earn['annual'] = _first_nonempty('financials', 'income_stmt')
            earn['quarterly'] = _first_nonempty('quarterly_financials', 'quarterly_income_stmt')
            if not is_kr:
                try: insid = t.insider_transactions
                except: pass
                try: fin_est = t.earnings_estimate
                except: pass
        except: pass

        # 한국 종목: yfinance가 429로 막히는 경우 네이버 실적표로 폴백 (순이익 기준)
        if is_kr:
            try:
                from canslim_run import fetch_naver_earnings_table
                earn['naver'] = fetch_naver_earnings_table(code)
            except Exception:
                pass

        if hist is None or hist.empty:
            raise RuntimeError(f'no price history: {sym}')
        return hist, info, earn, insid, fin_est
    except Exception:
        raise


def fetch_stock_data(sym: str, days: int):
    try:
        return _fetch_stock_data_cached(sym, days)
    except Exception:
        return None, {}, None, None, None


@st.cache_data(ttl=6 * 3600, max_entries=48)
def _official_cached(sym, is_kr):
    rows = _official_fetch(sym, is_kr)
    if not rows:
        raise RuntimeError('empty financials')   # 빈 결과는 캐시하지 않음
    return rows


def official_financials(sym, is_kr):
    """공식 재무제표: KR=DART, US=EDGAR. 실패/빈 결과는 캐시 안 됨(다음 조회 때 재시도).
    KR 은 DART 실시간이 막히면 저장된 DART 연간 손익(매출·영업익·순익)으로 대신한다(자본 등은 None)."""
    try:
        return _official_cached(sym, is_kr)
    except Exception:
        pass
    if is_kr:
        nav = unified_statements(sym, True, 'annual')          # DART→네이버 (캐시 공유)
        if nav:
            return [dict(r, roe=(round(r['net_income'] / r['equity'] * 100, 1)
                                 if (r.get('net_income') and r.get('equity')) else None)) for r in nav]
        rows, _ = kr_stored_statements(sym, 'annual', 5)
        return [dict(r, equity=None, assets=None, liabilities=None, eps=None, roe=None,
                     _src='stored') for r in rows]
    return []


def _official_fetch(sym, is_kr):
    """반환: [{period, revenue, op_income, net_income, equity, assets, eps, roe}] 최신순."""
    try:
        if is_kr:
            import dart_client
            from datetime import datetime as _dt
            cc = dart_client.corp_map().get(sym)
            if not cc:
                return []
            out = []
            for y in [_dt.now().year - 1 - i for i in range(4)]:
                f = dart_client.financials(cc, y, 'annual')
                if not any(f.get(k) for k in ('revenue', 'net_income', 'op_income')):
                    continue
                cf = dart_client.cashflow(cc, y, 'annual')
                ni, eq = f.get('net_income'), f.get('equity')
                out.append({'period': str(y), 'revenue': f.get('revenue'), 'op_income': f.get('op_income'),
                            'net_income': ni, 'equity': eq, 'assets': f.get('assets'),
                            'liabilities': f.get('liabilities'),
                            'op_cf': cf.get('op_cf'), 'inv_cf': cf.get('inv_cf'), 'fin_cf': cf.get('fin_cf'),
                            'eps': None, 'roe': round(ni / eq * 100, 1) if (ni and eq) else None})
            return out
        else:
            import edgar_client
            fa = edgar_client.facts(sym)
            if not isinstance(fa, dict) or fa.get('_err'):
                return []
            return [{'period': y, 'revenue': d.get('revenue'), 'op_income': d.get('op_income'),
                     'net_income': d.get('net_income'), 'equity': d.get('equity'),
                     'assets': d.get('assets'), 'liabilities': d.get('liabilities'),
                     'op_cf': d.get('op_cf'), 'inv_cf': d.get('inv_cf'), 'fin_cf': d.get('fin_cf'),
                     'eps': d.get('eps'), 'roe': d.get('roe')}
                    for y, d in list(fa.items())[:5]]
    except Exception:
        return []


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _form4_rows(sym):
    """US Form 4 원문 최근 1년(최대 30건) — 성공만 캐시(실패는 예외)."""
    import edgar_client
    edgar_client.set_interactive(True)
    return edgar_client.form4_transactions(sym, days=365, limit=30)


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _kr_dilution_live(sym):
    """성공만 캐시한다(실패는 예외 → 캐시 안 됨). 공시 목록 실패는 조건표만 살린다."""
    import dart_client
    dart_client.set_interactive(True)
    cc = dart_client.corp_map().get(sym)
    if not cc:
        raise LookupError('DART 회사코드 없음')
    out = {'terms': dart_client.dilution_terms(cc, years=4), 'events': [], 'src': 'DART 주요사항보고(실시간)', 'err': None}
    try:
        out['events'] = dart_client.dilution_events(cc, days=365)
    except Exception as e:
        out['err'] = f"공시 목록 실패: {type(e).__name__}"
    return out


def kr_dilution(sym):
    """KR 잠재 희석 — CB·BW·EB 발행 조건 + 최근 1년 관련 공시(2026-10-21).
    실시간 DART(대화형 타임아웃·차단기) → 실패하면 주간 저장본 data/kr_dilution.parquet(발행 조건만)."""
    try:
        return _kr_dilution_live(sym)
    except Exception as e:
        out = {'terms': [], 'events': [], 'src': '', 'err': f"DART 실시간 실패: {type(e).__name__}"}
    try:
        d = _kr_dilution_store()
        x = d[d['sym'] == sym]
        out['terms'] = [{k: (None if (isinstance(v, float) and v != v) else v) for k, v in r.items()}
                        for r in x.to_dict('records')]
        out['src'] = f"DART 저장본(주간 갱신 {d['fetched'].max()})"
    except Exception:
        pass
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def _kr_dilution_store():
    return pd.read_parquet('data/kr_dilution.parquet')


@st.cache_data(ttl=6 * 3600, max_entries=48)
def kr_insiders(sym):
    """KR 내부자(임원·주요주주) 매수/매도 — DART 공식. [{date,name,position,change,holdings}]."""
    try:
        import dart_client
        cc = dart_client.corp_map().get(sym)
        return dart_client.insiders(cc, 40) if cc else []   # 1년 합계를 내려면 10건으로는 모자란다
    except Exception:
        return []


@st.cache_data(ttl=6 * 3600, max_entries=48)
def _unified_cached(sym, is_kr, freq):
    """빈 결과는 raise → 캐시 안 됨 (서버 일시 실패가 6시간 눌러붙는 것 방지).
    KR: DART 우선 → 막힌 서버(해외 클라우드)면 네이버 기업분석(FnGuide 집계, kr_fin_naver — 공시 대조 확인)."""
    if is_kr:
        rows = []
        try:
            import dart_client
            cc = dart_client.corp_map().get(sym)
            rows = dart_client.statements(cc, freq, 5) if cc else []
        except Exception:
            rows = []
        if not rows:
            import kr_fin_naver
            rows = kr_fin_naver.statements(sym, freq, 5)
    else:
        import edgar_client
        rows = edgar_client.statements(sym, freq, 6)
    if not rows:
        raise RuntimeError('empty statements')
    return rows


def unified_statements(sym, is_kr, freq):
    """통합 재무표 rows — KR=DART, US=EDGAR. freq='annual'|'quarter'. 최신순."""
    try:
        return _unified_cached(sym, is_kr, freq)
    except Exception:
        return []


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _kr_fund_q():
    """저장된 DART 분기 손익 (data/kr_fundamentals_q.parquet · CI/PC 가 DART 에서 적재).
    q=1~3 은 3개월치, q=4 는 **연간 합계**(Q4 = 연간 − 1~3Q)."""
    return pd.read_parquet('data/kr_fundamentals_q.parquet')


def kr_stored_statements(sym, freq, n=5):
    """DART 실시간이 막힌 서버용 폴백 — 저장된 DART 손익 3항목(매출·영업이익·순이익)으로 표를 세운다.
    2026-10-17: Streamlit Cloud 에서 DART 가 ConnectTimeout(해외 서버 차단으로 추정) → KR 재무표가 통째로 비었다.
    이 파일의 숫자는 공시와 대조했다(삼성전자 2Q26 매출 171.5조·영업익 89.5조, SK하이닉스 2Q26 순익 93.9조,
    에이피알 2Q26 매출 7,675억·영업익 1,906억 — 전부 일치). 반환: (rows 최신순, 갱신일)"""
    try:
        d = _kr_fund_q()
    except Exception:
        return [], None
    x = d[d.sym == sym]
    if x.empty:
        return [], None
    upd = str(x['updated'].max())
    by = {(int(r.year), int(r.q)): r for r in x.itertuples()}
    cols = ('revenue', 'op_income', 'net_income')
    # 대차 잔액(2026-10-19~ 네이버로 채움) — 흐름이 아니라 분기말 값이라 4Q 도 차감하지 않는다
    bal = tuple(c for c in ('assets', 'liabilities', 'equity') if c in x.columns)

    def _v(v):
        return None if v is None or pd.isna(v) else float(v)

    out = []
    for (yy, qq), r in by.items():
        _b = {c: _v(getattr(r, c)) for c in bal}
        if freq == 'annual':
            if qq == 4:
                out.append(((yy, 4), {'period': str(yy), **{c: _v(getattr(r, c)) for c in cols}, **_b}))
        elif qq in (1, 2, 3):
            out.append(((yy, qq), {'period': f'{yy}.{qq}Q', **{c: _v(getattr(r, c)) for c in cols}, **_b}))
        else:                                   # 4Q = 연간 − (1~3Q) — 셋 다 있을 때만
            parts = [by.get((yy, k)) for k in (1, 2, 3)]
            if all(p is not None for p in parts):
                row = {'period': f'{yy}.4Q', **_b}
                for c in cols:
                    a, ps = _v(getattr(r, c)), [_v(getattr(p, c)) for p in parts]
                    row[c] = (a - sum(ps)) if (a is not None and all(v is not None for v in ps)) else None
                out.append(((yy, 4), row))
    out.sort(key=lambda t: t[0], reverse=True)
    return [o[1] for o in out[:n]], upd


# ── 종목 분석 보강 데이터 (2026-10-19) ─────────────────────────────────
import stock_extras as _sx


def _yf_code(sym, is_kr):
    if not is_kr:
        return sym
    try:
        k = pd.read_csv('data/krx_listing_last.csv', dtype={'Code': str})
        mk = k.loc[k.Code == sym, 'Market']
        return f"{sym}.KQ" if (not mk.empty and 'KOSDAQ' in str(mk.iloc[0])) else f"{sym}.KS"
    except Exception:
        return f"{sym}.KS"


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _q_rows_long(sym, is_kr):
    """멀티플 밴드용 긴 분기 시계열. US=EDGAR 최대 60분기(XBRL 2009~) / KR=저장된 DART 손익 2017~(자본은 2021~ 연말·2025.2Q~ 분기)."""
    if is_kr:
        rows, _ = kr_stored_statements(sym, 'quarter', n=40)
        return rows, 'DART 분기 손익 + 네이버 대차(저장본)'
    import edgar_client
    return edgar_client.statements(sym, 'quarter', 60), 'SEC EDGAR 분기'


def _shares_now(sym, is_kr, info):
    try:
        if is_kr:
            k = pd.read_csv('data/krx_listing_last.csv', dtype={'Code': str})
            v = k.loc[k.Code == sym, 'Stocks']
            if not v.empty:
                return float(v.iloc[0])
        else:
            u = pd.read_csv('data/us_marketcap.csv')
            v = u.loc[u.Symbol == sym, 'shares']
            if not v.empty and pd.notna(v.iloc[0]):
                return float(v.iloc[0])
    except Exception:
        pass
    return float(info.get('sharesOutstanding') or 0) or None


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _earn_data(sym, is_kr):
    """실적 발표일·서프라이즈·컨센서스 추이 — yfinance. 실패는 빈 dict(캐시 안 됨 아님: 6시간)."""
    out = {}
    try:
        t = yf.Ticker(_yf_code(sym, is_kr))
        try:
            ed = t.get_earnings_dates(limit=12)
            if ed is not None and not ed.empty:
                ed = ed.reset_index()
                ed.columns = [str(c) for c in ed.columns]
                out['dates'] = ed
        except Exception:
            pass
        for k in ('eps_trend', 'eps_revisions'):
            try:
                v = getattr(t, k)
                if v is not None and not v.empty:
                    out[k] = v
            except Exception:
                pass
    except Exception:
        pass
    return out


@st.cache_data(ttl=12 * 3600, show_spinner=False, max_entries=48)
def _kr_results_dates(sym):
    """KR 실적 발표 이벤트(DART 잠정실적·정기보고서) — 성공만 캐시(실패는 예외)."""
    import dart_client
    dart_client.set_interactive(True)
    cc = dart_client.corp_map().get(sym)
    if not cc:
        raise LookupError('DART 회사코드 없음')
    return dart_client.results_dates(cc, days=500)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=48)
def _kr_cons_q(sym):
    """주간 저장한 분기 컨센서스(발표 직전 값) — results/consensus_q.json."""
    try:
        return (json.loads(Path('results/consensus_q.json').read_text(encoding='utf-8')) or {}).get(sym) or {}
    except Exception:
        return {}


def _kr_cons_hist(sym):
    rows = []
    try:
        with open('results/consensus_history.jsonl', encoding='utf-8') as f:
            for line in f:
                if f'"{sym}"' in line:
                    r = json.loads(line)
                    if r.get('sym') == sym:
                        rows.append(r)
    except Exception:
        pass
    return rows


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _kr_cons_live(sym):
    """오늘 컨센서스 한 점(네이버 wisereport · FnGuide 추정). 실패는 None — 화면은 저장된 스냅샷만 그린다."""
    try:
        import kr_fin_naver as _kfn
        c = _kfn.consensus(sym)
        return {k: float(v) for k, v in (c or {}).items() if v is not None} or None
    except Exception:
        return None


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _peer_rows(sym, is_kr, n=4):
    """2026-10-21 — 주석엔 '6시간 캐시'라 적혀 있었지만 데코레이터가 없었다. 화면을 다시 그릴 때마다
    (표 클릭·더블클릭 포함) 동종 4~5종의 분기 재무를 새로 읽어서 렉이 걸렸다."""
    ind, cands = _sx.peer_candidates(sym, is_kr, n)
    out = []
    for c in [{'sym': sym, 'name': None, 'mcap': None}] + cands:
        try:
            rows, _ = _q_rows_long(c['sym'], is_kr)
        except Exception:
            rows = []
        mc = c['mcap']
        if mc is None:
            try:
                if is_kr:
                    k = pd.read_csv('data/krx_listing_last.csv', dtype={'Code': str})
                    r = k[k.Code == sym]
                    mc, c['name'] = float(r.Marcap.iloc[0]), r.Name.iloc[0]
                else:
                    u = pd.read_csv('data/us_marketcap.csv')
                    r = u[u.Symbol == sym]
                    mc, c['name'] = float(r.marketcap.iloc[0]), r.Name.iloc[0]
            except Exception:
                mc = None
        try:                                   # 한 종목 재무가 비어도(조회 실패) 표 전체가 죽지 않게
            met = _sx.peer_metrics(mc, _sx.quarterly_frame(rows)) if mc else {}
        except Exception:
            met = {}
        out.append({'종목': c['name'] or c['sym'], '코드': c['sym'],
                    '시총($B)': cap_usd_b(mc, 'KR' if is_kr else 'US') if mc else None,
                    'PER(배)': met.get('PER'), 'PBR(배)': met.get('PBR'), 'PSR(배)': met.get('PSR'),
                    'ROE(%)': met.get('ROE'),
                    '매출성장(%)': met.get('매출성장'), '영업이익률(%)': met.get('영업이익률'),
                    '기준분기': met.get('기준분기')})
    return ind, out


@st.cache_data(ttl=24 * 3600, max_entries=48)
def full_close_history(sym, is_kr):
    """전체 상장 히스토리 종가 (월별 계절성 통계용, 차트 기간과 무관). FDR 1990~."""
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS', '').replace('.KQ', '') if is_kr else sym
        s = fdr.DataReader(code, '1990-01-01')['Close'].dropna()
        s.index = pd.to_datetime(s.index).tz_localize(None)
        return s if len(s) > 100 else None
    except Exception:
        return None


@st.cache_data(ttl=3 * 3600, max_entries=48)
def consensus_scenarios(sym, is_kr):
    """컨센서스 목표주가 BEAR/BASE/BULL + 선행 EPS/PER (yfinance, 불안정)."""
    try:
        yi = yf.Ticker(_yf_code(sym, is_kr)).info or {}
        return {'bear': yi.get('targetLowPrice'), 'base': yi.get('targetMeanPrice'),
                'bull': yi.get('targetHighPrice'), 'n': yi.get('numberOfAnalystOpinions'),
                'fwd_eps': yi.get('forwardEps'), 'fwd_pe': yi.get('forwardPE')}
    except Exception:
        return {}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=48)
def _seg_ai_get(sym, is_kr):
    """AI 부문 추출 — 성공본은 디스크(results/segments, 120일), 실패도 1시간은 기억(위젯 누를 때마다 재호출 방지)."""
    try:
        import segment_analysis as _sa
        return _sa.load_cached(sym, max_age_days=120) or _sa.analyze(sym, is_kr)
    except Exception as e:
        return {'_error': str(e)[:150]}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=48)
def _ai_summary_auto(sym, is_kr, name, fallback_text):
    """기업 개요 AI 요약 — 검색 즉시. 원천 문서(10-K) 날짜가 같으면 디스크 결과 재사용 → 보고서당 1회만 호출."""
    import json as _j
    p = Path('results/ai_summary') / f'{sym}.json'
    src_key = ''
    try:
        if not is_kr:
            import edgar_client as _E
            _f = _E.filings(sym, form='10-K', limit=1)
            src_key = _f[0]['date'] if _f else ''
        else:
            src_key = datetime.now().strftime('%Y-%m')
    except Exception:
        src_key = ''
    try:
        d = _j.loads(p.read_text(encoding='utf-8'))
        if d.get('src_key') == src_key and d.get('text'):
            return d
    except Exception:
        pass
    btxt = official_business_text(sym, is_kr)
    src = '10-K 공식 사업보고(Item 1~)' if btxt else '공식 사업설명(yfinance)'
    txt = ai_business_summary(name, btxt or fallback_text, src)
    out = {'text': txt, 'src': src, 'src_key': src_key, 'generated': datetime.now().isoformat(timespec='seconds')}
    if txt and not txt.startswith('('):          # '(…실패…)' 안내문은 저장하지 않는다
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(_j.dumps(out, ensure_ascii=False), encoding='utf-8')
        except Exception:
            pass
    return out


@st.cache_data(ttl=6 * 3600, show_spinner=False, max_entries=48)
def _seg_xbrl_cached(sym):
    import segment_xbrl
    r = segment_xbrl.latest(sym)
    if not r:
        raise RuntimeError('no segment xbrl')      # 빈 결과는 캐시하지 않는다
    return r


def _seg_xbrl(sym):
    try:
        return _seg_xbrl_cached(sym)
    except Exception:
        return None


def valuation_basis(sym, is_kr, mc, price, fest, info):
    """PER 기준 통일(2026-10-20 사용자 결정: TTM · 12MF 두 개).
    · TTM  = 시총 ÷ **최근 4개 분기 순이익 합**(공시 3개월치, 연속 4분기일 때만). 작년 연간이 아니다.
    · 12MF = 주가 ÷ 12개월 선행 EPS. 12MF EPS = 올해(FY0)E × 남은 회계연도 비율 + 내년(FY1)E × 나머지
      (증권사 '12개월 선행'의 표준 블렌드). yfinance 의 forwardPE 는 '다음 회계연도 EPS' 하나라 기준이 다르다.
    · PBR = 시총 ÷ 최근 분기말 자본, PSR = 시총 ÷ TTM 매출.
    무엇이든 계산 근거가 없으면 None — 다른 기준 값으로 메우지 않는다."""
    out = {}
    q = unified_statements(sym, is_kr, 'quarter') or []
    q4 = q[:4]

    def _qi(p):                                   # KR '2026.2Q' · US '2026-06'(분기 말월) → 분기 순번
        p = str(p)
        try:
            if 'Q' in p:
                return int(p[:4]) * 4 + int(p[5]) - 1
            return int(p[:4]) * 4 + (int(p[5:7]) - 1) // 3
        except Exception:
            return None
    _seq = [_qi(r.get('period')) for r in q4]
    if len(q4) == 4 and None not in _seq and all(_seq[i] - _seq[i + 1] == 1 for i in range(3)):
        out['ttm_label'] = f"{str(q4[-1]['period'])[:7]}~{str(q4[0]['period'])[:7]}"
        for k in ('net_income', 'revenue'):
            vs = [r.get(k) for r in q4]
            if all(v is not None for v in vs):
                out[f'ttm_{k}'] = float(sum(vs))
    for r in q:
        if r.get('equity'):
            out['equity'], out['equity_label'] = float(r['equity']), str(r['period'])[:7]
            break
    if mc:
        if (out.get('ttm_net_income') or 0) > 0:
            out['per_ttm'] = mc / out['ttm_net_income']
        if (out.get('ttm_revenue') or 0) > 0:
            out['psr_ttm'] = mc / out['ttm_revenue']
        if (out.get('equity') or 0) > 0:
            out['pbr'] = mc / out['equity']
        if price and out.get('ttm_net_income') is not None:
            out['eps_ttm'] = out['ttm_net_income'] / (mc / price)
    e0, e1 = fest.get('eps_0y'), fest.get('eps_1y')
    if e0 is not None and e1 is not None:
        import datetime as _dtm
        today = _dtm.date.today()
        fye = None
        try:
            if info.get('nextFiscalYearEnd'):
                fye = _dtm.date.fromtimestamp(int(info['nextFiscalYearEnd']))
        except Exception:
            fye = None
        if fye is None or fye <= today or (fye - today).days > 400:
            fye = _dtm.date(today.year, 12, 31)          # 12월 결산 가정(KR 대부분·US 다수)
        w = min(max((fye - today).days / 365.0, 0.0), 1.0)
        eps12 = w * float(e0) + (1 - w) * float(e1)
        out['eps_12mf'], out['w_fy0'], out['fy0_end'] = eps12, w, fye
        if price and eps12 > 0:
            out['per_12mf'] = price / eps12
    return out


@st.cache_data(ttl=6 * 3600, max_entries=48)
def _fwd_est_cached(sym, is_kr):
    """올해(0y)/내년(+1y) + 이번분기(0q)/다음분기(+1q) 컨센서스 — 매출·EPS·순이익(EPS×주식수).
    yfinance의 revenue_estimate/earnings_estimate는 연간·분기 행이 같은 표에 같이 들어있음
    (인덱스 '0y'/'+1y'/'0q'/'+1q') — 분기 행은 기존엔 안 읽고 버려지고 있었음. 빈 결과는 캐시 안 함."""
    t = yf.Ticker(_yf_code(sym, is_kr))
    out = {}
    _PERIODS = (('0y', '0y'), ('1y', '+1y'), ('0q', '0q'), ('1q', '+1q'))
    try:
        re_ = t.revenue_estimate
        if re_ is not None and not re_.empty:
            for lab, idx in _PERIODS:
                if idx in re_.index and pd.notna(re_.loc[idx, 'avg']):
                    out[f'revenue_{lab}'] = float(re_.loc[idx, 'avg'])
    except Exception:
        pass
    try:
        ee = t.earnings_estimate
        if ee is not None and not ee.empty:
            for lab, idx in _PERIODS:
                if idx in ee.index and pd.notna(ee.loc[idx, 'avg']):
                    out[f'eps_{lab}'] = float(ee.loc[idx, 'avg'])
    except Exception:
        pass
    try:
        sh = t.fast_info['shares']            # FastInfo는 .get이 없을 수 있어 인덱싱
        if sh:
            for lab, _ in _PERIODS:
                if out.get(f'eps_{lab}'):
                    out[f'net_income_{lab}'] = out[f'eps_{lab}'] * float(sh)
    except Exception:
        pass
    if not out:
        raise RuntimeError('no estimates')
    return out


@st.cache_data(ttl=6 * 3600, max_entries=48)
def _kr_naver_consensus_cached(sym):
    """KR 컨센서스 폴백 — 네이버 '기업실적분석' (E) 컬럼(증권사 추정 평균).
    yfinance에 없는 영업이익 추정까지 제공. 반환 단위: 원(EPS는 원 그대로).

    이 표엔 연간 (E) 다음에 분기 (E)도 같이 들어있는데(예: ...2025.12, 2026.03, 2026.06(E))
    기존엔 연간 구간만 읽고 분기 구간은 그냥 버려지고 있었음 — 실측(005930)으로 확인.
    분기 (E)는 대개 가장 가까운 미래분기 1개만 나옴 → 0q(이번), 그 다음 것이 있으면 1q(다음).

    2026-10-25: 표 수집·헤더 해석(이 분기 (E) 처리 포함)을 naver_main_table로 통합
    (consensus_snapshot.py·canslim_run.py와 공유) — 이 함수의 로직이 셋 중 가장
    완전해서 naver_main_table.fetch()의 기준이 됐다."""
    import naver_main_table as nmt
    tb = nmt.fetch(sym)
    if tb is None:
        raise RuntimeError('no table')
    if not tb['emap']:
        raise RuntimeError('no E cols')

    out = {}
    for kw, key, mult in [('매출액', 'revenue', 1e8), ('영업이익률', 'opm', 0.01),
                          ('영업이익', 'op_income', 1e8),
                          ('당기순이익', 'net_income', 1e8), ('ROE', 'roe', 0.01),
                          ('부채비율', 'debt_ratio', 0.01), ('EPS', 'eps', 1.0),
                          ('PER', 'per_dir', 1.0), ('PBR', 'pbr_dir', 1.0)]:
        vals = nmt.row(tb, kw)
        if vals is None:
            continue
        for i, lab in tb['emap'].items():
            if i < len(vals):
                v = nmt.num(vals[i])
                if v is not None:
                    out[f'{key}_{lab}'] = v * mult
    if not out:
        raise RuntimeError('empty')
    return out


def forward_estimates(sym, is_kr):
    """올해E/내년E 컨센서스 — US=yfinance. KR=FnGuide(wisereport) 1차→yfinance→네이버 메인표.

    2026-10-25: '컨센서스 추이' 패널(_kr_cons_live)은 FnGuide를 쓰는데 이 함수(밸류에이션
    12MF EPS 입력)는 yfinance를 1차로 썼다 — 한국 소형주는 yfinance 커버리지가 약해
    같은 화면 안에서 같은 종목의 EPS 추정치가 서로 다르게 보일 수 있었다(사용자 지적).
    두 패널이 같은 1차 소스를 보도록 KR은 FnGuide를 먼저 쓴다."""
    out = {}
    if is_kr:
        try:
            import kr_fin_naver as _kfn
            c = _kfn.consensus(sym) or {}
            for lab in ('0y', '1y'):
                if c.get(f'eps_{lab}') is not None:
                    out[f'eps_{lab}'] = c[f'eps_{lab}']
                if c.get(f'op_{lab}') is not None:
                    out[f'op_income_{lab}'] = c[f'op_{lab}']
        except Exception:
            pass
    try:
        for k, v in _fwd_est_cached(sym, is_kr).items():
            out.setdefault(k, v)
    except Exception:
        pass
    if is_kr:
        try:
            for k, v in _kr_naver_consensus_cached(sym).items():
                out.setdefault(k, v)      # FnGuide·yfinance 둘 다 없는 항목만 네이버 메인표로 보충
        except Exception:
            pass
    return out


@st.cache_data(ttl=12 * 3600, max_entries=48)
def company_profile(sym, is_kr):
    """기업 개요: 사업설명·경영진·홈페이지·공식공시 링크(EDGAR/DART/Form4)."""
    out = {'summary': None, 'officers': [], 'website': None,
           'edgar_url': None, 'form4_url': None, 'dart_url': None}
    try:
        yi = yf.Ticker(_yf_code(sym, is_kr)).info or {}
        out['summary'] = yi.get('longBusinessSummary')
        out['website'] = yi.get('website')
        out['officers'] = [{'name': o.get('name'), 'title': o.get('title')}
                           for o in (yi.get('companyOfficers') or [])[:6] if o.get('name')]
    except Exception:
        pass
    try:
        if is_kr:
            import dart_client
            if dart_client.corp_map().get(sym):
                out['dart_url'] = f"https://dart.fss.or.kr/dsab007/main.do?textCrpNm={sym}"
        else:
            import edgar_client
            cik = edgar_client.cik_map().get(sym.upper())
            if cik:
                out['edgar_url'] = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                                    f"&CIK={cik}&type=10-K&dateb=&owner=include&count=20")
                out['form4_url'] = (f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                                    f"&CIK={cik}&type=4&dateb=&owner=include&count=40")
    except Exception:
        pass
    return out


@st.cache_data(ttl=24 * 3600, max_entries=48)
def official_business_text(sym, is_kr):
    """공식 사업 텍스트 — US: 최신 10-K(Item 1 사업 + Item 7 MD&A), KR: DART 사업보고서 원문.
    홈페이지 스크래핑 대신 공식 제출문서 사용 (정확·안정)."""
    try:
        if is_kr:
            import dart_client
            cc = dart_client.corp_map().get(sym)
            if cc:
                return dart_client.business_text(cc, max_chars=80000)
        else:
            import re as _re
            import edgar_client
            fl = edgar_client.filings(sym, form='10-K', limit=1)
            if fl:
                html = edgar_client._get(fl[0]['url']).text
                txt = _re.sub(r'<[^>]+>', ' ', html)
                txt = _re.sub(r'&[a-zA-Z#0-9]+;', ' ', txt)
                txt = _re.sub(r'\s+', ' ', txt)
                m1 = _re.search(r'Item\s*1\s*[.:]?\s*Business', txt, _re.I)
                body = txt[m1.start():] if m1 else txt
                # 사업(Item 1~) 60k + 경영진 분석(MD&A, Item 7~) 25k 결합
                m7 = _re.search(r"Item\s*7\s*[.:]?\s*Management[’'`]?s?\s*Discussion", body, _re.I)
                if m7:
                    combined = body[:60000] + "\n\n[MD&A 경영진 분석]\n" + body[m7.start():m7.start() + 25000]
                else:
                    combined = body[:80000]
                if len(combined) > 3000:
                    return combined
    except Exception:
        pass
    return None


def ai_business_summary(name, text, src='공식 사업설명'):
    """Gemini로 사업·비전·마스터플랜 요약. 실패 시 안내문."""
    try:
        import config
        from google import genai
        key = getattr(config, 'GEMINI_KEY', '') or ''
        if not key:                       # Streamlit Secrets 직접 조회 (재시작 없이 반영)
            try:
                key = st.secrets.get('GEMINI_KEY', '')
            except Exception:
                key = ''
        if not key:
            return "(Gemini 키 미설정 — Streamlit Secrets에 GEMINI_KEY 추가 필요)"
        if not text:
            return "(사업 설명 데이터 없음)"
        prompt = (
            f"너는 20년차 기업분석 애널리스트다. 아래는 '{name}'의 {src} 원문이다. "
            "펀드매니저에게 브리핑하듯 한국어로 요약하라.\n\n"
            "형식 (각 소제목 굵게, 개조식 불릿, 문서의 구체적 숫자·제품명·고객명을 반드시 인용):\n"
            "**🎯 한 줄 정의**: 이 회사를 한 문장으로.\n"
            "**🏭 사업 구조**: 세그먼트별로 무엇을 팔아 돈을 버나 — 부문명·주요제품·매출 비중(문서에 있으면 숫자로) (3~5줄)\n"
            "**🧭 비전·마스터플랜**: 경영진이 공식적으로 밝힌 장기 방향·투자 계획·로드맵 (2~4줄)\n"
            "**🚀 성장 동력**: 향후 실적을 끌어올릴 구체적 요인 — 신제품·증설·신시장 (2~4줄)\n"
            "**🏰 경쟁·해자**: 경쟁 구도와 이 회사의 우위(기술·점유율·전환비용) (2~3줄)\n"
            "**⚠️ 핵심 리스크**: 문서에 명시된 리스크 중 투자판단에 중요한 것 (2~3줄)\n"
            "**✅ 체크포인트**: 투자자가 다음 분기에 확인해야 할 지표·이벤트 2~3개\n\n"
            "규칙: 과장·추측 금지, 문서에 있는 사실만. 일반론('경쟁이 치열함' 같은 말) 금지 — "
            "구체적 이름과 숫자로. 문서에 없는 항목은 '문서에 언급 없음'으로.\n\n"
            + str(text)[:100000])
        client = genai.Client(api_key=key)   # 임시객체로 쓰면 요청 중 GC로 닫힘("client has been closed")
        import time as _t
        last = None
        for _model in ['gemini-2.5-flash', 'gemini-2.5-flash', 'gemini-2.5-flash-lite']:
            try:
                r = client.models.generate_content(model=_model, contents=prompt)
                return (r.text or '').strip() or "(요약 생성 실패)"
            except Exception as _e:          # 503(과부하) 등 → 재시도/경량모델 폴백
                last = _e
                _t.sleep(2)
        return f"(AI 요약 실패 — Gemini 서버 혼잡. 잠시 후 다시 눌러줘. [{str(last)[:60]}])"
    except Exception as e:
        return f"(AI 요약 실패: {str(e)[:80]})"


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _name_index():
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


def _resolve_symbol(q: str):
    """입력 → (확정 코드 or None, 후보 목록[(코드, 표시명)]). 코드·티커는 그대로 통과."""
    q = (q or '').strip()
    if not q:
        return None, []
    up = q.upper()
    base = up.replace('.KS', '').replace('.KQ', '')
    if (len(base) == 6 and base[:5].isdigit()) or (up.isascii() and up.replace('.', '').replace('-', '').isalnum()
                                                    and len(up) <= 6 and not any('가' <= ch <= '힣' for ch in q)):
        # 영문 6자 이하는 티커로 본다 — 단, 그런 티커가 없고 이름으로 맞는 게 있으면 아래로
        idx = _name_index()
        if any(c == base for c, _, _, _ in idx) or (len(base) == 6 and base[:5].isdigit()):
            return base if len(base) == 6 and base[:5].isdigit() else up, []
    key = q.replace(' ', '').casefold()
    exact, part = [], []
    for c, n, m, cap in _name_index():
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


@st.fragment
def _tab_analysis():
    # 2026-10-15 — 이 탭의 조작(검색·토글·버튼)은 이 탭만 다시 그린다. 예전에는 검색 한 번에
    #   앱 전체(전 탭·표 수십 개)가 다시 돌아 모바일에서 화면이 한참 회색으로 멈춰 있었다.
    _tui.begin_run(st)       # 표 필터 키 순번을 프래그먼트 실행마다 0부터 — 키가 바뀌면 필터가 풀린다
    with guard('종목 분석'):
        st.header("🔍 종목 분석")
        st.caption("종목명 또는 코드 — KR: 삼성전자 · 005930  |  US: TSLA · Tesla")

        # 2026-10-15 — 모바일에서 검색이 안 되던 문제. 키보드의 '이동/검색'(Enter)은 입력칸만
        #   반영하고 '분석' 버튼은 안 눌린 상태라 아무 일도 없었다. 폼으로 묶어 Enter 도 제출로 친다
        #   (폼 안에서는 입력 중 재실행이 없어, iOS 에서 첫 탭이 입력칸 반영에 먹히는 일도 없다).
        with st.form("sym8_form", border=False, enter_to_submit=True):
            c_in, c_btn, _csp = st.columns([2.2, 0.9, 4.9])   # 필요한 만큼만 좁게 (#3)
            with c_in:
                sym8 = st.text_input("종목명 또는 코드", placeholder="삼성전자 / 005930 / TSLA",
                                     label_visibility="collapsed", key="sym8")
            with c_btn:
                go8 = st.form_submit_button("분석", use_container_width=True)

        # 분석 종목을 세션에 고정 — 라디오/슬라이더 조작(rerun)에도 분석 화면 유지 (#7)
        if sym8 and go8:
            _code, _cands = _resolve_symbol(sym8)
            if _code:
                st.session_state['analyze_sym'] = _code
                st.session_state.pop('sym8_cands', None)
            else:
                st.session_state['sym8_cands'] = _cands
        # 봇 감시 목록(링크로 받은 것) — 한 번 눌러 바로 분석
        _bw = st.session_state.get('bot_watch') or []
        if _bw:
            _bwk = f"bw_{','.join(_bw)}"

            def _bw_go(k=_bwk):                       # 바뀐 순간에만 이동(검색으로 다른 종목을 고르면 그쪽을 존중)
                v = st.session_state.get(k)
                if v:
                    st.session_state['analyze_sym'] = v
                    st.session_state.pop('sym8_cands', None)
            st.pills("🤖 봇 감시 목록", _bw, selection_mode='single', default=None, key=_bwk, on_change=_bw_go)
        _cands = st.session_state.get('sym8_cands')
        if _cands is not None:
            if not _cands:
                st.warning(f"'{sym8}' 와 맞는 종목이 없습니다. 이름 일부나 종목코드로 다시 찾아보세요.")
            else:
                _cc1, _cc2, _ = st.columns([3.1, 0.9, 4.0])
                _pick = _cc1.selectbox(f"후보 {len(_cands)}개 (시총 큰 순)", _cands,
                                       format_func=lambda x: x[1], key="sym8_pick")
                if _cc2.button("이 종목", key="sym8_go", use_container_width=True):
                    st.session_state['analyze_sym'] = _pick[0]
                    st.session_state.pop('sym8_cands', None)
                    st.rerun(scope="fragment")
        _asym = st.session_state.get('analyze_sym')

        if _asym:
            sym8_clean = _asym
            with st.spinner(f"{sym8_clean} 데이터 조회..."):
                # 최대한 길게 요청 — US(FDR)는 상장일까지 실제로 나옴(AAPL 1980~ 확인).
                # KR은 무료소스(FDR/pykrx 비로그인) 자체가 최근 ~3000거래일(~12y)로 캡핑돼 있어
                # 20y를 요청해도 KR은 그 한계까지만 나옴 — 아래 캡션에서 사실대로 안내.
                hist, info, earn, insid, fin_est = fetch_stock_data(sym8_clean, 365 * 20)

            _n_bad_bar = 0
            if hist is not None and not hist.empty:      # 캐시에 남은 옛 결과에도 같은 정리(위 수집 단계와 이중 안전)
                _okb = pd.to_numeric(hist['Close'], errors='coerce') > 0
                _n_bad_bar = int((~_okb).sum())
                hist = hist[_okb]
            if hist is None or hist.empty:
                st.error(f"데이터 없음 ({sym8_clean}). 종목코드 확인 — KR: 005930 · US: TSLA")
            else:
                price_now = hist['Close'].iloc[-1]
                price_prev= hist['Close'].iloc[-2] if len(hist) > 1 else price_now
                chg_pct   = (price_now / price_prev - 1) * 100

                mc = info.get('marketCap', 0) or 0
                # 2026-10-17 — KR 시총(원)을 달러 기호로 찍고 있었다(삼성전자 '$1403319.4B'). 통화대로 표기.
                if len(sym8_clean) == 6 and sym8_clean[:5].isdigit():
                    _mcs = (f"₩{mc/1e12:,.1f}조" if mc >= 1e12 else f"₩{mc/1e8:,.0f}억") if mc else "-"
                else:
                    _mcs = (f"${mc/1e9:,.1f}B" if mc >= 1e9 else f"${mc/1e6:,.0f}M") if mc else "-"
                # ── 머리 카드 (2026-10-19 · 디자인 시안 C) — 종목·현재가·신호 상태를 한 장에
                import html as _h
                _is_kr0 = len(sym8_clean) == 6 and sym8_clean[:5].isdigit()
                _px_s = f"₩{price_now:,.0f}" if _is_kr0 else f"${price_now:,.2f}"
                _ah0 = None if _is_kr0 else _sx.accel_history(sym8_clean)
                if _is_kr0:
                    # 2026-10-21 — 'KR 미운영' 대신 분기 영업이익 추이(흑자전환·적자 축소·가속). 주간 진입 신호는
                    #   한국에서 백테스트로 기각돼(원칙 v1.2) 신호로 쓰지 않는다 — 상태만 보인다.
                    try:
                        _et0 = _sx.earnings_trend(_q_rows_long(sym8_clean, True)[0], is_kr=True)
                    except Exception:
                        _et0 = {'state': '판정 불가', 'tone': 'na'}
                    _l0 = _et0.get('last') or {}
                    _sig_b = f"분기 이익 · {_et0['state']}"
                    _sig_s = (f"{_l0.get('분기')} 기준 · 이익 수준 {_et0.get('level', '-')} · 최근 8분기 중 가속 {_et0.get('acc_8q', 0)}회"
                              if _l0 else "분기 손익 데이터 부족")
                    _dot = {'good': '#16A34A', 'mid': '#F59E0B', 'bad': '#DC2626'}.get(_et0.get('tone'), '#6B7280')
                elif _ah0 and _ah0['rows']:
                    _r0 = _ah0['rows'][0]
                    _recent = (pd.Timestamp.today() - pd.Timestamp(_r0['주차'])).days <= 7 * 52
                    _sig_b = "이익 가속 신호 · 최근 1년 내" if _recent else "이익 가속 신호 · 1년 넘음"
                    _sig_s = f"{_r0['주차']} · 그 해 {_r0['회차']}회차"
                    _dot = "#16A34A" if _recent else "#9CA3AF"
                else:
                    _sig_b, _sig_s, _dot = "이익 가속 신호 없음", "2018년 이후 진입 규칙에 걸린 적 없음", "#6B7280"
                # 요약 칩(2026-10-20) — 이 종목이 지금 '어디쯤'인지 한 줄로. 전부 규칙 계산(가격·애널 컨센서스), 추정 없음
                # 2026-10-21 — '52주 위치 72%'(저점 0·고점 100 사이 어디인가)는 뜻이 안 읽혀서 뺐다.
                #   대신 저점 대비 상승률과 '신고가 후 n주'를 둔다 — 같은 정보를 바로 읽히는 말로.
                _chips = []
                _ttp = _sx.trend_template(hist['Close'], hist.get('High'), hist.get('Low'))
                try:
                    _hi52 = float(hist['High'].tail(252).max()); _lo52 = float(hist['Low'].tail(252).min())
                    _dd = (price_now / _hi52 - 1) * 100
                    _wk = _ttp.get('weeks_since_high')
                    _chips.append(('neg' if _dd < -20 else '', '52주 고점 대비', f"{_dd:+.1f}%"
                                   + (f" · 신고가 후 {_wk}주" if _wk else " · 이번 주 신고가" if _wk == 0 else '')))
                    if _lo52 > 0:
                        _chips.append(('pos', '52주 저점 대비', f"{(price_now / _lo52 - 1) * 100:+.0f}%"))
                    if len(hist) > 252:
                        _r1 = (price_now / float(hist['Close'].iloc[-253]) - 1) * 100
                        _chips.append(('pos' if _r1 >= 0 else 'neg', '1년 수익률', f"{_r1:+.1f}%"))
                    if len(hist) >= 200:
                        _m200 = float(hist['Close'].tail(200).mean())
                        _g = (price_now / _m200 - 1) * 100
                        _chips.append(('pos' if _g >= 0 else 'neg', '200일선', f"{'위' if _g >= 0 else '아래'} {_g:+.1f}%"))
                    _tp, _na = info.get('targetMeanPrice'), info.get('numberOfAnalystOpinions')
                    if _tp:
                        _u = (float(_tp) / price_now - 1) * 100
                        _chips.append(('pos' if _u >= 0 else 'neg', f"목표가 여력{f'({_na}명)' if _na else ''}", f"{_u:+.1f}%"))
                except Exception:
                    pass
                _chip_h = ''.join(f'<span class="chip {c}">{_h.escape(k)} <b>{_h.escape(v)}</b></span>'
                                  for c, k, v in _chips)
                if not _is_kr0 and re.fullmatch(r'[A-Z]{1,10}', sym8_clean):   # 봇은 미국(SEC) 종목만 감시
                    _chip_h += (f'<a class="chip bot" href="https://t.me/buza_alarm_bot?start=watch_{sym8_clean}" '
                                f'target="_blank">🤖 봇에서 공시·뉴스 감시</a>')
                _ind = str(info.get('industry') or info.get('sector') or '')
                _hero_slot = st.empty()

                def _hero(desc):
                    # 2026-10-21 — 설명은 한글로: AI 요약의 '한 줄 정의'를 쓴다(yfinance 원문은 영어).
                    #   AI 가 실패했을 때만 영문 원문 첫 문장을, 영문이라고 밝히고 보인다.
                    _hero_slot.markdown(f"""<div class="mo-hero">
<div class="t"><span class="k">{_h.escape(' · '.join(x for x in (sym8_clean, _ind, '시총 ' + _mcs) if x and x != '-'))}</span>
<span class="n">{_h.escape(str(info.get('longName', sym8_clean))[:40])}</span>
{f'<span class="d">{_h.escape(desc)}</span>' if desc else ''}</div>
<div class="p"><span class="pv">{_px_s}</span><span class="{'up' if chg_pct >= 0 else 'dn'}">{chg_pct:+.2f}% 오늘</span></div>
<div class="s"><span class="dot" style="background:{_dot}"></span><div><b>{_sig_b}</b><span>{_h.escape(_sig_s)}</span></div></div>
{f'<div class="chips">{_chip_h}</div>' if _chip_h else ''}
</div>""", unsafe_allow_html=True)
                _hero('기업 설명 요약 중…')

                # 2026-09-10: 우선주(00088K) 대응 — 앞 5자리로 판정
                is_kr_sym = len(sym8_clean) == 6 and sym8_clean[:5].isdigit()
                price_unit = '₩' if is_kr_sym else '$'

                # ── 화면 순서 (2026-10-19 재배치) ───────────────────────────────
                # 코드는 데이터 의존 순서대로 돌고, **보이는 순서는 이 컨테이너 순서**가 정한다.
                # 판단 → 가격·위험 → 실적 → 구조 → 가치 → 근거 상세 → 원표 → 개요 → 참고 통계.
                _SEC = {_k: st.container() for _k in ('summary', 'plan', 'price', 'flow', 'earn', 'seg', 'val',
                                                     'canslim', 'fin', 'profile', 'ref')}
                if IS_MOBILE:
                    # 2026-10-21 — 폰에서 종목 하나가 세로 2만 px(손가락 24번)였다. 요약 판단만 펼쳐 두고 나머지는 탭으로.
                    #   (펼침 상자 안에 펼침 상자를 넣을 수 없어 '접기' 대신 탭 — 섹션 안에 이미 펼침 상자가 있다)
                    _SEC = {'summary': _SEC['summary'], 'plan': _SEC['plan']}   # 매매 판단도 탭 밖에(핵심)
                    _mtabs = st.tabs(["📈 가격", "💵 실적", "🏭 구조", "⚖️ 가치", "📊 재무", "🏢 개요", "📆 참고·내부자"])
                    for _tb, _keys in zip(_mtabs, (('price',), ('flow', 'earn'), ('seg',), ('val', 'canslim'),
                                                   ('fin',), ('profile',), ('ref',))):
                        with _tb:
                            for _k in _keys:
                                _SEC[_k] = st.container()
                with _SEC['profile']:
                    st.divider()
                    # ── 🏢 기업 개요 · IR · 공식 공시 (item 7) ──
                    _prof = company_profile(sym8_clean, is_kr_sym)
                    st.subheader("🏢 기업 개요 · IR")
                    _lnk = []
                    if _prof.get('website'):
                        _lnk.append(f"[🌐 홈페이지/IR]({_prof['website']})")
                    if _prof.get('edgar_url'):
                        _lnk.append(f"[📄 EDGAR 10-K]({_prof['edgar_url']})")
                    if _prof.get('form4_url'):
                        _lnk.append(f"[👤 EDGAR Form4(내부자)]({_prof['form4_url']})")
                    if _prof.get('dart_url'):
                        _lnk.append(f"[📄 DART 공시]({_prof['dart_url']})")
                    if _lnk:
                        st.markdown("**공식 공시·IR**: " + "  ·  ".join(_lnk))
                    # 2026-10-20: 버튼 없이 검색 즉시. 같은 10-K 면 저장된 요약을 재사용(보고서당 AI 1회).
                    with st.spinner("공식 문서(10-K/사업설명)에서 사업·비전 요약 중…"):
                        _ais = _ai_summary_auto(sym8_clean, is_kr_sym, info.get('longName', sym8_clean),
                                                _prof.get('summary'))
                    _one = ''
                    # '**🎯 한 줄 정의**: …' 와 '### 🎯 한 줄 정의\n\n…'(제목 다음 줄) 두 형식 모두 — 후자를 놓쳐 영문이 떴다(10-21 실화면)
                    _m1 = re.search(r'한 줄 정의[*:：\s]*([^\s#*][^\n]*)', str(_ais.get('text') or ''))
                    if _m1:
                        _one = re.sub(r'\*\*|__', '', _m1.group(1)).strip()
                    if not _one:
                        _en = str(info.get('longBusinessSummary') or '').strip()
                        if _en:   # 첫 문장 — 'Inc.'·'Corp.' 의 마침표에서 자르지 않는다
                            _en = re.split(r'(?<!Inc)(?<!Corp)(?<!Co)(?<!Ltd)(?<!Mr)(?<!U\.S)\.\s+(?=[A-Z])', _en)[0].rstrip('.') + '.'
                            _one = '(영문 원문 · 한글 요약 실패) ' + (_en if len(_en) <= 200 else _en[:197].rsplit(' ', 1)[0] + '…')
                    _hero(_one if len(_one) <= 240 else _one[:237] + '…')
                    with st.container(border=True):
                        st.markdown(_ais['text'])
                    st.caption(f"🤖 AI 요약 · 원천: {_ais['src']}{(' (' + _ais['src_key'] + ' 공시)') if _ais.get('src_key') and not is_kr_sym else ''}"
                               f" · 생성 {str(_ais.get('generated', ''))[:10]}. 문장은 AI 가 원문에서 요약한 것 — "
                               "숫자 판단은 위·아래 공시 표(재무제표·부문 XBRL)를 기준으로 할 것.")
                    st.divider()

                with _SEC['fin']:
                    # ── 📊 공식 재무제표 통합표 (연도 가로 × 3표 세로 · 연간/분기 토글) ──
                    # 2026-10-17 — (구) `if _off:` 로 감싸서, 연간 요약(_off · DART 8~12건)이 실패하면 통합표가
                    #   이유 표시도 없이 통째로 사라졌다. 통합표는 자기 데이터로 서고, _off 는 아래 스코어카드 직전에 받는다.
                    _mc = info.get('marketCap') or 0
                    if True:
                        _osrc = 'DART 전자공시' if is_kr_sym else 'SEC EDGAR'
                        st.subheader(f"📊 재무제표 ({'KR 공시' if is_kr_sym else 'SEC EDGAR'})")   # 실제 출처는 표 아래 캡션

                        def _amt(v):
                            if v is None:
                                return '-'
                            if is_kr_sym:
                                return f"{v/1e12:.1f}조" if abs(v) >= 1e12 else f"{v/1e8:,.0f}억"
                            return f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:,.0f}M"

                        def _pct(v):
                            return f"{v*100:.1f}%" if isinstance(v, (int, float)) else '-'


                        _freq = st.radio("기준", ["연간", "분기"], horizontal=True, key=f"fin_freq_{sym8_clean}")
                        # 2026-10-21 — 폰(390px)에서는 13열 표가 3~4열만 보였다 → 최근 3개 기간만, 필요하면 펼친다
                        _fin_all = (not IS_MOBILE) or st.toggle("전체 기간 보기", value=False, key=f"fin_all_{sym8_clean}")
                        _stm = unified_statements(sym8_clean, is_kr_sym, 'annual' if _freq == "연간" else 'quarter')
                        _stored = None                 # 저장본으로 대신 그렸으면 그 갱신일
                        if not _stm and is_kr_sym:
                            _stm, _stored = kr_stored_statements(sym8_clean, 'annual' if _freq == "연간" else 'quarter')
                            if _stm:
                                st.info(f"DART 실시간 조회가 이 서버(해외)에서 막혀 있어 **저장된 DART 공시 손익**"
                                        f"(매출·영업이익·순이익, 갱신 {_stored})으로 표시합니다. "
                                        "대차대조표·현금흐름표는 저장본에 없어 생략합니다.")
                        _via_naver = bool(_stm) and _stm[0].get('_src') == 'naver'
                        if _via_naver:
                            # 같은 숫자를 두 소스로 맞춰 본다 — 저장된 DART(공시 원본)와 겹치는 기간·손익 3항목
                            _dart_rows, _ = kr_stored_statements(sym8_clean, 'annual' if _freq == "연간" else 'quarter', 8)
                            _dmap = {r['period']: r for r in _dart_rows}
                            _n_ok, _bad = 0, []
                            for _r in _stm:
                                _d = _dmap.get(_r['period'])
                                if not _d:
                                    continue
                                for _k, _kn in (('revenue', '매출'), ('op_income', '영업이익'), ('net_income', '순이익')):
                                    _a, _b = _r.get(_k), _d.get(_k)
                                    if _a is None or _b is None:
                                        continue
                                    if abs(_a - _b) <= max(abs(_b) * 0.005, 1e8):
                                        _n_ok += 1
                                    else:
                                        _bad.append(f"{_r['period']} {_kn} {_a/1e8:,.0f}억 vs DART {_b/1e8:,.0f}억")
                            st.caption("출처: **네이버 기업분석**(FnGuide 집계 · 영업이익=회사 발표 기준) — DART 가 이 서버(해외)에서 막혀 대신 씁니다. "
                                       + (f"저장된 DART 공시값과 대조: {_n_ok}건 일치" if _n_ok else "저장된 DART 값과 겹치는 기간 없음")
                                       + (f" · ⚠️ 불일치 {len(_bad)}건: " + " · ".join(_bad[:4]) if _bad else ""))
                        if _stm:
                            # 2026-10-17 — 분기 보기에서 PER·PSR·ROE 를 **한 분기 실적**으로 나누고 있었다
                            #   (삼성전자 2Q26 'PER 17.9x' — 실제 TTM 은 8x대). 분기는 최근 4개 분기 합(TTM)으로,
                            #   4개 분기가 연속으로 없으면 '-'. 연간 보기는 그 해 실적 그대로.
                            def _qidx(p):
                                p = str(p)
                                try:
                                    if 'Q' in p:                       # KR '2026.2Q'
                                        return int(p[:4]) * 4 + int(p[5]) - 1
                                    return int(p[:4]) * 4 + (int(p[5:7]) - 1) // 3   # US '2026-06'(회계분기 말월)
                                except Exception:
                                    return None

                            def _ttm(ix, key):
                                if ix + 4 > len(_stm):
                                    return None
                                win = _stm[ix:ix + 4]
                                qi = [_qidx(r['period']) for r in win]
                                vals = [r.get(key) for r in win]
                                if None in qi or any(qi[i] - qi[i + 1] != 1 for i in range(3)) or any(v is None for v in vals):
                                    return None
                                return float(sum(vals))

                            for _ix, _r in enumerate(_stm):
                                _rv = _r.get('revenue')
                                _r['gpm'] = (_r['gross'] / _rv) if (_r.get('gross') and _rv) else None
                                _r['opm'] = (_r['op_income'] / _rv) if (_r.get('op_income') and _rv) else None
                                _ni = _r.get('net_income') if _freq == "연간" else _ttm(_ix, 'net_income')
                                _r['ni_basis'] = _ni
                                _r['rev_basis'] = _rv if _freq == "연간" else _ttm(_ix, 'revenue')
                                _r['roe'] = (_ni / _r['equity']) if (_ni and _r.get('equity')) else None
                                _r['debt_ratio'] = (_r['liabilities'] / _r['equity']) if (_r.get('liabilities') and _r.get('equity')) else None
                            if not _fin_all:
                                _stm = _stm[:3]
                            _periods = [r['period'] for r in _stm]
                            _gl = "YoY" if _freq == "연간" else "QoQ"
                            _np = len(_stm)
                            # 증감 컬럼 헤더는 전부 'YoY'/'QoQ'로 보이게 (공백 패딩으로 중복 회피)
                            _dcols = [f'{_gl}(%){" " * _i}' for _i in range(_np - 1)]   # 마진·ROE 행은 %p 차이

                            def _delta(cur, prev, typ):
                                if typ == 'pct':
                                    return (f"{(cur-prev)*100:+.1f}%p"
                                            if (isinstance(cur, (int, float)) and isinstance(prev, (int, float))) else '-')
                                if cur is not None and prev:
                                    try:
                                        if prev < 0:
                                            return '흑전' if cur > 0 else '-'
                                        return f"{(cur/prev-1)*100:+.0f}%"
                                    except Exception:
                                        return '-'
                                return '-'

                            def _fmt_v(_v, _typ):
                                if _typ == 'pct':
                                    return _pct(_v)
                                if _typ == 'eps':                      # KR EPS 는 원 단위 정수
                                    return (f"{_v:,.0f}" if is_kr_sym else f"{_v:,.2f}") if isinstance(_v, (int, float)) else '-'
                                return _amt(_v)

                            _EST_LABELS = {
                                'annual':  (('내년E', '1y'), ('올해E', '0y')),
                                'quarter': (('다음분기E', '1q'), ('이번분기E', '0q')),
                            }

                            def _stmt_table(title, items, est=None, freq='annual'):
                                # 2026-10-21 — 칸 안의 단위('566.9조'·'13.1%'·'3.4x')를 걷어내고 **항목 이름에 단위**를 단다
                                #   (행마다 단위가 다른 표라 열 머리 대신 행 머리가 단위 자리). 금액 단위는 표마다 숫자 크기에 맞춰
                                #   조/억(US $B/$M) 중 하나 — 853000.0억 같은 0 행렬이 나오지 않게.
                                _est_pairs = _EST_LABELS[freq]
                                _ecols = [lab for lab, _ in _est_pairs] if est else []   # 미래→과거 방향 통일
                                _amts = [abs(_stm[i].get(it[1])) for it in items if it[2] in ('amt', 'flow') for i in range(_np)
                                         if isinstance(_stm[i].get(it[1]), (int, float)) and _stm[i].get(it[1])]
                                _med = float(np.median(_amts)) if _amts else 0
                                if is_kr_sym:
                                    _udiv, _ulab, _udp = (1e12, '조원', 1) if _med >= 1e12 else (1e8, '억원', 0)
                                else:
                                    _udiv, _ulab, _udp = (1e9, '$B', 2) if _med >= 1e9 else (1e6, '$M', 0)

                                def _lab_u(lab, typ):
                                    base, _, note = lab.partition(' (')
                                    note = note.rstrip(')')
                                    u = {'amt': _ulab, 'flow': _ulab, 'pct': '%', 'mult': '배', 'eps': '원' if is_kr_sym else '$'}[typ]
                                    return f"{base}({u}{', ' + note if note else ''})"

                                def _val(v, typ):
                                    if not isinstance(v, (int, float)) or v != v:
                                        return None
                                    if typ in ('amt', 'flow'):
                                        return v / _udiv
                                    if typ == 'pct':
                                        return v * 100
                                    return float(v)

                                def _dlt(cur, prev, typ):
                                    if not (isinstance(cur, (int, float)) and isinstance(prev, (int, float))):
                                        return None
                                    if typ == 'pct':
                                        return (cur - prev) * 100
                                    if typ == 'flow':
                                        # 투자·재무활동·Capex 는 원래 마이너스(유출)인 흐름 — '적자 확대'가 아니다(10-21 TSLA 실화면).
                                        #   규모 증감률만, 부호가 바뀌면 '유입↔유출'.
                                        if not prev:
                                            return None
                                        if (cur < 0) != (prev < 0):
                                            return '유입 전환' if cur > 0 else '유출 전환'
                                        return (abs(cur) / abs(prev) - 1) * 100
                                    if prev < 0:
                                        return '흑전' if cur > 0 else ('적자 축소' if cur > prev else '적자 확대')
                                    if prev > 0 and cur < 0:
                                        return '적전'
                                    return (cur / prev - 1) * 100 if prev else None

                                _rows, _types = [], []
                                for _it in items:
                                    _lab, _key, _typ = _it[0], _it[1], _it[2]
                                    _dk = _it[3] if len(_it) > 3 else None   # 직접 추정키(네이버 PER/PBR E 등)
                                    _row = {'항목': _lab_u(_lab, _typ)}
                                    if est:                       # 컨센서스(연간=내년/올해, 분기=다음/이번) — mult면 Fwd 멀티플
                                        for _el, _sfx in _est_pairs:
                                            if _dk and est.get(f'{_dk}_{_sfx}') is not None:
                                                _dv = est[f'{_dk}_{_sfx}']
                                                _row[_el] = float(_dv) if _typ == 'mult' else _val(_dv, _typ)
                                                continue
                                            _ek = {'ni_basis': 'net_income', 'rev_basis': 'revenue'}.get(_key, _key)
                                            _ev = est.get(f'{_ek}_{_sfx}')
                                            if _typ == 'mult':
                                                # 분기 추정치 1개로 시총을 나누면 4배 부풀려진 배수가 된다 → 분기 E 는 '-'
                                                _row[_el] = (_mc / _ev if (_mc and _ev and _ev > 0 and freq == 'annual') else None)
                                            else:
                                                _row[_el] = _val(_ev, _typ) if _ev else None
                                    for _ix in range(_np):
                                        _v = _stm[_ix].get(_key)
                                        if _typ == 'mult':        # 현재 시총 ÷ 각 기간 실적 (#4)
                                            _row[_periods[_ix]] = (_mc / _v if (_mc and isinstance(_v, (int, float)) and _v > 0) else None)
                                            if _ix < _np - 1:
                                                _row[_dcols[_ix]] = None
                                        else:
                                            _row[_periods[_ix]] = _val(_v, _typ)
                                            if _ix < _np - 1:    # 사이사이 증감
                                                _row[_dcols[_ix]] = _dlt(_v, _stm[_ix + 1].get(_key), _typ)
                                    _rows.append(_row)
                                    _types.append(_typ)
                                _df = pd.DataFrame(_rows)
                                # 컬럼 순서: 항목, [내년E, 올해E,] p0, YoY, p1, YoY, ..., pN
                                _order = ['항목'] + _ecols
                                for _ix in range(_np):
                                    _order.append(_periods[_ix])
                                    if _ix < _np - 1:
                                        _order.append(_dcols[_ix])
                                _df = _df[_order]
                                _numc = _ecols + list(_periods)
                                for _c in _numc:
                                    _df[_c] = pd.to_numeric(_df[_c], errors='coerce')
                                _dnum = [abs(v) for c in _dcols for v in _df[c].tolist() if isinstance(v, (int, float)) and v == v]
                                _dsc = float(np.quantile(_dnum, .9)) if len(_dnum) >= 5 else (max(_dnum) if _dnum else 1.0)
                                _WS = {'흑전': 1, '적자 축소': 1, '적전': -1, '적자 확대': -1}

                                def _cdl(v):
                                    if isinstance(v, str):
                                        return _tui._bg(_WS.get(v, 0) * (_dsc or 1), _dsc or 1)
                                    if isinstance(v, (int, float)) and v == v:
                                        return _tui._bg(float(v), _dsc or 1)
                                    return ''
                                # 증감 열은 숫자와 '흑전·적자 축소' 글자가 섞여 Arrow 가 한 번 실패한다 → 색은 숫자로 먼저 칠하고
                                #   표시는 미리 만든 문자열로(재무제표는 행마다 단위가 달라 열 정렬이 뜻이 없다).
                                _dcss = pd.DataFrame({c: [('' if _types[i] == 'flow' else _cdl(v)) for i, v in enumerate(_df[c])] for c in _dcols},
                                                     index=_df.index)   # 흐름 항목은 증감에 좋고 나쁨이 없어 칠하지 않는다
                                _dtxt = [c for c in _dcols if any(isinstance(v, str) for v in _df[c])]
                                for _c in _dtxt:      # 글자 섞인 열만 문자열(순수 숫자 열은 table_ui 가 다시 숫자로 되돌려 부호가 사라진다)
                                    _df[_c] = [(v if isinstance(v, str) else '-' if v is None or v != v else
                                                f"{v:+,.{1 if _types[i] == 'pct' else 0}f}") for i, v in enumerate(_df[_c])]
                                for _c in set(_dcols) - set(_dtxt):
                                    _df[_c] = pd.to_numeric(_df[_c], errors='coerce')
                                _sty = _df.style
                                for _ri, _typ in enumerate(_types):
                                    _dp = {'amt': _udp, 'flow': _udp, 'pct': 1, 'mult': 1, 'eps': 0 if is_kr_sym else 2}[_typ]
                                    _sty = _sty.format(lambda v, dp=_dp: '-' if v is None or v != v else f"{v:,.{dp}f}",
                                                       subset=pd.IndexSlice[[_ri], _numc])
                                    _ndc = [c for c in _dcols if c not in _dtxt]
                                    if _ndc:
                                        _sty = _sty.format(lambda v, dp=(1 if _typ == 'pct' else 0): '-' if v is None or v != v else f"{v:+,.{dp}f}",
                                                           subset=pd.IndexSlice[[_ri], _ndc])
                                _sty = _sty.apply(lambda _x: _dcss, axis=None, subset=_dcols)
                                _sty = _sty.map(lambda v: 'color:#dc2626' if isinstance(v, (int, float)) and v == v and v < 0 else '',
                                                subset=_numc)
                                if _ecols:
                                    _sty = _sty.set_properties(subset=_ecols, color='#2453C8')
                                st.caption(title + f" · 금액 {_ulab}")
                                _tsrc(('DART 전자공시' if is_kr_sym else 'SEC EDGAR') + ' (분기재무, 표 아래 캡션 참조)', live=True)
                                st.dataframe(_sty, hide_index=True, filters=False, color=False, row_height=28)

                            # 연간·분기 컨센서스가 같은 소스(yfinance/네이버)의 같은 응답에 함께 들어있어
                            # freq 무관하게 항상 가져오고, 어느 열을 보여줄지만 freq로 고름 (#1: 분기에서도 컨센서스 표시)
                            _est = forward_estimates(sym8_clean, is_kr_sym) or None
                            _est_freq = 'annual' if _freq == "연간" else 'quarter'
                            # 대차 → 손익 → 현금. 멀티플 행: 현재 시총÷각 기간 실적(밴드 감각), E열=Fwd (#4)
                            _bs_items = [('자산', 'assets', 'amt'), ('부채', 'liabilities', 'amt'),
                                         ('자본', 'equity', 'amt'), ('부채비율', 'debt_ratio', 'pct'),
                                         ('PBR (현시총÷자본)', 'equity', 'mult', 'pbr_dir')]
                            _tt = '' if _freq == "연간" else ' TTM'          # 분기 보기 = 최근 4분기 합
                            _is_items = [('매출', 'revenue', 'amt'), ('매출총이익', 'gross', 'amt'),
                                         ('GPM', 'gpm', 'pct'), ('영업이익', 'op_income', 'amt'),
                                         ('OPM', 'opm', 'pct'), ('순이익', 'net_income', 'amt'),
                                         ('EPS', 'eps', 'eps'), ('SG&A', 'sga', 'amt'), (f'ROE{_tt}', 'roe', 'pct'),
                                         (f'PER (현시총÷{_tt.strip()}순익)', 'ni_basis', 'mult', 'per_dir'),
                                         (f'PSR (현시총÷{_tt.strip()}매출)', 'rev_basis', 'mult')]
                            _cf_items = [('영업활동', 'op_cf', 'amt'), ('투자활동', 'inv_cf', 'flow'),
                                         ('재무활동', 'fin_cf', 'flow'), ('Capex', 'capex', 'flow')]
                            if _stored:                # 저장본은 손익 3항목뿐 — 빈 행('-')을 늘어놓지 않는다
                                _is_items = [it for it in _is_items
                                             if it[1] in ('revenue', 'op_income', 'opm', 'net_income', 'ni_basis', 'rev_basis')]
                            else:
                                _stmt_table("① 대차대조표 (E=컨센서스)", _bs_items, est=_est, freq=_est_freq)
                            _stmt_table("② 손익계산서 (E=컨센서스)", _is_items, est=_est, freq=_est_freq)
                            if not _stored:
                                _stmt_table("③ 현금흐름표 (Capex=유출, 음수)", _cf_items)
                            _qn = "3개월 환산" if _freq == "분기" else "회계연도"
                            _src_txt = (f"DART 공시 저장본(갱신 {_stored})" if _stored else
                                        "네이버 기업분석(FnGuide)" if _via_naver else f"{_osrc} 공식")
                            st.caption(f"출처: {_src_txt}({_qn}). Δ=직전 대비 증감({_gl}, 마진·ROE는 %p, 흑전=흑자전환). "
                                       "금액 단위는 표마다 숫자 크기에 맞춰 조/억원(US $B/$M) — 각 항목 이름 괄호에 표기. "
                                       f"{_gl}(%)=증감률, 단 %로 된 항목(마진·ROE·부채비율)은 %p 차이. "
                                       "PER/PBR/PSR 행=현재 시총÷각 기간 실적(최신=트레일링, E열=Fwd). "
                                       "컨센서스 커버: KR=매출·영업익·OPM·순익·ROE·부채비율·EPS·PER·PBR(네이버) / "
                                       "US=매출·순익·EPS(yfinance). ⚠️ 현금흐름·자산 추정치는 애널 컨센서스가 배포되지 않아 '-'.")
                        else:
                            # 없는 걸 조용히 숨기지 않는다 — 왜 없는지 적는다(데이터 원칙)
                            _why = ''
                            if is_kr_sym and _dc is not None:
                                _h = _dc.health()
                                if not _h['ok']:
                                    _why = (" — **DART 공시 서버가 이 서버(Streamlit Cloud, 해외)의 요청에 응답하지 않습니다**"
                                            f" ({_h['last_error'] or '응답 없음'})."
                                            + (f" {_h['blocked_sec'] // 60 + 1}분 뒤 자동으로 다시 시도합니다." if _h['blocked_sec'] else ''))
                            st.warning(f"{_freq} 재무표를 가져오지 못했습니다{_why}")

                with _SEC['seg']:
                    # ── 🏭 사업부문별 매출 구조 (2026-10-20 개편) ─────────────────────
                    # 숫자: US = SEC XBRL 원본(최신 10-Q/10-K, AI 관여 없음) · KR = DART 사업보고서 → Gemini 추출(검산 표시)
                    # 검색하면 바로 그린다(버튼 없음). AI 는 US 에선 '주요제품' 설명만 — 실패해도 숫자는 나온다.
                    st.divider()
                    st.subheader("🏭 사업부문별 매출 구조 — 이 회사는 어디서 돈을 버나")
                    _segs, _seg_meta = [], {}
                    _seg_ai = None
                    _seg_chk_pct, _seg_chk_ai = None, False      # → 요약의 데이터 점검
                    with st.spinner("사업부문 정리 중…"):
                        _seg_ai = _seg_ai_get(sym8_clean, is_kr_sym)
                    _ai_ok = bool(_seg_ai) and not _seg_ai.get('_error') and _seg_ai.get('segments')
                    _norm = lambda t: re.sub(r'[^a-z0-9가-힣]', '', str(t).lower().replace('segment', '').replace('and', ''))
                    _prod = {_norm(x.get('name')): x.get('products') for x in (_seg_ai or {}).get('segments', [])} if _ai_ok else {}
                    if not is_kr_sym:
                        _sx_ = _seg_xbrl(sym8_clean)
                        if _sx_ and _sx_.get('periods'):
                            _pl = {'q': '최근 분기(3개월)', 'ytd': '연초 누적', 'fy': '회계연도(연간)'}
                            _pks = [k for k in ('q', 'ytd', 'fy') if k in _sx_['periods']]
                            _pk = st.segmented_control("기간", [_pl[k] for k in _pks], default=_pl[_pks[0]],
                                                       key=f"segp_{sym8_clean}") or _pl[_pks[0]]
                            _P = _sx_['periods'][[k for k in _pks if _pl[k] == _pk][0]]
                            for x in _P['segments']:
                                _pd_ = _prod.get(_norm(x['name'])) or next((v for k, v in _prod.items()
                                                                           if k and (k in _norm(x['name']) or _norm(x['name']) in k)), None)
                                _segs.append(dict(x, products=_pd_))
                            _fl = _sx_['filing']
                            _chk = _P.get('check_pct')
                            _seg_chk_pct = _chk
                            _seg_meta = {
                                'src': f"SEC XBRL 원본 — {_fl['form']} ({_fl['date']} 공시) · 기간 {_P['start']} ~ {_P['end']}",
                                'src_short': f"SEC XBRL({_fl['form']} {_fl['date']})",
                                'asof': _fl['date'],
                                'axis': '사업부문' if _P['axis'] == 'StatementBusinessSegmentsAxis' else '제품·서비스(부문 태그 없음)',
                                'check': (None if _chk is None else
                                          (f"✅ 검산: 부문 매출 합 = 연결 매출 {fmt_cap(_P['total_revenue'], 'US')} (차이 {_chk:+.1f}%)"
                                           if abs(_chk) <= 1.0 else
                                           f"⚠️ 검산: 부문 매출 합이 연결 매출과 {_chk:+.1f}% 다름 — 부문 외 매출·내부거래 조정이 있다는 뜻(공시 원문 확인)")),
                                'link': _fl['url']}
                    if not _segs and _ai_ok:                         # KR(또는 XBRL 부문 태그가 없는 US) → AI 추출본
                        for x in _seg_ai['segments']:
                            if x.get('revenue') or x.get('revenue_pct'):
                                _segs.append({'name': x['name'], 'products': x.get('products'), 'revenue': x.get('revenue'),
                                              'gross_profit': x.get('gross_profit'), 'op_income': x.get('op_income'),
                                              'revenue_pct': x.get('revenue_pct')})
                        # 검산: AI 가 뽑은 부문 합 vs 공시 재무제표 연간 매출(같은 해)
                        _chk_txt = None
                        try:
                            _yr = str(_seg_ai.get('period', ''))[:4]
                            _ann = next((r for r in unified_statements(sym8_clean, is_kr_sym, 'annual')
                                         if str(r.get('period', ''))[:4] == _yr and r.get('revenue')), None)
                            _ss = sum(x['revenue'] for x in _segs if x.get('revenue'))
                            if _ann and _ss:
                                _d_ = (_ss / _ann['revenue'] - 1) * 100
                                _seg_chk_pct, _seg_chk_ai = _d_, True
                                _chk_txt = (f"✅ 검산: AI 추출 부문 합이 공시 매출({_yr})과 {_d_:+.1f}% 차이" if abs(_d_) <= 3 else
                                            f"⚠️ 검산: AI 추출 부문 합이 공시 매출({_yr})과 {_d_:+.1f}% 다름 — 부문간 내부거래 포함이거나 추출 오류. 원문 확인 필요")
                            else:
                                _chk_txt = "⚠️ 검산 불가 — 같은 해 공시 매출을 못 찾음. AI 추출 숫자이니 원문 대조 필요"
                        except Exception:
                            _chk_txt = "⚠️ 검산 불가 — AI 추출 숫자이니 원문 대조 필요"
                        _seg_meta = {'src': f"{_seg_ai.get('source', 'DART 사업보고서')} · {_seg_ai.get('period', '')} · Gemini 추출",
                                     'src_short': f"{_seg_ai.get('source', 'DART 사업보고서')}(AI 추출)",
                                     'asof': str(_seg_ai.get('_generated', ''))[:10], 'axis': '사업부문', 'check': _chk_txt}
                    if not _segs:
                        _emsg = str((_seg_ai or {}).get('_error', ''))
                        if 'RESOURCE_EXHAUSTED' in _emsg or '429' in _emsg:
                            st.info("부문 데이터: 오늘의 AI 분석 한도(Gemini 무료 등급)를 다 썼습니다 — 날짜가 바뀌면 다시 됩니다.")
                        elif is_kr_sym:
                            st.caption("부문 데이터 없음 — DART 사업보고서 원문을 이 서버에서 읽지 못했거나 부문표가 없습니다.")
                        else:
                            st.caption("부문 데이터 없음 — 최신 10-Q/10-K XBRL 에 부문 태그가 없습니다(단일 부문 회사일 수 있음).")
                    else:
                        _tot_rev = sum(x['revenue'] for x in _segs if x.get('revenue')) or None
                        for x in _segs:
                            if x.get('revenue') and _tot_rev:
                                x['revenue_pct'] = x['revenue'] / _tot_rev * 100
                        _has_op = any(x.get('op_income') is not None for x in _segs)
                        _pf_key = 'op_income' if _has_op else ('gross_profit' if any(x.get('gross_profit') is not None for x in _segs) else None)
                        _pf_lab = {'op_income': 'OPM', 'gross_profit': 'GPM'}.get(_pf_key, '')
                        _tot_pf = sum((x.get(_pf_key) or 0) for x in _segs) if _pf_key else None
                        _cu = '조원' if is_kr_sym else '$B'
                        _dv = 1e12 if is_kr_sym else 1e9
                        _srows = []
                        for x in _segs:
                            _pf = x.get(_pf_key) if _pf_key else None
                            _srows.append({
                                '사업부문': x['name'],
                                '주요제품': (str(x.get('products'))[:40] if x.get('products') else '-'),
                                f'매출({_cu})': (x['revenue'] / _dv) if x.get('revenue') else None,
                                '매출비중(%)': x.get('revenue_pct'),
                                **({f'부문 {_pf_lab}(%)': (_pf / x['revenue'] * 100) if (_pf is not None and x.get('revenue')) else None,
                                    '이익비중(%)': (_pf / _tot_pf * 100) if (_pf is not None and _tot_pf) else None} if _pf_key else {}),
                            })
                        _segdf = pd.DataFrame(_srows)
                        _sc1, _sc2 = st.columns([1, 1.25], gap='large')
                        with _sc1:
                            _fig_seg = go.Figure()
                            _fig_seg.add_trace(go.Bar(
                                y=[r['사업부문'] for r in _srows], x=[r['매출비중(%)'] or 0 for r in _srows],
                                name='매출 비중', orientation='h', marker_color='#93B4F5',
                                text=[f"{r['매출비중(%)'] or 0:.0f}%" for r in _srows], textposition='auto'))
                            if _pf_key and _tot_pf:
                                _fig_seg.add_trace(go.Bar(
                                    y=[r['사업부문'] for r in _srows], x=[r.get('이익비중(%)') or 0 for r in _srows],
                                    name=f'이익 비중({_pf_lab})', orientation='h', marker_color='#2453C8',
                                    text=[f"{r.get('이익비중(%)') or 0:.0f}%" for r in _srows], textposition='auto'))
                            _fig_seg.update_layout(
                                barmode='group', height=max(170, 56 * len(_srows) + 60),
                                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                font=dict(color='#4B5563', size=11), margin=dict(l=0, r=10, t=10, b=0),
                                legend=dict(orientation='h', y=1.12, x=0), xaxis_ticksuffix='%',
                                yaxis=dict(autorange='reversed'))
                            _fig_seg.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
                            st.plotly_chart(_fig_seg, use_container_width=True)
                        with _sc2:
                            st.dataframe(_segdf, filters=False, src=_seg_meta.get('src_short'), asof=_seg_meta.get('asof'),
                                         column_config={c: st.column_config.NumberColumn(c, format='%.1f')
                                                        for c in _segdf.columns if c not in ('사업부문', '주요제품')})
                            if _seg_meta.get('check'):
                                st.caption(_seg_meta['check'])
                        _mnote = {'op_income': "부문 **영업이익**을 공시하는 회사 → 부문 OPM",
                                  'gross_profit': "부문 **매출총이익**만 공시하는 회사 → 부문 GPM(판관비는 부문으로 안 나눔)",
                                  None: "부문별 이익을 공시하지 않는 회사 → 매출 비중만"}[_pf_key]
                        st.caption(f"📄 {_seg_meta.get('src', '')} · 구분: {_seg_meta.get('axis', '')}. {_mnote}. "
                                   "핵심: **매출 비중 ≠ 이익 비중** — 진한 막대(이익)가 연한 막대(매출)보다 긴 부문이 캐시카우. "
                                   + ("주요제품 설명은 AI 요약(숫자와 무관)." if not is_kr_sym else
                                      "⚠️ KR 부문 숫자는 AI 가 사업보고서에서 뽑은 값 — 위 검산 결과를 같이 볼 것."))

                with _SEC['flow']:
                    # ── 💵 손익 흐름(Sankey) + 마진 궤적 (App Economy Insights 스타일) ──
                    st.divider()
                    st.subheader("💵 손익 흐름 — 매출이 순이익까지 어떻게 흐르나")
                    _flowq = unified_statements(sym8_clean, is_kr_sym, 'quarter')      # 분기 시계열
                    if not _flowq or len(_flowq) < 1:
                        _flowq = unified_statements(sym8_clean, is_kr_sym, 'annual')
                    if not _flowq:
                        st.caption("손익 흐름 데이터 없음.")
                    else:
                        # 단위는 규모에 맞춘다(2026-10-20: 매출 970억 회사가 '0.1조 · 0.0 · −0.0'으로 보였다)
                        _rv0 = abs((_flowq[0] or {}).get('revenue') or 0)
                        if is_kr_sym:
                            _uq, _uu = (1e12, '조') if _rv0 >= 1e12 else (1e8, '억')
                        else:
                            _uq, _uu = (1e9, 'B') if _rv0 >= 1e9 else (1e6, 'M')
                        _seg_for_flow = None
                        if is_kr_sym:
                            try:
                                import segment_analysis as _sa2
                                _seg_for_flow = _sa2.load_cached(sym8_clean)
                            except Exception:
                                pass
                        # 2026-10-23 — 최근 분기 하나만 보였다 → 최근 4개 분기 중 고른다(기본 최신)
                        # 2026-10-24 — 고르는 버튼을 두 차트 위로: 왼쪽에만 있어 좌우 차트 시작 높이가 어긋났다
                        _fq4 = [r for r in _flowq if r.get('revenue')][:4]
                        _fqs = [str(r.get('period', '')) for r in _fq4]
                        _fpick = (st.segmented_control("분기", _fqs, default=_fqs[0], key=f"flowq_{sym8_clean}")
                                  if len(_fqs) > 1 else (_fqs[0] if _fqs else None)) or (_fqs[0] if _fqs else None)
                        _fc1, _fc2 = st.columns([1.15, 1], gap='large')    # 2026-10-20: 구조(이번 분기)와 추이를 나란히
                        with _fc1:
                          _frow = next((r for r in _fq4 if str(r.get('period', '')) == _fpick), _flowq[0])
                          _sank = _income_sankey(_frow, _uq, _uu, _seg_for_flow)
                          if _sank:
                            st.markdown(f"###### 🧱 분기 구조 — {_frow.get('period', '')}")
                            _sank.update_layout(height=320, margin=dict(t=34))
                            st.plotly_chart(_sank, use_container_width=True)
                            st.caption(f"{_frow.get('period','')} 분기 · 단위 {_uu}{'원' if is_kr_sym else '$'} · "
                                       "파랑=남은 이익(%는 매출 대비 마진) · 빨강=차감 · 초록=가산(영업외수익 등). "
                                       "위 버튼으로 최근 4개 분기를 바꿔 본다.")
                        # 마진 궤적 스트립
                        _mq = [r for r in _flowq if r.get('revenue')][:8][::-1]     # 오래된→최신
                        with _fc2:
                          if len(_mq) >= 3:
                            st.markdown("###### 📈 마진 궤적 (GPM·OPM·NPM) — 최근 8분기")
                            _mfig = go.Figure()
                            _mx = [r.get('period', '') for r in _mq]
                            for _mk, _mlab, _mcol in [('gross', 'GPM', '#7C8AA5'), ('op_income', 'OPM', '#2453C8'),
                                                    ('net_income', 'NPM', '#15803D')]:
                                _my = [round(r[_mk] / r['revenue'] * 100, 1) if r.get(_mk) and r.get('revenue') else None
                                       for r in _mq]
                                _mfig.add_trace(go.Scatter(x=_mx, y=_my, mode='lines+markers', name=_mlab,
                                                           line=dict(color=_mcol, width=2.5)))
                            _mfig.update_layout(height=320, margin=dict(l=0, r=8, t=34, b=0), xaxis_type='category',
                                                legend=dict(orientation='h', y=1.15, x=0, yanchor='bottom'),
                                                yaxis_ticksuffix='%')
                            _mfig.update_yaxes(gridcolor='#F3F4F6', zeroline=True, zerolinecolor='#D1D5DB')
                            st.plotly_chart(_mfig, use_container_width=True)
                            st.caption("**마진**이 '성장이 이익으로 이어지는가'를 드러냄 — 우상향=규모의 경제·가격결정력, "
                                       "우하향=경쟁 심화·원가 압박.")

                with _SEC['canslim']:
                    st.divider()
                    st.markdown("## 🏅 CANSLIM 스코어카드 — 종합 판단")
                    ret_1m = (price_now / hist['Close'].iloc[-22] - 1) * 100 if len(hist) > 22 else None
                    ret_3m = (price_now / hist['Close'].iloc[-66] - 1) * 100 if len(hist) > 66 else None
                    ret_6m = (price_now / hist['Close'].iloc[-126] - 1) * 100 if len(hist) > 126 else None
                    ret_1y = (price_now / hist['Close'].iloc[-252] - 1) * 100 if len(hist) > 252 else None
                    st.caption("가치(C·A) × 가격(L·M) × 정성(N·S·I) 종합")

                    # ── 🏅 CANSLIM 스코어카드 (체슬라투자자문 방식) ──
                    _off = official_financials(sym8_clean, is_kr_sym)   # 연간 요약(스코어카드·멀티플용)
                    if _off and len(_off) >= 2:
                        _op = [r.get('op_income') for r in _off]

                        def _grow_score(cur, base, yrs):
                            """min(25, 성장률% − 5). 체슬리 C·A 방식. base 적자면 흑자전환 처리."""
                            if cur is None or base is None:
                                return None
                            if base <= 0:
                                return 25.0 if cur and cur > 0 else -10.0
                            # ⚠️ 2026-09-09 — cur 가 음수면 (음수)**(1/3) 이 **complex** 가 되고,
                            #   바로 아래 min() 에서 터진다:
                            #     TypeError: '<' not supported between 'complex' and 'float'
                            #   흑자였다가 적자로 돌아선 종목에서 났다. yrs=1 이면 실수라
                            #   통과하고 3년 CAGR(A)에서만 터져서 눈에 늦게 띄었다.
                            #   흑자→적자는 성장률이 정의되지 않는다. 최저점으로 본다.
                            if cur is None or cur <= 0:
                                return -10.0
                            g = ((cur / base) ** (1 / yrs) - 1) * 100
                            return round(min(25.0, g - 5), 1)

                        _nb = min(3, len(_op) - 1)
                        _A = _grow_score(_op[0], _op[_nb], _nb)          # A: 영업이익 3년 CAGR
                        _C = _grow_score(_op[0], _op[1], 1)              # C: 영업이익 최근 YoY

                        # L: 시장대비 6개월 초과수익 (10%p당 +5점)
                        _stk6 = (price_now / hist['Close'].iloc[-126] - 1) * 100 if len(hist) > 126 else None
                        _mkt6, _idf = None, pd.DataFrame()
                        try:
                            _idf = fetch_index_history('KS11' if is_kr_sym else 'SPY', 400)
                            if len(_idf) > 127:
                                _mkt6 = (float(_idf.iloc[-1].values[0]) / float(_idf.iloc[-127].values[0]) - 1) * 100
                        except Exception:
                            pass
                        _exc = (_stk6 - _mkt6) if (_stk6 is not None and _mkt6 is not None) else None
                        _L = round(max(0.0, min(25.0, _exc * 0.5)), 1) if _exc is not None else None

                        # M: 시장방향 — 2026-10-21 기각된 3단계 신호(Fed·M2·SPX YoY) 대신 지수 200일선.
                        #   CANSLIM 발굴 화면·종합 탭과 같은 verdict.core_switch (KR=코스피, US=S&P500)
                        try:
                            _Mlabel = _V.market_dir(_V.core_switch(_idf.iloc[:, 0])) if len(_idf) else '—'
                        except Exception:
                            _Mlabel = '—'

                        # 2026-10-24 배치 정리 — 4칸(총점·점수표·좁은 수익률표·슬라이더)에 표가 눌리고 출처 줄이 세로로 깨졌다.
                        #   ① 판정 카드 한 줄(총점·등급·시장)  ② 점수표 | 정성 입력  ③ 수익률은 칩 한 줄(L 의 근거)
                        _ca, _cb, _cm = st.columns(3)
                        _cl, _cr_ = st.columns([1.7, 1], gap='large')
                        with _cr_:
                            with st.container(border=True):
                                st.markdown("###### ✍️ 정성 입력 (N·S·I, 각 0~25)")
                                _N = st.slider("N 신성장·경영진", 0, 25, 12, key=f"cans_n_{sym8_clean}")
                                _S = st.slider("S 자사주·수급", 0, 25, 0, key=f"cans_s_{sym8_clean}")
                                _I = st.slider("I 기관 보유증가", 0, 25, 12, key=f"cans_i_{sym8_clean}")

                        _parts = [('C', _C, '영업익 최근 YoY − 5'), ('A', _A, '영업익 3년 CAGR − 5'),
                                  ('N', float(_N), '신성장·경영진 (입력)'), ('S', float(_S), '자사주·수급 (입력)'),
                                  ('L', _L, (f'시장대비 6M {_exc:+.0f}%p' if _exc is not None else '데이터 없음')),
                                  ('I', float(_I), '기관 보유증가 (입력)')]
                        _total = round(sum(v for _, v, _ in _parts if isinstance(v, (int, float))), 1)
                        _grade = ('S' if _total >= 90 else 'A' if _total >= 70 else 'B' if _total >= 50
                                  else 'C' if _total >= 30 else 'D')

                        _ca.metric("총점", f"{_total:.0f}", help="C+A+N+S+L+I (각 max 25)")
                        _cb.metric("등급", _grade, help="S 90+ · A 70+ · B 50+ · C 30+ · D")
                        _cm.metric("M 시장 국면", _Mlabel or '—', help="verdict.core_switch — KR=코스피, US=S&P500 200일선")
                        with _cl:
                            _scdf = pd.DataFrame([{'항목': k, '점수': (round(v, 1) if isinstance(v, (int, float)) else None),
                                                   '근거': d} for k, v, d in _parts])
                            _tsrc('DART·SEC EDGAR(재무) · FinanceDataReader·yfinance(주가) — 조회 시 계산', live=True)
                            st.dataframe(_scdf, filters=False, color=True,
                                         column_config={'점수': st.column_config.NumberColumn('점수', format='%+.1f')})
                            _stat_grid([('수익률 — L(상대강도)의 근거', [(k, '-' if v is None else f"{v:+.1f}%", True)
                                         for k, v in [('1개월', ret_1m), ('3개월', ret_3m), ('6개월', ret_6m), ('1년', ret_1y)]])])
                        st.caption("체슬리식: C·A=영업이익 성장(공식 DART/EDGAR) · L=시장 상대강도 · "
                                   "N·S·I=정성 입력(체슬리 엑셀 방식) · M=시장국면. ⚠️ 점수는 참고용, 정성 판단이 핵심.")
                        st.divider()
                with _SEC['val']:
                    st.divider()
                    st.markdown("## ⚖️ 멀티플 · 컨센서스 — 가격÷가치")
                    st.caption("공식 멀티플(시총÷공식실적) · BEAR/BASE/BULL 목표주가 · 밸류에이션")


                    yr1  = hist.tail(252)
                    yr_h = yr1['High'].max();   yr_l = yr1['Low'].min()
                    ret_1m  = (price_now / hist['Close'].iloc[-22] - 1)*100  if len(hist) > 22  else None
                    ret_3m  = (price_now / hist['Close'].iloc[-66] - 1)*100  if len(hist) > 66  else None
                    ret_6m  = (price_now / hist['Close'].iloc[-126] - 1)*100 if len(hist) > 126 else None
                    ret_1y  = (price_now / hist['Close'].iloc[-252] - 1)*100 if len(hist) > 252 else None
                    vol_20  = hist['Close'].pct_change().tail(20).std() * (252**0.5) * 100

                    _cons = consensus_scenarios(sym8_clean, is_kr_sym)
                    _fest = forward_estimates(sym8_clean, is_kr_sym)
                    _vb = valuation_basis(sym8_clean, is_kr_sym, _mc, price_now, _fest, info)
                    _x = lambda v: f"{v:.1f}x" if v else '-'
                    if _mc:
                        _w = _vb.get('w_fy0')
                        _bl = (f"올해E {_w*100:.0f}% + 내년E {100-_w*100:.0f}%" if _w is not None else '컨센서스 없음')
                        st.markdown(
                            f"⚖️ **PER** TTM **{_x(_vb.get('per_ttm'))}** "
                            f"<sub>최근 4분기 {_vb.get('ttm_label', '-')}</sub> · "
                            f"12MF **{_x(_vb.get('per_12mf'))}** <sub>{_bl}</sub> · "
                            f"PBR **{_x(_vb.get('pbr'))}** <sub>{_vb.get('equity_label', '-')} 자본</sub> · "
                            f"PSR **{_x(_vb.get('psr_ttm'))}** <sub>TTM</sub> "
                            f"<span style='color:#6B7280;font-size:11px'>· 시총·주가는 실시간 · "
                            f"TTM=공시 확정 4분기 합 · 12MF=앞으로 12개월 컨센서스 EPS</span>",
                            unsafe_allow_html=True)
                    # 🎯 컨센서스 BEAR / BASE / BULL (목표주가)
                    if _cons.get('base'):
                        _cu = '₩' if is_kr_sym else '\\$'      # markdown 에서 '$…$' 가 수식으로 먹혀 글자가 깨졌다(2026-10-20)
                        def _pr(t):
                            try:
                                return f"{_cu}{t:,.0f}" if t else '-'
                            except Exception:
                                return '-'
                        def _up(t):
                            try:
                                return f" ({(t/price_now-1)*100:+.0f}%)" if t else ''
                            except Exception:
                                return ''
                        _fpe = _x(_vb.get('per_12mf'))
                        st.markdown(
                            f"🎯 **컨센서스 목표주가** · 🐻 BEAR {_pr(_cons.get('bear'))}{_up(_cons.get('bear'))} · "
                            f"⚖️ BASE {_pr(_cons.get('base'))}{_up(_cons.get('base'))} · "
                            f"🐂 BULL {_pr(_cons.get('bull'))}{_up(_cons.get('bull'))} "
                            f"<span style='color:#6B7280;font-size:11px'>· 애널 {_cons.get('n') or '?'}명 · 12MF PER {_fpe}</span>",
                            unsafe_allow_html=True)
                    else:
                        st.caption("🎯 컨센서스: 데이터 없음 (yfinance 제한 · KR 소형주 등).")
                    st.divider()
                    st.subheader("💹 밸류에이션 · 재무")
                    yi2 = {}
                    try:
                        t_yf = yf.Ticker(_yf_code(sym8_clean, is_kr_sym))
                        yi2 = t_yf.info or {}
                    except Exception:
                        yi2 = {}

                    def _pcur(v):   # 통화 포맷
                        if v is None: return '-'
                        return f"{price_unit}{v:,.0f}" if is_kr_sym else f"${v:.2f}"
                    def _fx(v, suffix='', mult=1, dp=1):  # 숫자 포맷 (None 안전) — 천 단위 쉼표(2026-10-23)
                        if v is None or (isinstance(v, float) and v != v): return '-'
                        try: return f"{v*mult:,.{dp}f}{suffix}"
                        except Exception: return '-'

                    # 2026-10-23 — ROE·ROA·마진·성장·부채비율이 KR 중소형주에서 '-'(야후 미제공)였다 → 공시 분기 재무로 직접 계산.
                    #   공시 기준을 먼저, 없을 때만 야후. PEG = PER(12MF) ÷ EPS 성장률(12MF vs TTM, %).
                    try:
                        _pf = _sx.profitability(_sx.quarterly_frame(_q_rows_long(sym8_clean, is_kr_sym)[0]))
                    except Exception:
                        _pf = {}
                    _pick = lambda own, yfk, mult=100: own if own is not None else (yi2.get(yfk) * mult if yi2.get(yfk) is not None else None)
                    _e_t, _e_f = _vb.get('eps_ttm'), _vb.get('eps_12mf')
                    _peg_own = None
                    if _e_t and _e_f and _e_t > 0 and _e_f > _e_t and _vb.get('per_12mf'):
                        _peg_own = _vb['per_12mf'] / ((_e_f / _e_t - 1) * 100)

                    _tgt = yi2.get('targetMeanPrice')
                    _upside = (_tgt/price_now - 1)*100 if (_tgt and price_now) else None
                    _peg = yi2.get('trailingPegRatio') or yi2.get('pegRatio')
                    if _peg is None:
                        _peg = _peg_own

                    # 지표: (라벨, 표시값)  — 없으면 '-'
                    val_rows = [
                        ('52주 고점',   _pcur(yr_h)),
                        ('52주 저점',   _pcur(yr_l)),
                        ('52주 저점 대비', f"{(price_now/yr_l-1)*100:+.0f}%" if yr_l else '-'),   # '52주 위치 %'는 뜻이 안 읽혀 교체(2026-10-21)
                        ('연간 변동성',  _fx(vol_20, '%')),
                        ('PER (TTM)',   _fx(_vb.get('per_ttm'), 'x')),
                        ('PER (12MF)',  _fx(_vb.get('per_12mf'), 'x')),
                        ('PBR',         _fx(_vb.get('pbr'), 'x')),
                        ('PSR (TTM)',   _fx(_vb.get('psr_ttm'), 'x')),
                        ('PEG',         _fx(_peg, '', dp=2)),
                        ('배당수익률',   _fx(yi2.get('dividendYield'), '%', mult=100, dp=2)),
                        ('EPS (TTM)',   _fx(_vb.get('eps_ttm'), '', dp=2 if not is_kr_sym else 0)),
                        ('EPS (12MF)',  _fx(_vb.get('eps_12mf'), '', dp=2 if not is_kr_sym else 0)),
                        ('ROE',         _fx(_pick(_pf.get('roe'), 'returnOnEquity'), '%')),
                        ('ROA',         _fx(_pick(_pf.get('roa'), 'returnOnAssets'), '%')),
                        ('영업마진',     _fx(_pick(_pf.get('opm'), 'operatingMargins'), '%')),
                        ('순이익률',     _fx(_pick(_pf.get('npm'), 'profitMargins'), '%')),
                        ('매출성장(YoY)', _fx(_pick(_pf.get('rev_growth'), 'revenueGrowth'), '%')),
                        ('부채비율(D/E)', _fx(_pick(_pf.get('debt_ratio'), 'debtToEquity', 1), '%')),
                        ('애널 목표가',   _pcur(_tgt)),
                        ('목표가 여력',   _fx(_upside, '%')),
                    ]
                    # 2026-10-19 — 2열 세로 표(20행) → 묶음별 칩 격자. 세로 길이 ⅓.
                    _VR = dict(val_rows)      # 2026-10-23 — 이름이 _V 였을 때 verdict 모듈(_V)을 가려 CANSLIM M 이 늘 '—' 였다
                    _sg = lambda ks, signed=(): [(k, _VR[k], k in signed) for k in ks]
                    _stat_grid([
                        ('가격', _sg(['52주 고점', '52주 저점', '52주 저점 대비', '연간 변동성', '애널 목표가', '목표가 여력'], ('목표가 여력',))),
                        ('멀티플', _sg(['PER (TTM)', 'PER (12MF)', 'PBR', 'PSR (TTM)', 'PEG', '배당수익률'])),
                        ('이익·수익성', _sg(['EPS (TTM)', 'EPS (12MF)', 'ROE', 'ROA', '영업마진', '순이익률',
                                         '매출성장(YoY)', '부채비율(D/E)'], ('ROE', 'ROA', '영업마진', '순이익률', '매출성장(YoY)'))),
                    ])
                    st.caption(f"기준 — PER·PSR(TTM)·EPS(TTM): 공시 확정 최근 4분기({_vb.get('ttm_label', '-')}) 합 · "
                               f"PBR: {_vb.get('equity_label', '-')} 분기말 자본 · 12MF: 컨센서스 올해E·내년E를 남은 기간으로 가중 · "
                               "주가·시총은 실시간. "
                               f"ROE·ROA·마진·매출성장·부채비율 = 공시 분기 재무 자체 계산({_pf.get('basis', '-')}, ROE·ROA 분모는 최신 분기말 잔액, "
                               "부채비율 = 부채총계÷자본) — 공시값이 없을 때만 yfinance. "
                               f"PEG = {'yfinance' if (yi2.get('trailingPegRatio') or yi2.get('pegRatio')) else 'PER(12MF) ÷ EPS 성장률(12MF vs TTM)'}. "
                               "배당·목표가 = yfinance(무료, 기준일 비공개). 적자거나 성장률이 음수면 PEG 는 '-'.")


                with _SEC['price']:
                    st.divider()
                    st.markdown("## 🔵 가격 — 언제 살까")
                    st.caption("차트·신호 · 계절성(연도×월) · 골든/데드크로스 · 수익률 · 내부자")

                    closes = hist['Close']
                    hist['MA20']  = closes.rolling(20).mean()
                    hist['MA50']  = closes.rolling(50).mean()
                    hist['MA200'] = closes.rolling(200).mean()
                    hist['RSI']   = _rsi(closes)
                    hist['MACD'], hist['Signal'], hist['Hist'] = _macd(closes)

                    last = hist.iloc[-1]
                    rsi_v  = last['RSI'] if not pd.isna(last['RSI']) else None
                    label, score, reasons = _tf_signal(
                        rsi_v, last['MACD'], last['Signal'], last['Close'],
                        last['MA20'] if not pd.isna(last['MA20']) else None,
                        last['MA50'] if not pd.isna(last['MA50']) else None,
                    )
                    col_sig, col_score = st.columns([2, 3])
                    col_sig.markdown(f"### {label}")
                    col_score.markdown("**신호 근거:** " + " · ".join(reasons))

                    # ── 차트 (2026-10-20 단순화) ─────────────────────────────────
                    # 기본 = 주봉 · 가격+이동평균+거래량만. RSI·MACD·낙폭은 골라서 켠다(패널 5개가 늘 떠서 난잡했다).
                    # 피보나치는 뺐다 — 예측력 근거가 약하고 매매 원칙(이익 가속 진입 · 고점 대비 −20% 청산)에 안 쓰인다.
                    # 대신 원칙에 쓰이는 선: 52주 고점, 그 −20%(청산 기준선).
                    _cc1, _cc2, _cc3 = st.columns([1, 1.4, 1.4])
                    _bar = _cc1.segmented_control("봉", ['일봉', '주봉', '월봉'], default='주봉',
                                                  key=f"bar_{sym8_clean}") or '주봉'
                    _per_opts = ['6개월', '1년', '3년', '5년', '10년', '전체']
                    _per = _cc2.segmented_control("기간", _per_opts,
                                                  default={'일봉': '1년', '주봉': '3년', '월봉': '전체'}[_bar],
                                                  key=f"per_{sym8_clean}_{_bar}") or '3년'
                    _ind = _cc3.pills("보조지표", ['RSI', 'MACD', '낙폭(MDD)'], selection_mode='multi',
                                      default=[], key=f"ind_{sym8_clean}") or []
                    _rule = {'일봉': None, '주봉': 'W-FRI', '월봉': 'ME'}[_bar]
                    if _rule:
                        disp = hist[['Open', 'High', 'Low', 'Close', 'Volume']].resample(_rule).agg(
                            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
                        ).dropna(subset=['Close'])
                    else:
                        disp = hist[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
                    # 이동평균 — 같은 '기간'이 되게 봉 단위를 바꾼다(50일≈10주, 200일≈40주≈10개월)
                    _mas = {'일봉': [(50, 'MA50'), (200, 'MA200')],
                            '주봉': [(10, 'MA10주 ≈50일'), (40, 'MA40주 ≈200일')],
                            '월봉': [(10, 'MA10개월 ≈200일')]}[_bar]
                    _full = disp
                    _ma_s = [(lab, _full['Close'].rolling(n).mean()) for n, lab in _mas]   # 지표는 전체로 계산 후 자른다(앞부분 공백 방지)
                    _rsi_s = _rsi(_full['Close']); _macd_s = _macd(_full['Close'])
                    _ddd_s = (_full['Close'] / _full['Close'].cummax() - 1) * 100
                    _mo = {'6개월': 6, '1년': 12, '3년': 36, '5년': 60, '10년': 120}.get(_per)
                    if _mo and len(_full):
                        disp = _full[_full.index >= _full.index[-1] - pd.DateOffset(months=_mo)]
                    _cut = lambda x: x.loc[disp.index[0]:] if len(disp) else x
                    _dcl = disp['Close']
                    _rows = ['price', 'vol'] + [x for x in ('RSI', 'MACD', '낙폭(MDD)') if x in _ind]
                    _hts = {'price': 0.55, 'vol': 0.13, 'RSI': 0.14, 'MACD': 0.14, '낙폭(MDD)': 0.14}
                    _tot = sum(_hts[r] for r in _rows)
                    fig = make_subplots(rows=len(_rows), cols=1, shared_xaxes=True, vertical_spacing=0.03,
                                        row_heights=[_hts[r] / _tot for r in _rows])
                    fig.add_trace(go.Candlestick(
                        x=disp.index, open=disp['Open'], high=disp['High'], low=disp['Low'], close=_dcl,
                        increasing_line_color='#15803D', decreasing_line_color='#DC2626',
                        increasing_fillcolor='#15803D', decreasing_fillcolor='#DC2626',
                        name=_bar, showlegend=False), row=1, col=1)
                    for (lab, _mser), colr in zip(_ma_s, ['#2453C8', '#B45309']):
                        fig.add_trace(go.Scatter(x=disp.index, y=_cut(_mser), mode='lines',
                                                 line=dict(color=colr, width=1.6), name=lab), row=1, col=1)
                    _hi52 = float(hist['High'].tail(252).max())
                    fig.add_hline(y=_hi52, line_color='rgba(17,24,39,.45)', line_dash='dot', row=1, col=1,
                                  annotation_text=f"52주 고점 {price_unit}{_hi52:,.0f} ", annotation_position='top right',
                                  annotation_font=dict(size=11, color='#374151'))
                    fig.add_hline(y=_hi52 * 0.8, line_color='rgba(220,38,38,.55)', line_dash='dash', row=1, col=1,
                                  annotation_text=f"고점 −20% {price_unit}{_hi52 * 0.8:,.0f} · 청산 기준선 ",
                                  annotation_position='bottom right', annotation_font=dict(size=11, color='#B91C1C'))
                    _r = 2
                    fig.add_trace(go.Bar(x=disp.index, y=disp['Volume'], showlegend=False, name='거래량',
                                         marker_color=['rgba(21,128,61,.45)' if c >= o else 'rgba(220,38,38,.45)'
                                                       for o, c in zip(disp['Open'], _dcl)]), row=_r, col=1)
                    if 'RSI' in _ind:
                        _r += 1
                        fig.add_trace(go.Scatter(x=disp.index, y=_cut(_rsi_s), mode='lines', showlegend=False,
                                                 line=dict(color='#2453C8', width=1.3), name='RSI'), row=_r, col=1)
                        fig.add_hline(y=70, line_color='rgba(220,38,38,.35)', line_dash='dot', row=_r, col=1)
                        fig.add_hline(y=30, line_color='rgba(21,128,61,.35)', line_dash='dot', row=_r, col=1)
                        fig.update_yaxes(title_text='RSI', range=[0, 100], row=_r, col=1)
                    if 'MACD' in _ind:
                        _r += 1
                        _m, _sg, _hs = (_cut(x) for x in _macd_s)
                        fig.add_trace(go.Bar(x=disp.index, y=_hs, showlegend=False, name='히스토그램',
                                             marker_color=['rgba(21,128,61,.5)' if v >= 0 else 'rgba(220,38,38,.5)'
                                                           for v in _hs.fillna(0)]), row=_r, col=1)
                        fig.add_trace(go.Scatter(x=disp.index, y=_m, mode='lines', showlegend=False, name='MACD',
                                                 line=dict(color='#2453C8', width=1.3)), row=_r, col=1)
                        fig.add_trace(go.Scatter(x=disp.index, y=_sg, mode='lines', showlegend=False, name='Signal',
                                                 line=dict(color='#B45309', width=1)), row=_r, col=1)
                        fig.update_yaxes(title_text='MACD', row=_r, col=1)
                    _dd = (hist['Close'] / hist['Close'].cummax() - 1) * 100      # 낙폭은 늘 일봉 종가로 계산
                    _dd_1y = float(_dd.tail(252).min()) if len(_dd) else 0.0
                    if '낙폭(MDD)' in _ind:
                        _r += 1
                        _ddd = _cut(_ddd_s)
                        fig.add_trace(go.Scatter(x=disp.index, y=_ddd, mode='lines', showlegend=False, name='낙폭',
                                                 line=dict(color='#DC2626', width=1.1), fill='tozeroy',
                                                 fillcolor='rgba(220,38,38,.15)',
                                                 hovertemplate='낙폭 %{y:.1f}%<extra></extra>'), row=_r, col=1)
                        fig.add_hline(y=-20, line_color='rgba(220,38,38,.5)', line_dash='dot', row=_r, col=1)
                        fig.update_yaxes(title_text='낙폭', ticksuffix='%', row=_r, col=1)

                    fig.update_layout(
                        height=430 + 140 * (len(_rows) - 2), paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                        font=dict(color='#4B5563', size=11), xaxis_rangeslider_visible=False,
                        margin=dict(l=0, r=10, t=40, b=0), hovermode='x unified',
                        legend=dict(orientation='h', y=1.06, x=1, xanchor='right'))
                    for i in range(1, len(_rows) + 1):
                        fig.update_xaxes(gridcolor='rgba(128,128,128,0.15)', row=i, col=1)
                        fig.update_yaxes(gridcolor='rgba(128,128,128,0.15)', row=i, col=1)
                    st.plotly_chart(fig, use_container_width=True)
                    _dd_cur = float(_dd.iloc[-1]) if len(_dd) else 0.0
                    _dd_all = float(_dd.min()) if len(_dd) else 0.0
                    _yrs = (hist.index[-1] - hist.index[0]).days / 365.25
                    st.caption(f"현재 낙폭(역대 고점 대비) **{_dd_cur:.1f}%** · 1년 최대 {_dd_1y:.1f}% · "
                               f"조회기간({_yrs:.1f}년) 최대 {_dd_all:.1f}%. 빨간 점선 = 52주 고점의 −20% — "
                               "보유 중이면 매매 원칙상 청산을 검토하는 선(정확한 기준은 '보유 후 고점').")
                    if sym8_clean.replace('.KS','').replace('.KQ','').isdigit() and _yrs < 15:
                        st.caption("ℹ️ 한국 종목은 무료 데이터소스 한계로 최근 ~12년까지만 조회됨 (실제 상장일과 무관한 소스 제약)")

                    st.divider()

                with _SEC['ref']:
                    # ════════════════════════════════════════════════════════════
                    # 📆 월별 상승률 통계 + ⚡ 골든/데드크로스 매매 성과 (item 8)
                    # ════════════════════════════════════════════════════════════
                    st.divider()
                    _mstat = st.container()
                    _gcdc = st.container()

                    with _mstat:
                        st.subheader("📆 월별 상승률 통계 (연도 × 월)")
                        # 차트 기간과 무관하게 전체 상장 히스토리 사용 (엑셀 '주가 추이 분석' 방식)
                        _fullc = full_close_history(sym8_clean, is_kr_sym)
                        _basec = _fullc if (_fullc is not None and len(_fullc) > len(hist)) else hist['Close']
                        import monthly_stats as _ms
                        _mraw, _msum = _ms.build(_basec)
                        if _mraw is not None:
                            # 두 표의 열 폭을 같게 고정 — 위아래 칸이 한 줄로 맞아야 RAW 와 요약을 견줘 읽는다
                            def _mcfg(first):
                                cfg = {first: st.column_config.TextColumn(first, width=92)}
                                cfg.update({c: st.column_config.NumberColumn(c, format='%.1f', width=58)
                                            for c in _ms.MONTHS})
                                cfg['연간'] = st.column_config.NumberColumn('연간', format='%.1f', width=74)
                                return cfg
                            _yb = 'font-weight:800'   # 연간 열 강조(표 격자는 캔버스라 테두리 CSS 는 안 먹는다 — 굵기로)
                            _tsrc('FinanceDataReader(일봉 주가)', live=True)
                            st.dataframe(_mraw.style.map(lambda v: _yb, subset=['연간']),
                                         column_config=_mcfg('연도'), filters=False, footer=False)

                            # 요약(전체·홀수해·짝수해) — 굵게, 승률은 50% 기준으로 색
                            _msc = _msum[_msum['구분'].str.endswith('평균')][_ms.COLS].abs().stack()
                            _msc = float(_msc.quantile(.9)) if len(_msc) else 1.0

                            def _mrow(r):
                                _win = str(r.get('구분', '')).endswith('승률')
                                out = []
                                for c in r.index:
                                    css = 'font-weight:800' if c == '연간' else 'font-weight:700'
                                    if c == '구분':
                                        css += ';background-color:rgba(51,65,85,0.08)'   # 요약 라벨 열 — RAW 연도 열과 구분
                                    v = r[c]
                                    if c in _ms.COLS and pd.notna(v):
                                        bg = _tui._bg(float(v) - 50, 40) if _win else _tui._bg(float(v), _msc or 1.0)
                                        if bg:
                                            css += ';' + bg
                                    out.append(css)
                                return pd.Series(out, index=r.index)
                            st.dataframe(_msum.style.apply(_mrow, axis=1),
                                         column_config=_mcfg('구분'), filters=False, color=False)
                            st.caption("연도×월 수익률(%) — 위는 연도별 RAW(오래된 해→최근 해), 아래는 요약. "
                                       "**평균**=월별 계절성, **승률**=그 달(연간은 그 해)이 오른 비율(%) · 50% 기준 색. "
                                       "홀수해/짝수해는 대선·중간선거 주기 같은 격년 패턴 확인용. "
                                       "연간=전년 말 대비(올해는 연초 대비 YTD). ⚠️ 표본 적으면 우연 — 해가 많을수록 믿을 만.")
                        else:
                            st.info("월별 통계 표본 부족 — 기간을 '3y'나 '5y'로 늘려주세요.")

                    with _gcdc:
                        st.subheader("⚡ 이동평균 크로스 매매 백테스트")
                        # 2026-10-21 — 조합을 사용자가 고른다(X일선이 Y일선을 상향 돌파=매수, 하향 이탈=매도).
                        #   '정통' 골든크로스는 50/200(미국 기관·언론 표준). 5/20 은 국내 단기매매에서 흔히 쓰는 조합.
                        #   검증 기간(시작일)을 화면에 적는다 — 기간이 다르면 같은 규칙도 결과가 전혀 다르다.
                        _cx_base = _fullc if (_fullc is not None and len(_fullc) > len(closes)) else closes
                        _cx_base = _cx_base.dropna()
                        _cx_base.index = pd.to_datetime(_cx_base.index)
                        if getattr(_cx_base.index, 'tz', None) is not None:
                            _cx_base.index = _cx_base.index.tz_localize(None)
                        # 2026-10-23 — 구루·업계가 쓰는 조합을 기본 목록으로, 이 종목에서 같은 기간 1등 조합에 ★.
                        _PRE = {nm: (f, sl) for nm, f, sl in _sx.MA_PRESETS}
                        _PRE["직접 입력"] = None
                        _gc1, _gc2, _gc3, _gc4 = st.columns([2.6, 0.9, 0.9, 1.6])
                        _y0 = _cx_base.index.min().date()
                        _cstart = _gc4.date_input("검증 시작일", value=max(_y0, (pd.Timestamp.today() - pd.DateOffset(years=10)).date()),
                                                  min_value=_y0, max_value=pd.Timestamp.today().date(), key=f"gcs_{sym8_clean}")
                        _cmp = _sx.ma_cross_compare(_cx_base, _cstart)
                        _best = next((r['name'] for r in _cmp if r.get('best')), None)
                        _lab = lambda k: (f"★ {k} (이 종목 1등)" if k == _best else k)
                        _gpair = _gc1.selectbox("이평 조합", list(_PRE), index=0, key="gcdc_pair3", format_func=_lab)
                        if _PRE[_gpair]:
                            _ff, _ss = _PRE[_gpair]
                            _gc2.number_input("X일선", value=_ff, disabled=True, key=f"gcx_d_{_ff}")
                            _gc3.number_input("Y일선", value=_ss, disabled=True, key=f"gcy_d_{_ss}")
                        else:
                            _ff = int(_gc2.number_input("X일선", 2, 250, 10, 1, key="gcx"))
                            _ss = int(_gc3.number_input("Y일선", 3, 400, 60, 1, key="gcy"))
                        _bt = _sx.ma_cross_bt(_cx_base, _ff, _ss, _cstart) if _ff < _ss else None
                        if _ff >= _ss:
                            st.warning("X일선이 Y일선보다 짧아야 합니다(예: 5/20, 50/200).")
                        elif _bt and _bt['n']:
                            st.markdown(f"**검증 기간 {_bt['start']:%Y-%m-%d} ~ {_bt['end']:%Y-%m-%d} ({_bt['years']:.1f}년)** · "
                                        f"MA{_ff}/MA{_ss} · 종가 기준, 수수료·세금·슬리피지 미반영")
                            _stat_grid([('', [
                                ('거래 횟수', f"{_bt['n']}회"),
                                ('승률', f"{_bt['win']:.0f}%"),
                                ('누적 수익', f"{_bt['cum']:+,.0f}%", True),
                                ('연환산', f"{_bt['cagr']:+.1f}%", True),
                                ('보유 연환산', f"{_bt['bh_cagr']:+.1f}%", True),
                                ('보유 대비', f"{_bt['excess']:+.1f}%p", True),
                                ('전략 MDD', f"{_bt['mdd']:.0f}%", True),
                                ('투자 기간 비중', f"{_bt['inmk']:.0f}%")])])
                            st.caption("출처: FinanceDataReader(일봉 주가) · 마지막 갱신: 실시간 조회")
                            _cur_gc = "🟢 골든(정배열)" if _bt['state'] == 'golden' else "🔴 데드(역배열)"
                            _openmsg = " · 현재 진입 중(미청산 — 마지막 행은 오늘 종가로 평가)" if _bt['trades'][-1]['open'] else ""
                            with st.expander(f"거래 내역 {_bt['n']}건"):
                                _tsrc('FinanceDataReader(일봉 종가) · 이 화면 계산', live=True)
                                st.dataframe(pd.DataFrame([{'진입일': f"{t['진입일']:%Y-%m-%d}",
                                                            '청산일': f"{t['청산일']:%Y-%m-%d}" + (' (보유 중)' if t['open'] else ''),
                                                            '수익률(%)': round(t['ret'], 1), '보유(일)': t['days']}
                                                           for t in reversed(_bt['trades'])]), filters=False)
                            if _cmp:
                                st.markdown("**조합 비교 — 같은 기간, 연환산 순**")
                                _tsrc('FinanceDataReader(일봉 종가) · 이 화면 계산', live=True)
                                st.dataframe(pd.DataFrame([{
                                    '조합': ('★ ' if r.get('best') else '') + r['name'], '연환산(%)': round(r['cagr'], 1),
                                    '보유 대비(%p)': round(r['excess'], 1), '전략 MDD(%)': round(r['mdd'], 1),
                                    '승률(%)': round(r['win'], 0) if r['win'] is not None else None, '거래(회)': r['n'],
                                    '지금': '골든' if r['state'] == 'golden' else '데드'} for r in _cmp]), filters=False)
                            st.caption(f"현재 상태: **{_cur_gc}**{_openmsg}. X일선이 Y일선을 상향 돌파한 날 종가 매수 → "
                                       "다음 하향 이탈 날 종가 매도. ⚠️ 후행지표라 횡보장에서는 잦은 손실(휩쏘). "
                                       "'보유 대비'가 마이너스면 이 종목에선 크로스 매매가 그냥 들고 있는 것보다 못했다는 뜻. "
                                       "⚠️ ★ 1등은 **과거 이 종목에서** 1등일 뿐이다 — 5개 중 1등을 고르면 운이 섞인다(과적합). "
                                       "다른 종목·다른 기간에서도 1등인지 봐야 원칙이 된다.")
                        else:
                            st.info(f"교차 신호 없음 — 검증 기간이 짧거나 MA{_ff}/MA{_ss} 교차가 없었다. 시작일을 앞당겨 보세요.")


                    # 2026-10-21 — '그래서 얼마 샀나/팔았나'가 안 보였다 → 금액 열 + 최근 1년 매수·매도·순매수 합계.
                    #   돋보기(필터)는 뺐다(10행 남짓 표에 필요 없다).
                    _ipx = hist['Close'].copy()
                    _ipx.index = pd.to_datetime(_ipx.index)
                    if getattr(_ipx.index, 'tz', None) is not None:
                        _ipx.index = _ipx.index.tz_localize(None)

                    def _px_at(d):
                        try:
                            _s = _ipx[_ipx.index <= pd.Timestamp(d)]
                            return float(_s.iloc[-1]) if len(_s) else None
                        except Exception:
                            return None

                    def _ins_summary(rows, unit, div):
                        _1y = pd.Timestamp.today() - pd.DateOffset(years=1)
                        _b = sum(r['amt'] for r in rows if r['amt'] is not None and r['amt'] > 0 and r['d'] >= _1y)
                        _s = sum(-r['amt'] for r in rows if r['amt'] is not None and r['amt'] < 0 and r['d'] >= _1y)
                        _n1 = sum(1 for r in rows if r['d'] >= _1y)
                        _f = (lambda v: f"${v/div:,.1f}M") if unit == '$M' else (lambda v: f"{v/div:,.1f}{unit}") if div != 1e8 else (lambda v: f"{v/div:,.0f}{unit}" if abs(v) >= 1e9 else f"{v/div:,.1f}{unit}")
                        _stat_grid([('', [('최근 1년 신고', f"{_n1}건"),
                                          ('매수 금액', _f(_b)), ('매도 금액', _f(_s)),
                                          ('순매수', ('+' if _b - _s >= 0 else '−') + _f(abs(_b - _s)), True)])])

                    # 2026-10-21 실화면: yfinance 집계 표와 Form 4 원문 표가 같은 거래를 두 번 보였다 → 원문이 되면 원문만
                    _f4, _f4e = [], None
                    if not is_kr_sym:
                        try:
                            with st.spinner("SEC Form 4 원문 읽는 중…"):
                                _f4 = _form4_rows(sym8_clean)
                        except Exception as _e4:
                            _f4e = f"{type(_e4).__name__}"
                    if is_kr_sym:
                        _kins = kr_insiders(sym8_clean)
                        if _kins:
                            st.subheader("👤 내부자 거래 (DART 공식)")
                            _kr_r = []
                            for x in _kins:
                                _d = pd.to_datetime(str(x['date']), errors='coerce')
                                _p = _px_at(_d) if pd.notna(_d) else None
                                _amt = (x['change'] * _p) if (x['change'] is not None and _p) else None
                                _kr_r.append({'d': _d if pd.notna(_d) else pd.Timestamp('1900-01-01'), 'x': x, 'p': _p, 'amt': _amt})
                            _ins_summary(_kr_r, '억원', 1e8)
                            _kidf = pd.DataFrame([{
                                '보고일': r['d'].strftime('%Y-%m-%d') if r['d'].year > 1900 else '-',
                                '보고자': r['x']['name'], '직위': r['x']['position'],
                                '구분': '매수' if (r['x']['change'] or 0) > 0 else ('매도' if (r['x']['change'] or 0) < 0 else '변동0'),
                                '증감(주)': r['x']['change'],
                                '추정금액(억원)': None if r['amt'] is None else round(r['amt'] / 1e8, 1),
                                '보유(주)': r['x']['holdings']} for r in _kr_r])
                            _tsrc('DART 임원·주요주주 소유상황보고 · 금액=증감×보고일 종가(추정)', live=True)
                            _kidf = _kidf[['보고일', '구분', '추정금액(억원)', '증감(주)', '보고자', '직위', '보유(주)']]   # 폰에서도 핵심 열이 먼저 보이게
                            st.dataframe(_kidf, filters=False, row_height=25,
                                         column_config={'증감(주)': st.column_config.NumberColumn(format='localized'),
                                                        '보유(주)': st.column_config.NumberColumn(format='localized'),
                                                        '추정금액(억원)': st.column_config.NumberColumn(format='%+,.1f')})
                            st.caption("증감>0=취득·<0=처분. **금액은 추정**: DART 소유상황보고에는 거래 단가가 없어 "
                                       "'증감 주수 × 보고일 종가'로 계산했다(실제 체결가·장외·증여·스톡옵션 행사와 다를 수 있다). "
                                       "정확한 단가는 DART 원문 보고서에서.")
                        else:
                            st.info("내부자 거래 내역 없음 (DART)")
                    elif insid is not None and not insid.empty and not _f4:
                        st.subheader("👤 내부자 거래 (SEC Form 4 기반)")
                        _uins, _ur = [], []
                        for _, _ri in insid.head(20).iterrows():
                            _utxt = str(_ri.get('Text') or '')
                            if 'Sale' in _utxt:
                                _ukind, _sg = '매도', -1
                            elif 'Purchase' in _utxt or 'Buy' in _utxt:
                                _ukind, _sg = '매수', 1
                            elif 'Award' in _utxt or 'Grant' in _utxt:
                                _ukind, _sg = '부여(보상·RSU 등)', 0     # 회사가 준 주식 보상 — 본인 돈으로 산 게 아니다
                            elif 'xercise' in _utxt:
                                _ukind, _sg = '옵션 행사', 0
                            elif 'onversion' in _utxt:
                                _ukind, _sg = '전환', 0
                            elif 'Gift' in _utxt:
                                _ukind, _sg = '증여', 0
                            else:
                                _ukind, _sg = '기타', 0
                            _ush, _uval = _ri.get('Shares'), _ri.get('Value')
                            _d = pd.to_datetime(str(_ri.get('Start Date'))[:10], errors='coerce')
                            _uv = float(_uval) if pd.notna(_uval) and _uval else None
                            if _uv is None and _sg and pd.notna(_ush) and pd.notna(_d):   # 금액 미기재 → 주수×그날 종가(추정)
                                _p = _px_at(_d)
                                _uv = float(_ush) * _p if _p else None
                            _ur.append({'d': _d if pd.notna(_d) else pd.Timestamp('1900-01-01'),
                                        'amt': (_sg * _uv) if (_uv is not None and _sg) else None})
                            _uins.append({'일자': str(_ri.get('Start Date'))[:10],
                                          '보고자': _ri.get('Insider'), '직위': _ri.get('Position'),
                                          '구분': _ukind,
                                          '주수': float(_ush) if pd.notna(_ush) else None,
                                          '금액($M)': round(_sg * _uv / 1e6, 2) if (_uv is not None and _sg) else None})
                        _ins_summary(_ur, '$M', 1e6)
                        _udf = pd.DataFrame(_uins)[['일자', '구분', '금액($M)', '주수', '보고자', '직위']]
                        _tsrc('SEC Form 4 (yfinance 집계)', live=True)
                        st.dataframe(_udf, filters=False, row_height=25,
                                     column_config={'주수': st.column_config.NumberColumn(format='localized'),
                                                    '금액($M)': st.column_config.NumberColumn(format='%+,.2f')})
                        st.caption("금액: 매수 +, 매도 −(백만 달러). 부여(RSU·성과주식 등 회사 보상)·옵션 행사·전환·증여는 "
                                   "본인 현금 매매가 아니라 합계에서 뺀다 — 내부자 신호로 읽을 건 **시장에서 직접 산 매수**다. "
                                   "Form 4 에 금액이 비어 있으면 주수×그날 종가로 추정. 정확 대조는 위 '기업 개요'의 EDGAR Form4 링크에서.")

                    # ── 📑 Form 4 원문 (US, 2026-10-21) — 장내 매매만 신호, 부여·행사·세금 반납은 보상 흐름 ─────
                    if not is_kr_sym:
                        st.subheader("📑 Form 4 원문 — 장내 매매·스톡옵션·RSU·워런트")
                        if not _f4:
                            st.info("최근 1년 Form 4 없음" if not _f4e else f"SEC 원문 조회 실패({_f4e}) — 위 yfinance 집계로 대신 표시")
                        else:
                            _P = [r for r in _f4 if r['code'] == 'P' and r['table'] == '주식']
                            _S = [r for r in _f4 if r['code'] == 'S' and r['table'] == '주식']
                            _amt = lambda rs: sum((r['shares'] or 0) * (r['price'] or 0) for r in rs)
                            _spl = _amt([r for r in _S if r['plan_10b5_1']])
                            _grant = [r for r in _f4 if r['code'] == 'A' and r['table'] == '파생']
                            _stat_grid([('', [
                                ('장내 매수', f"${_amt(_P)/1e6:,.2f}M · {len(_P)}건", True),
                                ('장내 매도', f"${_amt(_S)/1e6:,.2f}M · {len(_S)}건"),
                                ('계획 매도 비중', f"{_spl/_amt(_S)*100:.0f}%" if _amt(_S) else '-'),
                                ('옵션·RSU 부여', f"{len(_grant)}건 · {sum((r['underlying'] or r['shares'] or 0) for r in _grant):,.0f}주"),
                                ('행사·전환', f"{sum(1 for r in _f4 if r['code'] in ('M', 'X', 'O'))}건"),
                                ('세금 납부용 반납', f"{sum(1 for r in _f4 if r['code'] == 'F')}건")])])
                            _der = [r for r in _f4 if r['table'] == '파생']
                            if _der:
                                st.markdown("**파생상품 — 스톡옵션 · RSU · 성과주식 · 워런트**")
                                _tsrc('SEC EDGAR Form 4 원문(XML 파생상품 표·각주)', live=True)
                                st.dataframe(pd.DataFrame([{
                                    '일자': r['date'] or '-', '보고자': r['owner'], '직위': r['role'], '종류': r['sec_kind'],
                                    '거래': r['code_label'], '수량(주)': r['underlying'] or r['shares'],
                                    '행사가($)': r['exercise_price'], '행사 가능일': r['exercisable'] or '각주',
                                    '만기': r['expiration'] or '각주',
                                    '수령 조건': ' · '.join(t for t in r['tags'] if '10b5-1' not in t and '가중평균' not in t) or '-'}
                                    for r in _der[:40]])[['일자', '종류', '거래', '수량(주)', '행사가($)', '만기', '수령 조건',
                                                          '보고자', '직위', '행사 가능일']], filters=False)
                            _nd = [r for r in _f4 if r['table'] == '주식' and r['code'] in ('P', 'S')]
                            if _nd:
                                st.markdown("**장내 매매 — 사전계획(10b5-1) 여부**")
                                _tsrc('SEC EDGAR Form 4 원문(XML 비파생 표)', live=True)
                                st.dataframe(pd.DataFrame([{
                                    '일자': r['date'] or '-', '보고자': r['owner'], '직위': r['role'], '거래': r['code_label'],
                                    '수량(주)': r['shares'], '단가($)': r['price'],
                                    '금액($M)': None if not (r['shares'] and r['price']) else
                                                round((1 if r['code'] == 'P' else -1) * r['shares'] * r['price'] / 1e6, 2),
                                    '사전계획': '10b5-1' if r['plan_10b5_1'] else '-', '거래 후 보유(주)': r['after']}
                                    for r in _nd[:40]])[['일자', '거래', '금액($M)', '사전계획', '수량(주)', '단가($)',
                                                         '보고자', '직위', '거래 후 보유(주)']], filters=False)
                            _notes = list(dict.fromkeys((r['notes'], r['url']) for r in _f4 if r['notes']))
                            if _notes:
                                with st.expander(f"각주 원문 {len(_notes)}개(영문) — 수령 조건·계획 매매 근거"):
                                    st.markdown("\n".join(f"- {n[:600]} [원문]({u})" for n, u in _notes[:30]))
                            st.caption("내부자 신호로 의미가 큰 건 **장내 매수(P)** — 본인 돈으로 시장에서 산 것. 부여(A)는 회사 보상, "
                                       "행사(M)·세금 반납(F)은 보상을 현금화하는 흐름이라 신호가 약하다. 10b5-1 = 미리 정해 둔 계획에 따른 "
                                       "기계적 매매(2023-04부터 원문에 표시) — 계획 매도는 '팔고 싶어서 판' 매도보다 정보가 적다. "
                                       "수령 조건은 각주 문장을 규칙으로 읽은 꼬리표다(원문 확인 권장). 최근 1년 최대 30건.")

                    # ── 🧨 잠재 희석 — CB·BW·EB (2026-10-21) ─────────────────────
                    #   한국 중소형주의 '조용한 물량'. 전환가 ≤ 주가면 전환 후 매도 유인, 주가가 내리면 리픽싱으로 주식 수가 더 는다.
                    _dil = None
                    if is_kr_sym:
                        _kd = kr_dilution(sym8_clean)
                        _shn_d = _shares_now(sym8_clean, True, info)
                        _dil = _ac_dil.summarize_dilution(_kd['terms'], shares_out=_shn_d, price=float(price_now))
                        st.subheader("🧨 잠재 희석 — 전환사채·신주인수권부사채·교환사채")
                        if not _kd['terms'] and not _kd['src']:
                            st.info(f"조회 실패 — {_kd['err'] or 'DART 미접속'}. 저장본도 아직 없습니다(주간 갱신 후 표시).")
                        else:
                            _stat_grid([('', [
                                ('아직 전환 가능한 발행', f"{_dil['n_active']}건"),
                                ('잠재 신주(발행주식 대비)', f"{_dil['pot_pct']:.1f}%"),
                                ('리픽싱 바닥까지 가면', f"{_dil['max_pct']:.1f}%"),
                                ('지금 전환하면 이득인 물량', f"{_dil['itm_pct']:.1f}%"),
                                ('EB(기존 주식 교환)', f"{_dil['eb_pct']:.1f}%")])])
                            if _dil['rows']:
                                _knm = {'CB': '전환사채', 'BW': '신주인수권부사채', 'EB': '교환사채'}
                                _tsrc(_kd['src'] + ' · 비율 = 전환주식수 ÷ 현재 상장주식수', live='실시간' in _kd['src'])
                                st.dataframe(pd.DataFrame([{
                                    '종류': _knm.get(r['kind'], r['kind']), '회차': r.get('round') or '-',
                                    '결정일': r.get('decided') or '-',
                                    '발행액(억원)': None if not r.get('amount') else round(r['amount'] / 1e8, 1),
                                    '전환가(원)': r.get('price'), '최저 조정가(원)': r.get('floor'),
                                    '현재가÷전환가(%)': round(float(price_now) / r['price'] * 100) if r.get('price') else None,
                                    '발행주식 대비(%)': None if r.get('pct') is None else round(r['pct'], 1),
                                    '청구 종료': r.get('end') or '-',
                                    '상태': ('전환 가능' if r['active'] else '기간 종료')} for r in _dil['rows']]),
                                    filters=False)
                            _ev = _kd.get('events') or []
                            if _ev:
                                _evc = pd.Series([e['label'] for e in _ev]).value_counts()
                                st.markdown("**최근 1년 관련 공시** — " + " · ".join(f"{k} {v}건" for k, v in _evc.items()))
                                with st.expander(f"공시 {len(_ev)}건 원문 링크"):
                                    st.markdown("\n".join(f"- {e['date']} · {e['label']} · [{e['title']}]({e['url']})" for e in _ev[:40]))
                            elif _kd.get('err'):
                                st.caption(f"최근 공시 목록은 못 불러왔습니다({_kd['err']}) — 발행 조건만 저장본으로 표시.")
                            st.caption("발행 **결정** 기준의 최대치다 — 이미 전환·상환된 분량은 DART 구조화 데이터로 차감할 수 없다"
                                       "(전환청구 공시가 잦으면 이미 상당량이 주식으로 바뀌었다는 뜻). "
                                       "'현재가÷전환가' 100% 이상 = 전환 후 바로 팔면 이익 → 매도 압력. "
                                       "리픽싱 = 주가가 내리면 전환가를 최저 조정가까지 낮춰 주식 수가 늘어나는 조항. "
                                       "EB 는 회사가 가진 주식을 내주는 것이라 신주 희석은 아니지만 유통 물량이 는다. "
                                       "스톡옵션 부여 건수는 위 공시 목록에서 확인(행사가·조건은 원문).")



                # ════════════════════════════════════════════════════════════
                # 보강 섹션 (2026-10-19) — 요약 판단 · 낙폭 회차 · 실적 발표 · 멀티플 밴드 ·
                #   컨센서스 추세 · 동종업계 · 이익 가속 신호 이력. 위 블록들의 계산이 끝난 뒤
                #   돌아야 하므로 맨 끝에 두고, 보이는 위치는 컨테이너가 정한다.
                # ════════════════════════════════════════════════════════════
                _cl = hist['Close'].dropna().copy()
                _cl.index = pd.to_datetime(_cl.index)
                if getattr(_cl.index, 'tz', None) is not None:
                    _cl.index = _cl.index.tz_localize(None)
                _mkt = 'KR' if is_kr_sym else 'US'
                _cur_u = '원' if is_kr_sym else '$'

                # ── 📉 낙폭 회차 ─────────────────────────────────────────
                with _SEC['price']:
                    st.markdown("#### 📉 낙폭 회차 — 최근 N개월 동안 고점 대비 X% 이상 빠진 횟수")
                    _dc1, _dc2, _ = st.columns([1.2, 2.2, 4])
                    _dd_m = _dc1.selectbox("기간(개월)", [6, 12, 24, 36, 60, 120], index=1, key=f"dd_m_{sym8_clean}")
                    _dd_x = _dc2.slider("하락 기준(%)", 5, 60, 20, 5, key=f"dd_x_{sym8_clean}")
                    _eps = _sx.drawdown_episodes(_cl, _dd_m, _dd_x)
                    _dds = _sx.drawdown_series(_cl[_cl.index >= _cl.index.max() - pd.DateOffset(months=_dd_m)])
                    _rec = [e['days_to_recover'] for e in _eps if e['days_to_recover'] is not None]
                    _m1, _m2, _m3, _m4, _m5 = st.columns(5)
                    _m1.metric("횟수", f"{len(_eps)}회")
                    _m2.metric("평균 최대낙폭", f"{np.mean([e['depth'] for e in _eps]):.1f}%" if _eps else "-")
                    _m3.metric("최대 낙폭", f"{min(e['depth'] for e in _eps):.1f}%" if _eps else "-")
                    _m4.metric("평균 회복", f"{np.mean(_rec):.0f}일" if _rec else ("미회복" if _eps else "-"))
                    _m5.metric("현재 고점대비", f"{_dds.iloc[-1]:.1f}%" if len(_dds) else "-")
                    if len(_dds):
                        _fdd = go.Figure(go.Scatter(x=_dds.index, y=_dds.values, fill='tozeroy', mode='lines',
                                                    line=dict(color='#a03028', width=1),
                                                    hovertemplate='%{x|%Y-%m-%d}<br>고점대비 %{y:.1f}%<extra></extra>'))
                        _fdd.add_hline(y=-_dd_x, line_dash='dot', line_color='#7c8290',
                                       annotation_text=f'−{_dd_x}%', annotation_position='right')
                        _fdd.update_layout(height=230, margin=dict(l=8, r=8, t=10, b=8), yaxis_title='고점대비(%)',
                                           showlegend=False)
                        st.plotly_chart(_fdd, use_container_width=True)
                    if _eps:
                        _tsrc('FinanceDataReader·yfinance(일봉 종가) — 기간 내 고점 기준', live=True)
                        st.dataframe(pd.DataFrame([{
                            '고점일': str(e['peak_date'].date()), '저점일': str(e['trough_date'].date()),
                            '최대낙폭(%)': round(e['depth'], 1),
                            '고점까지(일)': (e['trough_date'] - e['peak_date']).days,
                            '회복일': str(e['recover_date'].date()) if e['recover_date'] is not None else '미회복',
                            '회복기간(일)': e['days_to_recover']} for e in reversed(_eps)]),
                            filters=False, use_container_width=True)
                    st.caption(f"한 회차 = 고점에서 {_dd_x}% 이상 빠진 순간부터 **그 고점을 되찾을 때까지**. "
                               "회복 전의 추가 하락은 같은 회차로 묶는다(따로 세면 횟수가 부풀려진다). "
                               "기간 시작 시점의 가격을 첫 고점으로 본다. 매매 원칙의 손절선(고점 대비 −20%)이 "
                               "이 종목에 얼마나 자주 걸렸을지를 보는 용도.")

                # ── 📅 실적 발표 · 서프라이즈 ─────────────────────────────
                _ed = _earn_data(sym8_clean, is_kr_sym)
                with _SEC['earn']:
                    st.divider()
                    st.markdown("## 📅 실적 발표 · 서프라이즈")
                    # 2026-10-23 개편 — ① '미정'이면 전년 같은 분기 발표일로 시기 추정 ② 최근 4개 분기를 순서대로
                    #   실적 vs 발표 직전 컨센서스 ③ yfinance 의 띄엄띄엄한 옛 기록(KR 2011·2015…)은 본 표에서 뺐다.
                    _edf = _ed.get('dates')
                    _now = pd.Timestamp.utcnow().tz_localize(None)
                    _eps_hist, _next_us = [], None
                    if _edf is not None and not _edf.empty:
                        _dcol = [c for c in _edf.columns if 'Date' in c][0]
                        _edf[_dcol] = pd.to_datetime(_edf[_dcol], utc=True).dt.tz_convert(None)
                        _fut = _edf[_edf[_dcol] > _now].sort_values(_dcol)
                        if not _fut.empty:
                            _next_us = (_fut[_dcol].iloc[0], _fut.get('EPS Estimate').iloc[0] if 'EPS Estimate' in _fut else None)
                        for _, _r in _edf[_edf[_dcol] <= _now].iterrows():
                            _eps_hist.append({'date': _r[_dcol], 'est': _r.get('EPS Estimate') if pd.notna(_r.get('EPS Estimate')) else None,
                                              'rep': _r.get('Reported EPS') if pd.notna(_r.get('Reported EPS')) else None})
                    _ev_kr, _ev_err = [], None
                    if is_kr_sym:
                        try:
                            _ev_kr = _kr_results_dates(sym8_clean)
                        except Exception as _e:
                            _ev_err = type(_e).__name__
                    _qf_e = _sx.quarterly_frame(_q_rows_long(sym8_clean, is_kr_sym)[0])
                    _cq = _kr_cons_q(sym8_clean) if is_kr_sym else {}
                    _eq = _sx.earnings_quarters(_qf_e, _ev_kr, _cq, _eps_hist)
                    _nx = _eq['next']
                    _e1, _e2 = st.columns(2)
                    if _next_us is not None:
                        _e1.metric("다음 발표", _next_us[0].strftime('%Y-%m-%d'), f"D-{(_next_us[0] - _now).days}")
                    elif _nx.get('예상') is not None:
                        _e1.metric("다음 발표", f"{_nx['예상']:%m월 %d일} 전후(추정)",
                                   f"전년 {_nx['전년 동기']} {_nx['전년 발표일']:%Y-%m-%d} {_nx['전년 근거'] or ''}", delta_color='off')
                    else:
                        _e1.metric("다음 발표", "미정", (f"법정 마감 {_nx['법정 마감(KR)']:%Y-%m-%d}" if is_kr_sym and _nx else None),
                                   delta_color='off')
                    _cmp = _eq['wins'] + _eq['losses']
                    _e2.metric("최근 4분기 컨센서스 대비", f"상회 {_eq['wins']} · 하회 {_eq['losses']}" if _cmp else "비교 불가",
                               (f"{len(_eq['rows']) - _cmp}개 분기는 컨센서스 기록 없음" if _cmp < len(_eq['rows']) else None),
                               delta_color='off')
                    if _eq['rows']:
                        _amt0 = max([abs(r['매출'] or 0) for r in _eq['rows']] + [0])
                        _eu2 = (('조원', 1e12) if _amt0 >= 1e12 else ('억원', 1e8)) if is_kr_sym else (('$B', 1e9) if _amt0 >= 1e9 else ('$M', 1e6))
                        _dv = lambda v: None if v is None or pd.isna(v) else v / _eu2[1]
                        _etb = pd.DataFrame([{
                            '분기': r['분기'], '발표일': f"{r['발표일']:%Y-%m-%d}" if r['발표일'] is not None else '-',
                            f"매출({_eu2[0]})": _dv(r['매출']), f"영업이익({_eu2[0]})": _dv(r['영업이익']),
                            f"영업이익 컨센서스({_eu2[0]})": _dv(r['영업이익 컨센서스']), '영업이익 차이(%)': r['영업이익 차이(%)'],
                            'EPS': r['EPS'], 'EPS 컨센서스': r['EPS 컨센서스'], 'EPS 차이(%)': r['EPS 차이(%)'],
                            '판정': r['판정'] or '-'} for r in _eq['rows']])
                        _etb = _etb[[c for c in _etb.columns if c in ('분기', '발표일', '판정') or _etb[c].notna().any()]]
                        _tsrc(('DART 공시(실적·발표일) · 네이버 FnGuide 분기 컨센서스(주간 저장본)' if is_kr_sym else
                               'SEC EDGAR(실적) · yfinance(EPS 컨센서스·발표일)'), live=True)
                        st.dataframe(_etb, filters=False)
                    st.caption("최근 4개 분기, 최신이 위. 차이 = (실적 − 발표 직전 컨센서스) ÷ |컨센서스|. 판정은 EPS 가 있으면 EPS, 없으면 영업이익. "
                               + ("⚠️ 한국 분기 컨센서스는 2026-10 부터 매주 저장을 시작했다 — 발표 후엔 추정치가 사라져 과거분을 만들 수 없다. "
                                  "2026.3Q 실적부터 비교가 채워진다. 발표일은 DART 잠정실적 공정공시(없으면 분기·반기·사업보고서) 접수일."
                                  + (f" (DART 조회 실패: {_ev_err} — 발표일 '-')" if _ev_err else '')
                                  if is_kr_sym else "EPS 는 회사 발표 기준(조정 EPS 일 수 있음)."))
                    if not is_kr_sym and _eps_hist:
                        _old = [h for h in _eps_hist if h['rep'] is not None and h['date'] >= _now - pd.DateOffset(years=3)]
                        if len(_old) > 4:
                            with st.expander(f"최근 3년 EPS 서프라이즈 {len(_old)}회"):
                                _tsrc('yfinance (EPS 컨센서스·발표치)', live=True)
                                st.dataframe(pd.DataFrame([{'발표일': f"{h['date']:%Y-%m-%d}", '예상 EPS': h['est'], '실제 EPS': h['rep'],
                                                            '서프라이즈(%)': ((h['rep'] - h['est']) / abs(h['est']) * 100) if h['est'] else None}
                                                           for h in sorted(_old, key=lambda h: h['date'], reverse=True)]), filters=False)

                # ── ⚖️ 멀티플 밴드 · 컨센서스 추세 · 동종업계 ───────────────
                with _SEC['val']:
                    st.divider()
                    st.markdown("### 📏 멀티플 밴드 — 지금 비싼가, 과거에는 어디까지 갔나")
                    _qr, _qsrc = _q_rows_long(sym8_clean, is_kr_sym)
                    _qf = _sx.quarterly_frame(_qr)
                    _shn = _shares_now(sym8_clean, is_kr_sym, info)
                    # 2026-10-21 — 기간은 사용자가 고른다. 고를 수 있는 끝 = 가진 재무 데이터의 시작(종목마다 다르다).
                    _band_all = _sx.multiple_band(_cl, _shn, _qf, None) if _shn else None
                    _bstart = (_band_all or {}).get('start')
                    _ymax = max(1, int(((_cl.index.max() - _bstart).days) // 365)) if _bstart is not None else 10
                    _yopts = [y for y in (1, 2, 3, 5, 7, 10, 15) if y < _ymax] + [None]
                    _by = st.radio("기간", _yopts, index=_yopts.index(5) if 5 in _yopts else len(_yopts) - 1,
                                   horizontal=True, key=f"band_y_{sym8_clean}",
                                   format_func=lambda y: f"{y}년" if y else (f"전체({_bstart:%Y.%m}~)" if _bstart is not None else "전체"))
                    _band = (_band_all if _by is None else _sx.multiple_band(_cl, _shn, _qf, _by)) if _shn else None
                    _bm = (_band or {}).get('main')
                    if _qf is not None and not _qf.empty:
                        _q0, _q1 = _qf.index.min(), _qf.index.max()
                        _eqn = int(_qf['equity'].notna().sum()) if 'equity' in _qf else 0
                        st.caption(f"보유 분기 재무: **{_q0:%Y.%m} ~ {_q1:%Y.%m}** ({len(_qf)}개 분기 · 출처 {_qsrc})"
                                   + (f" · 자본(P/B용) {_eqn}개 시점" if _eqn else " · 자본 이력 없음(P/B 불가)")
                                   + ". TTM 은 4개 분기가 쌓인 뒤부터라 밴드는 그보다 1년 늦게 시작한다.")
                    if not _bm:
                        st.info("멀티플 밴드를 그릴 수 없습니다 — 분기 재무가 1년 이상 연속으로 없거나 주식수를 모릅니다. "
                                + ("KR 은 저장된 DART 손익이 있는 종목만 됩니다." if is_kr_sym else ""))
                    else:
                        # 흑자면 P/E·P/S·P/B 전부, 적자면 P/S·P/B (판단 카드는 main = P/E 또는 P/S)
                        _bt = [(k, _band[k]) for k in ('pe', 'ps', 'pb') if _band.get(k)]
                        _tabs = st.tabs([f"{b['kind']} 밴드" for _, b in _bt])
                        for (_bk, _b), _tb in zip(_bt, _tabs):
                            with _tb:
                                _ser = _b['series']
                                _fb = go.Figure(go.Scatter(x=_ser.index, y=_ser.values, mode='lines', name=_b['kind'],
                                                           line=dict(color='#1f4e79', width=2),
                                                           hovertemplate='%{x|%Y-%m}<br>%{y:.1f}배<extra></extra>'))
                                for _pp, _dash in ((10, 'dot'), (25, 'dash'), (50, 'solid'), (75, 'dash'), (90, 'dot')):
                                    _fb.add_hline(y=_b['pct'][_pp], line_dash=_dash, line_width=1, line_color='#7c8290',
                                                  annotation_text=f"{_pp}분위 {_b['pct'][_pp]:.1f}", annotation_position='right')
                                _fb.update_layout(height=300, margin=dict(l=8, r=90, t=10, b=8),
                                                  yaxis_title=f"{_b['kind']}(배)", showlegend=False)
                                st.plotly_chart(_fb, use_container_width=True)
                                # 2026-10-19 — 지표 3개 줄 + 그 아래 좁은 표 → 한 줄에 나란히(왼쪽 지표 · 오른쪽 분위표)
                                _bL, _bR = st.columns([1, 2.2], gap='medium')
                                with _bL:
                                    _stat_grid([('', [(f"현재 {_b['kind']}", f"{_b['now']:.1f}배"),
                                                      ("과거 대비", f"{_b['rank']:.0f}%의 기간보다 비쌈"),
                                                      ("10분위 아래였던 기간", f"{_b['below10']:.0f}%")])], one=True)
                                with _bR:
                                    if _b['implied']:
                                        _tsrc(f"{_qsrc} TTM · 종가×현재 주식수", live=True)
                                        st.dataframe(pd.DataFrame([{
                                            '분위': f"{_pp}분위", f"{_b['kind']}(배)": round(_b['pct'][_pp], 1),
                                            f"환산주가({_cur_u})": round(_b['implied'][_pp], 2 if not is_kr_sym else 0),
                                            '현재가대비(%)': round((_b['implied'][_pp] / price_now - 1) * 100, 1)}
                                            for _pp in (10, 25, 50, 75, 90)]), filters=False, color=True)
                                st.caption(f"표본 {_b['n']}개월{' ⚠️ 2년 미만 — 분위가 불안정하다' if _b['n'] < 24 else ''}. {_b['why']}. 월말 시가총액(종가 × **현재** 발행주식수) ÷ 그 시점에 공시돼 있던 TTM "
                                           f"({'순이익' if _b['kind']=='P/E' else '매출' if _b['kind']=='P/S' else '자본'}, 분기말+45일). "
                                           "⚠️ 증자·자사주로 주식수가 크게 변한 종목은 과거 멀티플이 왜곡된다. "
                                           "⚠️ **10분위는 '바닥'이 아니다** — 이익이 꺾이는 구간에서는 분모가 줄어 밴드 하단도 뚫린다. "
                                           "환산주가는 '최근 TTM 이 유지된다면'의 가정이다.")
                        if is_kr_sym and not _band.get('pb'):
                            st.caption("P/B 밴드: KR 자본(잔액) 이력이 아직 짧다. 매주 네이버 기업분석으로 쌓는 중"
                                       "(2026-10-19 시작) — 과거분은 DART 를 한국 IP 에서 한 번 돌리면 채워진다.")

                    # 컨센서스 추세
                    st.markdown("### 🔁 컨센서스 추세 — 숫자보다 방향")
                    _tr, _rv = _ed.get('eps_trend'), _ed.get('eps_revisions')
                    if _tr is not None:
                        _lab = {'0q': '이번 분기', '+1q': '다음 분기', '0y': '올해', '+1y': '내년'}
                        _rows_t = []
                        for _per, _r in _tr.iterrows():
                            _c0 = _r.get('current')
                            def _chg(k):
                                v = _r.get(k)
                                return round((_c0 / v - 1) * 100, 1) if (v and pd.notna(v) and v != 0 and pd.notna(_c0)) else None
                            _row = {'기간': _lab.get(_per, _per), '현재 EPS': _c0,
                                    '7일 전 대비(%)': _chg('7daysAgo'), '30일 전 대비(%)': _chg('30daysAgo'),
                                    '90일 전 대비(%)': _chg('90daysAgo')}
                            if _rv is not None and _per in _rv.index:
                                _rr = _rv.loc[_per]
                                _row['30일 상향(건)'] = _rr.get('upLast30days')
                                _row['30일 하향(건)'] = _rr.get('downLast30days')
                            _rows_t.append(_row)
                        _tsrc('yfinance (애널리스트 EPS 추정치 이력)', live=True)
                        st.dataframe(pd.DataFrame(_rows_t), filters=False, use_container_width=True)
                        st.caption("추정치가 계속 올라가는 종목이 주가도 강하다(이익 추정 리비전 효과). "
                                   "30일·90일 전 대비가 모두 + 이고 상향 건수가 하향보다 많으면 우호적.")
                    elif is_kr_sym:
                        # 2026-10-21 — 삼아알미늄: 주간 수집 대상(value_kr 249종) 밖이라 07-24 한 점에서 멈춰 있었고,
                        #   점 하나를 추세 차트로 그려 축만 보였다. → 수집 대상을 한국 커버 1,300종으로 넓히고(consensus_snapshot),
                        #   화면에서는 오늘 값을 직접 받아 이력 끝에 붙인다. 점이 2개 미만이면 차트 대신 숫자.
                        _kh = pd.DataFrame(_kr_cons_hist(sym8_clean))
                        _klive = _kr_cons_live(sym8_clean)
                        _today = pd.Timestamp.today().normalize()
                        if _klive:
                            _lrow = pd.DataFrame([{'date': _today.strftime('%Y-%m-%d'), 'sym': sym8_clean, **_klive}])
                            _kh = _lrow if _kh.empty else pd.concat(
                                [_kh[_kh['date'] != _lrow['date'].iloc[0]], _lrow], ignore_index=True)
                        if _kh.empty:
                            _nc = load_json(Path('results/consensus_nocover.json')) or {}
                            if sym8_clean in set(_nc.get('none') or []):
                                st.info(f"애널리스트 추정치가 없는 종목입니다(네이버·FnGuide 기준, {_nc.get('date')} 확인). "
                                        "커버하는 증권사가 없으면 컨센서스 자체가 존재하지 않는다.")
                            else:
                                st.info("컨센서스를 받지 못했습니다 — 지금 네이버(wisereport) 응답이 없고 저장된 스냅샷도 없다.")
                        else:
                            _kh['date'] = pd.to_datetime(_kh['date'])
                            _kh = _kh.sort_values('date').reset_index(drop=True)
                            _xd = pd.DatetimeIndex(_kh['date'])
                            _kl = _kh.iloc[-1]
                            def _kv(k, fmt):
                                v = _kl.get(k)
                                return fmt.format(v) if v is not None and pd.notna(v) else '-'
                            def _kchg(k):
                                if len(_kh) < 2 or k not in _kh:
                                    return None
                                v0, v1 = _kh[k].iloc[0], _kh[k].iloc[-1]
                                return (v1 / v0 - 1) * 100 if pd.notna(v0) and pd.notna(v1) and v0 > 0 else None
                            _span = (_xd[-1] - _xd[0]).days
                            _ce, _co = _kchg('eps_0y'), _kchg('op_0y')
                            _stat_grid([('', [("올해 EPS(원)", _kv('eps_0y', '{:,.0f}')),
                                              ("올해 영업이익(억원)", _kv('op_0y', '{:,.0f}')),
                                              ("내년 EPS(원)", _kv('eps_1y', '{:,.0f}')),
                                              (f"올해 EPS 변화({_span}일)" if _span else "올해 EPS 변화", f"{_ce:+.1f}%" if _ce is not None else '-'),
                                              (f"올해 영업이익 변화({_span}일)" if _span else "올해 영업이익 변화", f"{_co:+.1f}%" if _co is not None else '-')])])
                            if len(_kh) >= 2:
                                # EPS(원)와 영업이익(억)은 단위가 수천 배 달라 축을 나눈다(왼쪽 EPS · 오른쪽 영업이익)
                                _fk = go.Figure()
                                if 'eps_0y' in _kh:
                                    _fk.add_trace(go.Scatter(x=_xd, y=_kh['eps_0y'], mode='lines+markers',
                                                             name='올해 EPS(원) · 왼쪽', line=dict(color='#2453C8', width=2.5)))
                                if 'op_0y' in _kh:
                                    _fk.add_trace(go.Scatter(x=_xd, y=_kh['op_0y'], mode='lines+markers', yaxis='y2',
                                                             name='올해 영업이익(억원) · 오른쪽',
                                                             line=dict(color='#7C8AA5', width=2, dash='dot')))
                                # 날짜 눈금은 실제 스냅샷 날짜에만(자동 눈금이 같은 날짜를 여러 번 찍던 것)
                                _fk.update_layout(height=240, margin=dict(l=8, r=8, t=30, b=8),
                                                  legend=dict(orientation='h', y=1.12, x=0, yanchor='bottom'),
                                                  xaxis=dict(tickvals=_xd, tickformat='%Y-%m-%d'),
                                                  yaxis=dict(tickformat=',.0f'),
                                                  yaxis2=dict(overlaying='y', side='right', showgrid=False, tickformat=',.0f'))
                                st.plotly_chart(_fk, use_container_width=True)
                            _gaps = _xd.to_series().diff().dt.days.dropna()
                            _klast = (_kh[~_kh.index.isin([len(_kh) - 1])]['date'].max() if _klive else _xd[-1])
                            _kage = (_today - pd.Timestamp(_klast)).days if pd.notna(_klast) else None
                            st.caption("출처: 네이버금융(FnGuide) 컨센서스 — 주간 스냅샷(results/consensus_history.jsonl)"
                                       + (" + 오늘 조회값" if _klive else "")
                                       + f" · 점 {len(_kh)}개"
                                       + (f" · ⚠️ 점 사이 최대 {int(_gaps.max())}일 공백 — 그 사이 움직임은 모른다" if len(_gaps) and _gaps.max() > 14 else "")
                                       + (f" · 마지막 저장 스냅샷 {pd.Timestamp(_klast).date()}({_kage}일 전)" if _klive and _kage is not None and len(_kh) > 1 else "")
                                       + (f" · ⚠️ {pd.Timestamp(_klast).date()} 값이다({_kage}일 전) — 지금 조회도 실패했다" if not _klive and _kage is not None and _kage > 10 else "")
                                       + (" · 4주 이상 쌓여야 방향을 말할 수 있다" if len(_kh) < 4 else ""))
                    else:
                        st.info("컨센서스 추세 데이터 없음 (yfinance 미제공 · KR 스냅샷 미축적 종목).")

                    # 동종업계
                    st.markdown("### 🧩 동종업계 비교")
                    # 2026-10-20: 버튼 없이 바로(결과는 6시간 캐시 — 같은 종목을 다시 열면 즉시)
                    if True:
                        with st.spinner("동종업계 재무 조회..."):
                            try:
                                _pind, _prows = _peer_rows(sym8_clean, is_kr_sym)
                            except Exception as _pe:
                                _pind, _prows = None, []
                                st.caption(f"`동종업계 조회 실패: {type(_pe).__name__}`")
                        if not _prows or len(_prows) < 2:
                            st.info("같은 업종 종목을 찾지 못했습니다.")
                        else:
                            _tsrc(("KRX 업종분류·DART 저장 손익" if is_kr_sym else "SEC SIC 업종·EDGAR 분기재무")
                                  + " · 시총: 상장목록", live=True)
                            _pdf = pd.DataFrame(_prows)
                            # 동종 중앙값 행 — 이 종목이 업종 안에서 비싼지·빠른지 한눈에(이 종목 제외 중앙값)
                            _peer_only = _pdf.iloc[1:]
                            _med = {c: (float(pd.to_numeric(_peer_only[c], errors='coerce').median())
                                        if pd.to_numeric(_peer_only[c], errors='coerce').notna().any() else None)
                                    for c in ('시총($B)', 'PER(배)', 'PBR(배)', 'PSR(배)', 'ROE(%)', '매출성장(%)', '영업이익률(%)')}
                            _pdf = pd.concat([_pdf, pd.DataFrame([{'종목': f'동종 중앙값({len(_peer_only)}종)', '코드': '', **_med,
                                                                   '기준분기': ''}])], ignore_index=True)
                            st.dataframe(_pdf, filters=False, use_container_width=True)
                            st.caption(f"업종: {_pind}. 첫 행이 이 종목. 같은 업종 안에서 시총이 가장 가까운 순. "
                                       "⚠️ 공식 업종분류는 사업 실제와 다를 수 있다(예: 대형 복합기업). "
                                       "PER·PSR·ROE 는 TTM, PBR 은 마지막 분기말 자본 기준. 적자면 PER, 자본잠식이면 PBR·ROE 는 '-'. "
                                       "PBR 은 ROE 와 같이 읽는다 — ROE 가 높으면 PBR 이 높은 게 정상이다.")

                # ── 🧭 요약 판단 (맨 위) ─────────────────────────────────
                _acch = None if is_kr_sym else _sx.accel_history(sym8_clean)
                with _SEC['summary']:
                    st.markdown("## 🧭 요약 판단")
                    # 2026-10-20 개편: 숫자 카드 5개가 같은 무게로 늘어서 '그래서 어떤데'가 안 보였다 →
                    #   카드마다 상태색(초록·주황·빨강·회색)을 입히고, 리스크·데이터 점검 결과를 카드로 끌어올린다.
                    #   근거 목록은 아래 펼침에(데이터 이상이 있으면 펼친 채로).
                    _L = locals()
                    _hi52 = _cl[_cl.index >= _cl.index.max() - pd.DateOffset(weeks=52)].max()
                    _e12 = _sx.drawdown_episodes(_cl, 12, 20)
                    _risk, _chk_ = [], []
                    try:
                        import analysis_checks as _ac
                        _vb_ = _L.get('_vb') or {}
                        _qq = unified_statements(sym8_clean, is_kr_sym, 'quarter') or []
                        _opm = lambda r: (r['op_income'] / r['revenue'] * 100) if (r.get('op_income') is not None and r.get('revenue')) else None
                        _et = (_L.get('_ed') or {}).get('eps_trend')
                        _e0 = _e30 = None
                        try:
                            if _et is not None and '0y' in _et.index:
                                _e0, _e30 = float(_et.loc['0y', 'current']), float(_et.loc['0y', '30daysAgo'])
                        except Exception:
                            pass
                        _segs_ = _L.get('_segs') or []
                        _risk = _ac.risk_checks(
                            price=float(price_now), high52=float(hist['High'].tail(252).max()),
                            band_rank=(_L.get('_bm') or {}).get('rank'), band_kind=(_L.get('_bm') or {}).get('kind', 'P/E'),
                            band_now=(_L.get('_bm') or {}).get('now'),
                            ttm_net_income=_vb_.get('ttm_net_income'),
                            opm_now=_opm(_qq[0]) if len(_qq) > 4 else None, opm_4q_ago=_opm(_qq[4]) if len(_qq) > 4 else None,
                            debt_to_equity=info.get('debtToEquity'), eps_fy0_now=_e0, eps_fy0_30d=_e30,
                            vol_annual=float(hist['Close'].pct_change().tail(252).std() * (252 ** 0.5) * 100),
                            top_segment_share=max((x.get('revenue_pct') or 0) for x in _segs_) if _segs_ else None,
                            dilution_pct=(_L.get('_dil') or {}).get('pot_pct') if (_L.get('_dil') or {}).get('rows') else None,
                            dilution_note=(f" (리픽싱 시 최대 {_L['_dil']['max_pct']:.1f}%)" if (_L.get('_dil') or {}).get('rows')
                                           and _L['_dil']['max_pct'] > _L['_dil']['pot_pct'] + 0.05 else ''))
                        _chk_ = _ac.integrity_checks(
                            today=pd.Timestamp.today().date(), last_price_date=hist.index[-1].date(),
                            latest_quarter=_qq[0]['period'] if _qq else None,
                            per_ttm=_vb_.get('per_ttm'), yf_trailing_pe=info.get('trailingPE'),
                            rev_ttm=_vb_.get('ttm_revenue'), yf_total_revenue=info.get('totalRevenue'),
                            mcap=info.get('marketCap'), price=float(price_now),
                            shares=(_shares_now(sym8_clean, is_kr_sym, info) if is_kr_sym else info.get('sharesOutstanding')),
                            seg_check_pct=_L.get('_seg_chk_pct'), seg_src_ai=bool(_L.get('_seg_chk_ai')),
                            n_analysts=info.get('numberOfAnalystOpinions'), is_kr=is_kr_sym, bad_bars=_L.get('_n_bad_bar', 0))
                    except Exception as _ace:
                        st.caption(f"`리스크·데이터 점검 실패: {type(_ace).__name__}: {_ace}`")

                    import html as _hx                     # _h 는 이 함수 안에서 다른 값으로 재사용된다(DART health)
                    def _kpi(label, value, sub, tone):
                        return (f'<div class="mo-kpi {tone}"><span class="l">{_hx.escape(label)}</span>'
                                f'<span class="v">{_hx.escape(value)}</span><span class="s">{_hx.escape(sub)}</span></div>')
                    _cards = []
                    # 추세 (2026-10-21) — 고점 대비 낙폭만으로 '추세'를 말하지 않는다. Trend Template 8조건.
                    _tpl = _L.get('_ttp') or _sx.trend_template(hist['Close'], hist.get('High'), hist.get('Low'))
                    if _tpl.get('n') is None:
                        _cards.append(_kpi('추세', '-', _tpl['state'], 'na'))
                    else:
                        _wk = _tpl.get('weeks_since_high')
                        _cards.append(_kpi('추세', _tpl['state'],
                                           f"조건 {_tpl['n']}/8 · 고점 {_tpl['from_high']:+.0f}% · 저점 {_tpl['from_low']:+.0f}%"
                                           + (f" · 신고가 후 {_wk}주" if _wk else ' · 이번 주 신고가'),
                                           _tpl['tone']))
                    # 밸류 (2026-10-21) — '상위 26%'는 싸다는 건지 비싸다는 건지 안 읽혔다 → 지금 배수를 크게,
                    #   과거 몇 %의 기간보다 비싼지를 아래에. 높을수록 비쌈.
                    _bm_ = _L.get('_bm')
                    if _bm_:
                        _rk = _bm_['rank']
                        _cards.append(_kpi(f"밸류 · {_bm_['kind']}", f"{_bm_['now']:.1f}배",
                                           f"과거 {_rk:.0f}%의 기간보다 비쌈 · 중앙값 {_bm_['pct'][50]:.1f}배",
                                           'bad' if _rk >= 80 else 'mid' if _rk >= 60 else 'good'))
                    else:
                        _cards.append(_kpi('밸류', '-', '밴드 계산 불가', 'na'))
                    # 이익 — KR 은 이익 가속 '신호'(US 주간 규칙)가 없으니 분기 영업이익 추이로 판정(흑자전환·적자 축소 포함)
                    _etr = _sx.earnings_trend(_L.get('_qr') or [], is_kr=is_kr_sym)
                    _el = _etr.get('last') or {}
                    _ef = (lambda v: (f"{v/1e12:+,.1f}조" if abs(v) >= 1e12 else f"{v/1e8:+,.0f}억") if is_kr_sym
                           else (f"{v/1e9:+,.2f}B" if abs(v) >= 1e9 else f"{v/1e6:+,.0f}M"))
                    _esub = ''
                    if _el.get('op') is not None and pd.notna(_el.get('op')):
                        _esub = (f"{_etr.get('level')} · " if _etr.get('level') and _etr.get('level') not in _etr['state'] else '') + (f"{_el['분기']} 영업익 {_ef(_el['op'])}"
                                 + (f" (전년 {_ef(_el['prev'])})" if _el.get('prev') is not None else '')
                                 + (f" · 매출 {_el['rev_yoy']:+.0f}%" if _el.get('rev_yoy') is not None else '')
                                 + (" · ⚠️ 기저효과" if _etr.get('base_warn') else ''))
                    if is_kr_sym:
                        _cards.append(_kpi('이익 추이', _etr['state'], _esub or _etr.get('detail', ''), _etr['tone']))
                    elif _acch and _acch['rows']:
                        _lr = _acch['rows'][0]
                        _rec = (pd.Timestamp.today() - pd.Timestamp(_lr['주차'])).days <= 365
                        _cards.append(_kpi('이익 가속 신호', str(_lr['주차']),
                                           (f"그 해 {_lr['회차']}회차 · " if _lr['회차'] else '') + ('최근 1년 내' if _rec else '1년 넘음')
                                           + (f" · 지금 {_etr['state']}" if _etr.get('rows') else ''),
                                           'good' if _rec else 'na'))
                    else:
                        _cards.append(_kpi('이익 추이', _etr['state'], _esub or '2018년 이후 이익 가속 신호 없음', _etr['tone']))
                    _tt, _gg = _L.get('_total'), _L.get('_grade')
                    _cards.append(_kpi('CANSLIM', f"{_gg}" if _gg else '-', f"{_tt:.0f}점" if isinstance(_tt, (int, float)) else '점수 없음',
                                       'na' if not _gg else ('good' if str(_gg)[:1] in 'AB' else 'mid' if str(_gg)[:1] == 'C' else 'bad')))
                    _nr = sum(r['state'] == 'warn' for r in _risk)
                    _cards.append(_kpi('리스크', f"{_nr}개 해당" if _risk else '-',
                                       ' · '.join(r['name'] for r in _risk if r['state'] == 'warn')[:40] or '해당 없음',
                                       'na' if not _risk else ('good' if _nr == 0 else 'mid' if _nr <= 2 else 'bad')))
                    _nd = sum(r['state'] == 'warn' for r in _chk_)
                    _cards.append(_kpi('데이터', f"이상 {_nd}건" if _nd else ('정상' if _chk_ else '-'),
                                       ' · '.join(r['name'] for r in _chk_ if r['state'] == 'warn')[:40] or
                                       f"{sum(r['state'] == 'ok' for r in _chk_)}개 항목 확인",
                                       'na' if not _chk_ else ('bad' if _nd else 'good')))
                    st.markdown(f'<div class="mo-kpis">{"".join(_cards)}</div>', unsafe_allow_html=True)
                    if _nd:
                        st.error("데이터 이상이 있습니다 — 아래 숫자 중 일부가 틀렸을 수 있습니다. '근거 보기'에서 무엇이 이상한지 확인하세요.")

                    _ico = {'warn': '⚠️', 'ok': '✅', 'na': '·'}
                    _ord = lambda rs: sorted(rs, key=lambda r: {'warn': 0, 'ok': 1, 'na': 2}[r['state']])
                    with st.expander("근거 보기 — 리스크 점검 · 데이터 점검", expanded=bool(_nd)):
                        _rc1, _rc2 = st.columns(2, gap='large')
                        with _rc1:
                            st.markdown(f"**⚠️ 리스크 점검** — {sum(r['state'] != 'na' for r in _risk)}개 판정 중 {_nr}개 해당")
                            st.markdown("\n".join(f"- {_ico[r['state']]} **{r['name']}** · {r['detail']}" for r in _ord(_risk)))
                            st.caption("사실·규칙 판정(매수·매도 의견 아님). '·'는 데이터가 없어 판정하지 않은 항목.")
                        with _rc2:
                            st.markdown(f"**🧪 데이터 점검** — {sum(r['state'] != 'na' for r in _chk_)}개 확인 · "
                                        + (f"이상 {_nd}건" if _nd else "이상 없음"))
                            st.markdown("\n".join(f"- {_ico[r['state']]} **{r['name']}** · {r['detail']}" for r in _ord(_chk_)))
                            st.caption("이 화면 숫자가 서로 맞는지·최신인지 종목마다 그 자리에서 확인. '확인 불가(·)'는 통과로 치지 않는다.")
                        # 2026-10-24 — 분기 이익 표(7열)가 반쪽 칸을 넘어 가로 드래그가 생겼다 → 추세·분기 이익을 위아래 전체 폭으로
                        if _tpl.get('items'):
                            st.markdown(f"**📈 추세 — Trend Template {_tpl['n']}/8**")
                            st.markdown("\n".join(f"- {'✅' if ok else '⚠️'} **{nm}** · {dt}" for nm, ok, dt in _tpl['items']))
                            st.caption("마크 미너비니의 주도주 추세 조건(이동평균 정배열 + 저점 대비 +30% 이상 + 고점 −25% 이내). "
                                       "8/8 = 상승 추세 · 6~7 = 일부 이탈 · 4~5 = 약화 · 3 이하 = 하락·바닥. "
                                       "고점 −20% 는 추세가 아니라 **보유 중 청산선**이라 리스크 점검에 따로 둔다.")
                        if _etr.get('rows'):
                            st.markdown(f"**💰 분기 이익 — {_etr['state']}**"
                                        + (f" · 수준 {_etr['level']}" if _etr.get('level') and _etr['level'] not in _etr['state'] else '')
                                        + f" · 최근 8분기 중 가속 {_etr.get('acc_8q', 0)}회")
                            _eu = ('억원', 1e8) if is_kr_sym else ('$M', 1e6)
                            _tsrc(_L.get('_qsrc') or '분기 손익', live=True)
                            # 2026-10-21 실화면 — None 만 있는 열이 글자 'None' 으로 찍히고, 머리말이 길어 반쪽 칸을 넘쳤다
                            _nn = lambda v, d=1: float('nan') if v is None or pd.isna(v) else round(float(v), d)
                            _etab = pd.DataFrame([{
                                '분기': r['분기'], f"영업익({_eu[0]})": _nn(None if r['op'] is None else r['op'] / _eu[1], 0),
                                f"전년 동기({_eu[0]})": _nn(None if r['prev'] is None else r['prev'] / _eu[1], 0),
                                '영업익 YoY(%)': _nn(r['yoy']), '매출 YoY(%)': _nn(r['rev_yoy']),
                                '개선폭÷매출(%p)': _nn(r['oi_pp']),
                                '가속': '가속' if r['acc'] else ('-' if r['acc'] is None else '')}
                                for r in _etr['rows'][:6]])
                            if _etab['영업익 YoY(%)'].isna().all():      # 적자 구간이라 전부 '-' 면 열을 뺀다
                                _etab = _etab.drop(columns=['영업익 YoY(%)'])
                            st.dataframe(_etab, filters=False)
                            st.caption("**가속 = 매출 YoY 와 '개선폭÷매출'(1년 전 대비 영업익 증가분 ÷ 매출)이 둘 다 직전 분기보다 커진 분기** — 미국 이익 가속 신호와 같은 정의"
                                       "(이익 증가를 매출로 나눠 적자에서도 측정된다. 그래서 '이익 감소'인데 '가속'일 수 있다 = 감소 폭이 줄었다). "
                                       "한 분기는 기저효과·일회성일 수 있어 연속 분기 수를 본다: 1분기 확인 전 · 2분기 가속 · "
                                       "3분기+ 강한 가속(미너비니 'Code 33'). ⚠️ 연속 조건의 수익 우위는 아직 백테스트 전 — 상태 표시일 뿐 매수 신호 아님. "
                                       "기저효과 = 1년 전 분기 이익이 최근 8분기 중앙값의 25% 미만.")

                    if _acch and _acch['rows']:
                        with st.expander(f"🚀 이익 가속 신호 이력 — {len(_acch['rows'])}회"):
                            _tsrc('Yahoo Finance(주가)·SEC EDGAR(분기재무) → leaders_accel.json',
                                  path='results/leaders_accel.json')
                            st.dataframe(pd.DataFrame(_acch['rows']), use_container_width=True)
                            st.caption("주도주 진입 규칙(매출·영업이익 성장 동시 가속 + 그 주 +10% + 유동성)이 이 종목에 걸린 주. "
                                       "회차는 그 해 안에서 센 순번 — 11회를 넘으면 초과수익이 꺾이는 경향.")
                    elif not is_kr_sym and _acch is not None:
                        st.caption("이익 가속 신호 이력 없음 — 이 종목은 2018년 이후 진입 규칙에 걸린 적이 없습니다.")

                # ── 🎯 매매 판단 — 규칙 계산 (2026-10-23) ─────────────────────────
                #   목표가(컨센서스·역사적 PER·PEG) · 다운사이드(정류장 통계) · 손절 참고선 · 매수/관망/탈출 판정 · 비중.
                #   계산은 trade_plan.py(테스트 있음). 원칙 v1: 위성은 가격 손절 대신 크기(총자산 1.5%)로 위험 관리.
                with _SEC['plan']:
                    try:
                        import trade_plan as _tp
                        import html as _hx
                        _LP = locals()
                        _c_all = hist['Close'].dropna().copy()
                        _c_all.index = pd.to_datetime(_c_all.index)
                        if getattr(_c_all.index, 'tz', None) is not None:
                            _c_all.index = _c_all.index.tz_localize(None)
                        _v_all = hist['Volume'].reindex(hist.index).values if 'Volume' in hist else None
                        _v_all = pd.Series(_v_all, index=_c_all.index) if _v_all is not None and len(_v_all) == len(_c_all) else None
                        _p = float(price_now)
                        _ma50 = float(_c_all.rolling(50).mean().iloc[-1]) if len(_c_all) >= 50 else None
                        _ma200s = _c_all.rolling(200).mean()
                        _ma200 = float(_ma200s.iloc[-1]) if len(_c_all) >= 200 else None
                        _ma200p = float(_ma200s.iloc[-22]) if len(_c_all) >= 222 else None
                        _hi52v = float(hist['High'].tail(252).max())
                        _dd52 = (_p / _hi52v - 1) * 100 if _hi52v else None
                        _tt = _LP.get('_tpl') or _sx.trend_template(hist['Close'], hist.get('High'), hist.get('Low'))
                        _rsi_now = _tp.rsi(_c_all)
                        _mac = _tp.macd(_c_all)
                        _liv = _tp.livermore(_c_all, _v_all)
                        _vd = _tp.verdict(price=_p, ma50=_ma50, ma200=_ma200, ma200_prev=_ma200p, tt_n=_tt.get('n'),
                                          rsi_v=_rsi_now, macd_d=_mac, canslim_grade=_LP.get('_gg'), liv=_liv, dd52=_dd52)
                        _sw = _tp.swings(_c_all, theta=10)
                        _cur = _sw['current'] or {}
                        _low_piv = next((pv['price'] for pv in reversed(_sw['pivots']) if pv['type'] == 'L'), None)
                        _st = _tp.stops(_p, ma50=_ma50, ma200=_ma200, last_low=_low_piv)
                        _vb2 = _LP.get('_vb') or {}
                        _bd = (_LP.get('_band') or {})
                        _tg = _tp.targets(_p, cons={'mean': info.get('targetMeanPrice'), 'high': info.get('targetHighPrice'),
                                                    'n': info.get('numberOfAnalystOpinions')},
                                          band=_bd.get('pe') or _bd.get('main'), eps_fwd=_vb2.get('eps_12mf'),
                                          eps_ttm=_vb2.get('eps_ttm'), hi52=_hi52v)
                        _volA = float(_c_all.pct_change().tail(252).std() * (252 ** 0.5) * 100)
                        # 기준 목표 = 근거별 목표가의 **중앙값**(한 근거에 휘둘리지 않게 — 2026-10-23 실화면: 애널 1명 제외 시
                        #   '역사적 P/S 중앙값 −42%' 하나가 기준이 됐다). 범위(최저~최고)를 같이 보인다.
                        _base = None
                        if _tg:
                            _pz = sorted(t['price'] for t in _tg)
                            _bp = float(np.median(_pz))
                            _base = {'name': f"근거 {len(_tg)}개 중앙값", 'price': _bp, 'up': (_bp / _p - 1) * 100,
                                     'lo': (_pz[0] / _p - 1) * 100, 'hi': (_pz[-1] / _p - 1) * 100}
                        # 조건은 '지금 위치'가 아니라 이 스윙이 **이미 도달한 깊이/높이**(빠졌다 반등 중이어도 그 깊이까지는 간 것)
                        _ns_dn = _tp.next_stops(_sw['declines'], _cur.get('reached', 0) if _cur.get('dir') == 'down' else 0)
                        _ns_up = _tp.next_stops(_sw['rallies'], _cur.get('reached', 0) if _cur.get('dir') == 'up' else 0)
                        # 역사적 다운사이드: 지금 하락 중이면 '이만큼 빠진 스윙들의 최종 깊이 중앙값', 상승 중이면 '스윙 하락 중앙값'
                        if _cur.get('dir') == 'down' and _cur.get('reached', 0) >= 10 and _ns_dn['median_final']:
                            _dn_px = _cur['from'] * (1 - _ns_dn['median_final'] / 100)
                        elif _sw['declines']:
                            _dn_px = _p * (1 - float(np.median(_sw['declines'])) / 100)
                        else:
                            _dn_px = None
                        _dn_pct = (_dn_px / _p - 1) * 100 if _dn_px else None
                        _rr = ((_base['price'] - _p) / (_p - _st['s1'])) if _base and _base['price'] > _p else None
                        _risk_b = st.session_state.get('plan_risk', 1.0)
                        _slot = st.session_state.get('plan_slot', 1.5)
                        _ps = _tp.position_size(verdict_state=_vd['state'], stop_pct=_st['s1_pct'], vol_annual=_volA,
                                                risk_budget=_risk_b, slot_cap=_slot, trim_cap=_slot * 3)
                        _fs = _tp.forward_similar(_c_all)

                        st.markdown("## 🎯 매매 판단 — 규칙 계산")
                        _pf_ = lambda v: (f"₩{v:,.0f}" if is_kr_sym else f"\\${v:,.2f}") if v else '-'   # $ 두 개가 수식으로 렌더되지 않게
                        _plan_cards = [
                            _kpi('판정', _vd['state'], (' · '.join(_vd['exit']) if _vd['exit'] else f"체크 {_vd['ok']}/{len(_vd['checks'])} 통과"), _vd['tone']),
                            _kpi('목표 중앙값', f"{_base['up']:+.0f}%" if _base else '-',
                                 (f"{_pf_(_base['price']).replace(chr(92), '')} · 범위 {_base['lo']:+.0f}~{_base['hi']:+.0f}% · {_base['name']}" if _base else '목표가 계산 불가'),
                                 'na' if not _base else ('good' if _base['up'] >= 20 else 'mid' if _base['up'] > 0 else 'bad')),
                            _kpi('1차 손절(참고)', f"{_st['s1_pct']:.0f}%", f"{_pf_(_st['s1'])} · 2차 {_pf_(_st['s2'])}({_st['s2_pct']:.0f}%)", 'mid'),
                            _kpi('역사적 다운사이드', f"{_dn_pct:.0f}%" if _dn_pct is not None else '-',
                                 (f"{_pf_(_dn_px)} · 스윙 {len(_sw['declines'])}회 중앙값" if _dn_px else '표본 없음'),
                                 'na' if _dn_pct is None else ('bad' if _dn_pct <= -30 else 'mid')),
                            _kpi('보상 ÷ 위험', f"{_rr:.1f}배" if _rr else '-', ('목표 중앙값 상승폭 ÷ 1차 손절폭' if _rr else '목표 중앙값이 현재가 아래'), 'na' if not _rr else ('good' if _rr >= 3 else 'mid' if _rr >= 1.5 else 'bad')),
                            _kpi('투입 가능 비중', f"{_ps['rec']:.1f}%",
                                 (f"판정이 '매수 가능 영역' 아님 → 신규 0 (조건 충족 시 {min(_ps['risk_size'], _slot) * (0.5 if _ps['half'] else 1):.1f}%)"
                                  if _ps['rec'] == 0 else ("총자산 기준 · 변동성 60%↑ 절반" if _ps['half'] else "총자산 기준 · 원칙 v1 상한")),
                                 'good' if _ps['rec'] > 0 else 'na'),
                        ]
                        st.markdown('<div class="mo-kpis">' + ''.join(_plan_cards).replace('\\$', '$') + '</div>', unsafe_allow_html=True)

                        _pl, _pr = st.columns(2, gap='large')
                        with _pl:
                            st.markdown("**🎯 목표가 — 근거별**")
                            if _tg:
                                _tsrc('yfinance(애널 목표가) · 멀티플 밴드(공시 TTM) · 컨센서스 EPS — 이 화면 계산', live=True)
                                st.dataframe(pd.DataFrame([{'근거': t['name'], f"목표가({'원' if is_kr_sym else '$'})": t['price'],
                                                            '업사이드(%)': round(t['up'], 1), '계산': t['basis']} for t in _tg]),
                                             filters=False)
                            else:
                                st.caption("목표가를 계산할 재료(컨센서스·PER 밴드·12MF EPS)가 없다.")
                            st.markdown("**🛑 손절 참고선**")
                            st.markdown(f"- 1차 {_pf_(_st['s1'])} ({_st['s1_pct']:.0f}%) — {_st['why1']}\n"
                                        f"- 2차 {_pf_(_st['s2'])} ({_st['s2_pct']:.0f}%) — {_st['why2']}\n"
                                        f"- ⚠️ **매매 원칙 v1**: 위성 종목은 가격 손절을 쓰지 않는다(백테스트 CAGR 15.4% → 9.9%). "
                                        f"대신 **비중**(한 종목 총자산 {_slot:.1f}%)이 손절을 대신한다 — 위 선은 트레이더식 참고값.")
                        with _pr:
                            st.markdown(f"**✅ 판정 근거 — {_vd['state']}**")
                            _ico = {'ok': '✅', 'warn': '⚠️', 'bad': '❌', 'na': '·'}
                            st.markdown("\n".join(f"- {_ico[sx_]} **{n_}** · {t_}" for n_, sx_, t_ in _vd['checks']))
                            if _liv.get('pivot'):
                                st.caption(f"리버모어 피벗 {_pf_(_liv['pivot'])}(직전 1년 최고 종가, 최근 2주 제외) · 지금 {_liv['gap']:+.1f}% · "
                                           f"거래량 {('%.1f배' % _liv['vol_ratio']) if _liv.get('vol_ratio') else '-'}(최근 5일 ÷ 그 전 20일). "
                                           f"피라미딩은 첫 매수가 수익일 때만 {_pf_(_liv['adds'][0])}·{_pf_(_liv['adds'][1])}(피벗 +5%·+10%)에서 — "
                                           "손실 중 추가(물타기)는 금지. 원칙 v1 은 불타기 기본 OFF(검증상 수익 개선 없음).")

                        # 🚏 정류장
                        st.markdown("### 🚏 정류장 — 이만큼 움직였으면 어디까지 갔나")
                        _nd = len(_sw['declines']); _nr = len(_sw['rallies'])
                        if _cur:
                            _dirk = '하락' if _cur['dir'] == 'down' else '상승'
                            _nsx = _ns_dn if _cur['dir'] == 'down' else _ns_up
                            _rch = _cur.get('reached', _cur['move'])
                            st.markdown(f"지금은 **{_cur['from_date']:%Y-%m-%d} {('고점' if _cur['dir'] == 'down' else '저점')} {_pf_(_cur['from'])}에서 "
                                        f"{_dirk} 스윙 진행 중** — 이번 스윙에서 최대 {_rch:.0f}%까지 갔고 지금은 {_cur['move']:.0f}%. "
                                        + (f"과거 {_dirk} 스윙 {(_nd if _cur['dir'] == 'down' else _nr)}회 중 {_rch:.0f}% 이상 간 것이 **{_nsx['n']}회**"
                                           + (f", 그 스윙들의 최종 {_dirk}폭 중앙값은 **{_nsx['median_final']:.0f}%**." if _nsx['median_final'] else '.')
                                           if _rch >= 10 else f"아직 10% 미만이라 스윙으로 치기 전(과거 {_dirk} 스윙 중앙값 "
                                           f"{float(np.median(_sw['declines'] if _cur['dir'] == 'down' else _sw['rallies']) if (_nd if _cur['dir'] == 'down' else _nr) else 0):.0f}%)."))
                        _g1, _g2 = st.columns(2, gap='large')
                        for _col, _nm2, _sz, _nsx, _clr in ((_g1, '하락', _sw['declines'], _ns_dn, '#DC2626'), (_g2, '상승', _sw['rallies'], _ns_up, '#16A34A')):
                            with _col:
                                _gm = _tp.gap_map(_sz)
                                if _gm:
                                    _fg = go.Figure(go.Bar(x=[f"{int(g['from'])}→{int(g['to'])}" for g in _gm], y=[g['p'] for g in _gm],
                                                           marker_color=_clr, text=[f"{g['p']:.0f}%<br>n={g['n']}" for g in _gm],
                                                           textposition='outside', cliponaxis=False))
                                    _fg.update_layout(height=240, margin=dict(l=0, r=0, t=30, b=0), yaxis=dict(range=[0, 115], ticksuffix='%'),
                                                      title=dict(text=f"{_nm2} 스윙: x% 넘으면 x+5% 도 넘은 비율", font=dict(size=13)))
                                    st.plotly_chart(_fg, use_container_width=True)
                                if _nsx['rows'] and _nsx['n']:
                                    _now_m = _cur.get('reached', 0) if _cur.get('dir') == ('down' if _nm2 == '하락' else 'up') else 0
                                    _tsrc(f"일봉 종가 지그재그(10% 되돌림 = 새 스윙) · {_c_all.index[0]:%Y-%m}~", live=True)
                                    st.dataframe(pd.DataFrame([{f"{_nm2} 도달(%)": r['level'], '도달(회)': r['hit'],
                                                                '확률(%)': None if r['p'] is None else round(r['p'])}
                                                               for r in _nsx['rows'][:7]]), filters=False)
                                    st.caption(f"기준: 지금까지 {_now_m:.0f}% {_nm2}한 스윙 {_nsx['n']}회"
                                               + (" — ⚠️ 표본 8회 미만, 참고 불가" if _nsx['n'] < 8 else ''))
                        st.caption("막대가 높은 구간 = 정류장 사이가 먼 곳: 그 지점을 넘으면 다음 5%도 대부분 넘었다(멈추지 않고 간다). "
                                   "낮은 구간 = 자주 멈추던 정류장. 스윙은 일봉 종가 기준, 반대로 10% 이상 되돌리면 끝난 것으로 본다. "
                                   "**이 종목 자체의 과거 빈도**일 뿐 — 시장 국면·실적이 바뀌면 달라진다.")

                        if _fs and _fs.get('n'):
                            st.markdown("### 📈 비슷한 자리에서 산 날의 6개월 뒤")
                            _stat_grid([('', [('비슷한 날', f"{_fs['n']}번"), ('중앙값', f"{_fs['median']:+.0f}%", True),
                                              ('하위 10%', f"{_fs['p10']:+.0f}%", True), ('상위 10%', f"{_fs['p90']:+.0f}%", True),
                                              ('오른 비율', f"{_fs['win']:.0f}%")])])
                            st.caption(f"지금처럼 52주 고점 대비 {_fs['dd_now']:.0f}%(±5%p)였던 날을 20거래일 간격으로 뽑아 126거래일(약 6개월) 뒤 수익을 셌다. "
                                       + ("⚠️ 10번 미만 — 참고 불가. " if _fs['n'] < 10 else '') + "기대수익 '분포'이지 예측이 아니다.")

                        with st.expander("💼 비중 계산 조건 바꾸기"):
                            _k1, _k2 = st.columns(2)
                            _k1.number_input("한 번에 잃어도 되는 금액(총자산 %)", 0.25, 5.0, float(_risk_b), 0.25, key='plan_risk')
                            _k2.number_input("한 종목 상한(총자산 %) — 원칙 v1 위성 한 칸 1.5", 0.5, 20.0, float(_slot), 0.5, key='plan_slot')
                            st.caption(f"위험예산식 비중 = {_risk_b:.2f}% ÷ 1차 손절폭 {abs(_st['s1_pct']):.0f}% = **{_ps['risk_size']:.1f}%** → "
                                       f"상한 {_slot:.1f}%와 비교해 작은 쪽" + (" → 연 변동성 60% 이상이라 절반" if _ps['half'] else '')
                                       + f". 판정이 '매수 가능 영역'이 아니면 신규 투입 0. 한 종목 최대(트림선) {_ps['trim_cap']:.1f}%. "
                                       "AI 판단이 아니라 같은 입력이면 같은 답이 나오는 규칙이다 — 포트 전체(섹터 쏠림·현금)는 🛡️ 내 포트폴리오 탭에서.")
                        st.caption("⚠️ 전부 공개 데이터와 정해진 규칙으로 계산한 참고값이며 투자 권유가 아니다. 판정·확률은 과거 빈도이고, "
                                   "모든 투자 판단과 책임은 이용자에게 있다.")
                    except Exception as _e_plan:
                        st.caption(f"`매매 판단 계산 실패: {type(_e_plan).__name__}: {str(_e_plan)[:120]}`")

        else:
            st.caption("예: TSLA · NVDA · 005930(삼성전자) · 000660(SK하이닉스)")


with tab7:
    _tab_analysis()


# ════════════════════════════════════════════════════════════════════
# 탭: 포트폴리오 관리 + 🛡️ 원칙 가드레일
# (2026-07-02 탭 재편 때 대시보드에서 12일간 빠져 있었음 — 2026-07-14 복원 + 준수이력 추가)
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, max_entries=48)
def _fetch_pf_price(sym: str, market: str):
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start)
        return float(df['Close'].iloc[-1]) if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=1800, max_entries=48)
def _pf_trail(sym: str, market: str, buy_date: str):
    """(매수 후 주봉 최고가, 마지막 52주 신고가 이후 경과 주) — 가드레일 트레일링용.

    2026-08-16: 검증된 청산 규칙이 '매수가 대비 −8%'가 아니라 '고점 대비 −20%
    트레일링'이라 고점이 필요하다. 판정은 백테(leaders_alloc)와 같은 주봉 종가로 한다.
    52주 신고가 기준일은 '마지막 신고가'와 '매수 주차' 중 나중 것 — 매수 전부터
    신고가를 못 낸 종목이 당일 축소 대상이 되는 것을 막는다.
    """
    try:
        w = None
        # 2026-10-25: US 종목이면 price_store(leaders_build 주봉, 같은 W-MON anchor)를
        # 먼저 본다 — 10일 이내로 신선할 때만 믿는다(weekly-accel 크론 지연 대비,
        # 낡은 캐시로 트레일링 피크를 잘못 계산하면 가드레일이 틀린 판정을 내린다).
        # KR은 price_store에 데이터가 없어 항상 FDR로 간다.
        if market != 'KR':
            try:
                import price_store
                _cached = price_store.get(sym, 'US')
                if _cached is not None and len(_cached) >= 10:
                    _last = pd.Timestamp(_cached.index[-1])
                    if (pd.Timestamp.today().normalize() - _last).days <= 10:
                        w = _cached['Close'].dropna()
            except Exception:
                w = None
        if w is None:
            import FinanceDataReader as fdr
            code = sym.replace('.KS', '').replace('.KQ', '')
            fdr_sym = code if market == 'KR' else sym
            start = (datetime.now() - timedelta(days=520)).strftime('%Y-%m-%d')
            s = fdr.DataReader(fdr_sym, start)['Close'].dropna()
            if s.empty:
                return None, None
            w = s.resample('W-MON', label='left', closed='left').last().dropna()
            if len(w) and (pd.Timestamp(s.index[-1]) - pd.Timestamp(w.index[-1])).days < 4:
                w = w.iloc[:-1]
        if not len(w):
            return None, None
        bd = pd.Timestamp(buy_date).normalize() if buy_date else w.index[0]
        bw = bd - timedelta(days=bd.weekday())
        since = w[w.index >= bw]
        peak = float(since.max()) if len(since) else float(w.iloc[-1])
        hi = w.index[(w >= w.rolling(52, min_periods=10).max() - 1e-9).values]
        ref = max(hi[-1], bw) if len(hi) else bw
        return peak, (pd.Timestamp(w.index[-1]) - ref).days / 7
    except Exception:
        return None, None


@st.cache_data(ttl=600, max_entries=48)
def _px_series(sym: str, market: str, days: int = 75):
    """(현재가, 최근 45영업일 종가 리스트) — 현재가와 추세 스파크라인을 호출 1회로."""
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        c = fdr.DataReader(fdr_sym, start)['Close'].dropna()
        if c.empty:
            return None, []
        return float(c.iloc[-1]), [round(float(x), 4) for x in c.tail(45)]
    except Exception:
        return None, []


@st.cache_data(ttl=1800)
def _marcap_join() -> dict:
    """sym → 시총. 기존 산출물(screener·mdd·returns)에서 조인 — 추가 API 호출 없음."""
    m = {}
    for _p in (SCREENER_JSON, MDD_JSON, Path('results/returns.json')):
        d = load_json(_p) or {}
        for s in d.get('stocks', []):
            if s.get('marcap') and s['sym'] not in m:
                m[s['sym']] = s['marcap']
    return m

# ── 화면 하단 설정 (사이드바 제거 → 페이지 맨 아래) ───────────────────

# ════════════════════════════════════════════════════════════════════
# 🛡️ 내 포트폴리오 — 원칙 가드레일  (2026-10-10 복원)
# ────────────────────────────────────────────────────────────────────
# 왜 비어 있었나: 08-22 에 "입력이 없어 처음부터 빈 화면"이라며 탭을 지웠다.
# 그런데 입력이 없던 이유는 **보유 종목을 넣을 화면이 아예 없었기** 때문이다.
# data/portfolio.json 은 git 전체 이력에 한 번도 존재한 적이 없다. 엔진
# (guardrail.evaluate)과 헬퍼(_fetch_pf_price · _pf_trail)는 내내 살아 있었다.
# 그래서 이번엔 **입력부터** 만든다.
#
# ⚠️ Streamlit Cloud 는 파일시스템이 임시다. 저장해도 재배포하면 사라지므로
#    세션 상태를 1순위로 쓰고 파일 저장은 되면 하는 보너스로 둔다. 영구 보관이
#    필요하면 맨 아래 '복사용 JSON' 을 repo 의 data/portfolio.json 에 넣는다.
# ════════════════════════════════════════════════════════════════════
with tab_pf, guard('포트폴리오 가드레일'):
    import guardrail as _gr
    import access as _acc
    # 2026-10-21 — 로그인 + 테스트 명단 통과해야 아래가 열린다(공개 사이트라 남의 화면에 보이면 안 된다)
    if _acc.gate('내 포트폴리오'):

        _PF_PATH = Path('data/portfolio.json')
        _PF_COLS = ['sym', 'name', 'market', 'qty', 'avg_cost', 'buy_date']

        import user_store as _us
        _pf_email = _acc.email()

        if _pf_email:   # 2026-10-21 저장 연결 상태를 늘 보이게 — '안 떠 있음'을 추측 말고 화면에서 확인
            if 'pf_db_ping' not in st.session_state:
                st.session_state['pf_db_ping'] = _us.ping()
            _pok, _pmsg = st.session_state['pf_db_ping']
            (st.caption if _pok else st.warning)(f"🔐 계정 저장 연결: {'정상' if _pok else '오류 — ' + _pmsg}")
            if st.session_state.get('pf_db_msg'):
                st.caption(st.session_state.pop('pf_db_msg'))

        def _pf_load():
            if 'pf_rows' in st.session_state:
                return st.session_state['pf_rows']
            # 2026-10-21: data/portfolio.json(서버 공용 파일)은 읽지 않는다 — 한 사람이 저장하면 다음 방문자에게 보였다.
            #   대신 계정별 암호화 저장(user_store)에서 세션당 한 번 불러온다.
            if _us.ready() and _pf_email and not st.session_state.get('_pf_db_tried'):
                st.session_state['_pf_db_tried'] = True
                try:
                    _d = _us.load(_pf_email)
                    if _d:
                        st.session_state['pf_rows'] = _d.get('positions') or []
                        st.session_state.setdefault('cand_list', _d.get('candidates') or [])
                        st.session_state['pf_cap'] = int(_d.get('total_capital') or 0)
                        st.session_state['pf_db_asof'] = _d.get('_updated_at')
                        return st.session_state['pf_rows']
                except Exception as _e:
                    st.warning(f'저장된 포트폴리오를 불러오지 못했습니다: {str(_e)[:80]}')
            return []

        st.markdown("### 🛡️ 원칙 가드레일")
        st.caption("**2026-06-23 정립한 원칙을 코드가 강제합니다.** "
                   "종목당 매입 20% 상한 · 평가 40% 초과 시 30%로 트림 · "
                   "청산은 **고점 대비 −20%**(진입가 대비 아님) · "
                   "3주간 52주 신고가 미갱신 시 30% 축소 · 레버리지 ETF 합계 10% 이내.")

        # ── 🔐 토스 계좌 자동 연동 (2026-10-14) ─────────────────────────────
        # 토스 Open API 는 허용 IP(고정)에서만 응답한다 → 이 사이트(유동 IP)는 직접 못 부른다.
        # 노트북(tools/toss_sync.py)이 매일 받아 **암호화**해 올리고, 여기서는 비밀번호로만 푼다.
        # 저장소·사이트가 공개라 평문 잔고는 어디에도 두지 않는다. 키도 이 사이트엔 없다.
        import pf_vault as _pv
        _tz_head = _pv.peek()
        if _tz_head and _acc.is_owner():
            with st.container(border=True):
                _tz_c1, _tz_c2 = st.columns([3, 1])
                _tz_c1.markdown(f"**🔐 토스 계좌 연동** · 자료 기준 {_tz_head.get('asof') or '-'} "
                                "(노트북이 매일 06:40 KST 갱신)")
                if st.session_state.get('pf_toss'):
                    if _tz_c2.button('🔒 잠그기', key='pf_toss_lock', use_container_width=True):
                        for _k in ('pf_toss', 'pf_rows', 'pf_cap', 'pf_src'):
                            st.session_state.pop(_k, None)
                        st.rerun()
                else:
                    _tz_pw = _tz_c1.text_input('포트폴리오 비밀번호', type='password', key='pf_toss_pw',
                                               label_visibility='collapsed', placeholder='포트폴리오 비밀번호')
                    if _tz_c2.button('🔓 불러오기', key='pf_toss_go', use_container_width=True) and _tz_pw:
                        try:
                            _snap = _pv.unseal(_tz_pw)
                            st.session_state['pf_toss'] = _snap
                            _rows_t, _cash_krw, _cash_usd = [], 0.0, 0.0
                            for _a in _snap.get('accounts') or []:
                                _cash_krw += float((_a.get('cash') or {}).get('KRW') or 0)
                                _cash_usd += float((_a.get('cash') or {}).get('USD') or 0)
                                for _h in _a.get('holdings') or []:
                                    if not _h.get('sym') or not _h.get('qty'):
                                        continue
                                    _rows_t.append({'sym': _h['sym'], 'name': _h.get('name') or _h['sym'],
                                                    'market': 'KR' if _h.get('market') == 'KR' else 'US',
                                                    'qty': float(_h['qty']),
                                                    'avg_cost': float(_h.get('avg_cost') or 0), 'buy_date': ''})
                            _hold_krw = sum(float(_h.get('value') or 0) * (_usdkrw() if _h.get('currency') == 'USD' else 1)
                                            for _a in _snap.get('accounts') or [] for _h in _a.get('holdings') or [])
                            st.session_state['pf_rows'] = _rows_t
                            st.session_state['pf_cap'] = int(_hold_krw + _cash_krw + _cash_usd * _usdkrw())
                            st.session_state['pf_src'] = 'toss'
                            st.session_state.pop('pf_toss_pw', None)
                            st.rerun()
                        except ValueError as _e:
                            st.error(str(_e))
                        except Exception as _e:
                            st.error(f'불러오기 실패: {str(_e)[:120]}')
                _snap = st.session_state.get('pf_toss')
                if _snap:
                    _ck = sum(float((_a.get('cash') or {}).get('KRW') or 0) for _a in _snap['accounts'])
                    _cu = sum(float((_a.get('cash') or {}).get('USD') or 0) for _a in _snap['accounts'])
                    _nh = sum(len(_a.get('holdings') or []) for _a in _snap['accounts'])
                    _t1, _t2, _t3, _t4 = st.columns(4)
                    _t1.metric('총자산(원 환산)', f"{st.session_state.get('pf_cap', 0):,.0f}")
                    _t2.metric('보유 종목', f"{_nh}종")
                    _t3.metric('원화 현금', f"{_ck:,.0f}")
                    _t4.metric('달러 현금', f"${_cu:,.2f}")
                    st.caption(f"환율 {_usdkrw():,.1f}원/$ · 계좌 "
                               + ', '.join(f"{_a.get('no_masked')}" for _a in _snap['accounts'])
                               + " · 아래 표에 자동 반영됐습니다. 이 화면을 닫거나 '잠그기'를 누르면 지워집니다.")
        elif _acc.is_owner():
            st.caption("🔐 토스 계좌 자동 연동: 노트북에서 `python tools/toss_sync.py --setup` 을 한 번 실행하면 켜집니다.")

        _pf_up = st.file_uploader('📂 백업 불러오기(my_portfolio.json)', type=['json'], key='pf_up',
                                  help='이전에 내려받은 백업 파일. 서버에는 저장하지 않고 이 세션에만 올립니다.')
        if _pf_up is not None and st.session_state.get('_pf_up_done') != _pf_up.file_id:
            try:
                _bk = json.loads(_pf_up.getvalue().decode('utf-8'))
                st.session_state['pf_rows'] = [r for r in (_bk.get('positions') or []) if str(r.get('sym') or '').strip()]
                st.session_state['pf_cap'] = int(_bk.get('total_capital') or 0)
                st.session_state['_pf_up_done'] = _pf_up.file_id
                st.rerun()
            except Exception as _e:
                st.error(f'백업 파일을 읽지 못했습니다: {str(_e)[:80]}')
        _rows = _pf_load()
        if not _rows:
            _rows = [{'sym': '', 'name': '', 'market': 'KR', 'qty': 0,
                      'avg_cost': 0.0, 'buy_date': ''}]
        _df_in = pd.DataFrame(_rows)
        for _c in _PF_COLS:
            if _c not in _df_in.columns:
                _df_in[_c] = '' if _c in ('sym', 'name', 'market', 'buy_date') else 0
        _df_in = _df_in[_PF_COLS]

        _cap_col, _btn_col = st.columns([2, 1])
        _total_cap = _cap_col.number_input(
            "총자본 (현금 포함, 원)", min_value=0,
            value=int(st.session_state.get('pf_cap', 0)), step=1_000_000, format="%d",
            help="현금 비중까지 점검하려면 넣으세요. 0이면 보유분만 봅니다.")

        st.markdown("**보유 종목** — 행 추가·삭제 가능. "
                    "`종목코드`는 KR이면 6자리(005930), US면 티커(AAPL).")
        _edited = st.data_editor(
            _df_in, num_rows='dynamic', use_container_width=True, hide_index=True,
            key='pf_editor',
            # 표 규칙 ②: 종목 → 코드 순 (편집표라 행번호 열은 넣지 않는다 — 행 추가·삭제와 충돌)
            column_order=['name', 'sym', 'market', 'qty', 'avg_cost', 'buy_date'],
            column_config={
                'sym': st.column_config.TextColumn('코드', width='small'),
                'name': st.column_config.TextColumn('종목', width='medium'),
                'market': st.column_config.SelectboxColumn('시장', options=['KR', 'US'], width='small'),
                'qty': st.column_config.NumberColumn('수량', min_value=0.0, step=0.000001, format='%g'),  # 소수점 주식(토스) 대응
                'avg_cost': st.column_config.NumberColumn('평균단가', min_value=0.0, format='%.2f'),
                'buy_date': st.column_config.TextColumn('매수일 YYYY-MM-DD', width='small'),
            })
        st.caption("출처: 직접 입력 · 토스증권 계좌 연동 · 마지막 갱신: 저장 시점")

        if _btn_col.button('💾 저장 & 평가', use_container_width=True, type='primary'):
            _keep = [r for r in _edited.to_dict('records') if str(r.get('sym') or '').strip()]
            st.session_state['pf_rows'] = _keep
            st.session_state['pf_cap'] = _total_cap
            if _us.ready() and _pf_email and st.session_state.get('pf_src') != 'toss':   # 계좌 연동분은 저장하지 않는다
                try:
                    # 2026-10-26 — 같은 저장 칸에 '후보'(종목 발굴에서 담은 것)도 있다. 덮어쓰지 않게 함께 저장
                    _us.save(_pf_email, {'positions': _keep, 'total_capital': _total_cap,
                                         'candidates': st.session_state.get('cand_list') or []})
                    st.session_state['pf_db_asof'] = datetime.now().strftime('%Y-%m-%d %H:%M')
                    st.session_state['pf_db_msg'] = f'✅ {len(_keep)}종목 — 내 계정에 암호화 저장됨'
                except Exception as _e:
                    _rt = getattr(getattr(_e, 'response', None), 'text', '') or ''
                    st.session_state['pf_db_msg'] = f'⚠️ 계정 저장 실패(이 세션에만 반영): {str(_e)[:80]} {_rt[:120]}'
            elif st.session_state.get('pf_src') == 'toss':
                st.session_state['pf_db_msg'] = 'ℹ️ 토스 연동 자료는 계정에 저장하지 않습니다 — 🔒 잠그기 후 직접 입력분만 저장됩니다'
            else:
                st.session_state['pf_db_msg'] = f'{len(_keep)}종목 반영 — 이 세션에만 있습니다(계정 저장 미설정)'
            st.rerun()

        _live = st.session_state.get('pf_rows') or [
            r for r in _edited.to_dict('records') if str(r.get('sym') or '').strip()]

        if not _live:
            st.info('보유 종목을 입력하고 **저장 & 평가**를 누르세요. '
                    '현재가 · 매수 후 최고가 · 신고가 경과주는 자동으로 채웁니다.')
        else:
            _pos, _miss = [], []
            for _r in _live:
                _sym = str(_r['sym']).strip()
                _mk = (_r.get('market') or 'KR').upper()
                _qty = float(_r.get('qty') or 0)
                _avg = float(_r.get('avg_cost') or 0)
                _cur = _fetch_pf_price(_sym, _mk)
                if _cur is None or _qty <= 0:
                    _miss.append(_sym)
                    continue
                _peak, _wk = None, None
                try:
                    _peak, _wk = _pf_trail(_sym, _mk, str(_r.get('buy_date') or '') or None)
                except Exception:
                    pass
                # 2026-10-14: US 를 달러 그대로 더하면 KR(원)과 섞여 비중이 엉터리였다 → 원화 환산
                _fxm = _usdkrw() if _mk == 'US' else 1.0
                _pos.append({
                    'sym': _sym, 'name': _r.get('name') or _sym, 'market': _mk,
                    'qty': _qty, 'cur_price': _cur,
                    'value': _qty * _cur * _fxm, 'cost': (_qty * _avg * _fxm) if _avg else None,
                    'pnl_pct': ((_cur / _avg - 1) * 100) if _avg else None,
                    'peak_price': _peak, 'weeks_since_high': _wk})
            if _miss:
                st.warning('현재가를 못 가져온 종목: ' + ', '.join(_miss))

            if _pos:
                _res = _gr.evaluate(_pos, total_capital=(_total_cap or None))
                _vi = _res.get('violations') or []
                st.session_state['pf_eval'] = dict(grade=_res.get('grade'), n=len(_pos), n_vi=len(_vi),
                                                   top=[v.get('msg') for v in _vi[:3]])   # 🏠 종합 '할 일'이 읽는다
                _m1, _m2, _m3 = st.columns(3)
                _m1.metric('원칙 준수 등급', _res.get('grade', '—'))
                _m2.metric('보유 종목', f"{len(_pos)}종")
                _m3.metric('위반', f"{len(_vi)}건")

                if _vi:
                    st.markdown('#### 조치가 필요한 항목')
                    for _v in _vi:
                        (st.error if _v.get('sev') == '🔴' else st.warning)(
                            f"**{_v.get('rule')}** — {_v.get('msg')}")
                else:
                    st.success('원칙 위반 없음. 지금 손댈 것이 없습니다.')

                _hd = _res.get('holdings') or []
                if _hd:
                    st.markdown('#### 보유 현황')
                    _tsrc('보유: 직접 입력·토스증권 계좌 / 현재가: FinanceDataReader·yfinance', live=True)
                    st.dataframe(pd.DataFrame([{
                        '종목': h.get('name') or h['sym'],
                        '평가비중%': round(h.get('weight') or 0, 1),
                        '매입비중%': round(h.get('cost_weight') or 0, 1),
                        '분할': h.get('tranche'),
                        '현재가': h.get('cur_price'),
                        '수익률%': (round(h['pnl_pct'], 1) if h.get('pnl_pct') is not None else None),
                        '보유중최고': h.get('peak_price'),
                        '고점대비%': (round((h['cur_price'] / h['peak_price'] - 1) * 100, 1)
                                      if h.get('peak_price') and h.get('cur_price') else None),
                        '신고가경과주': h.get('weeks_since_high'),
                        '레버리지': '⚠️' if h.get('lev') else '',
                    } for h in _hd]), use_container_width=True, hide_index=True, row_height=25)

                # 준수 이력 — 이게 있어야 '얼마나 지켰나'를 나중에 실측할 수 있다
                try:
                    _gr.append_snapshot(_res)
                    _stat = _gr.compliance_stats(_gr.load_history())
                    if _stat:
                        st.caption(f"최근 30일 준수율 {_stat.get('green_pct', 0):.0f}% · "
                                   f"현재 연속 무위반 {_stat.get('cur_streak_green', 0)}일")
                except Exception:
                    pass

            if st.session_state.get('pf_src') != 'toss':
                # 2026-10-21: '저장소에 넣으라'던 안내 삭제 — 저장소는 공개다. 대신 본인 기기에 파일로 받고, 다음에 올려서 복원.
                st.download_button('💾 내 기기에 백업(JSON)', key='pf_dl', width='content',
                                   data=json.dumps({'positions': _live, 'total_capital': _total_cap},
                                                   ensure_ascii=False, indent=2).encode('utf-8'),
                                   file_name='my_portfolio.json', mime='application/json')
                if _us.ready() and _pf_email:
                    st.caption(f"🔐 내 계정에 암호화 저장 · 마지막 저장 {str(st.session_state.get('pf_db_asof') or '-')[:16]} "
                               "· 운영자도 내용을 볼 수 없습니다")
                    if st.button('🗑️ 내 저장 데이터 완전 삭제', key='pf_db_del'):
                        try:
                            _us.delete(_pf_email)
                            for _k in ('pf_rows', 'pf_cap', 'pf_db_asof'):
                                st.session_state.pop(_k, None)
                            st.toast('삭제했습니다 — 서버에 남은 것이 없습니다')
                            st.rerun()
                        except Exception as _e:
                            st.error(f'삭제 실패: {str(_e)[:80]}')


# ════════════════════════════════════════════════════════════════════
# 🔄 흑자전환 (턴어라운드)  — 2026-10-10 복원
# ────────────────────────────────────────────────────────────────────
# "테슬라 2019 Q3 같은 종목 발굴"이 목적이다. 엔진(turnaround_run.py)은 계속
# 결과를 만들고 있었는데 **읽는 화면이 없었다** — results/turnaround_latest.json
# 의 소비자가 0이었고, 그래서 아무도 멈춘 걸 몰랐다(09-16 자 · 종목 0개).
# 지금은 어느 워크플로도 이걸 돌리지 않는다. 화면을 붙이면서 레지스트리에도
# 올려 정지하면 보이게 한다.
# ════════════════════════════════════════════════════════════════════
with t_turn, guard('흑자전환'):
    _ta = load_json(Path('results/turnaround_latest.json')) or {}
    _tas = _ta.get('stocks') or []
    st.markdown("#### 🔄 흑자전환 — 적자에서 돌아서는 구간을 찾는다")
    st.caption("판정은 **영업이익** · 전년 같은 분기와 비교(백테스트와 같은 정의) — "
               "**흑자전환완료** 이번 분기 영업흑자 + 전년 같은 분기 영업적자 · "
               "**흑자전환임박** 아직 적자지만 전년 같은 분기보다 적자 폭 50%+ 축소 · **적자개선중** 25~50% 축소. "
               "'흑자 n분기째'가 1~2면 막 돌아선 것, 4 이상이면 이미 자리 잡은 것.")
    _new_fmt = any('op' in r for r in _tas)
    if _tas and not _new_fmt:
        st.warning("이 결과는 **옛 정의**(순이익 · 직전 3분기 중 한 번이라도 적자)로 만들어졌습니다 — LG전자처럼 매년 4분기만 "
                   "적자인 종목도 '흑자전환완료'로 잡히던 정의입니다. 새 정의(영업이익 · 전년 같은 분기) 결과는 "
                   "다음 주간 갱신(weekly-accel)부터 이 자리에 나옵니다.")

    if not _tas:
        st.info(f"데이터가 비어 있습니다 (파일 기준일 {_ta.get('date', '-')}). 주간 갱신(weekly-accel)이 만듭니다.")
    else:
        _c1, _c2, _c3 = st.columns(3)
        _c1.metric("총 종목", f"{_ta.get('total', len(_tas))}종")
        _c2.metric("KR", f"{_ta.get('kr', 0)}종")
        _c3.metric("US", f"{_ta.get('us', 0)}종")
        _skp = _ta.get('skipped') or {}
        if _skp:
            st.caption("⏸️ 판정 보류: " + " · ".join(f"{k.replace('_', ' ')} {v}종" for k, v in _skp.items())
                       + " — 분기가 빠졌거나 최신 분기가 비어 있으면 틀린 판정을 내지 않고 뺍니다.")
        _mk = _GMKT
        if _mk != "US" and not _ta.get('kr'):
            st.warning("🇰🇷 **KR 흑자전환이 0종입니다 — 시장이 아니라 데이터 사고입니다.** 토요일 주간 갱신이 휴장일 KRX 목록"
                       "(거래량 전부 0)을 받아 한국 종목을 전부 지웠습니다(2026-10-26 원인 확인·수정). 같은 데이터로 다시 돌리면 "
                       "한국 140종(완료 97)이 나옵니다 — 다음 주간 갱신부터 반영됩니다.")
        _sts = [x for x in ('흑자전환완료', '흑자전환임박', '적자개선중') if any(r.get('status') == x for r in _tas)]
        _tc1, _tc2 = st.columns([2, 1])
        _pick = _tc1.multiselect("구분", _sts, default=_sts, key="turn_st")
        _streak_max = _tc2.selectbox("흑자 몇 분기째", ["전체", "1~2분기째(막 돌아섬)", "1분기째만"], key="turn_streak",
                                     disabled=not _new_fmt)
        _rows = [r for r in _tas
                 if (_mk == "전체" or r.get('market') == _mk)
                 and (not _pick or r.get('status') in _pick)]
        if _new_fmt and _streak_max != "전체":
            _lim = 2 if _streak_max.startswith("1~2") else 1
            _rows = [r for r in _rows if r.get('status') != '흑자전환완료' or 1 <= (r.get('profit_streak') or 0) <= _lim]
        if _rows:
            _kr_only = all(r.get('market') == 'KR' for r in _rows)
            _us_only = all(r.get('market') == 'US' for r in _rows)
            _opc = '최근분기 영업익(억원)' if _kr_only else '최근분기 영업익($M)' if _us_only else '최근분기 영업익(억원·$M)'

            def _op0(r):
                v = (r.get('op') or [None])[0]
                if v is None:
                    return None
                return round(v / 1e8) if r.get('market') == 'KR' else round(v / 1e6, 1)
            _trows = [{'종목': r.get('name') or r.get('sym'), '코드': r.get('sym'), '구분': r.get('status'),
                       '흑자 n분기째': r.get('profit_streak') or None, '직전 적자(분기)': r.get('loss_run_before'),
                       _opc: _op0(r), '영업이익률 변화(%p)': r.get('opm_chg')} for r in _rows]
            st.subheader(f"{len(_rows)}종 · 정렬: 구분 → 시총")
            _std_table(pd.DataFrame(_trows), ['구분', '흑자 n분기째', '직전 적자(분기)', _opc, '영업이익률 변화(%p)'],
                       src='DART·네이버(KR)·SEC EDGAR(US) 분기재무 → turnaround_latest.json', path='results/turnaround_latest.json',
                       column_config={'흑자 n분기째': st.column_config.NumberColumn(format='%d', help='이번 분기 포함 연속 영업흑자 분기 수'),
                                      '직전 적자(분기)': st.column_config.NumberColumn(format='%d', help='흑자로 돌아서기 직전 연속 영업적자 분기 수'),
                                      _opc: st.column_config.NumberColumn(format='localized', help='한국 = 억원, 미국 = $M'),
                                      '영업이익률 변화(%p)': st.column_config.NumberColumn(format='%+.1f', help='이번 분기 영업이익률 − 전년 같은 분기')},
                       note='영업익YoY 는 전년이 적자라 비어 있는 게 정상 — 대신 매출YoY 로 매출이 함께 크는지 본다')
            _cand_register(_trows, 'turn')
        st.caption("⚠️ 흑자전환은 **되돌아가는 경우가 많습니다.** 한 분기 흑자를 추세로 읽지 마세요 — 매출이 함께 크는지(매출YoY), "
                   "이익률이 함께 오르는지, 그리고 🚀 주도주 → 교집합 후보와 겹치는지 같이 보는 것이 안전합니다.")

# ── 운영자 화면(2026-10-20): 설정·정답 점검·데이터 신선도는 고객이 아니라 운영자가 보는 것 →
#   ?diag=admin 에서만 펼친다. 평소엔 '틀린 게 있을 때만' 한 줄 경고(문제를 숨기지는 않는다).
_ADMIN = st.query_params.get('diag') == 'admin'


@st.cache_data(ttl=600, show_spinner=False)
def _known_answers():
    import importlib, tools.known_answers as _ka
    importlib.reload(_ka)
    return _ka.run()


if _ADMIN:
    st.divider()
    with st.expander("⚙️ 설정 — Finnhub API 키 · 전체 새로고침", expanded=False):
        _KEY_FILE = Path('data/.finnhub_key')
        if 'fh_key' not in st.session_state:
            try:
                st.session_state['fh_key'] = _KEY_FILE.read_text().strip() if _KEY_FILE.exists() else ''
            except Exception:
                st.session_state['fh_key'] = ''
        _set1, _set2 = st.columns([2, 1])
        with _set1:
            fh_input = st.text_input("Finnhub API 키 (선택 · finnhub.io 무료 · 종목분석 PER·내부자거래용)",
                                     type="password", value=st.session_state.get('fh_key', ''),
                                     key="fh_key_input")
            if fh_input and fh_input != st.session_state.get('fh_key', ''):
                st.session_state['fh_key'] = fh_input
                try:
                    _KEY_FILE.parent.mkdir(exist_ok=True); _KEY_FILE.write_text(fh_input)
                except Exception:
                    pass
            if IS_CLOUD:
                st.caption("⚠️ 웹에서 넣은 키는 이번 세션에서만 유효합니다(서버 재시작 시 소멸). "
                           "영구 적용은 Streamlit Cloud → Settings → Secrets 에 `FINNHUB_KEY` 등록.")
        with _set2:
            st.write("")
            if st.button("🔄 전체 새로고침", use_container_width=True):
                st.cache_data.clear()
                st.rerun()
        st.caption("데이터 갱신은 매일 06:00 자동(GitHub Actions). 수동: weekly_run·perf_run·canslim_run·screen_precompute")

    # ── 정답 점검 (2026-10-19) ─────────────────────────────────────
    # 날짜가 신선해도 내용에 구멍이 날 수 있다(시총 파일에 S~Z 1,300종 누락, NVDA 시총 NULL).
    # '반드시 참이어야 하는 사실'을 이 서버에서 바로 확인한다 — CI 결과 파일이 아니라 지금 배포된 파일 기준.


    with guard('정답 점검'):
        _KA = _known_answers()
        _ka_bad = [r for r in _KA if not r['ok']]
        _ka_hdr = (f"🧪 정답 점검 — 전 항목 통과 ({len(_KA)}/{len(_KA)})" if not _ka_bad
                   else f"🔴 정답 점검 — **{len(_ka_bad)}개 항목이 틀림** ({len(_KA) - len(_ka_bad)}/{len(_KA)} 통과)")
        with st.expander(_ka_hdr, expanded=bool(_ka_bad)):
            _tsrc('tools/known_answers.py — 이 서버의 산출물을 직접 검사', live=True)
            st.dataframe(pd.DataFrame([{'상태': '✅ 통과' if r['ok'] else '❌ 틀림', '분야': r['area'],
                                        '질문': r['question'], '결과': r['detail']}
                                       for r in sorted(_KA, key=lambda r: r['ok'])]),
                         filters=False, color=False)
            st.caption("행 수·날짜만 보는 감시는 '구멍 난 정상'을 못 잡았다(2026-10-19 S~Z 누락·시총 NULL·컨센서스 정지). "
                       "그래서 답을 아는 질문으로 내용을 본다. 매일 06시 CI 도 같은 점검을 돌려, 하나라도 틀리면 실패·텔레그램.")

    # ── 페이지 최하단: 데이터 신선도 ─────────────────────────────────
    # 예전엔 file_mtime(파일 수정시각)을 '데이터 갱신일'로 표시했다. 클라우드에서 그건
    # 저장소를 내려받은 시각이라, 07-26에 멈춘 데이터가 '어제 갱신'으로 보였다.
    # 이제 파일 안의 실제 날짜를 읽는다 — 화면이 신선하다고 거짓말하지 않는다.
    with guard('데이터 신선도'):
        _DS = _data_status()
        _n_stale = sum(1 for r in _DS if r['state'] != 'ok')
        _oldest = max((max(r['age'], 0) for r in _DS if r['age'] is not None), default=None)
        _hdr = (f"📅 데이터 신선도 — 전 항목 정상 (가장 오래된 것 {_oldest}일 전)" if not _n_stale
                else f"🔴 데이터 신선도 — **{_n_stale}개 항목이 갱신 정지** (클릭해서 확인)")
        with st.expander(_hdr, expanded=bool(_n_stale)):
          _ft1, _ft2 = st.tabs(['🗺️ 흐름도 — 무엇이 무엇에서 나오나', '📋 목록 (중요도순)'])
          with _ft1:
            try:
                import data_freshness as _dfm
                st.graphviz_chart(_dfm.dot(_DS), use_container_width=True)
                st.caption(
                    "왼쪽이 **원천**(회색 타원 = 외부 소스, 파란 원통 = 저장소), "
                    "오른쪽으로 갈수록 그것에서 **계산된 결과**입니다. "
                    "`▼N` 은 **그게 멈추면 같이 멈추는 산출물 수**이고, 이 수치가 "
                    "곧 고치는 순서입니다 — 사람이 매긴 등급이 아니라 연결에서 자동으로 셉니다.")
                _top = [r for r in _DS if r.get('upstream_bad')]
                if _top:
                    st.warning("**상류가 죽은 채 '정상'으로 보이는 항목** — 파일 날짜만 "
                               "신선하고 재료가 낡았다는 뜻입니다:\n" +
                               "\n".join(f"· {r['label']} ← {', '.join(_dfm.node_label(d) for d in r['upstream_bad'])}"
                                          for r in _top))
            except Exception as _e:
                st.caption(f"흐름도를 그리지 못했습니다: {_e}")
          with _ft2:
            _tsrc('pipeline_health — 각 산출물 내부 날짜 검사', live=True)
            st.dataframe(pd.DataFrame([{
                '상태': {'ok': '🟢 정상', 'stale': '🔴 정지', 'missing': '⚫ 없음',
                        'nodate': '⚠️ 날짜없음', 'error': '⚠️ 오류'}[r['state']],
                # 중요도 = 이게 멈추면 같이 멈추는 산출물 수. 고치는 순서가 된다.
                '중요도': r.get('impact', 0),
                '데이터': r['label'],
                '마지막 갱신': r['date'] or '-',
                '경과': (f"{max(r['age'], 0)}일" if r['age'] is not None else '-'),
                '갱신 주기': r['cycle'],
                # 2026-09-09: '쓰임' 열 신설. 그전에는 화면이 직접 읽는 것과 계산 입력이
                # 한 열에 섞여 있어 "우리가 이렇게 많은 데이터를 쓰나?"로 읽혔다.
                # 실제로 화면이 직접 읽는 건 18개 중 14개다.
                '쓰임': ('입력' if ('계산' in r['used_by'] or '화면 없음' in r['used_by']
                                  or 'point-in-time' in r['used_by']) else '화면'),
                '쓰이는 곳': r['used_by'],
                '만드는 것': f"{r['producer']} ({r['job']})",
            } for r in _DS]), use_container_width=True, hide_index=True,
                row_height=25, height=_dfh(len(_DS)))
            st.caption("**중요도**는 그 데이터가 멈추면 **같이 멈추는 산출물 수**입니다. "
                       "큰 것부터 고치면 됩니다.")
            st.caption("‘마지막 갱신’은 **파일 안에 기록된 데이터 날짜**입니다(배포 시각이 아님). "
                       "정지 항목은 매일 06:00 `pipeline_health.py`가 텔레그램으로도 알립니다.")
            st.caption("**쓰임** — `화면`은 대시보드가 직접 읽는 파일, `입력`은 화면이 아니라 "
                       "**계산의 재료**입니다. 입력이 멈추면 화면에는 에러가 안 뜨고 **숫자만 조용히 "
                       "낡습니다** — 실제로 미국 시총이 20일 멈춰 있는 동안 종목들이 낡은 시총으로 "
                       "필터링되고 있었습니다. 그래서 화면에 안 보여도 같이 감시합니다.")
else:
    with guard('운영 점검 요약'):
        _ka_n, _st_n = _ops_counts()          # 상단 배지와 같은 캐시(10분) — 두 번 읽지 않는다
        _ka_n, _st_n = _ka_n or 0, _st_n or 0
        if _ka_n or _st_n:
            st.caption(f"🔴 운영 점검 — 정답 점검 틀림 {_ka_n}건 · 갱신 정지 {_st_n}건. "
                       "자세히는 주소 끝에 `?diag=admin`.")
st.caption("출처: DART·SEC EDGAR(공식 재무) · FinanceDataReader/KRX(가격) · "
           "FRED(매크로) · 네이버금융·yfinance(컨센서스, 참고)")


# ── 📰 시황 리포트 + 챗봇 (2026-10-14) ─────────────────────────────────
def _gemini_key_site():
    try:
        import config
        k = getattr(config, 'GEMINI_KEY', '') or ''
    except Exception:
        k = ''
    if not k:
        try:
            k = st.secrets.get('GEMINI_KEY', '')
        except Exception:
            k = ''
    return k or os.environ.get('GEMINI_KEY', '')


def _related_rows(q):
    """질문에 종목명·코드가 있으면 그 종목의 숫자를 챗봇 자료에 붙인다."""
    qn = q.replace(' ', '').casefold()
    out = []
    for f in ('results/perf_latest.json', 'results/canslim_latest.json', 'results/canslim_us_latest.json'):
        for x in (load_json(Path(f)) or {}).get('stocks', []):
            n = str(x.get('name') or '').replace(' ', '').casefold()
            sym = str(x.get('sym') or '')
            if (len(n) >= 2 and n in qn) or (len(sym) >= 2 and sym.casefold() in qn.split() + [qn]):
                out.append({k: v for k, v in x.items() if not isinstance(v, (list, dict))} | {'_src': f})
    return out[:6]



def _goto_tab(name):
    st.session_state['main_tab'] = name


def _home_verdict(V):
    """① 이번 주 판정 — 🌍 매크로 탭 맨 위 카드와 같은 값(verdict.py)."""
    st.subheader("① 이번 주 판정")
    c, a, ph, g, fl, ec = (V.get(k) or {} for k in ('core', 'alloc', 'phase', 'greed', 'flow', 'econ'))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric('코어 스위치 · 확정 규칙', '판정 불가' if not c else ('ON' if c['on'] else 'OFF'),
              None if not c else f"S&P500 200일선 {c['gap']:+.1f}%", delta_color='normal' if c else 'off',
              help='원칙 v1.3 §3 — SPY 종가가 200일 이평 위면 코어 보유, 아래면 코어를 현금으로. 비중을 바꾸는 유일한 규칙')
    k2.metric('이번 주 목표 비중(%)',
              '-' if a.get('cash_total') is None else f"{a['core_now']} / {a['satellite']} / {a['cash_total']}",
              '코어 / 위성 / 현금', delta_color='off', delta_arrow='off',
              help='시작 배분 50/30/20(executor/config.json). 스위치 OFF 면 코어 몫이 현금으로 간다. 위성에는 시장 필터가 없다(§4)')
    k3.metric('사이클 국면 · 참고', f"{ph.get('emoji', '')} {ph.get('name') or '-'}",
              f"욕심 경고 {g.get('n', '-')}/3" if g else None, delta_color='off', delta_arrow='off',
              help='우라가미 4계절과 참고 경고 3종(신용 스프레드·역국면·강달러) — 백테스트에서 비중 규칙으로 살아남지 못해 표시만 한다')
    k4.metric('돈의 흐름 · 경기 · 참고', f"{fl.get('word') or '-'}", ec.get('word') or None,
              delta_color='off', delta_arrow='off', help='🌍 매크로 탭 축 1(자산 8종 200일선)·축 2(선행·동행 지표) 요약')
    kr = V.get('kr_core') or {}
    _src = ('results/macro.json (verdict.py · 매일 06:00 KST)' if V.get('_src') == 'file'
            else f"라이브 계산(verdict.core_switch) — macro.json 이 없거나 낡음({V.get('_file_asof') or '없음'}) · 국면·흐름은 직전 파일 값")
    _krt = '-' if not kr else f"{'위' if kr['on'] else '아래'} {kr['gap']:+.1f}%"
    st.caption(f"코스피 200일선 {_krt} — 한국 노출은 지수로 갖는다(원칙 v1.2). 왜 이렇게 판정했는지는 🌍 매크로 탭.")
    st.caption(f"출처: {_src} · 마지막 갱신: {V.get('asof') or '-'} 종가")


def _home_todo(V):
    """② 이번 주 할 일 — 원칙 v1 §8 주간 사이클 순서: 데이터 → 코어 → 위성 매도 → 위성 매수 → 보유 점검."""
    st.subheader("② 이번 주 할 일")
    c = V.get('core') or {}
    ka, stl = _ops_counts()
    acc = load_json(Path('results/leaders_accel.json')) or {}
    cands = acc.get('candidates') or []
    pf = st.session_state.get('pf_eval')
    rows = []
    bad = (ka or 0) + (stl or 0)
    rows.append(('① 데이터', '🔴' if bad else '🟢',
                 f"정답 점검 틀림 {ka}건 · 갱신 정지 {stl}건 — 신호를 쓰기 전에 데이터부터(원칙 §8 ①)" if bad
                 else '정답 점검·신선도 전 항목 정상'))
    if not c:
        rows.append(('② 코어', '⚪', '판정 불가 — 지난주 상태 유지'))
    elif V.get('changed'):
        rows.append(('② 코어', '🟠', 'ON 전환 → 코어 복귀 매수' if c['on'] else 'OFF 전환 → 코어 매도, 현금으로'))
    else:
        rows.append(('② 코어', '🟢' if c['on'] else '🔴', '유지 (보유)' if c['on'] else '유지 (현금)'))
    rows.append(('③ 위성 신규', '🟢' if cands else '⚪',
                 f"이익가속 신호 {len(cands)}종 ({acc.get('signal_week', '-')} 주) — 시총 작은 순 · 칸당 위성 5% · 월요일 매수 · 보유 중이면 건너뜀"
                 if cands else f"신규 신호 없음 ({acc.get('signal_week', '-')} 주) — 빈 칸은 S&P500 으로(§4-6)"))
    rows.append(('④ 보유 점검', ('🟢' if pf and not pf['n_vi'] else '🟠') if pf else '⚪',
                 (f"{pf['grade']} · {pf['n']}종 · 위반 {pf['n_vi']}건" + (' — ' + ' / '.join(pf['top']) if pf['top'] else ''))
                 if pf else '보유 종목이 아직 없습니다 — 🛡️ 내 포트폴리오 탭에서 토스 잔고를 불러오거나 입력'))
    st.dataframe(pd.DataFrame([{'단계': r[0], '상태': r[1], '할 일': r[2]} for r in rows]),
                 filters=False, color=False, src='verdict.py · leaders_accel.json · 정답 점검·신선도 · 🛡️ 포트폴리오 평가',
                 asof=V.get('asof'), use_container_width=True,
                 column_config={'할 일': st.column_config.TextColumn('할 일', width='large')})
    st.caption("위성 매도(52주 보유 후 33주 신고가 미갱신)·트림(위성 15% 초과)은 보유 기록이 있어야 판정된다 — "
               "토스 자동매매(executor) 원장이 붙으면 이 표가 주문표가 된다.")
    if cands:
        _t = pd.DataFrame([{'종목': x.get('name'), '코드': x.get('sym'), '시총($B)': x.get('mc'),
                            '신호 주 상승(%)': x.get('up'), '영업이익 가속(%p)': x.get('oia'),
                            '매출 YoY(%)': x.get('revy'), 'PER': x.get('per')}
                           for x in sorted(cands, key=lambda x: x.get('mc') or 9e9)])
        for _c in _t.columns[2:]:
            _t[_c] = pd.to_numeric(_t[_c], errors='coerce')        # None → NaN('-'), 숫자 정렬 유지
        _tsrc('leaders_accel.py — 이익가속 신호 (시총 작은 순 = 원칙 §4 매수 순서)', path='results/leaders_accel.json',
              asof=acc.get('signal_week'))
        st.dataframe(_t, filters=False, column_config={
            '시총($B)': st.column_config.NumberColumn(format='%.2f'),
            '신호 주 상승(%)': st.column_config.NumberColumn(format='%+.1f'),
            '영업이익 가속(%p)': st.column_config.NumberColumn(format='%+.1f'),
            '매출 YoY(%)': st.column_config.NumberColumn(format='%+.1f'),
            'PER': st.column_config.NumberColumn(format='%.1f')})
        st.caption("종목·코드 칸을 누르면 🔍 종목 분석으로 · 전체 이력은 🔎 종목 발굴 → 💎 펀더멘털 → 이익가속")
    b1, b2, b3 = st.columns(3)
    b1.button("🌍 매크로 근거 보기", on_click=_goto_tab, args=("🌍 매크로",), use_container_width=True, key='home_go_macro')
    b2.button("🔎 발굴 전체 보기", on_click=_goto_tab, args=("🔎 종목 발굴",), use_container_width=True, key='home_go_screen')
    b3.button("🛡️ 보유 점검하기", on_click=_goto_tab, args=("🛡️ 내 포트폴리오",), use_container_width=True, key='home_go_pf')


# ── 상단 배지 + 🏠 종합 — 맨 끝에서(판정 계산이 다른 탭을 붙잡지 않게) ──────────
with guard('이번 주 판정'):
    _VERDICT = _verdict_now()
with _status_slot, guard('상단 배지'):
    _status_bar(_VERDICT)
with tab_home, guard('종합 — 판정'):
    st.caption("월요일 아침 이 화면 하나 — ① 판정 ② 할 일 ③ 시황. 판정은 verdict.py 한 곳에서 계산하고 모든 탭이 같은 값을 읽는다.")
    _home_verdict(_VERDICT)
with tab_home, guard('종합 — 할 일'):
    _home_todo(_VERDICT)

with tab_rep, guard('시황 리포트'):
    st.subheader("③ 시황 리포트")
    _rep = load_json(Path('results/market_report.json')) or {}
    st.caption("매일 06시(KST) 일간 · 월요일 주간. 지수(Yahoo)와 이 사이트의 데이터 **숫자만으로** 작성합니다 — "
               "뉴스·전망을 지어내지 않도록 제한했고, AI 한도에 걸리면 숫자 요약으로 대체됩니다.")
    _hist = _rep.get('history') or []
    if not _hist:
        st.info("아직 발행된 리포트가 없습니다. 다음 자동 갱신(매일 06시)부터 쌓입니다.")
    else:
        _opts = [f"{h['date']} · {'일간' if h['kind']=='daily' else '주간'}" for h in _hist]
        _i = st.selectbox("리포트", range(len(_opts)), format_func=lambda i: _opts[i], key="rep_pick")
        _h = _hist[_i]
        st.caption(f"작성: {'AI(' + _h['engine'].split(':')[-1] + ')' if _h['engine'].startswith('gemini') else '숫자 템플릿'}")
        # 2026-10-24 — 리포트 본문의 #·## 가 탭 제목(①②③)보다 커서 위계가 뒤집혔다 → 두 단계 내려 그린다
        st.markdown(re.sub(r'^(#{1,4}) ', lambda m: '#' * min(len(m.group(1)) + 2, 6) + ' ', _h['markdown'], flags=re.M))
        _lf = (_rep.get(f"latest_{_h['kind']}") or {})
        # 2026-10-21 — 리포트에 나온 종목을 눌러 종목 분석으로(리포트 → 분석 연결)
        _fst = ((_lf.get('facts') or {}).get('stocks') or {}) if _lf.get('date') == _h['date'] else {}
        _syms = []
        for _m in ('KR', 'US'):
            for _k in ('top', 'bottom'):
                for _x in (_fst.get(_m) or {}).get(_k, [])[:3]:
                    if _x.get('sym') and _x['sym'] not in [y for y, _ in _syms]:
                        _syms.append((_x['sym'], f"{'▲' if _k == 'top' else '▼'} {_x.get('name') or _x['sym']} {_x.get('ret', 0):+.1f}%"))
        if _syms:
            st.caption("리포트에 나온 종목 — 누르면 🔍 종목 분석")
            _bc = st.columns(6)
            for _n, (_sy, _lb) in enumerate(_syms[:12]):
                _bc[_n % 6].button(_lb, key=f"rep_go_{_sy}", on_click=_goto_analysis, args=(_sy,), use_container_width=True)
        if _lf.get('date') == _h['date']:
            with st.expander("근거 숫자 보기 (리포트가 쓴 원자료)"):
                st.json(_lf.get('facts') or {}, expanded=False)

    st.divider()
    st.markdown("#### 💬 시황 챗봇")
    st.caption("최신 리포트의 원자료와 질문에 나온 종목의 숫자만 근거로 답합니다. 매수·매도 추천은 하지 않습니다. "
               "AI 무료 한도가 있어 세션당 10회로 제한합니다.")
    st.session_state.setdefault('chat_log', [])
    for _role, _msg in st.session_state['chat_log'][-12:]:
        with st.chat_message(_role):
            st.markdown(_msg)
    _qc1, _qc2 = st.columns([5, 1])
    _q = _qc1.text_input("질문", placeholder="예: 어제 코스피 왜 빠졌어? / 이번 주 미국 강세 종목은? / 티에스이 신호 어때?",
                         label_visibility="collapsed", key="chat_q")
    if _qc2.button("묻기", key="chat_go", use_container_width=True) and _q.strip():
        if sum(1 for r, _ in st.session_state['chat_log'] if r == 'user') >= 10:
            st.warning("이번 세션 질문 한도(10회)를 다 썼습니다. 새로고침하면 초기화됩니다.")
        else:
            _key = _gemini_key_site()
            if not _key:
                _ans = "AI 키가 설정되지 않았습니다 — Streamlit Secrets 에 GEMINI_KEY 가 필요합니다."
            else:
                with st.spinner("답변 작성 중…"):
                    try:
                        import market_report as _MR
                        _ans, _m = _MR.answer(_q.strip(), key=_key, extra_rows=_related_rows(_q))
                        _ans += f"\n\n_※ AI({_m}) 생성 · 사실 확인 필요 · 투자 권유 아님_"
                    except Exception as _e:
                        _ans = f"답변 실패 — AI 한도 초과 또는 일시 오류일 수 있습니다. ({str(_e)[:80]})"
            st.session_state['chat_log'] += [('user', _q.strip()), ('assistant', _ans)]
            st.rerun()



# ── 페이지 최하단 고지 — 모든 탭 공통 (2026-10-21 지인 베타 배포 전 필수) ─────────
# 탭마다 따로 두지 않는다(모든 탭 같은 UI). 문구를 바꾸면 buza-bot 의 DISCLAIMER 와 같이 바꾼다.
DISCLAIMER_VER = 1
st.divider()
st.caption(
    "**ⓘ 이용 안내** · 이 사이트는 공개 데이터와 정해진 규칙으로 계산한 결과, AI 요약을 보여주는 "
    "**정보 도구이며 투자 권유가 아닙니다.** 모든 투자 판단과 책임은 이용자 본인에게 있습니다.\n\n"
    "**데이터 지연** · 표·신호·점수는 매일 06:00(KST) 갱신되는 **전일 종가 기준**입니다. "
    "종목 분석의 현재가도 무료 API 기준이라 **최소 15분 이상 지연**되거나 오류가 있을 수 있습니다.\n\n"
    "**백테스트·목표가** · 상승 확률·평균 상승률은 표시된 기간의 과거 성과이며 미래 수익을 보장하지 않습니다. "
    "목표가는 증권사 컨센서스를 옮긴 것으로, 이 사이트의 의견이 아닙니다.\n\n"
    "**이해상충** · 운영자는 화면에 나온 종목을 보유하고 있을 수 있습니다. "
    "점수·신호는 운영자의 보유 여부와 무관하게 모든 종목에 같은 규칙으로 계산되며, 규칙을 바꾸면 변경 이력에 남깁니다."
)
