# -*- coding: utf-8 -*-
"""🧪 퀀트 백테스트 화면 (2026-11-01, 차니 요구 1~8) — 엔진 quant_engine.py · 패널 research/quant_panel.py

모든 규칙은 표(행 추가·삭제)와 숫자로 넣는다. 화면이 만든 명세(JSON)를 그대로 보여 주고, 붙여 넣어 되살릴 수 있다.
패널은 수십 MB 라 git 이 아니라 GitHub Release 'quant-panel' 에서 받는다(로컬에 results/quant_panel_*.parquet 가 있으면 그걸 쓴다).
"""
import gc
import io
import json
import os
import urllib.request

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import quant_engine as Q

REL = 'https://github.com/pcy604/stock-dashboard/releases/download/quant-panel/quant_panel_{m}.parquet'
_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
_IDX = {'US': ['SPX', 'NDX'], 'KR': ['MKT', 'KOSPI']}   # 첫 번째 = 기본 지수 게이트
KR_FIN_START = '2018-06-01'   # 한국 분기 재무 2017Q1~ → 전년 동분기 비교는 2018Q1(공시 +45일) 부터
# 2026-11-08 점검: 미국 패널 종가는 배당 반영 수정주가(AAPL 2024-11 219.2 vs 원가격 ~222) → 가격지수 SPX 와 비교하면 전략이 연 1.5%p 안팎 공짜로 앞섬.
#   비교 지수는 배당 포함 SPXTR. 한국은 패널(marcap 원가격·배당 미반영)과 코스피 가격지수가 같은 기준이라 그대로.
_BM = {'US': 'SPXTR', 'KR': 'KOSPI'}                      # 비교 지수(게이트와 별개)
# MKT(2026-11-05) = 소속 시장 지수 — 코스피 종목은 코스피, 코스닥 종목은 코스닥 5주선. 실전 규칙(live/plan.py)과 같다.
_IDXN = {'SPX': 'S&P500', 'SPXTR': 'S&P500(배당 포함)', 'NDX': '나스닥100', 'KOSPI': '코스피', 'KOSDAQ': '코스닥', 'MKT': '소속 시장(코스피·코스닥)', '': '없음'}
# 필드 선택지: '이름 (키)' — :n 이 붙은 것은 n 칸을 쓴다
_FOPT = [f"{v[0]} ({k.split(':')[0]})" for k, v in Q.FIELDS.items()]
_FKEY = {f"{v[0]} ({k.split(':')[0]})": k for k, v in Q.FIELDS.items()}
_SOPT = {f"{v[0]} ({k})": k for k, v in Q.EXIT_SIGNALS.items()}
_WT = {'equal': '동일 비중', 'rank': '순위 가중(1등 더 많이)', 'mcap': '시총 가중', 'inv_vol': '변동성 역가중(덜 흔들리는 종목 더 많이)'}

PRESETS = {
    # 2026-11-08 차니 "태초마을에서 — 처음부터 내가 지표를 조합" → 기본값. 조건은 유동성 하한(시총) 하나뿐, 손절·지수·불타기 없음.
    '🌱 빈 전략 — 처음부터 직접 조합': dict(
        filters=[dict(field='marcap', op='>=', value='LIQ')],
        rank=dict(field='marcap', desc=True), rebalance=4, max_pos=20, weight='equal', max_w=0.10,
        exposure=dict(index='', ma=40, below=0.0),
        exit=dict(stop=0, trail=[], signals=[])),
    '🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80),
                                              dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
                                     rank=dict(field='rs', desc=True), rebalance=1, max_pos=10, max_w=0.30,
                                     entry=dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
                                     exposure=dict(index='IDX', ma=5, below=0.0, mode='entry'),
                                     exit=dict(stop=0, trail=[[0, 20]], cooldown=2,
                                               signals=[dict(type='field', field='rs', op='<', value=70)])),
    # 2026-11-08 차니 — 지수 신호 현금 확대(이탈·재진입). 사전 등록 검증(research/cash_gate_check.py): 한국 실전 규칙 기준 96조합 합격 0
    '실전 규칙 + 지수 10주선 이탈 시 현금 50% (2번 연속 회복 시 복귀)': dict(
        filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80),
                 dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
        rank=dict(field='rs', desc=True), rebalance=1, max_pos=10, max_w=0.30,
        entry=dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
        exposure=dict(index='IDX', ma=5, below=0.0, mode='entry'),
        exit=dict(stop=0, trail=[[0, 20]], cooldown=2, signals=[dict(type='field', field='rs', op='<', value=70)]),
        cash=dict(index='IDX', rule='ma', unit='w', n=10, level=0.5, reentry='confirm', k=2)),
    '실전 규칙 + 지수 신고가 13주 정체 시 현금 50% (신고가 재돌파 시 복귀)': dict(
        filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80),
                 dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
        rank=dict(field='rs', desc=True), rebalance=1, max_pos=10, max_w=0.30,
        entry=dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
        exposure=dict(index='IDX', ma=5, below=0.0, mode='entry'),
        exit=dict(stop=0, trail=[[0, 20]], cooldown=2, signals=[dict(type='field', field='rs', op='<', value=70)]),
        cash=dict(index='IDX', rule='stall', unit='w', n=13, hi=52, level=0.5, reentry='new_high')),
    'RS 상위 회전 (모멘텀)': dict(filters=[dict(field='marcap', op='>=', value='LIQ')], rank=dict(field='rs', desc=True)),
    '주도주: RS≥80 × 흑자전환': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80),
                                            dict(field='op_turn', op='==', value=1)], rank=dict(field='rs', desc=True),
                                   exit=dict(signals=[dict(type='ma_break', n=20), dict(type='field', field='op_yoy', op='<', value=-30)])),
    '저PER 가치 + 이평 위': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='per', op='between', value=[0, 12]),
                                     dict(field='ma_gap:40', op='>', value=0)], rank=dict(field='per', desc=False)),
    '할로윈 (11~4월만 주식)': dict(filters=[dict(field='marcap', op='>=', value='LIQ')], rank=dict(field='marcap', desc=True),
                                exposure=dict(months=[11, 12, 1, 2, 3, 4])),
    '예시: PER 10~30 × RS 80+ (지수 5주선 아래면 비중 축소)': dict(
        filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='per', op='between', value=[10, 30]),
                 dict(field='rs', op='>=', value=80)],
        rank=dict(field='rs', desc=True),
        exposure=dict(index='IDX', ma=5, below=0.3)),
    '차니식: 반만 사고 불타기 + 래칫': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80)],
                                    rank=dict(field='rs', desc=True), max_w=0.15,
                                    entry=dict(init=0.5, pyramid=[[20, 0.25], [40, 0.25]]),
                                    exit=dict(stop=15, trail=[[0, 25], [50, 20], [100, 15]], cooldown=4,
                                              signals=[dict(type='doji_vol', vol_x=2), dict(type='macd_neg')])),
}
_LIQ = {'US': 1e9, 'KR': 1e11}
_CIX = {'KR': ['KOSPI', 'KOSDAQ'], 'US': ['SPX', 'NDX']}          # 현금 확대 신호용 지수(소속 시장 MKT 는 종목별이라 못 씀)
_RE = {'ma': '이평 위로 마감하면', 'confirm': '이평 위 k번 연속 마감하면', 'rising': '이평 위 + 이평이 오르기 시작하면',
       'band': '이평 × (1+x%) 위로 마감하면', 'new_high': '지수가 다시 신고가를 내면', 'm_ma': '지수가 m선 위로 마감하면'}


