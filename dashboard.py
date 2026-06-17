"""통합 스크리너 대시보드
실행: python -m streamlit run dashboard.py
"""
import json
import requests
import pandas as pd
import streamlit as st
import yfinance as yf
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
from datetime import datetime, timedelta

st.set_page_config(page_title="Stock Dashboard", page_icon="📈", layout="wide")

st.markdown("""
<style>
html, body, [class*="css"] { font-size: 13px !important; }
.stDataFrame, .stDataFrame td, .stDataFrame th { font-size: 12px !important; }
.stTabs [data-baseweb="tab"] { font-size: 13px !important; font-weight: 600; padding: 6px 14px; }
section[data-testid="stSidebar"] * { font-size: 12px !important; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 18px !important; font-weight: 700; }
[data-testid="metric-container"] label { font-size: 11.5px !important; }
h1 { font-size: 19px !important; margin-bottom: 6px !important; }
h2 { font-size: 16px !important; margin-bottom: 5px !important; }
h3 { font-size: 14px !important; margin-bottom: 4px !important; }
</style>
""", unsafe_allow_html=True)

PERF_JSON        = Path('results/perf_latest.json')
SCREENER_JSON    = Path('results/screener_latest.json')
CANSLIM_JSON     = Path('results/canslim_latest.json')
TURNAROUND_JSON  = Path('results/turnaround_latest.json')
PORTFOLIO_FILE   = Path('data/portfolio.json')
PORTFOLIO_RESULT = Path('results/portfolio_latest.json')

SIG_COLS_PAST = ['past_sig_52w','past_sig_vol','past_sig_ma5','past_sig_cup','past_sig_maconv','past_sig_rsimacd']
SIG_COLS_NOW  = ['now_sig_52w', 'now_sig_vol', 'now_sig_ma5', 'now_sig_cup', 'now_sig_maconv', 'now_sig_rsimacd']
SIG_LABELS    = ['52주신고가','거래량폭발','5일라이딩','컵위드핸들','이평수렴','RSI/MACD']


# ── 공통 헬퍼 ────────────────────────────────────────────────────────
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
    try:
        v = float(str(val).replace('%','').replace('+',''))
        if v >= 20:  return 'color:#ff2222;font-weight:bold'
        if v >= 10:  return 'color:#ff6600;font-weight:bold'
        if v >= 3:   return 'color:#ffaa00'
        if v < -10:  return 'color:#4488ff;font-weight:bold'
        if v < 0:    return 'color:#88aaff'
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

@st.cache_data(ttl=3600)
def fetch_fred(series_id: str, limit: int = 24):
    url = f'https://api.stlouisfed.org/fred/series/observations'
    params = dict(series_id=series_id, api_key=FRED_KEY, file_type='json',
                  sort_order='desc', limit=limit)
    try:
        r = requests.get(url, params=params, timeout=10)
        obs = r.json()['observations']
        data = [(o['date'], float(o['value'])) for o in obs if o['value'] != '.']
        return sorted(data)
    except:
        return []

@st.cache_data(ttl=3600)
def fetch_spx_yoy():
    try:
        url = 'https://stooq.com/q/d/l/?s=^spx&i=m'
        df = pd.read_csv(url, parse_dates=['Date'])
        df = df.sort_values('Date').tail(15)
        if len(df) < 13:
            return None
        latest = float(df['Close'].iloc[-1])
        yr_ago = float(df['Close'].iloc[-13])
        return round((latest / yr_ago - 1) * 100, 2)
    except:
        return None

def compute_macro_signal(fed_rate, m2_yoy, spx_yoy):
    score = 0
    details = []
    if fed_rate is not None:
        if fed_rate <= 2.5:
            score += 2; details.append(f"Fed {fed_rate:.2f}% ✅ 완화")
        elif fed_rate <= 4.5:
            score += 1; details.append(f"Fed {fed_rate:.2f}% ⚠️ 중립")
        else:
            score -= 1; details.append(f"Fed {fed_rate:.2f}% ❌ 긴축")
    if m2_yoy is not None:
        if m2_yoy >= 5:
            score += 2; details.append(f"M2 YoY {m2_yoy:.1f}% ✅ 팽창")
        elif m2_yoy >= 0:
            score += 1; details.append(f"M2 YoY {m2_yoy:.1f}% ⚠️ 보통")
        else:
            score -= 1; details.append(f"M2 YoY {m2_yoy:.1f}% ❌ 수축")
    if spx_yoy is not None:
        if spx_yoy >= 10:
            score += 1; details.append(f"SPX YoY {spx_yoy:.1f}% ✅ 강세")
        elif spx_yoy >= -10:
            score += 0; details.append(f"SPX YoY {spx_yoy:.1f}% ⚠️ 보통")
        else:
            score -= 1; details.append(f"SPX YoY {spx_yoy:.1f}% ❌ 약세")
    if score >= 4:
        signal = "🟢 매수우호"
        cash_min, cash_max = 10, 20
    elif score >= 1:
        signal = "🟡 중립관망"
        cash_min, cash_max = 25, 40
    else:
        signal = "🔴 위험경계"
        cash_min, cash_max = 50, 70
    return signal, cash_min, cash_max, score, details


# ════════════════════════════════════════════════════════════════════
# 오늘의 종합 — 한 페이지 요약 (탭 위에 항상 표시)
# ════════════════════════════════════════════════════════════════════
st.title("📊 오늘의 종합")

_sum_paths = [SCREENER_JSON, CANSLIM_JSON, TURNAROUND_JSON, PERF_JSON]
_sum_mtimes = [m for m in (file_mtime(p) for p in _sum_paths) if m]
_latest_update = max(_sum_mtimes) if _sum_mtimes else "데이터 없음"
st.caption(f"🕐 마지막 업데이트: **{_latest_update}**  ·  자동 갱신 매일 06:00  ·  수동 갱신: run_update.bat")

_s_scr  = load_json(SCREENER_JSON) or {}
_s_can  = load_json(CANSLIM_JSON) or {}
_s_ta   = load_json(TURNAROUND_JSON) or {}

# 매크로 신호 (best-effort, 네트워크 실패 시 '—')
try:
    _fed = fetch_fred('FEDFUNDS', 1)
    _fed_rate = _fed[-1][1] if _fed else None
    _m2 = fetch_fred('M2SL', 14)
    _m2_yoy = round((_m2[-1][1] / _m2[-13][1] - 1) * 100, 1) if len(_m2) >= 13 else None
    _macro_sig = compute_macro_signal(_fed_rate, _m2_yoy, fetch_spx_yoy())[0]
except Exception:
    _macro_sig = "—"

_can_stocks = _s_can.get('stocks') or []
_mc1, _mc2, _mc3, _mc4, _mc5 = st.columns(5)
_mc1.metric("시장 방향", _s_can.get('market_dir', '—'))
_mc2.metric("매크로 신호", _macro_sig)
_mc3.metric("주봉 신호 종목", f"{_s_scr.get('total', '—')}개", help=f"기준일 {_s_scr.get('date','')}")
_mc4.metric("CANSLIM 통과", f"{len(_can_stocks)}개" if _can_stocks else "—")
_mc5.metric("흑자전환", f"{_s_ta.get('total', '—')}개", help=f"기준일 {_s_ta.get('date','')}")

if not _can_stocks:
    st.warning("⚠️ CANSLIM 결과가 비어있거나 손상됨 → run_update.bat 을 다시 돌려 갱신하세요.")

# 주봉 신호 상위 (신호 많은 순) — 한눈에 후보
try:
    _scr_stocks = _s_scr.get('stocks') or []
    if _scr_stocks:
        _df_sum = pd.DataFrame(_scr_stocks)
        _df_sum = _df_sum.sort_values('total_signals', ascending=False).head(12)
        _cols = [c for c in ['market', 'name', 'sym', 'total_signals',
                             'pct_change', 'dist_52w', 'sector'] if c in _df_sum.columns]
        _show = _df_sum[_cols].rename(columns={
            'market': '시장', 'name': '종목', 'sym': '코드', 'total_signals': '신호수',
            'pct_change': '등락%', 'dist_52w': '52주고가대비%', 'sector': '섹터'})
        st.markdown("##### 🔥 주봉 신호 상위 (신호 많은 순) — 자세한 건 아래 탭에서")
        st.dataframe(_show, use_container_width=True, hide_index=True)
except Exception as _e:
    st.caption(f"(요약 표 생략: {_e})")

st.divider()


# ── 탭 구성 ──────────────────────────────────────────────────────────
tab10, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
    "🧭 프로젝트 종합",
    "📈 월간 성과", "📊 주봉 스크리너", "🏆 CANSLIM",
    "🌍 매크로", "🎯 추천 포트", "🔄 흑자전환", "🔍 종목 분석", "💼 포트폴리오",
    "📒 페이퍼 트레이딩"
])


