"""CANSLIM 대시보드 — 가중치 조절 → 실시간 순위 산출
실행: streamlit run canslim_dashboard.py
"""
import json
import pandas as pd
import streamlit as st
from pathlib import Path

# ── 페이지 설정 ──────────────────────────────────────────────────────
st.set_page_config(
    page_title="CANSLIM 스크리너",
    page_icon="📊",
    layout="wide",
)

JSON_PATH = Path(__file__).parent / 'results' / 'canslim_latest.json'

# ── 데이터 로딩 ──────────────────────────────────────────────────────
@st.cache_data(ttl=300)
def load_data():
    if not JSON_PATH.exists():
        return None
    with open(JSON_PATH, encoding='utf-8') as f:
        return json.load(f)

data = load_data()

# ── 헤더 ─────────────────────────────────────────────────────────────
st.title("📊 CANSLIM 스크리너")

if data is None:
    st.error("결과 파일이 없습니다. `python canslim_run.py`를 먼저 실행하세요.")
    st.stop()

col1, col2, col3 = st.columns(3)
col1.metric("기준일", data['date'])
col2.metric("시장방향 (M)", data['market_dir'])
col3.metric("신호 종목", f"{len(data['stocks'])}개")

if not data['market_ok']:
    st.warning("⚠️ KOSPI 하락추세 — CANSLIM은 상승장 전략. 신규매수 주의.")

st.divider()

# ── 사이드바: 가중치 슬라이더 ────────────────────────────────────────
st.sidebar.header("⚖️ 항목별 가중치 (0 ~ 10)")
st.sidebar.caption("0 = 해당 항목 무시 / 10 = 최고 중요도")

w = {
    'M': st.sidebar.slider("M — 시장방향",  0, 10, 5),
    'C': st.sidebar.slider("C — 분기실적",  0, 10, 8),
    'A': st.sidebar.slider("A — 연간실적",  0, 10, 7),
    'N': st.sidebar.slider("N — 52주신고가",0, 10, 6),
    'S': st.sidebar.slider("S — 거래량폭발",0, 10, 6),
    'L': st.sidebar.slider("L — 상대강도",  0, 10, 7),
    'I': st.sidebar.slider("I — 기관수급",  0, 10, 5),
}

st.sidebar.divider()
st.sidebar.caption("※ C·A는 네이버금융/pykrx 근사치")
st.sidebar.caption("※ ? = 데이터 없음 (0점 처리)")

# ── 점수 계산 ─────────────────────────────────────────────────────────
def bool_score(val):
    """True→1, False→0, None→0"""
    return 1 if val is True else 0

m_score = 1 if data['market_ok'] else 0

rows = []
for s in data['stocks']:
    weighted = (
        w['M'] * m_score            +
        w['C'] * bool_score(s['c_ok']) +
        w['A'] * bool_score(s['a_ok']) +
        w['N'] * bool_score(s['n_ok']) +
        w['S'] * bool_score(s['s_ok']) +
        w['L'] * (s['rs_pct'] / 100)   +   # RS는 비율(0~1)로 반영
        w['I'] * bool_score(s['i_ok'])
    )

    max_possible = w['M'] + w['C'] + w['A'] + w['N'] + w['S'] + w['L'] + w['I']
    pct = round(weighted / max_possible * 100, 1) if max_possible > 0 else 0

    cap = s['marcap'] // 100_000_000
    cap_str = f"{cap/10000:.1f}조" if cap >= 10000 else f"{cap:,}억"

    def tag(v):
        if v is True:  return '✅'
        if v is False: return '❌'
        return '?'

    c_detail = ''
    if s.get('c_growth') is not None:
        g = s['c_growth']
        q = s.get('c_quarter', '')
        c_detail = f"{g}%({q})" if isinstance(g, (int, float)) else str(g)

    a_detail = ''
    if s.get('a_growth'):
        a_detail = ' / '.join(f"{g}%" for g in s['a_growth'])

    rows.append({
        '순위':     0,
        '종목명':   s['name'],
        '종목코드': s['sym'],
        '시총':     cap_str,
        '가중점수': round(weighted, 1),
        '달성률':   pct,
        'RS':       f"{s['rs_pct']:.0f}p",
        'M': '✅' if data['market_ok'] else '❌',
        'C': tag(s['c_ok']),
        'A': tag(s['a_ok']),
        'N': tag(s['n_ok']),
        'S': tag(s['s_ok']),
        'L': '✅' if s['rs_pct'] >= 70 else '❌',
        'I': tag(s['i_ok']),
        'N상세':    f"{s['n_dist']:+.1f}%",
        'S상세':    f"거래량{s['s_vol']}배",
        'C상세':    c_detail,
        'A상세':    a_detail,
        'I상세':    f"{s['i_net_buy']}억" if s.get('i_net_buy') else '',
        '_weighted': weighted,
    })