@st.cache_resource(show_spinner=False, ttl=3600 * 12)
def _panel(m):
    _ver = '2026-11-12 once_in·univ_floor'      # 패널을 새로 빌드하면 이 글자를 바꾼다 — 함수 코드가 바뀌어야 배포 앱의 12시간 캐시가 버려진다
    loc = f'results/quant_panel_{m}.parquet'
    if os.path.exists(loc):
        df = pd.read_parquet(loc)
    else:
        with urllib.request.urlopen(REL.format(m=m), timeout=60) as r:
            df = pd.read_parquet(io.BytesIO(r.read()))
    df['date'] = pd.to_datetime(df['date'])
    sm = None
    if 'market' in df.columns and df['market'].isin(['KOSPI', 'KOSDAQ']).any():   # 주마다 소속 시장(이전 상장 반영) — 작은 표만 남긴다
        sm = df.loc[df['market'].isin(['KOSPI', 'KOSDAQ']), ['sym', 'date', 'market']].copy()
        sm['market'] = sm['market'].astype('category')
    df = df.drop(columns=[c for c in ('market',) if c in df.columns])   # 문자열 열(메모리)
    P = Q.Panel(df)
    P.univ_floor = {'KR': 5e10, 'US': 2e8}.get(m)       # 패널 빌더 하한과 같아야 함(research/quant_panel.py)
    P.sym_market = sm
    del df
    gc.collect()
    try:                                                # 읽기에 쓴 빈 메모리를 OS 에 돌려줌 — Arrow 풀(mimalloc)이 약 300MB 를 쥐고 있었다
        import pyarrow as pa
        pa.default_memory_pool().release_unused()
    except Exception:
        pass
    try:                                                # 리눅스 malloc 빈 칸 반환
        import ctypes
        ctypes.CDLL('libc.so.6').malloc_trim(0)
    except Exception:
        pass
    return P


@st.cache_data(ttl=3600 * 12, show_spinner=False)
def _index(name):
    s = pd.read_parquet('data/research/macro_long_px.parquet')[name].dropna()
    s.index = pd.to_datetime(s.index)
    return s.resample('W-MON', label='left', closed='left').last()


@st.cache_data(ttl=3600 * 12, show_spinner=False)
def _index_daily(name):
    """지수 일봉 종가 — exposure.daily=True 일 때(요구: '지수 5일선 이탈여부'). 리샘플 없이 그대로."""
    s = pd.read_parquet('data/research/macro_long_px.parquet')[name].dropna()
    s.index = pd.to_datetime(s.index)
    return s


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def _run(m, spec_json):
    spec = json.loads(spec_json)
    P = _panel(m)
    pre = ''
    # 2026-11-05 — 한국 분기 재무(흑자전환·이익 증가율·PER)는 2017년부터라 쓸 수 있는 신호가 2018-05 부터 생긴다.
    #   그 전 구간을 넣으면 몇 년치 현금 대기가 연 수익률을 깎는다(실전 규칙 2015~ 20.3% = 실제론 2018-08 첫 매매).
    _fin = {'op_turn', 'op_yoy', 'rev_yoy', 'per', 'pbr', 'psr', 'roe', 'opm', 'debt', 'rev_qoq', 'gpm'}
    if m == 'KR' and any(f.get('field', '').split(':')[0] in _fin for f in spec.get('filters', [])) \
            and pd.Timestamp(spec.get('start') or '2000-01-01') < pd.Timestamp(KR_FIN_START):
        spec['start'] = KR_FIN_START
        pre = f'ℹ️ 한국 재무 조건은 {KR_FIN_START[:7]}부터 계산할 수 있어 시작을 그때로 옮겼습니다(그 전엔 신호 0건). '
    ex = spec.get('exposure') or {}
    ixn = ex.get('index') or ''
    bm = _BM[m]
    _cs = spec.get('cash') or {}
    _cpx = None
    if _cs.get('index'):
        try:
            _cpx = (_index_daily if _cs.get('unit') == 'd' else _index)(_cs['index'])
        except Exception:
            _cpx = None
    note = ''
    if ixn == 'MKT':
        blk = None
        try:
            if getattr(P, 'sym_market', None) is not None:
                blk = Q.market_block(P, P.sym_market, {'KOSPI': _index('KOSPI'), 'KOSDAQ': _index('KOSDAQ')}, int(ex.get('ma') or 5))
        except Exception as e:
            note = f'{type(e).__name__}'
        if blk is None:      # 패널에 소속 시장이 없거나 코스닥 지수가 없음 → 코스피 하나로(화면에 밝힌다)
            spec['exposure']['index'] = 'KOSPI'
            r = Q.run(P, spec, cash_px=_cpx, index_px=_index('KOSPI'), bench_px=_index(bm))
            r['note'] = pre + '⚠️ 소속 시장 자료가 아직 없어 코스닥 종목도 코스피 5주선으로 계산했습니다' + (f' ({note})' if note else '') + \
                        ' — 실전 규칙(소속 시장별)과 다릅니다.'
            return r
        spec['exposure']['index'] = ''
        r = Q.run(P, spec, cash_px=_cpx, bench_px=_index(bm), entry_block=blk)
        r['note'] = pre
        return r
    ixd = _index_daily(ixn) if ixn and ex.get('daily') else None
    r = Q.run(P, spec, cash_px=_cpx, index_px=_index(ixn) if ixn else None, bench_px=_index(bm), index_px_daily=ixd)
    r['note'] = pre
    return r


def _fill(spec, m):
    s = json.loads(json.dumps(spec))
    if (s.get('exposure') or {}).get('index') == 'IDX':
        s['exposure']['index'] = _IDX[m][0]
    if (s.get('cash') or {}).get('index') == 'IDX':
        s['cash']['index'] = _CIX[m][0]
    for f in s.get('filters', []):
        if f.get('value') == 'LIQ':
            f['value'] = _LIQ[m]
    return s


_MUL = {'marcap': (1e8, 1e9), 'turnover': (1e8, 1e6)}      # 화면 단위 → 원·달러 (KR 억원 · US $B / $M)


def _mul(base, m):
    return _MUL[base][0 if m == 'KR' else 1] if base in _MUL else 1.0


def _fields_df(filters, m):
    rows = []
    for f in filters:
        k = f['field']; base, _, n = k.partition(':')
        lab = next(o for o, kk in _FKEY.items() if kk.split(':')[0] == base)
        v = f['value']
        txt = v if isinstance(v, str) else None
        v1, v2 = (v if isinstance(v, list) else [v, None]) if txt is None else (None, None)
        d = _mul(base, m)
        v1 = v1 / d if isinstance(v1, (int, float)) else v1
        v2 = v2 / d if isinstance(v2, (int, float)) else v2
        rows.append({'지표': lab, 'n': n or None, '조건': f['op'], '값': v1, '값2': v2, '글자': txt})
    return pd.DataFrame(rows or [{'지표': _FOPT[0], 'n': None, '조건': '>=', '값': 0.0, '값2': None, '글자': None}],
                        columns=['지표', 'n', '조건', '값', '값2', '글자'])


def _ok(v):
    return v is not None and not (isinstance(v, float) and np.isnan(v)) and str(v) != ''


def _fields_from(df, m):
    out = []
    for r in df.dropna(subset=['지표']).to_dict('records'):
        k = _FKEY[r['지표']]; base = k.split(':')[0]
        if ':' in k:
            dflt = '10-40' if base == 'ma_x' else '20'
            n = str(r.get('n') or dflt).strip().replace('.0', '')
            k = f"{base}:{n}"
        op = r.get('조건') or '>='
        if op == 'contains':
            if _ok(r.get('글자')):
                out.append(dict(field=k, op=op, value=str(r['글자'])))
            continue
        v1, v2 = r.get('값'), r.get('값2')
        if not _ok(v1):
            continue
        mul = _mul(base, m)
        if op == 'between' and _ok(v2):
            out.append(dict(field=k, op=op, value=[float(v1) * mul, float(v2) * mul]))
        else:
            out.append(dict(field=k, op=op if op != 'between' else '>=', value=float(v1) * mul))
    return out


