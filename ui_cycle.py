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
# 구간별 색(2026-11-10 차니: 구간끼리 구분되게) — 서로 잘 갈리는 12색. 진행 중 구간은 검정 굵은 선, 과거 중앙은 방향색 점선.
_PAL = ['#2563EB', '#DC2626', '#059669', '#D97706', '#7C3AED', '#DB2777', '#0891B2', '#65A30D',
        '#EA580C', '#4F46E5', '#0D9488', '#A16207']


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
    """단독 화면(검색창 포함) — 2026-11-08 부터 본 자리는 🔍 종목 분석 탭(render_for). 남겨 두는 건 연구 스크립트·점검용."""
    st.markdown("#### 🔁 사이클 비교")
    sym = _pick_symbol()
    if not sym:
        st.info('종목을 검색하세요.')
        return
    m = S.market_of(sym)
    close = C.load_close(sym, m)
    if close is None or len(close) < 10:
        st.error(f'{sym}({m}) 가격 데이터가 없습니다 — 코드를 확인하세요.')
        return
    render_for(sym, close, tsrc, src='daily_store (FinanceDataReader 캐시)')


def _logticks(lo, hi):
    """로그 축 눈금 — 1·2·5 단위에서 5~7개만(기본 눈금은 작은 칸마다 숫자를 찍어 겹친다)."""
    import math
    lo, hi = max(float(lo), 1e-9), max(float(hi), 1e-9)
    v = [m * 10 ** e for e in range(int(math.floor(math.log10(lo))) - 1, int(math.ceil(math.log10(hi))) + 1) for m in (1, 2, 5)]
    v = [x for x in v if lo * 0.9 <= x <= hi * 1.1]
    while len(v) > 7:
        v = v[::2]
    return v


def _fmt(x):
    return f"{x / 1e6:,.4g}M" if x >= 1e6 else (f"{x / 1e3:,.4g}K" if x >= 1e4 else f"{x:,.4g}")


def _logaxis(lo, hi):
    tv = _logticks(lo, hi)
    return dict(type='log', title=None, tickvals=tv, ticktext=[_fmt(t) for t in tv], minor=dict(showgrid=False))


_PER = {'3년': 3, '5년': 5, '10년': 10, '20년': 20}


def _segments(close, rows):
    segs, skipped = [], 0
    for r in rows.dropna(subset=['시작일', '종료일']).to_dict('records'):
        s = C.build_segment(close, r.get('라벨'), r['시작일'], r['종료일'])
        if s:
            s['live'] = '진행' in str(r.get('라벨') or '')
            segs.append(s)
        else:
            skipped += 1
    return segs, skipped


