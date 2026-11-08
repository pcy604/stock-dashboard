# -*- coding: utf-8 -*-
"""🔭 대박주 역분석 화면 (2026-11-08 재작성 — 차니 "데이터도 UI도 좀 그렇다") · 계산 research/winners_reverse.py

연구실 → 🧪 퀀트 백테스트 → 🔬 개별 종목 심층 분석 안에 들어간다(전략 시험과 같은 자리 — '종목 단위로 깊게 보기').
화면 순서 = 질문 순서: 누가 대박났나(목록) → 무엇이 공통이었나(필요·충분) → 언제 사야 했나(저점 vs 돌파) → 언제 꽉 쥐나.
옛 결과 JSON(돌파 필드 없음)도 그려지게 — 없는 값은 '-'·'재계산 대기'로 정직하게.
"""
import json
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

PATH = 'results/winners_reverse.json'
_MK = {'US': '🇺🇸 미국', 'KR': '🇰🇷 한국'}
_C1, _C2 = '#0e5a6b', '#D9363E'


def _load():
    try:
        return json.load(open(PATH, encoding='utf-8'))
    except Exception:
        return {}


def _bar(x, y, title, color, ytitle=None, h=230):
    f = go.Figure(go.Bar(x=list(x), y=list(y), marker_color=color, hovertemplate='%{x}<br>%{y}<extra></extra>'))
    f.update_layout(height=h, margin=dict(l=8, r=8, t=30, b=8), title=dict(text=title, font=dict(size=13)), showlegend=False)
    if ytitle:
        f.update_yaxes(title=ytitle)
    return f