# ════════════════════════════════════════════════════════════════════
# 탭1: 월간 성과 분석
# ════════════════════════════════════════════════════════════════════
with tab1:
    st.header("📈 월간 성과 분석 — 상승률 순위")
    update_badge(PERF_JSON)
    perf = load_json(PERF_JSON)

    if perf is None:
        st.error("데이터 없음 → `python perf_run.py` 실행 후 새로고침")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("기준일", perf['date'])
        col2.metric("분석 종목", f"{perf['total']:,}개")
        stocks = perf['stocks']
        col3.metric("🇰🇷 KR", f"{sum(1 for s in stocks if s['market']=='KR'):,}개")
        col4.metric("🇺🇸 US", f"{sum(1 for s in stocks if s['market']=='US'):,}개")

        st.divider()

        with st.sidebar:
            st.header("📈 월간성과 필터")
            mkt1 = st.radio("시장", ["전체","KR","US"], key="perf_mkt")
            min_ret = st.slider("최소 4주 수익률(%)", -50, 100, -100, key="perf_minret")
            max_ret = st.slider("최대 4주 수익률(%)", -50, 200, 200, key="perf_maxret")
            st.markdown("**4주 전 신호 있었던 종목만**")
            fp52w    = st.checkbox("52주신고가", key="fp52w")
            fpvol    = st.checkbox("거래량폭발",  key="fpvol")
            fpmaconv = st.checkbox("이평수렴",    key="fpmaconv")
            fpcup    = st.checkbox("컵위드핸들",  key="fpcup")
            st.markdown("**현재 신호 있는 종목만**")
            fn52w    = st.checkbox("52주신고가",  key="fn52w")
            fnmaconv = st.checkbox("이평수렴",    key="fnmaconv")
            sort_p   = st.selectbox("정렬", ["4주수익률↓","1주수익률↓","시총↓"], key="perf_sort")

        rows = []
        for s in stocks:
            rows.append({
                '시장':      s['market'],
                '종목명':    s['name'],
                '코드':      s['sym'],
                '시총':      fmt_cap(s['marcap'], s['market']),
                '_marcap':   s['marcap'],
                '4주수익률': s['ret_4w'],
                '1주수익률': s['ret_1w'],
                '4주전신호': ', '.join(s['sigs_past']) if s['sigs_past'] else '없음',
                '현재신호':  ', '.join(s['sigs_now'])  if s['sigs_now']  else '없음',
                '4w_52주': tag(s.get('past_sig_52w')),
                '4w_거래량':tag(s.get('past_sig_vol')),
                '4w_이평':  tag(s.get('past_sig_maconv')),
                '4w_컵':    tag(s.get('past_sig_cup')),
                '4w_라이딩':tag(s.get('past_sig_ma5')),
                '4w_RSI':   tag(s.get('past_sig_rsimacd')),
                '현_52주':  tag(s.get('now_sig_52w')),
                '현_이평':  tag(s.get('now_sig_maconv')),
                '현_컵':    tag(s.get('now_sig_cup')),
                '_p52w':    s.get('past_sig_52w', False),
                '_pvol':    s.get('past_sig_vol',  False),
                '_pmaconv': s.get('past_sig_maconv',False),
                '_pcup':    s.get('past_sig_cup',  False),
                '_n52w':    s.get('now_sig_52w',   False),
                '_nmaconv': s.get('now_sig_maconv', False),
            })

        df1 = pd.DataFrame(rows)

        if mkt1 != "전체":
            df1 = df1[df1['시장'] == mkt1]
        df1 = df1[(df1['4주수익률'] >= min_ret) & (df1['4주수익률'] <= max_ret)]
        if fp52w:    df1 = df1[df1['_p52w']]
        if fpvol:    df1 = df1[df1['_pvol']]
        if fpmaconv: df1 = df1[df1['_pmaconv']]
        if fpcup:    df1 = df1[df1['_pcup']]
        if fn52w:    df1 = df1[df1['_n52w']]
        if fnmaconv: df1 = df1[df1['_nmaconv']]

        if sort_p == "4주수익률↓":   df1 = df1.sort_values('4주수익률', ascending=False)
        elif sort_p == "1주수익률↓": df1 = df1.sort_values('1주수익률', ascending=False)
        elif sort_p == "시총↓":       df1 = df1.sort_values('_marcap',   ascending=False)
        df1 = df1.reset_index(drop=True)
        df1.index += 1

        st.subheader(f"총 {len(df1):,}개 종목")

        show_detail = st.toggle("신호 상세 보기 (4주전 / 현재)", value=False)

        if show_detail:
            disp_cols = ['시장','종목명','코드','시총','4주수익률','1주수익률',
                         '4w_52주','4w_거래량','4w_이평','4w_컵','4w_라이딩','4w_RSI',
                         '현_52주','현_이평','현_컵']
        else:
            disp_cols = ['시장','종목명','코드','시총','4주수익률','1주수익률','4주전신호','현재신호']

        sig_display = ['4w_52주','4w_거래량','4w_이평','4w_컵','4w_라이딩','4w_RSI','현_52주','현_이평','현_컵']

        styled1 = df1[disp_cols].style \
            .applymap(color_ret, subset=['4주수익률','1주수익률']) \
            .format({'4주수익률': '{:+.1f}%', '1주수익률': '{:+.1f}%'})

        if show_detail:
            existing_sig_cols = [c for c in sig_display if c in disp_cols]
            if existing_sig_cols:
                styled1 = styled1.applymap(color_sig, subset=existing_sig_cols)

        st.dataframe(styled1, use_container_width=True, height=420)

        st.divider()
        st.subheader("📊 4주 전 신호별 평균 수익률")
        df_all = pd.DataFrame(rows)
        if mkt1 != "전체":
            df_all = df_all[df_all['시장'] == mkt1]

        sig_perf = []
        sig_keys = [('_p52w','52주신고가'),('_pvol','거래량폭발'),('_pmaconv','이평수렴'),
                    ('_pcup','컵위드핸들')]
        for key, label in sig_keys:
            sub = df_all[df_all[key] == True]
            if len(sub) >= 5:
                sig_perf.append({
                    '신호': label,
                    '종목수': len(sub),
                    '평균4주수익률': round(sub['4주수익률'].mean(), 2),
                    '중앙값': round(sub['4주수익률'].median(), 2),
                    '승률(>0%)': f"{(sub['4주수익률'] > 0).mean()*100:.1f}%",
                })
        if sig_perf:
            sp_df = pd.DataFrame(sig_perf).sort_values('평균4주수익률', ascending=False)
            st.dataframe(sp_df.style.applymap(color_ret, subset=['평균4주수익률','중앙값']),
                         use_container_width=True, hide_index=True)
            st.bar_chart(sp_df.set_index('신호')['평균4주수익률'])


# ════════════════════════════════════════════════════════════════════
# 탭2: 주봉 스크리너
# ════════════════════════════════════════════════════════════════════
with tab2:
    st.header("📊 주봉 스크리너 — 현재 신호 종목")
    update_badge(SCREENER_JSON)
    screener = load_json(SCREENER_JSON)

    if screener is None:
        st.error("데이터 없음 → `python weekly_run.py` 실행 후 새로고침")
    else:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("기준일", screener['date'])
        col2.metric("신호 종목", f"{screener['total']}개")
        stocks2 = screener['stocks']
        col3.metric("🇰🇷 KR", f"{sum(1 for s in stocks2 if s['market']=='KR')}개")
        col4.metric("🇺🇸 US", f"{sum(1 for s in stocks2 if s['market']=='US')}개")

        st.divider()

        with st.sidebar:
            st.divider()
            st.header("📊 스크리너 필터")
            mkt2     = st.radio("시장", ["전체","KR","US"], key="scr_mkt")
            min_sigs = st.slider("최소 신호 수", 1, 6, 1, key="scr_minsig")
            sort2    = st.selectbox("정렬", ["시총↓","주간수익률↓","신호수↓"], key="scr_sort")

        rows2 = []
        for s in stocks2:
            rows2.append({
                '시장':    s['market'],
                '종목명':  s['name'],
                '코드':    s['sym'],
                '시총':    fmt_cap(s['marcap'], s['market']),
                '_marcap': s['marcap'],
                '주간%':   s['pct_change'],
                '신호수':  s['total_signals'],
                '신호':    ', '.join(s['signals']),
                '52주신고가': tag(s.get('sig_52w')),
                '거래량':    tag(s.get('sig_vol')),
                '5일라이딩': tag(s.get('sig_ma5')),
                '컵위드핸들':tag(s.get('sig_cup')),
                '이평수렴':  tag(s.get('sig_maconv')),
                'RSI/MACD':  tag(s.get('sig_rsimacd')),
                '고가유형':  s.get('high_type',''),
            })

        df2 = pd.DataFrame(rows2)
        if mkt2 != "전체":
            df2 = df2[df2['시장'] == mkt2]
        df2 = df2[df2['신호수'] >= min_sigs]

        if sort2 == "시총↓":          df2 = df2.sort_values('_marcap', ascending=False)
        elif sort2 == "주간수익률↓":  df2 = df2.sort_values('주간%',   ascending=False)
        elif sort2 == "신호수↓":      df2 = df2.sort_values('신호수',  ascending=False)
        df2 = df2.reset_index(drop=True)
        df2.index += 1

        st.subheader(f"총 {len(df2)}개 종목")

        show_entry = st.toggle("📍 일봉 진입 타이밍 표시 (느림 ~30초)", value=False, key="show_entry")
        if show_entry:
            with st.spinner("일봉 데이터 조회 중..."):
                try:
                    from entry_timing import batch_check
                    stocks_for_check = [
                        {'sym': row['코드'], 'market': row['시장']}
                        for _, row in df2.iterrows()
                    ]
                    entry_results = batch_check(stocks_for_check[:30])
                    df2['진입'] = df2['코드'].map(
                        lambda s: entry_results.get(s, {}).get('grade', '⚪')
                    )
                except Exception as e:
                    st.warning(f"진입 타이밍 조회 실패: {e}")
                    df2['진입'] = '⚪'
        else:
            df2['진입'] = ''

        disp2 = ['시장','종목명','코드','시총','주간%']
        if show_entry:
            disp2.append('진입')
        disp2 += ['52주신고가','거래량','5일라이딩','컵위드핸들','이평수렴','RSI/MACD','신호수','고가유형']

        sig2_cols = ['52주신고가','거래량','5일라이딩','컵위드핸들','이평수렴','RSI/MACD']

        def color_entry(v):
            if '진입적정' in str(v): return 'color:#56d364;font-weight:bold'
            if '눌림대기' in str(v): return 'color:#ffa657'
            if '추격위험' in str(v): return 'color:#f78166'
            return 'color:#555'

        styled2 = df2[disp2].style \
            .applymap(color_sig, subset=sig2_cols) \
            .applymap(color_ret, subset=['주간%']) \
            .format({'주간%': '{:+.1f}%'})
        if show_entry and '진입' in disp2:
            styled2 = styled2.applymap(color_entry, subset=['진입'])

        st.dataframe(styled2, use_container_width=True, height=420)


# ════════════════════════════════════════════════════════════════════
# 탭3: CANSLIM (슬라이더 실시간 조정)
# ════════════════════════════════════════════════════════════════════
with tab3:
    st.header("🏆 CANSLIM 스크리너 (한국)")
    update_badge(CANSLIM_JSON)
    canslim = load_json(CANSLIM_JSON)

    if canslim is None:
        st.error("데이터 없음 → `python canslim_run.py` 실행 후 새로고침")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("기준일", canslim['date'])
        col2.metric("시장방향(M)", canslim['market_dir'])
        col3.metric("후보 종목", f"{len(canslim['stocks'])}개 (N+RS 사전필터)")

        if not canslim['market_ok']:
            st.warning("⚠️ KOSPI 하락추세 — 신규매수 주의")

        m_ok = canslim['market_ok']

        with st.sidebar:
            st.divider()
            st.header("🏆 CANSLIM 기준 조정")
            st.caption("슬라이더로 각 항목 기준을 실시간으로 바꿔보세요")
            th_N    = st.slider("N  52주 신고가 허용거리 (%)", -30, 0, -5, key="th_N",
                                help="예: -5 = 신고가 대비 5% 이내")
            th_S    = st.slider("S  거래량 배수 (60일 평균 대비)", 1.0, 4.0, 1.5, 0.1, key="th_S")
            th_Sb   = st.slider("S  캔들 몸통 비율 (%)", 10, 70, 40, key="th_Sb")
            th_Sbull = st.checkbox("S  양봉 필수", value=True, key="th_Sbull")
            th_L    = st.slider("L  상대강도 RS 하한 (퍼센타일)", 40, 95, 70, key="th_L",
                                help="12개월 수익률이 전체 상위 X%")
            st.divider()
            th_C    = st.slider("C  분기 순이익 성장 (%)", 0, 150, 20, key="th_C",
                                help="전년 동기 대비 순이익 성장")
            th_A1   = st.slider("A  연간 성장 — 최근년 (%)", -50, 150, 20, key="th_A1")
            th_A2   = st.slider("A  연간 성장 — 전년 (%)", -50, 150, 20, key="th_A2")
            th_I    = st.slider("I  기관+외인 순매수 하한 (억원·20일)", -2000, 10000, 0, 100, key="th_I",
                                help="최근 20거래일 기관+외국인 합산 순매수 (양수=매집, pykrx)")
            st.divider()
            st.caption("**필수 통과 항목 설정**")
            req_S = st.checkbox("S 통과 필수", value=False, key="req_S")
            req_C = st.checkbox("C 통과 필수", value=False, key="req_C")
            req_A = st.checkbox("A 통과 필수", value=False, key="req_A")
            req_I = st.checkbox("I 통과 필수", value=False, key="req_I")

        def _tag3(v, th, fmt='{:.1f}'):
            if v is None: return '?'
            if isinstance(v, str): return f"✅ {v}"   # '흑자전환' 등 텍스트 = 통과
            return f"{'✅' if v >= th else '❌'} {fmt.format(v)}"

        rows3 = []
        for s in canslim['stocks']:
            n_dist = s.get('n_dist_pct')
            vol    = s.get('s_vol_ratio')
            body   = s.get('s_body_pct')
            bull   = s.get('s_bull', False)
            rs     = s.get('rs_pct', 0)
            c_g    = s.get('c_growth_pct')
            a_y1   = s.get('a_growth_y1')
            a_y2   = s.get('a_growth_y2')
            i_inst = s.get('i_inst_pct')

            n_ok = n_dist is not None and n_dist >= th_N
            s_ok = (vol is not None and vol >= th_S and
                    body is not None and body >= th_Sb and
                    (not th_Sbull or bull))
            l_ok = rs >= th_L
            c_ok = (c_g == '흑자전환') or (isinstance(c_g, (int, float)) and c_g >= th_C)
            a_ok = (a_y1 is not None and a_y1 >= th_A1 and
                    a_y2 is not None and a_y2 >= th_A2)
            i_ok = i_inst is not None and i_inst >= th_I

            if not n_ok or not l_ok: continue
            if req_S and not s_ok:   continue
            if req_C and not c_ok:   continue
            if req_A and not a_ok:   continue
            if req_I and not i_ok:   continue

            score = sum([bool(m_ok), n_ok, l_ok, s_ok, c_ok, a_ok, i_ok])

            cap = s['marcap'] // 100_000_000
            if a_y1 is not None and a_y2 is not None:
                a_tag = f"{'✅' if a_ok else '❌'} {a_y1:+.0f}%/{a_y2:+.0f}%"
            elif a_y1 is not None:
                a_tag = f"{'✅' if a_y1>=th_A1 else '❌'} {a_y1:+.0f}%/??"
            else:
                a_tag = '?'

            rows3.append({
                '종목명':  s['name'],
                '코드':    s['sym'],
                '시총':    f"{cap/10000:.1f}조" if cap >= 10000 else f"{cap:,}억",
                '점수/7':  score,
                'RS':      _tag3(rs,     th_L,  '{:.0f}p'),
                'N 거리%': _tag3(n_dist, th_N,  '{:+.1f}%'),
                'S 배수':  _tag3(vol,    th_S,  '{:.1f}x'),
                'C 분기%': _tag3(c_g,    th_C,  '{:+.0f}%'),
                'A 연간%': a_tag,
                'I 순매수': _tag3(i_inst, th_I,  '{:+.0f}억'),
                '_score':  score,
            })

        df3 = pd.DataFrame(rows3) if rows3 else pd.DataFrame()

        if df3.empty:
            st.warning("조건을 충족하는 종목이 없습니다. 슬라이더를 완화해보세요.")
        else:
            df3 = df3.sort_values('_score', ascending=False).reset_index(drop=True)
            df3.index += 1

            def color_score3(val):
                try:
                    v = int(val)
                    if v >= 6: return 'background-color:#1a472a;color:white;font-weight:bold'
                    if v >= 5: return 'background-color:#2d6a4f;color:white'
                    if v >= 4: return 'color:#f0c040'
                except: pass
                return ''

            def color_cell3(v):
                s = str(v)
                if '✅' in s: return 'color:#2ecc71'
                if '❌' in s: return 'color:#f78166'
                return 'color:#8b949e'

            disp3 = ['종목명','코드','시총','점수/7','RS','N 거리%','S 배수','C 분기%','A 연간%','I 순매수']
            sig3c = ['RS','N 거리%','S 배수','C 분기%','A 연간%','I 순매수']

            st.subheader(f"총 {len(df3)}개 종목 | N✅ L✅ 필수, C/A/S/I는 슬라이더 기준으로 색상 표시")
            st.dataframe(
                df3[disp3].style
                    .applymap(color_score3, subset=['점수/7'])
                    .applymap(color_cell3,  subset=sig3c),
                use_container_width=True, height=380,
            )

            st.divider()
            st.subheader("📊 항목별 통과율 (현재 슬라이더 기준)")
            total3 = len(rows3)
            pr_counts = {
                'C 분기실적': sum(1 for r in rows3 if '✅' in str(r['C 분기%'])),
                'A 연간실적': sum(1 for r in rows3 if '✅' in str(r['A 연간%'])),
                'S 거래량':   sum(1 for r in rows3 if '✅' in str(r['S 배수'])),
                'I 기관수급': sum(1 for r in rows3 if '✅' in str(r['I 순매수'])),
            }
            pr_df = pd.DataFrame({
                '항목': list(pr_counts.keys()),
                '통과수': list(pr_counts.values()),
                '통과율(%)': [round(v/total3*100,1) for v in pr_counts.values()],
            })
            st.dataframe(pr_df, use_container_width=True, hide_index=True)