def _nl_box(m):
    """🤖 말로 쓰기 — Gemini 가 명세를 만들고 quant_nl.validate 가 다시 검사. 세션당 15회."""
    import quant_nl as N
    with st.container(border=True):
        st.markdown("**🤖 전략을 말로 쓰기** — 쓰면 아래 설정 표가 채워집니다. 엔진이 못 하는 조건은 빼고 따로 알려 드립니다.")
        txt = st.text_area('전략', key='qb_nl_txt', height=90, label_visibility='collapsed',
                           placeholder='예) 시총 3천억 이상이고 RS 80 이상인데, 흑자전환했거나 PER 15 이하인 종목을 RS 순으로 15개. '
                                       '처음엔 절반만 사고 +20% 오르면 나머지 매수. 손절 −12%, 50% 오르면 고점 대비 −20%로 손절선 올림. '
                                       '20일선 깨지거나 MACD 약세 전환하면 매도. 코스피가 200일선 아래면 주식 30%만.')
        c1, c2 = st.columns([1, 3])
        used = st.session_state.get('qb_nl_n', 0)
        if c1.button('🤖 명세 만들기', type='primary', disabled=not txt.strip() or used >= 15, key='qb_nl_go'):
            key = ''
            try:
                key = st.secrets.get('GEMINI_KEY', '')
            except Exception:
                pass
            key = key or os.environ.get('GEMINI_KEY', '')
            if not key:
                st.error('AI 키(GEMINI_KEY)가 설정돼 있지 않습니다.')
            else:
                with st.spinner('AI 가 명세로 바꾸는 중…'):
                    try:
                        spec, notes, dropped, _raw = N.to_spec(txt, m, key)
                        st.session_state['qb_nl'] = dict(spec=spec, notes=notes, dropped=dropped, text=txt, m=m)
                        st.session_state['qb_nl_n'] = used + 1
                    except Exception as e:
                        st.error(f'변환 실패: {type(e).__name__}: {str(e)[:200]}')
        c2.caption(f'이번 접속에서 {used}/15회 사용 · AI 는 설정만 만들고, 실행은 아래 같은 엔진이 합니다. 생성된 설정은 반드시 직접 확인해 주십시오.')
        nl = st.session_state.get('qb_nl')
        if nl and nl.get('m') == m:
            if nl['dropped']:
                st.warning('**빼고 실행합니다 (데이터·기능 없음):** ' + ' · '.join(map(str, nl['dropped'])))
            if nl['notes']:
                st.caption('ℹ️ ' + ' · '.join(map(str, nl['notes'])))
            if st.button('✖ 말로 만든 설정 지우기', key='qb_nl_clear'):
                st.session_state.pop('qb_nl', None); st.rerun()
            return nl['spec']
    return None


_DESC = {
    '🌱 빈 전략 — 처음부터 직접 조합': '아무 규칙 없는 출발점 — 시총 하한만 걸려 있습니다. 아래 📐 종목 필터에서 지표를 고르고, 순위 기준·리밸런싱·비중·손절을 정해 '
        '직접 전략을 만드세요. 다 만든 전략은 맨 아래 🧾 명세를 복사해 두면 고급 → 명세 붙여넣기로 되살립니다.',
    '🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)': 'RS 80↑ × 영업 흑자전환 × 5주선 위, RS 순 최대 10종목 · 첫 매수 50%, +10%·+20%에 25%씩 불타기 · 고점 −20% 손절 · RS 70 아래로 떨어지면 매도(주도주 탈락) · 소속 시장 5주선 아래면 신규 중지 — 토스 실전 시범 v1.9 와 같은 규칙',
    '실전 규칙 + 지수 10주선 이탈 시 현금 50% (2번 연속 회복 시 복귀)': '실전 규칙 그대로 + 지수(코스피/S&P500) 주봉이 10주선 아래로 마감하면 보유를 절반으로 덜고, '
        '10주선 위로 2주 연속 마감하면 원래 비중으로 — ⚠️ 사전 등록 검증에서 한국 불합격(낙폭 개선보다 수익 손실이 큼)',
    '실전 규칙 + 지수 신고가 13주 정체 시 현금 50% (신고가 재돌파 시 복귀)': '실전 규칙 그대로 + 지수가 52주 신고가를 낸 뒤 13주 동안 새 신고가가 없으면 보유를 절반으로, '
        '다시 신고가를 내면 원래 비중으로 — ⚠️ 사전 등록 검증에서 한국 불합격',
    'RS 상위 회전 (모멘텀)': '최근 많이 오른(RS 높은) 종목을 정기적으로 갈아탐',
    '주도주: RS≥80 × 흑자전환': 'RS 80↑ × 흑자전환, 20주선 이탈·이익 급감 때 매도',
    '저PER 가치 + 이평 위': 'PER 0~12 중 40주선 위 종목, PER 낮은 순',
    '할로윈 (11~4월만 주식)': '대형주를 11~4월에만 보유',
    '예시: PER 10~30 × RS 80+ (지수 5주선 아래면 비중 축소)': 'PER 10~30 이고 RS 80 이상인 종목을 RS 순으로 — '
        '지수(코스피/S&P500)가 5주선 아래면 평소 비중의 30%만. "원하는 지표 몇 개 고르고 범위 정하기"의 예시',
    '차니식: 반만 사고 불타기 + 래칫': 'RS 80↑ · 절반 매수 후 +20·40% 불타기 · 오를수록 손절선 상향',
}
_STOPS = {0: '끔', 10: '−10%', 15: '−15%', 20: '−20%', 25: '−25%', 30: '−30%'}


_W = {'equal': '동일 비중', 'rank': '순위 가중', 'mcap': '시총 가중', 'inv_vol': '변동성 역가중'}


def _easy(m):
    """쉬운 모드 — 출발점(빈 전략 또는 예시) + 뼈대 7개(시작·종목 수·순위·리밸런싱·비중·손절·지수). 2026-11-08 빈 전략이 기본."""
    c0 = st.columns([3, 2])
    pname = c0[0].selectbox('출발점 — 빈 전략에서 직접 만들거나 예시를 불러와 고치기', list(PRESETS), key='qb_easy_p')
    base = Q.merged(_fill(PRESETS[pname], m))
    # 순위 기준 — '후보가 많을 때 무엇부터 사나'. 엔진 지표 전부(0/1·업종 제외)
    rk_keys = [k for k in Q.FIELDS if k.split(':')[0] not in ('op_turn', 'acc', 'nh', 'sector', 'month')]
    cur_rk = base['rank']['field']
    cur_b = cur_rk.split(':')[0]
    rk_k = next((k for k in rk_keys if k.split(':')[0] == cur_b), rk_keys[0])
    r1, r2, r3 = c0[1].columns([2.2, 1, 1])
    rkf = r1.selectbox('순위 기준 (무엇부터 살까)', rk_keys, index=rk_keys.index(rk_k), key=f'qb_easy_rk|{pname}',
                       format_func=lambda k: Q.FIELDS[k][0])
    rkn = None
    if ':' in rkf:
        rkn = r2.text_input('n', cur_rk.split(':')[1] if ':' in cur_rk and cur_b == rkf.split(':')[0] else str(_NUM_N.get(rkf.split(':')[0], 13)),
                            key=f'qb_easy_rkn|{pname}')
    desc = r3.radio('방향', [True, False], index=0 if base['rank'].get('desc', True) else 1, key=f'qb_easy_rkd|{pname}',
                    format_func=lambda v: '높은 순' if v else '낮은 순')
    base['rank'] = dict(field=(f"{rkf.split(':')[0]}:{(rkn or '').strip() or _NUM_N.get(rkf.split(':')[0], 13)}" if ':' in rkf else rkf), desc=bool(desc))
    c = st.columns([1, 1, 1, 1.3, 1, 1.2])
    rb = c[2].number_input('리밸런싱 (주마다)', 1, 52, int(base.get('rebalance') or 4), 1, key=f'qb_easy_rb|{pname}',
                           help='몇 주마다 순위를 다시 매겨 갈아탈지 — 1 = 매주')
    wopts = list(_W)
    wt = c[3].selectbox('비중', wopts, index=wopts.index(base.get('weight', 'equal')) if base.get('weight', 'equal') in wopts else 0,
                        format_func=_W.get, key=f'qb_easy_w|{pname}')
    base['rebalance'], base['weight'] = int(rb), wt
    # 2026-11-08 차니 "목록으로 하드코딩하지 말고 숫자를 치게" — 숫자 선택은 전부 직접 입력(number_input)
    y_max = pd.Timestamp.today().year
    y0 = min(max(2014, pd.Timestamp(base['start']).year), y_max)
    yr = c[0].number_input('시작 연도', 2014, y_max, int(y0), 1, key=f'qb_easy_y|{pname}', help='2014~ (한국 재무 조건은 2018-06부터 자동)')
    npos = c[1].number_input('종목 수', 1, 100, int(base['max_pos']), 1, key=f'qb_easy_n|{pname}')
    tr = base['exit'].get('trail') or []
    cur = int(tr[0][1]) if len(tr) == 1 and float(tr[0][0]) == 0 else (int(base['exit'].get('stop') or 0) if not tr else None)
    stp = c[4].number_input('손절 (고점 대비 −%)', 0, 90, cur, 1, key=f'qb_easy_s|{pname}', placeholder='전략 기본',
                            help='보유 중 최고가에서 이만큼 빠지면 판다(손절선은 올라가기만) · 0 = 끔 · 비우면 전략 기본(단계별 래칫)')
    stp = 'preset' if stp is None else int(stp)
    ix_on = c[5].toggle('지수 약하면 현금', value=bool(base['exposure'].get('index')), key=f'qb_easy_i|{pname}',
                        help=f"{_IDXN[_IDX[m][0]]}이(가) 이평선 아래면 주식을 사지 않음(한국 5주선 · 미국 40주선≈200일선)")
    st.caption('ℹ️ ' + _DESC.get(pname, ''))
    base['start'] = f'{yr}-01-01'
    base['max_pos'] = int(npos)
    base['max_w'] = max(float(base['max_w']), round(1 / npos, 4))
    if stp != 'preset':
        base['exit'].update(stop=0, trail=[[0, stp]] if stp else [])
    if ix_on:
        base['exposure'].update(index=base['exposure'].get('index') or _IDX[m][0],
                                ma=int(base['exposure'].get('ma') or (5 if m == 'KR' else 40)), below=0.0)
    else:
        base['exposure'].update(index='')
    return pname, base


