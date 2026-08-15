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
/* 본문 14px — 13px 컴팩트는 표는 좋았지만 설명 글이 안 읽혔다(2026-08-12).
   표·탭은 촘촘하게 유지하고 '읽는 텍스트'만 키운다. */
html, body, [class*="css"] { font-size: 14px !important; }
.stDataFrame, .stDataFrame td, .stDataFrame th { font-size: 12.5px !important; }
.stTabs [data-baseweb="tab"] { font-size: 14px !important; font-weight: 600; padding: 7px 15px; }
/* 캡션이 화면의 절반이다 — 회색을 한 단계 진하게(#52514e) + 행간을 벌려 읽히게 */
[data-testid="stCaptionContainer"] p { font-size: 12.5px !important; line-height: 1.65 !important;
  color: #52514e !important; }
[data-testid="stMarkdownContainer"] p, [data-testid="stMarkdownContainer"] li {
  line-height: 1.65 !important; }
section[data-testid="stSidebar"] * { font-size: 12px !important; }
[data-testid="metric-container"] [data-testid="stMetricValue"] { font-size: 18px !important; font-weight: 700; }
[data-testid="metric-container"] label { font-size: 11.5px !important; }
h1 { font-size: 21px !important; margin-bottom: 8px !important; }
h2 { font-size: 17px !important; margin-bottom: 6px !important; }
h3 { font-size: 15px !important; margin-bottom: 5px !important; }
/* 섹션 제목 위에 숨 쉴 자리 — 앞 블록에 붙어 있으면 어디서 끊기는지 안 보인다 */
h2, h3 { margin-top: 1.6rem !important; }

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
hr { margin: 1.7rem 0 !important; border-color: #e8e8e4 !important; }
[data-testid="stMetric"] { padding: 0 !important; }
div[data-testid="stSlider"] { padding-top: 0 !important; padding-bottom: 0.1rem !important; }
[data-testid="stCaptionContainer"] p { margin-bottom: 0.1rem !important; }
[data-testid="stRadio"] > label { margin-bottom: 0 !important; }
[data-testid="stExpander"] details { padding: 0 !important; }
/* 테두리 카드 안쪽 여백 — 글이 선에 닿아 있으면 답답하다 */
[data-testid="stVerticalBlockBorderWrapper"] > div > [data-testid="stVerticalBlock"] {
  padding: 0.4rem 0.6rem !important; }
/* 표는 위아래로 조금 띄운다 */
[data-testid="stDataFrame"] { margin: 0.35rem 0 0.6rem !important; }

/* ── 모바일 반응형 (≤640px) ───────────────────────────────────
   Streamlit은 좁은 화면에서 st.columns를 자동으로 쌓지 않아 카드/표가
   찌그러진다. 좁은 화면에선 컬럼을 세로로 쌓고 여백·탭을 조정. */
@media (max-width: 640px) {
  /* 컬럼 행을 줄바꿈 + 각 컬럼 전체폭으로 → 세로 스택 */
  [data-testid="stHorizontalBlock"] { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"] > div { flex: 1 1 100% !important; min-width: 100% !important; }
  /* 본문 좌우 여백 축소해 화면폭 최대 활용 */
  .block-container { padding-left: 0.6rem !important; padding-right: 0.6rem !important; padding-top: 2.5rem !important; }
  /* 탭 라벨 촘촘하게 (가로 스크롤은 유지) */
  .stTabs [data-baseweb="tab"] { padding: 5px 9px !important; font-size: 12px !important; }
  /* 메트릭 값/표 폰트 약간 축소 */
  [data-testid="stMetricValue"] { font-size: 16px !important; }
  .stDataFrame, .stDataFrame td, .stDataFrame th { font-size: 11px !important; }
  /* 넓은 정적표(st.table)가 넘칠 때 가로 스크롤 허용 */
  [data-testid="stTable"] { overflow-x: auto !important; display: block !important; }
}
</style>
""", unsafe_allow_html=True)

# Streamlit Cloud 컨테이너의 파일시스템은 휘발성이다(슬립·재배포 시 초기화). 여기에
# 파일로 저장하는 기능 — 보유종목·API키·구루 채널 — 은 "저장됐다"고 표시된 뒤 조용히
# 사라진다. 조용히 실패하는 대신 사실대로 알리려고 환경을 구분한다.
IS_CLOUD = str(Path(__file__).resolve()).replace('\\', '/').startswith('/mount/src')

PERF_JSON        = Path('results/perf_latest.json')
SCREENER_JSON    = Path('results/screener_latest.json')
CANSLIM_JSON     = Path('results/canslim_latest.json')
# TURNAROUND_JSON 제거(2026-08-13): 정의만 있고 쓰는 화면이 없었다. 파일도 06-01에
# 멈춰 있어, 남겨두면 '살아 있는 데이터'로 오인돼 감시 목록만 오염시킨다.
PORTFOLIO_FILE   = Path('data/portfolio.json')
PORTFOLIO_RESULT = Path('results/portfolio_latest.json')
MDD_JSON         = Path('results/mdd.json')


@st.cache_data(ttl=1800)
def _mdd_map() -> dict:
    """sym → 현재 고점대비 낙폭%(cur_dd) · 1y/역대 MDD. mdd.json(주 1회 갱신) 기반."""
    d = load_json(MDD_JSON) or {}
    return {s['sym']: s for s in d.get('stocks', [])}


@st.cache_data(ttl=1800)
def _attract_map(market: str = "전체") -> dict:
    """sym → 매력도(위닝점수 0~100 · S/A/B/C 등급). winning_score(백테스트 샤프 가중) 기반 —
    주봉 신호 유니버스에만 계산돼 있어 커버리지 밖 종목은 '-'."""
    try:
        import winning_score as _ws
        return {r['sym']: {'score': r['score'], 'grade': r['grade']} for r in _ws.rank_all(market)}
    except Exception:
        return {}


def _mdd_col(sym: str, mmap: dict):
    r = mmap.get(sym)
    return f"{r['cur_dd']:+.1f}%" if r and r.get('cur_dd') is not None else '-'


@st.cache_data(ttl=1800)
def _traj_map() -> dict:
    """sym → 펀더멘털 궤적(판정·ΔROE·궤적점수). value_kr.json 기반 — KR만."""
    d = load_json(Path('results/value_kr.json')) or {}
    return {s['sym']: s['traj'] for s in d.get('stocks', []) if s.get('traj')}


def _income_sankey(row, unit_div, unit, seg=None):
    """손익계산서 1개 기간 → App Economy 스타일 Sankey.
    매출 → 매출총이익(초록)/매출원가(빨강) → 영업이익/판관비 → 순이익/세금·기타.
    seg(부문 dict) 있으면 왼쪽에 사업부문 → 매출 흐름 추가(KR)."""
    rv = row.get('revenue')
    gross = row.get('gross')
    op = row.get('op_income')
    ni = row.get('net_income')
    if not rv or gross is None or op is None:
        return None
    cogs = rv - gross
    sga = row.get('sga')
    sga = sga if (sga is not None) else max(gross - op, 0)
    other = max(op - ni, 0) if ni is not None else None

    labels, colors, srcs, tgts, vals, lcolors = [], [], [], [], [], []
    def _node(lbl, color):
        labels.append(lbl); colors.append(color); return len(labels) - 1
    def _link(s, t, v, c):
        if v and v > 0:
            srcs.append(s); tgts.append(t); vals.append(v / unit_div); lcolors.append(c)

    GRN, RED, GRY = '#2f9e44', '#e04131', '#8a8a8a'
    GRNL, REDL = 'rgba(47,158,68,0.28)', 'rgba(224,65,49,0.22)'

    n_rev = _node(f"매출 {rv/unit_div:,.1f}{unit}", GRY)
    # 왼쪽 사업부문 → 매출 (KR seg)
    if seg and seg.get('segments'):
        _ss = [s for s in seg['segments'] if s.get('revenue')]
        _tot = sum(s['revenue'] for s in _ss) or 1
        for s in _ss[:6]:
            ni_seg = _node(f"{s['name']} {s['revenue']/unit_div:,.0f}{unit}", GRY)
            _link(ni_seg, n_rev, s['revenue'] * (rv / _tot), 'rgba(138,138,138,0.22)')
    n_gross = _node(f"매출총이익 {gross/unit_div:,.1f}{unit}", GRN)
    n_cogs  = _node(f"매출원가 {cogs/unit_div:,.1f}{unit}", RED)
    n_op    = _node(f"영업이익 {op/unit_div:,.1f}{unit}", GRN)
    n_sga   = _node(f"판관비 {sga/unit_div:,.1f}{unit}", RED)
    n_net   = _node(f"순이익 {ni/unit_div:,.1f}{unit}" if ni is not None else "순이익", GRN)
    n_oth   = _node(f"세금·기타 {other/unit_div:,.1f}{unit}", RED) if other else None

    _link(n_rev, n_gross, gross, GRNL)
    _link(n_rev, n_cogs, cogs, REDL)
    _link(n_gross, n_op, op, GRNL)
    _link(n_gross, n_sga, sga, REDL)
    if ni is not None:
        _link(n_op, n_net, ni, GRNL)
    if n_oth is not None:
        _link(n_op, n_oth, other, REDL)

    fig = go.Figure(go.Sankey(
        arrangement='snap',
        node=dict(label=labels, color=colors, pad=18, thickness=16,
                  line=dict(width=0)),
        link=dict(source=srcs, target=tgts, value=vals, color=lcolors)))
    fig.update_layout(height=380, paper_bgcolor='rgba(0,0,0,0)',
                      font=dict(color='#c9d1d9', size=12), margin=dict(l=0, r=0, t=6, b=6))
    return fig


def _traj_col(sym: str, tmap: dict):
    """'📈 개선 5/7' 축약 — 다른 탭 표에 한 열로 얹는 용도."""
    t = tmap.get(sym)
    if not t:
        return '-'
    lab = {'improving': '📈', 'deteriorating': '📉', 'stable': '➖'}.get(t.get('verdict'), '')
    return f"{lab} {t.get('traj_score')}/7"


def _attract_col(sym: str, amap: dict):
    r = amap.get(sym)
    return f"{r['grade']} {r['score']:.0f}" if r and r.get('score') is not None else '-'

SIG_COLS_PAST = ['past_sig_52w','past_sig_vol','past_sig_ma5','past_sig_cup','past_sig_maconv','past_sig_rsimacd']
SIG_COLS_NOW  = ['now_sig_52w', 'now_sig_vol', 'now_sig_ma5', 'now_sig_cup', 'now_sig_maconv', 'now_sig_rsimacd']
SIG_LABELS    = ['52주신고가','거래량폭발','5일라이딩','컵위드핸들','이평수렴','RSI/MACD']


# ── 공통 헬퍼 ────────────────────────────────────────────────────────
def _dfh(n, cap=620):
    """dataframe 높이 — 행 27px에 딱 맞게(빈 필러 행 방지), 길면 내부 스크롤. row_height=25과 세트."""
    return int(min(25 * n + 36, cap))




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

@st.cache_data(ttl=600, show_spinner=False)
def _data_status():
    """산출물별 실제 데이터 날짜·주기·상태 (data_freshness 레지스트리 단일 원천)."""
    try:
        import data_freshness
        return data_freshness.statuses()
    except Exception:
        return []


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

@st.cache_data(ttl=3600)
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


def fetch_fred(series_id: str, limit: int = 24):
    try:
        return _fetch_fred_cached(series_id, limit)
    except Exception:
        return []

@st.cache_data(ttl=3600)
def _fetch_spx_yoy_cached():
    url = 'https://stooq.com/q/d/l/?s=^spx&i=m'
    df = pd.read_csv(url, parse_dates=['Date'])
    df = df.sort_values('Date').tail(15)
    if len(df) < 13:
        raise RuntimeError('short')
    latest = float(df['Close'].iloc[-1])
    yr_ago = float(df['Close'].iloc[-13])
    return round((latest / yr_ago - 1) * 100, 2)


def fetch_spx_yoy():
    try:
        return _fetch_spx_yoy_cached()
    except Exception:
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


# ── 탭 구성 ──────────────────────────────────────────────────────────
# ── 📸 온보딩 포토카드 — 처음 온 사람이 탭을 누르기 전에 먼저 보는 30초 설명 ──
#    세션 첫 렌더에서만 펼쳐두고, 이후 상호작용부터는 접힌다(매일 쓰는 사람 방해 금지).
_first_visit = 'seen_onboard' not in st.session_state
st.session_state['seen_onboard'] = True
_ONBOARD_TEXT = """
**이 도구는** 공식 공시(DART·SEC EDGAR)와 시장 가격을 매일 자동으로 모아
"뭘 살까 · 언제 살까 · 얼마나 살까"를 숫자로 계산해 주는 개인 리서치 도구입니다.

**생각하는 방식 — 3층 프레임**
🟡 가치(뭘 살까: 재무 3표·ROE·흑자전환) × ⚖️ 멀티플(비싼가: PER·PBR·PSR) × 🔵 가격(언제 살까: 차트·주봉 신호·계절성)

**탭 4개**
- 💼 **포트폴리오** — 보유 종목의 수익률·비중·손절선 자동 추적 + **📒 성적표**(지난 신호가 실제로 맞았는지 전부 공개)
- 🔎 **종목 발굴** — 조건에 맞는 종목을 기계가 골라 목록으로. 🚀주도주·🏆CANSLIM이 검증된 규칙, 나머지는 탐색용
- 🔍 **종목 분석** — 종목코드(US `NVDA` / KR `005930`) 입력 → 차트·공식 재무 3표·멀티플·목표주가·AI 사업요약
- 🌍 **매크로** — 지금이 사이클의 어느 국면인지(우라가미 4계절·코스톨라니 달걀·막스 시계추)와 권고 현금비중

**처음이라면 이 순서**
① 🌍 매크로에서 지금 국면과 권고 현금비중 확인 → ② 🔎 종목 발굴에서 후보 3~5개(🚀주도주부터) →
③ 🔍 종목 분석으로 재무가 실제로 좋아지는지 확인 → ④ 💼 포트폴리오에 손절가와 함께 기록

⚠️ **의사결정 보조 도구**입니다. 점수·신호는 확률이지 보장이 아니며 매수 권유가 아닙니다.
숫자에 `-`가 보이는 칸은 오류가 아니라 **그 종목에 해당 데이터가 없다는 뜻**입니다.
"""
with st.expander("📸 처음이신가요? — 30초 사용법 카드 (탭 안내 · 시작 순서 · 전체 사용설명서)",
                 expanded=_first_visit):
    _card = Path('docs/onboarding_card.svg')
    if _card.exists():
        _svg = _card.read_text(encoding='utf-8')
        # st.image(<img> 렌더)는 카드의 CSS가 앱 전역에 새지 않도록 격리해 준다.
        try:
            st.image(_svg, use_container_width=True)
        except Exception:
            st.html(_svg)
        st.download_button("🖼️ 카드 이미지 저장 (SVG)", _svg,
                           file_name="dashboard_사용법_카드.svg", mime="image/svg+xml",
                           key="dl_onboard")
        # 카드는 1160px 고정 레이아웃이라 폰(375px)에서는 331px로 줄어 글자가 안 읽힌다.
        # 이 앱의 주 사용처가 폰이므로, 같은 내용을 흐르는 텍스트로도 제공한다.
        with st.expander("📱 폰에서는 글자가 작습니다 — 같은 내용 텍스트로 보기"):
            st.markdown(_ONBOARD_TEXT)
    else:
        st.markdown(_ONBOARD_TEXT)

    # 구 '프로젝트 종합' 탭에 있던 전체 사용설명서 — 탭을 없애면서 여기로 이관
    with st.expander("📖 전체 사용설명서 — 개념 사전 · 데이터 신뢰등급 · 자주 묻는 것"):
        try:
            st.markdown(Path('GUIDE.md').read_text(encoding='utf-8'))
        except Exception:
            st.caption("GUIDE.md 없음 — 저장소에서 확인.")

# 탭 순서 = 의사결정 순서. 내 돈이 어떻게 되고 있나(포트폴리오) → 뭘 살까(발굴) →
# 이게 맞나(분석) → 지금 사도 되나(매크로). 구루 인사이트는 2026-08-11 페이지에서 제거
# (텔레그램 다이제스트는 guru-digest·guru-roundup 워크플로가 계속 발송한다),
# 프로젝트 종합도 같은 날 제거하고 사용설명서만 상단 온보딩으로 이관했다.
tab_pf, tab_screen, tab7, tab4 = st.tabs([
    "💼 포트폴리오", "🔎 종목 발굴", "🔍 종목 분석", "🌍 매크로"])

# 포트폴리오 = 실적 공시판. 현재 보유와 '지난 추천이 맞았나'(성적표)를 한 탭에 둔다.
with tab_pf:
    _pf_main, t_track = st.tabs(["💼 보유 · 추적", "📒 성적표 — 신호가 실제로 맞았나"])

# 종목 발굴 — 발굴·분석·추천을 한 탭에 서브탭으로 통합
# 순서 주의: 서브탭 핸들(t_gain…)은 아래 6개 블록이 전부 의존하므로 **무조건 먼저** 만든다.
# 매크로 스트립처럼 실패할 수 있는 계산을 먼저 두면, 그게 죽는 순간 핸들이 미정의가 되어
# 서브탭 6개가 통째로 NameError로 날아간다. 스트립은 자리(container)만 잡아두고 뒤에서 채운다.
_MDDM, _ATTM = {}, {}

with tab_screen:                           # 데이터를 건드리지 않는 순수 레이아웃 → 가드 불필요
    _GMKT = st.radio("시장", ["전체", "KR", "US"], horizontal=True, key="screen_mkt")
    _macro_strip = st.container()          # 매크로 요약이 들어갈 자리
    # 서브탭 순서 = 신뢰도 순서. 검증된 규칙(주도주·CANSLIM)을 앞에, 참고용 탐색을 뒤에.
    # 성적표는 2026-08-11 포트폴리오 탭으로 이관했다(실적 공시는 한 곳에서).
    # 2026-08-12 통폐합: ⚡타이밍 발굴 서브탭 제거.
    #   · 계절성·고점대비 낙폭 → 🔥상승 상위의 필터로 흡수(같은 데이터를 두 화면에서 보던 중복)
    #   · 🧮 사이징 계산기 → 💼포트폴리오로 이동(발굴이 아니라 집행 단계의 도구다)
    st.caption("🚀주도주·🏆CANSLIM = 백테스트로 검증된 규칙 · 🔥상승상위·💎가치 = 후보 탐색용 — "
               "시장 필터는 위 하나로 전 서브탭 공통 · 📒성적표와 🧮사이징 계산기는 💼포트폴리오 탭에 있습니다")
    t_lead, tab3, t_gain, t_value = st.tabs([
        "🚀 주도주", "🏆 CANSLIM", "🔥 상승 상위", "💎 가치 발굴 (KR)"])

# 서브탭 공통 조회맵 — 실패해도 빈 맵으로 진행(표의 부가 열만 '-'가 된다)
try:
    _MDDM = _mdd_map()            # sym → 고점대비 낙폭
except Exception:
    _MDDM = {}
try:
    _ATTM = _attract_map(_GMKT)   # sym → 매력도(위닝점수·등급)
except Exception:
    _ATTM = {}

# ── 매크로 요약 스트립 (구 '오늘의 종합' 카드 이관) ──
with _macro_strip, guard('매크로 요약'):
    _s_can_h = load_json(CANSLIM_JSON) or {}
    try:
        _fed_h = fetch_fred('FEDFUNDS', 1); _fed_r = _fed_h[-1][1] if _fed_h else None
        _m2_h = fetch_fred('M2SL', 14)
        _m2y = round((_m2_h[-1][1] / _m2_h[-13][1] - 1) * 100, 1) if len(_m2_h) >= 13 else None
        _msig, _cmn, _cmx, _, _ = compute_macro_signal(_fed_r, _m2y, fetch_spx_yoy())
    except Exception:
        _msig, _cmn, _cmx = "—", 25, 40
    _hm1, _hm2, _hm4 = st.columns(3)
    _hm1.metric("시장 방향", _s_can_h.get('market_dir', '—'))
    _hm2.metric("매크로 신호", _msig)
    _hm4.metric("권고 현금", f"{_cmn}~{_cmx}%", help="매크로 위험도 기반 현금 비중 권고 · 상세는 🌍 매크로 탭")



# ════════════════════════════════════════════════════════════════════
# 종목 발굴 서브탭 콘텐츠: 주도주(t_lead) · 계절성(t_seas) · MDD 바닥(t_mdd)
# ════════════════════════════════════════════════════════════════════

# ── 🔥 상승 상위 (기간 상승률 + 주봉 신호 + 실적증감 + 계절성 + 낙폭 필터) ──
with t_gain, guard('상승 상위'):
    st.caption("기간별 상승 상위 + 주봉 신호 · 매출/영업익 증감 · 향후 2개월 계절성. CANSLIM 점수는 🏆 서브탭에서 슬라이더로 직접 조정해 보세요.")
    _retj = load_json(Path('results/returns.json'))
    _perf = load_json(PERF_JSON) or {}
    if not _retj or not _retj.get('stocks'):
        st.error("기간 수익률 데이터 없음 → `python screen_precompute.py` 실행 후 새로고침")
    else:
        _PERIODS = {'1주': ('perf', 'ret_1w'), '1개월': ('ret', 'ret_1m'), '3개월': ('ret', 'ret_3m'),
                    '6개월': ('ret', 'ret_6m'), '1년': ('ret', 'ret_12m'), 'YTD': ('ret', 'ret_ytd')}
        _gmkt = _GMKT
        _gc1, _gc2, _gc3, _gc4 = st.columns([1.2, 1.2, 1, 1])
        _gper = _gc1.selectbox("상승률 기간", list(_PERIODS.keys()), index=1, key="gain_per")
        _gsort = _gc2.selectbox("정렬", ["상승률", "위닝점수"], key="gain_sort")
        _gsig = _gc3.checkbox("신호 있는 종목만", value=False, key="gain_sigonly")
        _gn = _gc4.slider("표시 종목수", 10, 60, 30, key="gain_n")
        # ⚡타이밍 발굴에서 흡수한 두 필터 — 같은 데이터를 별도 화면으로 두던 중복 제거
        with st.expander("⚡ 타이밍 필터 — 계절성 승률 · 고점대비 낙폭 (구 '타이밍 발굴')"):
            _tf1, _tf2 = st.columns(2)
            _gwr = _tf1.slider("당월 계절성 최소 승률 %  (0 = 끄기)", 0, 90, 0, 5, key="gain_seaswr",
                               help="이번 달에 과거 몇 %의 확률로 올랐는지. 표본 3년 미만은 자동 제외.")
            _gdd = _tf2.slider("고점대비 낙폭 범위 %", -90, 0, (-90, 0), key="gain_ddrange",
                               help="바닥 탐색용. 예: -60~-25 로 좁히면 크게 조정받은 종목만 남는다.")
        _src, _retkey = _PERIODS[_gper]

        # 위닝 셋업 스코어 흡수 (점수/등급) — JSON 기반이라 가벼움
        _winmap = {}
        try:
            import winning_score as _ws
            for _wr in _ws.rank_all(_gmkt):
                _winmap[_wr['sym']] = {'score': _wr['score'], 'grade': _wr['grade']}
        except Exception:
            pass

        # perf 맵: 1주 수익률 + 현재 신호
        _SIGL = [('now_sig_52w', '52주신고가'), ('now_sig_vol', '거래량'), ('now_sig_maconv', '이평수렴'),
                 ('now_sig_cup', '컵핸들'), ('now_sig_ma5', '5주라이딩'), ('now_sig_rsimacd', 'RSI/MACD')]
        _perfmap = {}
        for s in _perf.get('stocks', []):
            sigs = [lab for k, lab in _SIGL if s.get(k)]
            _perfmap[s['sym']] = {'ret_1w': s.get('ret_1w'), 'sigs': sigs, 'nsig': len(sigs)}

        # CANSLIM 점수 + 실적증감
        _canj = load_json(CANSLIM_JSON) or {}
        _mok = _canj.get('market_ok', True)
        _canmap = {}
        for s in _canj.get('stocks', []):
            n = s.get('n_dist_pct'); rs = s.get('rs_pct', 0)
            cg = s.get('c_growth_pct'); a1 = s.get('a_growth_y1'); ii = s.get('i_inst_pct')
            vol = s.get('s_vol_ratio'); bd = s.get('s_body_pct'); bull = s.get('s_bull')
            score = sum([bool(_mok), (n is not None and n >= -5), rs >= 70,
                         (vol is not None and vol >= 1.5 and bd is not None and bd >= 40 and bool(bull)),
                         (cg == '흑자전환' or (isinstance(cg, (int, float)) and cg >= 20)),
                         (isinstance(a1, (int, float)) and a1 >= 20),
                         (isinstance(ii, (int, float)) and ii > 0)])
            _canmap[s['sym']] = {'score': score, 'rev': s.get('rev_growth'), 'op': s.get('op_growth')}

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

        _retc = f'{_gper}상승'
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
            _dd_v = (_MDDM.get(s['sym']) or {}).get('cur_dd')
            if (_gdd[0], _gdd[1]) != (-90, 0):
                if _dd_v is None or not (_gdd[0] <= _dd_v <= _gdd[1]):
                    continue
            cm = _canmap.get(s['sym'], {})
            wm = _winmap.get(s['sym'], {})
            _ws_v = wm.get('score')
            _grows.append({
                '시장': s['market'], '종목': s['name'], '코드': s['sym'],
                '시총': fmt_cap(s.get('marcap'), s['market']),
                '등급': wm.get('grade', '-'),
                '위닝점수': _ws_v if _ws_v is not None else None,   # 정렬용 원값
                '신호': ', '.join(pm.get('sigs', [])[:3]) or '-',
                # CANSLIM 점수 열은 2026-08-12 제거 — 🏆CANSLIM 서브탭과 같은 판정을 두 곳에서
                # 다르게 보여주던 중복. 실적 증감(매출·영업익)만 남긴다.
                '매출%': f"{cm['rev']:+.0f}" if isinstance(cm.get('rev'), (int, float)) else '-',
                '영업익%': f"{cm['op']:+.0f}" if isinstance(cm.get('op'), (int, float)) else '-',
                _retc: ret,
                '향후2M계절성': _seasmap.get(s['sym']),
                '고점대비%': _mdd_col(s['sym'], _MDDM),
            })
        if _gsort == "위닝점수":
            _grows.sort(key=lambda r: -(r['위닝점수'] if r['위닝점수'] is not None else -999))
        else:
            _grows.sort(key=lambda r: -(r[_retc] if r[_retc] is not None else -999))
        _grows = _grows[:_gn]
        for r in _grows:                                 # 표시용 변환 (None → '-')
            r['위닝점수'] = f"{r['위닝점수']:.1f}" if r['위닝점수'] is not None else '-'
            r['향후2M계절성'] = f"{r['향후2M계절성']:+.1f}%" if r['향후2M계절성'] is not None else '-'

        _slab = "위닝점수순" if _gsort == "위닝점수" else f"{_gper}상승순"
        st.subheader(f"🔥 {_gper} 상승 상위 — {len(_grows)}개 · {_slab} ({_cmo}·{_nmo}월 계절성 동반)")
        st.caption(data_stamp('results/returns.json', '상승률 기준일'))
        _gdf = pd.DataFrame(_grows)
        def _cg2(v):
            try: return 'color:#16a34a;font-weight:bold' if float(str(v).replace('%','').replace('+','')) >= 0 else 'color:#dc2626'
            except: return ''
        def _cg_grade(v):
            return {'S': 'background-color:#1a472a;color:white;font-weight:bold',
                    'A': 'background-color:#2d6a4f;color:white',
                    'B': 'color:#f0c040', 'C': 'color:#888'}.get(str(v), '')
        def _cg_score(v):
            try:
                f = float(v)
                if f >= 80: return 'color:#56d364;font-weight:bold'
                if f >= 65: return 'color:#7ee787'
                if f >= 50: return 'color:#f0c040'
            except: pass
            return 'color:#888'
        _gsub = [c for c in [_retc, '향후2M계절성'] if c in _gdf.columns]
        st.dataframe(
            _gdf.style.map(_cg2, subset=_gsub)
                .map(_cg_grade, subset=['등급']).map(_cg_score, subset=['위닝점수'])
                .format({_retc: '{:+.1f}%'}, na_rep='-'),
            use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_gdf)))
        _ncov = sum(1 for r in _grows if r['등급'] != '-')
        st.caption(f"ℹ️ 위닝점수·신호·CANSLIM은 **주봉 신호 유니버스(337종목)**에만 계산돼 있어 "
                   f"급등 소형주는 '-'가 많음 (현재 표시 {len(_grows)}개 중 {_ncov}개 커버). "
                   "커버리지 확대(전 종목 스코어링)는 로드맵 항목.")
        st.caption("위닝점수=백테스트 샤프 가중 셋업 점수(S≥80·A≥65·B≥50). 신호=주봉(현재). "
                   "CANSLIM·매출/영업익은 KR 한정. 계절성·1주는 perf 기준. "
                   "⚠️ 상승률 상위 = '이미 오른' 종목, 점수 = '셋업의 질'(미래 보장 아님) — 추격 주의, 손익비·가드레일 확인.")


# ── 주도주 (섹터/전체 상대강도) ──
with t_lead, guard('주도주'):
    # 2026-08-15: KR 규칙(KR-P1) 추가. US 규칙⑥과 근거 강도가 달라 탭을 나눈다.
    _lead_mkt = st.radio("시장", ["🇺🇸 미국 (규칙⑥)", "🇰🇷 한국 (KR-P1)"],
                         horizontal=True, key="lead_mkt",
                         help="두 규칙은 검증 수준이 다릅니다 — 미국은 워크포워드까지, "
                              "한국은 가격 백테스트만 거쳤습니다.")

if st.session_state.get('lead_mkt', '').startswith('🇰🇷'):
    with t_lead, guard('주도주 KR'):
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
                f"워크포워드 검증도 아직 없습니다.</div></div>", unsafe_allow_html=True)
            st.markdown(f"**진입** `{_kr['rule']}`  \n"
                        f"**유동성 컷** 20일 평균 거래대금 "
                        f"{_kr['params'].get('min_adv_eok', '-')}억 이상 (체결 가능한 신호만)  \n"
                        f"유니버스 {_kr['universe']:,}종 · 기간 {_kr['period']} · 생성 {_kr['generated']}")

            _k1, _k2, _k3, _k4 = st.columns(4)
            _k1.metric("거래당 평균수익", f"{_kbt.get('avg','-')}%",
                       help="왕복 비용 0.3% 차감 + 거래대금 컷 적용 후. 컷을 빼면 12.0%로 오르지만 "
                            "그건 체결 불가능한 소형주 신호를 포함한 값이라 쓰지 않는다.")
            _k2.metric("승률", f"{_kbt.get('winrate','-')}%", f"중앙값 {_kbt.get('med','-')}%",
                       delta_color="off", help="중앙값이 음수 = 전형적 거래는 손실. 소수의 대박이 전부를 만든다")
            _k3.metric("손익비", f"{_kbt.get('payoff','-')}")
            _k4.metric("상위 1% 의존도", f"{_kbt.get('top1pct_share','-')}%",
                       help="전체 수익 중 상위 1% 거래가 차지하는 비중. 높을수록 몇 건을 놓치면 무너진다")

            st.markdown(f"**이번 후보 {_kr['n']}종** — 최근 8주 내 신고가 돌파 후 아직 트레일링에 안 걸린 종목")
            if _kr['candidates']:
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
                            "이 분산에서는 구분할 수 없는 차이다.")
                st.markdown("그런데도 켜는 이유는 '수익'이 아니라 **선별성**이다:")
                st.markdown("- 거래가 **5,079 → 1,599건으로 68% 감소**. 연 590건은 개인이 다룰 수 없고, "
                            "연 186건은 다룰 수 있다. **실행 가능성이 곧 전략의 일부다.**")
                st.markdown("- 손익비 2.96 → 3.05, 상위 1% 의존도 49.3% → 46.7%로 **꼬리 의존이 완화**된다.")
                st.markdown("- **에코프로 2023-02-06 진입(+256%)은 필터를 통과한다** — 잡고 싶은 걸 죽이지 않는다.")
                st.caption("판정은 **공시 시차**를 반영한다: 2023Q1 실적은 3/31이 아니라 5월 중순에야 "
                           "알 수 있으므로, 분기말+50일(사업보고서 90일) 이후부터만 참조한다. "
                           "이걸 안 하면 미래를 훔쳐보는 백테스트가 된다.")

            with st.expander("💧 유동성 컷을 왜 넣었나 — 백테스트 수익을 깎는데도"):
                _sp = _kr.get('adv_spectrum', {})
                if _sp:
                    st.dataframe(pd.DataFrame([{
                        '거래대금 컷': f"{k}억", '거래': f"{v['n']:,}",
                        '평균수익': f"{v['avg']}%", '손익비': v['payoff'],
                        '상위1% 의존': f"{v['tail']}%",
                    } for k, v in sorted(_sp.items(), key=lambda x: int(x[0]))]),
                        use_container_width=True, hide_index=True, row_height=25, height=_dfh(6))
                st.markdown("컷을 올릴수록 백테스트 수익은 **단조로 떨어진다** (12.0% → 6.4%). "
                            "그런데도 넣는 이유:")
                st.markdown("- 컷 없는 **12.0% 안에는 실제로는 체결할 수 없는 소형주 신호가 섞여 있다.** "
                            "낮아진 9.8%가 '진짜 값'이다.")
                st.markdown("- 필터가 성과를 깎는다고 빼면 **백테스트만 예뻐지고 실전은 그대로**다.")
                st.markdown("- 10억은 개인 자금 규모에서 체결 가능한 최소선으로 잡았다.")
                st.caption("⚠️ 다만 컷을 올릴수록 **상위 1% 의존도가 44% → 70%로 오른다.** "
                           "유동성을 요구할수록 소수의 대박에 더 기대게 된다 — 분산이 더 중요해진다.")

            with st.expander("⚠️ 이 숫자를 믿으면 안 되는 이유 (반드시 읽을 것)"):
                for c in _kr.get('caveats', []):
                    st.markdown(f"- {c}")
                st.caption("특히 **중앙값이 -11%**다. 셋 중 둘은 손실로 끝나고, 수익의 44%가 상위 1% 거래에서 나온다. "
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
"내년에 하나 나온다"는 맞지만 "그게 뭔지 미리 안다"는 틀리다. → 한 종목을 맞히는 게 아니라
**후보 여러 개를 규칙으로 태우는 것**이 유일한 방법.
""")
else:
  with t_lead, guard('주도주 US'):
    st.caption(data_stamp('results/leaders_signal.json'))
    # 주도주 검증판 — 미국 1,279종·2018~2026 백테스트 + 워크포워드로 확정한 규칙⑤
    # (구 "주도주 지문" 로직은 2026-08-05 제거 — 신고가 −15% 이내·영익 YoY≥+100% 가 검증에서 기각됨)
    # ── 검증판 (규칙⑤) — 미국 1,279종·8.6년 백테스트 + 워크포워드로 확정한 규칙 ──
    _lsig = load_json(Path('results/leaders_signal.json'))
    if not _lsig:
        st.warning("주도주 신호 데이터 없음 → 로컬에서 `python leaders_publish.py` 실행 후 커밋.")
    else:
        _bt = _lsig['backtest']
        st.caption(
            f"미국 1,279종·2018~2026 백테스트와 워크포워드 6분할로 확정한 규칙. "
            f"*시장 필터(KR/US)와 무관하게 미국 전용이다.*  \n"
            f"**진입** `{_lsig['rule']}`  \n"
            f"**운용** {_lsig['exit']}  \n"
            f"기준 주차 **{_lsig['signal_week']}** · 유니버스 {_lsig['universe']:,}종 · "
            f"생성 {_lsig['generated']}")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("백테스트 CAGR", f"{_bt['cagr']}%", f"SPY {_bt['spy_cagr']}%")
        c2.metric("MDD", f"{_bt['mdd']}%", f"SPY {_bt['spy_mdd']}%", delta_color="inverse")
        c3.metric("회복배율", f"{_bt['recover']}", f"SPY {_bt['spy_recover']}")
        c4.metric("워크포워드", _bt['wf_cagr'], f"회복배율 {_bt['wf_recover']}", delta_color="off")

        st.markdown(f"**이번 주 후보 {_lsig['n']}종**")
        if _lsig['candidates']:
            st.dataframe(pd.DataFrame([{
                '종목': m['name'][:22], '코드': m['sym'], '종가': f"${m['close']:,.2f}",
                'RS13': m['rs_13w'], 'PSR': m['psr'],
                # str/float 혼재 열은 Arrow 직렬화가 실패해 로그가 지저분해진다 → 문자열로 통일
                'PER': ('-' if m['per'] is None else f"{m['per']:.1f}"),
                '신고가': f"{m['dist_52w']:+.1f}%",
                'OPM': ('-' if m['opm'] is None else f"{m['opm']:.1f}%"),
                'OPM QoQ': ('-' if m['opm_qoq'] is None else f"{m['opm_qoq']:+.1f}"),
                '시총($B)': m['marcap_b'],
                '트리거': ', '.join(m['triggers'])} for m in _lsig['candidates']]),
                use_container_width=True, hide_index=True, row_height=25,
                height=_dfh(len(_lsig['candidates'])))
        else:
            st.info("이번 주 조건 충족 종목 없음")

        # ── 후보 A·B (2026-08-15~) ────────────────────────────────────
        # 유니버스 look-ahead를 제거하자 규칙⑥이 밀렸다. 확정 전까지 병렬 관찰한다.
        _alt = _lsig.get('alt')
        if _alt:
            st.divider()
            st.subheader("🧪 후보 규칙 A·B — 병렬 관찰 중")
            st.caption("유니버스 선정의 look-ahead를 제거하고(수집 하한 $2B→$0.15B · 1,279→2,208종) "
                       "32개 조합을 전수 비교한 결과 위 규칙⑥보다 앞선 둘. "
                       "**아직 확정 규칙이 아니며 페이퍼로만 추적 중이다.**")
            _tabs = st.tabs([f"A · 회복 {_alt['A']['stat']['recover']}",
                             f"B · CAGR {_alt['B']['stat']['cagr']}%"])
            for _t, _k in zip(_tabs, ('A', 'B')):
                _a = _alt[_k]; _s = _a['stat']
                with _t:
                    st.markdown(f"**진입** `{_a['rule']}` · **{_a['slots']}종목** 균등")
                    _m = st.columns(5)
                    _m[0].metric("CAGR", f"{_s['cagr']}%", f"SPY {_bt['spy_cagr']}%")
                    _m[1].metric("MDD", f"{_s['mdd']}%", f"SPY {_bt['spy_mdd']}%",
                                 delta_color="inverse")
                    _m[2].metric("회복배율", _s['recover'], f"SPY {_bt['spy_recover']}")
                    _m[3].metric("승률", f"{_s['winrate']}%")
                    _m[4].metric("평균 노출", f"{_s['exposure']}%",
                                 help="낙폭을 만드는 건 손절폭이 아니라 노출이다. "
                                      "최악 낙폭 시점 현금이 A는 69.8%, B는 18.9%였다.")
                    if _k == 'B':
                        st.warning(_a['note'])
                    else:
                        st.caption(_a['note'])
                    st.markdown(f"**이번 주 후보 {_a['n']}종 중 상위 {len(_a['candidates'])}종**")
                    if _a['candidates']:
                        st.dataframe(pd.DataFrame([{
                            '종목': m['name'][:22], '코드': m['sym'],
                            '종가': f"${m['close']:,.2f}", 'RS13': m['rs_13w'],
                            'PER': ('-' if m['per'] is None else f"{m['per']:.1f}"),
                            'PSR': m['psr'],
                            'OPM': ('-' if m['opm'] is None else f"{m['opm']:.1f}%"),
                            '시총($B)': m['marcap_b'],
                            '트리거': ', '.join(m['triggers'])} for m in _a['candidates']]),
                            use_container_width=True, hide_index=True, row_height=25,
                            height=_dfh(len(_a['candidates'])))
                    else:
                        st.info("이번 주 조건 충족 종목 없음")

        # ── 종목 심층 조회 ─────────────────────────────────────────────
        # market.db는 저장소에 없으므로 leaders_symbol.py가 미리 만든 JSON을 읽는다.
        st.divider()
        st.subheader("🔍 종목 심층 조회 — 언제 걸렸고 언제 나갔나")
        _sd = load_json(Path('results/leaders_symbol_detail.json'))
        if not _sd:
            st.info("`python leaders_symbol.py build` 실행 후 커밋하면 조회할 수 있습니다.")
        else:
            _syms = _sd['symbols']
            _opts = sorted(_syms, key=lambda s: (-len(_syms[s].get('rows', [])), s))
            _pick = st.selectbox(
                f"종목 검색 — 신호 이력이 있는 {len(_opts)}종",
                _opts, index=0, key="lead_sym",
                format_func=lambda s: f"{s} · {_syms[s]['name'][:28]} "
                                      f"({len(_syms[s].get('rows', []))}회 신호)")
            _r = _syms[_pick]
            _D = pd.to_datetime(_sd['dates'])
            _px = pd.Series([v for v in _r['c']],
                            index=_D[[i for i in _r['i']]]).astype(float).dropna()

            _cols = {'A': '#17415c', 'B': '#a03028', 'R6': '#8a6a12'}
            _fig = go.Figure()
            _fig.add_trace(go.Scatter(x=_px.index, y=_px.values, mode='lines',
                                      name='주봉 종가', line=dict(color='#12161b', width=1.4)))
            for _k, _tr in _r.get('trades', {}).items():
                for _t in _tr:
                    _a, _b = _D[_t['e']], _D[_t['x']]
                    _fig.add_vrect(x0=_a, x1=_b, fillcolor=_cols[_k], opacity=.07,
                                   line_width=0, layer='below')
                    _fig.add_trace(go.Scatter(
                        x=[_a], y=[_t['ep']], mode='markers+text',
                        marker=dict(symbol='triangle-up', size=13, color=_cols[_k],
                                    line=dict(color='white', width=1)),
                        text=[f"{_k} {_t['ret']:+.0f}%"], textposition='bottom center',
                        textfont=dict(size=10, color=_cols[_k]),
                        name=f"{_k} 진입", showlegend=False,
                        hovertemplate=f"{_k} 진입 %{{x|%Y-%m-%d}}<br>${_t['ep']:,.2f}<extra></extra>"))
                    if _t['closed']:
                        _fig.add_trace(go.Scatter(
                            x=[_b], y=[_t['xp']], mode='markers',
                            marker=dict(symbol='triangle-down', size=13,
                                        color='#1f6b45' if _t['ret'] >= 0 else '#a03028',
                                        line=dict(color='white', width=1)),
                            name=f"{_k} 청산", showlegend=False,
                            hovertemplate=(f"{_k} 청산 %{{x|%Y-%m-%d}}<br>${_t['xp']:,.2f}"
                                           f"<br>{_t['ret']:+.1f}% · {_t['wk']}주<extra></extra>")))
            _fig.update_yaxes(type='log', title='주봉 종가(로그)')
            _fig.update_layout(height=430, margin=dict(l=8, r=8, t=34, b=8),
                               title=f"{_pick} · {_r['name']}  —  ▲ 진입 / ▼ 고점 −20% 청산",
                               hovermode='x unified')
            st.plotly_chart(_fig, use_container_width=True)

            _tr_all = [dict(규칙=_k, 진입=str(_D[_t['e']].date()),
                            청산=(str(_D[_t['x']].date()) if _t['closed'] else '보유 중'),
                            진입가=f"${_t['ep']:,.2f}", 청산가=f"${_t['xp']:,.2f}",
                            수익률=f"{_t['ret']:+.1f}%", 보유=f"{_t['wk']}주")
                       for _k, _tr in _r.get('trades', {}).items() for _t in _tr]
            if _tr_all:
                st.markdown("**매매 내역** — 규칙별 진입·청산·재진입")
                st.dataframe(pd.DataFrame(_tr_all).sort_values('진입'),
                             use_container_width=True, hide_index=True,
                             row_height=25, height=_dfh(len(_tr_all)))

            _rows = _r.get('rows', [])
            if _rows:
                st.markdown(f"**신호 주차 데이터 {len(_rows)}건** — 그 주에 각 지표가 얼마였나")
                st.dataframe(pd.DataFrame([{
                    '주차': x['d'], '규칙': ','.join(x['r']), '종가': x['close'],
                    'RS13': x['rs13'], 'RS26': x['rs26'], 'OPM': x['opm'],
                    'OPM QoQ': x['opmq'], 'PER': x['per'], 'PSR': x['psr'],
                    '신고가대비': x['dist'], '52주낙폭': x['mdd'], '거래량배': x['vol'],
                    '매출YoY': x['rev'], '시총($B)': x['mc'], '거래대금($M)': x['adv'],
                    '트리거': x['trg']} for x in _rows]),
                    use_container_width=True, hide_index=True, row_height=25,
                    height=_dfh(min(len(_rows), 14)))

        with st.expander("필터 단계별 잔존 · 기각된 조건"):
            st.dataframe(pd.DataFrame(_lsig['funnel'], columns=['단계', '종목수']),
                         use_container_width=True, hide_index=True, row_height=25, height=_dfh(4))
            st.markdown("**검증에서 기각된 조건** (넣으면 오히려 성과가 나빠짐)")
            for r in _bt['rejected']:
                st.markdown(f"- ~~{r}~~")

        _pp = _lsig.get('paper')
        if _pp:
            st.markdown(f"**📓 포워드 페이퍼 트레이딩** — 시작 {_pp['created']} · "
                        f"갱신 {_pp.get('updated','-')} · 보유 {_pp['n_open']} / 청산 {_pp['n_closed']}")
            if _pp['open']:
                st.dataframe(pd.DataFrame([{
                    '종목': t['sym'], '기록일': t['log_date'],
                    '진입': f"${t['entry']:,.2f}", '고점': f"${t['peak']:,.2f}",
                    '고점대비': f"{(t['entry']/t['peak']-1)*100:+.1f}%",
                    'RS13': t['rs'], 'PSR': t['psr'],
                    '트리거': ', '.join(t['triggers'])} for t in _pp['open']]),
                    use_container_width=True, hide_index=True, row_height=25,
                    height=_dfh(len(_pp['open'])))
            if _pp.get('live'):
                _lv = _pp['live']
                st.dataframe(pd.DataFrame([
                    {'지표': '평균 수익', '실전': f"{_lv['avg']:+.1f}%", '백테스트': num(_bt, 'avg_ret', '{:+.1f}%')},
                    {'지표': '중앙 수익', '실전': f"{_lv['med']:+.1f}%", '백테스트': num(_bt, 'med_ret', '{:+.1f}%')},
                    {'지표': '승률', '실전': f"{_lv['winrate']:.0f}%", '백테스트': num(_bt, 'winrate', '{:.0f}%')},
                    {'지표': '평균 보유', '실전': f"{_lv['hold_wk']:.0f}주", '백테스트': num(_bt, 'hold_wk', '{}주')}]),
                    use_container_width=True, hide_index=True, row_height=25, height=_dfh(4))
            else:
                st.caption(f"청산 거래가 없어 대조 불가. 백테스트 기대값 — "
                           f"중앙 {num(_bt, 'med_ret', '{:+.1f}%')} · "
                           f"승률 {num(_bt, 'winrate', '{:.0f}%')} · "
                           f"평균 보유 {num(_bt, 'hold_wk', '{}주')} · "
                           f"거래 {num(_bt, 'trades', '{}건')}")
        st.caption(
            f"⚠️ {_bt['period']} 백테스트. 생존편향(상폐 미포함)·인샘플 규칙선택이 있어 낙관적이며, "
            f"워크포워드는 CAGR {_bt['wf_cagr']}·회복배율 {_bt['wf_recover']}로 **절반은 SPY에 진다**. "
            f"조건 충족 종목의 기계적 출력이며 매수 권유가 아님.")

# ── 종목 프로파일 (계절성 + MDD 통합) ──
# ── 💎 가치 발굴 — 기본적 분석 기준 (뭘 살까) ──
with t_value, guard('가치 발굴'):
    st.caption(data_stamp('results/value_kr.json'))
    st.caption("💎 공식 지표(KRX)로 '싸고(저PER·저PBR) 돈 잘 버는(ROE·성장·배당)' 종목 발굴 — 가격이 아니라 가치 기준.")
    if _GMKT == "US":
        st.info("US 가치 스크린은 EDGAR 벌크 적재 후 제공 예정 — 지금은 KR만. "
                "(US 개별 종목 밸류는 🔍 종목 분석에서 공식 멀티플로 확인)")
    else:
        _vj = load_json(Path('results/value_kr.json'))
        _ATTM = _attract_map("KR")   # 이 탭은 KR 전용 — 전역 _GMKT가 US여도 KR 매력도로 조회
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
            st.radio("정렬", ["저PER순", "위닝점수순"], horizontal=True, key="val_sort",
                     help="위닝점수 = 백테스트 샤프 가중 셋업 점수. '싼 순'만 보면 저PER 함정이 늘 위로 온다.")
            def _fmt_growth(v):
                # 숫자·'흑자전환' 문자열 혼재 컬럼 → 균일 문자열 (Arrow 직렬화 오류 방지)
                if isinstance(v, str): return v
                return f"{v:+.0f}" if v is not None else '-'
            _vrows = []
            for s in _vj['stocks']:
                _per, _pbr, _roe = s.get('per'), s.get('pbr'), s.get('roe')
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
                _vrows.append({'종목': s['name'], '코드': s['sym'],
                               '시총': fmt_cap(s.get('marcap'), 'KR'),
                               'PER': _per, 'PBR': _pbr, 'PSR': s.get('psr'),
                               'ROE%(위치)': _roe,
                               'ΔROE(속도)': _tr.get('d_roe'),
                               'ΔOPM(마진속도)': _tr.get('d_opm'),
                               '매출성장': _fmt_growth(s.get('rev_growth')),
                               '성장가속': _tr.get('growth_accel'),
                               '궤적': f"{_tr.get('traj_score')}/7" if _tr.get('traj_score') is not None else '-',
                               '판정': _tr.get('verdict_label', '-'),
                               '컨센리비전': ({'up': '📈 상향', 'down': '📉 하향', 'flat': '➖ 유지'}
                                          .get((_REVM.get(s['sym']) or {}).get('dir'), '-')),
                               '고점대비%': _mdd_col(s['sym'], _MDDM),
                               '기준': s.get('period')})
            # 정렬 축을 '싼 순'에만 묶어두면 저PER 함정이 늘 맨 위로 온다.
            # 위닝점수(셋업의 질)는 이미 전 표에 계산돼 있으니 정렬 축으로도 쓴다.
            if st.session_state.get('val_sort', '저PER순') == '위닝점수순':
                _vrows.sort(key=lambda r: -(( _ATTM.get(r['코드']) or {}).get('score') or -1))
            else:
                _vrows.sort(key=lambda r: r['PER'])
            _ntrap = sum(1 for s in _vj['stocks'] if (s.get('traj') or {}).get('verdict') == 'deteriorating')
            st.subheader(f"💎 저평가·우량 — {len(_vrows)}개 (PER≤{_vper} · PBR≤{_vpbr} · ROE≥{_vroe}% · 영업익≥{_vgrw}%)")
            if _vrows:
                _vdf9 = pd.DataFrame(_vrows[:50])
                def _c_verd(v):
                    s = str(v)
                    if '개선' in s or '상향' in s: return 'color:#16a34a;font-weight:bold'
                    if '악화' in s or '하향' in s: return 'color:#dc2626;font-weight:bold'
                    return 'color:#888'
                def _c_delta(v):
                    try: return 'color:#16a34a' if float(v) >= 0 else 'color:#dc2626'
                    except Exception: return ''
                st.dataframe(
                    _vdf9.style.map(_c_verd, subset=['판정', '컨센리비전'])
                        .map(_c_delta, subset=['ΔROE(속도)', 'ΔOPM(마진속도)', '성장가속'])
                        .format({'PER': '{:.1f}', 'PBR': '{:.2f}', 'PSR': '{:.2f}', 'ROE%(위치)': '{:.1f}',
                                 'ΔROE(속도)': '{:+.1f}', 'ΔOPM(마진속도)': '{:+.1f}', '성장가속': '{:+.1f}'}, na_rep='-'),
                    use_container_width=True, hide_index=True, row_height=25, height=_dfh(min(len(_vdf9), 20)))
                st.caption(f"커버리지 {_vj.get('coverage')}종목(DART 공식재무 × 실시간 시총). "
                           f"**위치(스칼라) + 속도(Δ, 전년대비) + 가속(Δ²)** = 벡터 — Piotroski F-Score 방식. "
                           f"판정: 📈개선 가속 / ➖정체 / 📉악화(함정). ⚠️ 현재 전체 밸류 유니버스 중 **{_ntrap}종목이 '싸지만 악화 중'**(함정) — "
                           f"위치만 보면 안 보이던 것. **컨센리비전**=애널 추정(올해EPS) 4주 변화 "
                           f"({'축적 {}주차 — 방향 판독까지 몇 주 더'.format(len(_REVM)) if _REVM else '스냅샷 축적 시작 — 다음 주부터 방향'}).")
            else:
                st.info("조건 통과 종목 없음 — 기준을 완화해보세요.")



# ── 📒 성적표 — 추천 사후분석 (포워드 트랙레코드) ──
@st.cache_data(ttl=3600, show_spinner=False)
def _wp_analyze_cached():
    import weekly_portfolio as _wp
    return _wp.analyze()

with t_track, guard('성적표'):
    st.caption("📒 시스템 추천을 이후 실제 가격으로 채점 — '신호가 나온다 ≠ 돈 번다'의 증거를 쌓는 곳. "
               "가상매매(신호별 정확도)와 주간 포트폴리오(종합 성과 vs 시장)로 나눠 본다.")
    import paper_trade as _pt
    _ptd = _pt._load()
    _ptr = _ptd.get('trades', [])
    _n4t = sum(1 for t in _ptr if '4w' in t.get('realized', {}))
    _n13t = sum(1 for t in _ptr if '13w' in t.get('realized', {}))
    _lastlog = max((t['log_date'] for t in _ptr), default=None)
    _tk1, _tk2, _tk3, _tk4 = st.columns(4)
    _tk1.metric("누적 가상매매", f"{len(_ptr)}건")
    _tk2.metric("4주 만기", f"{_n4t}건")
    _tk3.metric("13주 종료", f"{_n13t}건")
    _tk4.metric("마지막 기록", _lastlog or '-')
    if _lastlog:
        _staled = (datetime.now() - datetime.strptime(_lastlog, '%Y-%m-%d')).days
        if _staled > 10:
            st.error(f"⚠️ 가상매매 기록이 **{_staled}일째 정지** — daily-refresh의 weekly_run이 "
                     "신호를 생산하지 못하고 있음. 파이프라인부터 살려야 성적표가 쌓임.")

    st.markdown("##### 🎯 신호별 실전 성적 vs 백테스트 (가상매매)")
    _hz_pick = st.radio("보유 기간", ["4주", "13주"], horizontal=True, key="track_hz")
    _hz = '4w' if _hz_pick == "4주" else '13w'
    _agg9 = _pt._agg_by_signal(_ptr, _hz)
    _trows = []
    for _f in _pt.SIG_FLAGS:
        _v = _agg9.get(_f)
        _ref = _pt.BACKTEST_REF[_f][_hz]
        if _v is None:
            _trows.append({'신호': _pt.SIG_LABEL[_f], '표본': 0, '실전승률': '-', '실전EV': '-',
                           '백테EV': f"{_ref:+.1f}%", '괴리': '-', '신뢰계수': '1.00 (중립)'})
        else:
            _gap = _v['live_ev'] - _ref
            _mult = _pt._reliability_mult(_v['live_ev'], _ref, _v['n'])
            _trows.append({'신호': _pt.SIG_LABEL[_f], '표본': _v['n'],
                           '실전승률': f"{_v['wr']:.0f}%", '실전EV': f"{_v['live_ev']:+.2f}%",
                           '백테EV': f"{_ref:+.1f}%", '괴리': f"{_gap:+.2f}%p",
                           '신뢰계수': f"{_mult:.2f}"})
    _tdf = pd.DataFrame(_trows)
    def _c_gap(v):
        try:
            f = float(str(v).replace('%', '').replace('p', '').replace('+', ''))
            return 'color:#56d364' if f >= 0 else ('color:#f0c040' if f > -1.5 else 'color:#f78166;font-weight:bold')
        except Exception:
            return ''
    st.dataframe(_tdf.style.map(_c_gap, subset=['괴리']),
                 use_container_width=True, hide_index=True,
                 row_height=25, height=_dfh(len(_tdf)))
    st.caption("신뢰계수 = 실전EV/백테EV를 표본수로 수축 보정(적으면 1.0으로 수렴, 상한 1.3) — "
               "**auto_recommend·위닝점수가 이 계수로 신호 비중을 자동 가감** (results/signal_live_weights.json). "
               "괴리가 크게 음수인 신호 = 과최적화 의심 → 표본 30건+ 쌓이면 강등 검토.")

    st.divider()
    st.markdown("##### 📊 주간 추천 포트폴리오 사후분석 (진입가 → 현재, vs 시장)")
    _wpres = _wp_analyze_cached()
    if not _wpres:
        st.info("주간 포트폴리오 히스토리 없음 — weekly_run이 매주 스냅샷을 쌓으면 여기 채워짐.")
    else:
        _wrows = [{'주차': r['week'], '세트': {'p10': '10선', 'p20': '20선', 'ckr': '역발상KR'}.get(r['set'], r['set']),
                   '종목수': r['n'], '현금%': f"{r['cash_pct']:.0f}",
                   '포트수익': f"{r['port_return']:+.2f}%",
                   '벤치(KOSPI·SPY)': f"{r['bench_return']:+.2f}%" if r.get('bench_return') is not None else '-',
                   '알파': f"{r['alpha']:+.2f}%p" if r.get('alpha') is not None else '-'}
                  for r in _wpres]
        _wdf9 = pd.DataFrame(_wrows)
        st.dataframe(_wdf9.style.map(_c_gap, subset=['포트수익', '알파']),
                     use_container_width=True, hide_index=True,
                     row_height=25, height=_dfh(len(_wdf9)))
        st.markdown("###### 🔍 스냅샷 상세 — 실제로 뭘 담았고 각각 얼마나 갔나")
        _SET_LAB = {'p10': '10선', 'p20': '20선', 'ckr': '역발상KR'}
        _wk_opts = [f"{r['week']} [{_SET_LAB.get(r['set'], r['set'])}]" for r in _wpres]
        _wk_pick = st.selectbox("주차 선택", _wk_opts, index=len(_wk_opts) - 1, key="track_wk_detail")
        _wsel = _wpres[_wk_opts.index(_wk_pick)]
        _ddet = _wsel.get('details', [])
        if _ddet:
            _ddf = pd.DataFrame([{
                '종목': d['name'], '코드': d['sym'], '시장': d.get('market', '-'),
                '비중%': f"{d['weight_pct']:.1f}",
                '진입가': f"{d['entry']:,.2f}" if d.get('entry') else '-',
                '현재가': f"{d['cur']:,.2f}" if d.get('cur') else '조회실패',
                '수익률': d.get('ret'),
                '상태': ('🔴 손절가 이탈' if d.get('hit_stop') else
                        '🟢 목표가 도달' if d.get('hit_target') else
                        '⚪ 보유중' if d.get('ret') is not None else '-'),
                '신호': ', '.join(d.get('signals', [])[:3]) or '-',
            } for d in sorted(_ddet, key=lambda x: -(x['weight_pct'] or 0))])
            st.dataframe(_ddf.style.map(_c_gap, subset=['수익률']).format({'수익률': lambda v: f"{v:+.1f}%" if v is not None else '-'}),
                         use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_ddf)))
        else:
            st.caption("상세 없음")
        st.caption("벤치마크 = 스냅샷의 KR/US 비중대로 KOSPI·SPY를 섞은 같은 기간 수익률. "
                   "알파>0 = 시장을 이겼다는 뜻. 표본이 몇 주 쌓이기 전엔 소음이 큼 — 4주·13주 누적으로 판단.")