# ════════════════════════════════════════════════════════════════════
# 탭4: 글로벌 매크로
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600)
def fetch_fred_history(series_id: str, limit: int = 60):
    url = 'https://api.stlouisfed.org/fred/series/observations'
    params = dict(series_id=series_id, api_key=FRED_KEY, file_type='json',
                  sort_order='desc', limit=limit)
    try:
        r = requests.get(url, params=params, timeout=10)
        obs = r.json()['observations']
        data = [(o['date'], float(o['value'])) for o in obs if o['value'] != '.']
        df = pd.DataFrame(sorted(data), columns=['date', series_id])
        df['date'] = pd.to_datetime(df['date'])
        return df.set_index('date')
    except:
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_index_history(symbol: str, days: int = 365):
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        df = fdr.DataReader(symbol, start)[['Close']].rename(columns={'Close': symbol})
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except:
        return pd.DataFrame()

def _fred_latest(series_id: str):
    d = fetch_fred(series_id, 2)
    return d[-1][1] if d else None

def _fred_yoy(series_id: str):
    d = fetch_fred(series_id, 14)
    if len(d) >= 13 and d[-13][1] > 0:
        return round((d[-1][1] / d[-13][1] - 1) * 100, 2)
    return None

def _plotly_line(dfs, labels, colors, title, yformat='{:.2f}', height=260):
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
        title=dict(text=title, font=dict(size=13)),
        height=height, paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
        font=dict(color='#8b949e', size=10),
        margin=dict(l=0, r=0, t=35, b=0),
        legend=dict(orientation='h', y=1.18, x=0),
        hovermode='x unified',
    )
    fig.update_xaxes(gridcolor='#21262d', showgrid=True)
    fig.update_yaxes(gridcolor='#21262d', showgrid=True)
    return fig

