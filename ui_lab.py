# -*- coding: utf-8 -*-
"""🧪 전략 실험실 화면 — 🪜 익절 래칫 + 🎮 매매 실험실 통합 (2026-11-01). 엔진 quant_lab.py.
표본: results/trade_px.parquet(최근 5년 상승률 상위 100 = '대박주' · 같은 조건 무작위 100 = '평범한 종목', 미국·한국 일봉)."""
import json
import os
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import quant_lab as Q

PX, IX = 'results/trade_px.parquet', 'results/trade_idx.parquet'
_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
_GRP = {'승자100': '대박주 100', '대조100': '평범한 종목 100'}


@st.cache_data(ttl=3600 * 6, show_spinner=False)
def _load(mt):
    P = pd.read_parquet(PX)
    P['date'] = pd.to_datetime(P['date'])
    I = pd.read_parquet(IX)
    I.index = pd.to_datetime(I.index)
    try:
        win = {m: pd.Timestamp(v['window'][0]) for m, v in
               json.load(open('results/stock_ratchet.json', encoding='utf-8'))['info'].items() if 'window' in v}
    except Exception:
        win = {}
    S = []
    for (mkt, grp, sym), g in P.groupby(['market', 'grp', 'sym'], sort=False):
        g = g.sort_values('date')
        idx = pd.DatetimeIndex(g.date)
        s = int(np.searchsorted(idx, win.get(mkt, idx[0])))
        if s < len(idx) - 250:
            S.append(dict(mkt=mkt, grp=grp, sym=sym, name=g.name.iloc[0], idx=idx,
                          o=g.o.values.astype(float), h=g.h.values.astype(float),
                          l=g.l.values.astype(float), c=g.c.values.astype(float), s=s))
    return S, I


def _ix(I, name, idx):
    return I[name].reindex(idx).ffill().values.astype(float) if name in I else None


@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def _run(key, p_json, idx_ma, stop, ixmap_json, mt, mkts):
    p, ixm = json.loads(p_json), json.loads(ixmap_json)
    S, I = _load(mt)
    rows = []
    for x in S:
        if x['mkt'] in mkts:
            r = Q.summary(x['o'], x['h'], x['l'], x['c'], _ix(I, ixm[x['mkt']], x['idx']), x['s'], key, p, idx_ma, stop)
            rows.append(dict(market=x['mkt'], grp=x['grp'], sym=x['sym'], name=x['name'], **r))
    return pd.DataFrame(rows)


def _agg(D):
    out = {}
    for (m, g), G in D.groupby(['market', 'grp']):
        out[(m, g)] = dict(mult=G.mult.median(), bh=G.bh.median(), mdd=G.mdd.median() * 100, bh_mdd=G.bh_mdd.median() * 100,
                           lose=(G.mult < 1).mean() * 100, keep=(np.log(G.mult.clip(lower=1e-6)).sum() > 0),
                           trades=G.trades.median(), expo=G.exposure.median() * 100)
    return out


