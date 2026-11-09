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


def _when(r):
    st.caption("저점(점화)은 지나고서야 압니다. 미국은 대부분 2022년 약세장 바닥이라 '저점 국면'은 그 해의 설명일 뿐입니다 — "
               "판단에 쓸 수 있는 건 **돌파 주의 국면**입니다. 몰림(배) = 그 국면 비율 ÷ 평소 비율, 1 보다 크면 그 국면에 몰렸다는 뜻.")
    Mc = pd.DataFrame(r['macro'])
    has_bo = 'at_breakout' in Mc and Mc['at_breakout'].notna().any()
    Mt = pd.DataFrame({'국면': Mc['regime'], '평소(%)': Mc['all_weeks'], '저점 주(%)': Mc['at_ignition']})
    if has_bo:
        Mt['돌파 주(%)'] = Mc['at_breakout']
        Mt['돌파 몰림(배)'] = [round(b / a, 2) if a else None for a, b in zip(Mc['all_weeks'], Mc['at_breakout'])]
    Mt['저점 몰림(배)'] = [round(b / a, 2) if a else None for a, b in zip(Mc['all_weeks'], Mc['at_ignition'])]
    _TS[0]('research/winners_reverse.py', path=PATH)
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



def _lessons(r, m):
    """2026-11-10 차니 "여기서 무슨 인사이트를 도출한 건지 모르겠다" → 표 위에 '그래서 무엇을 배웠고 전략에 어떻게 쓰나'.
    숫자는 전부 결과 JSON 에서 — 재계산되면 문장도 따라 바뀐다."""
    F = {f['feat']: f for f in r.get('features') or []}
    C = r.get('combos') or []
    h = r.get('hold') or {}
    bo = h.get('breakout') or {}
    base = r.get('base_p2x')
    lines = []
    top = sorted(F.values(), key=lambda f: -f['lift'])[:2]
    v19 = next((c for c in C if '흑자전환' in c['feat'] and 'RS 80' in c['feat']), None)
    if top:
        t = ' · '.join(f"{f['feat']}(×{f['lift']:.1f})" for f in top)
        s1 = f"**무엇을 — ** 평소 아무 종목이 1년 안에 2배 될 확률 {base}%. 가장 잘 가려낸 특징은 {t}."
        if v19:
            s1 += (f" 실전 v1.9 의 재료 **흑자전환 + RS 80** 을 같이 가지면 {v19['p2x']:.1f}%(×{v19['lift']:.1f}) — "
                   f"방향은 맞다. 단 그래도 {100 - v19['p2x']:.0f}%는 2배가 안 된다 → 한 종목에 걸지 말고 여러 장 + 손절.")
        lo = F.get('52주 고점 -40% 이하')
        if lo:
            s1 += (f" '많이 빠진 종목(52주 고점 −40% 이하)'은 ×{lo['lift']:.2f} — "
                   + ("바닥 줍기는 한국에선 오히려 불리." if lo['lift'] < 1 else "미국에선 반등 후보로 의미 있음(단 RS 80 과 같이일 때)."))
        lines.append(s1)
    if bo.get('left_median') is not None:
        lines.append(f"**언제 — ** 저점은 지나고서야 안다. 저점 대비 이미 +{bo['low_to_bo_median']:.0f}% 오른 **52주 신고가 돌파 주**에 사도 "
                     f"전체 상승의 {bo['left_median']:.0f}%가 남아 있었다 → 바닥을 맞히려 하지 말고 '강해진 걸 확인하고' 산다 "
                     f"(v1.9 의 RS 80·5주선 위 = 돌파 쪽 매수, 그대로 유지).")
    Mc = {x['regime']: x for x in r.get('macro') or []}
    ix = Mc.get('한국 시총합 40주선 위') if m == 'KR' else Mc.get('SPY 40주선 위')
    vx = Mc.get('VIX 25 이상')
    if ix and ix.get('at_breakout') is not None:
        lines.append(f"**시장 — ** 저점(점화)은 공포 속에서(VIX 25 이상 주 {vx['at_ignition']:.0f}% vs 평소 {vx['all_weeks']:.0f}%), "
                     f"돌파는 시장이 살아난 뒤에(지수 40주선 위 {ix['at_breakout']:.0f}% vs 저점 때 {ix['at_ignition']:.0f}%) 왔다 "
                     f"→ '지수가 선 아래면 신규 중지'(v1.9 지수 게이트)는 대박주를 놓치는 규칙이 아니다." if vx else
                     f"**시장 — ** 돌파는 지수 40주선 위에서 {ix['at_breakout']:.0f}% → 지수 게이트는 대박주를 놓치는 규칙이 아니다.")
    so = (h.get('stopped_out') or {}).get('20')
    if so is not None:
        lines.append(f"**보유 — ** 대박주도 가는 길에 중앙 {h['run_dd']['median']:.0f}% 빠졌고, 고점 −20% 손절이면 {so:.0f}%가 중간에 털렸다. "
                     "그런데 포트폴리오 전체로는 −20% 가 −25·30% 보다 낫다(11-08 최적 조건 탐색, 두 구간 공통) — 손절은 대박주를 '끝까지 쥐는' "
                     "규칙이 아니라 실패작을 빨리 버리는 규칙이다.")
        try:
            cp = json.load(open('results/winners_v19_capture.json', encoding='utf-8')) if m == 'KR' else None
        except Exception:
            cp = None
        if cp:
            lines.append(f"**실전 규칙은 대박주를 탔나 — ** 같은 5년 한국 대박주 {cp['winners']}종 중 v1.9 가 산 건 {cp['bought']}종, "
                         f"그중 {cp['stopped']}종이 손절·래칫으로 털렸고 다시 산 건 {cp['rebought']}종, 매도 수익을 이어 곱해 손해로 끝난 게 "
                         f"{cp['net_loss']}종이다. → **v1.9 는 대박주를 '찾기'는 하지만 '타지'는 못한다.** 수익은 대박주 몇 개를 끝까지 쥐어서가 아니라 "
                         "여러 종목을 짧게 갈아타며 난다. 대박주를 더 오래 타려면 손절 '폭'이 아니라 **재진입 규칙**(신고가 재돌파 시 재매수 등)을 "
                         "사전 등록으로 검증해야 한다(10-31 래칫 실험: 신고가 재진입이 승자 ×0.8 → ×2.0~2.7 회복).")
    lines.append("**한계 — ** 같은 5년을 보고 고른 특징이라 가설입니다. 규칙 변경은 반드시 사전 등록 백테스트를 거칩니다.")
    with st.container(border=True):
        st.markdown("##### 🧭 그래서 무엇을 배웠나 — 전략에 쓰는 결론")
        for x in lines:
            st.markdown(f"- {x}")


