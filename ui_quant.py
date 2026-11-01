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
_IDX = {'US': ['SPX', 'NDX'], 'KR': ['KOSPI']}
_IDXN = {'SPX': 'S&P500', 'NDX': '나스닥100', 'KOSPI': '코스피', '': '없음'}
# 필드 선택지: '이름 (키)' — :n 이 붙은 것은 n 칸을 쓴다
_FOPT = [f"{v[0]} ({k.split(':')[0]})" for k, v in Q.FIELDS.items()]
_FKEY = {f"{v[0]} ({k.split(':')[0]})": k for k, v in Q.FIELDS.items()}
_SOPT = {f"{v[0]} ({k})": k for k, v in Q.EXIT_SIGNALS.items()}
_WT = {'equal': '동일 비중', 'rank': '순위 가중(1등 더 많이)', 'mcap': '시총 가중', 'inv_vol': '변동성 역가중(덜 흔들리는 종목 더 많이)'}

PRESETS = {
    'RS 상위 회전 (모멘텀)': dict(filters=[dict(field='marcap', op='>=', value='LIQ')], rank=dict(field='rs', desc=True)),
    '주도주: RS≥80 × 흑자전환': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80),
                                            dict(field='op_turn', op='==', value=1)], rank=dict(field='rs', desc=True),
                                   exit=dict(signals=[dict(type='ma_break', n=20), dict(type='field', field='op_yoy', op='<', value=-30)])),
    '저PER 가치 + 이평 위': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='per', op='between', value=[0, 12]),
                                     dict(field='ma_gap:40', op='>', value=0)], rank=dict(field='per', desc=False)),
    '할로윈 (11~4월만 주식)': dict(filters=[dict(field='marcap', op='>=', value='LIQ')], rank=dict(field='marcap', desc=True),
                                exposure=dict(months=[11, 12, 1, 2, 3, 4])),
    '차니식: 반만 사고 불타기 + 래칫': dict(filters=[dict(field='marcap', op='>=', value='LIQ'), dict(field='rs', op='>=', value=80)],
                                    rank=dict(field='rs', desc=True), max_w=0.15,
                                    entry=dict(init=0.5, pyramid=[[20, 0.25], [40, 0.25]]),
                                    exit=dict(stop=15, trail=[[0, 25], [50, 20], [100, 15]], cooldown=4,
                                              signals=[dict(type='doji_vol', vol_x=2), dict(type='macd_neg')])),
}
_LIQ = {'US': 1e9, 'KR': 1e11}


@st.cache_resource(show_spinner=False, ttl=3600 * 12)
def _panel(m):
    loc = f'results/quant_panel_{m}.parquet'
    if os.path.exists(loc):
        df = pd.read_parquet(loc)
    else:
        with urllib.request.urlopen(REL.format(m=m), timeout=60) as r:
            df = pd.read_parquet(io.BytesIO(r.read()))
    df = df.drop(columns=[c for c in ('market',) if c in df.columns])   # 안 쓰는 문자열 열(메모리)
    df['date'] = pd.to_datetime(df['date'])
    P = Q.Panel(df)
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


@st.cache_data(ttl=3600, show_spinner=False, max_entries=4)
def _run(m, spec_json):
    spec = json.loads(spec_json)
    P = _panel(m)
    ex = spec.get('exposure') or {}
    ixn = ex.get('index') or ''
    bm = _IDX[m][0]
    r = Q.run(P, spec, index_px=_index(ixn) if ixn else None, bench_px=_index(bm))
    return r


def _fill(spec, m):
    s = json.loads(json.dumps(spec))
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
        c2.caption(f'이번 접속에서 {used}/15회 사용 · AI 는 설정만 만들고, 실행은 아래 같은 엔진이 합니다. 결과 설정은 반드시 눈으로 확인하세요.')
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