# ════════════════════════════════════════════════════════════════════
# 탭3: CANSLIM (슬라이더 실시간 조정)
# ════════════════════════════════════════════════════════════════════
with tab3, guard('CANSLIM'):
    st.caption(data_stamp('results/canslim_latest.json'))
    _cs_mkt = st.radio("시장", ["🇰🇷 한국", "🇺🇸 미국"], horizontal=True, key="canslim_mkt")
    _cs_kr = _cs_mkt.endswith("한국")
    _CS_JSON = CANSLIM_JSON if _cs_kr else Path('results/canslim_us_latest.json')
    _ATTM = _attract_map("KR" if _cs_kr else "US")   # 이 탭은 자체 KR/US 토글 — 전역 _GMKT와 별개
    _TRAJM = _traj_map()                             # 궤적(KR만) — US는 '-'
    st.header(f"🏆 CANSLIM 스크리너 ({'한국' if _cs_kr else '미국'})")
    update_badge(_CS_JSON)
    canslim = load_json(_CS_JSON)
    if not _cs_kr:
        st.caption("US: C·A=SEC EDGAR 공식 재무 · I(기관 수급)는 무료 일간 소스가 없어 '?'(13F는 분기 지연) — I 필수 체크 비권장")

    if canslim is None:
        st.error(f"데이터 없음 → `python {'canslim_run.py' if _cs_kr else 'canslim_us_run.py'}` 실행 후 새로고침")
    else:
        col1, col2, col3 = st.columns(3)
        col1.metric("기준일", canslim['date'])
        col2.metric("시장방향(M)", canslim['market_dir'])
        col3.metric("후보 종목", f"{len(canslim['stocks'])}개 (N+RS 사전필터)")

        if not canslim['market_ok']:
            st.warning(f"⚠️ {'KOSPI' if _cs_kr else 'S&P500'} 하락추세 — 신규매수 주의")

        m_ok = canslim['market_ok']

        with st.expander("⚙️ CANSLIM 기준 조정 (슬라이더로 실시간)", expanded=False):
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

            score = sum([bool(m_ok), n_ok, l_ok, s_ok, c_ok, a_ok, i_ok])

            # 시총은 숫자로 저장 (표시 포맷은 column_config가 담당) — 문자열로 저장하면
            # 표 헤더 클릭 정렬이 사전순("$9B">"$87B")으로 깨짐 (#4 실측 확인)
            _cap_num = (s.get('marcap') or 0) / (1e12 if _cs_kr else 1e9)   # KR=조원, US=$B
            def _gtxt(v):
                return v if isinstance(v, str) else (f"{v:+.0f}%" if v is not None else '??')
            if a_y1 is not None and a_y2 is not None:
                a_tag = f"{'✅' if a_ok else '❌'} {_gtxt(a_y1)}/{_gtxt(a_y2)}"
            elif a_y1 is not None:
                a_tag = f"{'✅' if _ge(a_y1, th_A1) else '❌'} {_gtxt(a_y1)}/??"
            else:
                a_tag = '?'

            rows3.append({
                '종목명':  s['name'],
                '코드':    s['sym'],
                '시총':    _cap_num,
                '점수/7':  score,
                'RS':      _tag3(rs,     th_L,  '{:.0f}p'),
                'N 거리%': _tag3(n_dist, th_N,  '{:+.1f}%'),
                'S 배수':  _tag3(vol,    th_S,  '{:.1f}x'),
                'C 분기%': _tag3(c_g,    th_C,  '{:+.0f}%'),
                'A 연간%': a_tag,
                'I 순매수': _tag3(i_inst, th_I,  '{:+.0f}억'),
                '고점대비%': _mdd_col(s['sym'], _MDDM),
                '궤적': _traj_col(s['sym'], _TRAJM) if _cs_kr else '-',
                '매력도': _attract_col(s['sym'], _ATTM),
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

            # 컬럼을 CANSLIM 글자 순서(C→A→N→S→L→I)로 (#3)
            disp3 = ['종목명','코드','시총','점수/7','C 분기%','A 연간%','N 거리%','S 배수','RS (L)','I 순매수',
                     '고점대비%','궤적','매력도']
            df3 = df3.rename(columns={'RS': 'RS (L)'})
            sig3c = ['C 분기%','A 연간%','N 거리%','S 배수','RS (L)','I 순매수']

            st.subheader(f"총 {len(df3)}개 종목 | N✅ L✅ 필수, C/A/S/I는 슬라이더 기준으로 색상 표시")
            st.dataframe(
                df3[disp3].style
                    .map(color_score3, subset=['점수/7'])
                    .map(color_cell3,  subset=sig3c),
                use_container_width=True,
                row_height=25, height=_dfh(len(df3), cap=760),
                column_config={'시총': st.column_config.NumberColumn(
                    '시총', format=('%.1f조' if _cs_kr else '$%.1fB'))},
            )
            with st.expander("📖 CANSLIM 각 항목 기준·설명", expanded=False):
                st.dataframe(pd.DataFrame([
                    {'글자': 'C', '이름': '분기 실적', '컬럼': 'C 분기%',
                     '기준': '최근 분기 순이익 YoY ≥ +20% (흑자전환 포함)', '출처': 'DART 공식(폴백 네이버)'},
                    {'글자': 'A', '이름': '연간 실적', '컬럼': 'A 연간%',
                     '기준': '연간 순이익 YoY ≥ +20% × 2개년 (최근년/전년)', '출처': 'DART 공식(폴백 네이버)'},
                    {'글자': 'N', '이름': '신고가 근접', '컬럼': 'N 거리%',
                     '기준': '52주 신고가 대비 거리 — 0%에 가까울수록(신고가 부근) 강함', '출처': '주가'},
                    {'글자': 'S', '이름': '수급(거래량)', '컬럼': 'S 배수',
                     '기준': '거래량이 평균 대비 몇 배 터졌나 (≥1.5x + 양봉 몸통)', '출처': '주가·거래량'},
                    {'글자': 'L', '이름': '주도주(상대강도)', '컬럼': 'RS (L)',
                     '기준': 'RS = 최근 수익률의 시장 내 백분위(0~100). 90p = 상위 10% 강자', '출처': '주가(상대비교)'},
                    {'글자': 'I', '이름': '기관 수급', '컬럼': 'I 순매수',
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
                    'C 분기실적': sum(1 for r in rows3 if '✅' in str(r['C 분기%'])),
                    'A 연간실적': sum(1 for r in rows3 if '✅' in str(r['A 연간%'])),
                    'S 거래량':   sum(1 for r in rows3 if '✅' in str(r['S 배수'])),
                    'I 기관수급': sum(1 for r in rows3 if '✅' in str(r['I 순매수'])),
                }
                pr_df = pd.DataFrame({
                    '항목': list(pr_counts.keys()),
                    '통과수': list(pr_counts.values()),
                    '통과율(%)': [round(v/total3*100, 1) for v in pr_counts.values()],
                })
                st.dataframe(pr_df, use_container_width=False, hide_index=True,
                             row_height=25, height=_dfh(len(pr_df)))


# ════════════════════════════════════════════════════════════════════
# 탭4: 글로벌 매크로
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600)
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


@st.cache_data(ttl=3600)
def _fetch_index_history_cached(symbol: str, days: int):
    import FinanceDataReader as fdr
    start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    df = fdr.DataReader(symbol, start)[['Close']].rename(columns={'Close': symbol})
    if df is None or df.empty:
        raise RuntimeError('empty')
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def fetch_index_history(symbol: str, days: int = 365):
    try:
        return _fetch_index_history_cached(symbol, days)
    except Exception:
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
        title=dict(text=title, font=dict(size=13), x=0, xanchor='left'),
        height=height + 34, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#8b949e', size=10),
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
def _pctile(vals, x):
    """vals 분포에서 x의 백분위(0~100)."""
    if not vals or x is None:
        return None
    return round(sum(1 for v in vals if v <= x) / len(vals) * 100)


def _yoy_series(obs, k=12):
    """[(date,val)] → [(date, YoY%)]. 월간 시계열 전용."""
    out = []
    for i in range(k, len(obs)):
        prev = obs[i - k][1]
        if prev:
            out.append((obs[i][0], (obs[i][1] / prev - 1) * 100))
    return out


@st.cache_data(ttl=3600, show_spinner=False)
def macro_inputs():
    """국면 판정용 원지표를 한 번에 수집. 실패 항목은 None으로 남기고 나머지로 진행한다."""
    d = {}
    ff = fetch_fred('FEDFUNDS', 130)                      # 월간 ~10년
    if ff:
        d['fed'] = ff[-1][1]
        d['fed_6m'] = round(ff[-1][1] - ff[-7][1], 2) if len(ff) >= 7 else None
        d['fed_12m'] = round(ff[-1][1] - ff[-13][1], 2) if len(ff) >= 13 else None
        d['fed_pct'] = _pctile([v for _, v in ff], ff[-1][1])
        d['fed_hist'] = ff
    ip = fetch_fred('INDPRO', 130)                        # 산업생산 = 실적 사이클 대용
    if ip:
        ipy = _yoy_series(ip)
        d['ip_yoy'] = round(ipy[-1][1], 2) if ipy else None
        d['ip_hist'] = ipy
    ur = fetch_fred('UNRATE', 40)
    if ur:
        d['unrate'] = ur[-1][1]
        lo12 = min(v for _, v in ur[-12:]) if len(ur) >= 12 else ur[-1][1]
        d['sahm'] = round(ur[-1][1] - lo12, 2)            # 삼의 법칙 근사(12개월 최저 대비)
    m2 = fetch_fred('M2SL', 26)
    if m2 and len(m2) >= 13:
        d['m2_yoy'] = round((m2[-1][1] / m2[-13][1] - 1) * 100, 2)
    cpi = fetch_fred('CPIAUCSL', 26)
    if cpi and len(cpi) >= 13:
        d['cpi_yoy'] = round((cpi[-1][1] / cpi[-13][1] - 1) * 100, 2)
    t10, t2 = fetch_fred('DGS10', 5), fetch_fred('DGS2', 5)
    if t10 and t2:
        d['spread'] = round(t10[-1][1] - t2[-1][1], 2)
    hy = fetch_fred('BAMLH0A0HYM2', 2600)                 # 하이일드 OAS = 신용 스트레스
    if hy:
        d['hy'] = hy[-1][1]
        d['hy_pct'] = _pctile([v for _, v in hy], hy[-1][1])
    vx = fetch_fred('VIXCLS', 2600)
    if vx:
        d['vix'] = vx[-1][1]
        d['vix_pct'] = _pctile([v for _, v in vx], vx[-1][1])
    return d


def macro_price_state():
    """주가 추세 — 200일선 위/아래, 52주 위치, 12개월 모멘텀."""
    df = fetch_index_history('SPY', 400)
    if df.empty or len(df) < 210:
        return {}
    c = df.iloc[:, 0]
    cur = float(c.iloc[-1])
    ma200 = float(c.tail(200).mean())
    hi, lo = float(c.tail(252).max()), float(c.tail(252).min())
    return {
        'spx': cur, 'ma200': ma200, 'above_ma': cur > ma200,
        'pos52': round((cur - lo) / (hi - lo) * 100) if hi > lo else None,
        'mom12': round((cur / float(c.iloc[-252]) - 1) * 100, 1) if len(c) >= 252 else None,
    }


# 우라가미 구미오 4계절 — (금리 방향 × 실적 방향 × 주가 추세)
SEASONS = {
    'FIN':  dict(emoji='🌱', name='금융장세', sub='유동성이 끌어올리는 장 (봄)',
                 desc='실적은 아직 나쁜데 금리가 내려가며 돈이 먼저 들어온다. 밸류에이션이 먼저 오른다.',
                 works='금리민감·성장주·소외 대형주. 실적보다 "금리 방향"이 주가를 정한다.',
                 fails='실적 기준 종목 선별. 지금 좋은 실적은 이미 과거다.'),
    'EARN': dict(emoji='☀️', name='실적장세', sub='펀더멘털이 끌어올리는 장 (여름)',
                 desc='금리가 올라도 이익이 더 빨리 는다. 이익이 나오는 종목만 오른다.',
                 works='이익 증가·흑자전환·주도주. 이 도구의 🚀주도주·🏆CANSLIM이 가장 잘 맞는 구간.',
                 fails='유동성만 보고 사는 저가 매수. 이익 없는 종목은 여기서 걸러진다.'),
    'RFIN': dict(emoji='🍂', name='역금융장세', sub='긴축이 눌러 내리는 장 (가을)',
                 desc='이익은 아직 괜찮은데 금리·긴축이 멀티플을 깎는다. 좋은 실적에도 주가가 안 간다.',
                 works='현금 비중 확대·손절 규율. 고PER·고PSR 축소.',
                 fails='"실적 좋으니 괜찮다"는 논리. 이 국면에서 깨지는 대표적 착각이다.'),
    'RERN': dict(emoji='❄️', name='역실적장세', sub='이익이 무너지는 장 (겨울)',
                 desc='금리는 내려오는데 이익이 더 빨리 무너진다. 싸 보이는 게 함정인 구간.',
                 works='현금·채권. 워치리스트 작성. "실탄을 들고 기다리는 것"이 전략이다.',
                 fails='물타기·저PER 매수. 분모(이익)가 계속 깎이면 PER은 사후에 올라간다.'),
}

# 코스톨라니 달걀 — 금리 사이클 위치로 '지금 무슨 자산을 들 때인가'
EGG = [
    ('A1', '금리 고점 통과 → 채권', '금리가 꼭대기를 찍고 내려오기 시작. 채권이 가장 유리한 구간.'),
    ('A2', '금리 하락 중 → 채권·부동산', '금리 하락이 진행 중. 주식은 아직 이르지만 준비 구간.'),
    ('A3', '금리 저점 → 주식 매수', '금리가 바닥. 코스톨라니가 "주식을 사라"고 한 자리.'),
    ('B1', '금리 저점 통과 → 주식 보유', '금리가 바닥에서 오르기 시작. 주식 상승이 가장 강한 구간.'),
    ('B2', '금리 상승 중 → 주식 축소', '금리 상승이 진행 중. 비중을 줄여가야 하는 구간.'),
    ('B3', '금리 고점 접근 → 현금·예금', '금리가 꼭대기 근처. 현금이 가장 편한 구간.'),
]


def macro_regime(d, px):
    """세 렌즈 판정 + 근거. d=macro_inputs(), px=macro_price_state()."""
    fed6, ip, sahm = d.get('fed_6m'), d.get('ip_yoy'), d.get('sahm')
    rate_dir = '하락' if (fed6 is not None and fed6 <= -0.25) else \
               ('상승' if (fed6 is not None and fed6 >= 0.25) else '횡보')
    if ip is None:
        growth = '횡보'
    elif ip >= 1.0:
        growth = '개선'
    elif ip <= -1.0:
        growth = '악화'
    else:
        growth = '횡보'
    if sahm is not None and sahm >= 0.5:          # 삼의 법칙 발동 시 성장은 악화로 덮어씀
        growth = '악화'
    up = bool(px.get('above_ma')) and (px.get('mom12') or 0) > 0
    px_dir = '상승' if up else '하락'

    sc = {
        'FIN':  (2 if rate_dir == '하락' else 0) + (1 if growth in ('악화', '횡보') else 0) + (2 if px_dir == '상승' else 0),
        'EARN': (1 if rate_dir in ('횡보', '상승') else 0) + (2 if growth == '개선' else 0) + (2 if px_dir == '상승' else 0),
        'RFIN': (2 if rate_dir == '상승' else 0) + (1 if growth in ('개선', '횡보') else 0) + (2 if px_dir == '하락' else 0),
        'RERN': (2 if growth == '악화' else 0) + (2 if px_dir == '하락' else 0) + (1 if rate_dir == '하락' else 0),
    }
    order = sorted(sc.items(), key=lambda kv: -kv[1])
    phase, top = order[0]
    conf = top - order[1][1]                       # 1위와 2위 점수차 = 확신도

    # 코스톨라니 달걀 — 금리의 사이클 위치 × 방향
    # 6개월 변화가 0 근처(횡보)면 달걀 위치가 정해지지 않는다. 이때 12개월 변화로 한 번 더
    # 물어보고, 그래도 정체면 '방향 미정'을 숨기지 말고 표시한다(예전엔 횡보를 '하락'으로
    # 흘려보내 "금리 하락 중"이라고 잘못 단정했다).
    fp, f12 = d.get('fed_pct'), d.get('fed_12m')
    egg_dir = rate_dir
    if egg_dir == '횡보' and f12 is not None and abs(f12) >= 0.5:
        egg_dir = '하락' if f12 < 0 else '상승'
    egg_flat = (egg_dir == '횡보')
    if fp is None:
        egg_i = None
    elif fp >= 70:
        egg_i = 0 if egg_dir == '하락' else 5          # 고점 통과=A1(채권) / 고점 접근·정체=B3(현금)
    elif fp >= 30:
        egg_i = 1 if egg_dir == '하락' else (4 if egg_dir == '상승' else (4 if fp >= 50 else 1))
    else:
        egg_i = 2 if egg_dir == '하락' else 3          # 저점 하락중=A3(매수) / 저점 통과=B1(보유)

    # 막스 시계추 — 0=극도의 공포, 100=극도의 탐욕
    parts = []
    if d.get('hy_pct') is not None:
        parts.append(100 - d['hy_pct'])            # 스프레드 낮을수록 탐욕
    if d.get('vix_pct') is not None:
        parts.append(100 - d['vix_pct'])
    if px.get('pos52') is not None:
        parts.append(px['pos52'])
    pend = round(sum(parts) / len(parts)) if parts else None

    return dict(phase=phase, scores=sc, conf=conf, rate_dir=rate_dir, growth=growth,
                px_dir=px_dir, egg_i=egg_i, egg_flat=egg_flat, pend=pend, second=order[1][0])


def macro_triggers(d, px):
    """국면을 넘기는 관측 가능한 방아쇠. (방향, 지표, 현재, 임계, 넘었나, 뜻)"""
    T = []
    def add(side, name, cur, thr, hit, why, fmt='{:+.2f}'):
        T.append(dict(side=side, name=name,
                      cur=('-' if cur is None else fmt.format(cur)),
                      thr=thr, hit=(None if cur is None else hit), why=why))
    hy, sp = d.get('hy'), d.get('spread')
    add('악화', 'HY 하이일드 스프레드', hy, '≥ 5.00%', (hy is not None and hy >= 5.0),
        '신용경색 신호. 5%를 넘으면 이익 사이클이 꺾이며 ❄️역실적장세로 넘어가는 경우가 많다.', '{:.2f}%')
    add('악화', '10Y-2Y 금리차', sp, '< 0.00%', (sp is not None and sp < 0),
        '재역전은 경기 침체 선행. 역전 해소 직후 침체가 오는 패턴도 있어 방향을 같이 본다.')
    add('악화', '실업률 상승폭(12개월 최저 대비)', d.get('sahm'), '≥ +0.50%p',
        (d.get('sahm') is not None and d['sahm'] >= 0.5),
        '삼의 법칙. 발동하면 성장을 "악화"로 강제 전환한다 — 실적장세 종료 신호.', '{:+.2f}')
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


with tab4, guard('매크로'):
    st.header("🌍 매크로 — 지금은 사이클의 어느 국면인가")
    st.caption(f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M')} · FRED · FDR (1시간 캐시)")

    with st.spinner("사이클 지표 수집 중..."):
        _MI = macro_inputs()
        _PX = macro_price_state()
    _RG = macro_regime(_MI, _PX)
    _S = SEASONS[_RG['phase']]

    fed_rate = _MI.get('fed')
    m2_yoy   = _MI.get('m2_yoy')
    spx_yoy  = fetch_spx_yoy()
    kr_rate  = _fred_latest('INTDSRKRM193N')
    signal, cash_min, cash_max, score, details = compute_macro_signal(fed_rate, m2_yoy, spx_yoy)

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
    # 색 면적도 줄인다 — 큰 색 블록이 나란히 서면 화면이 소리를 지른다(2026-08-13).
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

    # ── ② 세 렌즈 ────────────────────────────────────────────────
    st.divider()
    st.subheader("🔭 세 렌즈로 본 현재 위치")
    st.caption("셋이 서로 어긋나면 그 자체가 '전환기' 신호다.")
    _L1, _L2, _L3 = st.columns(3, gap='medium')

    with _L1.container(border=True):
        st.markdown("##### 🗓️ 우라가미 4계절")
        st.caption("장세의 **종류** — 지금이 무슨 장인가")
        for k in ('FIN', 'EARN', 'RFIN', 'RERN'):
            _on = (k == _RG['phase'])
            _sv = SEASONS[k]
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"padding:{'9px 12px' if _on else '7px 12px'};margin:4px 0;border-radius:8px;"
                f"font-size:{'15px' if _on else '13.5px'};"
                f"background:{'#0b0b0b' if _on else '#f4f4f2'};color:{'#fff' if _on else '#52514e'};"
                f"font-weight:{'700' if _on else '500'}'>"
                f"<span>{_sv['emoji']} {_sv['name']}</span>"
                f"<span style='font-variant-numeric:tabular-nums;opacity:{'1' if _on else '.7'}'>"
                f"{_RG['scores'][k]}점</span></div>",
                unsafe_allow_html=True)
        with st.expander("판정 근거"):
            st.caption("점수 = (금리 방향 · 실적 방향 · 주가 추세) 3축 부합도의 합. "
                       "최고점이 현재 국면이고, 1위와 2위의 점수차가 확신도다.")

    with _L2.container(border=True):
        st.markdown("##### 🥚 코스톨라니 달걀")
        st.caption("무슨 **자산**을 들 때인가 — 금리 사이클 위치")
        if _RG['egg_i'] is None:
            st.caption("금리 데이터 없음 — 판정 불가")
        else:
            for i, (code, title, why) in enumerate(EGG):
                _on = (i == _RG['egg_i'])
                st.markdown(
                    f"<div style='padding:{'8px 12px' if _on else '5px 12px'};margin:3px 0;"
                    f"border-radius:8px;font-size:{'14px' if _on else '12.5px'};"
                    f"background:{'#0b0b0b' if _on else '#f4f4f2'};color:{'#fff' if _on else '#52514e'};"
                    f"font-weight:{'700' if _on else '500'}'>{code} · {title}</div>",
                    unsafe_allow_html=True)
            _ei = _RG['egg_i']
            if _RG.get('egg_flat'):
                # 금리가 정체면 방향이 없으므로 '하락 중/상승 중' 같은 단정을 하지 않는다.
                _nb = [EGG[j][0] for j in (_ei - 1, _ei + 1) if 0 <= j < len(EGG)]
                _egg_line = (f"현재: **{EGG[_ei][0]} 부근 — 금리 정체로 방향 미확정**  \n"
                             f"금리가 어느 쪽으로 움직이느냐에 따라 {' 또는 '.join(_nb)} 로 갈립니다. "
                             f"지금은 달걀보다 위 두 렌즈를 우선해 보세요.")
            else:
                # 달걀은 6개월이 횡보면 12개월로 판정한다. 위 '방향'(6개월)과 달라 보일 수
                # 있으므로 어느 창을 썼는지 밝힌다.
                _win = ("6개월은 횡보지만 12개월 기준으로는 방향이 잡혀 이렇게 봅니다. "
                        if _RG['rate_dir'] == '횡보' else "")
                _egg_line = f"현재: **{EGG[_ei][1]}** — {_win}{EGG[_ei][2]}"
            _egg_head, _, _egg_rest = _egg_line.partition('  \n')
            st.caption(_egg_head)
            with st.expander("판정 근거"):
                st.caption(f"금리 {_MI.get('fed','-')}% = 최근 10년 분포의 {_MI.get('fed_pct','-')}% 지점  \n"
                           f"6개월 {_MI.get('fed_6m','-')}%p · 12개월 {_MI.get('fed_12m','-')}%p "
                           f"→ 방향 **{_RG['rate_dir']}**"
                           + (f"  \n{_egg_rest}" if _egg_rest else ""))

    with _L3.container(border=True):
        st.markdown("##### ⏳ 하워드 막스 시계추")
        st.caption("남들이 얼마나 **겁먹었나** — 역발상 눈금")
        _p = _RG['pend']
        if _p is None:
            st.caption("위험지표 조회 실패 — 판정 불가")
        else:
            _plab = ('극도의 공포' if _p < 15 else '공포' if _p < 35 else
                     '중립' if _p < 65 else '탐욕' if _p < 85 else '극도의 탐욕')
            _pcol = '#2a78d6' if _p < 35 else ('#52514e' if _p < 65 else '#d03b3b')
            st.markdown(
                f"<div style='margin:10px 0 2px'>"
                f"<div style='font-size:38px;font-weight:800;line-height:1.05;color:{_pcol}'>{_p}"
                f"<span style='font-size:15px;font-weight:600;color:#898781'> / 100</span></div>"
                f"<div style='font-size:16px;font-weight:700;color:{_pcol};margin-top:2px'>{_plab}</div>"
                f"<div style='position:relative;height:14px;border-radius:7px;margin-top:14px;"
                f"background:linear-gradient(90deg,#2a78d6,#eeeeec 50%,#d03b3b)'>"
                f"<div style='position:absolute;left:calc({_p}% - 3px);top:-5px;width:6px;height:24px;"
                f"background:#0b0b0b;border:2px solid #fff;border-radius:3px'></div></div>"
                f"<div style='display:flex;justify-content:space-between;font-size:12px;color:#898781;"
                f"margin-top:6px'><span>공포</span><span>중립</span><span>탐욕</span></div></div>",
                unsafe_allow_html=True)
            st.caption("오른쪽일수록 남들이 낙관적 → 기대수익은 낮다.")
            with st.expander("판정 근거"):
                st.caption(f"HY 스프레드 {_MI.get('hy','-')}% (하위 {_MI.get('hy_pct','-')}%)  \n"
                           f"VIX {_MI.get('vix','-')} (하위 {_MI.get('vix_pct','-')}%)  \n"
                           f"S&P 52주 위치 {_PX.get('pos52','-')}%")
                st.caption("막스: *\"남들이 겁 없이 사는 곳에서 조심하고, "
                           "아무도 안 사는 곳에서 사라.\"*")

    # ── ③ 사이클 궤적 ────────────────────────────────────────────
    st.divider()
    st.subheader("🌀 사이클 궤적 — 지난 2년 어디서 어디로 왔나")
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
            st.plotly_chart(_fig_cy, use_container_width=True)
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
    st.divider()
    st.subheader("🚨 전이 감시판 — 무엇이 바뀌면 국면이 넘어가나")
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
            st.dataframe(pd.DataFrame([{
                '상태': ('❓ 자료없음' if t['hit'] is None else
                        (('🔴 발동' if _bad else '🟢 발동') if t['hit'] else
                         ('🟢 아직' if _bad else '⚪ 아직'))),
                '지표': t['name'], '현재': t['cur'], '임계': t['thr']} for t in _rows]),
                use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_rows)))
            for t in _rows:
                if t['hit']:
                    st.caption(f"{'🔴' if _bad else '🟢'} **{t['name']}** — {t['why']}")
    with st.expander("각 방아쇠가 무슨 뜻인지 (전체)"):
        for t in _TR:
            st.markdown(f"- **[{t['side']}] {t['name']}** (현재 {t['cur']} / 임계 {t['thr']}) — {t['why']}")

    st.divider()
    _sig_col = {'🟢 매수우호': '#16a34a', '🟡 중립관망': '#ca8a04', '🔴 위험경계': '#dc2626'}
    st.markdown(
        f"<div style='font-size:13px;color:#6b7280'>참고 — 기존 3단계 신호: "
        f"<b style='color:{_sig_col.get(signal,'#6b7280')}'>{signal}</b> · 현금 권고 {cash_min}~{cash_max}% · "
        f"점수 {score}점 &nbsp;({' · '.join(details)})</div>", unsafe_allow_html=True)

    with st.spinner(""):
        ecb_rate = _fred_latest('ECBDFR')
        boj_rate = _fred_latest('IRSTCI01JPM156N')
        dgs10    = _fred_latest('DGS10')
        dgs2     = _fred_latest('DGS2')
        cpi_yoy_us = _fred_yoy('CPIAUCSL')
        unrate   = _fred_latest('UNRATE')

    spread = round(dgs10 - dgs2, 2) if dgs10 and dgs2 else None

    if all(v is None for v in (fed_rate, ecb_rate, kr_rate, m2_yoy, cpi_yoy_us, unrate)):
        st.warning("⚠️ FRED 데이터 일시 조회 실패 — 신호·차트가 비어 보일 수 있어요. "
                   "잠시 후 새로고침하면 복구됩니다. (실패는 더 이상 캐싱되지 않음)")

    snap_cols = st.columns(7)
    snap_data = [
        ("Fed",    f"{fed_rate:.2f}%" if fed_rate else '-',  '❌' if fed_rate and fed_rate > 4.5 else '✅'),
        ("ECB",    f"{ecb_rate:.2f}%" if ecb_rate else '-',  '❌' if ecb_rate and ecb_rate > 3.5 else '✅'),
        ("BoK",    f"{kr_rate:.2f}%"  if kr_rate  else '-',  '⚠️'),
        ("M2 YoY", f"{m2_yoy:+.1f}%" if m2_yoy is not None else '-',  '✅' if m2_yoy is not None and m2_yoy >= 5 else ('❌' if m2_yoy is not None and m2_yoy < 0 else '⚠️')),
        ("10Y-2Y", f"{spread:+.2f}%"  if spread is not None else '-',  '🔴' if spread is not None and spread < 0 else '✅'),
        ("CPI YoY",f"{cpi_yoy_us:+.1f}%" if cpi_yoy_us is not None else '-', '✅' if cpi_yoy_us is not None and cpi_yoy_us < 3 else '❌'),
        ("실업률", f"{unrate:.1f}%"   if unrate   else '-',  '✅'),
    ]
    for col, (label, val, flag) in zip(snap_cols, snap_data):
        col.metric(f"{flag} {label}", val)

    st.divider()

    # 개별 지표 차트는 국면 판정의 근거자료 — 기본은 접어두고 필요할 때만 편다.
    with st.expander("📊 상세 지표 차트 — 중앙은행 금리 · 수익률곡선 · CPI · M2 · 주요 지수"):
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
                fig_sp.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                     font=dict(color='#8b949e', size=10),
                                     margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                fig_sp.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
                fig_sp.update_yaxes(gridcolor='rgba(128,128,128,0.2)')
                st.plotly_chart(fig_sp, use_container_width=True)
                if spread is None:
                    st.info("스프레드 계산 불가 (금리 데이터 일시 조회 실패)")
                elif spread < 0:
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
                fig_cpi.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                      font=dict(color='#8b949e', size=10),
                                      margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
                fig_cpi.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
                fig_cpi.update_yaxes(gridcolor='rgba(128,128,128,0.2)', ticksuffix='%')
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
                idx_df.style.map(_ci_chg, subset=['전일대비','YoY']),
                use_container_width=True, hide_index=True,
                row_height=25, height=_dfh(len(idx_df)),
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
                title=dict(text='주요 지수 상대 성과 (1년 전 = 0%)', x=0, xanchor='left'),
                height=314, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#8b949e', size=10),
                margin=dict(l=0,r=0,t=34,b=34),
                legend=dict(orientation='h', y=-0.22, x=0, yanchor='top'),   # 범례 하단 (제목 겹침 방지)
                hovermode='x unified', yaxis_ticksuffix='%',
            )
            fig_idx.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
            fig_idx.update_yaxes(gridcolor='rgba(128,128,128,0.2)')
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
        st.caption("**국면별 대응표** — 현재 국면은 굵게 표시")
        _PLAY = {
            'FIN':  ('20~30%', '🚀주도주 · 🔥상승 상위', '금리민감·성장주. 실적보다 금리 방향'),
            'EARN': ('10~25%', '🚀주도주 · 🏆CANSLIM', '이익 증가·흑자전환. 이 도구가 가장 잘 맞는 구간'),
            'RFIN': ('40~60%', '💎가치 발굴(방어)', '고멀티플 축소·손절 강화. 신규매수 자제'),
            'RERN': ('60~80%', '워치리스트만', '현금 보유. 싸 보이는 게 함정'),
        }
        st.dataframe(pd.DataFrame([{
            '국면': ('▶ ' if k == _RG['phase'] else '  ') + f"{SEASONS[k]['emoji']} {SEASONS[k]['name']}",
            '현금': _PLAY[k][0], '주로 볼 곳': _PLAY[k][1], '요령': _PLAY[k][2]}
            for k in ('FIN', 'EARN', 'RFIN', 'RERN')]),
            use_container_width=True, hide_index=True, row_height=25, height=_dfh(4))
        st.caption(f"⚠️ 위 '권고 현금 {cash_min}~{cash_max}%'는 기존 3단계 신호(금리·M2·지수) 기준이고, "
                   f"국면표의 현금 구간은 사이클 국면 기준이다. **둘이 다르면 보수적인 쪽을 택하라** — "
                   f"현재 국면 {SEASONS[_RG['phase']]['name']} 기준은 {_PLAY[_RG['phase']][0]}. "
                   "두 값이 벌어져 있다는 것 자체가 전환기라는 뜻이다.")


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

def _pf_secrets():
    """st.secrets 는 없을 수도 있다(로컬). 접근 자체가 예외를 던지므로 감싼다."""
    try:
        return st.secrets
    except Exception:
        return None


def _pf_status() -> dict:
    try:
        import portfolio_store
        return portfolio_store.status(_pf_secrets())
    except Exception:
        return {'backend': 'local', 'permanent': False,
                'where': str(PORTFOLIO_FILE), 'label': '🔴 임시 저장'}


def _load_pf() -> list:
    """보유종목 — 영구 저장(GitHub)이 켜져 있으면 그쪽을 진실로 본다."""
    try:
        import portfolio_store
        return portfolio_store.load(_pf_secrets())
    except Exception:
        pass
    if not PORTFOLIO_FILE.exists(): return []
    try: return json.loads(PORTFOLIO_FILE.read_text(encoding='utf-8')).get('positions', [])
    except: return []

def _save_pf(positions: list, note: str = '') -> tuple[bool, str]:
    """저장하고 (영구저장됐는가, 메시지)를 돌려준다. 화면이 사실대로 말할 수 있게."""
    try:
        import portfolio_store
        return portfolio_store.save(positions, _pf_secrets(), note)
    except Exception as e:
        PORTFOLIO_FILE.parent.mkdir(exist_ok=True)
        data = {'updated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'positions': positions}
        PORTFOLIO_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return False, f'로컬에만 저장됨 ({type(e).__name__})'



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

        earn = {'annual': None, 'quarterly': None, 'naver': None}
        insid = fin_est = None
        yf_sym = f"{code}.KS" if is_kr else sym
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

        return hist, info, earn, insid, fin_est
    except Exception as e:
        return None, {}, None, None, None


@st.cache_data(ttl=6 * 3600)
def _official_cached(sym, is_kr):
    rows = _official_fetch(sym, is_kr)
    if not rows:
        raise RuntimeError('empty financials')   # 빈 결과는 캐시하지 않음
    return rows


def official_financials(sym, is_kr):
    """공식 재무제표: KR=DART, US=EDGAR. 실패/빈 결과는 캐시 안 됨(다음 조회 때 재시도)."""
    try:
        return _official_cached(sym, is_kr)
    except Exception:
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


@st.cache_data(ttl=6 * 3600)
def kr_insiders(sym):
    """KR 내부자(임원·주요주주) 매수/매도 — DART 공식. [{date,name,position,change,holdings}]."""
    try:
        import dart_client
        cc = dart_client.corp_map().get(sym)
        return dart_client.insiders(cc, 10) if cc else []
    except Exception:
        return []


@st.cache_data(ttl=6 * 3600)
def _unified_cached(sym, is_kr, freq):
    """빈 결과는 raise → 캐시 안 됨 (서버 일시 실패가 6시간 눌러붙는 것 방지)."""
    if is_kr:
        import dart_client
        cc = dart_client.corp_map().get(sym)
        rows = dart_client.statements(cc, freq, 5) if cc else []
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


@st.cache_data(ttl=24 * 3600)
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


@st.cache_data(ttl=3 * 3600)
def consensus_scenarios(sym, is_kr):
    """컨센서스 목표주가 BEAR/BASE/BULL + 선행 EPS/PER (yfinance, 불안정)."""
    try:
        yi = yf.Ticker(f"{sym}.KS" if is_kr else sym).info or {}
        return {'bear': yi.get('targetLowPrice'), 'base': yi.get('targetMeanPrice'),
                'bull': yi.get('targetHighPrice'), 'n': yi.get('numberOfAnalystOpinions'),
                'fwd_eps': yi.get('forwardEps'), 'fwd_pe': yi.get('forwardPE')}
    except Exception:
        return {}


@st.cache_data(ttl=6 * 3600)
def _fwd_est_cached(sym, is_kr):
    """올해(0y)/내년(+1y) + 이번분기(0q)/다음분기(+1q) 컨센서스 — 매출·EPS·순이익(EPS×주식수).
    yfinance의 revenue_estimate/earnings_estimate는 연간·분기 행이 같은 표에 같이 들어있음
    (인덱스 '0y'/'+1y'/'0q'/'+1q') — 분기 행은 기존엔 안 읽고 버려지고 있었음. 빈 결과는 캐시 안 함."""
    t = yf.Ticker(f"{sym}.KS" if is_kr else sym)
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


@st.cache_data(ttl=6 * 3600)
def _kr_naver_consensus_cached(sym):
    """KR 컨센서스 폴백 — 네이버 '기업실적분석' (E) 컬럼(증권사 추정 평균).
    yfinance에 없는 영업이익 추정까지 제공. 반환 단위: 원(EPS는 원 그대로).

    이 표엔 연간 (E) 다음에 분기 (E)도 같이 들어있는데(예: ...2025.12, 2026.03, 2026.06(E))
    기존엔 연간 구간만 읽고 분기 구간은 그냥 버려지고 있었음 — 실측(005930)으로 확인.
    분기 (E)는 대개 가장 가까운 미래분기 1개만 나옴 → 0q(이번), 그 다음 것이 있으면 1q(다음)."""
    import re
    from bs4 import BeautifulSoup
    from datetime import datetime as _d
    r = requests.get(f'https://finance.naver.com/item/main.naver?code={sym}',
                     headers={'User-Agent': 'Mozilla/5.0'}, timeout=8)
    soup = BeautifulSoup(r.text, 'html.parser')
    tb = soup.select_one('div.cop_analysis table')
    if tb is None:
        raise RuntimeError('no table')
    heads = [th.get_text(' ', strip=True) for th in tb.select('thead th')]
    dh = [h for h in heads if re.match(r'\d{4}\.\d{2}', h)]
    n_annual = 4 if len(dh) >= 10 else max(len(dh) - 6, 0)
    ynow = _d.now().year
    emap = {}                             # 컬럼 인덱스 → 0y(올해)/1y(내년)/0q(이분기)/1q(다음분기)
    for i, h in enumerate(dh[:n_annual]):
        if '(E)' in h:
            emap[i] = '0y' if int(h[:4]) <= ynow else '1y'
    _q_e_idx = [i for i, h in enumerate(dh[n_annual:], start=n_annual) if '(E)' in h]
    for j, i in enumerate(_q_e_idx[:2]):
        emap[i] = '0q' if j == 0 else '1q'
    if not emap:
        raise RuntimeError('no E cols')

    def _num(s):
        s = s.replace(',', '').strip()
        try:
            return float(s)
        except Exception:
            return None

    out = {}
    for kw, key, mult in [('매출액', 'revenue', 1e8), ('영업이익률', 'opm', 0.01),
                          ('영업이익', 'op_income', 1e8),
                          ('당기순이익', 'net_income', 1e8), ('ROE', 'roe', 0.01),
                          ('부채비율', 'debt_ratio', 0.01), ('EPS', 'eps', 1.0),
                          ('PER', 'per_dir', 1.0), ('PBR', 'pbr_dir', 1.0)]:
        for row in tb.select('tbody tr'):
            th = row.select_one('th')
            if th and kw in th.get_text():
                vals = [_num(td.get_text(strip=True)) for td in row.select('td')]
                for i, lab in emap.items():
                    if i < len(vals) and vals[i] is not None:
                        out[f'{key}_{lab}'] = vals[i] * mult
                break
    if not out:
        raise RuntimeError('empty')
    return out


def forward_estimates(sym, is_kr):
    """올해E/내년E 컨센서스 — US=yfinance, KR=yfinance→네이버 폴백(영업이익 포함)."""
    out = {}
    try:
        out = dict(_fwd_est_cached(sym, is_kr))
    except Exception:
        out = {}
    if is_kr:
        try:
            for k, v in _kr_naver_consensus_cached(sym).items():
                out.setdefault(k, v)      # yfinance 값 우선, 빈 곳만 네이버로 보충
        except Exception:
            pass
    return out


@st.cache_data(ttl=12 * 3600)
def company_profile(sym, is_kr):
    """기업 개요: 사업설명·경영진·홈페이지·공식공시 링크(EDGAR/DART/Form4)."""
    out = {'summary': None, 'officers': [], 'website': None,
           'edgar_url': None, 'form4_url': None, 'dart_url': None}
    try:
        yi = yf.Ticker(f"{sym}.KS" if is_kr else sym).info or {}
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


@st.cache_data(ttl=24 * 3600)
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


with tab7, guard('종목 분석'):
    st.header("🔍 종목 분석")
    st.caption("US: TSLA · AAPL · NVDA  |  KR: 005930 또는 005930.KS")

    c_in, c_btn, _csp = st.columns([2.2, 0.9, 4.9])   # 필요한 만큼만 좁게 (#3)
    with c_in:
        sym8 = st.text_input("종목코드", placeholder="TSLA / 005930",
                             label_visibility="collapsed", key="sym8")
    with c_btn:
        go8 = st.button("분석", use_container_width=True, key="go8")

    # 분석 종목을 세션에 고정 — 라디오/슬라이더 조작(rerun)에도 분석 화면 유지 (#7)
    if sym8 and go8:
        st.session_state['analyze_sym'] = sym8.strip().upper()
    _asym = st.session_state.get('analyze_sym')

    if _asym:
        sym8_clean = _asym
        with st.spinner(f"{sym8_clean} 데이터 조회..."):
            # 최대한 길게 요청 — US(FDR)는 상장일까지 실제로 나옴(AAPL 1980~ 확인).
            # KR은 무료소스(FDR/pykrx 비로그인) 자체가 최근 ~3000거래일(~12y)로 캡핑돼 있어
            # 20y를 요청해도 KR은 그 한계까지만 나옴 — 아래 캡션에서 사실대로 안내.
            hist, info, earn, insid, fin_est = fetch_stock_data(sym8_clean, 365 * 20)

        if hist is None or hist.empty:
            st.error(f"데이터 없음 ({sym8_clean}). 종목코드 확인 — KR: 005930 · US: TSLA")
        else:
            price_now = hist['Close'].iloc[-1]
            price_prev= hist['Close'].iloc[-2] if len(hist) > 1 else price_now
            chg_pct   = (price_now / price_prev - 1) * 100

            h1, h2, h3, h4, h5 = st.columns(5)
            h1.metric("종목명", info.get('longName', sym8_clean)[:20])
            h2.metric("현재가", f"${price_now:.2f}" if info.get('currency','') != 'KRW' else f"₩{price_now:,.0f}")
            h3.metric("일일대비", f"{chg_pct:+.2f}%")
            mc = info.get('marketCap', 0)
            h4.metric("시가총액", f"${mc/1e9:.1f}B" if mc >= 1e9 else f"${mc/1e6:.0f}M" if mc else "-")
            h5.metric("섹터", info.get('sector', '-'))

            st.divider()

            is_kr_sym = sym8_clean.isdigit() and len(sym8_clean) == 6
            price_unit = '₩' if is_kr_sym else '$'

            st.divider()
            st.markdown("## 🟡 ① 가치 — 뭘 살까 (What to buy)")
            st.caption("기업 개요·경영진·IR · 공식 재무 3표 (DART/EDGAR)")

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
            if st.button("🤖 AI 사업·비전 요약 (Gemini)", key=f"aisum_{sym8_clean}"):
                with st.spinner("공식 문서(10-K/사업설명)에서 비전·마스터플랜 요약 중..."):
                    _btxt = official_business_text(sym8_clean, is_kr_sym)
                    _bsrc = '10-K 공식 사업보고(Item 1~)' if _btxt else '공식 사업설명(yfinance)'
                    st.markdown(ai_business_summary(info.get('longName', sym8_clean),
                                                    _btxt or _prof.get('summary'), _bsrc))
                    st.caption(f"요약 원천: {_bsrc}")
            st.caption("AI 요약 원천: US=최신 10-K 본문(공식), KR=공식 사업설명. "
                       "서버에서 쓰려면 Streamlit Secrets에 GEMINI_KEY 필요.")
            st.divider()

            # ── 📊 공식 재무제표 통합표 (연도 가로 × 3표 세로 · 연간/분기 토글) ──
            _off = official_financials(sym8_clean, is_kr_sym)   # 연간(멀티플·스코어카드용)
            if _off:
                _osrc = 'DART 전자공시' if is_kr_sym else 'SEC EDGAR'
                st.subheader(f"📊 공식 재무제표 ({_osrc})")
                _mc = info.get('marketCap') or 0

                def _amt(v):
                    if v is None:
                        return '-'
                    if is_kr_sym:
                        return f"{v/1e12:.1f}조" if abs(v) >= 1e12 else f"{v/1e8:,.0f}억"
                    return f"${v/1e9:.1f}B" if abs(v) >= 1e9 else f"${v/1e6:,.0f}M"

                def _pct(v):
                    return f"{v*100:.1f}%" if isinstance(v, (int, float)) else '-'


                _freq = st.radio("기준", ["연간", "분기"], horizontal=True, key=f"fin_freq_{sym8_clean}")
                _stm = unified_statements(sym8_clean, is_kr_sym, 'annual' if _freq == "연간" else 'quarter')
                if _stm:
                    for _r in _stm:
                        _rv = _r.get('revenue')
                        _r['gpm'] = (_r['gross'] / _rv) if (_r.get('gross') and _rv) else None
                        _r['opm'] = (_r['op_income'] / _rv) if (_r.get('op_income') and _rv) else None
                        _r['roe'] = (_r['net_income'] / _r['equity']) if (_r.get('net_income') and _r.get('equity')) else None
                        _r['debt_ratio'] = (_r['liabilities'] / _r['equity']) if (_r.get('liabilities') and _r.get('equity')) else None
                    _periods = [r['period'] for r in _stm]
                    _gl = "YoY" if _freq == "연간" else "QoQ"
                    _np = len(_stm)
                    # 증감 컬럼 헤더는 전부 'YoY'/'QoQ'로 보이게 (공백 패딩으로 중복 회피)
                    _dcols = [f'{_gl}{" " * _i}' for _i in range(_np - 1)]

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
                        if _typ == 'eps':
                            return f"{_v:,.2f}" if isinstance(_v, (int, float)) else '-'
                        return _amt(_v)

                    _EST_LABELS = {
                        'annual':  (('내년E', '1y'), ('올해E', '0y')),
                        'quarter': (('다음분기E', '1q'), ('이번분기E', '0q')),
                    }

                    def _stmt_table(title, items, est=None, freq='annual'):
                        _est_pairs = _EST_LABELS[freq]
                        _ecols = [lab for lab, _ in _est_pairs] if est else []   # 미래→과거 방향 통일
                        _rows = []
                        for _it in items:
                            _lab, _key, _typ = _it[0], _it[1], _it[2]
                            _dk = _it[3] if len(_it) > 3 else None   # 직접 추정키(네이버 PER/PBR E 등)
                            _row = {'항목': _lab}
                            if est:                       # 컨센서스(연간=내년/올해, 분기=다음/이번) — mult면 Fwd 멀티플
                                for _el, _sfx in _est_pairs:
                                    if _dk and est.get(f'{_dk}_{_sfx}') is not None:
                                        _dv = est[f'{_dk}_{_sfx}']
                                        _row[_el] = f"{_dv:.1f}x" if _typ == 'mult' else _fmt_v(_dv, _typ)
                                        continue
                                    _ev = est.get(f'{_key}_{_sfx}')
                                    if _typ == 'mult':
                                        _row[_el] = (f"{_mc/_ev:.1f}x" if (_mc and _ev and _ev > 0) else '-')
                                    else:
                                        _row[_el] = _fmt_v(_ev, _typ) if _ev else '-'
                            for _ix in range(_np):
                                _v = _stm[_ix].get(_key)
                                if _typ == 'mult':        # 현재 시총 ÷ 각 기간 실적 (#4)
                                    _row[_periods[_ix]] = (f"{_mc/_v:.1f}x" if (_mc and _v and _v > 0) else '-')
                                    if _ix < _np - 1:
                                        _row[_dcols[_ix]] = '·'
                                else:
                                    _row[_periods[_ix]] = _fmt_v(_v, _typ)
                                    if _ix < _np - 1:    # 사이사이 증감
                                        _row[_dcols[_ix]] = _delta(_v, _stm[_ix + 1].get(_key), _typ)
                            _rows.append(_row)
                        _df = pd.DataFrame(_rows)
                        # 컬럼 순서: 항목, [내년E, 올해E,] p0, YoY, p1, YoY, ..., pN
                        _order = ['항목'] + _ecols
                        for _ix in range(_np):
                            _order.append(_periods[_ix])
                            if _ix < _np - 1:
                                _order.append(_dcols[_ix])
                        _df = _df[_order]
                        def _cgg(v):
                            try:
                                _f = float(str(v).replace('%', '').replace('p', '').replace('+', ''))
                                return 'color:#16a34a' if _f >= 0 else 'color:#dc2626'
                            except Exception:
                                return 'color:#16a34a' if str(v) == '흑전' else ''
                        st.caption(title)
                        _sty = _df.style.map(_cgg, subset=_dcols)
                        if _ecols:
                            _sty = _sty.set_properties(subset=_ecols, color='#79c0ff')
                        # 행높이·표높이 명시 → 세 표의 행간 완전 동일 + 빈 공간 없음 (#1,#2)
                        st.dataframe(_sty, use_container_width=True, hide_index=True,
                                     row_height=25, height=_dfh(len(_df)))

                    # 연간·분기 컨센서스가 같은 소스(yfinance/네이버)의 같은 응답에 함께 들어있어
                    # freq 무관하게 항상 가져오고, 어느 열을 보여줄지만 freq로 고름 (#1: 분기에서도 컨센서스 표시)
                    _est = forward_estimates(sym8_clean, is_kr_sym) or None
                    _est_freq = 'annual' if _freq == "연간" else 'quarter'
                    # 대차 → 손익 → 현금. 멀티플 행: 현재 시총÷각 기간 실적(밴드 감각), E열=Fwd (#4)
                    _stmt_table("① 대차대조표 (E=컨센서스)", [
                                               ('자산', 'assets', 'amt'), ('부채', 'liabilities', 'amt'),
                                               ('자본', 'equity', 'amt'),
                                               ('부채비율', 'debt_ratio', 'pct'),
                                               ('PBR (현시총÷자본)', 'equity', 'mult', 'pbr_dir')],
                                est=_est, freq=_est_freq)
                    _stmt_table("② 손익계산서 (E=컨센서스)", [
                                               ('매출', 'revenue', 'amt'), ('매출총이익', 'gross', 'amt'),
                                               ('GPM', 'gpm', 'pct'), ('영업이익', 'op_income', 'amt'),
                                               ('OPM', 'opm', 'pct'), ('순이익', 'net_income', 'amt'),
                                               ('EPS', 'eps', 'eps'),
                                               ('SG&A', 'sga', 'amt'), ('ROE', 'roe', 'pct'),
                                               ('PER (현시총÷순익)', 'net_income', 'mult', 'per_dir'),
                                               ('PSR (현시총÷매출)', 'revenue', 'mult')],
                                est=_est, freq=_est_freq)
                    _stmt_table("③ 현금흐름표", [('영업활동', 'op_cf', 'amt'), ('투자활동', 'inv_cf', 'amt'),
                                               ('재무활동', 'fin_cf', 'amt'), ('Capex', 'capex', 'amt')])
                    _qn = "3개월 환산" if _freq == "분기" else "회계연도"
                    st.caption(f"출처: {_osrc} 공식({_qn}). Δ=직전 대비 증감({_gl}, 마진·ROE는 %p, 흑전=흑자전환). "
                               "금액 KR=조/억·US=USD. PER/PBR/PSR 행=현재 시총÷각 기간 실적(최신=트레일링, E열=Fwd). "
                               "컨센서스 커버: KR=매출·영업익·OPM·순익·ROE·부채비율·EPS·PER·PBR(네이버) / "
                               "US=매출·순익·EPS(yfinance). ⚠️ 현금흐름·자산 추정치는 애널 컨센서스가 배포되지 않아 '-'.")
                else:
                    st.caption("통합 재무표 데이터 없음 (해당 기준).")

            # ── 🏭 사업부문별 매출 구조 (App Economy Insights 스타일, DART/EDGAR×Gemini) ──
            st.divider()
            st.subheader("🏭 사업부문별 매출 구조 — 이 회사는 어디서 돈을 버나")
            if True:
                _seg_cached = None
                try:
                    import segment_analysis as _sa
                    _seg_cached = _sa.load_cached(sym8_clean)
                except Exception:
                    pass
                _seg_src = 'DART 사업보고서' if is_kr_sym else 'SEC 10-K'
                _seg_go = st.button(f"🔍 사업부문 분석 ({_seg_src} · Gemini · ~15초)", key=f"seg_{sym8_clean}") if not _seg_cached else True
                if _seg_go:
                    with st.spinner(f"{_seg_src}에서 부문별 매출 추출 중..."):
                        try:
                            import segment_analysis as _sa
                            _seg = _seg_cached or _sa.analyze(sym8_clean, is_kr_sym)
                        except Exception as _se:
                            _seg = {'_error': str(_se)[:150]}
                    if not _seg or _seg.get('_error') or not _seg.get('segments'):
                        st.warning(f"부문 데이터 추출 실패 — 사업보고서에 부문표가 없거나 파싱 실패. {(_seg or {}).get('_error','')}")
                    else:
                        _segs = [s for s in _seg['segments'] if s.get('revenue') or s.get('revenue_pct')]
                        # 공시된 부문 이익지표 자동 판별 (회사별로 GP/OP/둘다/없음이 다름 — management approach)
                        _measure = _seg.get('segment_profit_measure')
                        if _measure not in ('gross', 'operating', 'both'):   # 구버전 캐시 폴백
                            _measure = 'operating' if any(s.get('op_income') for s in _segs) else \
                                       ('gross' if any(s.get('gross_profit') for s in _segs) else 'none')
                        # 표시할 이익 필드·라벨을 회사에 맞게 선택 (both면 OP 우선, GP 병기)
                        _pf_key = 'op_income' if _measure in ('operating', 'both') else 'gross_profit'
                        _pf_lab = 'OPM' if _pf_key == 'op_income' else 'GPM'
                        _mlabel = _seg.get('segment_measure_label') or (f"부문 {_pf_lab}" if _measure != 'none' else "부문 마진 미공시")
                        _tot_pf = sum((s.get(_pf_key) or 0) for s in _segs) or None
                        _srows = []
                        for s in _segs:
                            _pf = s.get(_pf_key)
                            _pf_pct = (_pf / _tot_pf * 100) if (_pf and _tot_pf) else None
                            _seg_margin = (_pf / s['revenue'] * 100) if (_pf and s.get('revenue')) else None
                            _srows.append({
                                '사업부문': s['name'],
                                '주요제품': str(s.get('products', ''))[:26],
                                '매출': fmt_cap(s.get('revenue'), 'KR' if is_kr_sym else 'US') if s.get('revenue') else '-',
                                '매출비중%': s.get('revenue_pct'),
                                f'{_pf_lab}(부문마진)': round(_seg_margin, 1) if _seg_margin is not None else None,
                                '이익비중%': round(_pf_pct, 1) if _pf_pct is not None else None,
                            })
                        _segdf = pd.DataFrame(_srows)
                        # 매출 비중 vs 이익 비중 나란히 막대 (핵심 통찰: 둘의 괴리)
                        _fig_seg = go.Figure()
                        _fig_seg.add_trace(go.Bar(
                            y=[r['사업부문'] for r in _srows], x=[r.get('매출비중%') or 0 for r in _srows],
                            name='매출 비중', orientation='h', marker_color='#388bfd',
                            text=[f"{r.get('매출비중%') or 0:.0f}%" for r in _srows], textposition='auto'))
                        if _tot_pf:
                            _fig_seg.add_trace(go.Bar(
                                y=[r['사업부문'] for r in _srows], x=[r.get('이익비중%') or 0 for r in _srows],
                                name=f'{_pf_lab} 이익 비중', orientation='h', marker_color='#f0883e',
                                text=[f"{r.get('이익비중%') or 0:.0f}%" for r in _srows], textposition='auto'))
                        _fig_seg.update_layout(
                            barmode='group', height=max(180, 60 * len(_srows)),
                            paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                            font=dict(color='#8b949e', size=11), margin=dict(l=0, r=10, t=10, b=0),
                            legend=dict(orientation='h', y=1.15, x=0), xaxis_ticksuffix='%')
                        _fig_seg.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
                        st.plotly_chart(_fig_seg, use_container_width=True)
                        st.dataframe(
                            _segdf, use_container_width=True, hide_index=True, height=_dfh(len(_segdf)),
                            column_config={'매출비중%': st.column_config.NumberColumn(format='%.1f%%'),
                                           f'{_pf_lab}(부문마진)': st.column_config.NumberColumn(format='%.1f%%'),
                                           '이익비중%': st.column_config.NumberColumn(format='%.1f%%')})
                        _mnote = {
                            'operating': "이 회사는 부문 **영업이익(OPM)**을 공시 (부문 매출원가 미분리 → GPM 불가)",
                            'gross':     "이 회사는 부문 **매출총이익(GPM)**을 공시 (부문 판관비 미분리 → OPM 불가)",
                            'both':      "이 회사는 부문 GPM·OPM 둘 다 공시 (OPM 표시)",
                            'none':      "⚠️ 이 회사는 부문별 이익을 공시하지 않음 — 매출 비중만 표시",
                        }.get(_measure, '')
                        st.caption(f"📄 {_seg.get('source', 'DART')} · {_seg.get('period', '')} · Gemini 추출 "
                                   f"(원문 대조 권장). {_mnote}. "
                                   "핵심: **매출 비중 ≠ 이익 비중** — 파란막대보다 주황막대가 큰 부문이 진짜 캐시카우. "
                                   f"{('· ' + _seg['note']) if _seg.get('note') else ''}")
                        st.caption("ℹ️ 부문별 공시 이익지표는 회사마다 다름(경영진이 쓰는 지표 공시) — 테슬라類=GPM, 삼성類=OPM. "
                                   "부문 매출 합이 100% 초과 가능(부문간 내부거래 포함).")

            # ── 💵 손익 흐름(Sankey) + 마진 궤적 (App Economy Insights 스타일) ──
            st.divider()
            st.subheader("💵 손익 흐름 — 매출이 순이익까지 어떻게 흐르나")
            _flowq = unified_statements(sym8_clean, is_kr_sym, 'quarter')      # 분기 시계열
            if not _flowq or len(_flowq) < 1:
                _flowq = unified_statements(sym8_clean, is_kr_sym, 'annual')
            if not _flowq:
                st.caption("손익 흐름 데이터 없음.")
            else:
                _uq, _uu = (1e12, '조') if is_kr_sym else (1e9, 'B')
                _seg_for_flow = None
                if is_kr_sym:
                    try:
                        import segment_analysis as _sa2
                        _seg_for_flow = _sa2.load_cached(sym8_clean)
                    except Exception:
                        pass
                _sank = _income_sankey(_flowq[0], _uq, _uu, _seg_for_flow)
                if _sank:
                    st.plotly_chart(_sank, use_container_width=True)
                    st.caption(f"{_flowq[0].get('period','')} 기준 · 초록=이익 흐름 · 빨강=비용 · "
                               f"{'왼쪽 사업부문은 연간 mix를 기간 매출에 적용(예시)' if _seg_for_flow else '매출→순이익 흐름'}. "
                               "이건 '위치'(이번 기간 구조) — 아래 마진 궤적이 '벡터'.")
                # 마진 궤적 스트립
                _mq = [r for r in _flowq if r.get('revenue')][:8][::-1]     # 오래된→최신
                if len(_mq) >= 3:
                    st.markdown("###### 📈 마진 궤적 (GPM·OPM·NPM) — Sankey가 못 보여주는 추이")
                    _mfig = go.Figure()
                    _mx = [r.get('period', '') for r in _mq]
                    for _mk, _mlab, _mc in [('gross', 'GPM', '#79c0ff'), ('op_income', 'OPM', '#f0883e'),
                                            ('net_income', 'NPM', '#56d364')]:
                        _my = [round(r[_mk] / r['revenue'] * 100, 1) if r.get(_mk) and r.get('revenue') else None
                               for r in _mq]
                        _mfig.add_trace(go.Scatter(x=_mx, y=_my, mode='lines+markers', name=_mlab,
                                                   line=dict(color=_mc, width=2.5)))
                    _mfig.update_layout(height=240, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                        font=dict(color='#8b949e', size=11), margin=dict(l=0, r=8, t=34, b=0),
                                        legend=dict(orientation='h', y=1.15, x=0, yanchor='bottom'),
                                        yaxis_ticksuffix='%')
                    _mfig.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
                    _mfig.update_yaxes(gridcolor='rgba(128,128,128,0.2)')
                    st.plotly_chart(_mfig, use_container_width=True)
                    st.caption("절대 매출은 회사 크면 무조건 커짐 — **마진**이 '성장이 이익으로 이어지는가'를 드러냄. "
                               "마진이 우상향이면 규모의 경제/가격결정력 확보, 우하향이면 경쟁심화/원가압박 신호.")

            st.divider()
            st.markdown("## 🏅 CANSLIM 스코어카드 — 종합 판단")
            ret_1m = (price_now / hist['Close'].iloc[-22] - 1) * 100 if len(hist) > 22 else None
            ret_3m = (price_now / hist['Close'].iloc[-66] - 1) * 100 if len(hist) > 66 else None
            ret_6m = (price_now / hist['Close'].iloc[-126] - 1) * 100 if len(hist) > 126 else None
            ret_1y = (price_now / hist['Close'].iloc[-252] - 1) * 100 if len(hist) > 252 else None
            st.caption("가치(C·A) × 가격(L·M) × 정성(N·S·I) 종합")

            # ── 🏅 CANSLIM 스코어카드 (체슬라투자자문 방식) ──
            if _off and len(_off) >= 2:
                _op = [r.get('op_income') for r in _off]

                def _grow_score(cur, base, yrs):
                    """min(25, 성장률% − 5). 체슬리 C·A 방식. base 적자면 흑자전환 처리."""
                    if cur is None or base is None:
                        return None
                    if base <= 0:
                        return 25.0 if cur and cur > 0 else -10.0
                    g = ((cur / base) ** (1 / yrs) - 1) * 100
                    return round(min(25.0, g - 5), 1)

                _nb = min(3, len(_op) - 1)
                _A = _grow_score(_op[0], _op[_nb], _nb)          # A: 영업이익 3년 CAGR
                _C = _grow_score(_op[0], _op[1], 1)              # C: 영업이익 최근 YoY

                # L: 시장대비 6개월 초과수익 (10%p당 +5점)
                _stk6 = (price_now / hist['Close'].iloc[-126] - 1) * 100 if len(hist) > 126 else None
                _mkt6 = None
                try:
                    _idf = fetch_index_history('KS11' if is_kr_sym else 'SPY', 200)
                    if len(_idf) > 127:
                        _mkt6 = (float(_idf.iloc[-1].values[0]) / float(_idf.iloc[-127].values[0]) - 1) * 100
                except Exception:
                    pass
                _exc = (_stk6 - _mkt6) if (_stk6 is not None and _mkt6 is not None) else None
                _L = round(max(0.0, min(25.0, _exc * 0.5)), 1) if _exc is not None else None

                # M: 시장국면
                try:
                    _fr = fetch_fred('FEDFUNDS', 1); _frr = _fr[-1][1] if _fr else None
                    _m2m = fetch_fred('M2SL', 14)
                    _m2yy = round((_m2m[-1][1] / _m2m[-13][1] - 1) * 100, 1) if len(_m2m) >= 13 else None
                    _Mlabel = compute_macro_signal(_frr, _m2yy, fetch_spx_yoy())[0]
                except Exception:
                    _Mlabel = '—'

                # 콤팩트 1행 배치: 총점 | 점수표 | 수익률 | 정성 슬라이더(세로) — #2
                _cc0, _cc2, _cc3, _cc4 = st.columns([0.7, 1.6, 0.9, 1.3])
                _N = _cc4.slider("N 신성장·경영진", 0, 25, 12, key=f"cans_n_{sym8_clean}")
                _S = _cc4.slider("S 자사주·수급", 0, 25, 0, key=f"cans_s_{sym8_clean}")
                _I = _cc4.slider("I 기관 보유증가", 0, 25, 12, key=f"cans_i_{sym8_clean}")

                _parts = [('C', _C, '영업익 최근 YoY − 5'), ('A', _A, '영업익 3년 CAGR − 5'),
                          ('N', float(_N), '신성장·경영진 (입력)'), ('S', float(_S), '자사주·수급 (입력)'),
                          ('L', _L, (f'시장대비 6M {_exc:+.0f}%p' if _exc is not None else '데이터 없음')),
                          ('I', float(_I), '기관 보유증가 (입력)')]
                _total = round(sum(v for _, v, _ in _parts if isinstance(v, (int, float))), 1)
                _grade = ('S' if _total >= 90 else 'A' if _total >= 70 else 'B' if _total >= 50
                          else 'C' if _total >= 30 else 'D')

                _cc0.metric("총점", f"{_total:.0f}", help="C+A+N+S+L+I (각 max 25)")
                _cc0.metric("등급", _grade)
                _cc0.caption(f"M: {_Mlabel}")
                _scdf = pd.DataFrame([{'항목': k, '점수': (f"{v:+.1f}" if isinstance(v, (int, float)) else '-'),
                                       '근거': d} for k, v, d in _parts])
                _cc2.dataframe(_scdf, use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_scdf)))
                with _cc3:
                    r_df = pd.DataFrame([
                        {'기간': k, '수익률': f"{v:+.1f}%" if v is not None else '-'}
                        for k, v in [('1개월', ret_1m), ('3개월', ret_3m), ('6개월', ret_6m), ('1년', ret_1y)]
                    ])
                    def _cr(v):
                        try:
                            _f = float(str(v).replace('%', '').replace('+', ''))
                            return 'color:#56d364' if _f >= 0 else 'color:#f78166'
                        except Exception:
                            return ''
                    st.dataframe(r_df.style.map(_cr, subset=['수익률']),
                                 use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(r_df)))
                st.caption("체슬리식: C·A=영업이익 성장(공식 DART/EDGAR) · L=시장 상대강도 · "
                           "N·S·I=정성 입력(체슬리 엑셀 방식) · M=시장국면. ⚠️ 점수는 참고용, 정성 판단이 핵심.")
                st.divider()
            st.divider()
            st.markdown("## ⚖️ ② 멀티플 · 컨센서스 — 가격÷가치")
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
            if _off:
                _lt = _off[0]
                def _mult(den):
                    try:
                        return f"{_mc/den:.1f}x" if (_mc and den and den > 0) else '-'
                    except Exception:
                        return '-'
                if _mc:
                    # 멀티플은 살아있는 수치 — 트레일링(최근 확정실적) + Fwd12M(컨센서스) 병기 (#2)
                    _fpe_v = _cons.get('fwd_pe')
                    _per_f = f"{_fpe_v:.1f}x" if _fpe_v else '-'
                    _psr_f = _mult(_fest.get('revenue_1y')) if _fest.get('revenue_1y') else '-'
                    st.markdown(
                        f"⚖️ **멀티플** (실시간 시총 ÷ 실적): "
                        f"PER **{_mult(_lt.get('net_income'))}** <sub>트레일링</sub> / **{_per_f}** <sub>Fwd12M</sub> · "
                        f"PBR **{_mult(_lt.get('equity'))}** · "
                        f"PSR **{_mult(_lt.get('revenue'))}** <sub>트레일링</sub> / **{_psr_f}** <sub>Fwd</sub> "
                        f"<span style='color:#8b949e;font-size:11px'>· 트레일링={_lt['period']} 확정실적 · Fwd=컨센서스 · "
                        f"시총·주가는 실시간</span>",
                        unsafe_allow_html=True)
            # 🎯 컨센서스 BEAR / BASE / BULL (목표주가)
            if _cons.get('base'):
                _cu = '₩' if is_kr_sym else '$'
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
                _fpe = f"{_cons['fwd_pe']:.1f}x" if _cons.get('fwd_pe') else '-'
                st.markdown(
                    f"🎯 **컨센서스 목표주가** · 🐻 BEAR {_pr(_cons.get('bear'))}{_up(_cons.get('bear'))} · "
                    f"⚖️ BASE {_pr(_cons.get('base'))}{_up(_cons.get('base'))} · "
                    f"🐂 BULL {_pr(_cons.get('bull'))}{_up(_cons.get('bull'))} "
                    f"<span style='color:#8b949e;font-size:11px'>· 애널 {_cons.get('n') or '?'}명 · 선행PER {_fpe}</span>",
                    unsafe_allow_html=True)
            else:
                st.caption("🎯 컨센서스: 데이터 없음 (yfinance 제한 · KR 소형주 등).")
            st.divider()
            st.subheader("💹 밸류에이션 · 재무")
            yi2 = {}
            try:
                t_yf = yf.Ticker(f"{sym8_clean}.KS" if is_kr_sym else sym8_clean)
                yi2 = t_yf.info or {}
            except Exception:
                yi2 = {}

            def _pcur(v):   # 통화 포맷
                if v is None: return '-'
                return f"{price_unit}{v:,.0f}" if is_kr_sym else f"${v:.2f}"
            def _fx(v, suffix='', mult=1, dp=1):  # 숫자 포맷 (None 안전)
                if v is None: return '-'
                try: return f"{v*mult:.{dp}f}{suffix}"
                except Exception: return '-'

            _tgt = yi2.get('targetMeanPrice')
            _upside = (_tgt/price_now - 1)*100 if (_tgt and price_now) else None
            _peg = yi2.get('trailingPegRatio') or yi2.get('pegRatio')

            # 지표: (라벨, 표시값)  — 없으면 '-'
            val_rows = [
                ('52주 고점',   _pcur(yr_h)),
                ('52주 저점',   _pcur(yr_l)),
                ('52주 위치',   f"{(price_now-yr_l)/(yr_h-yr_l)*100:.1f}%" if yr_h > yr_l else '-'),
                ('연간 변동성',  _fx(vol_20, '%')),
                ('PER (TTM)',   _fx(yi2.get('trailingPE'), 'x')),
                ('PER (선행)',  _fx(yi2.get('forwardPE'), 'x')),
                ('PBR',         _fx(yi2.get('priceToBook'), 'x')),
                ('PSR',         _fx(yi2.get('priceToSalesTrailing12Months'), 'x')),
                ('PEG',         _fx(_peg, '', dp=2)),
                ('배당수익률',   _fx(yi2.get('dividendYield'), '%', mult=100, dp=2)),
                ('EPS (TTM)',   _fx(yi2.get('trailingEps'), '', dp=2)),
                ('EPS (선행)',  _fx(yi2.get('forwardEps'), '', dp=2)),
                ('ROE',         _fx(yi2.get('returnOnEquity'), '%', mult=100)),
                ('ROA',         _fx(yi2.get('returnOnAssets'), '%', mult=100)),
                ('영업마진',     _fx(yi2.get('operatingMargins'), '%', mult=100)),
                ('순이익률',     _fx(yi2.get('profitMargins'), '%', mult=100)),
                ('매출성장(YoY)', _fx(yi2.get('revenueGrowth'), '%', mult=100)),
                ('부채비율(D/E)', _fx(yi2.get('debtToEquity'), '%')),
                ('애널 목표가',   _pcur(_tgt)),
                ('목표가 여력',   _fx(_upside, '%')),
            ]
            # 2단 분할 — 세로로 긴 표 대신 컴팩트 배치 (#10)
            _vhalf = (len(val_rows) + 1) // 2
            _vc1, _vc2 = st.columns(2)
            _vc1.dataframe(pd.DataFrame([{'지표': k, '값': v} for k, v in val_rows[:_vhalf]]),
                           use_container_width=True, hide_index=True, row_height=25, height=_dfh(_vhalf))
            _vc2.dataframe(pd.DataFrame([{'지표': k, '값': v} for k, v in val_rows[_vhalf:]]),
                           use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(val_rows) - _vhalf))
            st.caption("PER/PBR/PSR·ROE·마진·배당·목표가 = yfinance(무료). KR(.KS)은 일부 항목이 빌 수 있음('-'). "
                       "PEG<1·PBR낮음·ROE높음·부채비율낮음 = 저평가/우량 신호.")


            st.divider()
            st.markdown("## 🔵 ③ 가격 — 언제 살까 (When to buy)")
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

            window60 = hist.tail(60)
            fib_high = window60['High'].max()
            fib_low  = window60['Low'].min()
            fib_lvls = _fib(fib_high, fib_low)

            fig = make_subplots(
                rows=5, cols=1, shared_xaxes=True,
                row_heights=[0.46, 0.135, 0.135, 0.135, 0.135],
                vertical_spacing=0.02,
                subplot_titles=('캔들 · 이동평균 · 피보나치', 'RSI (14)', 'MACD (12·26·9)', '거래량',
                                f'MDD 낙폭 (전고점 대비 %, 조회기간 {(hist.index[-1]-hist.index[0]).days/365.25:.1f}y 기준)'),
            )
            disp = hist                                   # 전체 5y — 차트 기간버튼으로 직접 조절 (#2)


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

            # MDD 낙폭(underwater): 전고점(5y 누적 최고 종가) 대비 %
            _dd = (disp['Close'] / disp['Close'].cummax() - 1) * 100
            fig.add_trace(go.Scatter(
                x=disp.index, y=_dd, mode='lines', name='낙폭',
                line=dict(color='#f78166', width=1.2),
                fill='tozeroy', fillcolor='rgba(247,129,102,0.25)', showlegend=False,
                hovertemplate='낙폭: %{y:.1f}%<extra></extra>',
            ), row=5, col=1)
            _dd_1y = float(_dd.tail(252).min()) if len(_dd) else 0.0
            fig.add_hline(y=_dd_1y, line_color='rgba(240,192,64,0.5)', line_dash='dot',
                          annotation_text=f' 1y MDD {_dd_1y:.0f}%',
                          annotation_position='right', row=5, col=1)

            fig.update_layout(
                height=900, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#8b949e', size=11),
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=100, t=30, b=0),
                legend=dict(orientation='h', y=1.02, x=0),
            )
            # 기간 버튼(1m·6m·YTD·1y·3y·전체) — 셀렉트박스 대신 차트에서 직접 조절 (#2)
            fig.update_layout(xaxis=dict(rangeselector=dict(
                buttons=[dict(count=1, label='1m', step='month', stepmode='backward'),
                         dict(count=6, label='6m', step='month', stepmode='backward'),
                         dict(count=1, label='YTD', step='year', stepmode='todate'),
                         dict(count=1, label='1y', step='year', stepmode='backward'),
                         dict(count=3, label='3y', step='year', stepmode='backward'),
                         dict(step='all', label='전체')],
                bgcolor='rgba(30,35,42,0.9)', activecolor='rgba(56,139,253,0.6)',
                font=dict(color='#c9d1d9', size=11), y=1.08)))
            if len(hist) > 252:                           # 초기 화면은 최근 1년
                fig.update_xaxes(range=[hist.index[-252], hist.index[-1]], row=1, col=1)
            for i in range(1, 6):
                fig.update_xaxes(gridcolor='rgba(128,128,128,0.2)', row=i, col=1)
                fig.update_yaxes(gridcolor='rgba(128,128,128,0.2)', row=i, col=1)
            fig.update_yaxes(title_text='RSI', row=2, col=1, range=[0, 100])
            fig.update_yaxes(ticksuffix='%', row=5, col=1)

            st.plotly_chart(fig, use_container_width=True)
            _dd_cur = float(_dd.iloc[-1]) if len(_dd) else 0.0
            _dd_all = float(_dd.min()) if len(_dd) else 0.0
            _yrs = (hist.index[-1] - hist.index[0]).days / 365.25
            st.caption(f"📉 MDD: 현재 낙폭 **{_dd_cur:.1f}%** · 1년 최대 {_dd_1y:.1f}% · 조회기간({_yrs:.1f}년) 최대 {_dd_all:.1f}% — "
                       "역대 낙폭 범위 안에서 현재 위치를 보는 용도 (낙폭 깊다 ≠ 싸다, 추세·펀더멘털과 같이 볼 것).")
            if sym8_clean.replace('.KS','').replace('.KQ','').isdigit() and _yrs < 15:
                st.caption("ℹ️ 한국 종목은 무료 데이터소스 한계로 최근 ~12년까지만 조회됨 (실제 상장일과 무관한 소스 제약)")

            # 📐 피보나치 레벨 (expander 제거 — 바로 표시, #4)
            fib_ext_lvls = _fib_ext(fib_high, fib_low)
            st.markdown("**📐 피보나치 레벨** (최근 60일 기준)")
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
                             row_height=25, height=_dfh(len(ret_df)))

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
                    ext_df.style.map(_color_ext, subset=['현재 대비']),
                    use_container_width=True, hide_index=True,
                    row_height=25, height=_dfh(len(ext_df)),
                )

            st.divider()

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
                _mclose = _basec.resample('ME').last()
                _mret = (_mclose.pct_change() * 100).dropna()
                if len(_mret) >= 12:
                    _md = _mret.to_frame('ret')
                    _md['y'] = _md.index.year
                    _md['m'] = _md.index.month
                    _pv = _md.pivot_table(index='y', columns='m', values='ret', aggfunc='first')
                    _yret = (_basec.resample('YE').last().pct_change() * 100)
                    _ymap = {d.year: v for d, v in _yret.items()}
                    _moncols = [f'{m}월' for m in range(1, 13)] + ['연간']

                    def _cell(yr, m):
                        if m in _pv.columns and yr in _pv.index and pd.notna(_pv.loc[yr, m]):
                            return float(_pv.loc[yr, m])
                        return None
                    _rows = []
                    for _yr in sorted(_pv.index, reverse=True)[:35]:
                        _row = {'연도': str(int(_yr))}
                        for _m in range(1, 13):
                            _row[f'{_m}월'] = _cell(_yr, _m)
                        _row['연간'] = _ymap.get(_yr)
                        _rows.append(_row)
                    # 하단 요약: 월평균 · 승률
                    _avg = {'연도': '평균'}; _win = {'연도': '승률'}
                    for _m in range(1, 13):
                        _col = _pv[_m].dropna() if _m in _pv.columns else pd.Series(dtype=float)
                        _avg[f'{_m}월'] = float(_col.mean()) if len(_col) else None
                        _win[f'{_m}월'] = float((_col > 0).mean() * 100) if len(_col) else None
                    _avg['연간'] = float(_yret.dropna().mean()) if len(_yret.dropna()) else None
                    _win['연간'] = None
                    _mm = pd.DataFrame(_rows + [_avg, _win])

                    def _cmat(v):
                        try:
                            return 'color:#16a34a;font-weight:bold' if float(v) >= 0 else 'color:#dc2626'
                        except Exception:
                            return ''
                    st.dataframe(
                        _mm.style.map(_cmat, subset=_moncols)
                           .format({c: (lambda v: f'{v:+.0f}' if pd.notna(v) else '·') for c in _moncols}),
                        use_container_width=True, hide_index=True,
                        row_height=25, height=_dfh(len(_mm)))
                    st.caption("연도×월 수익률(%). 하단 **평균**=월별 계절성, **승률**=상승 빈도(%). "
                               "엑셀 '주가 추이 분석' 방식. ⚠️ 표본 적으면 우연 — 기간 '5y' 권장.")
                else:
                    st.info("월별 통계 표본 부족 — 기간을 '3y'나 '5y'로 늘려주세요.")

            with _gcdc:
                st.subheader("⚡ 골든/데드크로스 매매 성과")
                _gpair = st.radio("이평 조합", ["50/200 (정통)", "20/60 (단기)"],
                                  horizontal=True, key="gcdc_pair")
                _ff, _ss = (50, 200) if _gpair.startswith("50") else (20, 60)
                _maf = closes.rolling(_ff).mean()
                _mas = closes.rolling(_ss).mean()
                _rel = (_maf > _mas).astype(float)
                _rel[_maf.isna() | _mas.isna()] = float('nan')
                _cross = _rel.diff()   # +1 골든크로스, -1 데드크로스
                _ent = list(hist.index[_cross == 1])
                _exs = list(hist.index[_cross == -1])
                _trades = []
                for _e in _ent:
                    _later = [x for x in _exs if x > _e]
                    _xd = _later[0] if _later else hist.index[-1]
                    _pe = float(closes.loc[_e]); _px = float(closes.loc[_xd])
                    if _pe > 0:
                        _trades.append({'ret': (_px / _pe - 1) * 100,
                                        'days': (_xd - _e).days,
                                        'open': not _later})
                if _trades:
                    _rets = [t['ret'] for t in _trades]
                    _wins = sum(1 for r in _rets if r > 0)
                    _bh = (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1) * 100
                    _srows = [
                        {'항목': '거래 횟수', '값': f"{len(_trades)}회"},
                        {'항목': '승률', '값': f"{_wins/len(_trades)*100:.0f}%"},
                        {'항목': '평균 수익', '값': f"{sum(_rets)/len(_rets):+.1f}%"},
                        {'항목': '최고 / 최저', '값': f"{max(_rets):+.0f}% / {min(_rets):+.0f}%"},
                        {'항목': '평균 보유', '값': f"{sum(t['days'] for t in _trades)//len(_trades)}일"},
                        {'항목': '비교: 매수후보유', '값': f"{_bh:+.1f}%"},
                    ]
                    st.table(pd.DataFrame(_srows).style.hide(axis="index"))
                    _cur_gc = "🟢 골든(정배열)" if (_rel.iloc[-1] == 1) else "🔴 데드(역배열)"
                    _openmsg = " · 현재 진입 중(미청산)" if _trades[-1]['open'] else ""
                    st.caption(f"현재 상태: **{_cur_gc}**{_openmsg}. 골든크로스 진입→다음 데드크로스 청산 기준 "
                               f"(MA{_ff}/MA{_ss}). ⚠️ 후행지표라 횡보장선 잦은 손실(휩쏘). 추세장에서만 유효.")
                else:
                    st.info(f"교차 신호 없음 — 기간이 짧거나(현 기간 < MA{_ss}) 교차 미발생. '5y'로 늘려보세요.")


            if is_kr_sym:
                _kins = kr_insiders(sym8_clean)
                if _kins:
                    st.subheader("👤 내부자 거래 (DART 공식)")
                    _kidf = pd.DataFrame([{
                        '일자': x['date'], '보고자': x['name'], '직위': x['position'],
                        '구분': '🟢매수' if (x['change'] or 0) > 0 else ('🔴매도' if (x['change'] or 0) < 0 else '변동0'),
                        '증감': f"{x['change']:+,.0f}" if x['change'] is not None else '-',
                        '보유': f"{x['holdings']:,.0f}" if x['holdings'] is not None else '-'}
                        for x in _kins])
                    st.dataframe(_kidf, use_container_width=True, hide_index=True,
                                 row_height=25, height=_dfh(min(len(_kidf), 8)))
                    st.caption("출처: DART 임원·주요주주 특정증권 소유상황보고(공식). 증감>0=취득·<0=처분.")
                else:
                    st.info("내부자 거래 내역 없음 (DART)")
            elif insid is not None and not insid.empty:
                st.subheader("👤 내부자 거래 (SEC Form 4 기반)")
                _uins = []
                for _, _ri in insid.head(10).iterrows():
                    _utxt = str(_ri.get('Text') or '')
                    if 'Sale' in _utxt:
                        _ukind = '🔴 매도'
                    elif 'Purchase' in _utxt or 'Buy' in _utxt:
                        _ukind = '🟢 매수'
                    elif 'onversion' in _utxt or 'xercise' in _utxt:
                        _ukind = '⚙️ 행사/전환'
                    else:
                        _ukind = '-'
                    _ush, _uval = _ri.get('Shares'), _ri.get('Value')
                    _uins.append({'일자': str(_ri.get('Start Date'))[:10],
                                  '보고자': _ri.get('Insider'), '직위': _ri.get('Position'),
                                  '구분': _ukind,
                                  '주수': f"{_ush:,.0f}" if pd.notna(_ush) else '-',
                                  '금액': f"${_uval:,.0f}" if pd.notna(_uval) else '-'})
                _udf = pd.DataFrame(_uins)
                st.dataframe(_udf, use_container_width=True, hide_index=True,
                             row_height=25, height=_dfh(len(_udf)))
                st.caption("출처: yfinance(SEC Form 4 집계). 금액=거래대금(USD). "
                           "정확 대조는 위 '기업 개요'의 EDGAR Form4 링크에서.")



    else:
        st.info("👆 종목코드를 입력하고 분석 버튼을 누르세요\n\n"
                "**US**: TSLA · AAPL · NVDA · MSFT · QCOM\n\n"
                "**KR**: 005930.KS (삼성전자) · 000660.KS (SK하이닉스)")


