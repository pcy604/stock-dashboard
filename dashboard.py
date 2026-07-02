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


# ── 탭 구성 ──────────────────────────────────────────────────────────
tab_screen, tab7, tab4, tab_guru, tab10 = st.tabs([
    "🔎 종목 발굴", "🔍 종목 분석", "🌍 매크로",
    "🎙️ 구루 인사이트", "🧭 프로젝트 종합"
])

# 종목 발굴 — 발굴·분석·추천을 한 탭에 서브탭으로 통합
with tab_screen:
    _GMKT = st.radio("시장", ["전체", "KR", "US"], horizontal=True, key="screen_mkt")

    # ── 매크로 요약 스트립 (구 '오늘의 종합' 카드 이관) ──
    _s_can_h = load_json(CANSLIM_JSON) or {}
    _s_scr_h = load_json(SCREENER_JSON) or {}
    _scr_fh = [s for s in (_s_scr_h.get('stocks') or [])
               if _GMKT == "전체" or s.get('market') == _GMKT]
    try:
        _fed_h = fetch_fred('FEDFUNDS', 1); _fed_r = _fed_h[-1][1] if _fed_h else None
        _m2_h = fetch_fred('M2SL', 14)
        _m2y = round((_m2_h[-1][1] / _m2_h[-13][1] - 1) * 100, 1) if len(_m2_h) >= 13 else None
        _msig, _cmn, _cmx, _, _ = compute_macro_signal(_fed_r, _m2y, fetch_spx_yoy())
    except Exception:
        _msig, _cmn, _cmx = "—", 25, 40
    _hm1, _hm2, _hm3, _hm4 = st.columns(4)
    _hm1.metric("시장 방향", _s_can_h.get('market_dir', '—'))
    _hm2.metric("매크로 신호", _msig)
    _hm3.metric("주봉 신호 종목", f"{len(_scr_fh)}개")
    _hm4.metric("권고 현금", f"{_cmn}~{_cmx}%", help="매크로 위험도 기반 현금 비중 권고 · 상세는 🌍 매크로 탭")

    st.caption("상승 상위(위닝 점수·신호 통합) · CANSLIM · 주도주 · 종목 프로파일 · 자동추천 — 시장 필터는 위 하나로 전 서브탭 공통")
    t_gain, tab3, t_lead, t_prof, tab11 = st.tabs([
        "🔥 상승 상위", "🏆 CANSLIM",
        "🚀 주도주", "🔬 종목 프로파일", "🎯 자동추천"])