df = pd.DataFrame(rows).sort_values('_weighted', ascending=False).reset_index(drop=True)
df['순위'] = df.index + 1

# ── 메인 테이블 ──────────────────────────────────────────────────────
st.subheader("🏆 가중치 반영 순위")

# 달성률 색상 함수
def color_pct(val):
    if val >= 80: return 'background-color: #1a472a; color: white'
    if val >= 60: return 'background-color: #2d6a4f; color: white'
    if val >= 40: return 'background-color: #74c69d'
    return ''

def color_tag(val):
    if val == '✅': return 'color: #2ecc71; font-weight: bold'
    if val == '❌': return 'color: #e74c3c'
    return 'color: #95a5a6'

display_cols = ['순위', '종목명', '시총', '가중점수', '달성률', 'RS',
                'M', 'C', 'A', 'N', 'S', 'L', 'I',
                'N상세', 'S상세', 'C상세', 'A상세', 'I상세']

styled = (
    df[display_cols]
    .style
    .applymap(color_tag, subset=['M','C','A','N','S','L','I'])
    .applymap(color_pct, subset=['달성률'])
    .format({'달성률': '{}%', '가중점수': '{:.1f}'})
    .hide(axis='index')
)
st.dataframe(styled, use_container_width=True, height=600)

# ── 차트 ─────────────────────────────────────────────────────────────
st.divider()
st.subheader("📈 상위 종목 가중점수 비교")

top_n = min(15, len(df))
chart_df = df.head(top_n)[['종목명', '가중점수']].set_index('종목명')
st.bar_chart(chart_df)

# ── 항목별 통과율 ─────────────────────────────────────────────────────
st.divider()
st.subheader("📊 항목별 통과율")

total = len(data['stocks'])
if total > 0:
    pass_rates = {
        'C (분기실적)': sum(1 for s in data['stocks'] if s['c_ok'] is True),
        'A (연간실적)': sum(1 for s in data['stocks'] if s['a_ok'] is True),
        'N (52주신고가)': sum(1 for s in data['stocks'] if s['n_ok']),
        'S (거래량)':   sum(1 for s in data['stocks'] if s['s_ok']),
        'L (상대강도)': sum(1 for s in data['stocks'] if s['rs_pct'] >= 70),
        'I (기관수급)': sum(1 for s in data['stocks'] if s['i_ok'] is True),
    }
    rate_df = pd.DataFrame({
        '항목': list(pass_rates.keys()),
        '통과수': list(pass_rates.values()),
        '통과율(%)': [round(v / total * 100, 1) for v in pass_rates.values()],
    })
    st.dataframe(rate_df, use_container_width=True, hide_index=True)

# ── 새로고침 ──────────────────────────────────────────────────────────
st.divider()
if st.button("🔄 데이터 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.caption(f"데이터: {JSON_PATH} | 새 결과를 보려면 canslim_run.py 재실행 후 새로고침")
