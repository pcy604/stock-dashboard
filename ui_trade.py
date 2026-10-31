# -*- coding: utf-8 -*-
"""🎮 매매 실험실 — 종목 게임(A) × 지수 게임(B), 일봉·스탑 체결 (2026-10-31)
엔진 trade_rules.py · 표본 results/trade_px.parquet(🪜 래칫과 같은 승자100·대조100) · 사전 등록 결과 results/trade_lab.json"""
import json
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import trade_rules as T
import stock_rules as R

PX, IX, RES = 'results/trade_px.parquet', 'results/trade_idx.parquet', 'results/trade_lab.json'
_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
_RE = {'none': '안 함', 'sell_px': '판 가격 재돌파(스탑)'}


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _load(mt):
    P = pd.read_parquet(PX)
    P['date'] = pd.to_datetime(P['date'])
    I = pd.read_parquet(IX)
    I.index = pd.to_datetime(I.index)
    win = {}
    try:
        win = {m: pd.Timestamp(v['window'][0]) for m, v in json.load(open('results/stock_ratchet.json', encoding='utf-8'))['info'].items() if 'window' in v}
    except Exception:
        pass
    S = []
    for (mkt, grp, sym), g in P.groupby(['market', 'grp', 'sym'], sort=False):
        g = g.sort_values('date')
        idx = pd.DatetimeIndex(g.date)
        s = int(np.searchsorted(idx, win.get(mkt, idx[0])))
        if s < len(idx) - 250:
            S.append(dict(mkt=mkt, grp=grp, sym=sym, name=g.name.iloc[0], idx=idx, o=g.o.values.astype(float),
                          h=g.h.values.astype(float), l=g.l.values.astype(float), c=g.c.values.astype(float), s=s))
    return S, I


def _ix(I, name, idx):
    return I[name].reindex(idx).ffill().values.astype(float) if name in I else None


@st.cache_data(ttl=3600, show_spinner=False, max_entries=24)
def _run(a_json, b_json, ixmap_json, mt, mkts):
    a, b, ixm = json.loads(a_json), json.loads(b_json), json.loads(ixmap_json)
    S, I = _load(mt)
    rows = []
    for x in S:
        if x['mkt'] not in mkts:
            continue
        ix = _ix(I, ixm[x['mkt']], x['idx'])
        r = T.summarize(x['o'], x['h'], x['l'], x['c'], ix, x['s'], a, b)
        rows.append(dict(market=x['mkt'], grp=x['grp'], sym=x['sym'], name=x['name'], **r))
    P = pd.DataFrame(rows)
    agg = []
    for (m, g), G in P.groupby(['market', 'grp'], sort=False):
        q = R.aggregate(G.to_dict('records'))
        agg.append({'시장': _MK[m], '그룹': g, '종목 수': q['n'], '규칙 배수 중앙(×)': q['mult_med'], '그냥 보유 배수 중앙(×)': q['bh_med'],
                    '규칙 MDD 중앙(%)': q['mdd_med'] * 100, '그냥 보유 MDD 중앙(%)': q['bh_mdd_med'] * 100,
                    'MDD 개선(%p)': (q['mdd_med'] - q['bh_mdd_med']) * 100, '거래 수 중앙': q['trades_med'],
                    '종목 게임 보유(%)': q['exposure_med'] * 100, '손실 종목(%)': q['lose'] * 100})
    return pd.DataFrame(agg), P


