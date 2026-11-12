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

# dashboard.py 가 이 값과 다르면 importlib.reload — 클라우드가 옛 모듈을 메모리에 들고 있던 사고(2026-11-12 배포 화면
# 'module ui_home has no attribute account') 재발 방지. 이 파일을 고치면 반드시 올린다.
VERSION = '2026-11-12e'

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
  .hm-mega { display:grid; gap:6px; grid-template-columns:repeat(5,minmax(0,1fr)); }
  .hm-mega > span { font-size:12px; padding:5px 10px; border-radius:8px; border:1px solid var(--line); background:var(--surface);
            font-variant-numeric:tabular-nums; display:flex; justify-content:space-between; gap:6px; white-space:nowrap; overflow:hidden; }
  .hm-four { display:grid; gap:10px; grid-template-columns:repeat(4,minmax(0,1fr)); }
  @media (max-width:1100px) { .hm-four { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  @media (max-width:560px) { .hm-four { grid-template-columns:1fr; } .hm-mega { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  .hm-steps { border:1px solid var(--line); border-radius:10px; background:var(--surface); overflow:hidden; }
  .hm-step { display:grid; grid-template-columns:22px 118px 1fr; gap:10px; align-items:start; padding:10px 14px;
            border-bottom:1px solid var(--line-2); font-size:13px; }
  .hm-step:last-child { border-bottom:0; }
  .hm-step .dot { width:10px; height:10px; border-radius:50%; margin-top:5px; }
  .hm-step .k { font-weight:700; color:var(--ink); } .hm-step .v { color:var(--ink-2); line-height:1.55; }
  .hm-step .v em { font-style:normal; color:var(--ink-3); font-size:12px; margin-left:8px; }
  .hm-step .v em::before { content:'· '; }
  .hm-acc { display:grid; gap:8px; grid-template-columns:repeat(6,minmax(0,1fr)); }
  @media (max-width:980px) { .hm-acc { grid-template-columns:repeat(2,minmax(0,1fr)); } }
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


def breadth_sectors(kr: dict, nh: dict, asof: str = '', flow: dict | None = None):
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
    mega = ''.join(f"<span><b style='font-weight:600'>{_e(m.get('name'))}</b>{_pct(m.get('ret'), nd=1)}</span>" for m in (kr.get('megacaps') or [])[:10])
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>🇰🇷 지수 뒤의 체력 — 시장 폭 · 업종</b>
      <span>지수가 올라도 오르는 종목이 적으면 소수 대형주 장세</span></div>
      <div class="hm-four">
        <div class="hm-box"><h5>시장 폭 (코스피+코스닥 전 종목)</h5>{bar}<div class="hm-kv">{'<br>'.join(kv)}</div></div>
        {flow_box(flow or {})}
        <div class="hm-box"><h5>강한 업종 (시총가중)</h5>{_rows(sec[:5])}</div>
        <div class="hm-box"><h5>하위 업종 (시총가중)</h5>{_rows(sorted(sec[-5:], key=lambda s: s['ret']))}</div>
      </div>
      <div class="hm-sec" style="margin-top:12px"><b style="font-size:13px">시총 상위 10</b><span>지수를 움직이는 종목</span></div>
      <div class="hm-mega">{mega or '<span>-</span>'}</div>
      <div class="hm-src">출처: 네이버 금융 전 종목 시세·업종·투자자별 매매·증시자금동향(market_report.py · tools/kr_flow.py) · 마지막 갱신: {_e(asof)}</div></div>""")


def _jo(v):
    """억원 → '±1.23조' 또는 '±4,567억'."""
    if v is None:
        return '-'
    return f"{v / 1e4:+.1f}조" if abs(v) >= 1e4 else f"{v:+,.0f}억"


def _sgn(v, txt):
    if v is None or v == 0:
        return f"<span class='z'>{txt}</span>"
    return f"<span class='{'p' if v > 0 else 'n'}'>{txt}</span>"


def flow_box(fl: dict) -> str:
    """수급 박스 — 오늘(잠정) 외국인·기관 + 5·20일 누적(kr_flow) + 신용잔고. 날짜를 같이 적고 3일 넘게 묵으면 경고.
    입력 = dict(today={'KOSPI':{개인,외국인,기관},...}, today_date=, summary=kr_flow.summary, asof=오늘)."""
    import datetime as _dt
    sm = fl.get('summary') or {}
    td = fl.get('today') or {}
    lines = []
    for mk, lab in (('KOSPI', '코스피'), ('KOSDAQ', '코스닥')):
        t, s = td.get(mk) or {}, sm.get(mk) or {}
        f1 = t.get('외국인') if t else s.get('d1')
        i1 = t.get('기관') if t else None
        bits = [f"외국인 {_sgn(f1, _jo(f1))}"]
        if i1 is not None:
            bits.append(f"기관 {_sgn(i1, _jo(i1))}")
        if s.get('d5') is not None:
            bits.append(f"<em>외국인 5일 {_sgn(s['d5'], _jo(s['d5']))} · 20일 {_sgn(s.get('d20'), _jo(s.get('d20')))}</em>")
        lines.append(f"<div class='hm-row' style='display:block'><b>{lab}</b> {' · '.join(bits[:2])}<br>{bits[2] if len(bits) > 2 else ''}</div>")
    cr = sm.get('credit') or {}
    if cr.get('v') is not None:
        lines.append(f"<div class='hm-row' style='display:block'><b>신용잔고</b> {cr['v'] / 1e4:,.1f}조 "
                     f"<em>(고점 대비 {cr.get('from_peak', 0):+.1f}% · {_e(cr.get('date'))})</em></div>")
    when = fl.get('today_date') if td else (sm.get('KOSPI') or {}).get('date')
    stale = ''
    try:
        gap = (_dt.date.fromisoformat(str(fl.get('asof'))[:10]) - _dt.date.fromisoformat(str(when)[:10])).days
        if gap > 3:
            stale = f"<div class='hm-kv' style='color:var(--warn)'>⚠️ {gap}일 전 자료 — 수집 정지 확인 필요</div>"
    except Exception:
        pass
    tag = '오늘 잠정' if td else '최근 거래일'
    return (f"<div class='hm-box'><h5>수급 — 누가 사고 파나 <span style='font-weight:500;color:var(--ink-3);font-size:11.5px'>"
            f"({tag} · {_e(when)})</span></h5>{''.join(lines) or '<div class=hm-kv>수급 자료 없음</div>'}{stale}</div>")


def steps(rows: list[tuple]):
    """할 일 체크리스트 — (단계, 톤 g/y/r/k, 본문, 보조) . 표가 아니라 순서 목록이라 카드 목록으로(같은 디자인)."""
    col = {'g': 'var(--pos)', 'y': '#D97706', 'r': 'var(--neg)', 'k': '#CBD5E1'}
    body = ''.join(f"""<div class="hm-step"><span class="dot" style="background:{col.get(t, '#CBD5E1')}"></span>
        <span class="k">{_e(k)}</span><span class="v">{v}{f' <em>{sub}</em>' if sub else ''}</span></div>"""
                   for k, t, v, sub in rows)
    st.html(CSS + f'<div class="hm"><div class="hm-steps">{body}</div></div>')


def account(led: dict, plan: dict, sectors: dict | None = None) -> dict:
    """실전 원장(한국) 요약. 2026-11-12: **토스 스냅샷(led['toss'])이 있으면 수량·평단·현재가·현금은 토스가 정답**
    (원장 현금은 11-11 손 입력 추정치였다 — 61,370 vs 토스 45,031). 고점·손절가·불타기 횟수는 원장(봇 상태).
    원장과 토스 수량이 다르면 mismatch 에 담는다(주문 직후 미체결·이중 체결을 화면에서 바로 보이게)."""
    kr = (led or {}).get('KR') or {}
    pos = kr.get('positions') or {}
    tz = (led or {}).get('toss') or {}
    th = {str(h.get('sym')): h for h in (tz.get('holdings') or [])}
    use_t = bool(th)
    dep = sum(float(d[1]) for d in (kr.get('deposits') or []) if len(d) > 1)
    cash = float(tz['cash_krw']) if use_t and tz.get('cash_krw') is not None else float(kr.get('cash_krw') or 0)
    rows, ev, cost, mism = [], 0.0, 0.0, []
    for code in sorted(set(pos) | set(th)):
        p, h = pos.get(code) or {}, th.get(code) or {}
        sh = float(h['qty']) if h.get('qty') is not None else float(p.get('shares') or 0)
        avg = h.get('avg_cost') if h.get('avg_cost') is not None else p.get('avg')
        px = h.get('last_price') if h.get('last_price') is not None else p.get('last_px')
        if use_t and float(p.get('shares') or 0) != sh:
            mism.append(f"{p.get('name') or h.get('name')} 원장 {float(p.get('shares') or 0):g}주 · 토스 {sh:g}주")
        ev += (px or avg or 0) * sh
        cost += (avg or 0) * sh
        peak = max(x for x in (p.get('peak'), px) if x) if (p.get('peak') or px) else None
        stop = p.get('stop')
        sd = (sectors or {}).get(code) or {}
        rows.append(dict(종목=p.get('name') or h.get('name'), 코드=code, 업종=sd.get('upjong'), **{
            '수량(주)': sh, '평단(원)': avg, '현재가(원)': px,
            '수익률(%)': (px / avg - 1) * 100 if px and avg else None,
            '보유 고점(원)': peak, '손절가(원)': stop,
            '손절 여유(%)': (px / stop - 1) * 100 if px and stop else None,
            '불타기': p.get('adds') or 0, '매수일': p.get('opened')}))
    tot = ev + cash
    # 업종 쏠림 — 평가액 기준 업종 비중 + 2종 이상 겹치는 테마(같이 빠질 위험)
    by, th_cnt = {}, {}
    for r in rows:
        v = (r['현재가(원)'] or r['평단(원)'] or 0) * r['수량(주)']
        by[r['업종'] or '미분류'] = by.get(r['업종'] or '미분류', 0) + v
        for t in ((sectors or {}).get(r['코드']) or {}).get('themes') or []:
            th_cnt.setdefault(t, []).append(r['종목'])
    top_sec = max(by.items(), key=lambda kv: kv[1]) if by else (None, 0)
    shared = sorted([(t, n) for t, n in th_cnt.items() if len(n) >= 2], key=lambda x: -len(x[1]))
    return dict(rows=sorted(rows, key=lambda r: -(r['수익률(%)'] if r['수익률(%)'] is not None else -1e9)), n=len(rows),
                ev=ev, cash=cash, tot=tot, dep=dep, pnl=tot - dep if dep else None,
                pnl_pct=(tot / dep - 1) * 100 if dep else None, unreal=ev - cost,
                cash_pct=cash / tot * 100 if tot else None,
                near=[r for r in rows if r['손절 여유(%)'] is not None and r['손절 여유(%)'] < 5],
                src='토스 스냅샷' if use_t else '봇 원장', at=tz.get('at'), mismatch=mism,
                top_sector=(top_sec[0], top_sec[1] / ev * 100 if ev else None), shared=shared[:4])


def health(rows: list[tuple]):
    """실행 건강 한 줄 — (이름, 톤, 값). 봇이 돌았나·토스 동기화·원장 대조. 11-09 이중 체결·11-10 미실행을 화면에서 바로."""
    col = {'g': 'var(--pos)', 'y': '#D97706', 'r': 'var(--neg)', 'k': 'var(--ink-3)'}
    chips = ''.join(f"<span style='display:inline-flex;gap:6px;align-items:center;font-size:12px;padding:4px 10px;border:1px solid var(--line);"
                    f"border-radius:999px;background:var(--surface)'><i style='width:8px;height:8px;border-radius:50%;background:{col.get(t)}'></i>"
                    f"<b style='font-weight:650'>{_e(k)}</b> {v}</span>" for k, t, v in rows)
    st.html(CSS + f"<div class='hm' style='display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 2px'>{chips}</div>")


def account_cards(a: dict, kospi_since: float | None, since: str):
    def card(nm, big, sub, cls='z'):
        return f'<div class="hm-card"><div class="nm">{nm}</div><div class="px">{big}</div><div class="sub {cls}">{sub}</div></div>'
    c = [card('계좌 평가액', f"{a['tot']:,.0f}원", f"입금 {a['dep']:,.0f}원"),
         card('손익(입금 대비)', '-' if a['pnl'] is None else f"{a['pnl']:+,.0f}원",
              '-' if a['pnl_pct'] is None else f"{a['pnl_pct']:+.2f}%" + (f" · 코스피 {kospi_since:+.2f}%" if kospi_since is not None else ''),
              'z' if not a['pnl'] else ('p' if a['pnl'] > 0 else 'n')),
         card('보유', f"{a['n']}종", f"평가 {a['ev']:,.0f}원"),
         card('현금', f"{a['cash']:,.0f}원", '-' if a['cash_pct'] is None else f"비중 {a['cash_pct']:.1f}%"),
         card('손절선 5% 이내', f"{len(a['near'])}종", ' · '.join(r['종목'] for r in a['near'][:3]) or '없음',
              'n' if a['near'] else 'z'),
         card('업종 쏠림(최대)', '-' if a['top_sector'][1] is None else f"{a['top_sector'][1]:.0f}%",
              f"{_e(a['top_sector'][0])} · 겹치는 테마 " + (', '.join(f"{t} {len(n)}종" for t, n in a['shared'][:2]) or '없음'),
              'n' if (a['top_sector'][1] or 0) > 30 else 'z')]
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>🔐 내 실전 계좌 (토스 한국 · 소유자만)</b>
      <span>{_e(a['src'])} {_e(a.get('at') or '')} 기준 · 실시간 아님 · {since}부터 운용</span></div><div class="hm-acc">{''.join(c)}</div></div>""")


def events_box(ev: list[dict], days: int):
    """🗓️ 다가오는 일정 — 보유 종목에 걸린 것(실적 기한) · 내 규칙(오버라이드 종료·계획표) · 한국 · 미국."""
    tag = {'보유': ('#B91C1C', '#FEE2E2'), '내 규칙': ('#1D4ED8', '#DBEAFE'), '한국': ('#374151', '#F3F4F6'),
           '미국': ('#374151', '#F3F4F6')}
    rows = []
    for e in ev[:12]:
        fg, bg = tag.get(e.get('kind'), ('#374151', '#F3F4F6'))
        dd = '오늘' if e['dday'] == 0 else f"D-{e['dday']}"
        hot = e.get('hot') or e['dday'] <= 1
        rows.append(f"""<div class="hm-step" style="grid-template-columns:96px 52px 64px 1fr">
          <span class="k" style="font-variant-numeric:tabular-nums">{e['date'][5:]} ({e['wd']}){f"<br><em style='font-style:normal;font-weight:500;color:var(--ink-3);font-size:11.5px'>{_e(e['time'])} KST</em>" if e.get('time') else ''}</span>
          <span style="font-size:12px;font-weight:700;color:{'var(--neg)' if hot else 'var(--ink-2)'}">{dd}</span>
          <span><i style="font-style:normal;font-size:11px;font-weight:700;padding:2px 7px;border-radius:999px;color:{fg};background:{bg}">{_e(e.get('kind'))}</i></span>
          <span class="v"><b style="color:var(--ink)">{_e(e['name'])}</b>{f"<br>{_e(e['detail'])}" if e.get('detail') else ''}</span></div>""")
    body = ''.join(rows) or "<div class='hm-step'><span></span><span></span><span></span><span class='v'>예정된 일정 없음</span></div>"
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>🗓️ 다가오는 일정 — {days}일</b>
      <span>보유 종목 실적 기한·내 규칙 일정이 먼저 · 시각은 한국 시간</span></div><div class="hm-steps">{body}</div></div>""")


def pulse_box(idx_rows: list[dict], hist: list[dict]):
    """오닐 방식 시장 방향(참고) + 시장 폭 추이. market_report 가 매일 계산한 facts.indices[].pulse · stocks.KR.breadth_hist."""
    tone = {'상승 추세': 'p', '상승 확인': 'p', '압력 받는 상승': 'n'}
    cards = []
    for x in idx_rows:
        pz = x.get('pulse') or {}
        if not pz:
            continue
        st_ = pz.get('state', '-')
        cls = tone.get(st_, 'z' if '반등' in st_ else 'n')
        sub = [f"분배일 {pz.get('dist_n', '-')}개 (25거래일)"]
        if pz.get('ftd_date'):
            sub.append(f"팔로스루 {pz['ftd_date'][5:]}")
        if pz.get('low_date'):
            sub.append(f"저점 {pz['low_date'][5:]} ({pz.get('corr_dd', 0):+.1f}%)")
        cards.append(f"""<div class="hm-card"><div class="nm">{_e(x.get('name'))} · 오닐식 시장 방향</div>
          <div class="px {cls}" style="font-size:17px">{_e(st_)}</div><div class="sub">{' · '.join(sub)}</div></div>""")
    trend = ''
    pts = [h for h in (hist or []) if h.get('up') is not None and h.get('down') is not None]
    if len(pts) >= 2:
        bars = ''.join(
            f"<span title='{_e(h['date'])} 상승 {h['up'] / max(1, h['up'] + h['down'] + (h.get('flat') or 0)) * 100:.0f}%' "
            f"style='display:inline-block;width:10px;margin-right:2px;vertical-align:bottom;"
            f"height:{max(2, h['up'] / max(1, h['up'] + h['down'] + (h.get('flat') or 0)) * 44):.0f}px;"
            f"background:{'var(--pos)' if h['up'] >= h['down'] else 'var(--neg)'};border-radius:2px'></span>" for h in pts[-30:])
        trend = (f"<div class='hm-card'><div class='nm'>한국 상승 종목 비율 — 최근 {len(pts[-30:])}거래일</div>"
                 f"<div style='height:46px;margin-top:6px'>{bars}</div><div class='sub'>초록 = 오른 종목이 더 많은 날 · 기록 {pts[0]['date']}부터</div></div>")
    elif pts:
        trend = ("<div class='hm-card'><div class='nm'>한국 상승 종목 비율 — 추이</div><div class='sub' style='margin-top:8px'>"
                 f"기록 시작 {pts[0]['date']} — 2거래일부터 막대로 보입니다</div></div>")
    if not cards and not trend:
        return
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>시장 방향 — 오닐식 (참고)</b>
      <span>실전 규칙(5주선)과 별개 · 이 저장소에서 백테스트 안 함 · 분배일 = −0.2%↓ + 거래량 증가</span></div>
      <div class="hm-grid" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">{''.join(cards)}{trend}</div></div>""")


def movers_box(kr: dict, asof: str = ''):
    """오늘 무엇이 움직였나 — 강세 테마 · 특징주(돈이 몰린 급등) · 52주 신고가. 시황 리포트 facts 재사용(봇 시황 2장과 같은 계산)."""
    tt, tb = kr.get('themes_top') or [], kr.get('themes_bottom') or []
    ft, nh = kr.get('featured') or [], kr.get('new_high_52w') or {}
    if not (tt or ft or nh):
        return False

    def lead(t):
        return ' · '.join(f"{_e(x['name'])} {_pct(x.get('ret'), nd=1)}" for x in (t.get('lead') or [])[:3])
    th = ''.join(f"<div class='hm-row' style='display:block'><b>{_e(t['name'])}</b> {_pct(t.get('ret'), nd=1)} "
                 f"<em>{t.get('up', '-')}/{t.get('n', '-')}종 상승</em><br><span style='font-size:11.5px'>{lead(t)}</span></div>"
                 for t in tt[:3]) or "<div class='hm-kv'>-</div>"
    if tb:
        th += ("<div class='hm-kv' style='margin-top:6px'>약세: " + ', '.join(f"{_e(t['name'])} {_pct(t.get('ret'), nd=1)}" for t in tb[:3]) + "</div>")
    fr = ''.join(f"<div class='hm-row'><span>{_e(x['name'])} <em>{_e(x.get('tag'))}</em></span>{_pct(x.get('ret'), nd=1)}</div>"
                 for x in ft[:6]) or "<div class='hm-kv'>해당 없음</div>"
    nr = ''.join(f"<div class='hm-row'><span>{_e(x['name'])}{' <em>상장 1년 미만</em>' if x.get('young') else ''}</span>{_pct(x.get('ret'), nd=1)}</div>"
                 for x in (nh.get('top') or [])[:6]) or "<div class='hm-kv'>-</div>"
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>🔥 오늘 무엇이 움직였나</b>
      <span>테마 = 네이버 테마 구성 종목 단순 평균(5종+) · 특징주 = 상한가 + 거래대금 300억+·+10% · 돈이 몰린 순</span></div>
      <div class="hm-two" style="grid-template-columns:repeat(3,minmax(0,1fr))">
        <div class="hm-box"><h5>강세 테마</h5>{th}</div>
        <div class="hm-box"><h5>특징주</h5>{fr}</div>
        <div class="hm-box"><h5>52주 신고가 {nh.get('n', '-')}종 <span style='font-weight:500;color:var(--ink-3)'>/ {nh.get('universe', '-')}종</span></h5>{nr}</div>
      </div><div class="hm-src">출처: 네이버 금융 전 종목 시세·테마(market_report.py) · 마지막 갱신: {_e(asof)}</div></div>""")
    return True


def heatmap_fig(rows: list[dict]):
    """업종 히트맵(시총 1조+) — 면적 = 시총, 색 = 등락(±5% 에서 포화, 0 = 회색). 봇 이미지는 작아서 기각됐지만 웹은 확대·호버 가능."""
    import plotly.graph_objects as go
    rows = [r for r in rows or [] if r.get('mc') and r.get('ret') is not None]
    if not rows:
        return None
    secs = sorted({r['sec'] or '기타' for r in rows})
    ids = [f"s:{x}" for x in secs] + [f"{r['sec'] or '기타'}/{r['sym']}" for r in rows]
    labels = secs + [r['name'] for r in rows]
    parents = [''] * len(secs) + [f"s:{r['sec'] or '기타'}" for r in rows]
    vals = [sum(r['mc'] for r in rows if (r['sec'] or '기타') == x) for x in secs] + [r['mc'] for r in rows]
    sec_ret = []
    for x in secs:
        rr = [r for r in rows if (r['sec'] or '기타') == x]
        sec_ret.append(sum(r['ret'] * r['mc'] for r in rr) / sum(r['mc'] for r in rr))
    col = sec_ret + [r['ret'] for r in rows]
    # finviz 식: 0% = 짙은 회색, ±5% 에서 포화 — 흰 글자가 어느 칸에서나 읽힌다(밝은 회색 중앙은 흰 글자가 안 보였다)
    fig = go.Figure(go.Treemap(ids=ids, labels=labels, parents=parents, values=vals, branchvalues='total', customdata=col,
                               marker=dict(colors=col, colorscale=[[0, '#B91C1C'], [0.5, '#4B5563'], [1, '#15803D']],
                                           cmid=0, cmin=-5, cmax=5, line=dict(width=1, color='#fff')),
                               textfont=dict(color='#fff'), root_color='#fff',
                               texttemplate='%{label}<br>%{customdata:+.1f}%',
                               hovertemplate='%{label}<br>시총 %{value:,.1f}조<br>%{customdata:+.2f}%<extra></extra>',
                               tiling=dict(pad=2), pathbar=dict(visible=False)))
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0), font=dict(family='Pretendard, Malgun Gothic, sans-serif', size=12))
    return fig


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