def render(mkt_sel: str, tsrc, name_of=None):
    st.markdown("#### 🔭 대박주 역분석 — 최근 5년 2배 이상 오른 종목은 무엇이 달랐고, 언제 샀어야 했나")
    D = _load()
    mk = {k: v for k, v in (D.get('markets') or {}).items() if 'error' not in v}
    if not mk:
        st.info("결과를 만드는 중입니다 — GitHub Actions research-rs: https://github.com/pcy604/stock-dashboard/actions/workflows/research-rs.yml")
        return
    opts = [m for m in (['KR', 'US'] if mkt_sel == '전체' else [mkt_sel]) if m in mk]
    if not opts:
        st.info("이 시장의 결과가 아직 없습니다.")
        return
    m = opts[0] if len(opts) == 1 else (st.segmented_control('시장', opts, default=opts[0], key='wr_m', format_func=_MK.get) or opts[0])
    r = mk[m]
    h = r.get('hold') or {}
    bo = h.get('breakout') or {}
    new = 'min_total' in r                                    # 2026-11-08 재계산본인가
    if not new:
        st.warning("⏳ 이 시장은 옛 계산본입니다(2배 기준·돌파 시점 반영 전). research-rs 가 다시 돌면(약 1시간) 바뀝니다 — "
                   "그때까지 돌파 관련 칸은 비어 있습니다.")

    # ── 핵심 숫자 ─────────────────────────────────────
    k = st.columns(4)
    k[0].metric("대박주", f"{r['n_winners']:,}종", f"대상 {r['eligible']:,}종 중 · {r['window'][0][:7]}~{r['window'][1][:7]}", delta_color='off',
                help=f"창 시작 주에 유동성 통과(미국 시총 $3억·거래대금 $500만 / 한국 1,000억·10억) 종목 중 5년 수익 "
                     f"{'+' + str(int(r['min_total'])) + '% 이상, ' if new else ''}상위 최대 300 · 상장폐지 포함")
    k[1].metric("5년 수익 중앙", f"+{r['winner_total_median']:,.0f}%", f"평소 아무 주나 52주 2배 확률 {r['base_p2x']}%", delta_color='off')
    k[2].metric("52주 돌파에 사도 남은 상승", f"{bo['left_median']:.0f}%" if bo.get('left_median') is not None else '재계산 대기',
                f"저점 뒤 {bo['wk_median']:.0f}주 · 저점 대비 +{bo['low_to_bo_median']:.0f}%에서 돌파" if bo.get('wk_median') is not None else None,
                delta_color='off', help='저점→고점 상승(로그) 중 52주 신고가 돌파 주 이후에 남아 있던 몫의 중앙값. 저점은 지나야 알지만 돌파는 그 주에 안다')
    k[3].metric("고점 −20% 손절에 털림", f"{h['stopped_out']['20']:.0f}%", f"상승 도중 최대 낙폭 중앙 {h['run_dd']['median']:.0f}%",
                delta_color='off', help='점화→고점 사이 고점 대비 −20% 를 한 번이라도 찍고, 그 뒤 더 오른 승자 비율')

    t1, t2, t3, t4 = st.tabs(["🏆 대박주 목록", "🧬 무엇이 달랐나", "⏱ 언제 샀어야 했나", "✊ 언제 꽉 쥐나"])

    # ── ① 목록 ──
    with t1:
        W = pd.DataFrame(r.get('winners') or [])
        if not len(W):
            st.caption('목록 없음')
        else:
            nm = W['name'] if 'name' in W else pd.Series([None] * len(W))
            W['종목'] = [n or (name_of(str(s)) if name_of else None) or str(s) for s, n in zip(W.sym, nm)]
            cap = '시총(억원)' if m == 'KR' else '시총($B)'
            W[cap] = (W['mc0'] / (1e8 if m == 'KR' else 1e9)) if 'mc0' in W else None
            for c in ('bo', 'low_to_bo', 'bo_to_peak', 'left', 'edge'):
                if c not in W:
                    W[c] = None
            W['저점 주'] = [f"{t}{' ⇤' if e else ''}" for t, e in zip(W.t0, W.edge)]
            V = pd.DataFrame({'종목': W['종목'], '코드': W.sym.astype(str), cap: W[cap],
                              '5년 수익률(%)': W.total, '저점 주': W['저점 주'], '돌파 주': W.bo, '고점 주': W.peak,
                              '저점→고점(%)': W.run_gain, '돌파→고점(%)': W.bo_to_peak, '돌파 뒤 남은 몫(%)': W.left,
                              '저점→고점(주)': W.run_wk, '도중 최대 낙폭(%)': W.run_dd})
            tsrc('research/winners_reverse.py (GitHub Actions research-rs)', path=PATH)
            st.dataframe(V, use_container_width=True, hide_index=True, height=420,
                         column_config={cap: st.column_config.NumberColumn(format='%,.0f' if m == 'KR' else '%.1f'),
                                        **{c: st.column_config.NumberColumn(format='%,.0f') for c in
                                           ('5년 수익률(%)', '저점→고점(%)', '돌파→고점(%)', '돌파 뒤 남은 몫(%)', '저점→고점(주)', '도중 최대 낙폭(%)')}})
            st.caption("시총 = 창 시작 주 · 저점 = 5년 안 가장 큰 상승의 출발점(지나고서야 앎) · 돌파 = 그 뒤 처음 직전 52주 최고 종가를 넘은 주(그 주에 앎) · "
                       "돌파 뒤 남은 몫 = 저점→고점 로그 상승 중 돌파 이후 비율 · ⇤ = 저점이 창 첫 주(그 전부터 오르던 중, 실제 출발은 더 앞)"
                       + (f" {r['n_edge']}종" if r.get('n_edge') is not None else '') + " · 상장폐지 종목 포함"
                       + (" · 한국은 분할·병합·감자를 이어 붙인 수정주가" if m == 'KR' and new else ''))

    # ── ② 필요·충분 ──
    with t2:
        st.caption("**필요조건** = 대박주가 그 특징을 갖고 있던 비율 · **리프트** = 평소 그 특징이 있을 때 이후 52주 2배 확률 ÷ 전체 확률. "
                   "대박주 대부분이 가졌어도 평소에 흔하면 리프트 ≈ 1 = 미리 가려내는 힘이 없습니다. **돌파 주 보유**가 실제로 쓸 수 있는 숫자입니다.")
        F = pd.DataFrame([{'특징': f['feat'], '돌파 주 보유(%)': f.get('need_bo'), '저점 ±13주 보유(%)': f['need_near'],
                           '평소 보유(%)': f['prevalence'], '이후 52주 2배 확률(%)': f['p2x'], '리프트(배)': f['lift'],
                           '이후 52주 중앙(%)': f['med52'], '표본(주·종목)': f['n']} for f in r['features']])
        if F['돌파 주 보유(%)'].isna().all():
            F = F.drop(columns=['돌파 주 보유(%)'])
        tsrc('research/winners_reverse.py', path=PATH)
        st.dataframe(F, use_container_width=True, hide_index=True, color=False,
                     column_config={c: st.column_config.NumberColumn(format='%.1f') for c in F.columns if c.endswith('(%)')}
                     | {'리프트(배)': st.column_config.NumberColumn(format='%.2f'), '표본(주·종목)': st.column_config.NumberColumn(format='%,d')})
        st.markdown("**특징 두 개 조합 — 리프트 상위** (표본 500 이상)")
        tsrc('research/winners_reverse.py', path=PATH)
        st.dataframe(pd.DataFrame([{'조합': c['feat'], '대박주 보유(%)': c['need_near'], '이후 52주 2배 확률(%)': c['p2x'],
                                    '리프트(배)': c['lift'], '이후 52주 중앙(%)': c['med52'], '표본(주·종목)': c['n']} for c in r['combos']]),
                     use_container_width=True, hide_index=True, color=False, height=300,
                     column_config={'리프트(배)': st.column_config.NumberColumn(format='%.2f'),
                                    '표본(주·종목)': st.column_config.NumberColumn(format='%,d')})
        st.caption("⚠️ 리프트 2배도 확률로는 10~20% — '이 특징이면 대박'이 아니라 '평소보다 몇 배 자주'입니다. 같은 5년을 보고 고른 특징이라 다른 시기 확인 전엔 가설입니다.")

    # ── ③ 언제 사나 ──
    with t3:
        st.caption("저점(점화)은 지나고서야 압니다. 미국은 대부분 2022년 약세장 바닥이라 '저점 국면'은 그 해의 설명일 뿐입니다 — "
                   "판단에 쓸 수 있는 건 **돌파 주의 국면**입니다. 몰림(배) = 그 국면 비율 ÷ 평소 비율, 1 보다 크면 그 국면에 몰렸다는 뜻.")
        Mc = pd.DataFrame(r['macro'])
        has_bo = 'at_breakout' in Mc and Mc['at_breakout'].notna().any()
        Mt = pd.DataFrame({'국면': Mc['regime'], '평소(%)': Mc['all_weeks'], '저점 주(%)': Mc['at_ignition']})
        if has_bo:
            Mt['돌파 주(%)'] = Mc['at_breakout']
            Mt['돌파 몰림(배)'] = [round(b / a, 2) if a else None for a, b in zip(Mc['all_weeks'], Mc['at_breakout'])]
        Mt['저점 몰림(배)'] = [round(b / a, 2) if a else None for a, b in zip(Mc['all_weeks'], Mc['at_ignition'])]
        tsrc('research/winners_reverse.py', path=PATH)
        st.dataframe(Mt, use_container_width=True, hide_index=True, filters=False, color=False,
                     column_config={c: st.column_config.NumberColumn(format='%.2f') for c in Mt.columns if '몰림' in c})
        c1, c2 = st.columns(2)
        iq = r.get('ignition_by_q') or {}
        bq = r.get('breakout_by_q') or {}
        if iq:
            c1.plotly_chart(_bar(iq, iq.values(), '분기별 저점(점화) 종목 수', '#7C8AA5'), use_container_width=True)
        if bq:
            c2.plotly_chart(_bar(bq, bq.values(), '분기별 52주 돌파 종목 수', _C1), use_container_width=True)
        else:
            c2.caption('돌파 분포 — 재계산 대기')

    # ── ④ 꽉 쥐나 ──
    with t4:
        s = h['stopped_out']
        q = st.columns(5)
        q[0].metric("저점→고점 기간(중앙)", f"{h['run_wk']['median']:.0f}주", f"상승 중앙 +{h['run_gain_median']:,.0f}%", delta_color='off')
        for i, x in enumerate(('20', '25', '30', '40'), 1):
            q[i].metric(f"고점 −{x}% 손절", f"{s[x]:.0f}% 털림", delta_color='off')
        sh = h['share_by_13w_mean']
        st.plotly_chart(_bar([f"{i * 13 + 1}~{(i + 1) * 13}주" for i in range(len(sh))], sh,
                             '저점 뒤 13주 단위 상승 몫(평균, %) — 상승은 어디에 몰리나', _C1, '상승 몫(%)', h=250), use_container_width=True)
        st.caption(f"상승 도중 최대 낙폭: 중앙 {h['run_dd']['median']:.0f}% · 하위 25% {h['run_dd']['p25']:.0f}% · 하위 10% {h['run_dd']['worst10']:.0f}%. "
                   "대박주라도 가는 길에 이만큼 빠집니다 — 손절 폭이 이보다 좁으면 대부분 중간에 털립니다(실전 v1.9 = 고점 −20%).")
    if r.get('note'):
        st.caption(r['note'])