def render(mkt_sel: str, tsrc):
    st.caption("**두 게임을 따로 둡니다.** 🅰 종목 게임 = 주도주 필터로 고른 종목을 언제 들고 내리나(손절·사다리·재매수). "
               "🅱 지수 게임 = 종목이 보유 상태일 때 지수(S&P500·나스닥·러셀 / 코스피·코스닥)를 보고 실제로 몇 %를 담나. "
               "**일봉 · 스탑 체결**: 손절은 손절선에, 재매수는 판 가격에(갭이면 시가). 지수 비중은 그날 종가로 정해 다음 날 시가에. 편도 0.3%.")
    st.warning("⚠️ 승자100은 결과를 보고 고른 표본입니다 — 수익률은 기대 수익이 아닙니다. **대조100(무작위)에서 MDD 가 줄고 덜 잃는지**와 함께 보세요.", icon=None)
    if not os.path.exists(PX):
        st.info("일봉 표본이 아직 없습니다 — GitHub Actions 'research-ratchet' 실행 후 생깁니다.")
        return
    mt = os.path.getmtime(PX)
    S, I = _load(mt)
    mkts = tuple(m for m in (['US', 'KR'] if mkt_sel == '전체' else [mkt_sel]) if any(x['mkt'] == m for x in S))
    if not mkts:
        st.info("이 시장의 일봉 표본이 아직 없습니다.")
        return

    # ── ① 사전 등록 30조합 ──────────────────────────
    res = {}
    try:
        res = json.load(open(RES, encoding='utf-8'))
    except Exception:
        pass
    if res.get('results'):
        st.markdown("##### 📋 사전 등록 30조합 (🅰 6 × 🅱 5) — 판정: 대조 MDD 10%p↑ 개선 · 승자 배수 60%↑ 유지 · 대조 배수 악화 없음")
        rows = []
        for k, v in res['results'].items():
            an, bn = k.split(' ‖ ')
            for m in mkts:
                w, c = v.get(f'{m}|승자100'), v.get(f'{m}|대조100')
                if w and c:
                    ok = (res.get('verdict', {}).get(k, {}).get(m) or {}).get('ok')
                    rows.append({'시장': _MK[m], '🅰 종목 게임': an, '🅱 지수 게임': bn, '승자 배수(×)': w['mult_med'], '승자 MDD(%)': w['mdd_med'] * 100,
                                 '대조 배수(×)': c['mult_med'], '대조 MDD(%)': c['mdd_med'] * 100, '판정': '✅' if ok else '—'})
        tsrc('research/trade_lab.py (사전 등록 4c7549c)', path=RES)
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={
            '승자 배수(×)': st.column_config.NumberColumn(format='%.2f'), '대조 배수(×)': st.column_config.NumberColumn(format='%.2f'),
            '승자 MDD(%)': st.column_config.NumberColumn(format='%.0f'), '대조 MDD(%)': st.column_config.NumberColumn(format='%.0f')})

    # ── ② 내 규칙 ─────────────────────────────────
    st.markdown("##### 🛠️ 내 규칙 — 🅰 종목 게임 · 🅱 지수 게임을 따로 정하고 ▶")
    c0, c1 = st.columns(2)
    pa = c0.selectbox("🅰 시작 프리셋", list(T.PRESETS_A), index=1, key='tr_pa')
    pb = c1.selectbox("🅱 시작 프리셋", list(T.PRESETS_B), index=0, key='tr_pb')
    A0 = dict(T.DEF_A); A0.update(T.PRESETS_A[pa])
    B0 = dict(T.DEF_B); B0.update(T.PRESETS_B[pb])
    with st.form('tr_form'):
        st.markdown("**🅰 종목 게임**")
        a1, a2, a3, a4 = st.columns(4)
        ent = a1.selectbox("진입", ['start', 'nh52'], format_func={'start': '창 첫날 시가', 'nh52': '52주 신고가 종가 돌파 → 다음 날'}.get, key=f'tr_e{pa}')
        init = a2.number_input("초기 손절(진입가 −%, 0=없음)", 0.0, 90.0, float(A0['init_stop']), 1.0, key=f'tr_i{pa}')
        atrk = a3.number_input("ATR 손절 배수(0=끔) — 고점 − k×20일 ATR", 0.0, 10.0, float(A0['atr_k']), 0.5, key=f'tr_k{pa}')
        mh = a4.number_input("최소보유(거래일) — 이 기간엔 사다리 손절 안 함", 0, 500, int(A0['min_hold']), 5, key=f'tr_m{pa}')
        lad = st.data_editor(pd.DataFrame(A0['ladder'] or [[0.0, 20.0]], columns=['수익(%) 이상', '고점 대비(−%)']),
                             num_rows='dynamic', hide_index=True, key=f'tr_l{pa}', use_container_width=True)
        r1, r2 = st.columns(2)
        ren = r1.selectbox("청산 후 재매수", list(_RE), index=list(_RE).index(A0['reentry']), format_func=_RE.get, key=f'tr_r{pa}')
        cma = r2.number_input("재매수 확인: 종가가 판 가격과 n일선 위일 때 다음 날 시가(0=확인 없이 스탑)", 0, 250, int(A0['confirm_ma']), 5, key=f'tr_c{pa}')
        st.markdown("**🅱 지수 게임** — 종목이 🅰에서 보유 중일 때 실제 비중 = 이평 비중 × 상대 비중")
        b1, b2, b3 = st.columns(3)
        ixm = {}
        for m in mkts:
            ixm[m] = b1.selectbox(f"기준 지수 {_MK[m]}", T.INDEX_CHOICES[m], key=f'tr_x{m}',
                                  format_func={'SPX': 'S&P500', 'NDX': '나스닥100', 'RUT': '러셀2000', 'KOSPI': '코스피', 'KOSDAQ': '코스닥'}.get)
        man = b2.number_input("지수 n일선 아래면 0% (0=끔)", 0, 250, int(B0['ma_n']), 1, key=f'tr_ma{pb}')
        rl = b3.number_input("상대 수익 비교 기간 L일 (0=끔)", 0, 250, int(B0['rel_L']), 5, key=f'tr_rl{pb}')
        b4, b5, b6, b7, b8 = st.columns(5)
        rx = b4.number_input("x일 연속 지수 하회 →", 1, 120, int(B0['rel_x']), 1, key=f'tr_rx{pb}')
        ww = b5.number_input("약세 비중(%)", 0, 100, int(B0['w_weak'] * 100), 10, key=f'tr_ww{pb}')
        ry = b6.number_input("y일 연속 지수 상회 →", 1, 120, int(B0['rel_y']), 1, key=f'tr_ry{pb}')
        wsr = b7.number_input("강세 비중(%)", 0, 100, int(B0['w_strong'] * 100), 10, key=f'tr_ws{pb}')
        wb = b8.number_input("시작 비중(%)", 0, 100, int(B0['w_base'] * 100), 10, key=f'tr_wb{pb}')
        st.form_submit_button("▶ 백테스트", type='primary')
    for m in mkts:
        if ixm[m] not in I:
            st.caption(f"⚠️ {ixm[m]} 지수 자료가 아직 없습니다 — 그 시장은 지수 게임 없이 계산합니다.")
    lad = lad.dropna()
    a = dict(entry=ent, init_stop=init, atr_k=atrk, min_hold=int(mh), reentry=ren, confirm_ma=int(cma),
             ladder=[[float(x), float(y)] for x, y in lad.values.tolist() if y > 0])
    b = dict(ma_n=int(man), rel_L=int(rl), rel_x=int(rx), rel_y=int(ry), w_weak=ww / 100, w_strong=wsr / 100, w_base=wb / 100)
    with st.spinner("종목별 일봉으로 돌리는 중…"):
        A, P = _run(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True), json.dumps(ixm, sort_keys=True), mt, mkts)
    tsrc('trade_rules.py (화면에서 계산)', path=PX)
    st.dataframe(A, hide_index=True, use_container_width=True, column_config={
        c: st.column_config.NumberColumn(format='%.2f') for c in ['규칙 배수 중앙(×)', '그냥 보유 배수 중앙(×)']} | {
        c: st.column_config.NumberColumn(format='%.0f') for c in ['규칙 MDD 중앙(%)', '그냥 보유 MDD 중앙(%)', 'MDD 개선(%p)', '거래 수 중앙', '종목 게임 보유(%)', '손실 종목(%)']})
    st.caption("MDD 개선(%p) = 규칙 MDD − 그냥 보유 MDD (양수면 낙폭이 줄어든 것).")

    # ── ③ 종목별 · 차트 ─────────────────────────────
    st.markdown("##### 🔍 종목별 — 행을 골라 차트로 보기")
    grp = st.segmented_control("그룹", ['승자100', '대조100'], default='승자100', key='tr_grp') or '승자100'
    Q = P[P.grp == grp].sort_values('bh', ascending=False).reset_index(drop=True)
    V = pd.DataFrame({'No.': range(1, len(Q) + 1), '종목': Q.name, '코드': Q.sym, '시장': Q.market.map(_MK),
                      '규칙(×)': Q.mult, '그냥 보유(×)': Q.bh, '규칙 MDD(%)': Q.mdd * 100, '보유 MDD(%)': Q.bh_mdd * 100, '거래(회)': Q.n_trades})
    tsrc('trade_rules.py (화면에서 계산)', path=PX)
    ev = st.dataframe(V, hide_index=True, use_container_width=True, on_select='rerun', selection_mode='single-row', key='tr_tbl',
                      column_config={c: st.column_config.NumberColumn(format='%.2f') for c in ['규칙(×)', '그냥 보유(×)']}
                      | {c: st.column_config.NumberColumn(format='%.0f') for c in ['규칙 MDD(%)', '보유 MDD(%)']})
    try:
        ri = (ev.selection.rows or [0])[0]
    except Exception:
        ri = 0
    if len(Q):
        r = Q.iloc[ri]
        x = next(z for z in S if z['mkt'] == r.market and z['sym'] == r.sym and z['grp'] == grp)
        sim = T.simulate(x['o'], x['h'], x['l'], x['c'], _ix(I, ixm[r.market], x['idx']), x['s'], a, b)
        idx, c = x['idx'], x['c']
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx[x['s']:], y=c[x['s']:], name='종가', line=dict(color='#7C8AA5', width=1.3)))
        bi = [t['i0'] for t in sim['trades']]; si = [t['i1'] for t in sim['trades'] if t['i1'] is not None]
        fig.add_trace(go.Scatter(x=idx[bi], y=[t['buy'] for t in sim['trades']], mode='markers', name='매수',
                                 marker=dict(symbol='triangle-up', size=9, color='#D9363E')))
        fig.add_trace(go.Scatter(x=idx[si], y=[t['sell'] for t in sim['trades'] if t['i1'] is not None], mode='markers', name='매도',
                                 marker=dict(symbol='triangle-down', size=9, color='#2453C8')))
        fig.update_layout(height=320, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(type='log', title=None), showlegend=False)
        st.markdown(f"**{r['name']} ({r.sym})** — 규칙 ×{r.mult:.2f} · 그냥 보유 ×{r.bh:.2f} · 거래 {r.n_trades}회 · 🔺매수 🔻매도(로그 축)")
        st.plotly_chart(fig, use_container_width=True)