with tab4:
    st.header("🌍 글로벌 매크로 대시보드")
    st.caption(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} (FRED · FDR, 1시간 캐시)")

    with st.spinner("데이터 로딩 중..."):
        fed_rate = _fred_latest('FEDFUNDS')
        kr_rate  = _fred_latest('INTDSRKRM193N')
        m2_yoy   = _fred_yoy('M2SL')
        spx_yoy  = fetch_spx_yoy()

    signal, cash_min, cash_max, score, details = compute_macro_signal(fed_rate, m2_yoy, spx_yoy)

    sig_color = {'🟢 매수우호': '#56d364', '🟡 중립관망': '#ffa657', '🔴 위험경계': '#f78166'}
    s_col = sig_color.get(signal, '#8b949e')
    st.markdown(
        f"<div style='background:#161b22;border:1px solid #30363d;border-left:4px solid {s_col};"
        f"border-radius:10px;padding:16px 20px;margin-bottom:8px'>"
        f"<span style='font-size:22px;font-weight:bold;color:{s_col}'>{signal}</span>"
        f"&nbsp;&nbsp;<span style='color:#8b949e;font-size:13px'>현금 권고 {cash_min}~{cash_max}% · 점수 {score}점</span>"
        f"<br><span style='color:#8b949e;font-size:12px'>" + " &nbsp;·&nbsp; ".join(details) + "</span>"
        f"</div>",
        unsafe_allow_html=True,
    )

    with st.spinner(""):
        ecb_rate = _fred_latest('ECBDFR')
        boj_rate = _fred_latest('IRSTCI01JPM156N')
        dgs10    = _fred_latest('DGS10')
        dgs2     = _fred_latest('DGS2')
        cpi_yoy_us = _fred_yoy('CPIAUCSL')
        unrate   = _fred_latest('UNRATE')

    spread = round(dgs10 - dgs2, 2) if dgs10 and dgs2 else None

    snap_cols = st.columns(7)
    snap_data = [
        ("Fed",    f"{fed_rate:.2f}%" if fed_rate else '-',  '❌' if fed_rate and fed_rate > 4.5 else '✅'),
        ("ECB",    f"{ecb_rate:.2f}%" if ecb_rate else '-',  '❌' if ecb_rate and ecb_rate > 3.5 else '✅'),
        ("BoK",    f"{kr_rate:.2f}%"  if kr_rate  else '-',  '⚠️'),
        ("M2 YoY", f"{m2_yoy:+.1f}%" if m2_yoy   else '-',  '✅' if m2_yoy and m2_yoy >= 5 else ('❌' if m2_yoy and m2_yoy < 0 else '⚠️')),
        ("10Y-2Y", f"{spread:+.2f}%"  if spread   else '-',  '🔴' if spread and spread < 0 else '✅'),
        ("CPI YoY",f"{cpi_yoy_us:+.1f}%" if cpi_yoy_us else '-', '✅' if cpi_yoy_us and cpi_yoy_us < 3 else '❌'),
        ("실업률", f"{unrate:.1f}%"   if unrate   else '-',  '✅'),
    ]
    for col, (label, val, flag) in zip(snap_cols, snap_data):
        col.metric(f"{flag} {label}", val)

    st.divider()

    st.subheader("🏦 주요국 중앙은행 기준금리")
    with st.spinner("금리 데이터 로딩..."):
        rate_series = [
            ('FEDFUNDS',        'Fed (미국)',   '#3b82f6'),
            ('ECBDFR',          'ECB (유럽)',   '#10b981'),
            ('IRSTCI01JPM156N', 'BoJ (일본)',   '#f59e0b'),
            ('INTDSRKRM193N',   'BoK (한국)',   '#ef4444'),
            ('IRSTCB01CNM156N', 'PBoC (중국)',  '#a855f7'),
        ]
        rate_dfs = [fetch_fred_history(s, 60) for s, _, _ in rate_series]

    fig_rates = _plotly_line(
        rate_dfs, [l for _,l,_ in rate_series], [c for _,_,c in rate_series],
        '중앙은행 기준금리 (%)', '{:.2f}', 280,
    )
    st.plotly_chart(fig_rates, use_container_width=True)

    col_yc1, col_yc2 = st.columns(2)
    with col_yc1:
        st.subheader("📉 미국 수익률 곡선 (10Y-2Y 스프레드)")
        with st.spinner(""):
            spread_df10 = fetch_fred_history('DGS10', 60)
            spread_df2  = fetch_fred_history('DGS2',  60)
        if not spread_df10.empty and not spread_df2.empty:
            merged = spread_df10.join(spread_df2, how='inner')
            merged['스프레드'] = merged['DGS10'] - merged['DGS2']
            fig_sp = go.Figure()
            colors_sp = ['rgba(86,211,100,0.8)' if v >= 0 else 'rgba(247,129,102,0.8)'
                         for v in merged['스프레드']]
            fig_sp.add_trace(go.Bar(x=merged.index, y=merged['스프레드'],
                                    marker_color=colors_sp, name='10Y-2Y'))
            fig_sp.add_hline(y=0, line_color='rgba(110,118,129,0.6)')
            fig_sp.update_layout(height=220, paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
                                 font=dict(color='#8b949e', size=10),
                                 margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            fig_sp.update_xaxes(gridcolor='#21262d')
            fig_sp.update_yaxes(gridcolor='#21262d')
            st.plotly_chart(fig_sp, use_container_width=True)
            if spread and spread < 0:
                st.warning(f"⚠️ 수익률 역전 중 ({spread:+.2f}%) — 역사적으로 12~18개월 후 침체 선행")
            else:
                st.success(f"✅ 정상 곡선 ({spread:+.2f}%)")

    with col_yc2:
        st.subheader("📊 US 인플레이션 (CPI YoY)")
        with st.spinner(""):
            cpi_df = fetch_fred_history('CPIAUCSL', 36)
        if not cpi_df.empty:
            cpi_df['CPI YoY%'] = cpi_df['CPIAUCSL'].pct_change(12) * 100
            fig_cpi = go.Figure()
            fig_cpi.add_trace(go.Scatter(x=cpi_df.index, y=cpi_df['CPI YoY%'],
                mode='lines', line=dict(color='#f59e0b', width=2), name='CPI YoY'))
            fig_cpi.add_hline(y=2, line_color='rgba(86,211,100,0.5)', line_dash='dash',
                              annotation_text=' 목표 2%')
            fig_cpi.update_layout(height=220, paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
                                  font=dict(color='#8b949e', size=10),
                                  margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            fig_cpi.update_xaxes(gridcolor='#21262d')
            fig_cpi.update_yaxes(gridcolor='#21262d', ticksuffix='%')
            st.plotly_chart(fig_cpi, use_container_width=True)

    st.divider()
    st.subheader("💧 글로벌 M2 유동성")
    with st.spinner("M2 데이터 로딩..."):
        m2_series = [
            ('M2SL',            'M2 (미국)',    '#3b82f6'),
            ('MABMM301EZM189S', 'M2 (유로존)',  '#10b981'),
            ('MYAGM2JPM189S',   'M2 (일본)',    '#f59e0b'),
            ('MYAGM2CNM189N',   'M2 (중국)',    '#ef4444'),
        ]
        m2_dfs = [fetch_fred_history(s, 36) for s, _, _ in m2_series]

    m2_yoy_dfs = []
    for df, (sid, label, color) in zip(m2_dfs, m2_series):
        if df.empty: continue
        yoy = df.copy()
        yoy[sid] = df[sid].pct_change(12) * 100
        yoy = yoy.dropna()
        m2_yoy_dfs.append((yoy, label, color))

    if m2_yoy_dfs:
        fig_m2 = _plotly_line(
            [x[0] for x in m2_yoy_dfs],
            [x[1] for x in m2_yoy_dfs],
            [x[2] for x in m2_yoy_dfs],
            'M2 통화량 YoY 증가율 (%)', '{:.1f}', 260,
        )
        fig_m2.add_hline(y=0, line_color='rgba(110,118,129,0.4)', line_dash='dash')
        fig_m2.add_hline(y=5, line_color='rgba(86,211,100,0.3)', line_dash='dot',
                         annotation_text=' 팽창 기준 5%')
        st.plotly_chart(fig_m2, use_container_width=True)

    st.divider()
    st.subheader("📈 주요 주식시장 지수")
    with st.spinner("지수 데이터 로딩..."):
        idx_configs = [
            ('KS11',  '코스피 🇰🇷',   '#ef4444'),
            ('SPY',   'S&P500 🇺🇸',   '#3b82f6'),
            ('QQQ',   'NASDAQ 🇺🇸',   '#8b5cf6'),
            ('N225',  'Nikkei 🇯🇵',   '#f59e0b'),
            ('GDAXI', 'DAX 🇩🇪',      '#10b981'),
        ]
        idx_rows = []
        idx_chart_dfs = []
        for sym, label, color in idx_configs:
            df_i = fetch_index_history(sym, 400)
            idx_chart_dfs.append((df_i, label, color))
            if df_i.empty: continue
            cur   = float(df_i.iloc[-1].values[0])
            prev  = float(df_i.iloc[-2].values[0]) if len(df_i) > 1 else cur
            yr_ago = float(df_i.iloc[-252].values[0]) if len(df_i) > 252 else None
            chg_d = (cur/prev - 1)*100
            chg_y = (cur/yr_ago - 1)*100 if yr_ago else None
            hi52  = float(df_i.tail(252).max().values[0])
            lo52  = float(df_i.tail(252).min().values[0])
            idx_rows.append({
                '지수': label,
                '현재': f"{cur:,.1f}",
                '전일대비': f"{chg_d:+.2f}%",
                'YoY': f"{chg_y:+.1f}%" if chg_y else '-',
                '52주위치': f"{(cur-lo52)/(hi52-lo52)*100:.0f}%" if hi52 > lo52 else '-',
            })

    if idx_rows:
        idx_df = pd.DataFrame(idx_rows)
        def _ci_chg(v):
            try:
                return 'color:#56d364' if float(str(v).replace('%','').replace('+','')) >= 0 else 'color:#f78166'
            except: return ''
        st.dataframe(
            idx_df.style.applymap(_ci_chg, subset=['전일대비','YoY']),
            use_container_width=True, hide_index=True,
            height=36 + 35*len(idx_df),
        )

    valid_idx = [(df, l, c) for df, l, c in idx_chart_dfs if not df.empty]
    if valid_idx:
        fig_idx = go.Figure()
        for df_i, label, color in valid_idx:
            base = float(df_i.iloc[0].values[0])
            if base > 0:
                normalized = (df_i.iloc[:, 0] / base - 1) * 100
                fig_idx.add_trace(go.Scatter(
                    x=df_i.index, y=normalized, mode='lines', name=label,
                    line=dict(color=color, width=1.8),
                    hovertemplate=f'{label}: %{{y:.1f}}%<extra></extra>',
                ))
        fig_idx.add_hline(y=0, line_color='rgba(110,118,129,0.4)', line_dash='dash')
        fig_idx.update_layout(
            title='주요 지수 상대 성과 (1년 전 = 0%)',
            height=280, paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
            font=dict(color='#8b949e', size=10),
            margin=dict(l=0,r=0,t=35,b=0),
            legend=dict(orientation='h', y=1.18, x=0),
            hovermode='x unified', yaxis_ticksuffix='%',
        )
        fig_idx.update_xaxes(gridcolor='#21262d')
        fig_idx.update_yaxes(gridcolor='#21262d')
        st.plotly_chart(fig_idx, use_container_width=True)

    st.divider()
    st.subheader("💼 포트폴리오 현금비중 결정")
    pc1, pc2 = st.columns(2)
    with pc1:
        capital_m = st.number_input("투자 가능 자본 (원)", min_value=0, value=10_000_000,
                                    step=1_000_000, format="%d", key="macro_capital")
        cash_mid  = (cash_min + cash_max) / 2
        st.metric("권고 현금",   f"{capital_m * cash_mid/100:,.0f}원 ({cash_mid:.0f}%)")
        st.metric("주식 투자 가용", f"{capital_m * (1-cash_mid/100):,.0f}원")
        st.divider()
        st.caption("**시그널 상세**")
        for d in details: st.write(f"• {d}")

    with pc2:
        st.caption("**매크로 시나리오 & 전략 가이드**")
        scenario_data = [
            {'시나리오':'🟢 매수우호','조건':'Fed ≤2.5% & M2↑ & SPX↑','현금비중':'10~20%',
             '전략':'적극 매수 — 1~2급 신호 집중'},
            {'시나리오':'🟡 중립관망','조건':'혼조 — 금리 중간 or M2 보통','현금비중':'25~40%',
             '전략':'선별 매수 — 1급 신호(52주·이평수렴) 위주'},
            {'시나리오':'🔴 위험경계','조건':'Fed ≥4.5% or M2↓ or SPX↓10%','현금비중':'50~70%',
             '전략':'비중 축소 — 손절 룰 강화, 신규매수 자제'},
        ]
        st.dataframe(pd.DataFrame(scenario_data), use_container_width=True, hide_index=True,
                     height=36+35*3)


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

def _kelly_pct(score):
    if score >= 8:  return 15
    if score >= 6:  return 12
    if score >= 4:  return 9
    return 5

def _load_pf() -> list:
    if not PORTFOLIO_FILE.exists(): return []
    try: return json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8')).get('positions', [])
    except: return []

def _save_pf(positions: list):
    PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
    data = {'updated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'positions': positions}
    PORTFOLIO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

with tab5:
    st.header("🎯 추천 포트폴리오 — 자동 생성")
    update_badge(SCREENER_JSON)

    screener5 = load_json(SCREENER_JSON)
    if screener5 is None:
        st.error("데이터 없음 → `python weekly_run.py` 실행 후 새로고침")
    else:
        with st.spinner("매크로 확인 중..."):
            fd  = fetch_fred('FEDFUNDS', 3)
            m2d = fetch_fred('M2SL', 14)
            spx = fetch_spx_yoy()
        fed_r = fd[-1][1] if fd else None
        m2y   = None
        if len(m2d) >= 13:
            lv, pv = m2d[-1][1], m2d[-13][1]
            if pv > 0: m2y = round((lv/pv - 1)*100, 2)
        macro_sig, cash_min, cash_max, _, _ = compute_macro_signal(fed_r, m2y, spx)
        cash_pct   = (cash_min + cash_max) / 2 / 100
        invest_pct = 1 - cash_pct

        c1, c2, c3 = st.columns(3)
        c1.metric("매크로 시그널",    macro_sig)
        c2.metric("현금 권고",        f"{cash_min}~{cash_max}%")
        c3.metric("주식 투자 가능",   f"{invest_pct*100:.0f}%")

        st.divider()

        with st.sidebar:
            st.divider()
            st.header("🎯 추천 필터")
            rec_mkt    = st.radio("시장", ["전체(균형)","전체(점수순)","KR","US"], key="rec_mkt")
            rec_top_n  = st.slider("추천 종목 수", 3, 10, 6, key="rec_topn")
            rec_kr_min = st.slider("KR 최소 종목 수", 0, 5, 2, key="rec_kr_min")
            rec_primary_only = st.checkbox("1급 신호 포함 종목만", value=True, key="rec_prim")
            capital5   = st.number_input("투자 자본 (원/$)", min_value=0, value=10_000_000,
                                         step=1_000_000, format="%d", key="rec_cap")

        def _score_all(mkt_filter=None):
            result = []
            for s in screener5['stocks']:
                if mkt_filter and s['market'] != mkt_filter:
                    continue
                sc, has_prim = _signal_score(s)
                if rec_primary_only and not has_prim:
                    continue
                result.append((sc, s))
            result.sort(key=lambda x: x[0], reverse=True)
            return result

        if rec_mkt == "전체(균형)":
            kr_scored = _score_all('KR')
            us_scored = _score_all('US')
            kr_take   = min(rec_kr_min, len(kr_scored))
            seen = set(); top_dedup = []
            for item in (kr_scored[:kr_take] + sorted(
                kr_scored[kr_take:] + us_scored, key=lambda x: x[0], reverse=True
            )):
                sym_key = item[1]['sym']
                if sym_key not in seen:
                    seen.add(sym_key); top_dedup.append(item)
                if len(top_dedup) >= rec_top_n: break
            top = top_dedup
        elif rec_mkt == "전체(점수순)":
            top = _score_all()[:rec_top_n]
        else:
            top = _score_all(rec_mkt)[:rec_top_n]

        if not top:
            st.warning("조건에 맞는 종목이 없습니다. 필터를 완화해보세요.")
        else:
            alloc_rows = []
            total_stock_pct = 0
            for sc, s in top:
                raw_pct = _kelly_pct(sc)
                pos_pct = round(raw_pct * invest_pct, 1)
                total_stock_pct += pos_pct
                dist = s.get('dist_52w')
                alloc_rows.append({
                    '시장':     s['market'],
                    '종목명':   s['name'],
                    '코드':     s['sym'],
                    '신호':     ', '.join(s['signals']),
                    '신호점수': sc,
                    '주간%':    s['pct_change'],
                    '52주거리%': round(dist, 1) if dist is not None else '-',
                    '추천비중%': pos_pct,
                    '추천금액': f"{int(capital5 * pos_pct / 100):,}",
                    '_52w':    s.get('sig_52w'),
                    '_maconv': s.get('sig_maconv'),
                })

            actual_cash_pct = round(100 - total_stock_pct, 1)
            df5 = pd.DataFrame(alloc_rows)

            def color_score(val):
                try:
                    v = float(val)
                    if v >= 8: return 'background-color:#1a472a;color:white;font-weight:bold'
                    if v >= 6: return 'background-color:#2d6a4f;color:white'
                    if v >= 4: return 'color:#f0c040'
                except: pass
                return ''

            def color_dist(val):
                try:
                    v = float(str(val).replace('%',''))
                    if   0 <= v <= 5:  return 'color:#2ecc71;font-weight:bold'
                    elif -5 <= v < 0:  return 'color:#f0c040'
                    elif v > 20:       return 'color:#888'
                except: pass
                return ''

            disp5 = ['시장','종목명','코드','신호','신호점수','주간%','52주거리%','추천비중%','추천금액']
            styled5 = df5[disp5].style \
                .applymap(color_score, subset=['신호점수']) \
                .applymap(color_ret,   subset=['주간%']) \
                .applymap(color_dist,  subset=['52주거리%']) \
                .format({'주간%': '{:+.1f}%', '추천비중%': '{}%'})

            st.subheader(f"📋 상위 {len(top)}개 추천 종목")
            st.dataframe(styled5, use_container_width=True, hide_index=True)

            st.divider()
            bar_data = {r['종목명']: r['추천비중%'] for r in alloc_rows}
            bar_data['💵 현금'] = actual_cash_pct
            st.subheader("💼 포트폴리오 비중")
            bar_df = pd.DataFrame({'비중(%)': bar_data})
            st.bar_chart(bar_df)

            col_a, col_b, col_c = st.columns(3)
            col_a.metric("주식 합계",  f"{total_stock_pct:.1f}%")
            col_b.metric("현금",       f"{actual_cash_pct:.1f}%")
            col_c.metric("추천 종목수", f"{len(top)}개")

            st.divider()
            st.subheader("📥 이 추천 포트폴리오를 내 포트폴리오에 추가")
            col_imp1, col_imp2 = st.columns([3, 1])
            with col_imp1:
                imp_capital = st.number_input(
                    "실제 투자 자본 (원/$)", min_value=0, value=capital5,
                    step=1_000_000, format="%d", key="imp_capital"
                )
            with col_imp2:
                st.write("")
                do_import = st.button("💼 포트폴리오에 추가", key="do_import", use_container_width=True)

            if do_import:
                import FinanceDataReader as _fdr
                existing = _load_pf()
                existing_syms = {p['sym'] for p in existing}
                added, skipped = [], []

                for r in alloc_rows:
                    sym_i  = r['코드']
                    mkt_i  = r['시장']
                    name_i = r['종목명']
                    pct_i  = r['추천비중%']

                    if sym_i in existing_syms:
                        skipped.append(sym_i); continue

                    try:
                        code_i = sym_i.replace('.KS','')
                        fdr_sym_i = code_i if mkt_i == 'KR' else sym_i
                        start_i = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
                        df_i = _fdr.DataReader(fdr_sym_i, start_i)
                        cur_px_i = float(df_i['Close'].iloc[-1]) if not df_i.empty else 0
                    except:
                        cur_px_i = 0

                    invest_amt_i = imp_capital * pct_i / 100
                    qty_i = invest_amt_i / cur_px_i if cur_px_i > 0 else 0

                    existing.append({
                        'id':             f"{sym_i}_{datetime.now().strftime('%Y%m%d')}",
                        'sym':            sym_i,
                        'name':           name_i,
                        'market':         mkt_i,
                        'qty':            round(qty_i, 4),
                        'buy_price':      round(cur_px_i, 4),
                        'buy_date':       datetime.now().strftime('%Y-%m-%d'),
                        'stop_loss_pct':  7.0,
                        'target_pct':     20.0,
                        'note':           f"추천포트 {r['신호']} ({r['추천비중%']}%)",
                    })
                    added.append(sym_i)

                _save_pf(existing)
                st.cache_data.clear()
                if added:
                    st.success(f"✅ {', '.join(added)} 추가 완료 → 탭8 포트폴리오에서 확인")
                if skipped:
                    st.info(f"이미 보유 중: {', '.join(skipped)} (중복 제외)")


# ════════════════════════════════════════════════════════════════════
# 탭6: 흑자전환 스크리너
# ════════════════════════════════════════════════════════════════════
with tab6:
    st.header("🔄 흑자전환 스크리너 — 테슬라 2019 Q3 같은 종목")
    update_badge(TURNAROUND_JSON)
    ta = load_json(TURNAROUND_JSON)

    if ta is None:
        st.error("데이터 없음 → `python turnaround_run.py` 실행 후 새로고침")
        st.info("처음 실행 시 S&P500 전체 재무 데이터 다운로드로 30~60분 소요될 수 있습니다.\n"
                "이후 실행은 7일 캐시로 5~10분으로 단축됩니다.")
    else:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("기준일",       ta['date'])
        m2.metric("전체 발굴",    f"{ta['total']}개")
        m3.metric("🇰🇷 KR",       f"{ta['kr']}개")
        m4.metric("🇺🇸 US",       f"{ta['us']}개")

        st.divider()

        with st.sidebar:
            st.divider()
            st.header("🔄 흑자전환 필터")
            ta_mkt    = st.radio("시장", ["전체","KR","US"], key="ta_mkt")
            ta_status = st.multiselect("상태",
                ['흑자전환완료','흑자전환임박','적자개선중'],
                default=['흑자전환완료','흑자전환임박'],
                key="ta_status")
            ta_rev    = st.checkbox("매출 YoY 20%+ 종목만", value=False, key="ta_rev")
            ta_gm     = st.checkbox("마진 개선 종목만",      value=False, key="ta_gm")
            ta_sort   = st.selectbox("정렬", ["점수↓","YoY성장↓","매출성장↓","시총↓"], key="ta_sort")

        def status_color(s):
            if s == '흑자전환완료': return 'background-color:#1a472a;color:white;font-weight:bold'
            if s == '흑자전환임박': return 'background-color:#7d4e00;color:white'
            return 'color:#aaa'

        def yoy_color(v):
            try:
                f = float(str(v).replace('%',''))
                if f >= 80: return 'color:#2ecc71;font-weight:bold'
                if f >= 50: return 'color:#f0c040'
                if f >= 25: return 'color:#aaa'
            except: pass
            return ''

        ta_stocks = ta['stocks']
        if ta_mkt != "전체":
            ta_stocks = [s for s in ta_stocks if s['market'] == ta_mkt]
        if ta_status:
            ta_stocks = [s for s in ta_stocks if s['status'] in ta_status]
        if ta_rev:
            ta_stocks = [s for s in ta_stocks if s.get('rev_growth') and s['rev_growth'] >= 20]
        if ta_gm:
            ta_stocks = [s for s in ta_stocks if s.get('gm_improving')]

        rows7 = []
        for s in ta_stocks:
            rows7.append({
                '시장':       s['market'],
                '종목명':     s['name'],
                '코드':       s['sym'],
                '시총':       fmt_cap(s['marcap'], s['market']),
                '_marcap':    s['marcap'],
                '상태':       s['status'],
                '점수':       s['score'],
                '최근Q NI':   s['q0_ni'],
                'Q-1 NI':     s['q1_ni'],
                'Q-2 NI':     s['q2_ni'],
                'Q-3 NI':     s['q3_ni'],
                'TTM NI':     s['ttm_ni'],
                'YoY성장%':   s.get('yoy_imp_pct'),
                '매출YoY%':   s.get('rev_growth'),
                '마진개선':   '✅' if s.get('gm_improving') else '·',
                '최근날짜':   s.get('q0_date',''),
            })

        df7 = pd.DataFrame(rows7)
        if df7.empty:
            st.warning("조건에 맞는 종목이 없습니다.")
        else:
            if ta_sort == "점수↓":
                df7 = df7.sort_values('점수', ascending=False)
            elif ta_sort == "YoY성장↓":
                df7 = df7.sort_values('YoY성장%', ascending=False, na_position='last')
            elif ta_sort == "매출성장↓":
                df7 = df7.sort_values('매출YoY%', ascending=False, na_position='last')
            elif ta_sort == "시총↓":
                df7 = df7.sort_values('_marcap', ascending=False)
            df7 = df7.reset_index(drop=True)
            df7.index += 1

            st.subheader(f"총 {len(df7)}개 종목")

            disp7 = ['시장','종목명','코드','시총','상태','점수',
                     '최근Q NI','Q-1 NI','Q-2 NI','Q-3 NI','TTM NI',
                     'YoY성장%','매출YoY%','마진개선','최근날짜']

            def fmt_pct(v):
                try:
                    return f"{float(v):+.1f}%" if v is not None else '-'
                except:
                    return '-'

            styled7 = df7[disp7].style \
                .applymap(status_color, subset=['상태']) \
                .applymap(yoy_color,   subset=['YoY성장%']) \
                .applymap(color_sig,   subset=['마진개선']) \
                .format({'YoY성장%': fmt_pct, '매출YoY%': fmt_pct}, na_rep='-')

            st.dataframe(styled7, use_container_width=True, height=420)

            st.divider()
            st.subheader("📊 상태별 요약")
            sum_rows = []
            for st_label in ['흑자전환완료','흑자전환임박','적자개선중']:
                sub = df7[df7['상태'] == st_label]
                if len(sub) > 0:
                    sum_rows.append({
                        '상태':     st_label,
                        '종목수':   len(sub),
                        'KR':       len(sub[sub['시장']=='KR']),
                        'US':       len(sub[sub['시장']=='US']),
                        '평균점수': round(sub['점수'].mean(), 1),
                    })
            if sum_rows:
                st.dataframe(pd.DataFrame(sum_rows), use_container_width=True, hide_index=True)

            st.caption(
                "📌 점수 기준: 흑자전환완료=5점 / 흑자전환직전=4점 / 흑자전환임박(YoY≥0%)=3점 / 적자개선중(YoY≥5%)=2점 "
                "+ 매출YoY>20%=+1 / 마진개선=+1 / TTM개선=+1  ·  YoY성장%: 최근 날짜 전년도 대비 순이익 개선"
            )


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

@st.cache_data(ttl=1800)
def fetch_stock_data(sym: str, days: int):
    import FinanceDataReader as fdr

    is_kr = sym.isdigit() and len(sym) == 6
    code  = sym.replace('.KS','').replace('.KQ','')
    fdr_sym = code if is_kr else sym
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    try:
        hist = fdr.DataReader(fdr_sym, start)
        hist.index = pd.to_datetime(hist.index).tz_localize(None)
        for c in ['Open','High','Low','Close','Volume']:
            if c not in hist.columns: hist[c] = 0.0

        info = {}
        if is_kr:
            try:
                krx = fdr.StockListing('KRX')
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

        earn = insid = fin_est = None
        yf_sym = f"{code}.KS" if is_kr else sym
        try:
            t = yf.Ticker(yf_sym)
            yi = t.info or {}
            if yi and (yi.get('trailingPE') or yi.get('longName')):
                info.update({k: v for k, v in yi.items() if v is not None})
            try: earn = t.quarterly_financials
            except: pass
            if not is_kr:
                try: insid = t.insider_transactions
                except: pass
                try: fin_est = t.earnings_estimate
                except: pass
        except: pass

        return hist, info, earn, insid, fin_est
    except Exception as e:
        return None, {}, None, None, None

with tab7:
    st.header("🔍 종목 분석")
    st.caption("US: TSLA · AAPL · NVDA  |  KR: 005930 또는 005930.KS")

    c_in, c_tf, c_btn = st.columns([3, 2, 1])
    with c_in:
        sym8 = st.text_input("종목코드", placeholder="TSLA", label_visibility="collapsed", key="sym8")
    with c_tf:
        tf8  = st.selectbox("기간", ["1y (단기)", "3y (중기)", "5y (장기)"], key="tf8",
                             label_visibility="collapsed")
    with c_btn:
        go8  = st.button("분석", use_container_width=True, key="go8")

    st.markdown(
        " ".join([f'<span style="background:#1c2128;padding:2px 8px;border-radius:12px;'
                   f'font-size:12px;color:#8b949e">{s}</span>'
                  for s in ['TSLA','AAPL','NVDA','MSFT','QCOM','CRWD','005930','000660']]),
        unsafe_allow_html=True,
    )

    if sym8 and go8:
        days_map = {"1y (단기)": 365, "3y (중기)": 365*3, "5y (장기)": 365*5}
        days_sel = days_map[tf8]
        sym8_clean = sym8.strip().upper()
        with st.spinner(f"{sym8_clean} 데이터 조회..."):
            hist, info, earn, insid, fin_est = fetch_stock_data(sym8_clean, days_sel)

        if hist is None or hist.empty:
            st.error(f"데이터 없음 ({sym8_clean}). 종목코드 확인 — KR: 005930 · US: TSLA")
        else:
            price_now = hist['Close'].iloc[-1]
            price_prev= hist['Close'].iloc[-2] if len(hist) > 1 else price_now
            chg_pct   = (price_now / price_prev - 1) * 100

            h1, h2, h3, h4, h5 = st.columns(5)
            h1.metric("종목명", info.get('longName', sym8)[:20])
            h2.metric("현재가", f"${price_now:.2f}" if info.get('currency','') != 'KRW' else f"₩{price_now:,.0f}")
            h3.metric("일일대비", f"{chg_pct:+.2f}%")
            mc = info.get('marketCap', 0)
            h4.metric("시가총액", f"${mc/1e9:.1f}B" if mc >= 1e9 else f"${mc/1e6:.0f}M" if mc else "-")
            h5.metric("섹터", info.get('sector', '-'))

            st.divider()

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

            window60 = hist.tail(60)
            fib_high = window60['High'].max()
            fib_low  = window60['Low'].min()
            fib_lvls = _fib(fib_high, fib_low)

            fig = make_subplots(
                rows=4, cols=1, shared_xaxes=True,
                row_heights=[0.55, 0.15, 0.15, 0.15],
                vertical_spacing=0.02,
                subplot_titles=('캔들 · 이동평균 · 피보나치', 'RSI (14)', 'MACD (12·26·9)', '거래량'),
            )
            disp = hist.tail(min(252, len(hist)))

            is_kr_sym = sym8_clean.isdigit() and len(sym8_clean) == 6
            price_unit = '₩' if is_kr_sym else '$'

            fig.add_trace(go.Candlestick(
                x=disp.index, open=disp['Open'], high=disp['High'],
                low=disp['Low'], close=disp['Close'],
                increasing_line_color='#56d364', decreasing_line_color='#f78166',
                name='캔들', showlegend=False,
            ), row=1, col=1)

            for col_name, color, lw in [('MA20','#f78166',1),('MA50','#ffa657',1),('MA200','#a371f7',1.5)]:
                fig.add_trace(go.Scatter(
                    x=disp.index, y=disp[col_name], mode='lines',
                    line=dict(color=color, width=lw), name=col_name,
                ), row=1, col=1)

            fib_colors = [
                'rgba(110,118,129,0.5)', 'rgba(88,166,255,0.4)',
                'rgba(255,166,87,0.4)',  'rgba(255,123,114,0.4)',
                'rgba(88,166,255,0.4)',  'rgba(255,166,87,0.4)',
                'rgba(110,118,129,0.5)',
            ]
            for (fib_label, fib_price), fc in zip(fib_lvls.items(), fib_colors):
                fig.add_hline(y=fib_price, line_color=fc, line_dash='dot',
                              annotation_text=f' {fib_label} {price_unit}{fib_price:,.0f}',
                              annotation_position='right', row=1, col=1)

            fig.add_trace(go.Scatter(
                x=disp.index, y=disp['RSI'], mode='lines',
                line=dict(color='#79c0ff', width=1.5), name='RSI', showlegend=False,
            ), row=2, col=1)
            fig.add_hline(y=70, line_color='rgba(247,129,102,0.4)', line_dash='dot', row=2, col=1)
            fig.add_hline(y=30, line_color='rgba(86,211,100,0.4)',  line_dash='dot', row=2, col=1)

            fig.add_trace(go.Bar(
                x=disp.index, y=disp['Hist'], name='히스토그램',
                marker_color=['rgba(86,211,100,0.6)' if v >= 0 else 'rgba(247,129,102,0.6)' for v in disp['Hist']],
                showlegend=False,
            ), row=3, col=1)
            fig.add_trace(go.Scatter(x=disp.index, y=disp['MACD'],   mode='lines',
                line=dict(color='#79c0ff', width=1.5), name='MACD', showlegend=False), row=3, col=1)
            fig.add_trace(go.Scatter(x=disp.index, y=disp['Signal'], mode='lines',
                line=dict(color='#ffa657', width=1), name='Signal', showlegend=False), row=3, col=1)

            fig.add_trace(go.Bar(
                x=disp.index, y=disp['Volume'], name='거래량',
                marker_color='rgba(56,139,253,0.35)', showlegend=False,
            ), row=4, col=1)

            fig.update_layout(
                height=780, paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
                font=dict(color='#8b949e', size=11),
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=100, t=30, b=0),
                legend=dict(orientation='h', y=1.02, x=0),
            )
            for i in range(1, 5):
                fig.update_xaxes(gridcolor='#21262d', row=i, col=1)
                fig.update_yaxes(gridcolor='#21262d', row=i, col=1)
            fig.update_yaxes(title_text='RSI', row=2, col=1, range=[0, 100])

            st.plotly_chart(fig, use_container_width=True)

            fib_ext_lvls = _fib_ext(fib_high, fib_low)
            with st.expander("📐 피보나치 레벨 상세 (최근 60일 기준)", expanded=False):
                fc1, fc2 = st.columns(2)
                def _fmt_p(v): return f"₩{v:,.0f}" if is_kr_sym else f"${v:.2f}"
                def _fmt_chg(v): return f"{(v/price_now-1)*100:+.1f}%"

                with fc1:
                    st.caption("📉 되돌림(지지선)")
                    ret_df = pd.DataFrame([
                        {'레벨': k, '가격': _fmt_p(v), '현재 대비': _fmt_chg(v)}
                        for k, v in fib_lvls.items()
                    ])
                    st.dataframe(ret_df, use_container_width=True, hide_index=True,
                                 height=36 + 35 * len(ret_df))

                with fc2:
                    st.caption("📈 연장 (목표가격)")
                    ext_df = pd.DataFrame([
                        {'레벨': k, '목표가': _fmt_p(v), '현재 대비': _fmt_chg(v)}
                        for k, v in fib_ext_lvls.items()
                    ])
                    def _color_ext(v):
                        try:
                            pct = float(str(v).replace('%','').replace('+',''))
                            if pct > 0: return 'color:#56d364'
                        except: pass
                        return ''
                    st.dataframe(
                        ext_df.style.applymap(_color_ext, subset=['현재 대비']),
                        use_container_width=True, hide_index=True,
                        height=36 + 35 * len(ext_df),
                    )

            st.divider()
            left8, right8 = st.columns(2)

            yr1  = hist.tail(252)
            yr_h = yr1['High'].max();   yr_l = yr1['Low'].min()
            ret_1m  = (price_now / hist['Close'].iloc[-22] - 1)*100  if len(hist) > 22  else None
            ret_3m  = (price_now / hist['Close'].iloc[-66] - 1)*100  if len(hist) > 66  else None
            ret_6m  = (price_now / hist['Close'].iloc[-126] - 1)*100 if len(hist) > 126 else None
            ret_1y  = (price_now / hist['Close'].iloc[-252] - 1)*100 if len(hist) > 252 else None
            vol_20  = hist['Close'].pct_change().tail(20).std() * (252**0.5) * 100

            with left8:
                def _b(v, ccy='$'):
                    if v is None: return '-'
                    av = abs(v)
                    s = '-' if v < 0 else ''
                    if av >= 1e12: return f"{s}{ccy}{av/1e12:.2f}T"
                    if av >= 1e9:  return f"{s}{ccy}{av/1e9:.2f}B"
                    return f"{s}{ccy}{av/1e6:.0f}M"

                st.subheader("📅 연간 실적")
                if earn is not None and not earn.empty:
                    rows_e = []
                    for col in sorted(earn.columns, reverse=True)[:6]:
                        rev = earn.get('Total Revenue', pd.Series()).get(col)
                        net = earn.get('Net Income',    pd.Series()).get(col)
                        rows_e.append({'날짜': str(col)[:7], '매출': _b(rev), '순이익': _b(net)})
                    if rows_e:
                        e_df = pd.DataFrame(rows_e)
                        st.dataframe(e_df, use_container_width=True, hide_index=True,
                                     height=36 + 35*len(e_df))
                else:
                    st.info("실적 데이터 없음")

                st.subheader("📈 기간별 수익률")
                r_df = pd.DataFrame([
                    {'기간': k, '수익률': f"{v:+.1f}%" if v is not None else '-'}
                    for k, v in [('1개월', ret_1m),('3개월', ret_3m),('6개월', ret_6m),('1년', ret_1y)]
                ])
                def _cr(v):
                    try:
                        f = float(str(v).replace('%','').replace('+',''))
                        return 'color:#56d364' if f >= 0 else 'color:#f78166'
                    except: return ''
                st.dataframe(r_df.style.applymap(_cr, subset=['수익률']),
                             use_container_width=True, hide_index=True,
                             height=36 + 35*len(r_df))

            with right8:
                st.subheader("💹 밸류에이션")
                val_rows = [
                    ('52주 고점',  f"{price_unit}{yr_h:,.0f}" if is_kr_sym else f"${yr_h:.2f}"),
                    ('52주 저점',  f"{price_unit}{yr_l:,.0f}" if is_kr_sym else f"${yr_l:.2f}"),
                    ('52주 위치',  f"{(price_now-yr_l)/(yr_h-yr_l)*100:.1f}%" if yr_h > yr_l else '-'),
                    ('연간 변동성', f"{vol_20:.1f}%"),
                ]
                yf_val = {}
                try:
                    t_yf = yf.Ticker(f"{sym8_clean}.KS" if is_kr_sym else sym8_clean)
                    yi2 = t_yf.info or {}
                    yf_val = {
                        'PER (TTM)':   yi2.get('trailingPE'),
                        'PER (선행)':  yi2.get('forwardPE'),
                        'PBR':         yi2.get('priceToBook'),
                        'ROE (%)':     round(yi2.get('returnOnEquity',0)*100,1) if yi2.get('returnOnEquity') else None,
                        '영업마진 (%)': round(yi2.get('operatingMargins',0)*100,1) if yi2.get('operatingMargins') else None,
                    }
                except: pass

                all_val = val_rows + [(k, f"{v:.1f}x" if 'PER' in k or 'PBR' in k else f"{v}%") for k, v in yf_val.items() if v]
                v_df = pd.DataFrame([{'지표': k, '값': v} for k, v in all_val])
                st.dataframe(v_df, use_container_width=True, hide_index=True,
                             height=36 + 35*len(v_df))

                if insid is not None and not insid.empty:
                    st.subheader("👤 내부자 거래")
                    st.dataframe(insid.head(8), use_container_width=True, hide_index=True)
                elif is_kr_sym:
                    st.info("한국 종목 내부자 거래는 제공하지 않습니다")

    elif not sym8:
        st.info("👆 종목코드를 입력하고 분석 버튼을 누르세요\n\n"
                "**US**: TSLA · AAPL · NVDA · MSFT · QCOM\n\n"
                "**KR**: 005930.KS (삼성전자) · 000660.KS (SK하이닉스)")


# ════════════════════════════════════════════════════════════════════
# 탭8: 포트폴리오 관리
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300)
def _fetch_price(sym: str, market: str):
    try:
        import FinanceDataReader as fdr
        code = sym.replace('.KS','').replace('.KQ','')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start)
        return float(df['Close'].iloc[-1]) if not df.empty else None
    except: return None