def render(mkt_sel: str, tsrc):
    st.markdown("#### 🧪 퀀트 백테스트 — 고르는 법 · 담는 비중 · 불타기 · 탈출을 직접 조합")
    st.caption("주봉 기준(5주선 ≈ 25일선). 매주 종가로 판단 → 다음 주 시가에 매매, 손절·래칫만 주중 스탑. 편도 0.3%. "
               "재무는 그 주에 알 수 있던 값만(미국 공시일 · 한국 분기말 +45/90일). 상장폐지 종목 포함(마지막 가격에 정리).")
    mk = [m for m in (['US', 'KR'] if mkt_sel == '전체' else [mkt_sel])]
    m = mk[0] if len(mk) == 1 else st.segmented_control('이 백테스트의 시장(상단이 전체라서)', mk, default='US', key='qb_m',
                                                        format_func=_MK.get) or 'US'

    nl_spec = _nl_box(m)
    pc, jc = st.columns([2, 1])
    pname = pc.selectbox('예시 전략 불러오기 — 여기서 시작해 아래를 고치세요', list(PRESETS), key='qb_preset')
    base = Q.merged(_fill(PRESETS[pname], m))
    with jc.popover('📋 명세 붙여넣기'):
        raw = st.text_area('JSON (아래 "명세 보기"에서 복사한 것)', key='qb_json_in', height=160)
        if raw.strip():
            try:
                base = Q.merged(json.loads(raw)); st.caption('✅ 붙여 넣은 명세 사용 중')
            except Exception as e:
                st.error(f'JSON 오류: {e}')
    if nl_spec:
        base = Q.merged(nl_spec)
        pc.caption('🤖 말로 만든 설정을 쓰는 중 — 예시 전략 선택은 무시됩니다')
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
        ma = e3.number_input('지수 n주선', 2, 200, int(ex.get('ma') or 40))
        blw = e4.number_input('지수가 그 아래면 주식 비중(평소 대비 %)', 0.0, 100.0, float(ex.get('below', 0.0)) * 100, 10.0)
        mon = st.multiselect('주식을 들고 있을 달 (할로윈 = 11~4월)', list(range(1, 13)), default=ex.get('months') or list(range(1, 13)),
                             format_func=lambda x: f'{x}월')

        st.markdown("**⑥ 탈출 (요구 4·5)** — 손절선은 오를수록 올라가고 내려가지 않는다")
        x1, x2, x3 = st.columns(3)
        xe = base['exit']
        stp = x1.number_input('손절: 진입가 대비 −y%(0=끔)', 0.0, 90.0, float(xe.get('stop') or 0), 1.0)
        mh = x2.number_input('최소 보유(주) — 이 기간엔 래칫·신호 무시', 0, 156, int(xe.get('min_hold') or 0))
        cd = x3.number_input('판 뒤 다시 사지 않는 기간(주)', 0, 52, int(xe.get('cooldown') or 0))
        st.caption('래칫: 진입 후 최고 수익이 +a% 를 넘으면 손절선을 고점 대비 −b% 로 끌어올린다')
        trl = st.data_editor(pd.DataFrame(xe.get('trail') or [], columns=['최고 수익(%) 이상', '고점 대비(−%)']),
                             num_rows='dynamic', hide_index=True, use_container_width=True)
        st.caption('탈출 신호 — 하나라도 뜨면 다음 주 시가에 판다. 파라미터 칸은 해당 신호에만 씀(n·level·vol_x·pct·m, 펀더멘털은 지표·조건·값)')
        srows = []
        for sg in xe.get('signals') or []:
            lab = next(o for o, kk in _SOPT.items() if kk == sg['type'])
            fl = next((o for o, kk in _FKEY.items() if kk.split(':')[0] == str(sg.get('field', '')).split(':')[0]), None)
            srows.append({'신호': lab, 'n/m': sg.get('n') or sg.get('m'), 'level/배수/%': sg.get('level') or sg.get('vol_x') or sg.get('pct'),
                          '지표': fl, '조건': sg.get('op'), '값': sg.get('value')})
        sdf = st.data_editor(pd.DataFrame(srows, columns=['신호', 'n/m', 'level/배수/%', '지표', '조건', '값']), num_rows='dynamic',
                             hide_index=True, use_container_width=True,
                             column_config={'신호': st.column_config.SelectboxColumn(options=list(_SOPT), required=True, width='large'),
                                            '지표': st.column_config.SelectboxColumn(options=_FOPT),
                                            '조건': st.column_config.SelectboxColumn(options=['<', '>', '<=', '>=', '=='])})
        go_ = st.form_submit_button('▶ 백테스트 실행', type='primary')

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
                exposure=dict(base=bse / 100, index=ixs, ma=int(ma), below=blw / 100, months=sorted(mon) or list(range(1, 13))),
                entry=dict(init=ini / 100, pyramid=[[float(a), float(b) / 100] for a, b in pyr.dropna().values.tolist()]),
                exit=dict(stop=stp, trail=[[float(a), float(b)] for a, b in trl.dropna().values.tolist()], min_hold=int(mh),
                          cooldown=int(cd), signals=sigs),
                cost=0.003)
    with st.expander('🧾 명세 보기 (복사해 두면 그대로 다시 불러올 수 있음)'):
        st.code(json.dumps(spec, ensure_ascii=False), language='json')

    try:
        with st.spinner(f'{_MK[m]} 패널 불러와 계산 중… (처음 한 번은 수십 초)'):
            r = _run(m, json.dumps(spec, sort_keys=True))
    except Exception as e:
        st.error(f'백테스트 실패: {type(e).__name__}: {e}')
        st.caption('패널이 아직 없으면 GitHub Actions "quant-panel" 을 실행해야 합니다: https://github.com/pcy604/stock-dashboard/actions/workflows/quant-panel.yml')
        return
    S, eq, bm, T, Hd = r['stats'], r['equity'], r['bench'], r['trades'], r['holdings']
    if not S:
        st.info('결과가 없습니다 — 시작일·필터를 확인하세요.')
        return

    # ── 결과 ──
    bmn = _IDXN[_IDX[m][0]]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric('연 수익률(CAGR)', f"{S['CAGR']:.1f}%", f"{S['CAGR'] - S.get('BM_CAGR', 0):+.1f}%p vs {bmn}")
    k2.metric('최대 낙폭(MDD)', f"{S['MDD']:.1f}%", f"{S['MDD'] - S.get('BM_MDD', 0):+.1f}%p vs {bmn}")
    k3.metric('샤프', f"{S['Sharpe']:.2f}" if S.get('Sharpe') is not None else '-', f"수익÷낙폭 {S['Calmar']:.2f}" if S.get('Calmar') else None, delta_color='off')
    k4.metric('승률 · 손익비', f"{S.get('승률') or 0:.0f}% · {S.get('손익비') or 0:.2f}", f"매도 {S.get('매도건수', 0):,}건", delta_color='off')
    if len(Hd) and Hd.PER.notna().any():
        h = Hd.dropna(subset=['PER']); ey = (h.비중 / h.PER).sum() / h.비중.sum()
        k5.metric('지금 보유 PER (요구 6)', f"{1 / ey:.1f}배" if ey > 0 else '-', f"재무 커버 {h.비중.sum() / max(Hd.비중.sum(), 1e-9) * 100:.0f}%", delta_color='off',
                  help='1 ÷ Σ(비중 × 1/PER). 적자 종목(PER 없음)은 제외')
    else:
        k5.metric('지금 보유 PER (요구 6)', '-')

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=eq.index, y=eq.values * 100, name='전략', line=dict(color='#D9363E', width=2)))
    if bm is not None:
        fig.add_trace(go.Scatter(x=bm.index, y=bm.values * 100, name=bmn, line=dict(color='#7C8AA5', width=1.5)))
    fig.add_trace(go.Scatter(x=r['exposure'].index, y=r['exposure'].values * 100, name='주식 비중(%)', yaxis='y2',
                             line=dict(color='#2453C8', width=0.8), fill='tozeroy', fillcolor='rgba(36,83,200,0.08)'))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation='h', y=1.08, x=0),
                      yaxis=dict(type='log', title='100에서 시작'), yaxis2=dict(overlaying='y', side='right', range=[0, 300], showgrid=False, title=None))
    st.plotly_chart(fig, use_container_width=True)

    yr = pd.DataFrame({'전략(%)': eq.resample('YE').last().pct_change() * 100})
    yr.iloc[0, 0] = (eq.resample('YE').last().iloc[0] / eq.iloc[0] - 1) * 100
    if bm is not None:
        b = bm.resample('YE').last(); yr[f'{bmn}(%)'] = b.pct_change() * 100; yr.iloc[0, 1] = (b.iloc[0] / bm.iloc[0] - 1) * 100
        yr['차이(%p)'] = yr['전략(%)'] - yr[f'{bmn}(%)']
    yr.insert(0, '연도', yr.index.year)
    tsrc(f'quant_engine.py · 패널 quant_panel_{m}', asof=str(eq.index[-1].date()))
    st.dataframe(yr.reset_index(drop=True), hide_index=True, use_container_width=True, filters=False,
                 column_config={'연도': st.column_config.NumberColumn(format='%d')})

    st.markdown('##### 📜 매매 내역 (요구 8) — 모든 매수·불타기·덜기·매도와 사유')
    if len(T):
        TT = T.copy(); TT['날짜'] = pd.to_datetime(TT['날짜']).dt.date
        TT = TT.rename(columns={'날짜': '체결 주(월)'})
        TT = TT.rename(columns={'가격': '가격(현지)', '금액비중': '금액(자산 대비 %)', '수익률': '수익률(%)'})
        tsrc('quant_engine.py (화면에서 계산)', asof=str(eq.index[-1].date()))
        st.dataframe(TT.iloc[::-1].reset_index(drop=True), hide_index=True, use_container_width=True, height=380)
        st.download_button('⬇ 매매 내역 CSV', TT.to_csv(index=False).encode('utf-8-sig'), f'trades_{m}.csv', 'text/csv')
        why = T[T.구분 == '매도'].groupby('사유').수익률.agg(['count', 'median']).sort_values('count', ascending=False)
        st.caption('매도 사유별: ' + ' · '.join(f"{i} {int(c)}건(중앙 {md:+.0f}%)" for i, (c, md) in why.iterrows()))
    st.markdown('##### 📦 마지막 주 보유')
    if len(Hd):
        tsrc('quant_engine.py (화면에서 계산)', asof=str(eq.index[-1].date()))
        st.dataframe(Hd.rename(columns={'비중': '비중(%)', '수익률': '수익률(%)', '고점대비': '고점대비(%)', '불타기': '불타기(회)', 'PER': 'PER(배)'}),
                     hide_index=True, use_container_width=True)
    else:
        st.caption('보유 없음(현금)')
    st.caption('⚠️ 백테스트는 과거 한 경로입니다. 여러 설정을 돌려 가장 좋은 것을 고르면 그 숫자는 부풀려집니다(과최적화) — '
               '마음에 드는 설정은 다른 시작일·이웃 값에서도 비슷한지 확인하세요.')