_BIN = {'op_turn', 'acc', 'nh'}          # 0/1 지표
# 2026-11-08 차니 — 지표 고르기를 관점별로(밸류에이션·펀더멘털·시장). 엔진에 새 지표가 생기면 '시장'에 자동으로 붙는다.
_GROUPS = {
    '💰 밸류에이션': ['per', 'pbr', 'psr', 'marcap', 'close'],
    '🏭 펀더멘털': ['rev_yoy', 'rev_qoq', 'op_yoy', 'op_turn', 'acc', 'oi_g', 'ni_yoy', 'opm', 'gpm', 'roe', 'debt'],
    '📈 시장 (가격·수급·업종)': ['rs', 'rs_chg', 'rs_vec', 'ret', 'ma_gap', 'ma_x', 'dist_hi', 'nh', 'rsi', 'macd_hist', 'vol_x',
                         'turnover', 'vol', 'sector'],
}
_MONTH = 'month'                          # 필터가 아니라 '투자할 달'(exposure.months)로 다룬다
_NUM_N = {'ret': 13, 'rs_chg': 4, 'rs_vec': 4, 'ma_gap': 5, 'dist_hi': 52, 'nh': 52, 'vol_x': 20, 'rsi': 14, 'turnover': 4, 'vol': 26, 'ma_x': '10-40'}


def _unit(base, m):
    if base == 'marcap':
        return '억원' if m == 'KR' else '$B'
    if base == 'turnover':
        return '억원' if m == 'KR' else '$M'
    u = Q.FIELDS[next(k for k in Q.FIELDS if k.split(':')[0] == base)][1]
    return u


def _filter_bar(m, base, pname):
    """📐 상단 필터 바 (2026-11-08 차니 "PER·PBR·RS 강도 등 쓸 수 있는 지표를 전부 취사선택") —
    엔진이 아는 지표(quant_engine.FIELDS) 전부를 골라 범위를 넣는다. 고른 전략의 필터가 처음 값으로 깔린다.
    값을 안 건드린 칸은 전략의 원래 조건(>·== 등)을 그대로 쓴다 — 프리셋 결과가 바뀌지 않게."""
    keys = list(Q.FIELDS)
    bk = {k.split(':')[0]: k for k in keys}
    orig = {}
    for f in base.get('filters') or []:
        orig.setdefault(f['field'].split(':')[0], f)
    K = f"qb_fb|{pname}|{m}"
    with st.container(border=True):
        st.markdown("**📐 종목 필터** — 사용할 지표를 선택하고 범위를 입력합니다. 빈 칸은 제한 없음")
        grp = {g: [bk[b] for b in bs if b in bk] for g, bs in _GROUPS.items()}
        _seen = {k for v in grp.values() for k in v} | {bk.get(_MONTH)}
        grp['📈 시장 (가격·수급·업종)'] += [k for k in keys if k not in _seen]
        ck = lambda k: f"{K}|ck|{k.split(':')[0]}"
        for k in keys:                                          # 처음 한 번: 전략 필터를 체크해 둔다
            if ck(k) not in st.session_state:
                st.session_state[ck(k)] = k.split(':')[0] in orig
        _nm = lambda k: Q.FIELDS[k][0] + (f" ({_unit(k.split(':')[0], m)})" if _unit(k.split(':')[0], m) else '')
        n_on = sum(1 for v in grp.values() for k in v if st.session_state.get(ck(k)))
        with st.popover(f"➕ 지표 고르기 · {n_on}개 선택", use_container_width=True):
            gc = st.columns(len(grp))
            for col, (g, ks) in zip(gc, grp.items()):
                col.markdown(f"**{g}**")
                for k in ks:
                    col.checkbox(_nm(k), key=ck(k), help=Q.FIELDS[k][2])
        sel = [k for ks in grp.values() for k in ks if st.session_state.get(ck(k))]
        out, txt, pos = [], [], {}      # pos: 화면 번호 → 실제 조건 번호(범위 빈 칸은 빠지므로)
        cols = st.columns(3)
        for i, k in enumerate(sel, 1):
            b = k.split(':')[0]
            o = orig.get(b)
            d = _mul(b, m)
            lab, _u, hlp = Q.FIELDS[k]
            with cols[(i - 1) % 3].container(border=True):
                st.markdown(f"**{i}. {lab}**" + (f" <span style='color:#7c8290;font-size:12px'>{_u if b not in _MUL else _unit(b, m)}</span>" if _u else ''),
                            unsafe_allow_html=True, help=hlp)
                n = None
                if ':' in k:
                    n0 = o['field'].split(':')[1] if o and ':' in o['field'] else str(_NUM_N.get(b, 20))
                    n = st.text_input('n(주)', n0, key=f'{K}|{b}|n', help="n주 · 이평 정배열은 '단기-장기'")
                fk = f"{b}:{str(n).strip() or _NUM_N.get(b, 20)}" if ':' in k else b
                if b == 'sector':
                    v0 = o['value'] if o and isinstance(o.get('value'), str) else ''
                    v = st.text_input('포함(쉼표 = 또는)', v0, key=f'{K}|{b}|t', placeholder='반도체, 전기')
                    if v.strip():
                        out.append(dict(field=fk, op='contains', value=v.strip())); pos[i] = len(out); txt.append(f"{i}. 업종 ∋ {v.strip()}")
                    continue
                if b in _BIN:
                    v0 = 0 if o and o.get('value') in (0, 0.0) and o.get('op') == '==' else 1
                    v = st.radio('값', [1, 0], index=[1, 0].index(v0), horizontal=True, key=f'{K}|{b}|b',
                                 format_func=lambda z: '예' if z == 1 else '아니오', label_visibility='collapsed')
                    out.append(dict(field=fk, op='==', value=v)); pos[i] = len(out); txt.append(f"{i}. {lab} {'예' if v else '아니오'}")
                    continue
                lo0 = hi0 = None
                if o:
                    ov = o['value']
                    if o['op'] == 'between' and isinstance(ov, list):
                        lo0, hi0 = ov[0] / d, ov[1] / d
                    elif o['op'] in ('>=', '>'):
                        lo0 = ov / d
                    elif o['op'] in ('<=', '<'):
                        hi0 = ov / d
                    elif o['op'] == '==':
                        lo0 = hi0 = ov / d
                c1, c2 = st.columns(2)
                lo0 = None if lo0 is None else float(lo0)
                hi0 = None if hi0 is None else float(hi0)
                lo = c1.number_input('최소', value=lo0, key=f'{K}|{b}|lo', placeholder='제한 없음')
                hi = c2.number_input('최대', value=hi0, key=f'{K}|{b}|hi', placeholder='제한 없음')
                if o and lo == lo0 and hi == hi0 and o['field'] == fk:
                    out.append(o)                                    # 안 건드림 → 전략 원래 조건 그대로
                elif lo is not None and hi is not None:
                    out.append(dict(field=fk, op='between', value=[float(min(lo, hi)) * d, float(max(lo, hi)) * d]))
                elif lo is not None:
                    out.append(dict(field=fk, op='>=', value=float(lo) * d))
                elif hi is not None:
                    out.append(dict(field=fk, op='<=', value=float(hi) * d))
                else:
                    st.caption('범위를 넣어야 적용됩니다')
                    continue
                pos[i] = len(out)
                txt.append(f"{i}. {lab} " + (f"{lo:,.4g}~{hi:,.4g}" if lo is not None and hi is not None else
                                             (f"≥ {lo:,.4g}" if lo is not None else f"≤ {hi:,.4g}")))
        lg0 = base.get('logic') or ''
        modes = ['모두 만족 (AND)', '하나라도 (OR)', '결합식 직접']
        g1, g2 = st.columns([2, 3])
        mode = g1.radio('결합', modes, index=2 if lg0 else 0, horizontal=True, key=f'{K}|mode', label_visibility='collapsed')
        logic = ''
        if mode == modes[1] and len(out) > 1:
            logic = ' OR '.join(str(i) for i in range(1, len(out) + 1))
        elif mode == modes[2]:
            raw = g2.text_input('결합식 (위 칸 번호)', lg0, key=f'{K}|lg', placeholder='1 AND (2 OR 3) · NOT 4', label_visibility='collapsed')
            import re as _re
            bad = [int(z) for z in _re.findall(r'\d+', raw) if int(z) not in pos]
            logic = _re.sub(r'\d+', lambda mm: str(pos.get(int(mm.group()), mm.group())), raw)
            try:
                if bad:
                    raise ValueError(f'{bad}번 칸은 범위가 비었거나 없습니다')
                Q.parse_logic(logic, len(out))
            except Exception as e:
                st.error(f'결합식 오류 → 모두 AND 로 실행: {e}')
                logic = ''
        st.caption('적용: ' + (f"{logic} · " if logic else ('모두 AND · ' if len(out) > 1 else '')) + (' · '.join(txt) if txt else '필터 없음(전 종목)') +
                   (' · ⚠️ 범위가 빈 지표는 번호에서 빠집니다' if len(out) < len(sel) else ''))
        # 📅 투자할 달 — '달(월)'은 종목 조건이 아니라 '언제 주식을 들고 있나'(할로윈 등). 고른 달에만 보유, 나머지 달은 현금.
        ex0 = base.get('exposure') or {}
        mo0 = ex0.get('months') or list(range(1, 13))
        mf = orig.get(_MONTH)                                       # 말로 쓰기 등에서 온 달 필터 → 달 선택으로 옮김
        if mf and mf.get('op') == 'between' and isinstance(mf.get('value'), list):
            a_, b_ = int(mf['value'][0]), int(mf['value'][1])
            mo0 = [x for x in range(1, 13) if (a_ <= x <= b_ if a_ <= b_ else (x >= a_ or x <= b_))]
        mos = st.pills('📅 투자할 달 — 고른 달에만 주식 보유, 나머지는 현금', list(range(1, 13)), selection_mode='multi', default=mo0,
                       format_func=lambda x: f'{x}월', key=f'{K}|months')
        mos = sorted(mos) or list(range(1, 13))
        if len(mos) < 12:
            st.caption('📅 ' + ' · '.join(f'{x}월' for x in mos) + '에만 보유 (' + ', '.join(f'{x}월' for x in range(1, 13) if x not in mos) + ' 현금)')
    base = json.loads(json.dumps(base))
    base['filters'], base['logic'] = out, logic
    base.setdefault('exposure', {})['months'] = mos
    return base