with tab8:
    st.header("💼 포트폴리오 관리")
    update_badge(PORTFOLIO_RESULT)

    with st.expander("➕ 종목 추가", expanded=False):
        fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([2,1,1,1,1,1])
        with fc1: p_sym  = st.text_input("티커",         key="p_sym",  placeholder="TSLA / 005930")
        with fc2: p_name = st.text_input("이름(선택)",   key="p_name", placeholder="Tesla")
        with fc3: p_mkt  = st.selectbox("시장",          ["US","KR"],  key="p_mkt")
        with fc4: p_qty  = st.number_input("수량",       min_value=0.0, step=1.0,  key="p_qty")
        with fc5: p_buy  = st.number_input("매수가",     min_value=0.0, step=0.01, key="p_buy", format="%.2f")
        with fc6: p_date = st.date_input("매수일", key="p_date")

        fc7, fc8, fc9 = st.columns([1,1,2])
        with fc7: p_stop   = st.number_input("손절%", value=7.0,  min_value=1.0, max_value=50.0, key="p_stop")
        with fc8: p_target = st.number_input("목표%", value=20.0, min_value=1.0, max_value=500.0, key="p_target")
        with fc9: p_note   = st.text_input("메모", key="p_note", placeholder="52주신고가+이평수렴")

        if st.button("추가", key="p_add"):
            if p_sym and p_buy > 0 and p_qty > 0:
                positions = _load_pf()
                positions.append({
                    'id':         f"{p_sym}_{p_date}_{len(positions)}",
                    'sym':        p_sym.upper().strip(),
                    'name':       p_name or p_sym.upper(),
                    'market':     p_mkt,
                    'qty':        float(p_qty),
                    'buy_price':  float(p_buy),
                    'buy_date':   str(p_date),
                    'stop_loss_pct':  float(p_stop),
                    'target_pct':     float(p_target),
                    'note':       p_note,
                })
                _save_pf(positions)
                st.cache_data.clear()
                st.success(f"✅ {p_sym.upper()} 추가 완료")
                st.rerun()
            else:
                st.error("티커·매수가·수량을 모두 입력하세요")

    positions = _load_pf()

    if not positions:
        st.info("👆 '종목 추가'에서 보유 종목을 입력하세요\n\n"
                "입력 후 매일 06:00 자동으로 현재가 조회 + 손절 경고를 텔레그램으로 전송합니다.")
    else:
        with st.spinner("현재가 조회 중..."):
            rows_pf = []
            for pos in positions:
                cur = _fetch_price(pos['sym'], pos.get('market','US'))
                buy = float(pos.get('buy_price', 0))
                qty = float(pos.get('qty', 0))
                pnl_pct = (cur / buy - 1) * 100 if cur and buy > 0 else None
                pnl_amt = (cur - buy) * qty      if cur and buy > 0 else None
                stop_px = buy * (1 - float(pos.get('stop_loss_pct', 7)) / 100)
                tgt_px  = buy * (1 + float(pos.get('target_pct', 20)) / 100)
                ccy     = '₩' if pos.get('market') == 'KR' else '$'

                rows_pf.append({
                    '시장':     pos.get('market','US'),
                    '종목명':   pos.get('name', pos['sym']),
                    '코드':     pos['sym'],
                    '수량':     qty,
                    '매수가':   f"{ccy}{buy:,.2f}",
                    '현재가':   f"{ccy}{cur:,.2f}" if cur else '조회실패',
                    '수익률':   pnl_pct,
                    'P&L':      pnl_amt,
                    '손절가':   f"{ccy}{stop_px:,.2f}",
                    '목표가':   f"{ccy}{tgt_px:,.2f}",
                    '매수일':   pos.get('buy_date',''),
                    '메모':     pos.get('note',''),
                    '_id':      pos.get('id',''),
                })

        df_pf = pd.DataFrame(rows_pf)

        valid_pf = [r for r in rows_pf if r['P&L'] is not None]
        if valid_pf:
            total_pnl = sum(r['P&L'] for r in valid_pf)
            total_inv = sum(
                float(pos.get('buy_price',0)) * float(pos.get('qty',0))
                for pos in positions
            )
            total_pnl_pct = total_pnl / total_inv * 100 if total_inv > 0 else 0
            n_profit = sum(1 for r in valid_pf if r['수익률'] and r['수익률'] >= 0)
            n_loss   = len(valid_pf) - n_profit
            n_warn   = sum(1 for r in valid_pf
                          if r['수익률'] and r['수익률'] <= -float(
                              next((p['stop_loss_pct'] for p in positions if p['sym']==r['코드']), 7)))

            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("총 손익금액",  f"{total_pnl:+,.0f}")
            m2.metric("수익률",       f"{total_pnl_pct:+.1f}%")
            m3.metric("수익 종목",    f"{n_profit}개")
            m4.metric("손실 종목",    f"{n_loss}개")
            m5.metric("⚠️ 손절 경고", f"{n_warn}개",
                      delta="즉시 확인" if n_warn > 0 else None,
                      delta_color="inverse")

        st.divider()

        def _color_pnl(v):
            if v is None: return ''
            try:
                f = float(v)
                if f >= 10:  return 'color:#ff2222;font-weight:bold'
                if f >= 0:   return 'color:#56d364'
                if f >= -7:  return 'color:#ffa657'
                return 'color:#ff4444;font-weight:bold'
            except: return ''

        def _color_pnl_amt(v):
            if v is None: return ''
            try:
                return 'color:#56d364' if float(v) >= 0 else 'color:#ff4444'
            except: return ''

        disp_pf = ['시장','종목명','코드','수량','매수가','현재가','수익률','P&L','손절가','목표가','매수일','메모']
        styled_pf = df_pf[disp_pf].style \
            .applymap(_color_pnl,     subset=['수익률']) \
            .applymap(_color_pnl_amt, subset=['P&L']) \
            .format({'수익률': lambda v: f"{v:+.1f}%" if v is not None else '-',
                     'P&L':    lambda v: f"{v:+,.0f}" if v is not None else '-',
                     '수량':    '{:.0f}'})

        st.dataframe(styled_pf, use_container_width=True, hide_index=True,
                     height=36 + 35 * len(df_pf))

        st.divider()
        col_del1, col_del2 = st.columns([3, 1])
        with col_del1:
            del_name = st.selectbox("종목 삭제",
                [f"{r['코드']} ({r['종목명']})" for r in rows_pf],
                key="del_pos")
        with col_del2:
            st.write("")
            if st.button("🗑️ 삭제", key="do_del"):
                del_sym = del_name.split(' ')[0]
                new_pos = [p for p in positions if p['sym'] != del_sym]
                _save_pf(new_pos)
                st.cache_data.clear()
                st.success(f"{del_sym} 삭제 완료")
                st.rerun()

        if valid_pf:
            st.divider()
            st.subheader("📊 종목별 수익률")
            chart_df = pd.DataFrame([
                {'종목': r['종목명'], '수익률(%)': r['수익률']}
                for r in valid_pf if r['수익률'] is not None
            ]).sort_values('수익률(%)', ascending=True)

            fig_pf = go.Figure(go.Bar(
                x=chart_df['수익률(%)'],
                y=chart_df['종목'],
                orientation='h',
                marker_color=[
                    'rgba(86,211,100,0.8)' if v >= 0 else 'rgba(247,129,102,0.8)'
                    for v in chart_df['수익률(%)']
                ],
            ))
            fig_pf.add_vline(x=0, line_color='rgba(110,118,129,0.5)')
            fig_pf.update_layout(
                height=max(200, 40 * len(chart_df)),
                paper_bgcolor='#0f1117', plot_bgcolor='#0f1117',
                font=dict(color='#8b949e', size=11),
                margin=dict(l=0, r=60, t=10, b=0),
                xaxis_title='수익률(%)',
            )
            fig_pf.update_xaxes(gridcolor='#21262d')
            fig_pf.update_yaxes(gridcolor='#21262d')
            st.plotly_chart(fig_pf, use_container_width=True)

        st.divider()
        if st.button("📲 지금 텔레그램으로 포트폴리오 전송", key="tg_now"):
            import subprocess, sys as _sys
            result = subprocess.run(
                [_sys.executable, 'portfolio_monitor.py'],
                capture_output=True, text=True,
                cwd=str(Path(__file__).parent),
            )
            if result.returncode == 0:
                st.success("✅ 텔레그램 전송 완료!")
            else:
                st.error(f"오류: {result.stderr[:200]}")