_TS = [None]


def render(mkt_sel: str, tsrc, name_of=None):
    _TS[0] = tsrc
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

    _lessons(r, m)

    # 2026-11-08 차니 "탭 없이 드러내자" — 서브탭 4개 → 한 화면에 질문 순서대로
    t1 = t2 = t3 = t4 = st.container()
    st.markdown("##### 🏆 ① 누가 대박났나")
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
            st.caption("대상 = 창 시작 주에 이미 상장·유동성 통과한 종목(창 안 신규 상장은 빠짐 — 출발점이 없어서) · 시총 = 창 시작 주 · 저점 = 5년 안 가장 큰 상승의 출발점(지나고서야 앎) · 돌파 = 그 뒤 처음 직전 52주 최고 종가를 넘은 주(그 주에 앎) · "
                       "돌파 뒤 남은 몫 = 저점→고점 로그 상승 중 돌파 이후 비율 · ⇤ = 저점이 창 첫 주(그 전부터 오르던 중, 실제 출발은 더 앞)"
                       + (f" {r['n_edge']}종" if r.get('n_edge') is not None else '') + " · 상장폐지 종목 포함"
                       + (" · 한국은 분할·병합·감자를 이어 붙인 수정주가" if m == 'KR' and new else ''))

    # ── ② 언제 샀어야 했나 (차니 질문 순서: 목록 → 시점 → 특징 → 보유) ──
    st.markdown("##### ⏱ ② 언제 샀어야 했나 — 저점이 아니라 '돌파한 주'")
    _when(r)
    # ── ③ 필요·충분 ──
    st.markdown("##### 🧬 ③ 돌파한 주에 무엇이 달랐나")
    with t2:
        st.caption("**리프트** = 아무 주에서든 그 특징이 있을 때 이후 52주 안에 2배가 될 확률 ÷ 평소 확률(전 종목·전 주) — 높을수록 미리 가려내는 힘. "
                   "**대박주가 돌파 주에 보유** = 대박주가 52주 신고가를 뚫은 그 주에 그 특징을 갖고 있던 비율(필요조건). "
                   "둘 다 높아야 쓸모 있습니다 — 대박주 대부분이 가졌어도 평소에 흔하면(리프트 ≈ 1) 거르는 힘이 없습니다.")
        # 2026-11-08 점검: '저점 ±13주 보유'는 저점 뒤 13주 정보까지 섞여(사후) 판단에 못 씀 → 뺐다. 돌파 주 보유가 그 주에 알 수 있는 값.
        F = pd.DataFrame([{'특징': f['feat'], '대박주가 돌파 주에 보유(%)': f.get('need_bo'), '평소 보유(%)': f['prevalence'],
                           '이후 52주 2배 확률(%)': f['p2x'], '리프트(배)': f['lift'],
                           '이후 52주 중앙(%)': f['med52'], '표본(주·종목)': f['n']} for f in r['features']]).sort_values('리프트(배)', ascending=False)
        if F['대박주가 돌파 주에 보유(%)'].isna().all():
            F = F.drop(columns=['대박주가 돌파 주에 보유(%)'])
        tsrc('research/winners_reverse.py', path=PATH)
        st.dataframe(F, use_container_width=True, hide_index=True, color=False,
                     column_config={c: st.column_config.NumberColumn(format='%.1f') for c in F.columns if c.endswith('(%)')}
                     | {'리프트(배)': st.column_config.NumberColumn(format='%.2f'), '표본(주·종목)': st.column_config.NumberColumn(format='%,d')})
        st.markdown("**특징 두 개 조합 — 리프트 상위** (표본 500 이상)")
        tsrc('research/winners_reverse.py', path=PATH)
        st.dataframe(pd.DataFrame([{'조합': c['feat'], '이후 52주 2배 확률(%)': c['p2x'],
                                    '리프트(배)': c['lift'], '이후 52주 중앙(%)': c['med52'], '표본(주·종목)': c['n']} for c in r['combos']]),
                     use_container_width=True, hide_index=True, color=False, height=300,
                     column_config={'리프트(배)': st.column_config.NumberColumn(format='%.2f'),
                                    '표본(주·종목)': st.column_config.NumberColumn(format='%,d')})
        st.caption("⚠️ 리프트 2배도 확률로는 10~20% — '이 특징이면 대박'이 아니라 '평소보다 몇 배 자주'입니다. 같은 5년을 보고 고른 특징이라 다른 시기 확인 전엔 가설입니다.")

    # ── ④ 꽉 쥐나 ──
    st.markdown("##### ✊ ④ 산 뒤엔 얼마나 흔들렸나 — 언제 꽉 쥐나")
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
