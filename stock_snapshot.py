# -*- coding: utf-8 -*-
"""🔍 종목 분석 스냅샷 — 7블록 판정을 **한 번 계산해 dict 로** 돌려준다 (2026-11-13, 통폐합 P1 첫 단계).

왜: 같은 '종목 분석'을 대시보드·봇 /report·봇 /ir 이 따로 계산해 같은 종목에 다른 숫자가 나왔다.
    이 모듈이 돌려준 dict 하나를 화면(dashboard._an_v2_fill)이 그리고, 같은 dict 를 results/snap/{코드}.json 으로
    내보내면 봇은 그림만 그린다(상태 = 대시보드 정본 · 사건 = 봇 정본).

순서(차니 2026-11-13 확정): 결론 → 수급 → 이익 방향 → 가격 → 정체 → 깨지는 조건·촉매 → 매매 계획 → 원자료.
정체(린치 유형)는 읽는 순서는 5번째지만 **계산은 먼저** 한다 — 유형이 가격 블록의 해석(사이클 기업 P/E 보류)을 정한다.

입력: L = 종목 분석 탭이 이미 계산한 locals (여기서 새로 추정하지 않는다 — 없는 값은 '-'·'na' 로 정직하게).
      ctx = 대시보드 전역 도우미(공통 지표표 _CMB, 업종 사전, 컨센서스, 분기 재무 로더). streamlit 은 쓰지 않는다.
출력 계약(v1):
  {'v': 1, 'sym', 'market': 'KR'|'US', 'asof': 'YYYY-MM-DD', 'name',
   'type': {'label', 'sub', 'cyclical'},                      # 정체 — 린치 유형(v1 규칙·참고)
   'blocks': {블록명: {'tone', 'cards': [{'label','value','sub','tone'}…], 'detail': [...], 'error': str|None}},
   'verdict': {'head', 'cards', 'rules': {'pass','total','bot'}|None}}
"""
from __future__ import annotations

import datetime as _dt
import json
import os

import pandas as pd

VERSION = 3   # 2026-11-16 v3: 밸류에이션 블록 · verdict 4축+판단 철회 · halt·data_check·events
BLOCKS = ['수급', '이익 방향', '가격', '밸류에이션', '정체', '깨지는 조건·촉매', '매매 계획', '원자료']
SNAP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'results', 'snap')


def _r(v, nd=4):
    try:
        f = float(v)
        return None if pd.isna(f) else round(f, nd)
    except Exception:
        return None


def _dir(ys, k: int = 4, tol: float = 0.03) -> str | None:
    """마지막 값 vs k개 전 — 3% 이내면 횡보."""
    ys = [y for y in (ys or []) if y is not None]
    if len(ys) <= k:
        return None
    a, b = ys[-1 - k], ys[-1]
    base = max(abs(a), 1e-9)
    ch = (b - a) / base
    return 'up' if ch > tol else 'down' if ch < -tol else 'flat'


def _money(v, is_kr: bool) -> str:
    """KR 은 억원 입력, US 는 달러 입력."""
    if v is None:
        return '-'
    if is_kr:
        return f"{v / 1e4:,.1f}조원" if abs(v) >= 1e4 else f"{v:,.0f}억원"
    return f"${v / 1e9:,.2f}B" if abs(v) >= 1e9 else f"${v / 1e6:,.0f}M"


def C(label, value, sub='', tone='na', spark=None, dir=None):
    d = {'label': label, 'value': value, 'sub': sub, 'tone': tone}
    if spark:
        d['spark'] = spark
    if dir:
        d['dir'] = dir
    return d


def _num(v):
    try:
        f = float(v)
        return None if pd.isna(f) else f
    except Exception:
        return None


