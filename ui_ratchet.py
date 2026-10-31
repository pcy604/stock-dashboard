# -*- coding: utf-8 -*-
"""🪜 익절 래칫 — 종목별 매매 규칙 실험실 (2026-10-31)
최근 5년 상승률 TOP 100(미국·한국) + 무작위 대조 100 에 사용자가 만든 규칙을 바로 돌려 본다.
가격·연구 결과: research/stock_ratchet.py → results/stock_ratchet_px.parquet · stock_ratchet.json
엔진: stock_rules.py (연구와 같은 함수)."""
import json
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import stock_rules as R

PX = 'results/stock_ratchet_px.parquet'
RES = 'results/stock_ratchet.json'
_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _load_px(mtime):
    d = pd.read_parquet(PX)
    d['date'] = pd.to_datetime(d['date'])
    return d


@st.cache_data(ttl=3600, show_spinner=False, max_entries=24)
def _run(params_json, mtime, mkts):
    p = json.loads(params_json)
    d = _load_px(mtime)
    d = d[d.market.isin(mkts)]
    rows, per = [], []
    for (mkt, grp, sym), g in d.groupby(['market', 'grp', 'sym'], sort=False):
        c = g.sort_values('date').close.values
        a = R.summarize(c, 52, p)
        b = R.summarize(c, 52, dict(p, init_stop=0, ladder=[], lock_be=0, scale_out=[0, 0], reentry='none'))  # 같은 진입·보유만
        per.append(dict(market=mkt, grp=grp, sym=sym, name=g.name.iloc[0], **a, hold_same_entry=b['mult']))
    P = pd.DataFrame(per)
    for (mkt, grp), g in P.groupby(['market', 'grp'], sort=False):
        a = R.aggregate(g.to_dict('records'))
        rows.append(dict(시장=_MK[mkt], 그룹=grp, 종목수=a['n'], 규칙배수중앙=a['mult_med'], 규칙배수기하=a['mult_geo'],
                         보유배수중앙=float(g.hold_same_entry.median()), 창전체보유중앙=a['bh_med'],
                         보유보다나음=a['beat_bh'] * 100, 손실종목=a['lose'] * 100, 거래수중앙=a['trades_med'],
                         보유기간=a['exposure_med'] * 100, 규칙MDD중앙=a['mdd_med'] * 100, 보유MDD중앙=a['bh_mdd_med'] * 100))
    return pd.DataFrame(rows), P