def render_for(sym: str, close: pd.Series, tsrc, src: str = 'FinanceDataReader·yfinance(일봉 종가)'):
    """🔍 종목 분석 탭 안 사이클 비교 (2026-11-08 고도화) — 검색한 종목의 일봉을 그대로 쓴다.

    고도화: ① 자동 구간 = 지그재그 스윙(저점→다음 고점 / 고점→다음 저점, X% 되돌림이 나야 꼭짓점) — 슬라이더만 움직이면 다시 계산
            ② 가격 차트에 구간을 색으로 깔아 무엇을 골랐는지 보이게 ③ 진행 중 구간을 굵게 + 과거 중앙 경로(점선)와 겹쳐
            '지금 몇 번째 백분위인가'를 숫자로 ④ 직접 고치기는 토글(자동 결과를 표로 복사해 수정)."""
    close = close.dropna()
    close = close[close > 0]
    if len(close) < 60:
        st.caption('사이클 비교 — 가격 이력이 60일 미만이라 건너뜁니다.')
        return
    K = f"cyc2|{sym}"
    c1, c2, c3 = st.columns([1.3, 1.6, 1.2])
    yrs_all = max(1, (close.index[-1] - close.index[0]).days // 365)
    per_opts = [k for k, v in _PER.items() if v <= yrs_all + 1] + ['전체']
    per = c1.segmented_control('기간', per_opts, default='10년' if '10년' in per_opts else per_opts[-1], key=f'{K}|p') or per_opts[-1]
    x = c2.slider('꼭짓점 기준 — 이만큼 되돌려야 고점·저점으로 인정(%)', 10, 60, 30, 5, key=f'{K}|x',
                  help='작게 하면 작은 출렁임까지 사이클로 잘게 쪼개고, 크게 하면 큰 사이클만 남는다. 반도체 같은 경기민감주는 30~40% 권장')
    manual = c3.toggle('✏️ 구간 직접 고치기', key=f'{K}|man', help='켜면 지금 자동 구간이 표로 복사되고, 그 표를 고친 대로 계산합니다')
    cl = close if per == '전체' else close[close.index >= close.index[-1] - pd.DateOffset(years=_PER[per])]

    auto = C.swing_rows(cl, float(x))
    if manual:
        ek = f'{K}|rows|{per}|{x}'
        if ek not in st.session_state:
            st.session_state[ek] = auto
        rows = st.data_editor(st.session_state[ek], num_rows='dynamic', hide_index=True, use_container_width=True, key=f'{K}|ed|{per}|{x}',
                              column_config={'라벨': st.column_config.TextColumn(width='medium', help="'진행' 이 들어간 라벨 = 진행 중 구간"),
                                             '시작일': st.column_config.DateColumn(min_value=cl.index.min().date(), max_value=cl.index.max().date()),
                                             '종료일': st.column_config.DateColumn(min_value=cl.index.min().date(), max_value=cl.index.max().date())})
    else:
        rows = auto
    segs, skipped = _segments(cl, rows)
    if skipped:
        st.caption(f'⚠️ {skipped}개 구간은 건너뜀 — 시작일이 종료일보다 늦거나 거래일이 2일 미만입니다.')
    if not segs:
        st.info(f'{int(x)}% 이상 되돌린 꼭짓점이 없습니다 — 기준을 낮추거나 기간을 넓혀 보세요.')
        return

    # ── 가격 + 구간 색 ──
    fig0 = go.Figure(go.Scatter(x=cl.index, y=cl.values, line=dict(color='#2453C8', width=1.3), name='종가',
                                hovertemplate='%{x|%Y-%m-%d}<br>%{y:,.0f}<extra></extra>'))
    for s_ in segs:
        fig0.add_vrect(x0=pd.Timestamp(s_['start']), x1=pd.Timestamp(s_['end']), line_width=0, layer='below',
                       fillcolor=_GREEN if s_['direction'] == '상승' else _RED, opacity=0.16 if s_.get('live') else 0.08)
    fig0.update_layout(height=240, margin=dict(l=56, r=8, t=8, b=24), showlegend=False,
                       yaxis=_logaxis(cl.min(), cl.max()))
    st.plotly_chart(fig0, use_container_width=True)

    # ── 지금 위치 ──
    live = next((s_ for s_ in segs if s_.get('live')), None)
    if live:
        w = C.where_now(segs, live)
        k1, k2, k3 = st.columns(3)
        k1.metric(f"지금 = {live['direction']} 구간", f"{live['days']}거래일째", f"{live['ret']:+.1f}% (꼭짓점 {live['start']} 부터)", delta_color='off')
        if w:
            k2.metric(f"과거 {live['direction']} {w['n']}회 중앙", f"{w['days_med']:.0f}거래일 · {w['ret_med']:+.0f}%",
                      f"최장 {w['days_max']:.0f}일 · 최대 {w['ret_max']:+.0f}%", delta_color='off')
            k3.metric("과거 대비 위치", f"기간 {w['days_pct']:.0f} · 폭 {w['ret_pct']:.0f} 백분위",
                      '과거 중앙을 이미 넘음' if w['days_pct'] > 50 and w['ret_pct'] > 50 else
                      ('과거 중앙보다 짧고 얕음' if w['days_pct'] <= 50 and w['ret_pct'] <= 50 else '기간·폭 중 하나만 중앙 넘음'),
                      delta_color='off', help='과거 같은 방향(완료) 구간 중 지금보다 짧았던(얕았던) 비율. 표본이 3회 미만이면 참고만')
        else:
            k2.caption(f"과거 완료된 {live['direction']} 구간이 없어 비교할 수 없습니다.")

    # ── 낙폭 회차 요약 (2026-11-10 '📉 낙폭 회차' 섹션을 여기로 통합 — 같은 질문(얼마나 자주·깊이·오래)을 한 곳에서) ──
    downs = [s_ for s_ in segs if s_['direction'] == '하락' and not s_.get('live')]
    dd_now = float((cl.iloc[-1] / cl.cummax().iloc[-1] - 1) * 100)
    recs = [s_['recover'] for s_ in downs if s_.get('recover') is not None]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(f"{int(x)}%+ 하락", f"{len(downs)}회")
    m2.metric("평균 낙폭", f"{sum(s_['ret'] for s_ in downs) / len(downs):.1f}%" if downs else '-')
    m3.metric("최대 낙폭", f"{min(s_['ret'] for s_ in downs):.1f}%" if downs else '-')
    m4.metric("평균 회복", (f"{sum(recs) / len(recs):.0f}거래일" if recs else ('미회복' if downs else '-')),
              (f"{len(downs) - len(recs)}회 아직 미회복" if downs and len(recs) < len(downs) else None), delta_color='off',
              help='저점에서 그 하락이 시작된 고점 가격을 되찾기까지 걸린 거래일')
    m5.metric("기간 고점 대비 지금", f"{dd_now:.1f}%")

    # ── 구간 그림: 겹쳐 보기(같은 출발점) / 날짜순(MDD 차트) — 2026-11-10 차니 요구: 가로 전체 폭, 종료일 표기, 구간별 색 ──
    view = st.segmented_control('보기', ['겹쳐 보기 — 같은 출발점', '날짜순 — 낙폭(MDD) 차트'],
                                default='겹쳐 보기 — 같은 출발점', key=f'{K}|view') or '겹쳐 보기 — 같은 출발점'
    by_date = view.startswith('날짜순')
    for dirn, color, title in (('하락', _RED, '📉 하락 구간 (고점 → 저점)'), ('상승', _GREEN, '📈 상승 구간 (저점 → 고점)')):
        sub = [s_ for s_ in segs if s_['direction'] == dirn]
        up = dirn == '상승'
        st.caption(title + f" · {sum(1 for s_ in sub if not s_.get('live'))}회 · "
                   + ('세로 = 시작=100(로그)' if up else '세로 = 시작 고점 대비 %')
                   + (' · 가로 = 날짜' if by_date else ' · 가로 = 경과 거래일'))
        if not sub:
            st.caption('— 없음 —')
            continue
        fig = go.Figure()
        tf = (lambda v: 100 + v) if up else (lambda v: v)          # 상승은 '시작=100' 로그 축 — 초대형 상승 한 번이 나머지를 납작하게 누르지 않게
        if by_date and not up:                                      # 바탕 = 기간 전체 낙폭(고점 대비) — 구간 밖 흐름도 보이게
            ddall = (cl / cl.cummax() - 1) * 100
            fig.add_trace(go.Scatter(x=ddall.index, y=ddall.values, fill='tozeroy', mode='lines', name='기간 고점 대비',
                                     line=dict(color='rgba(120,120,120,0.35)', width=0.8), fillcolor='rgba(120,120,120,0.10)',
                                     hovertemplate='%{x|%Y-%m-%d} 고점 대비 %{y:.1f}%<extra></extra>'))
        for i, s_ in enumerate(sub):
            lv = s_.get('live')
            c_ = '#111827' if lv else _PAL[i % len(_PAL)]
            nm = f"{s_['label']} ({s_['start']}~{'진행 중' if lv else s_['end']})".replace(' (진행 중) (', ' (')
            xs = s_['dates'] if by_date else list(s_['series'].index)
            hov = ('%{x|%Y-%m-%d} ' if by_date else '%{x}일째 ') + '%{customdata:+.1f}%<extra>' + s_['label'] + '</extra>'
            fig.add_trace(go.Scatter(x=xs, y=tf(s_['series'].values), name=nm, mode='lines',
                                     line=dict(color=c_, width=3 if lv else 1.6), customdata=s_['series'].values, hovertemplate=hov))
        if not by_date:
            mp = C.median_path([s_ for s_ in sub if not s_.get('live')])
            if mp is not None and len(mp) > 1:
                fig.add_trace(go.Scatter(x=list(mp.index), y=tf(mp.values), name='과거 중앙', line=dict(color='#6B7280', width=3, dash='dot'),
                                         customdata=mp.values, hovertemplate='%{x}일째 중앙 %{customdata:+.1f}%<extra></extra>'))
        fig.add_hline(y=100 if up else 0, line=dict(color='#999', width=1, dash='dot'))
        if not up and by_date:
            fig.add_hline(y=-20, line=dict(color='#7c8290', width=1, dash='dot'), annotation_text='고점 −20% (손절선)',
                          annotation_position='bottom right')
        fig.update_layout(height=340, margin=dict(l=52, r=8, t=8, b=8),
                          legend=dict(orientation='h', y=-0.12, yanchor='top', font=dict(size=10)),
                          xaxis=dict(title=None),
                          yaxis=(_logaxis(100 + min(float(s_['series'].min()) for s_ in sub), 100 + max(float(s_['series'].max()) for s_ in sub)) if up
                                 else dict(title=None, ticksuffix='%')))
        st.plotly_chart(fig, use_container_width=True)

    asof = str(cl.index[-1].date())
    st.markdown("**방향별 통계** (진행 중 구간 제외)")
    tsrc(src + ' · cycle_compare.py', asof=asof)
    summ = C.summarize(segs)
    if len(summ):
        st.dataframe(summ, hide_index=True, use_container_width=True, filters=False)
    with st.expander(f'구간 목록 {len(segs)}개'):
        tsrc(src + ' · cycle_compare.py', asof=asof)
        st.dataframe(C.detail_table(segs), hide_index=True, use_container_width=True, filters=False)
    st.caption(f"꼭짓점 = 그 뒤 {int(x)}% 이상 되돌림이 나온 고점·저점(지그재그) — 나중에야 확정되므로 진행 중 구간의 끝은 아직 모릅니다. "
               "검은 굵은 선 = 지금, 회색 굵은 점선 = 과거 완료 구간의 중앙 경로. 날짜순 보기의 회색 바탕 = 기간 고점 대비 낙폭(MDD), 점선 = 손절선(고점 −20%). 표본이 적으면(3회 미만) 우연일 수 있고, "
               "같은 종목도 사이클 성격(메모리·파운드리·장비 등)이 바뀌면 직접 비교가 어긋납니다.")