# ════════════════════════════════════════════════════════════════════
# 탭9: 페이퍼 트레이딩 — 포워드 트랙레코드 + 오류수정 루프
# ════════════════════════════════════════════════════════════════════
with tab9:
    st.header("📒 페이퍼 트레이딩 — 실전 신뢰도 누적")
    st.caption("신호가 나온다 ≠ 돈 번다. 매주 가상 진입을 기록하고 1·4·13주 뒤 실제 수익으로 백테스트와 대조합니다.")

    import json as _json
    _ledger_path = Path('results/paper_trades.json')
    _ledger = load_json(_ledger_path)

    if not _ledger or not _ledger.get('trades'):
        st.info("아직 기록이 없습니다 → 터미널에서 `python paper_trade.py log` 실행 (또는 weekly_run.py가 자동 기록)")
    else:
        _trades = _ledger['trades']
        _SIG_LABEL = {'sig_52w':'52주신고가','sig_vol':'거래량폭발','sig_ma5':'5주라이딩',
                      'sig_cup':'컵핸들','sig_maconv':'이평수렴','sig_rsimacd':'RSI/MACD'}
        _REF = {'sig_52w':{'4w':1.0,'13w':3.3},'sig_vol':{'4w':0.8,'13w':0.8},
                'sig_ma5':{'4w':0.4,'13w':2.2},'sig_cup':{'4w':0.5,'13w':2.4},
                'sig_maconv':{'4w':1.6,'13w':4.3},'sig_rsimacd':{'4w':0.9,'13w':2.7}}

        _n_total = len(_trades)
        _n_4w = sum(1 for t in _trades if '4w' in t.get('realized', {}))
        _n_13w = sum(1 for t in _trades if t.get('status') == 'closed')

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("누적 가상매매", f"{_n_total}건")
        c2.metric("4주 만기", f"{_n_4w}건")
        c3.metric("13주 종료", f"{_n_13w}건")
        _first = min((t['log_date'] for t in _trades), default='-')
        c4.metric("추적 시작일", _first)

        if _n_4w == 0:
            from datetime import datetime as _dt, timedelta as _td
            _ready = (_dt.strptime(_first, '%Y-%m-%d') + _td(days=28)).strftime('%Y-%m-%d')
            st.warning(f"⏳ 아직 익은 구간이 없습니다. 첫 4주 성적표 예정일: **{_ready}**  "
                       f"— 그때까지는 '신호가 쌓이는 중'이고, 그 후부터 실전 검증이 시작됩니다.")
        else:
            st.divider()
            for _h in ['4w', '13w']:
                _rows = []
                for _flag, _lab in _SIG_LABEL.items():
                    _rets = [t['realized'][_h]['ret'] for t in _trades
                             if t['flags'].get(_flag) and _h in t.get('realized', {})]
                    if not _rets:
                        continue
                    _n = len(_rets); _wr = sum(1 for r in _rets if r > 0)/_n*100
                    _live = sum(_rets)/_n; _ref = _REF[_flag][_h]; _gap = _live - _ref
                    _raw = max(0.0, min(1.3, _live/_ref)) if _ref > 0 else (1.0 if _live >= 0 else 0.5)
                    _mult = round((_n*_raw + 10*1.0)/(_n+10), 2)
                    _rows.append({'신호':_lab,'표본':_n,'실전승률':round(_wr,1),
                                  '실전EV%':round(_live,2),'백테EV%':_ref,
                                  '괴리%':round(_gap,2),'신뢰계수':_mult})
                if _rows:
                    st.subheader(f"{_h} 보유 · 신호별 실전 vs 백테스트")
                    _df = pd.DataFrame(_rows)
                    def _c_gap(v):
                        try: return 'color:#56d364' if float(v)>=0 else ('color:#ffa657' if float(v)>-1.5 else 'color:#f78166')
                        except: return ''
                    def _c_mult(v):
                        try:
                            f=float(v)
                            if f>=1.0: return 'color:#56d364;font-weight:bold'
                            if f>=0.85: return 'color:#ffa657'
                            return 'color:#f78166;font-weight:bold'
                        except: return ''
                    st.dataframe(
                        _df.style.applymap(_c_gap, subset=['괴리%']).applymap(_c_mult, subset=['신뢰계수'])
                            .format({'실전승률':'{:.1f}%','실전EV%':'{:+.2f}','백테EV%':'{:+.2f}',
                                     '괴리%':'{:+.2f}','신뢰계수':'{:.2f}'}),
                        use_container_width=True, hide_index=True)
            st.caption("신뢰계수 <1 = 실전이 백테스트에 못 미침 → 추천·사이징에서 비중 자동 축소(대응). "
                       "표본이 적으면 1.0으로 수축(섣부른 판단 방지).")

        st.divider()
        with st.expander("📋 개별 가상매매 기록 (최근 30건)", expanded=False):
            _recent = sorted(_trades, key=lambda t: t['log_date'], reverse=True)[:30]
            _rt = []
            for t in _recent:
                _r = t.get('realized', {})
                _rt.append({
                    '진입일': t['log_date'], '시장': t['market'], '종목': t['name'],
                    '진입가': t['entry_px'], '신호': ', '.join(t.get('signals', [])),
                    '4주%': _r.get('4w', {}).get('ret', None),
                    '13주%': _r.get('13w', {}).get('ret', None),
                    '상태': t['status'],
                })
            _rtd = pd.DataFrame(_rt)
            def _c_ret(v):
                try: return 'color:#56d364' if float(v)>=0 else 'color:#f78166'
                except: return ''
            st.dataframe(
                _rtd.style.applymap(_c_ret, subset=['4주%','13주%'])
                    .format({'4주%': lambda v: f'{v:+.1f}' if v is not None else '대기',
                             '13주%': lambda v: f'{v:+.1f}' if v is not None else '대기'}, na_rep='대기'),
                use_container_width=True, hide_index=True, height=420)