# ════════════════════════════════════════════════════════════════════
# 탭: 포트폴리오 관리 + 🛡️ 원칙 가드레일
# (2026-07-02 탭 재편 때 대시보드에서 12일간 빠져 있었음 — 2026-07-14 복원 + 준수이력 추가)
# ════════════════════════════════════════════════════════════════════
@st.cache_data(ttl=300)
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


@st.cache_data(ttl=600)
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

with _pf_main, guard('포트폴리오'):
    st.header("💼 포트폴리오 관리")
    update_badge(PORTFOLIO_RESULT)

    # ── 🤖 AI 추천 포트폴리오 (시스템 제안) — 아래 '내 실보유'와 대비 구도 ──
    _wpj = load_json(Path('results/weekly_portfolio.json'))
    if _wpj and _wpj.get('p10'):
        st.subheader("🤖 AI 추천 포트폴리오 — 시스템 제안")
        _ai_opts = ["10선 (집중)", "20선 (분산)"] + (["🔄 역발상 KR (조정장)"] if _wpj.get('ckr') else [])
        _ai_set = st.radio("세트", _ai_opts, horizontal=True, key="ai_pf_set")
        if _ai_set.startswith("🔄"):
            _aip = _wpj['ckr']
            st.info("🔄 **역발상 엔진** — 모멘텀(신고가 추종)이 조정장에서 눈을 감는 결함의 보완. "
                    "'싸고(PER≤15) 돈 잘 벌고(ROE≥8%·영업익 성장) 고점대비 -15~-60% 조정받은' KR 우량주. "
                    "손절 -10% · 목표 +20%. ⚠️ 검증 0일차 — 이 엔진도 성적표에서 똑같이 채점됨.")
        else:
            _aip = _wpj['p10'] if _ai_set.startswith("10") else _wpj['p20']
        _am1, _am2, _am3, _am4 = st.columns(4)
        _am1.metric("기준 주차", _aip.get('week', '-'), help=f"갱신 {_wpj.get('updated', '-')}")
        _am2.metric("💰 포트 내 현금", f"{_aip.get('cash_pct', 0):.0f}%", help="매크로 신호(FRED) 기반 자동 — 표 마지막 행에도 표시")
        _am3.metric("주식 투입", f"{_aip.get('deployed_pct', 0)}%")
        _am4.metric("종목 수", f"{len(_aip.get('positions', []))}개")

        _af1, _af2 = st.columns([1.2, 1])
        _ai_mkt = _af1.radio("시장 필터", ["전체", "KR", "US"], horizontal=True, key="ai_pf_mkt")
        _ai_cap = _af2.selectbox("시총 필터", ["전체", "1조·$1B 이상", "10조·$10B 이상"], key="ai_pf_cap")
        _capmap = _marcap_join()

        def _cap_pass(sym, mkt):
            if _ai_cap == "전체":
                return True
            mc = _capmap.get(sym)
            if not mc:
                return True                      # 시총 미상은 필터로 죽이지 않음
            th = (1e12, 1e9) if _ai_cap.startswith("1조") else (1e13, 1e10)
            return mc >= (th[0] if mkt == 'KR' else th[1])

        _pos_f = [p for p in _aip.get('positions', [])
                  if (_ai_mkt == "전체" or p.get('market') == _ai_mkt)
                  and _cap_pass(p['sym'], p.get('market', 'US'))]

        with st.spinner("현재가·추세 조회 중 (제안 종목)..."):
            _airows = []
            for _p9 in _pos_f:
                _accy = '₩' if _p9.get('market') == 'KR' else '$'
                _acur, _aspark = _px_series(_p9['sym'], _p9.get('market', 'US'))
                _aret = (_acur / _p9['entry'] - 1) * 100 if _acur and _p9.get('entry') else None
                if _acur and _p9.get('stop') and _acur <= _p9['stop']:
                    _ast = '🔴 손절 실행'
                elif _acur and _p9.get('target') and _acur >= _p9['target']:
                    _ast = '🟢 익절 실행'
                else:
                    _ast = '보유'
                _airows.append({
                    '종목': _p9['name'], '시장': _p9.get('market', '-'),
                    '시총': fmt_cap(_capmap.get(_p9['sym']), _p9.get('market', 'US')) if _capmap.get(_p9['sym']) else '-',
                    '비중%': round(_p9.get('weight_pct', 0), 1),
                    '진입가': f"{_accy}{_p9['entry']:,.2f}" if _p9.get('entry') else '-',
                    '현재가': f"{_accy}{_acur:,.2f}" if _acur else '조회실패',
                    '진입대비%': round(_aret, 2) if _aret is not None else None,
                    '추세(45일)': _aspark or None,
                    '손절가': f"{_accy}{_p9['stop']:,.2f}" if _p9.get('stop') else '-',
                    '목표가': f"{_accy}{_p9['target']:,.2f}" if _p9.get('target') else '-',
                    '지시': _ast,
                    '신호': ', '.join(_p9.get('signals', [])[:2]) or '-',
                })
        _airows.append({'종목': '💰 현금', '시장': '-', '시총': '-',
                        '비중%': round(_aip.get('cash_pct', 0), 1),
                        '진입가': '-', '현재가': '-', '진입대비%': None, '추세(45일)': None,
                        '손절가': '-', '목표가': '-', '지시': '대기', '신호': '매크로 신호 기반'})
        _aidf = pd.DataFrame(_airows)
        st.dataframe(
            _aidf, use_container_width=True, hide_index=True, height=_dfh(len(_aidf), cap=760),
            column_config={
                '비중%': st.column_config.NumberColumn('비중%', format='%.1f%%'),
                '진입대비%': st.column_config.NumberColumn('진입대비%', format='%+.2f%%'),
                '추세(45일)': st.column_config.LineChartColumn('추세(45일)', width='medium'),
            })
        if _ai_mkt != "전체" or _ai_cap != "전체":
            st.caption(f"필터 적용 중: {len(_pos_f)}/{len(_aip.get('positions', []))}종목 표시 — 비중%는 원 포트폴리오 기준(재정규화 안 함)")
        st.caption("**이 포트는 원칙의 산출물** — ①선정: 신호 × 실전 신뢰계수(못 하는 신호 자동 감액) "
                   "②비중: 손익비 리스크 사이징 + 종목 캡 ③손절 -7% · 목표 +14% (손익비 2:1 고정) "
                   "④현금: 매크로 신호 자동 ⑤보유 후 매도: 방어손절·분할익절·시간매도 3룰. "
                   "매주 자동 재구성(월 06시) · 성적은 📒 성적표 탭에서 매주 채점됨. "
                   "⚠️ 페이퍼 트랙레코드 검증 중(8/11 첫 판독) — 실투자 근거 아님.")
        st.divider()

    with st.expander("➕ 종목 추가", expanded=False):
        # 저장 위치를 숨기지 않는다 — 트랙레코드는 어디에 남는지가 곧 신뢰다.
        _pfs = _pf_status()
        if _pfs['permanent']:
            st.caption(f"{_pfs['label']} — 저장 위치 `{_pfs['where']}`. "
                       "추가·삭제할 때마다 저장소에 커밋되어 서버가 재시작돼도 남습니다.")
        else:
            st.warning(
                f"{_pfs['label']} — 지금은 `{_pfs['where']}` 에만 저장됩니다. "
                "**영구 저장을 켜려면** GitHub 개인 액세스 토큰(`contents:write`)을 발급해 "
                "Streamlit Cloud → Settings → Secrets 에 `GITHUB_TOKEN` 으로 등록하세요. "
                "토큰은 형이 직접 만들어 넣어야 합니다(제가 대신 만들 수 없습니다). "
                "등록하면 이 문구가 🟢로 바뀌고 추가·삭제가 저장소에 커밋됩니다.")
        fc1, fc2, fc3, fc4, fc5, fc6 = st.columns([2, 1, 1, 1, 1, 1])
        with fc1: p_sym  = st.text_input("티커", key="p_sym", placeholder="TSLA / 005930")
        with fc2: p_name = st.text_input("이름(선택)", key="p_name", placeholder="Tesla")
        with fc3: p_mkt  = st.selectbox("시장", ["US", "KR"], key="p_mkt")
        with fc4: p_qty  = st.number_input("수량", min_value=0.0, step=1.0, key="p_qty")
        with fc5: p_buy  = st.number_input("매수가", min_value=0.0, step=0.01, key="p_buy", format="%.2f")
        with fc6: p_date = st.date_input("매수일", key="p_date")

        fc7, fc8, fc9 = st.columns([1, 1, 2])
        with fc7: p_stop   = st.number_input("손절%", value=7.0, min_value=1.0, max_value=50.0, key="p_stop")
        with fc8: p_target = st.number_input("목표%", value=20.0, min_value=1.0, max_value=500.0, key="p_target")
        with fc9: p_note   = st.text_input("메모", key="p_note", placeholder="52주신고가+이평수렴")

        if st.button("추가", key="p_add"):
            if p_sym and p_buy > 0 and p_qty > 0:
                positions = _load_pf()
                positions.append({
                    'id': f"{p_sym}_{p_date}_{len(positions)}",
                    'sym': p_sym.upper().strip(), 'name': p_name or p_sym.upper(), 'market': p_mkt,
                    'qty': float(p_qty), 'buy_price': float(p_buy), 'buy_date': str(p_date),
                    'stop_loss_pct': float(p_stop), 'target_pct': float(p_target), 'note': p_note,
                })
                _ok, _msg = _save_pf(positions, f"{p_sym.upper()} 추가")
                st.cache_data.clear()
                st.success(f"✅ {p_sym.upper()} 추가 완료 — {_msg}")
                if not _ok:
                    st.session_state['pf_warn'] = _msg
                st.rerun()
            else:
                st.error("티커·매수가·수량을 모두 입력하세요")

    positions = _load_pf()

    if not positions:
        st.info("👆 '종목 추가'에서 보유 종목을 입력하세요\n\n"
                "입력하면 daily-refresh가 매일 현재가 조회 + 손절 경고(텔레그램) + "
                "가드레일 준수 이력을 자동으로 쌓습니다.")
    else:
        with st.spinner("현재가 조회 중..."):
            rows_pf = []
            for pos in positions:
                cur = _fetch_pf_price(pos['sym'], pos.get('market', 'US'))
                buy = float(pos.get('buy_price', 0))
                qty = float(pos.get('qty', 0))
                pnl_pct = (cur / buy - 1) * 100 if cur and buy > 0 else None
                pnl_amt = (cur - buy) * qty if cur and buy > 0 else None
                stop_px = buy * (1 - float(pos.get('stop_loss_pct', 7)) / 100)
                tgt_px  = buy * (1 + float(pos.get('target_pct', 20)) / 100)
                ccy = '₩' if pos.get('market') == 'KR' else '$'
                rows_pf.append({
                    '시장': pos.get('market', 'US'), '종목명': pos.get('name', pos['sym']),
                    '코드': pos['sym'], '수량': qty,
                    '매수가': f"{ccy}{buy:,.2f}", '현재가': f"{ccy}{cur:,.2f}" if cur else '조회실패',
                    '수익률': pnl_pct, 'P&L': pnl_amt,
                    '손절가': f"{ccy}{stop_px:,.2f}", '목표가': f"{ccy}{tgt_px:,.2f}",
                    '매수일': pos.get('buy_date', ''), '메모': pos.get('note', ''),
                    '_id': pos.get('id', ''), '_cur': cur, '_value': (cur * qty) if cur else None, '_qty': qty,
                })

        df_pf = pd.DataFrame(rows_pf)
        valid_pf = [r for r in rows_pf if r['P&L'] is not None]
        if valid_pf:
            total_pnl = sum(r['P&L'] for r in valid_pf)
            total_inv = sum(float(pos.get('buy_price', 0)) * float(pos.get('qty', 0)) for pos in positions)
            total_pnl_pct = total_pnl / total_inv * 100 if total_inv > 0 else 0
            n_profit = sum(1 for r in valid_pf if r['수익률'] and r['수익률'] >= 0)
            n_loss   = len(valid_pf) - n_profit
            n_warn   = sum(1 for r in valid_pf if r['수익률'] and r['수익률'] <= -float(
                next((p['stop_loss_pct'] for p in positions if p['sym'] == r['코드']), 7)))
            m1, m2, m3, m4, m5 = st.columns(5)
            m1.metric("총 손익금액", f"{total_pnl:+,.0f}")
            m2.metric("수익률", f"{total_pnl_pct:+.1f}%")
            m3.metric("수익 종목", f"{n_profit}개")
            m4.metric("손실 종목", f"{n_loss}개")
            m5.metric("⚠️ 손절 경고", f"{n_warn}개",
                      delta="즉시 확인" if n_warn > 0 else None, delta_color="inverse")

        # ── 🛡️ 원칙 가드레일 ──
        st.divider()
        st.subheader("🛡️ 원칙 가드레일")
        st.caption("내가 정한 원칙대로 — 상위 2종목만 20%, 나머지는 더 작게, 30% 넘으면 줄이고, "
                   "레버리지·손절·현금을 기계가 강제합니다. (1억 손실 후 정립한 규칙)")

        with st.expander("⚙️ 원칙 설정 (한 번 정하면 끝)", expanded=False):
            _ga, _gb, _gc = st.columns(3)
            _g_top  = _ga.slider("상위 2종목 최대 비중 %", 10, 30, 20, key="g_top")
            _g_low  = _gb.slider("3위~ 종목 최대 비중 %", 5, 20, 12, key="g_low")
            _g_trim = _gc.slider("자동 축소 임계 %", 20, 50, 30, key="g_trim")
            _gd, _ge, _gf = st.columns(3)
            _g_lev  = _gd.slider("레버리지 합계 한도 %", 0, 50, 10, key="g_lev")
            _g_stop = _ge.slider("손절선 -%", 3, 20, 8, key="g_stop")
            _g_holdval = int(sum(r['_value'] for r in rows_pf if r.get('_value')))
            _g_cap  = _gf.number_input("총 자본(현금 포함, 원) — 현금비중 점검용", min_value=0,
                                       value=_g_holdval, step=1_000_000, key="g_cap",
                                       help="보유 평가액보다 크게 입력하면 그 차액을 현금으로 봅니다")

        try:
            _gfed = fetch_fred('FEDFUNDS', 1); _gfr = _gfed[-1][1] if _gfed else None
            _gm2 = fetch_fred('M2SL', 14)
            _gm2y = round((_gm2[-1][1] / _gm2[-13][1] - 1) * 100, 1) if len(_gm2) >= 13 else None
            _, _gcmin, _gcmax, _, _ = compute_macro_signal(_gfr, _gm2y, fetch_spx_yoy())
        except Exception:
            _gcmin, _gcmax = 25, 40

        _gpos = [{'sym': r['코드'], 'name': r['종목명'], 'market': r['시장'],
                  'value': r['_value'], 'pnl_pct': r['수익률'], 'cur_price': r['_cur'], 'qty': r['_qty']}
                 for r in rows_pf if r.get('_value')]
        try:
            import guardrail as _grd
            _gr = _grd.evaluate(_gpos, total_capital=(_g_cap or None),
                                top_cap=_g_top, lower_cap=_g_low, trim_threshold=_g_trim,
                                lev_cap=_g_lev, stop_pct=_g_stop, cash_min=_gcmin, cash_max=_gcmax)
            _gs = _gr['summary']
            _gx1, _gx2, _gx3, _gx4 = st.columns(4)
            _gx1.metric("원칙 점검", _gr['grade'])
            _gx2.metric("상위2 비중", f"{_gs.get('top2', 0):.0f}%", help=f"한도 {_g_top*2}% (각 {_g_top}%)")
            _gx3.metric("레버리지", f"{_gs.get('lev_pct', 0):.0f}%", help=f"한도 {_g_lev}%")
            _gx4.metric("현금", f"{_gs['cash_pct']:.0f}%" if _gs.get('cash_pct') is not None else "—",
                        help=f"매크로 권고 {_gcmin}~{_gcmax}%")
            if not _gr['violations']:
                st.success("🟢 원칙 준수 중 — 잘하고 있어요. 감정 흔들려도 이 규칙만 지키면 됩니다.")
            else:
                st.error(f"**{_gr['grade']}** — {_gs['msg']}")
                _vrows = [{'': v['sev'], '항목': v['rule'], '조치': v['msg'],
                           '줄일 금액': f"{v['trim_value']:,.0f}원" if v.get('trim_value') else '-',
                           '수량': f"{v['qty_cut']:,.0f}주" if v.get('qty_cut') else '-'}
                          for v in _gr['violations']]
                st.dataframe(pd.DataFrame(_vrows), use_container_width=True, hide_index=True,
                             row_height=25, height=_dfh(len(_vrows)))
                st.caption("⚠️ 자동 주문은 안 합니다 — '무엇을 얼마나' 알려줄 뿐, 실행은 본인이. "
                           "근데 이 지시대로만 하면 6월 같은 일은 안 생겨요.")
        except Exception as _ge2:
            st.caption(f"(가드레일 계산 생략: {_ge2})")

        # ── 🛡️ 가드레일 준수 이력 (daily-refresh가 매일 스냅샷, portfolio_monitor.py) ──
        _ghist = _grd.load_history() if '_grd' in dir() else []
        if _ghist:
            with st.expander(f"📈 가드레일 준수 이력 ({len(_ghist)}일 기록됨)", expanded=False):
                _gstat = _grd.compliance_stats(_ghist)
                _hc1, _hc2, _hc3 = st.columns(3)
                _hc1.metric("최근 30일 준수율", f"{_gstat.get('green_pct', 0):.0f}%",
                            help="🟢(위반 0건)인 날의 비율")
                _hc2.metric("위반 있었던 날", f"{_gstat.get('red_days', 0)}일 / {_gstat.get('n_days', 0)}일")
                _hc3.metric("현재 연속 준수", f"{_gstat.get('cur_streak_green', 0)}일")
                _hdf = pd.DataFrame([{'날짜': r['date'], '등급': r['grade'],
                                      '위반(🔴/🟠)': f"{r.get('n_red',0)}/{r.get('n_org',0)}",
                                      '상위2비중': f"{r.get('top2',0):.0f}%",
                                      '레버리지': f"{r.get('lev_pct',0):.0f}%"}
                                     for r in reversed(_ghist[-30:])])
                st.dataframe(_hdf, use_container_width=True, hide_index=True,
                             row_height=25, height=_dfh(len(_hdf)))
                st.caption("이 표는 종목선정이 아니라 '규칙을 지켰는가'를 채점함 — "
                           "신호 성적표와 같은 원리, 대상만 '나 자신의 규율'.")
        else:
            st.caption("ℹ️ 가드레일 준수 이력 없음 — daily-refresh가 매일 자동으로 쌓기 시작하면 여기 표시됩니다.")

        st.divider()

        def _color_pnl(v):
            if v is None: return ''
            try:
                f = float(v)
                if f >= 10: return 'color:#ff2222;font-weight:bold'
                if f >= 0:  return 'color:#56d364'
                if f >= -7: return 'color:#ffa657'
                return 'color:#ff4444;font-weight:bold'
            except Exception:
                return ''

        def _color_pnl_amt(v):
            if v is None: return ''
            try:
                return 'color:#56d364' if float(v) >= 0 else 'color:#ff4444'
            except Exception:
                return ''

        disp_pf = ['시장', '종목명', '코드', '수량', '매수가', '현재가', '수익률', 'P&L', '손절가', '목표가', '매수일', '메모']
        styled_pf = df_pf[disp_pf].style \
            .map(_color_pnl, subset=['수익률']) \
            .map(_color_pnl_amt, subset=['P&L']) \
            .format({'수익률': lambda v: f"{v:+.1f}%" if v is not None else '-',
                     'P&L': lambda v: f"{v:+,.0f}" if v is not None else '-',
                     '수량': '{:.0f}'})
        st.dataframe(styled_pf, use_container_width=True, hide_index=True,
                     row_height=25, height=_dfh(len(df_pf)))

        # ── 🚨 매도 점검 ──
        st.divider()
        st.subheader("🚨 매도 점검 — 언제 팔까")
        st.caption("보유 종목마다 사전 규칙 3가지로 자동 점검: 방어손절 · 분할익절 · 시간매도.")
        if st.button("🔍 지금 매도 신호 점검 (실시간 ~종목당 2초)", key="sell_check"):
            with st.spinner("매도 신호 분석 중..."):
                try:
                    import sell_signals as _sells
                    _srows = []
                    for pos in positions:
                        _ev = _sells.evaluate_sell(
                            pos['sym'], pos.get('market', 'US'), float(pos.get('buy_price', 0)),
                            buy_date=pos.get('buy_date'),
                            stop_pct=float(pos.get('stop_loss_pct', 8)),
                            target_pct=float(pos.get('target_pct', 20)))
                        _srows.append({'종목': pos.get('name', pos['sym']), '코드': pos['sym'],
                                      '신호': _ev['signal'], '수익률': _ev['pnl_pct'],
                                      '근거': _ev['reason'], '조치': _ev['action']})
                    _sdf = pd.DataFrame(_srows)
                    def _c_sell(v):
                        s = str(v)
                        if '손절' in s: return 'background-color:#5a1a1a;color:white;font-weight:bold'
                        if '익절' in s: return 'color:#56d364;font-weight:bold'
                        if '시간' in s: return 'color:#f0c040'
                        if '보유' in s: return 'color:#7ee787'
                        return 'color:#888'
                    st.dataframe(_sdf.style.map(_c_sell, subset=['신호'])
                                 .format({'수익률': lambda v: f"{v:+.1f}%" if v is not None else '-'}),
                                 use_container_width=True, hide_index=True, row_height=25, height=_dfh(len(_sdf)))
                    _urgent = [r for r in _srows if '손절' in r['신호']]
                    if _urgent:
                        st.error(f"🔴 즉시 점검: {', '.join(r['종목'] for r in _urgent)} — 손절선 이탈")
                    else:
                        st.success("✅ 손절 위반 없음 — 이기는 포지션은 그대로 둡니다")
                except Exception as _se:
                    st.error(f"매도 점검 오류: {_se}")

        st.divider()
        col_del1, col_del2 = st.columns([3, 1])
        with col_del1:
            del_name = st.selectbox("종목 삭제", [f"{r['코드']} ({r['종목명']})" for r in rows_pf], key="del_pos")
        with col_del2:
            st.write("")
            if st.button("🗑️ 삭제", key="do_del"):
                del_sym = del_name.split(' ')[0]
                new_pos = [p for p in positions if p['sym'] != del_sym]
                _ok, _msg = _save_pf(new_pos, f"{del_sym} 삭제")
                st.cache_data.clear()
                st.success(f"{del_sym} 삭제 완료 — {_msg}")
                st.rerun()

        if valid_pf:
            st.divider()
            st.subheader("📊 종목별 수익률")
            chart_df = pd.DataFrame([{'종목': r['종목명'], '수익률(%)': r['수익률']}
                                      for r in valid_pf if r['수익률'] is not None]).sort_values('수익률(%)')
            fig_pf = go.Figure(go.Bar(
                x=chart_df['수익률(%)'], y=chart_df['종목'], orientation='h',
                marker_color=['rgba(86,211,100,0.8)' if v >= 0 else 'rgba(247,129,102,0.8)'
                              for v in chart_df['수익률(%)']]))
            fig_pf.add_vline(x=0, line_color='rgba(110,118,129,0.5)')
            fig_pf.update_layout(height=max(200, 40 * len(chart_df)),
                                 paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                 font=dict(color='#8b949e', size=11), margin=dict(l=0, r=60, t=10, b=0),
                                 xaxis_title='수익률(%)')
            fig_pf.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
            fig_pf.update_yaxes(gridcolor='rgba(128,128,128,0.2)')
            st.plotly_chart(fig_pf, use_container_width=True)


        st.divider()
        # 텔레그램 토큰은 gitignore라 클라우드에는 없다 → 버튼을 눌러도 실패만 한다.
        # 눌리는 죽은 버튼 대신 조건을 명시한다.
        _tg_ready = Path('data/.telegram_token').exists() or bool(_get_secret('TELEGRAM_TOKEN'))
        if st.button("📲 지금 텔레그램으로 포트폴리오 전송", key="tg_now", disabled=not _tg_ready):
            import subprocess, sys as _sys
            with st.spinner("전송 중..."):
                result = subprocess.run([_sys.executable, 'portfolio_monitor.py'],
                                        capture_output=True, text=True,
                                        cwd=str(Path(__file__).parent))
            if result.returncode == 0:
                st.success("✅ 텔레그램 전송 완료!")
            else:
                st.error(f"오류: {(result.stderr or result.stdout)[:300]}")
        if not _tg_ready:
            st.caption("🔒 텔레그램 토큰이 없어 비활성화됨 — 로컬에서 `setup_telegram.py` 실행 후 사용하거나, "
                       "클라우드는 Secrets에 `TELEGRAM_TOKEN`·`TELEGRAM_CHAT` 등록. "
                       "(손절 경고 자동 발송은 매일 06:00 GitHub Actions가 따로 처리합니다)")

    # 🧮 포지션 사이징 계산기 — 2026-08-12 ⚡타이밍 발굴에서 이관('얼마나'는 집행 단계)
    st.divider()
    st.markdown("##### 🧮 포지션 사이징 계산기 — 얼마나 살까·어디서 자를까")
    _zc1, _zc2, _zc3, _zc4, _zc5 = st.columns(5)
    _z_cap = _zc1.number_input("투자 자본(원)", min_value=0, value=10_000_000, step=1_000_000, key="sz_cap")
    _z_risk = _zc2.slider("1회 리스크 %", 0.5, 5.0, 1.0, 0.5, key="sz_risk",
                          help="이 매매에서 잃어도 되는 최대 금액 = 자본 × 리스크%")
    _z_entry = _zc3.number_input("진입가", min_value=0.0, value=10000.0, step=100.0, key="sz_entry")
    _z_stop = _zc4.slider("손절 %", 3, 15, 8, key="sz_stop", help="오닐 룰: -7~8%")
    _z_rr = _zc5.slider("손익비 R:R", 1.0, 5.0, 2.0, 0.5, key="sz_rr")
    if _z_entry > 0 and _z_cap > 0:
        _z_stopp = _z_entry * (1 - _z_stop / 100)
        _z_riskamt = _z_cap * _z_risk / 100
        _z_qty = int(_z_riskamt / (_z_entry - _z_stopp)) if _z_entry > _z_stopp else 0
        _z_invest = _z_qty * _z_entry
        _z_target = _z_entry * (1 + _z_stop / 100 * _z_rr)
        _zm1, _zm2, _zm3, _zm4 = st.columns(4)
        _zm1.metric("매수 수량", f"{_z_qty:,}주", f"투입 {_z_invest:,.0f}원")
        _zm2.metric("손절가", f"{_z_stopp:,.0f}", f"-{_z_stop}%")
        _zm3.metric("목표가", f"{_z_target:,.0f}", f"+{_z_stop * _z_rr:.0f}%")
        _zm4.metric("최대 손실", f"{_z_riskamt:,.0f}원", f"자본의 {_z_risk}%")
        if _z_invest > _z_cap:
            st.warning(f"⚠️ 필요 투입({_z_invest:,.0f}원)이 자본을 초과 — 손절폭이 좁아 수량이 과대. "
                       "리스크%를 낮추거나 손절폭을 넓히세요.")
    st.caption("'얼마나'는 감이 아니라 산수: 수량 = (자본×리스크%) ÷ (진입가−손절가). "
               "손익비 2:1 = 손절 -8%면 목표 +16%. 목표 도달 전 추세 꺾이면 룰대로 청산.")




# ── 화면 하단 설정 (사이드바 제거 → 페이지 맨 아래) ───────────────────
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
        st.dataframe(pd.DataFrame([{
            '상태': {'ok': '🟢 정상', 'stale': '🔴 정지', 'missing': '⚫ 없음',
                    'nodate': '⚠️ 날짜없음', 'error': '⚠️ 오류'}[r['state']],
            '데이터': r['label'],
            '마지막 갱신': r['date'] or '-',
            '경과': (f"{max(r['age'], 0)}일" if r['age'] is not None else '-'),
            '갱신 주기': r['cycle'],
            '쓰이는 화면': r['used_by'],
            '만드는 것': f"{r['producer']} ({r['job']})",
        } for r in _DS]), use_container_width=True, hide_index=True,
            row_height=25, height=_dfh(len(_DS)))
        st.caption("‘마지막 갱신’은 **파일 안에 기록된 데이터 날짜**입니다(배포 시각이 아님). "
                   "정지 항목은 매일 06:00 `pipeline_health.py`가 텔레그램으로도 알립니다.")
st.caption("출처: DART·SEC EDGAR(공식 재무) · FinanceDataReader/KRX(가격) · "
           "FRED(매크로) · 네이버금융·yfinance(컨센서스, 참고)")