# ════════════════════════════════════════════════════════════════════
# 탭: 구루 인사이트 — 투자 유튜브 채널 영상 일일 요약
# ════════════════════════════════════════════════════════════════════
with tab_guru:
    st.header("🎙️ 구루 인사이트")
    st.caption("투자 유튜브 영상 일일 요약 — 핵심 · 언급 종목 · 강조 포인트, 클릭하면 해당 발언 시점으로 점프 (Gemini 분석)")

    def _guru_ts(sec):
        sec = int(sec or 0)
        h, m, s = sec // 3600, (sec % 3600) // 60, sec % 60
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"

    def _guru_pub(iso):
        if not iso:
            return ''
        try:
            from datetime import timezone as _tz
            return datetime.fromisoformat(iso.replace('Z', '+00:00')).astimezone(_tz(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M')
        except Exception:
            return iso[:16].replace('T', ' ')

    with st.expander("➕ 분석 채널 관리 (유튜브 채널 URL로 추가)"):
        import guru_youtube as _gy
        _chfile = Path('data/guru_channels.json')
        _chans_cfg = None
        if _chfile.exists():
            try:
                _chans_cfg = json.loads(_chfile.read_text(encoding='utf-8'))
            except Exception:
                _chans_cfg = None
        if not _chans_cfg:
            try:
                import config as _cfg
                _chans_cfg = [dict(c) for c in _cfg.GURU_CHANNELS]
            except Exception:
                _chans_cfg = []
        st.caption("현재 채널: " + (" · ".join(c['name'] for c in _chans_cfg) or "없음"))
        _ac1, _ac2 = st.columns([2, 3])
        _newname = _ac1.text_input("채널 이름", key="guru_addname", placeholder="예: 연합인포맥스")
        _newurl = _ac2.text_input("채널 URL / @핸들", key="guru_addurl",
                                  placeholder="https://www.youtube.com/@yna_news")
        if st.button("채널 추가", key="guru_addbtn"):
            if not _newname.strip() or not _newurl.strip():
                st.warning("이름과 URL을 모두 입력하세요.")
            else:
                _cid = _gy.resolve_channel_id(_newurl.strip())
                if not _cid:
                    st.error("채널 ID를 찾지 못했습니다. (영상이 아닌 '채널' URL인지 확인)")
                elif any(c.get('id') == _cid for c in _chans_cfg):
                    st.info(f"이미 등록된 채널입니다 ({_cid}).")
                else:
                    _chans_cfg.append({"name": _newname.strip(), "id": _cid})
                    _chfile.parent.mkdir(parents=True, exist_ok=True)
                    _chfile.write_text(json.dumps(_chans_cfg, ensure_ascii=False, indent=2),
                                       encoding='utf-8')
                    st.success(f"추가됨: {_newname.strip()} ({_cid})")
                    st.info("⚠️ 클라우드 자동 분석에 반영하려면 `data/guru_channels.json` 을 git push 하세요.")
        st.caption("삭제·필터(include/exclude)는 data/guru_channels.json 직접 편집.")

    _GURU_JSON = Path('results/guru_insights.json')
    if not _GURU_JSON.exists():
        st.info("아직 분석된 영상이 없습니다. `python guru_youtube.py` 실행 후 표시됩니다.")
    else:
        try:
            _gdata = json.loads(_GURU_JSON.read_text(encoding='utf-8'))
        except Exception as _e:
            _gdata = {'items': []}
            st.error(f"데이터 로드 실패: {_e}")
        _gitems = _gdata.get('items', [])

        if _gdata.get('updated'):
            st.caption(f"마지막 갱신: {_gdata['updated'][:16].replace('T', ' ')}")

        _gchart = Path('results/guru_chart_latest.png')
        if _gchart.exists():
            st.image(str(_gchart), caption="구루 언급 종목 가격 추이 (최근 5개월)", use_container_width=True)

        if not _gitems:
            st.info("분석된 영상이 없습니다.")
        else:
            _chans = sorted({i['channel'] for i in _gitems})
            _gc1, _gc2, _gc3 = st.columns([1, 2, 1])
            _gsel = _gc1.selectbox("채널", ["전체"] + _chans, key="guru_chan")
            _gq = _gc2.text_input("종목 / 키워드 검색", key="guru_q",
                                  placeholder="예: 테슬라, 엔비디아, 금리").strip()
            _ginv = _gc3.checkbox("투자 영상만", value=True, key="guru_inv")

            _view = _gitems
            if _gsel != "전체":
                _view = [i for i in _view if i['channel'] == _gsel]
            if _ginv:
                _view = [i for i in _view if i.get('analysis', {}).get('relevant', True)]
            if _gq:
                _ql = _gq.lower()
                _view = [i for i in _view
                         if _ql in json.dumps(i.get('analysis', {}), ensure_ascii=False).lower()
                         or _ql in i.get('title', '').lower()]

            st.caption(f"{len(_view)}개 영상")
            for _it in _view:
                _a = _it.get('analysis', {})
                _url = _it['url']
                _tag = "" if _a.get('relevant', True) else "  〔비투자〕"
                _hdr = f"[{_it['channel']}] {_it['title']}  ·  {_guru_pub(_it.get('published', '')) or _it.get('published', '')[:10]} KST{_tag}"
                with st.expander(_hdr):
                    if _a.get('one_liner'):
                        st.markdown(f"**💡 {_a['one_liner']}**")
                    if _a.get('summary'):
                        st.markdown("**핵심 요약**")
                        for _s in _a['summary']:
                            st.markdown(f"- {_s}")
                    if _a.get('tickers'):
                        st.markdown("**📌 언급 종목**  _(시점 클릭 → 영상 점프)_")
                        _mk = {'긍정': '🟢', '부정': '🔴'}
                        for _t in _a['tickers']:
                            _m = _mk.get(_t.get('view', ''), '⚪')
                            _code = f" `{_t['ticker']}`" if _t.get('ticker') else ''
                            _sec = _t.get('t')
                            _jump = f" · [{_guru_ts(_sec)}]({_url}&t={int(_sec)}s)" if _sec else ''
                            st.markdown(f"- {_m} **{_t.get('name','')}**{_code} — {_t.get('context','')}{_jump}")
                    if _a.get('key_points'):
                        st.markdown("**강조 포인트**")
                        for _kp in _a['key_points']:
                            if isinstance(_kp, dict):
                                _sec = _kp.get('t')
                                _jump = f" [{_guru_ts(_sec)}]({_url}&t={int(_sec)}s)" if _sec else ''
                                st.markdown(f"- {_kp.get('point','')}{_jump}")
                            else:
                                st.markdown(f"- {_kp}")
                    if _a.get('actionable'):
                        st.markdown("**✅ 체크 액션**")
                        for _s in _a['actionable']:
                            st.markdown(f"- {_s}")
                    _src = {'transcript': '자막 기반', 'video': '영상 직접 분석', 'fail': '분석 실패'}.get(_it.get('source', ''), '')
                    st.markdown(f"[▶️ 전체 영상]({_url})  ·  <small>{_src}</small>",
                                unsafe_allow_html=True)


@st.cache_data(ttl=1800, show_spinner=False)
def _returns_since(syms_markets, start_date):
    """사용자 지정 시작일~현재 상승률 (라이브 FDR, 캐시). syms_markets=((sym,mkt),...)."""
    import FinanceDataReader as fdr
    from concurrent.futures import ThreadPoolExecutor
    def _one(sm):
        sym, mkt = sm
        try:
            code = sym.replace('.KS', '').replace('.KQ', '')
            fsym = code if mkt == 'KR' else sym
            df = fdr.DataReader(fsym, start_date)
            c = df['Close'].dropna()
            return sym, (round((c.iloc[-1] / c.iloc[0] - 1) * 100, 1) if len(c) >= 2 else None)
        except Exception:
            return sym, None
    out = {}
    with ThreadPoolExecutor(max_workers=8) as ex:
        for sym, v in ex.map(_one, syms_markets):
            out[sym] = v
    return out


# ════════════════════════════════════════════════════════════════════
# 종목 발굴 서브탭 콘텐츠: 주도주(t_lead) · 계절성(t_seas) · MDD 바닥(t_mdd)
# ════════════════════════════════════════════════════════════════════

# ── 🔥 상승 상위 (기간 상승률 + 신호 + CANSLIM + 실적증감 + 계절성) — 주봉 스크리너 통합 ──
with t_gain:
    st.caption("기간별 상승 상위 + 주봉 신호 · CANSLIM · 매출/영업익 증감 · 당월 포함 향후 2개월 계절성. (주봉 스크리너 통합)")
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
        _seasmap = {}
        for s in _seasj.get('stocks', []):
            m = s.get('months', {})
            vals = [m[str(x)]['ret'] for x in (_cmo, _nmo) if m.get(str(x))]
            if vals:
                _seasmap[s['sym']] = round(sum(vals) / len(vals), 1)

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
            cm = _canmap.get(s['sym'], {})
            wm = _winmap.get(s['sym'], {})
            _grows.append({
                '시장': s['market'], '종목': s['name'], '코드': s['sym'],
                '시총': fmt_cap(s.get('marcap'), s['market']),
                '등급': wm.get('grade', '-'),
                '위닝점수': wm.get('score'),
                '신호': ', '.join(pm.get('sigs', [])[:3]) or '-',
                'CANSLIM': f"{cm['score']}/7" if cm.get('score') is not None else '-',
                '매출%': f"{cm['rev']:+.0f}" if isinstance(cm.get('rev'), (int, float)) else '-',
                '영업익%': f"{cm['op']:+.0f}" if isinstance(cm.get('op'), (int, float)) else '-',
                _retc: ret,
                '향후2M계절성': _seasmap.get(s['sym']),
            })
        if _gsort == "위닝점수":
            _grows.sort(key=lambda r: -(r['위닝점수'] if r['위닝점수'] is not None else -999))
        else:
            _grows.sort(key=lambda r: -(r[_retc] if r[_retc] is not None else -999))
        _grows = _grows[:_gn]

        _slab = "위닝점수순" if _gsort == "위닝점수" else f"{_gper}상승순"
        st.subheader(f"🔥 {_gper} 상승 상위 — {len(_grows)}개 · {_slab} ({_cmo}·{_nmo}월 계절성 동반)")
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
                .format({_retc: '{:+.1f}%',
                         '위닝점수': lambda v: f'{v:.1f}' if v is not None else '–',
                         '향후2M계절성': lambda v: f'{v:+.1f}%' if v is not None else '-'}, na_rep='-'),
            use_container_width=True, hide_index=True, height=min(36 + 35 * len(_gdf), 640))
        st.caption("위닝점수=백테스트 샤프 가중 셋업 점수(S≥80·A≥65·B≥50). 신호=주봉(현재). "
                   "CANSLIM·매출/영업익은 KR 한정. 계절성·1주는 perf 기준. "
                   "⚠️ 상승률 상위 = '이미 오른' 종목, 점수 = '셋업의 질'(미래 보장 아님) — 추격 주의, 손익비·가드레일 확인.")


# ── 주도주 (섹터/전체 상대강도) ──
with t_lead:
    st.caption("오닐: 주도주는 주도 섹터와 함께 온다. 신고가에 가장 붙은 + 신호 많은 = 강한 주도주.")
    _lm = _GMKT
    try:
        import leaders as _ld
        _lr = _ld.find_leaders(_lm)
        if not _lr:
            st.error("데이터 없음 → weekly_run.py 실행")
        else:
            if _lr['mode'] == 'sector' and _lr['sectors']:
                for _sec in _lr['sectors']:
                    st.markdown(f"**[{_sec['sector']}]** 섹터RS {_sec['sector_rs']} · 신고가근접 {_sec['near_high_pct']:.0f}% ({_sec['n']}종목)")
                    st.dataframe(pd.DataFrame([{
                        '시장': m['market'], '종목': m['name'], '코드': m['sym'],
                        '시총': fmt_cap(m.get('marcap'), m['market']),
                        'RS': m['_rs'], '신고가거리': f"{m['dist_52w']:+.0f}%" if m.get('dist_52w') is not None else '-',
                        '신호': ', '.join(m['signals'][:3])} for m in _sec['leaders']]),
                        use_container_width=True, hide_index=True)
            else:
                st.info("섹터 데이터가 부족해 전체 상대강도(RS) 랭킹으로 표시합니다.")
                st.dataframe(pd.DataFrame([{
                    '시장': m['market'], '종목': m['name'], '코드': m['sym'],
                    '시총': fmt_cap(m.get('marcap'), m['market']),
                    'RS': m['_rs'], '신고가거리': f"{m['dist_52w']:+.0f}%" if m.get('dist_52w') is not None else '-',
                    '주간%': m.get('pct_change'), '신호': ', '.join(m['signals'][:3])}
                    for m in _lr['top']]),
                    use_container_width=True, hide_index=True, height=560)
    except Exception as _le:
        st.error(f"주도주 오류: {_le}")

# ── 종목 프로파일 (계절성 + MDD 통합) ──
with t_prof:
    st.caption("종목의 과거 통계 성격 — 언제 오르나(계절성) · 얼마나 빠지나(MDD 낙폭)")
    _pmode = st.radio("분석", ["📅 계절성 (월별 강세)", "🔄 MDD 낙폭 (바닥 탐색)"],
                      horizontal=True, key="prof_mode")

    if _pmode.startswith("📅"):
        _seas = load_json(Path('results/seasonality.json'))
        if not _seas or not _seas.get('stocks'):
            st.warning("계절성 데이터 없음 → `python screen_precompute.py` 실행 후 새로고침")
        else:
            st.caption(f"표본 기간: {_seas.get('history', '5년')}  ·  더 깊게: "
                       "`python screen_precompute.py --start 2008-01-01` (수십 년 표본)")
            from datetime import datetime as _dtt
            _smkt = _GMKT
            _c1, _c3 = st.columns(2)
            _mo = _c1.selectbox("월 선택", list(range(1, 13)),
                                index=_dtt.now().month - 1, format_func=lambda x: f"{x}월", key="seas_mo")
            _minwr = _c3.slider("최소 승률 %", 50, 90, 65, key="seas_wr")
            _rows = []
            for s in _seas['stocks']:
                if _smkt != "전체" and s['market'] != _smkt:
                    continue
                md = s['months'].get(str(_mo)) or s['months'].get(_mo)
                if not md or md['n'] < 3 or md['wr'] < _minwr:
                    continue
                _rows.append({'시장': s['market'], '종목': s['name'], '코드': s['sym'],
                              '시총': fmt_cap(s.get('marcap'), s['market']),
                              f'{_mo}월 평균%': md['ret'], '승률%': md['wr'], '표본': md['n']})
            _rows.sort(key=lambda r: -r[f'{_mo}월 평균%'])
            if not _rows:
                st.info("조건에 맞는 종목이 없습니다. 승률 기준을 낮춰보세요.")
            else:
                st.subheader(f"📅 {_mo}월에 강한 종목 — {len(_rows)}개 (승률 {_minwr}%+)")
                _sdf = pd.DataFrame(_rows[:40])
                def _cs(v):
                    try: return 'color:#16a34a;font-weight:bold' if float(v) >= 0 else 'color:#dc2626'
                    except: return ''
                st.dataframe(_sdf.style.map(_cs, subset=[f'{_mo}월 평균%'])
                             .format({f'{_mo}월 평균%': '{:+.1f}%', '승률%': '{:.0f}%'}),
                             use_container_width=True, hide_index=True, height=min(36 + 35*len(_sdf), 600))
                st.caption("⚠️ 계절성은 과거 통계적 경향일 뿐 — 표본 적으면 우연. 보조 지표로만.")

    else:
        _mdd = load_json(Path('results/mdd.json'))
        if not _mdd or not _mdd.get('stocks'):
            st.warning("MDD 데이터 없음 → `python screen_precompute.py` 실행 후 새로고침")
        else:
            _mmkt = _GMKT
            _ddrange = st.slider("현재 고점대비 낙폭 범위 %", -90, 0, (-60, -25), key="mdd_range")
            _rows = []
            for s in _mdd['stocks']:
                if _mmkt != "전체" and s['market'] != _mmkt:
                    continue
                cd = s['cur_dd']
                if cd is None or not (_ddrange[0] <= cd <= _ddrange[1]):
                    continue
                _rows.append({'시장': s['market'], '종목': s['name'], '코드': s['sym'],
                              '시총': fmt_cap(s.get('marcap'), s['market']),
                              '현재가': s['price'], '현재낙폭%': cd,
                              '1년MDD%': s['mdd_1y'], '역대MDD%': s['mdd_all']})
            _rows.sort(key=lambda r: r['현재낙폭%'])
            if not _rows:
                st.info("해당 낙폭 범위 종목이 없습니다.")
            else:
                st.subheader(f"🔄 고점대비 {_ddrange[0]}~{_ddrange[1]}% 빠진 종목 — {len(_rows)}개")
                _mdf = pd.DataFrame(_rows[:50])
                def _cd(v):
                    try:
                        f = float(v)
                        if f <= -50: return 'color:#dc2626;font-weight:bold'
                        if f <= -30: return 'color:#ea580c'
                    except: pass
                    return 'color:#888'
                st.dataframe(_mdf.style.map(_cd, subset=['현재낙폭%', '1년MDD%', '역대MDD%'])
                             .format({'현재낙폭%': '{:.0f}%', '1년MDD%': '{:.0f}%', '역대MDD%': '{:.0f}%'}),
                             use_container_width=True, hide_index=True, height=min(36 + 35*len(_mdf), 600))
                st.caption("⚠️ 바닥은 칼날 — 많이 빠졌다고 사는 게 아니라 실적 개선·턴어라운드 확인 후 진입.")



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
                    .map(color_score3, subset=['점수/7'])
                    .map(color_cell3,  subset=sig3c),
                use_container_width=True,
                height=min(38 + 35 * len(df3), 760),   # 종목 수만큼 길게 (최대 760)
            )

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
                             height=36 + 35 * len(pr_df))


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
        height=height, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
        font=dict(color='#8b949e', size=10),
        margin=dict(l=0, r=0, t=35, b=0),
        legend=dict(orientation='h', y=1.18, x=0),
        hovermode='x unified',
    )
    fig.update_xaxes(gridcolor='rgba(128,128,128,0.2)', showgrid=True)
    fig.update_yaxes(gridcolor='rgba(128,128,128,0.2)', showgrid=True)
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
            fig_sp.update_layout(height=220, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                                 font=dict(color='#8b949e', size=10),
                                 margin=dict(l=0,r=0,t=10,b=0), showlegend=False)
            fig_sp.update_xaxes(gridcolor='rgba(128,128,128,0.2)')
            fig_sp.update_yaxes(gridcolor='rgba(128,128,128,0.2)')
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
            height=280, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
            font=dict(color='#8b949e', size=10),
            margin=dict(l=0,r=0,t=35,b=0),
            legend=dict(orientation='h', y=1.18, x=0),
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
def official_financials(sym, is_kr):
    """공식 재무제표: KR=DART(전자공시), US=EDGAR(SEC). 스크래핑 아님.
    반환: [{period, revenue, op_income, net_income, equity, assets, eps, roe}] 최신순."""
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
                height=780, paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color='#8b949e', size=11),
                xaxis_rangeslider_visible=False,
                margin=dict(l=0, r=100, t=30, b=0),
                legend=dict(orientation='h', y=1.02, x=0),
            )
            for i in range(1, 5):
                fig.update_xaxes(gridcolor='rgba(128,128,128,0.2)', row=i, col=1)
                fig.update_yaxes(gridcolor='rgba(128,128,128,0.2)', row=i, col=1)
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
                        ext_df.style.map(_color_ext, subset=['현재 대비']),
                        use_container_width=True, hide_index=True,
                        height=36 + 35 * len(ext_df),
                    )

            st.divider()

            # ── 📊 공식 재무제표 3표 + 공식 멀티플 (KR=DART / US=EDGAR) ──
            _off = official_financials(sym8_clean, is_kr_sym)
            if _off:
                _osrc = 'DART 전자공시' if is_kr_sym else 'SEC EDGAR'
                st.subheader(f"📊 공식 재무제표 · 연간 ({_osrc})")

                def _amt(v):
                    if v is None:
                        return '-'
                    return f"{v/1e8:,.0f}억" if is_kr_sym else f"${v/1e9:.1f}B"
                def _yoy(cur, prev):
                    if cur is None or not prev:
                        return '-'
                    try:
                        return f"{(cur/prev-1)*100:+.0f}%"
                    except Exception:
                        return '-'

                # 공식 멀티플 = 가격 ÷ 가치 (시총 ÷ 공식 순익/자본/매출) — 두 세계를 잇는 다리
                _lt = _off[0]
                _mc = info.get('marketCap') or 0
                def _mult(den):
                    try:
                        return f"{_mc/den:.1f}x" if (_mc and den and den > 0) else '-'
                    except Exception:
                        return '-'
                if _mc:
                    st.markdown(
                        f"⚖️ **공식 멀티플** (가격÷가치): PER **{_mult(_lt.get('net_income'))}** · "
                        f"PBR **{_mult(_lt.get('equity'))}** · PSR **{_mult(_lt.get('revenue'))}** "
                        f"<span style='color:#8b949e;font-size:11px'>· {_lt['period']} 공식 실적 기준 "
                        f"(적자면 '-')</span>", unsafe_allow_html=True)

                # ① 손익계산서
                _orows = []
                for _i, _r in enumerate(_off):
                    _p = _off[_i + 1] if _i + 1 < len(_off) else {}
                    _orows.append({'연도': _r['period'], '매출': _amt(_r['revenue']),
                                   '매출YoY': _yoy(_r['revenue'], _p.get('revenue')),
                                   '영업익': _amt(_r['op_income']), '순이익': _amt(_r['net_income']),
                                   '순익YoY': _yoy(_r['net_income'], _p.get('net_income')),
                                   'ROE': f"{_r['roe']:.1f}%" if _r['roe'] is not None else '-',
                                   'EPS': f"{_r['eps']:.2f}" if _r.get('eps') is not None else '-'})
                _odf = pd.DataFrame(_orows)
                def _ocg(v):
                    try:
                        return 'color:#16a34a;font-weight:bold' if float(str(v).replace('%', '').replace('+', '')) >= 0 else 'color:#dc2626'
                    except Exception:
                        return ''
                st.caption("① 손익계산서")
                st.dataframe(_odf.style.map(_ocg, subset=['매출YoY', '순익YoY']),
                             use_container_width=True, hide_index=True, height=36 + 35 * len(_odf))

                # ② 대차대조표 · ③ 현금흐름표
                with st.expander("② 대차대조표 · ③ 현금흐름표 (연간)", expanded=False):
                    _bs = pd.DataFrame([{'연도': r['period'], '자산총계': _amt(r.get('assets')),
                                         '부채총계': _amt(r.get('liabilities')), '자본총계': _amt(r.get('equity')),
                                         '부채비율': (f"{r['liabilities']/r['equity']*100:.0f}%"
                                                   if (r.get('liabilities') and r.get('equity')) else '-')}
                                        for r in _off])
                    st.caption("② 대차대조표")
                    st.dataframe(_bs, use_container_width=True, hide_index=True, height=36 + 35 * len(_bs))
                    _cfd = pd.DataFrame([{'연도': r['period'], '영업활동': _amt(r.get('op_cf')),
                                          '투자활동': _amt(r.get('inv_cf')), '재무활동': _amt(r.get('fin_cf'))}
                                         for r in _off])
                    st.caption("③ 현금흐름표 (영업>0 & 투자<0 = 건강한 성장기업 신호)")
                    st.dataframe(_cfd, use_container_width=True, hide_index=True, height=36 + 35 * len(_cfd))

                st.caption(f"출처: {_osrc} 공식 제출 재무제표(연결·연간). 무료·공식, 네이버/yfinance 스크래핑 아님. "
                           "금액 KR=억원·US=USD. 멀티플은 현재 시총÷공식 실적.")
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

                st.subheader("📅 실적 (YoY·QoQ 증감)")
                _emode = st.radio("기간", ["연간", "분기"], horizontal=True, key="earn_mode")

                def _growth(cur, prev):
                    try:
                        if cur is None or prev is None or prev == 0 or prev < 0:
                            return None
                        return (cur / prev - 1) * 100
                    except Exception:
                        return None

                _edict = earn if isinstance(earn, dict) else {}
                _edf = _edict.get('annual') if _emode == "연간" else _edict.get('quarterly')
                _naver = _edict.get('naver')
                rows_e = []
                _yoy_lag = 1 if _emode == "연간" else 4   # 연간:1칸전=전년 / 분기:4칸전=전년동기

                if _edf is not None and hasattr(_edf, 'empty') and not _edf.empty:
                    _cols = sorted(_edf.columns, reverse=True)[:7]   # 최신→과거

                    def _cell(keys, col):
                        for k in ([keys] if isinstance(keys, str) else keys):
                            if k in _edf.index:
                                v = _edf.loc[k, col]
                                try:
                                    return float(v) if not pd.isna(v) else None
                                except Exception:
                                    return None
                        return None

                    _revs = [_cell('Total Revenue', c) for c in _cols]
                    _nets = [_cell(['Net Income', 'Net Income Common Stockholders'], c) for c in _cols]
                    for i, c in enumerate(_cols[:6]):
                        yoy = _growth(_nets[i], _nets[i + _yoy_lag]) if i + _yoy_lag < len(_nets) else None
                        qoq = _growth(_nets[i], _nets[i + 1]) if (_emode == "분기" and i + 1 < len(_nets)) else None
                        rows_e.append({'날짜': str(c)[:7], '매출': _b(_revs[i]), '순이익': _b(_nets[i]),
                                       'YoY%': f"{yoy:+.0f}%" if yoy is not None else '-',
                                       'QoQ%': f"{qoq:+.0f}%" if qoq is not None else '-'})

                elif _naver:   # 한국 종목 네이버 폴백 (순이익, 억원)
                    _arr = list(reversed(_naver['annual'] if _emode == "연간" else _naver['quarterly']))
                    _nets = [v for _, v in _arr]
                    for i, (lab, net) in enumerate(_arr[:6]):
                        yoy = _growth(net, _nets[i + _yoy_lag]) if i + _yoy_lag < len(_nets) else None
                        qoq = _growth(net, _nets[i + 1]) if (_emode == "분기" and i + 1 < len(_nets)) else None
                        rows_e.append({'날짜': lab, '매출': '-',
                                       '순이익': f"{net:,.0f}억" if net is not None else '-',
                                       'YoY%': f"{yoy:+.0f}%" if yoy is not None else '-',
                                       'QoQ%': f"{qoq:+.0f}%" if qoq is not None else '-'})

                if rows_e:
                    _cols_show = ['날짜', '매출', '순이익', 'YoY%'] + (['QoQ%'] if _emode == "분기" else [])
                    e_df = pd.DataFrame(rows_e)[_cols_show]
                    def _cg(v):
                        try:
                            return 'color:#56d364' if float(str(v).replace('%','').replace('+','')) >= 0 else 'color:#f78166'
                        except Exception:
                            return ''
                    _gsub = [c for c in ['YoY%', 'QoQ%'] if c in _cols_show]
                    st.table(e_df.style.hide(axis="index").map(_cg, subset=_gsub))
                else:
                    st.info("실적 데이터 없음 (yfinance/네이버 조회 실패)")

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
                st.table(r_df.style.hide(axis="index").map(_cr, subset=['수익률']))

            with right8:
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
                v_df = pd.DataFrame([{'지표': k, '값': v} for k, v in val_rows])
                st.table(v_df.style.hide(axis="index"))
                st.caption("PER/PBR/PSR·ROE·마진·배당·목표가 = yfinance(무료). KR(.KS)은 일부 항목이 빌 수 있음('-'). "
                           "PEG<1·PBR낮음·ROE높음·부채비율낮음 = 저평가/우량 신호.")

                # 영업이익률(OPM) 연도별 추이
                st.subheader("📊 영업이익률(OPM) 추이")
                _pe_rows = []
                _ann = (earn or {}).get('annual') if isinstance(earn, dict) else None
                if _ann is not None and hasattr(_ann, 'empty') and not _ann.empty:
                    def _ac(keys, col):
                        for k in ([keys] if isinstance(keys, str) else keys):
                            if k in _ann.index:
                                v = _ann.loc[k, col]
                                try:
                                    return float(v) if not pd.isna(v) else None
                                except Exception:
                                    return None
                        return None
                    for c in sorted(_ann.columns, reverse=True)[:3]:
                        oi = _ac(['Operating Income', 'Operating Income Or Loss', 'EBIT'], c)
                        rev = _ac('Total Revenue', c)
                        opm = round(oi / rev * 100, 1) if (oi and rev) else None
                        _pe_rows.append({'항목': f'OPM {str(c)[:4]}',
                                         '값': f"{opm:+.1f}%" if opm is not None else '-'})
                if _pe_rows:
                    st.table(pd.DataFrame(_pe_rows).style.hide(axis="index"))
                    st.caption("OPM=영업이익/매출. 최근 3개 회계연도. US 위주(KR은 yfinance 제약으로 빌 수 있음).")
                else:
                    st.caption("OPM 데이터 없음 (yfinance 재무제표 조회 실패 — KR 종목에서 흔함).")

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
                                     height=36 + 35 * min(len(_kidf), 8))
                        st.caption("출처: DART 임원·주요주주 특정증권 소유상황보고(공식). 증감>0=취득·<0=처분.")
                    else:
                        st.info("내부자 거래 내역 없음 (DART)")
                elif insid is not None and not insid.empty:
                    st.subheader("👤 내부자 거래")
                    st.dataframe(insid.head(8), use_container_width=True, hide_index=True)

            # ════════════════════════════════════════════════════════════
            # 📆 월별 상승률 통계 + ⚡ 골든/데드크로스 매매 성과 (item 8)
            # ════════════════════════════════════════════════════════════
            st.divider()
            _mstat, _gcdc = st.columns(2)

            with _mstat:
                st.subheader("📆 월별 상승률 통계")
                _mclose = hist['Close'].resample('ME').last()
                _mret = _mclose.pct_change().dropna() * 100
                if len(_mret) >= 12:
                    _mrows = []
                    for _mo in range(1, 13):
                        _v = _mret[_mret.index.month == _mo]
                        if len(_v) == 0:
                            continue
                        _mrows.append({'월': f"{_mo}월", '평균%': round(float(_v.mean()), 1),
                                       '승률%': round(float((_v > 0).mean() * 100), 0),
                                       '표본': int(len(_v)),
                                       '최고%': round(float(_v.max()), 1),
                                       '최저%': round(float(_v.min()), 1)})
                    _msdf = pd.DataFrame(_mrows)
                    def _cmm(v):
                        try: return 'color:#56d364;font-weight:bold' if float(v) >= 0 else 'color:#f78166'
                        except Exception: return ''
                    st.dataframe(
                        _msdf.style.map(_cmm, subset=['평균%', '최고%', '최저%'])
                            .format({'평균%': '{:+.1f}%', '승률%': '{:.0f}%',
                                     '최고%': '{:+.1f}%', '최저%': '{:+.1f}%'}),
                        use_container_width=True, hide_index=True,
                        height=36 + 35 * len(_msdf))
                    _best = max(_mrows, key=lambda r: r['평균%'])
                    _worst = min(_mrows, key=lambda r: r['평균%'])
                    st.caption(f"과거 {len(_mret)}개월 표본. 강한 달 **{_best['월']}**(평균 {_best['평균%']:+.1f}%), "
                               f"약한 달 **{_worst['월']}**({_worst['평균%']:+.1f}%). "
                               "표본 늘리려면 기간을 '5y'로. ⚠️ 계절성은 통계 경향일 뿐 보조지표.")
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

    elif not sym8:
        st.info("👆 종목코드를 입력하고 분석 버튼을 누르세요\n\n"
                "**US**: TSLA · AAPL · NVDA · MSFT · QCOM\n\n"
                "**KR**: 005930.KS (삼성전자) · 000660.KS (SK하이닉스)")