# ── 정체: 린치 6유형 v1 규칙 ────────────────────────────────────────────────
def lynch_type(cyclical: bool | None, rev_yoy: float | None, state: str | None,
               mcap_usd: float | None) -> dict:
    """대형우량·고성장·경기순환·회생·저성장(+판정 불가). 자산주는 데이터(장부가 대비 숨은 자산)가 없어 v1 에선 안 가른다.
    규칙(참고용 — 백테스트한 것이 아니다): 흑자전환·적자축소 → 회생 / 이익률 사이클 기업 → 경기순환 /
    매출 YoY ≥ 20 → 고성장 / 시총 $50B+ 이고 매출 5~20 → 대형우량 / 매출 < 5 → 저성장."""
    st = str(state or '')
    if '흑자전환' in st or '적자' in st:
        return {'label': '회생(턴어라운드)', 'sub': f"{st} — 피터 린치 분류: 실적 바닥 탈출이 확인되는 국면의 상승폭이 가장 큼", 'cyclical': bool(cyclical)}
    if cyclical:
        return {'label': '경기순환', 'sub': '이익률이 자기 분포 안에서 크게 변동 — P/E 역방향 해석 필요(최저 P/E = 이익 천장)', 'cyclical': True}
    if rev_yoy is None:
        return {'label': '판정 불가', 'sub': '매출 성장률 없음', 'cyclical': False}
    if rev_yoy >= 20:
        return {'label': '고성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — PEG·성장 지속성이 핵심", 'cyclical': False}
    if rev_yoy < 5:
        return {'label': '저성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — 배당·자사주 정책이 수익률을 좌우(피터 린치)", 'cyclical': False}
    if mcap_usd is not None and mcap_usd >= 50e9:
        return {'label': '대형우량', 'sub': f"매출 YoY {rev_yoy:+.0f}% · 시총 ${mcap_usd / 1e9:,.0f}B — 린치 분류상 30~50% 구간 차익 실현 대상", 'cyclical': False}
    return {'label': '중간 성장', 'sub': f"매출 YoY {rev_yoy:+.0f}% — 고성장·대형우량 사이", 'cyclical': False}


# ── 깨지는 조건: 실전 v1.9 규칙 + 이익 방향을 '지금 거리'와 함께 ──────────────
def break_conditions(rs: float | None, dd52: float | None, fwd_tone: str | None,
                     gate_on: bool | None) -> dict:
    """각 조건 = (이름, 이미 해당?, 지금 값). 규칙상 손절선(고점 −20%)과 '판단이 깨지는 조건'은 같은 칸에 두되 출처를 적는다."""
    rows = []
    if rs is not None:
        rows.append(('RS 70 아래 (실전 v1.9 탈락 매도)', rs < 70, f"지금 RS {rs:.0f}"))
    if dd52 is not None:
        rows.append(('52주 고점 −20% (실전 손절선 기준은 보유 중 고점)', dd52 <= -20, f"지금 고점 대비 {dd52:+.1f}%"))
    if fwd_tone in ('good', 'mid', 'bad'):
        rows.append(('컨센서스 하향 전환 (이익 방향 악화)', fwd_tone == 'bad', {'good': '지금 상향', 'mid': '지금 혼조', 'bad': '지금 하향'}[fwd_tone]))
    if gate_on is not None:
        rows.append(('소속 지수 주봉 5주선 이탈 (신규 매수 중지)', not gate_on, '지금 ' + ('위' if gate_on else '아래')))
    hit = [r for r in rows if r[1]]
    if not rows:
        return {'value': '-', 'sub': '조건을 잴 데이터 없음', 'tone': 'na', 'rows': rows}
    return {'value': f"{len(rows)}개 중 {len(hit)}개 이미 해당",
            'sub': ' · '.join(r[0].split(' (')[0] for r in hit) if hit else '해당 조건 없음 — 조건별 현재 거리는 아래 근거 참조',
            'tone': 'bad' if len(hit) >= 2 else ('mid' if hit else 'good'), 'rows': rows}


# ── 본체 ─────────────────────────────────────────────────────────────────
def compute(L: dict, ctx: dict) -> dict:
    """L: 탭 locals · ctx: {'A2','CMB','sector_detail','kr_cons_hist','kr_cons_live','sx','q_rows_long','cm'}."""
    A2, CMB, cm = ctx['A2'], ctx['CMB'], ctx['cm']
    sym, is_kr, hist, info = L['sym8_clean'], L['is_kr_sym'], L['hist'], L.get('info') or {}
    pxf = (lambda v: f"₩{v:,.0f}") if is_kr else (lambda v: f"${v:,.2f}")
    snap = {'v': VERSION, 'sym': sym, 'market': 'KR' if is_kr else 'US',
            'asof': _dt.date.today().isoformat(), 'name': str(info.get('shortName') or info.get('longName') or L.get('name') or sym),
            'type': None, 'blocks': {}, 'verdict': None}
    tone = {}
    in_cmb = (CMB is not None) and (not CMB.empty) and (sym in CMB.index)
    row = CMB.loc[sym] if in_cmb else None
    rs = _num(row.get('RS')) if in_cmb else None
    oy = _num(row.get('영업익YoY(%)')) if in_cmb else None
    ry = _num(row.get('매출YoY(%)')) if in_cmb else None
    mcap_usd = _num(row.get('_mc_usd')) if in_cmb else None
    h = None
    try:
        h = A2.high52(hist['Close'])
    except Exception:
        pass

    # ① 수급 ───────────────────────────────────────────────────────────────
    #   2026-11-16 — 점 대신 흐름: RS 라인(종목 ÷ 지수, 주봉 1년) · 업종×종목 판정 · 거래량 60일
    try:
        sd = L.get('_sd') or ctx['sector_detail']()
        gsel, glabel = str(L.get('_gsel') or ''), L.get('_glabel')
        mkt = 'KR' if is_kr else 'US'
        if is_kr and gsel.startswith('테마'):
            fam = sd.get('theme') or {}
        elif is_kr and gsel.startswith('네이버 업종'):
            fam = sd.get('upjong') or {}
        elif not is_kr and gsel.startswith('세부 산업'):
            fam = sd.get('industry') or {}
        else:
            col = '_업종full' if (in_cmb and '_업종full' in CMB.columns) else '업종'
            fam = {k: list(v.index.astype(str)) for k, v in CMB.groupby(col)} if in_cmb else {}
            glabel = str(row[col]) if in_cmb else None
        gh = A2.group_heat(CMB, fam, market=mkt, min_n=5)
        grow = gh[gh['group'] == glabel] if glabel is not None and len(gh) else gh.iloc[0:0]
        gpct = float(grow['pct'].iloc[0]) if len(grow) else None
        vr = A2.volume_ratio(hist.get('Volume'))
        q = A2.flow_quadrant(gpct, rs)
        # RS 라인
        rs_sp, rs_dir, rs13 = None, None, None
        try:
            ix = ctx['index_hist']('KS11' if is_kr else 'SPY', 400) if ctx.get('index_hist') else None
            if ix is not None and len(ix):
                ic = pd.to_numeric(ix.iloc[:, 0], errors='coerce')
                ic.index = pd.to_datetime(ic.index).tz_localize(None) if getattr(pd.to_datetime(ic.index), 'tz', None) else pd.to_datetime(ic.index)
                sc = pd.to_numeric(hist['Close'], errors='coerce')
                sc.index = pd.to_datetime(sc.index).tz_localize(None) if getattr(pd.to_datetime(sc.index), 'tz', None) else pd.to_datetime(sc.index)
                ratio = (sc / ic.reindex(sc.index, method='ffill')).dropna()
                rw = ratio.resample('W-FRI').last().dropna().tail(52)
                if len(rw) >= 10:
                    rwn = rw / rw.iloc[0] * 100
                    rs_sp = {'y': [_r(v, 2) for v in rwn], 'ref': 100.0}
                    rs_dir = _dir(list(rwn), k=8, tol=0.02)
                    rs13 = (rw.iloc[-1] / rw.iloc[-14] - 1) * 100 if len(rw) > 14 else None
        except Exception:
            pass
        ixn = '코스피' if is_kr else 'S&P500'
        vol_sp = None
        try:
            vv = pd.to_numeric(hist['Volume'], errors='coerce').dropna().tail(60)
            if len(vv) >= 20:
                vol_sp = {'y': [_r(v / 1e6, 3) for v in vv], 'kind': 'bar', 'ref': _r(vv.tail(20).mean() / 1e6, 3)}
        except Exception:
            pass
        # 2026-11-16 — '종목 단독 강세'가 '업종 안에서 1등'으로 읽혔다(실제: 업종은 하위, 종목 RS 만 높음). 두 축을 그대로 적는다.
        g_hot = None if gpct is None else gpct <= 30        # flow_quadrant 와 같은 기준(업종 상위 30% · 종목 RS 80)
        s_hot = None if rs is None else rs >= 80
        qshort = ('-' if g_hot is None or s_hot is None else
                  f"업종 {'강세' if g_hot else '약세'} · 종목 {'강세' if s_hot else '약세'}")
        cards = [
            C(f'RS 라인 (대 {ixn} · 1년)', f"RS {rs:.0f} (상위 {max(1, 100 - int(rs))}%)" if rs is not None else 'RS -',
              (f"13주 지수 대비 {rs13:+.1f}%" if rs13 is not None else '지수 이력 없음')
              + (f" · 52주 고점 대비 {h['dd']:+.1f}%" if h else ''),
              'na' if rs is None else ('good' if rs >= 80 else 'bad' if rs < 50 else 'mid'), rs_sp, rs_dir),
            C('업종 온도 × 종목 강도', qshort,
              (f"{glabel} — 업종 온도 {int(grow['rank'].iloc[0])}/{int(grow['of'].iloc[0])}위 · 종목 RS {rs:.0f}"
               if len(grow) and rs is not None else (glabel or '업종 미상')),
              q['tone']),
            C('거래량 (5일 ÷ 20일)', f"{vr:.1f}배" if vr else '-', '최근 60거래일 · 점선 = 20일 평균',
              'na' if not vr else ('good' if vr >= 1.5 else 'mid' if vr >= 0.8 else 'bad'), vol_sp),
        ]
        if is_kr and ctx.get('kr_inv'):          # 2026-11-16 — 한국: 외국인·기관 순매매 20일(네이버) + 외국인 보유율 흐름
            try:
                iv = ctx['kr_inv'](sym)
                if iv:
                    fg, ins = iv['frgn'], iv['inst']
                    cards.append(C('외국인·기관 (20일 순매매)', f"외국인 {fg:+,.0f}억 · 기관 {ins:+,.0f}억",
                                   (f"외국인 보유율 {iv['hold_now']:.1f}% ({iv['hold_chg']:+.2f}%p) · " if iv.get('hold_now') is not None else '')
                                   + f"{iv['asof']} 기준 · 금액 = 주식수 × 종가 근사",
                                   'good' if fg > 0 and ins > 0 else 'bad' if fg < 0 and ins < 0 else 'mid',
                                   {'y': iv['hold_series']} if len(iv.get('hold_series') or []) >= 5 else None,
                                   _dir(iv.get('hold_series'), k=10, tol=0.002) if iv.get('hold_series') else None))
            except Exception:
                pass
        tone['수급'] = q['tone']
        snap['blocks']['수급'] = {'tone': q['tone'], 'cards': cards, 'detail': [], 'error': None}
    except Exception as e:
        tone['수급'] = 'na'
        snap['blocks']['수급'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ③ 이익 방향 → 화면 '펀더멘탈' ────────────────────────────────────────────
    #   이익 경로(TTM 실선 + 컨센서스 점선) · 추정치 흐름(90일) · 이익률 사이클(TTM 영업이익률)
    cyc, fwd, state = {}, {'tone': 'na'}, None
    try:
        ed = L.get('_ed') or {}
        rows = []
        if is_kr:
            rows = list(ctx['kr_cons_hist'](sym))
            lv = ctx['kr_cons_live'](sym)
            if lv:
                rows.append({'date': pd.Timestamp.today().strftime('%Y-%m-%d'), 'sym': sym, **lv})
            fwd = A2.forward_kr(rows)
        else:
            fwd = A2.forward_us(ed.get('eps_trend'), ed.get('eps_revisions'))
        qf = ctx['sx'].quarterly_frame(ctx['q_rows_long'](sym, is_kr)[0])
        cyc = A2.cycle_position(qf)
        et0, ah0 = L.get('_et0') or {}, L.get('_ah0') or {}
        state = et0.get('state') if is_kr else (f"이익 가속 {ah0['rows'][0]['주차']}" if ah0.get('rows') else '이익 가속 신호 없음')
        past_tone = ('na' if oy is None and not state else
                     'good' if (oy is not None and oy > 0) or '흑자전환' in str(state) else
                     'bad' if oy is not None and oy < 0 else 'mid')
        # (1) 이익 경로 — KR 영업이익(억원) + 컨센서스 올해·내년 / US 순이익 + EPS 컨센서스 × 주식수
        path_card = C('이익 경로', '-', '분기 재무 부족', 'na')
        try:
            key = 'op_income' if is_kr else 'net_income'
            t4 = qf[key].astype(float).rolling(4, min_periods=4).sum().dropna().tail(16) if (qf is not None and not qf.empty and key in qf) else pd.Series(dtype=float)
            if is_kr:
                t4 = t4 / 1e8
            if len(t4) >= 4:
                fw = []
                if is_kr and rows:
                    lr = rows[-1]
                    fw = [_r(lr.get('op_0y'), 1), _r(lr.get('op_1y'), 1)]
                elif not is_kr:
                    et = ed.get('eps_trend')
                    shn = _num(info.get('sharesOutstanding'))
                    try:
                        fw = [_r(float(et.loc[p_, 'current']) * shn, 0) for p_ in ('0y', '+1y')] if (et is not None and shn) else []
                    except Exception:
                        fw = []
                fw = [x for x in fw if x is not None]
                now_v = float(t4.iloc[-1])
                yoy = (now_v / float(t4.iloc[-5]) - 1) * 100 if len(t4) >= 5 and float(t4.iloc[-5]) > 0 else None
                nxt = (fw[-1] / now_v - 1) * 100 if fw and now_v > 0 else None
                lab = '영업이익 경로 (TTM → 컨센서스)' if is_kr else '순이익 경로 (TTM → 컨센서스)'
                path_card = C(lab, _money(now_v, is_kr) + (f" · YoY {yoy:+.0f}%" if yoy is not None else ''),
                              (f"내년 컨센서스 {_money(fw[-1], is_kr)} ({nxt:+.0f}%)" if nxt is not None else '컨센서스 없음')
                              + ' · 실선 실적 · 점선 추정',
                              'na' if yoy is None else ('good' if yoy > 0 and (nxt is None or nxt > 0) else 'bad' if yoy < 0 and (nxt is None or nxt < 0) else 'mid'),
                              {'y': [_r(v, 1) for v in t4], 'fwd': fw}, _dir(list(t4) + fw, k=min(4, len(t4)), tol=0.05))
        except Exception:
            pass
        # (2) 추정치 흐름
        rev_sp, rev_sub = None, fwd.get('sub', '')
        try:
            if not is_kr and ed.get('eps_trend') is not None:
                et = ed['eps_trend']
                cols = [c_ for c_ in ('90daysAgo', '60daysAgo', '30daysAgo', '7daysAgo', 'current') if c_ in et.columns]
                ys = [_r(et.loc['+1y', c_], 3) for c_ in cols]
                if sum(y is not None for y in ys) >= 3:
                    rev_sp = {'y': ys}
                n30 = fwd.get('net30')
                rev_sub = (f"90일 {fwd['rev90']:+.1f}%" if fwd.get('rev90') is not None else '') + \
                          (f" · 30일 상향−하향 {n30:+.0f}건" if n30 is not None else '')
            elif is_kr and rows:
                hh = pd.DataFrame(rows)
                k_ = 'op_1y' if 'op_1y' in hh else 'eps_1y'
                ys = [_r(v, 1) for v in pd.to_numeric(hh.get(k_), errors='coerce').dropna().tail(26)]
                if len(ys) >= 3:
                    rev_sp = {'y': ys}
        except Exception:
            pass
        rev_card = C('내년 추정치 흐름 (최근 90일)', fwd.get('value', '-'), rev_sub.strip(' ·') or '-', fwd['tone'], rev_sp,
                     _dir((rev_sp or {}).get('y'), k=min(4, len((rev_sp or {}).get('y') or []) - 1), tol=0.01) if rev_sp else None)
        # (3) 이익률 사이클
        cy_sp = None
        try:
            qq = qf[['revenue', 'op_income']].astype(float)
            opm = (qq['op_income'].rolling(4, min_periods=4).sum() / qq['revenue'].rolling(4, min_periods=4).sum() * 100).dropna().tail(40)
            if len(opm) >= 6:
                cy_sp = {'y': [_r(v, 2) for v in opm], 'ref': _r(opm.median(), 2)}
        except Exception:
            pass
        cy_card = C('영업이익률 사이클 (TTM)',
                    (f"{cy_sp['y'][-1]:.1f}%" if cy_sp else '-') + (f" · {cyc['pct']:.0f}%ile" if cyc.get('pct') is not None else ''),
                    (cyc.get('value') or '-') + (' · 점선 = 자기 중앙값' if cy_sp else ''), cyc.get('tone', 'na'), cy_sp,
                    _dir((cy_sp or {}).get('y'), k=4, tol=0.05) if cy_sp else None)
        cards = [path_card, rev_card, cy_card]
        t = fwd['tone'] if fwd['tone'] != 'na' else (cyc['tone'] if cyc.get('cyclical') else past_tone)
        peak = bool(cyc.get('cyclical') and (cyc.get('pct') or 0) >= 80 and t == 'good')   # 린치: 최대 이익·최저 P/E 에서 사면 반토막
        if peak:
            t = 'mid'
        tone['이익 방향'], tone['_cyc_peak'] = t, peak
        snap['blocks']['이익 방향'] = {'tone': t, 'cards': cards, 'detail': [], 'error': None}
    except Exception as e:
        tone['이익 방향'] = 'na'
        snap['blocks']['이익 방향'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # 정체 — 유형은 여기서 확정(가격 해석에 쓴다)
    snap['type'] = lynch_type(cyc.get('cyclical'), ry, state, mcap_usd)

    # ④ 가격 → 화면 '히스토리' · ④' 밸류에이션 (2026-11-16 차니: 밸류에이션을 펀더멘탈과 양대 축으로 분리)
    #   히스토리 = 주가 경로(주봉 1년·200일선) · 사이클 위치(진행 중 구간 vs 과거 중앙) · 이번 달 계절성
    #   밸류에이션 = 주 멀티플 밴드(흑자 P/E · 적자 P/S) · P/B 밴드 · 업종 대비(P/E·PEG)
    try:
        bm, vb = L.get('_bm') or {}, L.get('_vb') or {}
        peg = _num(L.get('_peg'))
        per = vb.get('per_ttm')
        try:
            pr = cm.peer_rank(CMB, sym, codes=L.get('_gcodes'), label=L.get('_glabel')) or {}
        except Exception:
            pr = {}
        med = next((r['업종중앙'] for r in (pr.get('rows') or []) if r['지표'] == 'PER(배)'), None)
        ratio = (per / med) if (per and med and per > 0 and med > 0) else None
        v = A2.valuation_reading(bm.get('rank'), peg, ratio, cyc.get('cyclical'))
        cl = pd.to_numeric(hist['Close'], errors='coerce').dropna()
        cl.index = pd.to_datetime(cl.index)
        wk = cl.resample('W-FRI').last().dropna()
        ma200 = float(cl.tail(200).mean()) if len(cl) >= 200 else None
        px_sp = {'y': [_r(x, 4) for x in wk.tail(52)], 'ref': _r(ma200, 4)} if len(wk) >= 10 else None
        above = (float(cl.iloc[-1]) >= ma200) if ma200 else None
        p_tone = 'na' if not h else ('good' if h['dd'] > -10 and above else 'bad' if h['dd'] <= -20 or above is False else 'mid')
        # 사이클 위치 — cycle_compare 와 같은 지그재그(30%) · 진행 중 구간을 과거 같은 방향 중앙값과 비교
        cy_card = C('사이클 위치 (30% 지그재그)', '-', '구간 계산 불가', 'na')
        try:
            import cycle_compare as _cc
            sw = _cc.swing_rows(cl, 30).to_dict('records')
            def _rr(r_):
                a_, b_ = pd.Timestamp(r_['시작일']), pd.Timestamp(r_['종료일'])
                return ((cl.loc[:b_].iloc[-1] / cl.loc[:a_].iloc[-1] - 1) * 100,
                        int(((cl.index >= a_) & (cl.index <= b_)).sum()))
            live = next((r_ for r_ in sw if '진행' in str(r_['라벨'])), None)
            if live:
                up = str(live['라벨']).startswith('상승')
                lr, ld = _rr(live)
                past = [_rr(r_) for r_ in sw if '진행' not in str(r_['라벨']) and str(r_['라벨']).startswith('상승' if up else '하락')]
                mret = float(pd.Series([x[0] for x in past]).median()) if past else None
                mday = float(pd.Series([x[1] for x in past]).median()) if past else None
                cy_card = C('사이클 위치 (30% 지그재그)', f"{'상승' if up else '하락'} {ld}일째 {lr:+.0f}%",
                            (f"과거 {'상승' if up else '하락'} {len(past)}회 중앙 {mday:.0f}일·{mret:+.0f}%" if past else '과거 같은 방향 구간 없음'),
                            ('good' if up else ('bad' if (mret is not None and lr > mret) else 'mid')))
        except Exception:
            pass
        # 이번 달 계절성 — 월말 종가 기준 같은 달 수익률 평균·승률
        se_card = C('이번 달 계절성', '-', '이력 부족', 'na')
        try:
            mr = cl.resample('ME').last().pct_change().dropna() * 100
            cur = pd.Timestamp.today().month
            same = mr[mr.index.month == cur]
            if len(same) >= 3:
                win = float((same > 0).mean() * 100)
                se_card = C(f'이번 달 계절성 ({cur}월)', f"평균 {same.mean():+.1f}% · 승률 {win:.0f}%",
                            f"{len(same)}년 표본 · 중앙값 {same.median():+.1f}%",
                            'good' if win >= 60 and same.mean() > 0 else 'bad' if win <= 40 and same.mean() < 0 else 'mid',
                            {'y': [_r(x, 2) for x in same.tail(12)], 'kind': 'bar', 'ref': 0.0})
        except Exception:
            pass
        cards = [C('주가 경로 (주봉 1년)', (f"고점 대비 {h['dd']:+.1f}%" if h else '-'),
                   (f"52주 고점 {pxf(h['high'])} ({h['date']})" if h else '가격 이력 부족')
                   + ('' if above is None else (' · 200일선 위' if above else ' · 200일선 아래')),
                   p_tone, px_sp, _dir((px_sp or {}).get('y'), k=8, tol=0.03) if px_sp else None),
                 cy_card, se_card]
        tone['_px'] = p_tone
        snap['blocks']['가격'] = {'tone': p_tone, 'cards': cards, 'detail': [], 'error': None, 'peer_rank': pr}
        # ── 밸류에이션 ──
        bands = L.get('_band') or {}

        def _bcard(b, title):
            if not b or b.get('now') is None or b.get('rank') is None:
                return None
            ser = b.get('series')
            sp = None
            try:
                if ser is not None and len(ser) >= 8:
                    bs = ser.resample('ME').last().dropna().tail(60) if hasattr(ser, 'resample') else ser
                    sp = {'y': [_r(x, 2) for x in bs], 'ref': _r((b.get('pct') or {}).get(50), 2)}
            except Exception:
                sp = None
            return C(title, f"{b['now']:.1f}배 · {b['rank']:.0f}%ile",
                     (f"중앙값 {b['pct'][50]:.1f}배" + (f" · 10~90% {b['pct'][10]:.1f}~{b['pct'][90]:.1f}배"
                                                        if (10 in b['pct'] and 90 in b['pct']) else '')) if (b.get('pct') or {}).get(50) else '-',
                     'good' if b['rank'] <= 25 else 'bad' if b['rank'] >= 75 else 'mid', sp,
                     _dir((sp or {}).get('y'), k=6, tol=0.05) if sp else None)
        main_b = bands.get('pe') if (bands.get('pe') and (per or 0) > 0) else bands.get('ps')
        vcards = [c_ for c_ in (_bcard(main_b or bm, f"{(main_b or bm).get('kind', 'P/E')} 밴드 (TTM)"),
                                _bcard(bands.get('pb'), 'P/B 밴드')) if c_]
        vcards.append(C('업종 대비', (f"P/E {per:.1f}배 vs 업종 {med:.1f}배" if (per and med) else '비교 불가'),
                        (f"업종 대비 {ratio:.2f}배" if ratio else '') + (f" · PEG {peg:.2f}" if peg else ''),
                        'na' if ratio is None else ('good' if ratio <= 0.8 else 'bad' if ratio >= 1.3 else 'mid')))
        tone['가격'] = v['tone']
        snap['blocks']['밸류에이션'] = {'tone': v['tone'], 'cards': vcards, 'detail': [], 'error': None, 'reading': v.get('value')}
    except Exception as e:
        pr = {}
        tone['가격'] = 'na'
        snap['blocks'].setdefault('가격', {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"})
        snap['blocks']['밸류에이션'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ② 정체 → 펀더멘탈 맨 위 '기업 요약 카드'(A안). 문장은 AI 카드(짧은 필드) — 잘라 쓰지 않는다.
    try:
        ty = snap['type']
        prr = {r['지표']: r for r in (pr.get('rows') or [])}
        mc = prr.get('시총') or {}
        card = L.get('_ai_card') or {}
        kp = []
        if ry is not None:
            kp.append({'label': '매출 YoY (최근 분기)', 'value': f"{ry:+.0f}%", 'tone': 'good' if ry > 0 else 'bad'})
        if (snap['blocks'].get('이익 방향') or {}).get('cards'):
            c3 = snap['blocks']['이익 방향']['cards'][2]
            if c3.get('spark'):
                kp.append({'label': 'TTM 영업이익률', 'value': f"{c3['spark']['y'][-1]:.1f}%", 'tone': c3['tone']})
        bmm = L.get('_bm') or {}
        if bmm.get('now') is not None and bmm.get('rank') is not None:
            kp.append({'label': f"{bmm.get('kind', 'P/E')} (5년 밴드)", 'value': f"{bmm['now']:.0f}배",
                       'sub': f"{bmm['rank']:.0f}%ile", 'tone': 'good' if bmm['rank'] <= 25 else 'bad' if bmm['rank'] >= 75 else 'mid'})
        if mc.get('순위'):
            kp.append({'label': '업종 내 시총', 'value': f"{mc['순위']}/{mc['비교수']}위", 'sub': str(pr.get('sector') or ''), 'tone': 'na'})
        snap['company'] = {'name': snap['name'], 'definition': card.get('definition') or L.get('_one') or '',
                           'revenue': card.get('revenue'), 'moat': card.get('moat'), 'risk': card.get('risk'),
                           'type': f"린치 유형 · {ty['label']}", 'kpis': kp,
                           'src': card.get('src') or ''}
        snap['blocks']['정체'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': None}
    except Exception as e:
        snap['blocks']['정체'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ⑤ 깨지는 조건·촉매 ────────────────────────────────────────────────────
    try:
        nx_us, nx = L.get('_next_us'), (L.get('_eq') or {}).get('next') or {}
        now = pd.Timestamp.today().normalize()
        if nx_us is not None:
            nd = pd.Timestamp(nx_us[0])
            nd = nd.tz_localize(None) if getattr(nd, 'tz', None) else nd
            ev = C('다음 실적 발표', f"{nd:%Y-%m-%d}", f"D-{(nd.normalize() - now).days}", 'mid' if (nd - now).days <= 14 else 'na')
        elif nx.get('예상') is not None:
            ev = C('다음 실적 발표', f"{nx['예상']:%m월 %d일} 전후(추정)", '전년 같은 분기 발표일 기준', 'na')
        else:
            ev = C('다음 실적 발표', '-', '일정 미상', 'na')
        try:                                    # 소속 지수 게이트 — 봇 계획표(live/plan_latest.json)와 같은 값
            ix = ((ctx['live_plan']() or {}).get('index') or {}).get('KR' if is_kr else 'US') or {}
            gate = ix.get('ok') if isinstance(ix.get('ok'), bool) else None
        except Exception:
            gate = None
        bc = break_conditions(rs, h['dd'] if h else None, fwd.get('tone'), gate)
        risk, chk = L.get('_risk') or [], L.get('_chk_') or []
        nr = [r for r in risk if r.get('state') == 'warn']
        nc = [r for r in chk if r.get('state') == 'warn']
        # 2026-11-16 — 첫 줄 카드 = 보유 리스크(종목 리스크)만. 데이터 점검은 종목 리스크와 섞지 않고 따로(data_check).
        #   '판단 철회 조건'은 결론 줄(4축과 나란히)로 · 다음 실적 발표는 첫 줄에서 내림(events).
        nr2 = [r for r in nr if not str(r.get('name', '')).startswith('청산선')]
        rsk = [r for r in risk if not str(r.get('name', '')).startswith('청산선')]
        cards = [C('보유 리스크', (f"{len(nr2)}/{len(rsk)} 해당" if rsk else '-'),
                   ' · '.join(r['name'] for r in nr2) or '해당 없음',
                   'na' if not rsk else ('good' if not nr2 else 'mid' if len(nr2) <= 2 else 'bad'))]
        snap['halt'] = C('판단 철회 조건', bc['value'], bc['sub'], bc['tone'])
        snap['data_check'] = {'warn': [r['name'] for r in nc], 'n': len(chk)}
        snap['events'] = {'next_earnings': ev['value'], 'sub': ev['sub']}
        # 2026-11-16 — 세 묶음(grp)으로: 깨지는 조건(판단 철회 4개) · 리스크 점검(재무·밸류·변동성) · 데이터 점검(숫자 신뢰도).
        #   화면은 묶음별 열 · 묶음 안에서 해당(warn) 먼저. '청산선 아래(보유 시)'는 깨지는 조건의 고점 −20% 와 같은 뜻이라 뺀다.
        detail = ([{'grp': '판단 철회 조건', 'state': 'warn' if r[1] else 'ok', 'name': r[0], 'detail': r[2]} for r in bc['rows']]
                  + [dict(r, grp='보유 리스크') for r in risk if not str(r.get('name', '')).startswith('청산선')]
                  + [dict(r, grp='데이터 점검') for r in chk])
        tone['리스크'] = cards[0]['tone']
        snap['blocks']['깨지는 조건·촉매'] = {'tone': bc['tone'], 'cards': cards, 'detail': detail, 'error': None,
                                        'expand': bool(nc)}
    except Exception as e:
        snap['blocks']['깨지는 조건·촉매'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': f"{type(e).__name__}: {str(e)[:100]}"}

    # ⑥ 매매 계획 · 원자료 — 첫 줄 카드 없음(섹션 본문이 곧 내용). 계약상 자리만 둔다.
    rk, bst = L.get('_rk'), L.get('_bst')
    rules = ({'pass': sum(1 for x in rk if x[1]), 'total': len(rk), 'bot': bst or '-'}
             if isinstance(rk, list) and rk else None)
    snap['blocks']['매매 계획'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': None, 'rules': rules}
    snap['blocks']['원자료'] = {'tone': 'na', 'cards': [], 'detail': [], 'error': None}

    # 결론 (항상) ─────────────────────────────────────────────────────────
    f_t, s_t, p_t = tone.get('이익 방향', 'na'), tone.get('수급', 'na'), tone.get('가격', 'na')
    fw = {'good': '이익 개선 국면', 'mid': '이익 신호 혼조', 'bad': '이익 악화 국면', 'na': '이익 판단 불가'}[f_t]
    if tone.get('_cyc_peak'):
        fw = '이익 사이클 천장권 — 해석 주의'
    fl = {'good': '수급 유입', 'mid': '수급 부분 유입', 'bad': '수급 이탈', 'na': '수급 판단 불가'}[s_t]
    px_t = tone.get('_px', 'na')
    pw = {'good': '주가 상승 추세', 'mid': '주가 조정 구간', 'bad': '주가 하락 추세', 'na': ''}[px_t]

    def _first(block, i=0):
        cs = (snap['blocks'].get(block) or {}).get('cards') or []
        return cs[i] if len(cs) > i else {}
    f0, v0, p0, s0 = _first('이익 방향'), _first('밸류에이션'), _first('가격'), _first('수급')
    vw = {'good': '밸류 매력', 'mid': '밸류 중립', 'bad': '밸류 부담', 'na': ''}[p_t]
    snap['verdict'] = {
        'head': ', '.join(x for x in (fw, vw, pw, fl) if x),
        'type_chip': snap['type']['label'],
        # 2026-11-16 — 4축(펀더멘탈·밸류에이션·히스토리·수급) + 판단 철회 조건을 한 줄에. 탭과 같은 순서·같은 대표 카드.
        'cards': [C('🏭 펀더멘탈', {'good': '개선', 'mid': '엇갈림', 'bad': '악화', 'na': '-'}[f_t],
                    f"{fw} · {f0.get('value', '-')}", f_t, f0.get('spark'), f0.get('dir')),
                  C('⚖️ 밸류에이션', {'good': '저평가', 'mid': '중립', 'bad': '고평가', 'na': '판정 보류'}[p_t],
                    v0.get('value', '-') + (" · 사이클 기업 — P/E 해석 보류(P/B·밴드 병행)" if (p_t == 'na' and cyc.get('cyclical')) else
                                            (" · 멀티플 자료 부족" if p_t == 'na' else '')),
                    p_t, v0.get('spark'), v0.get('dir')),
                  C('📈 히스토리', {'good': '상승 추세', 'mid': '조정', 'bad': '하락 추세', 'na': '-'}[px_t],
                    p0.get('value', '-'), px_t, p0.get('spark'), p0.get('dir')),
                  C('🌊 수급', {'good': '강함', 'mid': '보통', 'bad': '약함', 'na': '-'}[s_t],
                    s0.get('value', '-'), s_t, s0.get('spark'), s0.get('dir'))]
                 + ([dict(snap['halt'], label='🛑 판단 철회 조건')] if snap.get('halt') else []),
        'rules': rules,
        # 2026-11-16 — 축마다 '가능한 판정'과 기준, 이 종목이 어디에 해당하는지(차니: 선택지 설명이 어딘가 있어야)
        'criteria': [
            {'axis': '펀더멘탈', 'now': {'good': '개선', 'mid': '엇갈림', 'bad': '악화', 'na': '판단 불가'}[f_t],
             'why': fw,
             'opts': [('개선', '내년 추정치 90일 상향 + 상향 건수 ≥ 하향 건수(추정치 없으면 사이클 위치·최근 분기 이익)'),
                      ('엇갈림', '신호 혼재, 또는 사이클 기업 이익률 상위 20%(천장권 — 린치: 최대 이익에서 사면 반토막)'),
                      ('악화', '내년 추정치 90일 −3% 이하 또는 하향 건수 > 상향 건수')]},
            {'axis': '밸류에이션', 'now': {'good': '저평가', 'mid': '중립', 'bad': '고평가', 'na': '판정 보류'}[p_t],
             'why': (snap['blocks'].get('밸류에이션') or {}).get('reading') or '',
             'opts': [('저평가', 'PEG < 1 · 자기 밴드 25% 이하 · 업종 대비 0.8배 이하 중 찬성이 우세'),
                      ('중립', '찬반 균형'),
                      ('고평가', 'PEG > 2 · 자기 밴드 75% 이상 · 업종 대비 1.25배 이상 중 반대가 우세'),
                      ('판정 보류', '사이클 기업(P/E 가 이익 천장에서 낮고 바닥에서 높음 — P/B·밴드 병행) 또는 데이터 없음')]},
            {'axis': '히스토리', 'now': {'good': '상승 추세', 'mid': '조정', 'bad': '하락 추세', 'na': '판단 불가'}[px_t],
             'why': p0.get('sub', ''),
             'opts': [('상승 추세', '52주 고점 대비 −10% 이내 + 200일선 위'),
                      ('조정', '그 사이'),
                      ('하락 추세', '52주 고점 대비 −20% 이하 또는 200일선 아래')]},
            {'axis': '수급·업종', 'now': {'good': '강함', 'mid': '보통', 'bad': '약함', 'na': '판단 불가'}[s_t],
             'why': fl,
             'opts': [('강함', '업종 온도 상위 30% + 종목 RS 80 이상(주도 업종의 주도주)'),
                      ('보통', '둘 중 하나만 충족(업종 강세·종목 약세 / 업종 약세·종목 강세)'),
                      ('약함', '둘 다 미충족')]},
            {'axis': '판단 철회 조건', 'now': (snap.get('halt') or {}).get('value', '-'), 'why': (snap.get('halt') or {}).get('sub', ''),
             'opts': [('해당 0개', '판단 유지'), ('1개 이상', '해당 조건이 규칙상 매도·신규 매수 중지·판단 재검토 신호')]},
        ],
    }
    return snap


# ── 내보내기 (봇이 읽는 정본) ────────────────────────────────────────────
def _jsonable(o):
    if isinstance(o, dict):
        return {str(k): _jsonable(v) for k, v in o.items() if not str(k).startswith('_') or k in ('_cyc_peak',)}
    if isinstance(o, (list, tuple)):
        return [_jsonable(x) for x in o]
    if isinstance(o, (pd.Timestamp, _dt.date, _dt.datetime)):
        return str(o)[:10]
    if hasattr(o, 'item'):
        try:
            return o.item()
        except Exception:
            return str(o)
    if isinstance(o, float) and pd.isna(o):
        return None
    return o


def public(snap: dict) -> dict:
    """공개 저장소에 올라가도 되는 부분만 — 매매 계획(봇 규칙 대조·소유자 전용)은 뺀다."""
    out = _jsonable({k: v for k, v in snap.items() if k != 'verdict'})
    out['verdict'] = _jsonable({k: v for k, v in snap['verdict'].items() if k != 'rules'})
    out['blocks'].pop('매매 계획', None)
    for b in out['blocks'].values():
        b.pop('peer_rank', None)
    return out


def save(snap: dict, directory: str = SNAP_DIR) -> str:
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f"{snap['sym']}.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(public(snap), f, ensure_ascii=False, indent=1)
    return path