def _cash_box(m, base, pname):
    """🏦 지수 신호 현금 확대 (2026-11-08 차니) — ① 지수 n일·n주선 이탈 ② 지수 신고가 뒤 n일·n주 정체. 재진입을 따로 고른다."""
    cs0 = base.get('cash') or {}
    K = f"qb_cash|{pname}|{m}"
    with st.container(border=True):
        on = st.toggle('🏦 지수 신호로 현금 비중 확대', value=bool(cs0.get('index')), key=f'{K}|on',
                       help='지수가 약해지면 보유 종목을 같은 비율로 덜어 현금을 늘리고, 재진입 조건이 맞으면 원래 비중으로 되돌립니다. '
                            '(실전 규칙의 "지수 5주선 아래면 신규 중지"와는 별개 — 이건 이미 산 것까지 덜어냄)')
        if not on:
            base = json.loads(json.dumps(base)); base.pop('cash', None)
            return base
        c = st.columns([1.2, 1, 0.8, 0.8, 1])
        rule = c[0].radio('이탈 신호', ['ma', 'stall'], index=1 if cs0.get('rule') == 'stall' else 0, horizontal=True, key=f'{K}|rule',
                          format_func=lambda v: '이평선 이탈' if v == 'ma' else '신고가 정체')
        ixs = _CIX[m]
        ix = c[1].selectbox('지수', ixs, index=ixs.index(cs0['index']) if cs0.get('index') in ixs else 0, key=f'{K}|ix', format_func=_IDXN.get)
        unit = c[2].radio('단위', ['w', 'd'], index=1 if cs0.get('unit') == 'd' else 0, horizontal=True, key=f'{K}|u',
                          format_func=lambda v: '주' if v == 'w' else '일')
        u = '주' if unit == 'w' else '일'
        n = c[3].number_input(f"n({u})", 1, 500, int(cs0.get('n') or (10 if unit == 'w' else 50)), 1, key=f'{K}|n',
                              help='이평선 이탈: n선 · 신고가 정체: 신고가 뒤 n봉 동안 새 신고가 없음')
        lv = c[4].number_input('그때 주식 비중(평소 대비 %)', 0, 100, int(round(float(cs0.get('level', 0.5)) * 100)), 5, key=f'{K}|lv',
                               help='0 = 전부 현금, 50 = 보유를 절반으로')
        cs = dict(index=ix, rule=rule, unit=unit, n=int(n), level=lv / 100)
        r = st.columns([1.6, 1, 1])
        if rule == 'ma':
            opts = ['ma', 'confirm', 'rising', 'band']
            re_ = r[0].selectbox('재진입', opts, index=opts.index(cs0.get('reentry')) if cs0.get('reentry') in opts else 0, key=f'{K}|re',
                                 format_func=lambda v: _RE[v].replace('이평', f'{int(n)}{u}선'))
            if re_ == 'confirm':
                cs['k'] = int(r[1].number_input('k(번 연속)', 1, 60, int(cs0.get('k') or 2), 1, key=f'{K}|k'))
            if re_ == 'band':
                cs['x'] = float(r[1].number_input('x(%)', 0.0, 30.0, float(cs0.get('x') or 2.0), 0.5, key=f'{K}|x'))
            txt = f"{_IDXN[ix]} {u}봉이 {int(n)}{u}선 아래로 마감 → 주식 {lv}% · " + _RE[re_].replace('이평', f'{int(n)}{u}선').replace('k번', f"{cs.get('k', 2)}번").replace('x%', f"{cs.get('x', 2)}%") + ' 복귀'
        else:
            hi = r[1].number_input(f"신고가 기준({u})", 10, 1000, int(cs0.get('hi') or (52 if unit == 'w' else 252)), 1, key=f'{K}|hi',
                                   help='며칠(몇 주) 최고가를 신고가로 볼지 — 52주 = 252일')
            opts = ['new_high', 'ma']
            re_ = r[0].selectbox('재진입', opts, index=opts.index(cs0.get('reentry')) if cs0.get('reentry') in opts else 0, key=f'{K}|re',
                                 format_func=lambda v: _RE['new_high'] if v == 'new_high' else _RE['m_ma'].replace('m선', f'm{u}선'))
            cs['hi'] = int(hi)
            if re_ == 'ma':
                cs['m'] = int(r[2].number_input(f"m({u})", 2, 500, int(cs0.get('m') or (10 if unit == 'w' else 50)), 1, key=f'{K}|m'))
            cs['reentry'] = re_
            txt = (f"지수({_IDXN[ix]})가 {int(hi)}{u} 신고가를 낸 뒤 {int(n)}{u} 동안 새 신고가 없음 → 주식 {lv}% · "
                   + ('다시 신고가를 내면' if re_ == 'new_high' else f"{cs.get('m')}{u}선 위로 마감하면") + ' 복귀')
        cs['reentry'] = re_
        st.caption('적용: ' + txt + ' · 판정은 그 봉 종가, 체결은 다음 주 시가')
        try:
            V = json.load(open('results/cash_gate_check.json', encoding='utf-8'))['markets'].get(m)
            if V:
                st.caption(f"🔬 사전 등록 검증({_MK[m]}, 실전 규칙 기준 {len(V['rows'])}조합): 합격 {V['n_pass']}개 "
                           f"(기준 = 수익 하락 3%p 이내 + 낙폭 5%p 이상 개선 + 이웃 n 절반 합격) — research/cash_gate_check.py")
        except Exception:
            pass
    base = json.loads(json.dumps(base))
    base['cash'] = cs
    return base


