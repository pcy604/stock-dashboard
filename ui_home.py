"""🏠 종합 탭 — 결론 배너 · 시장 카드 · 시장 폭·업종 · 사용법 패널 (2026-11-10 개편).

설계 원칙(대시보드 설계의 정석 — 역피라미드 · 5초 규칙 · 점진적 공개):
  1층 결론(5초)  : 이번 주 실전 규칙(v1.9)이 신규 매수를 허락하나 + 오늘 시장 한 줄
  2층 상태(30초) : 지수·환율·금리·원자재 카드, 한국 시장 폭·업종 강약
  3층 근거(필요 시): 할 일 표 · 시황 리포트 원문 · 챗봇 (dashboard.py)
사용법은 Diátaxis 4분류(투어=배우기 · 루틴=하는 법 · 기능 지도=찾아보기 · 설명서=이해하기)로 나눈다.

데이터는 전부 파일에서만 읽는다(results/market_report.json · live/plan_latest.json). 여기서 외부 호출 없음.
숫자 없으면 '-' — 지어내지 않는다.
"""
from __future__ import annotations

import html
import re

import streamlit as st

CSS = """
<style>
  .hm { font-family:'Pretendard',-apple-system,'Malgun Gothic',system-ui,sans-serif; color:var(--ink); }
  .hm-hero { position:relative; overflow:hidden; border-radius:16px; padding:22px 26px 20px;
             background:linear-gradient(135deg,#111827 0%,#1F2937 100%); color:#F9FAFB; }
  .hm-hero::after { content:""; position:absolute; right:-70px; top:-70px; width:240px; height:240px; border-radius:50%;
             background:radial-gradient(circle,var(--glow,rgba(126,162,255,.30)),transparent 70%); }
  .hm-kick { font-size:11px; font-weight:700; letter-spacing:.14em; color:#93B4FF; margin-bottom:8px; }
  .hm-hero h3 { font-size:23px !important; font-weight:800 !important; letter-spacing:-.03em; margin:0 0 6px;
             color:#fff !important; line-height:1.3; }
  .hm-hero .ov { font-size:13px; color:#FCD34D; margin:0 0 8px; }
  .hm-hero p { font-size:14px; color:#D1D5DB; margin:0; max-width:760px; line-height:1.6; }
  .hm-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:14px; position:relative; z-index:1; }
  .hm-chip { font-size:12px; padding:5px 11px; border-radius:999px; border:1px solid rgba(255,255,255,.18);
             background:rgba(255,255,255,.06); color:#E5E7EB; }
  .hm-chip b.p { color:#4ADE80; } .hm-chip b.n { color:#F87171; }
  .hm-sec { display:flex; align-items:baseline; justify-content:space-between; margin:18px 2px 8px; }
  .hm-sec b { font-size:15px; font-weight:750; letter-spacing:-.02em; }
  .hm-sec span { font-size:12px; color:var(--ink-3); }
  .hm-grid { display:grid; gap:8px; grid-template-columns:repeat(6,minmax(0,1fr)); }
  @media (max-width:980px) { .hm-grid { grid-template-columns:repeat(3,minmax(0,1fr)); } }
  @media (max-width:560px) { .hm-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
    .hm-sec { flex-direction:column; align-items:flex-start; gap:2px; } .hm-sec b { white-space:nowrap; } }
  .hm-card { border:1px solid var(--line); border-radius:10px; background:var(--surface); padding:10px 12px 9px; }
  .hm-card .nm { font-size:12px; color:var(--ink-3); font-weight:600; display:flex; justify-content:space-between; }
  .hm-card .nm i { font-style:normal; font-size:10.5px; padding:1px 6px; border-radius:999px; }
  .hm-card .nm i.up { background:var(--pos-bg); color:var(--pos); } .hm-card .nm i.dn { background:var(--neg-bg); color:var(--neg); }
  .hm-card .px { font-size:19px; font-weight:780; letter-spacing:-.02em; margin:2px 0 0; font-variant-numeric:tabular-nums; }
  .hm-card .d1 { font-size:13px; font-weight:700; font-variant-numeric:tabular-nums; }
  .hm-card .sub { font-size:11px; color:var(--ink-3); margin-top:3px; font-variant-numeric:tabular-nums; }
  .p { color:var(--pos); } .n { color:var(--neg); } .z { color:var(--ink-2); }
  .hm-two { display:grid; gap:10px; grid-template-columns:repeat(auto-fit,minmax(280px,1fr)); }
  .hm-box { border:1px solid var(--line); border-radius:10px; background:var(--surface); padding:12px 14px; }
  .hm-box h5 { font-size:13px !important; font-weight:750 !important; margin:0 0 8px !important; color:var(--ink) !important; }
  .hm-bar { display:flex; height:10px; border-radius:6px; overflow:hidden; background:var(--line-2); margin:6px 0 6px; }
  .hm-bar span { display:block; height:100%; }
  .hm-kv { font-size:12px; color:var(--ink-2); line-height:1.7; font-variant-numeric:tabular-nums; }
  .hm-row { display:flex; justify-content:space-between; font-size:12.5px; padding:3px 0; border-bottom:1px dashed var(--line-2);
            font-variant-numeric:tabular-nums; }
  .hm-row:last-child { border-bottom:0; } .hm-row em { font-style:normal; color:var(--ink-3); font-size:11.5px; }
  .hm-mega { display:flex; flex-wrap:wrap; gap:6px; }
  .hm-mega span { font-size:12px; padding:3px 9px; border-radius:999px; border:1px solid var(--line); background:var(--surface);
            font-variant-numeric:tabular-nums; }
  .hm-src { font-size:11.5px; color:var(--ink-3); margin:6px 2px 0; }
  /* 사용법 패널 */
  .hm-cap { border:1px solid var(--line); border-radius:10px; background:var(--surface); padding:13px 15px; height:100%; box-sizing:border-box; }
  .hm-cap .t { font-size:14.5px; font-weight:780; letter-spacing:-.02em; }
  .hm-cap .q { font-size:12px; color:var(--accent); font-weight:650; margin:2px 0 8px; }
  .hm-cap ul { margin:0; padding-left:16px; } .hm-cap li { font-size:12.5px; color:var(--ink-2); line-height:1.6; }
  .hm-tag { display:inline-block; font-size:10.5px; font-weight:700; padding:0 6px; border-radius:999px; margin-left:4px; vertical-align:1px; }
  .hm-tag.g { background:var(--pos-bg); color:var(--pos); } .hm-tag.y { background:var(--warn-bg); color:var(--warn); }
  .hm-tag.r { background:var(--neg-bg); color:var(--neg); } .hm-tag.k { background:var(--line-2); color:var(--ink-2); }
  .hm-rt { border-left:4px solid var(--accent); }
  .hm-rt .when { font-size:11px; font-weight:700; letter-spacing:.08em; color:var(--ink-3); }
  .hm-rt ol { margin:6px 0 0; padding-left:18px; } .hm-rt li { font-size:12.5px; color:var(--ink-2); line-height:1.65; }
</style>
"""

