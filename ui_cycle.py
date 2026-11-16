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
if getattr(C, 'VERSION', 1) < 2:          # 2026-11-10 클라우드가 옛 cycle_compare 를 들고 있어 KeyError 'dates'·전부 '미회복'이 떴다
    import importlib
    C = importlib.reload(C)
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
            st.warning(f"'{q}' 와 맞는 종목이 없습니다. 종목명 일부 또는 종목코드로 다시 검색해 주십시오.")
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
        st.info('종목을 검색해 주십시오.')
        return
    m = S.market_of(sym)
    close = C.load_close(sym, m)
    if close is None or len(close) < 10:
        st.error(f'{sym}({m}) 가격 데이터가 없습니다 — 종목코드를 확인해 주십시오.')
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
    # 2026-11-15 — 기간 버튼 삭제(통계는 가진 이력 전체) · 기준 10~80% · 가격 차트는 위 '차트'에 구간 색으로 합침
    # 2026-11-16 — 한 줄: 구간 판정 기준(좁게) · 그림 보기 · 직접 고치기
    c2, cv, c3 = st.columns([1.6, 1.6, 0.9], vertical_alignment='bottom')
    x = c2.slider('구간 판정 기준(%)', 10, 80, 30, 5, key=f'{K}|x',
                  help='고점에서 이 비율 이상 하락하면 하락 구간, 저점에서 이 비율 이상 상승하면 상승 구간으로 끊는다. '
                       '값이 작으면 작은 등락까지 나뉘고, 크면 큰 사이클만 남는다(경기민감주 30~40% · 장기 사이클 50% 이상).')
    # 2026-11-16 차니 — 기본 = 기간 추이(날짜축)
    view = cv.segmented_control('그림', ['기간 추이', '구간 비교'], default='기간 추이', key=f'{K}|view3',
                                help='기간 추이 = 날짜축 위 고점 대비 낙폭(MDD) · 구간 비교 = 모든 구간을 같은 출발점(0일·0%)에 겹침') or '기간 추이'
    manual = c3.toggle('구간 직접 수정', key=f'{K}|man', help='켜면 자동 구간이 표로 복사되고, 고친 표대로 계산합니다')
    per = '전체'
    cl = close

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
        st.info(f'{int(x)}% 이상 되돌린 꼭짓점이 없습니다 — 기준을 낮추거나 기간을 넓혀 주십시오.')
        return

    # ── 지금 위치 ──
    live = next((s_ for s_ in segs if s_.get('live')), None)
    downs = [s_ for s_ in segs if s_['direction'] == '하락' and not s_.get('live')]
    dd_now = float((cl.iloc[-1] / cl.cummax().iloc[-1] - 1) * 100)
    recs = [s_['recover'] for s_ in downs if s_.get('recover') is not None]
    yrs = (cl.index[-1] - cl.index[0]).days / 365.25
    parts = []
    if live:
        w = C.where_now(segs, live)
        tone = '#B91C1C' if live['direction'] == '하락' else '#15803D'
        parts.append(f"<b style='color:{tone}'>지금 {live['direction']} {live['days']}거래일째 {live['ret']:+.1f}%</b> "
                     f"<span class='m'>({live['start']} 꼭짓점부터)</span>")
        if w:
            pos = ('과거 중앙을 이미 넘음' if w['days_pct'] > 50 and w['ret_pct'] > 50 else
                   ('과거 중앙보다 짧고 얕음' if w['days_pct'] <= 50 and w['ret_pct'] <= 50 else '기간·폭 중 하나만 중앙 넘음'))
            parts.append(f"과거 {live['direction']} {w['n']}회 중앙 {w['days_med']:.0f}일·{w['ret_med']:+.0f}% → <b>{pos}</b> "
                         f"<span class='m'>(기간 {w['days_pct']:.0f}·폭 {w['ret_pct']:.0f} 백분위)</span>")
    if downs:
        parts.append(f"{int(x)}%+ 하락 <b>{len(downs)}회</b> · 평균 {sum(s_['ret'] for s_ in downs) / len(downs):.0f}% · "
                     f"최대 {min(s_['ret'] for s_ in downs):.0f}% · 회복 평균 "
                     + (f"{sum(recs) / len(recs):.0f}거래일" if recs else '미회복')
                     + (f" ({len(downs) - len(recs)}회 미회복)" if len(recs) < len(downs) else ''))
    parts.append(f"전체 고점 대비 지금 <b>{dd_now:.1f}%</b> <span class='m'>({yrs:.0f}년 이력)</span>")
    st.markdown("<div style='background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:10px 14px;font-size:13.5px;"
                "line-height:1.9'>" + " &nbsp;│&nbsp; ".join(parts).replace("class='m'", "style='color:#6B7280'") + "</div>",
                unsafe_allow_html=True)

    # ── 구간 그림: 겹쳐 보기(같은 출발점) / 날짜순(MDD 차트) — 2026-11-10 차니 요구: 가로 전체 폭, 종료일 표기, 구간별 색 ──
    by_date = view == '기간 추이'
    ddall = (cl / cl.cummax() - 1) * 100
    # 2026-11-16 차니 — 하락·상승 두 그림의 가로축을 같게(날짜 = 전체 이력 · 경과일 = 가장 긴 구간)
    xr = ([cl.index[0], cl.index[-1]] if by_date else [0, max(len(s_['series']) for s_ in segs)])
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
            fig.add_trace(go.Scatter(x=ddall.index, y=ddall.values, fill='tozeroy', mode='lines', name='기간 고점 대비',
                                     line=dict(color='rgba(120,120,120,0.35)', width=0.8), fillcolor='rgba(120,120,120,0.10)',
                                     hovertemplate='%{x|%Y-%m-%d} 고점 대비 %{y:.1f}%<extra></extra>'))
        for i, s_ in enumerate(sub):
            lv = s_.get('live')
            c_ = '#111827' if lv else _PAL[i % len(_PAL)]
            nm = f"{s_['label']} ({s_['start']}~{'진행 중' if lv else s_['end']})".replace(' (진행 중) (', ' (')
            xs = s_['dates'] if by_date else list(s_['series'].index)
            hov = ('%{x|%Y-%m-%d} ' if by_date else '%{x}일째 ') + '%{customdata:+.1f}%<extra>' + s_['label'] + '</extra>'
            # 2026-11-16 차니 — 날짜축 하락선은 바탕(전체 고점 대비)과 같은 기준으로: 구간 시작 고점이 전고점보다 낮으면
            #   '구간 기준 %'는 바탕과 어긋났다(하락2·3). y = 전체 고점 대비 · 마우스 = 구간 시작 대비.
            yv = (ddall.reindex(pd.DatetimeIndex(s_['dates'])).values if (by_date and not up) else tf(s_['series'].values))
            hov = (('%{x|%Y-%m-%d} 전고점 대비 %{y:.1f}% · 구간 시작 대비 %{customdata:+.1f}%<extra>' + s_['label'] + '</extra>')
                   if (by_date and not up) else hov)
            fig.add_trace(go.Scatter(x=xs, y=yv, name=nm, mode='lines',
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
                          xaxis=dict(title=None, range=xr),
                          yaxis=(_logaxis(100 + min(float(s_['series'].min()) for s_ in sub), 100 + max(float(s_['series'].max()) for s_ in sub)) if up
                                 else dict(title=None, ticksuffix='%')))
        st.plotly_chart(fig, use_container_width=True)

    asof = str(cl.index[-1].date())
    # 2026-11-16 — 요약 표 + 상세 표 → 한 표(차니): 구간 행(최근 순) 아래에 방향별 평균·중앙값 행
    det = C.detail_table(segs).iloc[::-1].reset_index(drop=True)
    summ = C.summarize(segs)
    extra = []
    for r_ in summ.to_dict('records'):
        extra.append({'라벨': f"▶ {r_['방향']} 평균 ({r_['구간수']}회)", '시작': '', '종료': '',
                      '기간(거래일)': r_['평균 기간(거래일)'], '수익률(%)': r_['평균 수익률(%)'], '회복까지(거래일)': None, '방향': r_['방향']})
        extra.append({'라벨': f"▶ {r_['방향']} 중앙값", '시작': '', '종료': '',
                      '기간(거래일)': r_['중앙 기간(거래일)'], '수익률(%)': r_['중앙 수익률(%)'], '회복까지(거래일)': None, '방향': r_['방향']})
    st.markdown(f"**구간 {len(segs)}개 + 방향별 평균·중앙값**(맨 아래 ▶ 행, 진행 중 구간 제외)")
    tsrc(src + ' · cycle_compare.py', asof=asof)
    st.dataframe(pd.concat([det, pd.DataFrame(extra)], ignore_index=True), hide_index=True, use_container_width=True, filters=False)
    st.caption(f"꼭짓점 = 그 뒤 {int(x)}% 이상 되돌림 · 진행 중 구간의 끝은 미확정")
    _dd_backtest(K, cl, tsrc, src, asof)


def _dd_backtest(K: str, cl: pd.Series, tsrc, src: str, asof: str):
    """낙폭 매수 백테스트(2026-11-16 차니) — '고점 대비 −X% 도달' 또는 '−X% 밑까지 갔다가 다시 −X% 위로 회복한 다음 날' 매수.
    한 하락 회차(고점 갱신 전까지)에 신호 1번. 수익률은 그 뒤 N거래일 종가 기준 · 수수료 미반영 · 같은 종목 과거만."""
    import numpy as np
    st.markdown("#### 🧪 낙폭 매수 백테스트")
    b1, b2, b3 = st.columns([1.2, 2.2, 2.2], vertical_alignment='bottom')
    th = b1.number_input('기준 낙폭(%)', 5, 90, 30, 5, key=f'{K}|bt_x', help='고점 대비 이만큼 빠진 지점을 기준으로 삼는다')
    # 2026-11-16 차니 — 둘 다 '다음 날 종가'(장중 감시 없이 따라 할 수 있게) · 버튼 이름 정식 표현
    mode = b2.segmented_control('매수 시점', ['하향 돌파 익일', '재상향 돌파 익일'], default='하향 돌파 익일', key=f'{K}|bt_m2',
                                help='하향 돌파 익일 = 종가가 처음 고점 대비 −X% 아래로 내려간 다음 거래일 종가 · '
                                     '재상향 돌파 익일 = −X% 아래에 있다가 종가가 다시 −X% 위로 올라선 다음 거래일 종가') or '하향 돌파 익일'
    hz = b3.pills('보유 기간', ['1개월', '3개월', '6개월', '1년'], selection_mode='multi', default=['3개월', '6개월', '1년'], key=f'{K}|bt_h') or ['6개월']
    H = {'1개월': 21, '3개월': 63, '6개월': 126, '1년': 252}
    hz = sorted(hz, key=lambda h: H[h])           # 누른 순서가 아니라 짧은 기간부터(표 열 순서)
    c = cl.dropna()
    peak = c.cummax()
    dd = (c / peak - 1) * 100
    v, ix, pk = c.values, c.index, peak.values
    events, armed_peak, below = [], None, False
    for i in range(1, len(v)):
        if pk[i] > pk[i - 1]:                 # 새 고점 = 새 하락 회차
            armed_peak, below = None, False
        if armed_peak is not None:
            continue
        if mode == '하향 돌파 익일':
            if dd.iloc[i] <= -th and i + 1 < len(v):
                events.append(i + 1); armed_peak = pk[i]
        else:
            if dd.iloc[i] <= -th:
                below = True
            elif below and dd.iloc[i] > -th and i + 1 < len(v):
                events.append(i + 1); armed_peak = pk[i]
    if not events:
        st.caption(f'고점 대비 −{th}% 신호가 이력에 없음.')
        return
    rows = []
    for i in events:
        r_ = {'매수일': str(ix[i].date()), '매수가': round(float(v[i]), 2), '매수일 낙폭(%)': round(float(dd.iloc[i]), 1)}
        for h in hz:
            j = i + H[h]
            r_[f'{h} 뒤(%)'] = round(float(v[j] / v[i] - 1) * 100, 1) if j < len(v) else None
        j_end = min(len(v) - 1, i + max(H[h] for h in hz))
        r_['이후 최대 추가 하락(%)'] = round(float((v[i:j_end + 1].min() / v[i] - 1) * 100), 1)
        rows.append(r_)
    df = pd.DataFrame(rows)
    stat = []
    for h in hz:
        col = df[f'{h} 뒤(%)'].dropna()
        if len(col):
            stat.append(f"{h} 뒤 평균 {col.mean():+.1f}% · 승률 {(col > 0).mean() * 100:.0f}% ({len(col)}회)")
    bh = (v[-1] / v[0] - 1) * 100
    st.markdown(' &nbsp;│&nbsp; '.join(stat) + f" &nbsp;│&nbsp; 이후 최대 추가 하락 평균 {df['이후 최대 추가 하락(%)'].mean():.1f}%")
    tsrc(src + ' · 낙폭 매수 백테스트(이 화면 계산)', asof=asof)
    st.dataframe(df.iloc[::-1].reset_index(drop=True), hide_index=True, use_container_width=True, filters=False)
    st.caption(f"신호 다음 거래일 종가 매수 · 하락 회차(전고점 갱신 전)마다 1번 · 수수료 미반영 · 같은 기간 보유만 {bh:+,.0f}% · 3회 미만은 우연 가능")
