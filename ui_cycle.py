# -*- coding: utf-8 -*-
"""📈 사이클 비교 화면 (2026-11-06, 차니 요구 · 2026-11-07 검색창으로 교체) — 엔진 cycle_compare.py

고점·저점은 자동으로 찾지 않는다. 차트를 보고 사용자가 구간(시작일·종료일)을 직접 넣으면,
그 구간을 시작일=0으로 맞춰 겹쳐 그리고, 상승/하락 구간의 기간·수익률 평균·중앙값을 낸다.

종목 검색은 예시 버튼을 따로 만들지 않고 dashboard.py 종목분석 탭과 같은 걸 쓴다(sym_search.py,
2026-11-07 분리) — 화면마다 다른 검색 방식을 만들지 않는다는 사용자 지적 반영.
"""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import cycle_compare as C
import sym_search as S

_GREEN, _RED = '#16A34A', '#D9363E'


def _pick_symbol():
    """종목분석 탭과 같은 검색 UX(코드/이름 → 후보 목록). 결과는 세션에 고정."""
    with st.form('cyc_sym_form', border=False, enter_to_submit=True):
        c_in, c_btn = st.columns([3, 1])
        q = c_in.text_input('종목명 또는 코드', placeholder='삼성전자 / 005930 / TSLA / SOXX',
                            label_visibility='collapsed', key='cyc_q')
        go = c_btn.form_submit_button('검색', use_container_width=True)
    if q and go:
        code, cands = S.resolve_symbol(q)
        if code:
            st.session_state['cyc_sym'] = code
            st.session_state.pop('cyc_cands', None)
        else:
            st.session_state['cyc_cands'] = cands
    cands = st.session_state.get('cyc_cands')
    if cands is not None:
        if not cands:
            st.warning(f"'{q}' 와 맞는 종목이 없습니다. 이름 일부나 종목코드로 다시 찾아보세요.")
        else:
            pick = st.radio('후보', [c for c, _ in cands], format_func=lambda c: dict(cands)[c],
                            key='cyc_cand_pick', label_visibility='collapsed')
            if st.button('이 종목으로', key='cyc_cand_go'):
                st.session_state['cyc_sym'] = pick
                st.session_state.pop('cyc_cands', None)
                st.rerun()
    return st.session_state.get('cyc_sym')


def render(mkt_sel: str, tsrc):
    st.markdown("#### 📈 사이클 비교")
    st.caption("저점에서 고점까지(상승), 고점에서 저점까지(하락) — 차트를 보고 구간을 직접 정하면, "
               "시작일을 0%로 맞춰 겹쳐 그리고 기간·수익률을 비교합니다. 일봉 기준.")

    sym = _pick_symbol()
    if not sym:
        st.info('종목을 검색하세요.')
        return
    m = S.market_of(sym)
    close = C.load_close(sym, m)
    if close is None or len(close) < 10:
        st.error(f'{sym}({m}) 가격 데이터가 없습니다 — 코드를 확인하세요.')
        return
    st.caption(f'**{sym}** ({"한국" if m == "KR" else "미국"})')

    fig0 = go.Figure(go.Scatter(x=close.index, y=close.values, line=dict(color='#2453C8', width=1.3)))
    fig0.update_layout(height=260, margin=dict(l=8, r=8, t=8, b=8), yaxis=dict(type='log', title='종가(로그)'))
    st.plotly_chart(fig0, use_container_width=True)
    tsrc('daily_store (FinanceDataReader 캐시)', asof=str(close.index[-1].date()))
    st.caption('⬆️ 위 차트에서 저점·고점 날짜를 눈으로 확인한 뒤, 아래 표에 구간을 추가하세요(행 추가는 표 아래 ＋).')

    key = f'cyc_rows|{sym}'
    if key not in st.session_state:
        lo, hi = close.index.min().date(), close.index.max().date()
        st.session_state[key] = pd.DataFrame([{'라벨': '구간 1', '시작일': lo, '종료일': hi}])

    with st.container(border=True):
        st.caption('🤖 자동 채우기 — 종목분석 탭 "낙폭 회차"와 같은 정의(고점 대비 X% 이상 빠진 구간)로 '
                   '하락(고점→저점)·회복(저점→고점) 구간을 한 번에 채웁니다. 채운 뒤에도 아래 표에서 직접 수정·추가할 수 있습니다.')
        ac1, ac2, ac3 = st.columns([1.3, 2, 1])
        _mopt = [12, 24, 36, 60, 120, 240, '전체']
        amon = ac1.selectbox('기간', _mopt, index=len(_mopt) - 1, key=f'cyc_auto_m|{sym}',
                             format_func=lambda v: '전체' if v == '전체' else f'{v}개월')
        athr = ac2.slider('MDD 기준(%)', 5, 70, 30, 5, key=f'cyc_auto_x|{sym}')
        if ac3.button('⬇ 채우기', key=f'cyc_auto_go|{sym}', use_container_width=True):
            auto = C.auto_rows(close, 0 if amon == '전체' else int(amon), float(athr))
            if len(auto):
                st.session_state[key] = auto
            else:
                st.warning(f'{int(athr)}% 이상 빠진 구간이 없습니다 — 기준을 낮춰보세요.')
            st.rerun()

    rows = st.data_editor(st.session_state[key], num_rows='dynamic', hide_index=True, use_container_width=True,
                          key=f'cyc_editor|{sym}',
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
        st.caption(f'⚠️ {skipped}개 구간은 건너뜀 — 시작일이 종료일보다 늦거나, 구간 안에 거래일이 2일 미만입니다.')
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
                      xaxis=dict(title='경과(거래일)'), yaxis=dict(title='시작일 대비(%)'))
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