# 비율·금리·변동성처럼 '오르면 좋다'가 아닌 지표 — 부호로 색칠하면 뜻이 뒤집힌다(CLAUDE.md 표 규칙)
_NEUTRAL = {'VIX', '원/달러', '미국 10년물(%)', '달러인덱스', 'WTI 유가'}
_CARD_ORDER = ['코스피', '코스닥', 'S&P500', '나스닥', '필라델피아 반도체', 'VIX',
               '원/달러', '미국 10년물(%)', '달러인덱스', '금', 'WTI 유가', '비트코인']


def _e(x) -> str:
    return html.escape(str(x if x is not None else '-'))


def _pct(v, cls=True, neutral=False, nd=2) -> str:
    if v is None:
        return '<span class="z">-</span>'
    c = 'z' if (neutral or not cls or v == 0) else ('p' if v > 0 else 'n')
    return f'<span class="{c}">{v:+.{nd}f}%</span>'


def _num(v) -> str:
    if v is None:
        return '-'
    return f"{v:,.0f}" if abs(v) >= 10000 else f"{v:,.2f}"


# ── 데이터 조립 ──────────────────────────────────────────────────────────
def gate(plan: dict) -> dict:
    """실전 v1.9 지수 게이트 — 규칙상 판정(rule_ok)과 봇이 실제로 쓰는 값(ok, 오버라이드 포함)을 따로."""
    rows = []
    for k, lab in (('KR', '코스피'), ('KQ', '코스닥')):
        x = ((plan or {}).get('index') or {}).get(k) or {}
        if not x:
            continue
        last, ma = x.get('last'), x.get('ma200')
        rule_ok = (last is not None and ma is not None and last > ma)
        rows.append(dict(lab=lab, last=last, ma=ma, rule_ok=rule_ok, ok=bool(x.get('ok')),
                         date=x.get('date'), override=x.get('override')))
    ov = next((r['override'] for r in rows if r.get('override')), None)
    n_ok = sum(r['rule_ok'] for r in rows)
    if not rows:
        head, tone = '실전 규칙 판정 불가 — 이번 주 계획표가 없습니다', 'k'
    elif n_ok == len(rows):
        head, tone = '신규 매수 가능 — 코스피·코스닥 모두 주봉 5주선 위', 'g'
    elif n_ok == 0:
        head, tone = '신규 매수 중지 — 코스피·코스닥 모두 주봉 5주선 아래', 'r'
    else:
        on = [r['lab'] for r in rows if r['rule_ok']]
        head, tone = f"부분 허용 — {'·'.join(on)} 소속 종목만 신규 매수", 'y'
    return dict(rows=rows, head=head, tone=tone, override=ov, made=(plan or {}).get('made'))