def _seg(e):
    e = e.dropna()
    if len(e) < 20:
        return None, None
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    return (float(e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1) * 100 if yrs > 0 else None, float((e / e.cummax() - 1).min()) * 100


def _halves(eq, bm, bmn, tsrc):
    """2026-11-08 — 기간을 반으로 나눠도 이기나(워크포워드 대용). 한쪽 기간에서만 이기면 그 시절 운일 가능성이 크다."""
    mid = eq.index[len(eq) // 2]
    rows = []
    for lab, a_, b_ in (('앞 절반', eq.index[0], mid), ('뒤 절반', mid, eq.index[-1])):
        sc, sm = _seg(eq.loc[a_:b_])
        bc, bm_ = _seg(bm.loc[a_:b_]) if bm is not None else (None, None)
        if sc is None:
            continue
        rows.append({'구간': f"{lab} {a_:%Y-%m}~{b_:%Y-%m}", '전략 연 수익(%)': sc, f'{bmn} 연 수익(%)': bc,
                     '차이(%p)': (sc - bc) if bc is not None else None, '전략 최대 낙폭(%)': sm, f'{bmn} 최대 낙폭(%)': bm_})
    if len(rows) == 2:
        both = all((r['차이(%p)'] or 0) > 0 for r in rows)
        st.markdown(f"**기간 나눠 보기** — {'✅ 두 구간 모두 ' + bmn + ' 보다 높음' if both else '⚠️ 한 구간에서만 이김 — 그 시절 운일 수 있음' if any((r['차이(%p)'] or 0) > 0 for r in rows) else '❌ 두 구간 모두 못 이김'}")
        tsrc('quant_engine.py (화면에서 계산)', asof=str(eq.index[-1].date()))
        st.dataframe(pd.DataFrame(rows), filters=False)


def _verdict(S, bmn):
    dc, dm = S['CAGR'] - S.get('BM_CAGR', 0), S['MDD'] - S.get('BM_MDD', 0)    # MDD 는 음수 — 클수록(0에 가까울수록) 좋음
    if dc >= 0 and dm >= 0:
        v = f"✅ **{bmn}보다 수익도 높고 낙폭도 작았습니다**"
    elif dc >= 0:
        v = f"⚠️ **수익은 {bmn}보다 높지만 낙폭이 더 컸습니다** — 감내 가능한 낙폭인지 확인이 필요합니다"
    elif dm >= 0:
        v = f"🛡️ **수익은 {bmn}보다 낮지만 낙폭은 작았습니다**"
    else:
        v = f"❌ **수익·낙폭 모두 {bmn}보다 나빴습니다**"
    n = S.get('매도건수', 0) or 0
    if n < 30:
        v += f" · 매도 {n}건뿐이라 우연일 수 있음"
    return v


def _advanced(m, base, pname):
    """⚙️ 고급 — 모든 규칙을 표·숫자로 직접 조합(말로 쓰기 · 명세 붙여넣기 포함)."""
    nl_spec = _nl_box(m)
    with st.popover('📋 명세 붙여넣기'):
        raw = st.text_area('JSON (결과 아래 "명세 보기"에서 복사한 것)', key='qb_json_in', height=160)
        if raw.strip():
            try:
                base = Q.merged(json.loads(raw)); st.caption('✅ 붙여 넣은 명세 사용 중')
            except Exception as e:
                st.error(f'JSON 오류: {e}')
    if nl_spec:
        base = Q.merged(nl_spec)
        st.caption('🤖 말로 만든 설정을 쓰는 중 — 위 전략 선택은 무시됩니다')
    K = f"{pname}|{m}|{hash(json.dumps(base, sort_keys=True)) % 10**8}"
    with st.form(f'qb_form_{K}'):
        st.markdown("**① 기간 · 리밸런싱**")
        a1, a2, a3 = st.columns(3)
        start = a1.date_input('시작', pd.Timestamp(base['start']).date(), min_value=pd.Timestamp('2014-06-01').date())
        reb = a2.number_input('리밸런싱 주기(주)', 1, 26, int(base['rebalance']))
        mxp = a3.number_input('최대 보유 종목 수', 1, 100, int(base['max_pos']))
        st.markdown(f"**② 종목 필터** — 행 번호(맨 왼쪽, 1부터)로 아래 결합식을 씁니다 · 시총 {'억원' if m == 'KR' else '$B'} · "
                    f"거래대금 {'억원' if m == 'KR' else '$M'} · n = 주 수(이평 정배열은 '10-40')")
        _fd = _fields_df(base['filters'], m)
        _fd.index = range(1, len(_fd) + 1)
        fdf = st.data_editor(_fd, num_rows='dynamic', hide_index=False, use_container_width=True,
                             column_config={'지표': st.column_config.SelectboxColumn(options=_FOPT, required=True, width='large'),
                                            'n': st.column_config.TextColumn(help='n주선·n주 수익률의 n. 이평 정배열은 "단기-장기"(예 10-40)'),
                                            '조건': st.column_config.SelectboxColumn(options=Q.OPS, required=True),
                                            '값': st.column_config.NumberColumn(), '값2': st.column_config.NumberColumn(help='between 일 때 상한'),
                                            '글자': st.column_config.TextColumn(help='contains(업종 포함) 일 때 — 쉼표로 여러 개 = 또는')})
        lgc = st.text_input('조건 결합식 — 비우면 모두 AND. 예: 1 AND 2 AND (3 OR 4) · NOT 5', value=base.get('logic') or '',
                            placeholder='1 AND 2 AND (3 OR 4)')
        r1, r2, r3 = st.columns(3)
        rk_lab = next(o for o, kk in _FKEY.items() if kk.split(':')[0] == base['rank']['field'].split(':')[0])
        rk = r1.selectbox('③ 순위 매기는 지표', _FOPT, index=_FOPT.index(rk_lab))
        rk_n = r2.text_input('순위 지표의 n(해당 시)', base['rank']['field'].split(':')[1] if ':' in base['rank']['field'] else '13')
        rk_d = r3.radio('방향', ['큰 값 먼저', '작은 값 먼저'], index=0 if base['rank'].get('desc', True) else 1, horizontal=True)

        st.markdown("**④ 비중 (요구 2·3)** — 종목 비중의 합 = 주식 비중, 나머지 = 현금")
        b1, b2, b3 = st.columns(3)
        wt = b1.selectbox('나누는 방식', list(_WT), index=list(_WT).index(base['weight']), format_func=_WT.get)
        mxw = b2.number_input('종목당 최대 비중 X(%) — 넘으면 리밸런싱 때 익절', 1.0, 100.0, float(base['max_w']) * 100, 1.0)
        ini = b3.number_input('첫 매수 = 목표 비중의 몇 %', 10.0, 100.0, float(base['entry']['init']) * 100, 5.0)
        st.caption('불타기: 진입가 대비 +n% 오르면 목표 비중의 x% 를 더 산다(위에서부터 순서대로, 최대 비중 X 까지)')
        pyr = st.data_editor(pd.DataFrame(base['entry']['pyramid'] or [], columns=['상승(%)', '추가(목표 대비 %)']).assign(**{'추가(목표 대비 %)': lambda d: d['추가(목표 대비 %)'] * 100}),
                             num_rows='dynamic', hide_index=True, use_container_width=True)

        st.markdown("**⑤ 주식 vs 현금 (요구 1)** — 지수가 약하거나 정한 달이 아니면 주식 비중을 줄인다")
        e1, e2, e3, e4 = st.columns(4)
        ex = base['exposure']
        bse = e1.number_input('평소 주식 비중(%)', 0.0, 100.0, float(ex.get('base', 1.0)) * 100, 5.0)
        ixo = [''] + _IDX[m]
        ixs = e2.selectbox('기준 지수', ixo, index=ixo.index(ex.get('index') or '') if (ex.get('index') or '') in ixo else 0, format_func=_IDXN.get)
        ma = e3.number_input('지수 n주선(일봉 토글 켜면 n일선)', 2, 200, int(ex.get('ma') or 40))
        blw = e4.number_input('지수가 그 아래면 주식 비중(평소 대비 %)', 0.0, 100.0, float(ex.get('below', 0.0)) * 100, 10.0)
        ix_daily = st.toggle('지수 이탈을 일봉 n일선으로 (기본은 n주선)', value=bool(ex.get('daily')), disabled=ixs == 'MKT',
                             help='"지수 5일선 이탈여부"처럼 주봉보다 빨리 반응해야 할 때. 소속 시장(MKT) 게이트는 이미 자체 n(기본 5)이 '
                                  '있어 이 토글과 무관합니다.')
        mon = st.multiselect('주식을 들고 있을 달 (할로윈 = 11~4월)', list(range(1, 13)), default=ex.get('months') or list(range(1, 13)),
                             format_func=lambda x: f'{x}월')

        st.markdown("**⑥ 탈출 (요구 4·5)** — 손절선은 오를수록 올라가고 내려가지 않는다")
        x1, x2, x3 = st.columns(3)
        xe = base['exit']
        stp = x1.number_input('손절: 진입가 대비 −y%(0=끔)', 0.0, 90.0, float(xe.get('stop') or 0), 1.0)
        mh = x2.number_input('최소 보유(주) — 이 기간엔 래칫·신호 무시', 0, 156, int(xe.get('min_hold') or 0))
        cd = x3.number_input('판 뒤 다시 사지 않는 기간(주)', 0, 52, int(xe.get('cooldown') or 0))
        daily_ex = st.toggle('고점·손절·래칫·ma_break 를 일봉으로 (매수·리밸런싱은 그대로 주봉)', value=bool(xe.get('daily')),
                             help='보유 중 고점을 그 주 날짜별로 쫓고, 스탑을 건드린 날의 실제 가격으로 판다("고점대비 하락폭"). '
                                  '탈출 신호의 ma_break 는 n 이 "일"이 된다("5일선"). 종목마다 외부에서 일봉을 새로 받아 와 '
                                  '**처음 돌리면 느리다**(이후 캐시). 못 받으면 조용히 주봉 근사로.')
        st.caption('래칫: 진입 후 최고 수익이 +a% 를 넘으면 손절선을 고점 대비 −b% 로 끌어올린다')
        trl = st.data_editor(pd.DataFrame(xe.get('trail') or [], columns=['최고 수익(%) 이상', '고점 대비(−%)']),
                             num_rows='dynamic', hide_index=True, use_container_width=True)
        st.caption('탈출 신호 — 하나라도 뜨면 다음 주 시가에 판다. 파라미터 칸은 해당 신호에만 씀(n·level·vol_x·pct·m, 펀더멘털은 지표·조건·값)')
        srows = []
        for sg in xe.get('signals') or []:
            lab = next(o for o, kk in _SOPT.items() if kk == sg['type'])
            fl = next((o for o, kk in _FKEY.items() if kk.split(':')[0] == str(sg.get('field', '')).split(':')[0]), None)
            srows.append({'신호': lab, 'n/m': sg.get('n') or sg.get('m'), 'level/배수/%': sg.get('level') or sg.get('vol_x') or sg.get('pct') or sg.get('x'),
                          '지표': fl, '조건': sg.get('op'), '값': sg.get('value')})
        sdf = st.data_editor(pd.DataFrame(srows, columns=['신호', 'n/m', 'level/배수/%', '지표', '조건', '값']), num_rows='dynamic',
                             hide_index=True, use_container_width=True,
                             column_config={'신호': st.column_config.SelectboxColumn(options=list(_SOPT), required=True, width='large'),
                                            '지표': st.column_config.SelectboxColumn(options=_FOPT),
                                            '조건': st.column_config.SelectboxColumn(options=['<', '>', '<=', '>=', '=='])})
        go_ = st.form_submit_button('▶ 이 설정으로 실행', type='primary')

    # 화면 값 → 명세
    sigs = []
    for r in sdf.dropna(subset=['신호']).to_dict('records'):
        t = _SOPT[r['신호']]; a, b = r.get('n/m'), r.get('level/배수/%')
        ok = lambda v: v is not None and v == v
        d = dict(type=t)
        if t in ('ma_break', 'rsi_down'):
            d['n'] = int(a) if ok(a) else (5 if t == 'ma_break' else 14)
        if t == 'rsi_down':
            d['level'] = float(b) if ok(b) else 70.0
        if t == 'doji_vol':
            d['vol_x'] = float(b) if ok(b) else 2.0
        if t == 'bear':
            d['pct'] = float(b) if ok(b) else 7.0
        if t == 'rank_out':
            d['m'] = int(a) if ok(a) else int(mxp) * 2
        if t == 'climax':                                            # 화면에선 '40주선 위 x%' 전량 매도만(검증 결과 뒤 확장)
            d.update(rule='ext', x=float(b) if ok(b) else 70.0)
        if t == 'field':
            if not r.get('지표'):
                continue
            k = _FKEY[r['지표']]
            d.update(field=k if ':' not in k else f"{k.split(':')[0]}:{int(a) if ok(a) else 20}",
                     op=r.get('조건') or '<', value=float(r['값']) if ok(r.get('값')) else 0.0)
        sigs.append(d)
    rkk = _FKEY[rk]
    fdf = fdf.reset_index(drop=True)
    _filt = _fields_from(fdf, m)
    try:
        Q.parse_logic(lgc, len(_filt))
        import re as _re
        _used = {int(x) for x in _re.findall(r'\d+', lgc)} if lgc.strip() else set(range(1, len(_filt) + 1))
        _unused = [i for i in range(1, len(_filt) + 1) if i not in _used]
        st.caption(f"적용 조건: {lgc.strip() or '모두 AND'}" + (f" · ⚠️ 결합식에 없는 조건 {_unused}번은 쓰이지 않습니다" if _unused else ''))
    except Exception as e:
        st.error(f'조건 결합식 오류 → 모두 AND 로 실행합니다: {e}')
        lgc = ''
    spec = dict(market=m, start=str(start), rebalance=int(reb), max_pos=int(mxp), filters=_filt, logic=lgc,
                rank=dict(field=rkk if ':' not in rkk else f"{rkk.split(':')[0]}:{str(rk_n).strip() or '13'}", desc=rk_d == '큰 값 먼저'),
                weight=wt, max_w=mxw / 100,
                exposure=dict(base=bse / 100, index=ixs, ma=int(ma), below=blw / 100, months=sorted(mon) or list(range(1, 13)),
                              daily=bool(ix_daily)),
                entry=dict(init=ini / 100, pyramid=[[float(a), float(b) / 100] for a, b in pyr.dropna().values.tolist()]),
                exit=dict(stop=stp, trail=[[float(a), float(b)] for a, b in trl.dropna().values.tolist()], min_hold=int(mh),
                          cooldown=int(cd), signals=sigs, daily=bool(daily_ex)),
                cost=0.003)
    if base.get('cash'):
        spec['cash'] = base['cash']                                    # 🏦 현금 확대는 위 상자에서(고급 표 밖)
    return spec


def render(mkt_sel: str, tsrc):
    st.markdown("#### 🧪 퀀트 백테스트")
    st.caption("전략을 고르면 바로 계산합니다. 주봉 종가로 판단 → 다음 주 시가 매매 · 손절은 주중 스탑 · 편도 0.3% · 상장폐지 종목 포함.")
    mk = [m for m in (['US', 'KR'] if mkt_sel == '전체' else [mkt_sel])]
    m = mk[0] if len(mk) == 1 else st.segmented_control('시장', mk, default='KR', key='qb_m', format_func=_MK.get) or 'KR'
    pname, base = _easy(m)
    if not st.session_state.get('qb_adv'):
        base = _filter_bar(m, base, pname)
    else:
        st.caption('⚙️ 고급 모드 — 종목 필터는 아래 ② 표에서 고칩니다(상단 필터 바는 숨김).')
    base = _cash_box(m, base, pname)
    if st.toggle('⚙️ 직접 조합 (고급 — 필터·결합식·불타기·래칫·탈출 신호·말로 쓰기)', key='qb_adv'):
        spec = _advanced(m, base, pname)
    else:
        spec = base

    try:
        with st.spinner(f'{_MK[m]} 패널 불러와 계산 중… (처음 한 번은 수십 초)'):
            r = _run(m, json.dumps(spec, sort_keys=True))
    except Exception as e:
        st.error(f'백테스트 실패: {type(e).__name__}: {e}')
        st.caption('패널이 아직 없으면 GitHub Actions "quant-panel" 을 실행해야 합니다: https://github.com/pcy604/stock-dashboard/actions/workflows/quant-panel.yml')
        return
    S, eq, bm, T, Hd = r['stats'], r['equity'], r['bench'], r['trades'], r['holdings']
    if not S:
        st.info('결과가 없습니다 — 시작일·필터를 확인해 주십시오.')
        return

    # ── 결과 ──
    bmn = _IDXN[_BM[m]]
    if r.get('note'):
        st.caption(r['note'])
    st.markdown(_verdict(S, bmn))
    k1, k2, k3, k4 = st.columns(4)
    k1.metric('연 수익률(CAGR)', f"{S['CAGR']:.1f}%", f"{S['CAGR'] - S.get('BM_CAGR', 0):+.1f}%p vs {bmn}")
    k2.metric('최대 낙폭(MDD)', f"{S['MDD']:.1f}%", f"{S['MDD'] - S.get('BM_MDD', 0):+.1f}%p vs {bmn}")
    k3.metric('샤프', f"{S['Sharpe']:.2f}" if S.get('Sharpe') is not None else '-', f"수익÷낙폭 {S['Calmar']:.2f}" if S.get('Calmar') else None, delta_color='off')
    k4.metric('승률 · 손익비', f"{S.get('승률') or 0:.0f}% · {S.get('손익비') or 0:.2f}", f"매도 {S.get('매도건수', 0):,}건", delta_color='off')
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values * 100, name='전략', line=dict(color='#D9363E', width=2)))
    if bm is not None:
        fig.add_trace(go.Scatter(x=bm.index, y=bm.values * 100, name=bmn, line=dict(color='#7C8AA5', width=1.5)))
    fig.add_trace(go.Scatter(x=r['exposure'].index, y=r['exposure'].values * 100, name='주식 비중(%)', yaxis='y2',
                             line=dict(color='#2453C8', width=0.8), fill='tozeroy', fillcolor='rgba(36,83,200,0.08)'))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation='h', y=1.08, x=0),
                      yaxis=dict(type='log', title='100에서 시작'), yaxis2=dict(overlaying='y', side='right', range=[0, 300], showgrid=False, title=None))
    st.plotly_chart(fig, use_container_width=True)
    _halves(eq, bm, bmn, tsrc)

    with st.expander('📅 월별·연도별 수익', expanded=True):
        _yearly(eq, bm, bmn, m, tsrc)
    with st.expander(f"📜 매매 내역 · 매도 {S.get('매도건수', 0):,}건"):
        _trades(T, eq, m, tsrc)
    with st.expander('📦 마지막 주 보유'):
        _holdings(Hd, eq, tsrc)
    with st.expander('🧾 명세 보기 (복사해 두면 고급 → 명세 붙여넣기로 되살림)'):
        st.code(json.dumps(spec, ensure_ascii=False), language='json')
    st.caption('⚠️ 백테스트는 과거 한 경로입니다. 여러 설정을 돌려 가장 좋은 것을 고르면 숫자가 부풀려집니다 — 다른 시작 연도·인접 값에서도 결과가 유지되는지 확인해 주십시오.')


