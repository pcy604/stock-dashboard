# -*- coding: utf-8 -*-
"""
verdict.py — '이번 주 판정'의 단일 출처 (2026-10-21)

왜: 같은 판정을 다섯 군데서 따로 계산했다.
  · 화면 매크로 탭 / 발굴 상단 스트립 — FDR SPY 200일선
  · CANSLIM US M — FDR SPY 200일선(같은 계산을 또), CANSLIM KR M — KOSPI 주봉 MA10>MA30(다른 규칙)
  · 시황 리포트 — ^GSPC 200일선(다른 종목)
  · 종목분석 CANSLIM M — 기각된 3단계 매크로 신호(Fed·M2·SPX YoY)
  · 주간 포트폴리오 현금 — 같은 기각 신호로 현금 10~70%
  · executor(자동매매) — VOO **40주선** (원칙 v1.3 은 200일선)
  같은 날 탭마다 다른 답이 나올 수 있었다. 이제 계산은 여기 하나, 나머지는 읽기만 한다.

산출물: results/macro.json (daily-refresh 06:00 KST). 화면은 이 파일을 먼저 읽고,
없거나 낡았으면 같은 함수로 라이브 계산한다 — 계산식이 하나라 둘의 답이 같다.

비중을 바꾸는 확정 규칙은 코어 200일선 스위치 하나다(원칙 v1.3 §3). 위성에는 시장 필터가 없다(§4).
국면·욕심 경고·돈의 흐름·경기는 '참고'다 — 비중에 쓰지 않는다.

  python verdict.py            # results/macro.json 갱신
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, date

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, 'results', 'macro.json')
MA_DAYS = 200                    # 원칙 v1.3 — 길이를 바꿔가며 고르지 않는다(과적합 방지)
CORE_SYM, KR_SYM = 'SPY', 'KS11'


def sleeves() -> dict:
    """목표 배분 — executor/config.json 이 원본(값이 두 곳에 있지 않게)."""
    try:
        cfg = json.load(open(os.path.join(BASE, 'executor', 'config.json'), encoding='utf-8'))
        s = cfg['sleeves']
        return dict(core=round(s['core'] * 100), satellite=round(s['satellite'] * 100), buffer=round(s['buffer'] * 100))
    except Exception:
        return dict(core=50, satellite=30, buffer=20)


def alloc(core_on: bool | None) -> dict:
    """이번 주 목표 비중(%). 스위치 OFF 면 코어 몫이 현금으로 간다. 판정 불가면 직전 상태를 유지하라는 뜻으로 None."""
    s = sleeves()
    if core_on is None:
        return dict(s, core_now=None, cash_total=None)
    core_now = s['core'] if core_on else 0
    return dict(s, core_now=core_now, cash_total=s['buffer'] + (0 if core_on else s['core']))


# ── 200일선 스위치 ───────────────────────────────────────────────────
def _clean(s) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(pd.Series(s), errors='coerce').dropna()
    idx = pd.to_datetime(s.index)
    if getattr(idx, 'tz', None) is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep='last')].sort_index()


def core_switch(closes, n: int = MA_DAYS) -> dict:
    """일봉 종가 → {on, close, ma, gap, date, pos52, mom12}. 데이터 부족이면 {}.
    화면·CANSLIM M·리포트·executor 가 모두 이 함수 하나로 판정한다."""
    c = _clean(closes)
    if len(c) < n + 10:
        return {}
    cur, ma = float(c.iloc[-1]), float(c.tail(n).mean())
    hi, lo = float(c.tail(252).max()), float(c.tail(252).min())
    return dict(on=cur > ma, close=round(cur, 2), ma=round(ma, 2), gap=round((cur / ma - 1) * 100, 2),
                date=c.index[-1].strftime('%Y-%m-%d'),
                pos52=round((cur - lo) / (hi - lo) * 100) if hi > lo else None,
                mom12=round((cur / float(c.iloc[-252]) - 1) * 100, 1) if len(c) >= 252 else None)


def as_price_state(sw: dict) -> dict:
    """옛 macro_price_state() 모양(spx·ma200·above_ma) — 국면 판정(macro_regime)이 이 키를 쓴다."""
    if not sw:
        return {}
    return dict(spx=sw['close'], ma200=sw['ma'], above_ma=sw['on'], pos52=sw.get('pos52'), mom12=sw.get('mom12'))


def market_dir(sw: dict) -> str:
    """CANSLIM M 칸 문구 — KR·US 같은 규칙(지수 200일선)."""
    if not sw:
        return '판단불가'
    return f"{'상승추세 ✅' if sw['on'] else '하락추세 ⚠️'} (200일선 {sw['gap']:+.1f}%)"


def daily_closes(sym: str, days: int = 420) -> pd.Series:
    """배치용 일봉 종가. 1순위 FinanceDataReader(화면과 같은 소스) → 2순위 Yahoo v8."""
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(sym, (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'))
        s = _clean(df['Close'])
        if len(s) > MA_DAYS:
            return s
    except Exception:
        pass
    try:
        import urllib.request
        ysym = {'KS11': '^KS11', 'KQ11': '^KQ11'}.get(sym, sym)
        url = f"https://query2.finance.yahoo.com/v8/finance/chart/{ysym}?range=2y&interval=1d"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}),
                                              timeout=20).read())['chart']['result'][0]
        q = r['indicators']['quote'][0]['close']
        return _clean(pd.Series(q, index=pd.to_datetime(r['timestamp'], unit='s')))
    except Exception:
        return pd.Series(dtype=float)


# ── 사이클 지도(참고) — 2026-10-21 dashboard.py 에서 이관 ──────────────
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


def macro_inputs(fetch_fred):
    """국면 판정용 원지표를 한 번에 수집. 실패 항목은 None으로 남기고 나머지로 진행한다.
    fetch_fred(series_id, n) -> [(date, value)] 오름차순 — 화면은 캐시 버전, CI 는 fred_fetch()."""
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


# 우라가미 구미오 4계절 — (금리 방향 × 실적 방향 × 주가 추세)
SEASONS = {
    'FIN':  dict(emoji='🌱', name='금융장세', sub='유동성이 끌어올리는 장 (봄)',
                 desc='실적은 아직 나쁜데 금리가 내려가며 돈이 먼저 들어온다. 밸류에이션이 먼저 오른다.',
                 works='금리민감·성장주·소외 대형주. 실적보다 "금리 방향"이 주가를 정합니다.',
                 fails='실적 기준 종목 선별. 지금 좋은 실적은 이미 과거다.'),
    'EARN': dict(emoji='☀️', name='실적장세', sub='펀더멘털이 끌어올리는 장 (여름)',
                 desc='금리가 올라도 이익이 더 빨리 는다. 이익이 나오는 종목만 오른다.',
                 works='이익 증가·흑자전환·주도주. 이 도구의 🚀주도주·🏆CANSLIM이 가장 잘 맞는 구간.',
                 fails='유동성만 보고 사는 저가 매수. 이익 없는 종목은 여기서 걸러집니다.'),
    'RFIN': dict(emoji='🍂', name='역금융장세', sub='긴축이 눌러 내리는 장 (가을)',
                 desc='이익은 아직 괜찮은데 금리·긴축이 멀티플을 깎는다. 좋은 실적에도 주가가 안 간다.',
                 works='현금 비중 확대·손절 규율. 고PER·고PSR 축소.',
                 fails='"실적 좋으니 괜찮다"는 논리. 이 국면에서 깨지는 대표적 착각입니다.'),
    'RERN': dict(emoji='❄️', name='역실적장세', sub='이익이 무너지는 장 (겨울)',
                 desc='금리는 내려오는데 이익이 더 빨리 무너집니다. 싸 보이는 게 함정인 구간.',
                 works='현금·채권. 워치리스트 작성. "실탄을 들고 기다리는 것"이 전략입니다.',
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


# ── 두 축(돈의 흐름 · 경기) + 욕심 경고 — 화면과 배치가 같은 함수를 쓴다 ─────────
# (FRED 코드, 받을 개수) — 2026-10-21 dashboard._MO_FRED 에서 이관
MO_FRED = {'ICSA': 70, 'T10Y3M': 5, 'CFNAI': 6, 'NEWORDER': 16, 'XTEXVA01KRM667S': 16, 'GDPNOW': 3,
           'INDPRO': 16, 'PAYEMS': 6, 'UNRATE': 18, 'PCEPILFE': 16, 'CPIAUCSL': 16, 'FEDFUNDS': 9,
           'DGS10': 70, 'WALCL': 30, 'WTREGEN': 30, 'RRPONTSYD': 400, 'DFII10': 70,
           'BAMLH0A0HYM2': 800, 'VIXCLS': 5, 'VXVCLS': 5, 'BAA10Y': 80}


def axes(S: dict, closes: dict, core_on: bool | None, phase: str | None) -> dict:
    """S={FRED코드: Series}, closes={Yahoo심볼: Series}. 축 1·축 2·욕심 경고를 한 번에."""
    import macro_flow as mf
    at = mf.asset_table(closes) if closes else pd.DataFrame()
    flow = mf.flow_verdict(at) if len(at) else dict(word='-', up=0, n=0, risk_up=0, risk_n=0)
    rows = mf.econ_rows(S)
    ew, esub = mf.econ_verdict(rows)
    emp = pd.Series(dtype=float)
    baa = S.get('BAA10Y', emp)
    c1 = float(baa.iloc[-1] - baa.iloc[-66]) if len(baa) > 66 else None
    dx = mf._clean(closes.get('DX-Y.NYB')) if closes else emp
    dxy_gap = mf.ma_gap(dx) if len(dx) else None
    dxy_13 = mf.ret_pct(dx, 63) if len(dx) > 63 else None
    G = mf.greed_signals(core_on, c1, phase, dxy_gap, dxy_13)
    nl = mf.net_liquidity(S.get('WALCL', emp), S.get('WTREGEN', emp), S.get('RRPONTSYD', emp))
    nl13 = (float(nl.iloc[-1]) / float(nl.iloc[-14]) - 1) * 100 if len(nl) > 14 else None
    return dict(at=at, flow=flow, rows=rows, ew=ew, esub=esub, c1=c1, dx=dx, dxy_gap=dxy_gap,
                dxy_13=dxy_13, G=G, nl=nl, nl13=nl13)


# ── 배치(CI) 전용 수집기 ─────────────────────────────────────────────
def fred_fetch(series_id: str, limit: int = 24):
    """dashboard.fetch_fred 와 같은 모양 [(date, value)] 오름차순. 키 없거나 실패면 []."""
    key = os.environ.get('FRED_KEY', '')
    if not key:
        kf = os.path.join(BASE, 'data', '.fred_key')
        key = open(kf, encoding='utf-8').read().strip() if os.path.exists(kf) else ''
    if not key:
        return []
    try:
        import requests
        r = requests.get('https://api.stlouisfed.org/fred/series/observations',
                         params=dict(series_id=series_id, api_key=key, file_type='json',
                                     sort_order='desc', limit=limit), timeout=15)
        r.raise_for_status()
        return sorted((o['date'], float(o['value'])) for o in r.json()['observations'] if o['value'] != '.')
    except Exception:
        return []


def asset_closes() -> dict:
    import macro_flow as mf
    try:
        import yfinance as yf
        syms = [s for _, s, _ in mf.ASSETS] + [mf.FX_KRW]
        d = yf.download(syms, period='2y', auto_adjust=True, progress=False, threads=True)
        c = d['Close'] if isinstance(d.columns, pd.MultiIndex) else d
        return {s: c[s].dropna() for s in syms if s in c.columns}
    except Exception:
        return {}


def _r(v, n=2):
    try:
        return None if v is None or v != v else round(float(v), n)
    except Exception:
        return None


def build(spy=None, kospi=None, fetch=None, closes=None) -> dict:
    """이번 주 판정 한 장. 인자를 주면 그걸로(테스트·화면), 안 주면 직접 수집(CI)."""
    fetch = fetch or fred_fetch
    sw = core_switch(daily_closes(CORE_SYM) if spy is None else spy)
    kw = core_switch(daily_closes(KR_SYM) if kospi is None else kospi)
    d = macro_inputs(fetch)
    rg = macro_regime(d, as_price_state(sw)) if sw else {}
    S = {}
    import macro_flow as mf
    for k, n in MO_FRED.items():
        S[k] = mf.to_series(fetch(k, n))
    ax = axes(S, asset_closes() if closes is None else closes, sw.get('on') if sw else None, rg.get('phase'))
    ph = SEASONS.get(rg.get('phase')) if rg else None
    return dict(
        generated=datetime.now().strftime('%Y-%m-%d %H:%M'),
        asof=sw.get('date') if sw else None,
        rule=f'코어 = {CORE_SYM} 종가가 {MA_DAYS}일 이평 위면 보유, 아래면 현금 (원칙 v1.3 §3) · 위성은 시장 필터 없음 (§4)',
        core=sw, kr_core=kw, alloc=alloc(sw.get('on') if sw else None),
        canslim_m=dict(US=market_dir(sw), KR=market_dir(kw)),
        phase=dict(key=rg.get('phase'), name=ph['name'] if ph else None, emoji=ph['emoji'] if ph else None,
                   conf=rg.get('conf'), rate_dir=rg.get('rate_dir'), growth=rg.get('growth')) if rg else {},
        greed=dict(word=ax['G']['word'], n=ax['G']['n'], ref=ax['G']['ref']),
        flow=dict(ax['flow'], nl13=_r(ax['nl13'], 1)),
        econ=dict(word=ax['ew'], sub=ax['esub']),
        fred_ok=bool(d),
    )


def load(path: str = OUT) -> dict:
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}


def age_days(v: dict, today: date | None = None) -> int | None:
    t = (v or {}).get('asof')
    if not t:
        return None
    return ((today or date.today()) - date.fromisoformat(t[:10])).days


def latest_core_on(max_age: int = 5) -> bool | None:
    """배치 소비자(주간 포트폴리오·executor)용. 파일이 낡았으면 직접 계산한다."""
    v = load()
    if v.get('core') and (age_days(v) or 99) <= max_age:
        return v['core']['on']
    sw = core_switch(daily_closes(CORE_SYM))
    return sw.get('on') if sw else None


def cash_fraction() -> float:
    """주간 포트폴리오 현금 비중(0~1) = 원칙 완충 + (스위치 OFF 면 코어 몫).
    2026-10-21 — 기각된 3단계 신호(Fed·M2 → 10~70%) 대체. 판정 불가면 완충만."""
    a = alloc(latest_core_on())
    return (a['cash_total'] if a['cash_total'] is not None else a['buffer']) / 100


def write(v: dict, path: str = OUT) -> dict:
    """history 에 주간 전환 기록을 남긴다 — 종합 탭의 '스위치가 바뀌었나'."""
    old = load(path)
    hist = [h for h in (old.get('history') or []) if h.get('date') != v.get('asof')]
    if v.get('core'):
        hist.append(dict(date=v['asof'], on=v['core']['on'], gap=v['core']['gap']))
    hist = sorted(hist, key=lambda h: h['date'])[-260:]
    prev = [h for h in hist if h['date'] < (v.get('asof') or '')]
    v['history'] = hist
    v['changed'] = bool(prev and v.get('core') and prev[-1]['on'] != v['core']['on'])
    v['prev_on'] = prev[-1]['on'] if prev else None
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    json.dump(v, open(tmp, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
    os.replace(tmp, path)
    return v


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    v = build()
    if not v.get('core'):
        print('::error title=판정 실패::SPY 일봉을 받지 못했다 — macro.json 을 덮지 않는다')
        sys.exit(1)
    v = write(v)
    c, a = v['core'], v['alloc']
    print(f"{v['asof']} 코어 {'ON' if c['on'] else 'OFF'} ({c['gap']:+.1f}%) · 목표 코어 {a['core_now']} / 위성 {a['satellite']} / "
          f"현금 {a['cash_total']} · 국면 {v['phase'].get('name')} · 경고 {v['greed']['n']}/3"
          + (' · ⚠️ 스위치 전환' if v['changed'] else ''))