def one_liner(rep: dict) -> tuple[str, str]:
    """시황 리포트의 '한 줄 요약' 문단 → (문장, 날짜). 한국 장 마감(latest_kr)이 있으면 그걸 먼저."""
    for k in ('latest_kr', 'latest_daily'):
        r = (rep or {}).get(k) or {}
        m = re.search(r'##\s*한 줄 요약\s*\n+(.+?)(?:\n\s*\n|\n##|$)', r.get('markdown') or '', flags=re.S)
        if m:
            return m.group(1).strip().replace('\n', ' '), str(r.get('date') or '')
    return '', ''


def indices(rep: dict) -> list[dict]:
    """지수·자산 카드용 — 같은 이름이면 날짜가 늦은 쪽(한국 장 마감 리포트)을 쓴다."""
    by = {}
    for k in ('latest_daily', 'latest_kr'):
        f = ((rep or {}).get(k) or {}).get('facts') or {}
        for x in (f.get('indices') or []) + ((f.get('us') or {}).get('assets') or []):
            n = x.get('name')
            if n and (n not in by or str(x.get('date') or '') >= str(by[n].get('date') or '')):
                by[n] = x
    return [by[n] for n in _CARD_ORDER if n in by]


# ── 그리기 ──────────────────────────────────────────────────────────────
def hero(g: dict, line: str, line_date: str, chips: list[str]):
    glow = {'g': 'rgba(74,222,128,.30)', 'r': 'rgba(248,113,113,.32)', 'y': 'rgba(252,211,77,.30)'}.get(g['tone'], 'rgba(126,162,255,.30)')
    ov = (f'<div class="ov">⚠️ {_e(g["override"])}</div>' if g.get('override') else '')
    detail = ' · '.join(f"{r['lab']} {_num(r['last'])} vs 5주선 {_num(r['ma'])} ({'위' if r['rule_ok'] else '아래'} · {r.get('date') or '-'} 주봉)"
                        for r in g['rows'])
    body = (f"<p><b style='color:#fff'>오늘 시장</b> — {_e(line)} <span style='color:#9CA3AF'>(AI 요약 · {_e(line_date)})</span></p>"
            if line else "<p>오늘 시황 요약이 아직 없습니다 — 매일 06:45(KST) 한국 장 마감 리포트가 쌓입니다.</p>")
    st.html(CSS + f"""<div class="hm"><div class="hm-hero" style="--glow:{glow}">
      <div class="hm-kick">THIS WEEK · 실전 규칙 v1.9 (한국) · 계획표 {_e(g.get('made'))}</div>
      <h3>{_e(g['head'])}</h3>{ov}
      <p style="font-size:12.5px;color:#9CA3AF;margin-bottom:8px">{_e(detail)}</p>
      {body}
      <div class="hm-chips">{''.join(f'<span class="hm-chip">{c}</span>' for c in chips)}</div>
    </div></div>""")