def _monthly_frame(eq):
    """주봉 자산곡선 → monthly_stats 형식(연도×월 + 연간). 주 라벨(월요일) 값 = 그 주 마지막 거래일 종가라
    금요일로 옮겨 달을 가른다(3/30 주 = 4/3 마감 → 4월). 첫 달도 빠지지 않게 시작 직전 값 1.0 을 둔다."""
    import monthly_stats as MS
    s = eq.copy()
    s.index = pd.DatetimeIndex(s.index) + pd.Timedelta(days=4)
    s = pd.concat([pd.Series([1.0 if abs(float(eq.iloc[0]) - 1) < 1e-9 else float(eq.iloc[0])],
                             index=[s.index[0] - pd.Timedelta(days=7)]), s])
    return MS.build(s, max_years=40)


def _yearly(eq, bm, bmn, m, tsrc):
    """2026-11-08 차니 — 연도별만이 아니라 월별로: 종목분석 탭 '📆 월별 상승률 통계'(monthly_stats)와 같은 표."""
    import monthly_stats as MS
    view = st.segmented_control('보기', ['전략', bmn, f'차이 (전략 − {bmn})'], default='전략', key=f'qb_mview|{m}',
                                label_visibility='collapsed') or '전략'
    raw_s, sum_s = _monthly_frame(eq)
    raw_b, sum_b = _monthly_frame(bm / bm.iloc[0]) if bm is not None and len(bm) else (None, None)
    if raw_s is None:
        st.caption('기간이 1년 미만이라 월별 표를 만들 수 없습니다.')
        return
    if view == '전략':
        raw, summ = raw_s, sum_s
    elif view == bmn and raw_b is not None:
        raw, summ = raw_b, sum_b
    elif raw_b is not None:
        a, b = raw_s.set_index('연도'), raw_b.set_index('연도')
        raw = (a - b.reindex(a.index)).reset_index()
        summ = None
    else:
        raw, summ = raw_s, sum_s

    def cfg(first):
        c = {first: st.column_config.TextColumn(first, width=70)}
        c.update({k: st.column_config.NumberColumn(k, format='%.1f', width=54) for k in MS.MONTHS})
        c['연간'] = st.column_config.NumberColumn('연간', format='%.1f', width=66)
        return c
    tsrc(f'quant_engine.py · 패널 quant_panel_{m} (화면에서 계산) · 단위 %' + (' · 차이 = %p' if view.startswith('차이') else ''),
         asof=str(eq.index[-1].date()))
    st.dataframe(raw, column_config=cfg('연도'), filters=False, footer=False)
    if summ is not None and len(summ):
        _avg = summ[summ['구분'].str.endswith('평균')].reset_index(drop=True)
        _win = summ[summ['구분'].str.endswith('승률')].reset_index(drop=True)
        tsrc(f'quant_engine.py · 패널 quant_panel_{m}', asof=str(eq.index[-1].date()))
        st.dataframe(_avg, column_config=cfg('구분'), filters=False)
        tsrc(f'quant_engine.py · 패널 quant_panel_{m}', asof=str(eq.index[-1].date()))
        st.dataframe(_win, column_config=cfg('구분'), filters=False, color=False)
    st.caption("칸 = 그 달 수익률(%), 연간 = 전년 말 대비(첫 해는 시작일부터, 올해는 연초부터). 주봉 자산곡선이라 달의 경계는 "
               "그 주 마지막 거래일 기준(월말이 주 중간이면 며칠이 옆 달로 갈 수 있음). 승률 = 그 달이 오른 해의 비율.")


