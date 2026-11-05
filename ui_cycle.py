# -*- coding: utf-8 -*-
"""📈 사이클 비교 화면 (2026-11-06, 차니 요구) — 엔진 cycle_compare.py

고점·저점은 자동으로 찾지 않는다. 차트를 보고 사용자가 구간(시작일·종료일)을 직접 넣으면,
그 구간을 시작일=0%로 맞춰 겹쳐 그리고, 상승/하락 구간의 기간·수익률 평균·중앙값을 낸다.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import cycle_compare as C

_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
_PRESET = {
    'KR': [('005930', '삼성전자'), ('000660', 'SK하이닉스'), ('042700', '한미반도체'), ('000990', 'DB하이텍')],
    'US': [('NVDA', '엔비디아'), ('AMD', 'AMD'), ('INTC', '인텔'), ('TSM', 'TSMC'),
           ('MU', '마이크론'), ('ASML', 'ASML'), ('AMAT', '어플라이드 머티리얼즈'), ('LRCX', '램리서치')],
}
_GREEN, _RED = '#16A34A', '#D9363E'


def _sym_pick(m):
    opts = [f"{n} ({c})" for c, n in _PRESET[m]] + ['✏️ 직접 입력']
    pick = st.selectbox('종목 (반도체 사이클이 뚜렷한 종목 예시 — 다른 종목도 가능)', opts, key=f'cyc_pick|{m}')
    if pick == '✏️ 직접 입력':
        return st.text_input('코드/티커', placeholder='005930 또는 NVDA', key=f'cyc_sym|{m}').strip().upper()
    code = pick.rsplit('(', 1)[1].rstrip(')')
    return code


def render(mkt_sel: str, tsrc):
    st.markdown("#### 📈 사이클 비교")
    st.caption("저점에서 고점까지(상승), 고점에서 저점까지(하락) — 차트를 보고 구간을 직접 정하면, "
               "시작일을 0%로 맞춰 겹쳐 그리고 기간·수익률을 비교합니다. 주봉 기준.")
    mk = ['US', 'KR'] if mkt_sel == '전체' else [mkt_sel]
    m = mk[0] if len(mk) == 1 else st.segmented_control('시장', mk, default='KR', key='cyc_m', format_func=_MK.get) or 'KR'

    sym = _sym_pick(m)
    if not sym:
        st.info('종목을 고르거나 코드를 입력하세요.')
        return
    close = C.load_close(sym, m)
    if close is None or len(close) < 10:
        st.error(f'{sym}({m}) 가격 데이터가 없습니다 — 코드를 확인하세요.')
        return

    fig0 = go.Figure(go.Scatter(x=close.index, y=close.values, line=dict(color='#2453C8', width=1.3)))
    fig0.update_layout(height=260, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(type='log', title='종가(로그)'))
    st.plotly_chart(fig0, use_container_width=True)
    tsrc('price_store (market.db)', asof=str(close.index[-1].date()))
    st.caption('⬆️ 위 차트에서 저점·고점 날짜를 눈으로 확인한 뒤, 아래 표에 구간을 추가하세요(행 추가는 표 아래 ＋).')

    key = f'cyc_rows|{sym}|{m}'
    if key not in st.session_state:
        lo, hi = close.index.min().date(), close.index.max().date()
        st.session_state[key] = pd.DataFrame([{'라벨': '구간 1', '시작일': lo, '종료일': hi}])
    rows = st.data_editor(st.session_state[key], num_rows='dynamic', hide_index=True, use_container_width=True,
                          key=f'cyc_editor|{sym}|{m}',
                          column_config={'라벨': st.column_config.TextColumn(width='medium'),
                                         '시작일': st.column_config.DateColumn(min_value=close.index.min().date(), max_value=close.index.max().date()),
                                         '종료일': st.column_config.DateColumn(min_value=close.index.min().date(), max_value=close.index.max().date())})
    st.session_state[key] = rows

    segs, skipped = [], 0
    for r in rows.dropna(subset=['시작일', '종료일']).to_dict('records'):
        s = C.build_segment(close, r.get('라벨'), r['시작일'], r['종료일'])
        if s:
            segs.append(s)
        else:
            skipped += 1
    if skipped:
        st.caption(f'⚠️ {skipped}개 구간은 건너뜀 — 시작일이 종료일보다 늦거나, 구간 안에 주봉이 2개 미만입니다.')
    if not segs:
        st.info('유효한 구간이 없습니다. 표에서 시작일 < 종료일로 넣어 주세요.')
        return

    fig = go.Figure()
    for s in segs:
        fig.add_trace(go.Scatter(x=list(s['series'].index), y=s['series'].values,
                                 name=f"{s['label']} ({s['start']}~{s['end']}, {s['direction']})",
                                 line=dict(color=_GREEN if s['direction'] == '상승' else _RED, width=1.8)))
    fig.add_hline(y=0, line=dict(color='#999', width=1, dash='dot'))
    fig.update_layout(height=380, margin=dict(l=8, r=8, t=8, b=8), legend=dict(orientation='h', y=-0.18, yanchor='top'),
                      xaxis=dict(title='경과(주)'), yaxis=dict(title='시작일 대비(%)'))
    st.plotly_chart(fig, use_container_width=True)

    tsrc('cycle_compare.py (화면에서 계산)', asof=str(close.index[-1].date()))
    st.dataframe(C.detail_table(segs), hide_index=True, use_container_width=True, filters=False)

    st.markdown("##### 방향별 통계")
    tsrc('cycle_compare.py (화면에서 계산)', asof=str(close.index[-1].date()))
    summ = C.summarize(segs)
    if len(summ):
        st.dataframe(summ, hide_index=True, use_container_width=True, filters=False)
    st.caption('⚠️ 구간은 사용자가 고른 것이라(사후 선택) 표본이 적을수록 우연일 수 있습니다. '
               '같은 종목이라도 사이클 성격(메모리·파운드리·장비)이 다르면 직접 비교가 어긋날 수 있습니다.')