def market_cards(rows: list[dict], asof: str = ''):
    cards = []
    for x in rows:
        nm = x.get('name')
        neu = nm in _NEUTRAL
        ab = x.get('above_200d')
        sub = f"5일 {_pct(x.get('d5'), neutral=neu, nd=1)} · 1개월 {_pct(x.get('m1'), neutral=neu, nd=1)}"
        tail = []
        if x.get('from_52w_high') is not None:
            tail.append(f"고점 {x['from_52w_high']:+.1f}%")
        if ab is not None:
            dot = 'var(--ink-3)' if neu else ('var(--pos)' if ab else 'var(--neg)')
            tail.append(f"<span style='color:{dot}'>●</span> 200일선 {'위' if ab else '아래'}")
        if tail:
            sub += '<br>' + ' · '.join(tail)
        cards.append(f"""<div class="hm-card"><div class="nm">{_e(nm)}</div>
          <div class="px">{_num(x.get('close'))}</div><div class="d1">{_pct(x.get('d1'), neutral=neu)}</div>
          <div class="sub">{sub}</div></div>""")
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>시장 한눈에</b>
      <span>최근 종가 · 1일 등락 · 고점 = 52주 고점 대비 · 오르면 위험한 지표(VIX·환율·금리·달러·유가)는 색 없음</span></div>
      <div class="hm-grid">{''.join(cards) or '<div class="hm-src">지수 데이터 없음</div>'}</div>
      <div class="hm-src">출처: Yahoo Finance(market_report.py) · 마지막 갱신: {_e(asof)}</div></div>""")


def breadth_sectors(kr: dict, nh: dict, asof: str = ''):
    """한국 시장 폭(상승·하락 종목 수) + 업종 강약 + 시총 상위 — '지수 뒤의 내부 체력'."""
    b = kr.get('breadth_all') or {}
    up, dn, fl = b.get('up') or 0, b.get('down') or 0, b.get('flat') or 0
    tot = up + dn + fl
    if tot:
        bar = (f'<div class="hm-bar"><span style="width:{up / tot * 100:.1f}%;background:var(--pos)"></span>'
               f'<span style="width:{fl / tot * 100:.1f}%;background:#CBD5E1"></span>'
               f'<span style="width:{dn / tot * 100:.1f}%;background:var(--neg)"></span></div>')
        ratio = f"상승 <b class='p'>{up:,}</b> · 보합 {fl:,} · 하락 <b class='n'>{dn:,}</b> — 상승 비율 {up / tot * 100:.0f}%"
    else:
        bar, ratio = '', '전 종목 등락 수 없음'
    to = kr.get('turnover_tn') or {}
    kv = [ratio,
          f"상한가 {b.get('limit_up', '-')} · 하한가 {b.get('limit_down', '-')}",
          ' · '.join(f"{k} 거래대금 {v:,.1f}조" for k, v in to.items()) or '거래대금 -',
          f"대형주 {kr.get('universe', '-')}종 중 상승 {kr.get('breadth_up', '-')}%",
          f"52주 신고가 {nh.get('new_high', '-')}종 · 근접 {nh.get('near_52w', '-')}종 <em style='color:var(--ink-3)'>(대형주 · 주간)</em>"]
    sec = kr.get('sectors') or []
    sec = sorted([s for s in sec if s.get('ret') is not None], key=lambda s: -s['ret'])

    def _rows(ss):
        return ''.join(f"<div class='hm-row'><span>{_e(s['name'])} <em>{s.get('n', '')}종 · 대장 {_e(s.get('lead'))}</em></span>"
                       f"{_pct(s['ret'], nd=1)}</div>" for s in ss) or "<div class='hm-kv'>-</div>"
    mega = ''.join(f"<span>{_e(m.get('name'))} {_pct(m.get('ret'), nd=1)}</span>" for m in (kr.get('megacaps') or [])[:10])
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>🇰🇷 지수 뒤의 체력 — 시장 폭 · 업종</b>
      <span>지수가 올라도 오르는 종목이 적으면 소수 대형주 장세</span></div>
      <div class="hm-two">
        <div class="hm-box"><h5>시장 폭 (코스피+코스닥 전 종목)</h5>{bar}<div class="hm-kv">{'<br>'.join(kv)}</div></div>
        <div class="hm-box"><h5>강한 업종 (시총가중)</h5>{_rows(sec[:5])}</div>
        <div class="hm-box"><h5>하위 업종 (시총가중)</h5>{_rows(sorted(sec[-5:], key=lambda s: s['ret']))}</div>
      </div>
      <div class="hm-sec" style="margin-top:12px"><b style="font-size:13px">시총 상위 10</b><span>지수를 움직이는 종목</span></div>
      <div class="hm-mega">{mega or '<span>-</span>'}</div>
      <div class="hm-src">출처: 네이버 금융 전 종목 시세·업종(market_report.py, 한국 장 마감 리포트) · 마지막 갱신: {_e(asof)}</div></div>""")