# ════════════════════════════════════════════════════════════════════
# 탭10: 프로젝트 종합 — 여정 · 목표 · 검증 로드맵
# ════════════════════════════════════════════════════════════════════
with tab10:
    # 페이퍼 트레이딩 진행 상황을 종합 장표에 실시간 반영
    _pl = load_json(Path('results/paper_trades.json'))
    _pt_total = len(_pl['trades']) if _pl and _pl.get('trades') else 0
    _pt_first = min((t['log_date'] for t in _pl['trades']), default='-') if _pt_total else '-'
    _pt_4w = sum(1 for t in (_pl['trades'] if _pl else []) if '4w' in t.get('realized', {})) if _pt_total else 0
    try:
        from datetime import datetime as _d2, timedelta as _t2
        _pt_due = (_d2.strptime(_pt_first, '%Y-%m-%d') + _t2(days=28)).strftime('%Y-%m-%d') if _pt_first != '-' else '-'
    except Exception:
        _pt_due = '-'

    st.markdown(f"""
<style>
.pj{{font-family:-apple-system,'Segoe UI','Malgun Gothic',sans-serif;color:#e8edf4;max-width:1100px}}
.pj h1{{font-size:26px;font-weight:700;letter-spacing:-.4px;margin:4px 0 6px;
  background:linear-gradient(120deg,#fff,#7fa8ff 60%,#d4af37);-webkit-background-clip:text;
  background-clip:text;-webkit-text-fill-color:transparent}}
.pj .goal{{font-size:16px;color:#c7d2e0;line-height:1.7;border-left:3px solid #d4af37;
  padding:8px 18px;margin:14px 0 26px;background:rgba(212,175,55,.06)}}
.pj h2{{font-size:16px;color:#d4af37;font-weight:600;margin:26px 0 12px;letter-spacing:.3px}}
.pj .tl{{display:flex;flex-direction:column;gap:0;margin:8px 0}}
.pj .step{{display:flex;gap:14px;padding:10px 0;border-bottom:1px solid #1a2230}}
.pj .step .dot{{flex:0 0 26px;height:26px;border-radius:50%;background:#16324a;border:1px solid #2d5a82;
  color:#7fb3ff;font-size:12px;display:flex;align-items:center;justify-content:center;font-weight:700}}
.pj .step .body{{flex:1}}
.pj .step .t{{font-size:14.5px;color:#e8edf4;font-weight:600}}
.pj .step .d{{font-size:13px;color:#8a99ad;margin-top:2px;line-height:1.5}}
.pj .grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:10px}}
.pj .card{{background:#111722;border:1px solid #1e2837;border-radius:10px;padding:16px 18px}}
.pj .card .ch{{font-size:14px;font-weight:600;margin-bottom:8px}}
.pj .badge{{display:inline-block;font-size:11px;padding:2px 9px;border-radius:11px;margin-left:6px;font-weight:600}}
.pj .b-on{{background:rgba(57,217,138,.15);color:#56d364}}
.pj .b-next{{background:rgba(255,180,84,.15);color:#ffb454}}
.pj .b-gap{{background:rgba(255,107,107,.13);color:#ff8a8a}}
.pj .b-cap{{background:rgba(127,160,255,.13);color:#9bb8ff}}
.pj ul{{margin:6px 0 0;padding-left:0;list-style:none}}
.pj li{{font-size:13px;color:#aab6c6;line-height:1.85;padding-left:18px;position:relative}}
.pj li::before{{content:'▹';position:absolute;left:0;color:#4f8cff}}
.pj .kpi{{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 4px}}
.pj .kpi .k{{background:#111722;border:1px solid #1e2837;border-radius:10px;padding:12px 18px;min-width:120px}}
.pj .kpi .k .n{{font-size:22px;font-weight:700;color:#fff}}
.pj .kpi .k .l{{font-size:11.5px;color:#8a99ad;margin-top:3px}}
</style>
<div class="pj">
<h1>🧭 프로젝트 종합 — 시그널 트레이딩 시스템</h1>
<div class="goal"><b style="color:#fff">핵심 목표</b> — "검증된 규칙으로 한·미 구조적 성장주의 추세·흑자전환을 포착하고,
<b style="color:#fff">실투자 전에 포워드 데이터로 검증</b>해 감이 아닌 숫자로 매매한다." 파는 건 대박 신호가 아니라, 한계까지 정직하게 까는 검증 프레임워크.</div>

<div class="kpi">
  <div class="k"><div class="n">9</div><div class="l">대시보드 모듈</div></div>
  <div class="k"><div class="n">2,600+</div><div class="l">백테스트 유니버스</div></div>
  <div class="k"><div class="n">{_pt_total}건</div><div class="l">페이퍼 트레이딩 누적</div></div>
  <div class="k"><div class="n">{_pt_due}</div><div class="l">첫 4주 성적표 예정</div></div>
</div>

<h2>① 개발 여정</h2>
<div class="tl">
  <div class="step"><div class="dot">1</div><div class="body"><div class="t">주봉 6신호 스크리너</div><div class="d">52주신고가·이평수렴·컵핸들·거래량폭발·RSI/MACD·5주라이딩 — 시스템의 뼈대</div></div></div>
  <div class="step"><div class="dot">2</div><div class="body"><div class="t">백테스트 엔진</div><div class="d">2021–2026, 2,600+종목. look-ahead 차단·실거래비용·생존편향 경고까지 내장</div></div></div>
  <div class="step"><div class="dot">3</div><div class="body"><div class="t">매크로 · CANSLIM · 흑자전환</div><div class="d">FRED 레짐→현금비중, 한국 CANSLIM(네이버 실적 파싱), 분기 흑자전환 포착</div></div></div>
  <div class="step"><div class="dot">4</div><div class="body"><div class="t">추천 포트 · 포트폴리오 추적</div><div class="d">Kelly 기반 사이징, 손절/목표가, 텔레그램 알림</div></div></div>
  <div class="step"><div class="dot">5</div><div class="body"><div class="t">CANSLIM 슬라이더화</div><div class="d">raw 수치 저장 → 웹에서 N·S·L·C·A·I 기준 실시간 조정 (왕도 가정 폐기)</div></div></div>
  <div class="step"><div class="dot">6</div><div class="body"><div class="t">백테스트 검증 v2.1</div><div class="d">매각 실사 피드백 대응 — 아웃오브샘플(OOS)·레짐 분리·소형주 비용 차등·Sortino/PF</div></div></div>
  <div class="step"><div class="dot">7</div><div class="body"><div class="t">포워드 페이퍼 트레이딩 + 오류수정 루프</div><div class="d">신호 가상진입 기록→실현수익 대조→신뢰계수로 비중 자동축소. {_pt_first} 시작, {_pt_4w}건 만기</div></div></div>
</div>

<h2>② 현재 커버리지 — 13인 대가 종합</h2>
<div class="grid">
  <div class="card"><div class="ch" style="color:#56d364">반영됨 <span class="badge b-on">강점</span></div>
    <ul><li><b>추세·모멘텀</b> — 오닐·리버모어·박병창·이선엽 (스크리너 엔진)</li>
    <li><b>매크로·사이클</b> — 드러켄밀러·막스·김일구·오종태 (레짐·현금비중)</li></ul></div>
  <div class="card"><div class="ch" style="color:#ff8a8a">공백 <span class="badge b-gap">미완</span></div>
    <ul><li><b>가치·해자</b> — 버핏·멍거: 내재가치 미산출</li>
    <li><b>가치변화 트리거</b> — 박세익(체슬리): "왜 지금" 부재</li>
    <li><b>태도·오류수정</b> — 라쿤 홍진채: 페이퍼트레이딩으로 채우는 중</li></ul></div>
</div>

<h2>③ 앞으로 — 피드백 · 검증 로드맵</h2>
<div class="grid">
  <div class="card"><div class="ch">진행 중 <span class="badge b-on">NOW</span></div>
    <ul><li>포워드 페이퍼 트레이딩 누적 — 첫 성적표 <b style="color:#ffb454">{_pt_due}</b></li>
    <li>매주 weekly_run 자동 기록 → 실전 신뢰계수 갱신</li></ul></div>
  <div class="card"><div class="ch">다음 단계 <span class="badge b-next">NEXT</span></div>
    <ul><li>신뢰계수 → 추천 비중 자동 연동 (대응 루프 완성)</li>
    <li>OOS·레짐 실제 백테스트 실행해 수치 확정</li></ul></div>
  <div class="card"><div class="ch">빠진 축 채우기 <span class="badge b-gap">GAP</span></div>
    <ul><li>가치 모듈 — PER/PBR/ROE 기반 내재가치·해자 점수</li>
    <li>가치변화 트리거 — 공시·실적 서프라이즈·목표가 상향</li></ul></div>
  <div class="card"><div class="ch">자본 필요 <span class="badge b-cap">CAPEX</span></div>
    <ul><li>데이터 안정화 — 유료 피드(스크래핑 429 의존 탈피)</li>
    <li>생존편향 보정 — 상장폐지 종목 포함 유니버스</li></ul></div>
</div>

<h2>④ 실투자 게이트 (1천만원)</h2>
<div class="card" style="margin-top:8px">
  <ul>
  <li><b>1단계 — 페이퍼 트레이딩</b> (지금~3개월): 돈 0원, 트랙레코드 축적</li>
  <li><b>2단계 — 극소액 실전</b>: 포워드 EV가 비용 차감 후 양(+)일 때만, 잃어도 수업료인 금액으로 손절 규율 검증</li>
  <li><b>3단계 — 비중 확대</b>: 1·2단계 통과 시에만. "주식보다 먼저 사야 할 건 3개월치 성적표"</li>
  </ul>
</div>
</div>
""", unsafe_allow_html=True)