def _trades(T, eq, m, tsrc):
    if len(T):
        # 2026-11-08 — date 객체는 AgGrid 가 못 그려 칸이 비었다 → 글자로. 체결 = 그 주 첫 거래일 시가(주 라벨 = 월요일)
        TT = T.copy()
        _d = pd.to_datetime(TT['날짜'])
        TT['날짜'] = _d.dt.strftime('%Y-%m-%d')
        TT.insert(1, '연월', _d.dt.strftime('%Y-%m'))
        TT = TT.rename(columns={'날짜': '체결 주(월요일)'})
        TT = TT.rename(columns={'가격': '수정주가(현지)', '금액비중': '금액(자산 대비 %)', '수익률': '수익률(%)'})
        tsrc('quant_engine.py (화면에서 계산)', asof=str(eq.index[-1].date()))
        st.dataframe(TT.iloc[::-1].reset_index(drop=True), hide_index=True, use_container_width=True, height=380)
        st.download_button('⬇ 매매 내역 CSV', TT.to_csv(index=False).encode('utf-8-sig'), f'trades_{m}.csv', 'text/csv')
        why = T[T.구분 == '매도'].groupby('사유').수익률.agg(['count', 'median']).sort_values('count', ascending=False)
        st.caption('수정주가 = 분할·병합·무상증자·감자를 반영해 과거 가격을 이어 붙인 값(한국은 KRX 등락률 기준) — 그 당시 화면 호가와 다를 수 있고, 수익률은 정확합니다.')
        st.caption('매도 사유별: ' + ' · '.join(f"{i} {int(c)}건(중앙 {md:+.0f}%)" for i, (c, md) in why.iterrows()))


def _holdings(Hd, eq, tsrc):
    if len(Hd) and Hd.PER.notna().any():
        h = Hd.dropna(subset=['PER']); ey = (h.비중 / h.PER).sum() / h.비중.sum()
        st.metric('지금 보유 PER (요구 6)', f"{1 / ey:.1f}배" if ey > 0 else '-', f"재무 커버 {h.비중.sum() / max(Hd.비중.sum(), 1e-9) * 100:.0f}%", delta_color='off',
                  help='1 ÷ Σ(비중 × 1/PER). 적자 종목(PER 없음)은 제외')
    else:
        st.metric('지금 보유 PER (요구 6)', '-')