# ── 사용법 패널 (Diátaxis) ─────────────────────────────────────────────
# 신뢰 등급: g=실전 규칙/검증됨 · y=참고(검증 중·표본 작음) · k=사실 목록(판단 없음)
CAPS = [
    ("🏠 종합", "이번 주 들어가도 되나?", [
        ("실전 규칙 v1.9 지수 게이트 — 신규 매수 허용 여부", 'g'),
        ("지수·환율·금리·원자재 12종 카드", 'k'),
        ("한국 시장 폭·업종 강약·시총 상위", 'k'),
        ("이번 주 할 일 — 데이터 → 게이트 → 매수 → 보유 점검", 'g'),
        ("시황 리포트(매일 06:45·월요일 주간) · 시황 챗봇", 'y')]),
    ("🌍 매크로", "왜 그런 판정이 나왔나?", [
        ("세계 증시 강도판 — 어디가 제일 강한가", 'k'),
        ("축 1 돈의 흐름 · 축 2 경제(선행·동행)", 'y'),
        ("실전 판정 — 지금 돈을 움직이는 규칙", 'g'),
        ("한국 수급·신용(빚) · 국면 지도(4계절·달걀)", 'y'),
        ("정책금리·국채·수익률곡선·물가·유동성", 'k')]),
    ("🔎 종목 발굴", "그럼 뭘 살까?", [
        ("실전 v1.9 후보 — RS 80+ × 흑자전환 × 5주선 위", 'g'),
        ("이번 주 매수 대상 10종 · 지수 5주선 상태", 'g'),
        ("재료 목록 — 상승 상위·52주 신고가·CANSLIM·이익가속·흑자전환·가치", 'k')]),
    ("🔍 종목 분석", "이 종목, 진짜 맞나?", [
        ("결론 한 줄 → 원하는 축만 펼치기", 'y'),
        ("수급(업종 온도 × 종목 RS) · 펀더멘털(컨센서스·사이클)", 'y'),
        ("밸류(PEG·자기 과거 밴드·업종 대비) · 촉매·리스크", 'y'),
        ("매매 계획(손절·불타기 가격) · 사이클 비교 · 재무 원자료", 'g'),
        ("봇 상태(보유·체결 대기) 배지 · 텔레그램 감시 등록", 'k')]),
    ("🛡️ 내 포트폴리오", "내 계좌는 원칙대로인가?", [
        ("보유 종목 입력 · 토스 연동 시 불러오기(구글 로그인, 내 계정에만 저장)", 'k'),
        ("손절선(보유 중 고점 −20%)·비중 상한 위반 점검", 'g'),
        ("위반 건수는 🏠 종합 '할 일'에 자동 반영", 'k')]),
]
TAG_TXT = {'g': '실전 규칙', 'y': '참고', 'k': '사실', 'r': '약함'}