def render(mkt_sel: str, tsrc):
    st.caption("**한 종목**에 '오를수록 손절선(=익절선)을 끌어올리는' 규칙을 걸면 어떻게 되나. 판정은 주봉 종가, 체결은 다음 주 종가, 편도 0.3%. "
               "손절선은 전부 **보유 중 최고 종가 대비**(초기 손절·본전 보장만 진입가 대비).")
    st.warning("⚠️ **승자100은 결과를 보고 고른 표본**입니다 — 이 숫자는 기대 수익이 아닙니다. '오래 쥐는 규칙'은 승자에서 늘 이기므로, "
               "**대조100(같은 조건 무작위)에서 손실을 얼마나 줄였는지와 함께** 보세요. 둘 다 좋아야 쓸 만한 규칙입니다.", icon=None)
    if not os.path.exists(PX):
        st.info("가격 표본이 아직 없습니다 — GitHub Actions 'research-ratchet' 실행 후 생깁니다.")
        return
    mt = os.path.getmtime(PX)
    mkts = ['US', 'KR'] if mkt_sel == '전체' else [mkt_sel]
    res = {}
    try:
        res = json.load(open(RES, encoding='utf-8'))
    except Exception:
        pass

    # ── ① 프리셋 결과(연구 실행분) ──────────────────────────
    st.markdown("##### 📋 미리 잰 규칙 18종 — 창 첫 주 매수 기준")
    _ent0 = st.segmented_control("진입", list(R.ENTRIES)[:2], default='start', key='rat_ent0',
                                 format_func=lambda k: R.ENTRIES[k]) or 'start'
    rows = []
    for m in mkts:
        for grp in ('승자100', '대조100'):
            for name, a in (res.get('results', {}).get(f"{m}|{grp}|{_ent0}") or {}).items():
                rows.append(dict(시장=_MK[m], 규칙=name, 그룹=grp, 배수중앙=a['mult_med'], MDD중앙=a['mdd_med'] * 100,
                                 보유기간=a['exposure_med'] * 100))
    if rows:
        T = pd.DataFrame(rows)
        W = T.pivot_table(index=['시장', '규칙'], columns='그룹', values=['배수중앙', 'MDD중앙', '보유기간'], sort=False)
        W.columns = [f"{g} {v}" for v, g in W.columns]
        W = W.reset_index()
        cols = ['시장', '규칙', '승자100 배수중앙', '대조100 배수중앙', '승자100 MDD중앙', '대조100 MDD중앙', '승자100 보유기간']
        W = W[[c for c in cols if c in W.columns]].rename(columns={
            '승자100 배수중앙': '승자 배수(×)', '대조100 배수중앙': '대조 배수(×)', '승자100 MDD중앙': '승자 MDD(%)',
            '대조100 MDD중앙': '대조 MDD(%)', '승자100 보유기간': '승자 보유기간(%)'})
        tsrc('research/stock_ratchet.py', path=RES)
        st.dataframe(W, hide_index=True, use_container_width=True, column_config={
            '승자 배수(×)': st.column_config.NumberColumn(format='%.2f', help='5년 뒤 자산 배수(중앙). 1 = 본전'),
            '대조 배수(×)': st.column_config.NumberColumn(format='%.2f', help='무작위 100종에서의 배수(중앙)'),
            '승자 MDD(%)': st.column_config.NumberColumn(format='%.0f'), '대조 MDD(%)': st.column_config.NumberColumn(format='%.0f'),
            '승자 보유기간(%)': st.column_config.NumberColumn(format='%.0f', help='창 260주 중 주식을 들고 있던 비율')})
        st.caption(f"창 {', '.join(_MK[m] + ' ' + '~'.join((res.get('info', {}).get(m) or {}).get('window', ['-'])) for m in mkts)} · "
                   "읽는 법: 승자 배수가 크고(대박주를 지킴) 대조 배수도 1에 가까울수록(평범한 종목에서 덜 잃음) 좋은 규칙.")
    else:
        st.info("연구 결과가 아직 없습니다.")

    # ── ② 내 규칙 만들기 ─────────────────────────────────
    st.markdown("##### 🛠️ 내 규칙 만들기 — 값을 바꾸면 200~400종에 바로 다시 돌립니다")
    pre = st.selectbox("시작 프리셋", list(R.PRESETS), index=4, key='rat_pre')
    base = R.full(R.PRESETS[pre])
    with st.form('rat_form'):
        c1, c2, c3, c4 = st.columns(4)
        ent = c1.selectbox("진입", list(R.ENTRIES), format_func=lambda k: R.ENTRIES[k], key=f'rat_e_{pre}')
        init = c2.number_input("초기 손절(진입가 −%, 0=없음)", 0.0, 90.0, float(base['init_stop']), 5.0, key=f'rat_i_{pre}')
        mh = c3.number_input("최소보유(주) — 이 기간엔 고점 대비 손절 안 함", 0, 156, int(base['min_hold']), 1, key=f'rat_m_{pre}')
        lb = c4.number_input("본전 보장: 최고 수익 +%에서 (0=끔)", 0.0, 500.0, float(base['lock_be']), 10.0, key=f'rat_b_{pre}')
        st.markdown("**익절 사다리** — 최고 수익이 '수익%' 이상이면 손절선 = 고점 × (1 − 고점대비%). 손절선은 내려가지 않습니다. 행 추가·삭제 가능.")
        lad = st.data_editor(pd.DataFrame(base['ladder'] or [[0.0, 30.0]], columns=['수익(%) 이상', '고점 대비(−%)']),
                             num_rows='dynamic', hide_index=True, key=f'rat_l_{pre}', use_container_width=True)
        d1, d2, d3, d4 = st.columns(4)
        so_g = d1.number_input("부분 익절: 수익 +% (0=끔)", 0.0, 2000.0, float(base['scale_out'][0]), 10.0, key=f'rat_sg_{pre}')
        so_f = d2.number_input("부분 익절: 매도 비율(%)", 0.0, 100.0, float(base['scale_out'][1]) * 100, 10.0, key=f'rat_sf_{pre}')
        rent = d3.selectbox("청산 후 재진입", ['none', 'nh52', 'prev_peak', 'sell_px'], index=['none', 'nh52', 'prev_peak', 'sell_px'].index(base['reentry']),
                            format_func={'none': '안 함', 'nh52': '52주 신고가 돌파', 'prev_peak': '청산 때 고점 재돌파', 'sell_px': '판 가격 재돌파'}.get, key=f'rat_r_{pre}')
        cd = d4.number_input("재진입 냉각(주)", 0, 52, int(base['cooldown']), 1, key=f'rat_c_{pre}')
        go_ = st.form_submit_button("▶ 백테스트", type='primary')
    lad = lad.dropna()
    p = dict(entry=ent, init_stop=init, min_hold=int(mh), lock_be=lb,
             ladder=[[float(a), float(b)] for a, b in lad.values.tolist() if b > 0],
             scale_out=[so_g, so_f / 100 if so_g > 0 else 0.0], reentry=rent, cooldown=int(cd))
    with st.spinner("종목별로 돌리는 중…"):
        S, P = _run(json.dumps(p, sort_keys=True), mt, tuple(mkts))
    tsrc('stock_rules.py (화면에서 계산)', path=PX)
    st.dataframe(S, hide_index=True, use_container_width=True, column_config={
        '규칙배수중앙': st.column_config.NumberColumn('규칙 배수 중앙(×)', format='%.2f'),
        '규칙배수기하': st.column_config.NumberColumn('규칙 배수 기하(×)', format='%.2f', help='종목별 배수의 기하평균 — 동일 비중으로 나눠 담았을 때에 가깝다'),
        '보유배수중앙': st.column_config.NumberColumn('같은 진입·그냥 보유(×)', format='%.2f', help='같은 날 사서 끝까지 들고 있었다면'),
        '창전체보유중앙': st.column_config.NumberColumn('창 첫 주부터 보유(×)', format='%.2f'),
        '보유보다나음': st.column_config.NumberColumn('그냥 보유보다 나은 종목(%)', format='%.0f'),
        '손실종목': st.column_config.NumberColumn('손실 종목(%)', format='%.0f'),
        '거래수중앙': st.column_config.NumberColumn('거래 수 중앙', format='%.0f'),
        '보유기간': st.column_config.NumberColumn('보유 기간(%)', format='%.0f'),
        '규칙MDD중앙': st.column_config.NumberColumn('규칙 MDD 중앙(%)', format='%.0f'),
        '보유MDD중앙': st.column_config.NumberColumn('보유 MDD 중앙(%)', format='%.0f')})

    # ── ③ 종목별 결과 · 한 종목 차트 ─────────────────────────
    st.markdown("##### 🔍 종목별 — 행을 골라 차트로 보기")
    grp = st.segmented_control("그룹", ['승자100', '대조100'], default='승자100', key='rat_grp') or '승자100'
    Q = P[P.grp == grp].copy()
    Q['시장'] = Q.market.map(_MK)
    Q = Q.sort_values('bh', ascending=False).reset_index(drop=True)
    Q.insert(0, 'No.', range(1, len(Q) + 1))
    V = Q[['No.', 'name', 'sym', '시장', 'mult', 'hold_same_entry', 'bh', 'n_trades', 'exposure', 'mdd']].rename(columns={
        'name': '종목', 'sym': '코드', 'mult': '규칙(×)', 'hold_same_entry': '같은 진입 보유(×)', 'bh': '창 보유(×)',
        'n_trades': '거래(회)', 'exposure': '보유기간(%)', 'mdd': '규칙 MDD(%)'})
    V['보유기간(%)'] = V['보유기간(%)'] * 100; V['규칙 MDD(%)'] = V['규칙 MDD(%)'] * 100
    V['규칙−보유(×)'] = V['규칙(×)'] - V['같은 진입 보유(×)']
    tsrc('stock_rules.py (화면에서 계산)', path=PX)
    ev = st.dataframe(V, hide_index=True, use_container_width=True, on_select='rerun', selection_mode='single-row', key='rat_tbl',
                      column_config={c: st.column_config.NumberColumn(format='%.2f') for c in ['규칙(×)', '같은 진입 보유(×)', '창 보유(×)', '규칙−보유(×)']}
                      | {'보유기간(%)': st.column_config.NumberColumn(format='%.0f'), '규칙 MDD(%)': st.column_config.NumberColumn(format='%.0f')})
    try:
        ri = (ev.selection.rows or [0])[0]
    except Exception:
        ri = 0
    if len(Q):
        r = Q.iloc[ri]
        g = _load_px(mt)
        g = g[(g.market == r.market) & (g.sym == r.sym)].sort_values('date')
        c = g.close.values
        sim = R.simulate(c, 52, p)
        idx = pd.DatetimeIndex(g.date.values)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=idx[52:], y=c[52:], name='주봉 종가', line=dict(color='#7C8AA5', width=1.6)))
        for t in sim['trades']:
            fig.add_trace(go.Scatter(x=pd.DatetimeIndex([idx[t['i0']]]), y=[c[t['i0']]], mode='markers', showlegend=False,
                                     marker=dict(symbol='triangle-up', size=11, color='#D9363E'), hovertemplate='매수 %{y:,.2f}<extra></extra>'))
            if t['i1'] is not None:
                fig.add_trace(go.Scatter(x=pd.DatetimeIndex([idx[t['i1']]]), y=[c[t['i1']]], mode='markers', showlegend=False,
                                         marker=dict(symbol='triangle-down', size=11, color='#2453C8'),
                                         hovertemplate=f"매도({t['why']}) %{{y:,.2f}} · {t['ret'] * 100:+.0f}%<extra></extra>"))
        fig.update_layout(height=320, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(type='log', title=None), showlegend=False)
        st.markdown(f"**{r['name']} ({r.sym})** — 규칙 ×{r.mult:.2f} · 같은 진입 보유 ×{r.hold_same_entry:.2f} · 🔺매수 🔻매도(로그 축)")
        st.plotly_chart(fig, use_container_width=True)