# ════════════════════════════════════════════════════════════════════
# 탭11: 자동추천 — 일/주/월 + 손익비 리스크 사이징
# ════════════════════════════════════════════════════════════════════
with tab11:
    st.header("🎯 자동추천 — 일·주·월 + 손익비 사이징")
    st.caption("신호 → 종목 → 얼마나 살까 → 어디서 자를까. 손익비(R:R)와 1회 리스크를 정하면 수량·손절·목표가 자동 계산.")

    cc1, cc2, cc3 = st.columns([1.4, 1, 1])
    with cc1:
        ar_tf_label = st.radio("타임프레임", ["주간", "월간", "일간"], horizontal=True, key="ar_tf")
    ar_tf = {"일간": "daily", "주간": "weekly", "월간": "monthly"}[ar_tf_label]
    with cc2:
        ar_cap = st.number_input("투자 자본(원)", min_value=0, value=10_000_000,
                                 step=1_000_000, key="ar_cap")
    ar_mkt = _GMKT
    with cc3:
        ar_n = st.slider("최대 종목수", 3, 20, 10, key="ar_n")

    _tf_def = {"daily": (5, 2.0), "weekly": (7, 2.0), "monthly": (10, 2.5)}[ar_tf]
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1:
        ar_stop = st.slider("손절폭 -%", 2, 25, _tf_def[0], key="ar_stop",
                            help="진입가 대비 손절 거리")
    with rc2:
        ar_rr = st.slider("손익비 1 : ?", 1.0, 5.0, _tf_def[1], 0.5, key="ar_rr",
                          help="목표폭 = 손절폭 × 이 값. 2.0이면 손절 -7%일 때 목표 +14%")
    with rc3:
        ar_risk = st.slider("1회 리스크 %", 0.5, 5.0, 1.0, 0.5, key="ar_risk",
                            help="한 종목이 손절당할 때 잃는 자본 비율. 작을수록 보수적")
    with rc4:
        ar_cash = st.slider("현금 비중 %", 0, 70, 30, key="ar_cash",
                            help="매크로 위험에 따라 현금 보유. 나머지를 종목에 배분")

    ar_entry = False
    if ar_tf == "daily":
        ar_entry = st.checkbox("일봉 진입타이밍 적용 ('진입적정'만, 느림 ~20초)", value=False, key="ar_entry")

    if st.button("🎯 자동추천 생성", type="primary", key="ar_go"):
        with st.spinner("추천 생성 중..."):
            try:
                import auto_recommend
                _summary, _recs = auto_recommend.build_recommendations(
                    timeframe=ar_tf, capital=ar_cap, stop_pct=ar_stop, rr=ar_rr,
                    risk_per_trade=ar_risk, max_positions=ar_n, market_filter=ar_mkt,
                    cash_pct=ar_cash / 100, use_entry_timing=ar_entry,
                )
                st.session_state['ar_result'] = (_summary, _recs)
            except Exception as _e:
                st.error(f"추천 생성 실패: {_e}")
                st.session_state.pop('ar_result', None)

    if 'ar_result' in st.session_state:
        _summary, _recs = st.session_state['ar_result']
        s = _summary
        st.divider()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("손절 / 목표", f"-{s['stop_pct']}% / +{s['target_pct']}%")
        m2.metric("손익비", f"1 : {s['rr']}", help=f"본전 승률 {s['breakeven_wr']}% 이상이면 기대값 +")
        m3.metric("본전 승률", f"{s['breakeven_wr']}%")
        m4.metric("포트폴리오 히트", f"{s['portfolio_heat']}%",
                  help="전 종목이 동시에 손절당할 때 잃는 총 자본 비율")

        if not _recs:
            st.warning("추천 종목이 없습니다. 데이터가 비었거나(스크리너 갱신 필요) 조건이 빡빡합니다.")
        else:
            rows = []
            for r in _recs:
                ccy = '₩' if r['market'] == 'KR' else '$'
                rows.append({
                    '시장': r['market'], '종목': r['name'], '코드': r['sym'],
                    '종합': r.get('total_score'), '기술': r.get('win_score'),
                    '기본': r.get('fund_score'),
                    '신호': ', '.join(r['signals'][:2]),
                    '진입': f"{ccy}{r['entry']:,.0f}" if r['market'] == 'KR' else f"{ccy}{r['entry']:,.2f}",
                    '손절': f"{ccy}{r['stop']:,.0f}" if r['market'] == 'KR' else f"{ccy}{r['stop']:,.2f}",
                    '목표': f"{ccy}{r['target']:,.0f}" if r['market'] == 'KR' else f"{ccy}{r['target']:,.2f}",
                    '수량': f"{r['qty']:,.0f}" if r['market'] == 'KR' else f"{r['qty']:,.2f}",
                    '비중%': r['pos_pct'],
                    '투입금': f"{r['pos_value']:,.0f}",
                    '최대손실': f"{r['risk_amt']:,.0f}",
                    '신뢰계수': r['live_mult'],
                    '진입등급': r.get('entry_grade', ''),
                })
            _ardf = pd.DataFrame(rows)
            _show_cols = ['시장','종목','코드','종합','기술','기본','신호','진입','손절','목표','수량','비중%','투입금','최대손실','신뢰계수']
            if ar_tf == 'daily' and any(r.get('진입등급') for r in rows):
                _show_cols.append('진입등급')

            def _c_mult2(v):
                try:
                    f = float(v)
                    return 'color:#56d364;font-weight:bold' if f >= 1.0 else ('color:#ffa657' if f >= 0.85 else 'color:#f78166')
                except: return ''
            st.dataframe(
                _ardf[_show_cols].style.map(_c_mult2, subset=['신뢰계수'])
                    .format({'비중%': '{:.1f}%', '신뢰계수': '{:.2f}'}),
                use_container_width=True, hide_index=True,
                height=36 + 36 * len(_ardf),
            )

            sc1, sc2, sc3 = st.columns(3)
            sc1.metric("총 투입", f"{s['deployed']:,.0f}원 ({s['deployed_pct']}%)")
            sc2.metric("최대 손실 (전부 손절)", f"-{s['total_risk']:,.0f}원")
            sc3.metric("최대 수익 (전부 목표)", f"+{s['max_reward']:,.0f}원")

            st.caption(
                f"📌 {s['tf_label']} 보유 {s['hold']} · 1회 리스크 {s['risk_per_trade']}% · "
                f"신뢰계수는 페이퍼 트레이딩 실전 성적으로 자동 보정(라쿤 오류수정 루프). "
                f"손익비 1:{s['rr']} → 실제 승률이 {s['breakeven_wr']}%만 넘으면 기대값 +."
            )
            st.info("⚠️ 자동 계산된 제안일 뿐, 매매·책임은 본인. 실투자 전 페이퍼 트레이딩으로 검증 권장.")


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
    with _set2:
        st.write("")
        if st.button("🔄 전체 새로고침", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    st.caption("데이터 갱신은 매일 06:00 자동(GitHub Actions). 수동: weekly_run·perf_run·canslim_run·screen_precompute")

# ── 페이지 최하단: 데이터 출처·업데이트 시각 ──
_foot_upd = max([m for m in (file_mtime(p) for p in [SCREENER_JSON, CANSLIM_JSON, PERF_JSON,
                 Path('results/returns.json'), Path('results/seasonality.json')]) if m], default="—")
st.caption(f"📅 마지막 데이터 업데이트: {_foot_upd} (KST)  ·  자동 갱신 매일 06:00  ·  "
           f"출처: FinanceDataReader(가격)·네이버금융(실적)·FRED(매크로)·KRX/S&P500(섹터)")