ROUTINES = [
    ("매일 아침 · 1분", ["텔레그램 @buza_alarm_bot 아침 요약을 받는다",
                       "🏠 종합 맨 위 결론 배너 — 신규 매수 허용인지",
                       "상단 띠의 '데이터 점검'이 0건인지(아니면 숫자를 믿지 않는다)"]),
    ("주말 · 15분", ["🏠 종합 '할 일' — 이번 주 매수 대상·보유 점검",
                     "🔎 종목 발굴 — 후보가 왜 들어왔나(재료 목록과 대조)",
                     "🛡️ 내 포트폴리오 — 손절선(고점 −20%)·RS 70 탈락 확인",
                     "월요일 시가 전, 손절가를 먼저 적어 둔다"]),
    ("종목이 궁금할 때 · 5분", ["🔍 종목 분석에 코드 입력(005930 · NVDA)",
                             "결론 → 수급 → 펀더멘털 → 밸류 순으로 축을 연다",
                             "'매매 계획' 축의 손절가·불타기 가격을 먼저 본다",
                             "봇 배지로 이미 보유·대기 중인지 확인"]),
    ("월 1회 · 20분", ["🌍 매크로 — 국면이 바뀌었나, 매크로 신호가 시장을 이겼나",
                     "성과를 코스피·코스닥과 같은 기간으로 비교",
                     "규칙을 바꾸고 싶으면 먼저 백테스트 — 한 달 성적으로 규칙을 바꾸지 않는다"]),
]


def caps_panel():
    cols = ''.join(
        f"""<div class="hm-cap"><div class="t">{_e(t)}</div><div class="q">{_e(q)}</div><ul>{''.join(
            f'<li>{_e(f)}<span class="hm-tag {c}">{TAG_TXT[c]}</span></li>' for f, c in feats)}</ul></div>"""
        for t, q, feats in CAPS)
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>이 사이트로 할 수 있는 것 — 탭별 전부</b>
      <span><span class="hm-tag g">실전 규칙</span> 봇이 실제로 쓰는 규칙 · <span class="hm-tag y">참고</span> 검증 중·판단 보조 ·
      <span class="hm-tag k">사실</span> 가공 없는 목록</span></div>
      <div class="hm-two" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">{cols}</div></div>""")


def routines_panel():
    cols = ''.join(f"""<div class="hm-cap hm-rt"><div class="when">{_e(w)}</div>
        <ol>{''.join(f'<li>{_e(s)}</li>' for s in steps)}</ol></div>""" for w, steps in ROUTINES)
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>이렇게 쓰면 됩니다 — 시간대별 루틴</b>
      <span>도구보다 순서가 먼저: 판정 → 후보 → 검증 → 손절가</span></div>
      <div class="hm-two" style="grid-template-columns:repeat(auto-fit,minmax(230px,1fr))">{cols}</div></div>""")