# ── 사이드바 하단 ─────────────────────────────────────────────────────
st.sidebar.divider()
_KEY_FILE = Path('data/.finnhub_key')
if 'fh_key' not in st.session_state:
    try:
        if _KEY_FILE.exists():
            st.session_state['fh_key'] = _KEY_FILE.read_text().strip()
        else:
            st.session_state['fh_key'] = ''
    except:
        st.session_state['fh_key'] = ''

st.sidebar.subheader("🔑 Finnhub API 키")
fh_input = st.sidebar.text_input("키 입력 (선택)", type="password",
    value=st.session_state.get('fh_key',''),
    placeholder="finnhub.io 무료 발급",
    key="fh_key_input")
if fh_input and fh_input != st.session_state.get('fh_key',''):
    st.session_state['fh_key'] = fh_input
    try:
        _KEY_FILE.parent.mkdir(exist_ok=True)
        _KEY_FILE.write_text(fh_input)
    except: pass
st.sidebar.caption("입력 시 종목 분석 탭에서\nPER·EPS·내부자거래 추가 표시")

st.sidebar.divider()
if st.sidebar.button("🔄 전체 새로고침"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption("perf_run.py → 월간성과\nweekly_run.py → 주봉스크리너\ncanslim_run.py → CANSLIM\nturnaround_run.py → 흑자전환")