def render(mkt_sel: str, tsrc):
    st.markdown("#### 🎯 전략 시험 — 한 종목 단위로, 대박주와 평범한 종목에 똑같이 돌려 봅니다")
    st.caption("**읽는 법**: 좋은 전략은 ① 대박주의 상승을 많이 지키고 ② 평범한 종목에서 덜 잃습니다. 하나만 잘하면 반쪽입니다. "
               "대박주 100 = 최근 5년 가장 많이 오른 종목(결과를 보고 고른 표본이라 수익률 자체는 기대 수익이 아님) · "
               "평범한 종목 100 = 같은 조건 무작위. 일봉 · 종가로 판단해 다음 날 시가에 매매 · 편도 0.3%.")
    if not os.path.exists(PX):
        st.info("표본이 아직 없습니다 — GitHub Actions 'research-ratchet' 실행 후 생깁니다.")
        return
    mt = os.path.getmtime(PX)
    S, I = _load(mt)
    mkts = tuple(m for m in (['US', 'KR'] if mkt_sel == '전체' else [mkt_sel]) if any(x['mkt'] == m for x in S))
    if not mkts:
        st.info("이 시장의 표본이 아직 없습니다.")
        return

    # ── ① 전략 고르기 ─────────────────────────────────
    c1, c2 = st.columns([1.2, 1], gap='large')
    with c1:
        st.markdown("**① 전략**")
        key = st.selectbox("전략", list(Q.STRATS), index=1, label_visibility='collapsed', key='lab_s',
                           format_func=lambda k: f"{Q.STRATS[k]['name']}  ·  {Q.STRATS[k]['kind']}")
        sd = Q.STRATS[key]
        st.caption(sd['desc'])
        p = {}
        for pk, lab, lo, hi, dv, stp in sd['params']:
            p[pk] = st.number_input(lab, lo, hi, dv, stp, key=f'lab_{key}_{pk}', help=f'{lo}~{hi}')   # 2026-11-08 직접 입력
    with c2:
        st.markdown("**② 지수 필터 (선택)** — 지수가 약하면 쉬기")
        idx_ma = st.number_input("지수가 이 n일선 아래면 보유하지 않음 (0 = 끔)", 0, 300, 0, 5, key='lab_ix')
        ixm = {m: Q.INDEX_OF[m] for m in mkts}
        if idx_ma:
            cols = st.columns(len(mkts))
            for i, m in enumerate(mkts):
                ixm[m] = cols[i].selectbox(f"{_MK[m]} 기준 지수", Q.INDEX_CHOICES[m], key=f'lab_x{m}', format_func=Q.INDEX_NAME.get)
        st.markdown("**③ 안전장치 (선택)** — 고점에서 이만큼 빠지면 손절")
        stop = 0
        if key != 'trail':
            stop = st.number_input("보유 중 최고가 대비 −% (0 = 끔)", 0, 90, 0, 1, key='lab_stop')
        else:
            st.caption("이 전략은 손절 자체가 규칙이라 안전장치가 따로 없습니다.")

    with st.spinner("400종에 돌리는 중…"):
        D = _run(key, json.dumps(p, sort_keys=True), int(idx_ma), float(stop), json.dumps(ixm, sort_keys=True), mt, mkts)
    A = _agg(D)

    # ── 결과 카드 ─────────────────────────────────────
    st.markdown("##### 결과 — 단순 보유와 비교")
    for m in mkts:
        w, c = A.get((m, '승자100')), A.get((m, '대조100'))
        if not (w and c):
            continue
        k1, k2, k3, k4 = st.columns(4)
        k1.metric(f"{_MK[m]} 대박주 — 남긴 수익", f"×{w['mult']:.2f}", f"단순 보유 ×{w['bh']:.2f}", delta_color='off',
                  help='5년 뒤 자산 배수(중앙값). 1 = 본전')
        k2.metric("대박주 상승을 지킨 비율", f"{(w['mult'] - 1) / (w['bh'] - 1) * 100:.0f}%" if w['bh'] > 1 else '-',
                  help='(전략 배수 − 1) ÷ (단순 보유 배수 − 1). 100% = 단순 보유와 같은 수준')
        k3.metric("평범한 종목 — 결과", f"×{c['mult']:.2f}", f"단순 보유 ×{c['bh']:.2f}", delta_color='off',
                  help='무작위 100종에서의 배수(중앙값)')
        k4.metric("평범한 종목 — 최대 낙폭", f"{c['mdd']:.0f}%", f"{c['mdd'] - c['bh_mdd']:+.0f}%p (단순 보유 {c['bh_mdd']:.0f}%)",
                  help='종목별 최대 낙폭의 중앙값. 화살표가 + 면 낙폭이 줄어든 것')
        good_w = w['bh'] > 1 and (w['mult'] - 1) / (w['bh'] - 1) >= 0.6
        good_c = c['mult'] >= c['bh'] and c['mdd'] - c['bh_mdd'] >= 10
        verdict = ('✅ 둘 다 잘함 — 후보로 기록할 만합니다' if good_w and good_c else
                   '🟡 대박주는 지켰지만 평범한 종목 방어는 약함' if good_w else
                   '🟡 방어는 됐지만 대박주 상승을 많이 놓침' if good_c else '❌ 둘 다 단순 보유보다 나쁨')
        st.caption(f"{_MK[m]} 판정: {verdict} · 거래 횟수(중앙) 대박주 {w['trades']:.0f}회 · 주식을 들고 있던 기간 {w['expo']:.0f}% "
                   "(기준: 대박주 상승 60% 이상 유지 + 평범한 종목 낙폭 10%p 이상 축소)")

    # ── 모든 전략 한눈에 ───────────────────────────────
    with st.expander("📊 모든 전략을 기본값으로 한 번에 비교", expanded=False):
        if st.toggle("계산하기 (몇 초 걸림)", key='lab_all'):
            rows = []
            for k, s in Q.STRATS.items():
                pp = {pk: dv for pk, _, _, _, dv, _ in s['params']}
                AA = _agg(_run(k, json.dumps(pp, sort_keys=True), int(idx_ma), float(stop), json.dumps(ixm, sort_keys=True), mt, mkts))
                for m in mkts:
                    w, c = AA.get((m, '승자100')), AA.get((m, '대조100'))
                    if w and c:
                        rows.append({'시장': _MK[m], '전략': s['name'], '종류': s['kind'],
                                     '대박주 배수(×)': w['mult'], '대박주 지킨 비율(%)': (w['mult'] - 1) / (w['bh'] - 1) * 100 if w['bh'] > 1 else None,
                                     '평범 배수(×)': c['mult'], '평범 낙폭(%)': c['mdd'], '거래(회)': w['trades']})
            tsrc('quant_lab.py (화면에서 계산, 지수 필터·안전장치는 위 설정 그대로)', path=PX)
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True, column_config={
                '대박주 배수(×)': st.column_config.NumberColumn(format='%.2f'), '평범 배수(×)': st.column_config.NumberColumn(format='%.2f'),
                '대박주 지킨 비율(%)': st.column_config.NumberColumn(format='%.0f'), '평범 낙폭(%)': st.column_config.NumberColumn(format='%.0f'),
                '거래(회)': st.column_config.NumberColumn(format='%.0f')})

    # ── 한 종목 차트 ───────────────────────────────────
    with st.expander("🔍 종목 하나 골라 매수·매도 지점 보기", expanded=False):
        g1, g2 = st.columns([1, 2])
        grp = g1.radio("그룹", list(_GRP), format_func=_GRP.get, key='lab_grp')
        Dg = D[D.grp == grp].sort_values('bh', ascending=False)
        lab = {f"{r['name']} ({r.sym}) — 전략 ×{r.mult:.2f} / 보유 ×{r.bh:.2f}": (r.market, r.sym) for _, r in Dg.iterrows()}
        pick = g2.selectbox("종목", list(lab), key='lab_pick')
        if pick:
            m, sym = lab[pick]
            x = next(z for z in S if z['mkt'] == m and z['sym'] == sym and z['grp'] == grp)
            r = Q.run(x['o'], x['h'], x['l'], x['c'], _ix(I, ixm[m], x['idx']), x['s'], key, p, idx_ma, stop)
            idx, c = x['idx'], x['c']
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=idx[x['s']:], y=c[x['s']:], name='종가', line=dict(color='#7C8AA5', width=1.3)))
            if r['buys']:
                fig.add_trace(go.Scatter(x=idx[[t for t, _ in r['buys']]], y=[v for _, v in r['buys']], mode='markers', name='매수',
                                         marker=dict(symbol='triangle-up', size=9, color='#D9363E')))
            if r['sells']:
                fig.add_trace(go.Scatter(x=idx[[t for t, _ in r['sells']]], y=[v for _, v in r['sells']], mode='markers', name='매도',
                                         marker=dict(symbol='triangle-down', size=9, color='#2453C8')))
            fig.update_layout(height=320, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(type='log', title=None),
                              legend=dict(orientation='h', y=1.08, x=0))
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"🔺 매수 {len(r['buys'])}회 · 🔻 매도 {len(r['sells'])}회 · 로그 축")
