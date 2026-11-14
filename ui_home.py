"""🏠 종합 탭 — 결론 배너 · 시장 카드 · 시장 폭·업종 · 사용법 패널 (2026-11-10 개편).

설계 원칙(대시보드 설계의 정석 — 역피라미드 · 5초 규칙 · 점진적 공개):
  1층 결론(5초)  : 이번 주 실전 규칙(v1.9)이 신규 매수를 허락하나 + 오늘 시장 한 줄
  2층 상태(30초) : 지수·환율·금리·원자재 카드, 한국 시장 폭·업종 강약
  3층 근거(필요 시): 할 일 표 · 시황 리포트 원문 · 챗봇 (dashboard.py)
사용법은 3탭(한눈에 · 활용 루틴 · 전체 설명서) — 문구·숫자는 manual.py 단일 원천(2026-11-14).

데이터는 전부 파일에서만 읽는다(results/market_report.json · live/plan_latest.json). 여기서 외부 호출 없음.
숫자 없으면 '-' — 지어내지 않는다.
"""
from __future__ import annotations

import html
import re

import streamlit as st

# dashboard.py 가 이 값과 다르면 importlib.reload — 클라우드가 옛 모듈을 메모리에 들고 있던 사고(2026-11-12 배포 화면
# 'module ui_home has no attribute account') 재발 방지. 이 파일을 고치면 반드시 올린다.
VERSION = '2026-11-14c'

CSS = """
<style>
  .hm { font-family:'Pretendard',-apple-system,'Malgun Gothic',system-ui,sans-serif; color:var(--ink); }
  .hm, .hm * { word-break:keep-all; overflow-wrap:anywhere; }
  .hm-hero { position:relative; overflow:hidden; border-radius:16px; padding:20px 24px 18px; color:var(--ink);
             border:1px solid var(--line); border-left:6px solid var(--tone,#64748B);
             background:linear-gradient(120deg, color-mix(in srgb, var(--tone,#64748B) 9%, var(--surface)) 0%, var(--surface) 62%); }
  .hm-kick { font-size:11.5px; font-weight:700; letter-spacing:.06em; color:var(--tone,#64748B); margin-bottom:6px; }
  .hm-hero h3 { font-size:22px !important; font-weight:800 !important; letter-spacing:-.03em; margin:0 0 8px;
             color:var(--ink) !important; line-height:1.3; }
  .hm-hero .gl { display:flex; flex-wrap:wrap; gap:6px 18px; font-size:12.5px; color:var(--ink-2); margin:0 0 6px;
             font-variant-numeric:tabular-nums; }
  .hm-hero .gl b { color:var(--ink); font-weight:700; }
  .hm-hero p { font-size:14px; color:var(--ink-2); margin:6px 0 0; max-width:900px; line-height:1.65; }
  .hm-chips { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
  .hm-chip { font-size:12px; padding:4px 10px; border-radius:999px; border:1px solid var(--line); background:var(--surface);
             color:var(--ink-2); font-variant-numeric:tabular-nums; }
  .hm-chip b.p { color:var(--pos); } .hm-chip b.n { color:var(--neg); }
  .hm-sec { display:flex; align-items:baseline; justify-content:space-between; margin:18px 2px 8px; }
  .hm-sec b { font-size:15px; font-weight:750; letter-spacing:-.02em; }
  .hm-sec span { font-size:12px; color:var(--ink-3); }
  .hm-grid { display:grid; gap:8px; grid-template-columns:repeat(7,minmax(0,1fr)); }
  @media (max-width:1200px) { .hm-grid { grid-template-columns:repeat(4,minmax(0,1fr)); } }
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
  details.hm-det { border-bottom:1px dashed var(--line-2); }
  details.hm-det:last-child { border-bottom:0; }
  details.hm-det > summary { list-style:none; cursor:pointer; display:flex; justify-content:space-between; gap:8px;
            font-size:12.5px; padding:3px 0; font-variant-numeric:tabular-nums; }
  details.hm-det > summary::-webkit-details-marker { display:none; }
  details.hm-det > summary em { font-style:normal; color:var(--ink-3); font-size:11.5px; }
  details.hm-det > summary:hover { background:var(--line-2); border-radius:4px; }
  details.hm-det > summary .cv { color:var(--ink-3); font-size:10px; margin-left:4px; transition:transform .15s; display:inline-block; }
  details.hm-det[open] > summary .cv { transform:rotate(90deg); }
  .hm-mem { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:2px 12px; padding:4px 6px 8px;
            font-size:11.5px; color:var(--ink-2); font-variant-numeric:tabular-nums; background:var(--line-2); border-radius:6px; margin:2px 0 6px; }
  .hm-mem span { display:flex; justify-content:space-between; gap:6px; white-space:nowrap; overflow:hidden; }
  .hm-tile { border:1px solid var(--line); border-radius:9px; padding:8px 10px; display:flex; flex-direction:column; gap:1px;
            font-variant-numeric:tabular-nums; }
  .hm-tile .t1 { font-size:12.5px; font-weight:650; color:var(--ink); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .hm-tile .t2 { font-size:15px; font-weight:780; }
  .hm-tile .t3 { font-size:11px; color:var(--ink-3); }
  .hm-tiles { display:grid; gap:6px; grid-template-columns:repeat(5,minmax(0,1fr)); }
  @media (max-width:560px) { .hm-tiles { grid-template-columns:repeat(2,minmax(0,1fr)); } }
  .hm-trend { display:flex; align-items:flex-end; gap:2px; height:64px; position:relative; margin-top:6px; }
  .hm-trend i { flex:1; border-radius:2px 2px 0 0; min-width:3px; }
  .hm-trend .mid { position:absolute; left:0; right:0; bottom:32px; border-top:1px dashed var(--ink-3); opacity:.45; }
  .hm-legend { display:flex; flex-wrap:wrap; gap:4px; align-items:center; font-size:11.5px; color:var(--ink-3); margin:2px 2px 8px; }
  .hm-legend b { font-weight:650; color:var(--ink-2); padding:1px 7px; border-radius:999px; background:var(--line-2); }
  .hm a.hm-a { color:inherit; text-decoration:none; border-bottom:1px dotted var(--ink-3); cursor:pointer; }
  .hm a.hm-a:hover { color:var(--accent); border-bottom-color:var(--accent); }
  @media (max-width:980px) { .hm-two[style*="repeat(4"] { grid-template-columns:repeat(2,minmax(0,1fr)) !important; } }
  .hm-why { margin:0 0 12px !important; padding:0 !important; list-style:none; display:grid; gap:6px; }
  .hm-why li { font-size:13.5px; line-height:1.6; color:var(--ink-2); padding:8px 12px; background:var(--line-2); border-radius:8px; }
  .hm-why li b { color:var(--ink); margin-right:6px; }
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
_NEUTRAL = {'VIX', '원/달러', '미국 10년물(%)', '달러인덱스', 'WTI 유가', '하이일드 스프레드'}
# 2026-11-14 차니 순서: 윗줄 = 주가·위험자산(미국 → 한국 → 반도체 → 비트코인), 아랫줄 = 변동성·환율·금리·달러·원자재·신용
_CARD_ORDER = ['S&P500', '나스닥', '다우', '코스피', '코스닥', '필라델피아 반도체', '비트코인',
               'VIX', '원/달러', '미국 10년물(%)', '달러인덱스', '금', 'WTI 유가', '하이일드 스프레드']


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
        for x in (f.get('indices') or []) + ((f.get('us') or {}).get('assets') or []) + ([f['hy']] if f.get('hy') else []):
            n = x.get('name')
            if n and (n not in by or str(x.get('date') or '') >= str(by[n].get('date') or '')):
                by[n] = x
    return [by[n] for n in _CARD_ORDER if n in by]


# ── 그리기 ──────────────────────────────────────────────────────────────
_TONE = {'g': '#16A34A', 'r': '#DC2626', 'y': '#D97706', 'k': '#64748B'}


def hero(g: dict, line: str, line_date: str, chips: list[str], live: str = ''):
    """이번 주 시장 신호 — 밝은 카드(2026-11-14: 검은 배경이 무겁다는 지적). 운영 정보(오버라이드·데이터 점검)는 경영실로."""
    wk = next((r.get('date') for r in g['rows'] if r.get('date')), None)
    gl = ''.join(f"<span>{_e(r['lab'])} <b>{_num(r['last'])}</b> · 5주선 {_num(r['ma'])} "
                 f"<span class='{'p' if r['rule_ok'] else 'n'}'>({'위' if r['rule_ok'] else '아래'})</span></span>" for r in g['rows'])
    body = (f"<p><b style='color:var(--ink)'>오늘 시장</b> — {_e(line)} <span style='color:var(--ink-3);font-size:12px'>(AI 요약 · {_e(line_date)})</span></p>"
            if line else "<p>오늘 시황 요약 준비 중 — 평일 15:50(KST) 한국 장 마감 후 갱신.</p>")
    st.html(CSS + f"""<div class="hm"><div class="hm-hero" style="--tone:{_TONE.get(g['tone'], '#64748B')}">
      <div class="hm-kick">이번 주 시장 신호 · 한국 주봉 5주선{f' · {_e(wk)} 주봉 기준' if wk else ''}</div>
      <h3>{_e(g['head'])}</h3>
      <div class="gl">{gl}</div>
      {f'<div class="gl">{live}</div>' if live else ''}
      {body}
      <div class="hm-chips">{''.join(f'<span class="hm-chip">{c}</span>' for c in chips)}</div>
    </div></div>""")


def _bp(v) -> str:
    return '<span class="z">-</span>' if v is None else f'<span class="z">{v:+.0f}bp</span>'


def market_cards(rows: list[dict], asof: str = ''):
    """글로벌 마켓 — 7 × 2. 모든 카드 같은 4줄(종가·1일·5일/1개월·52주 고점/200일선). 없는 값은 '-'(지어내지 않음)."""
    cards = []
    for x in rows:
        nm = x.get('name')
        neu = nm in _NEUTRAL
        bp = x.get('unit') == 'bp'
        f = (lambda k: _bp(x.get(k))) if bp else (lambda k: _pct(x.get(k), neutral=neu, nd=1))
        ab = x.get('above_200d')
        sub = f"5일 {f('d5')} · 1개월 {f('m1')}"
        if bp:
            t1 = f"1년 저점 {x['from_52w_low']:+.0f}bp" if x.get('from_52w_low') is not None else '1년 저점 -'
        else:
            t1 = f"고점 {x['from_52w_high']:+.1f}%" if x.get('from_52w_high') is not None else '고점 -'
        if ab is None:
            t2 = '200일선 -'
        else:
            dot = 'var(--ink-3)' if (neu or bp) else ('var(--pos)' if ab else 'var(--neg)')
            t2 = f"<span style='color:{dot}'>●</span> 200일선 {'위' if ab else '아래'}"
        px = f"{x['close']:.2f}%" if bp and x.get('close') is not None else _num(x.get('close'))
        d1 = _bp(x.get('d1')) if bp else _pct(x.get('d1'), neutral=neu)
        cards.append(f"""<div class="hm-card"><div class="nm">{_e(nm)}</div>
          <div class="px">{px}</div><div class="d1">{d1}</div>
          <div class="sub">{sub}<br>{t1} · {t2}</div></div>""")
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>글로벌 마켓</b>
      <span>종가 · 1일 등락 · 고점 = 52주 고점 대비 · VIX·환율·금리·달러·유가·스프레드는 오르면 위험이라 색 없음 · bp = 0.01%p</span></div>
      <div class="hm-grid">{''.join(cards) or '<div class="hm-src">지수 데이터 없음</div>'}</div>
      <div class="hm-src">출처: Yahoo Finance · FRED(하이일드 스프레드 = ICE BofA US High Yield OAS) · market_report.py · 마지막 갱신: {_e(asof)}</div></div>""")


LINK_BASE = ''      # dashboard 가 넣는다 — 종목 이름 링크(새 창 → 종목 분석)의 앱 주소. 2026-11-14


def _a(name, sym=None) -> str:
    """종목 이름 → 새 창으로 종목 분석(?sym=). 코드가 없으면 글자만."""
    if not sym:
        return _e(name)
    return f"<a class='hm-a' href='{LINK_BASE}?sym={_e(sym)}' target='_blank' rel='noopener' title='새 창에서 종목 분석'>{_e(name)}</a>"


def _lead2(s: dict) -> str:
    mem = s.get('members') or []
    names = [m['name'] for m in mem[:2]] if mem else [s.get('lead')]
    return '·'.join(_e(n) for n in names if n)


def _sec_rows(ss: list[dict]) -> str:
    """업종 줄 — 누르면 구성 종목(시총 순)이 펼쳐진다(<details>, 서버 왕복 없음). 구성 종목이 없는 옛 자료는 펼침 없이."""
    out = []
    for s in ss:
        head = (f"<span>{_e(s['name'])} <em>{s.get('n', '')}종 · {_lead2(s)}</em>"
                f"{'<i class=cv>▶</i>' if s.get('members') else ''}</span>{_pct(s['ret'], nd=1)}")
        mem = s.get('members') or []
        if mem:
            body = ''.join(f"<span>{_a(m['name'], m.get('sym'))}{_pct(m.get('ret'), nd=1)}</span>" for m in mem[:20])
            more = f"<span style='color:var(--ink-3)'>외 {s['n'] - 20}종</span>" if (s.get('n') or 0) > 20 else ''
            out.append(f"<details class='hm-det'><summary>{head}</summary><div class='hm-mem'>{body}{more}</div></details>")
        else:
            out.append(f"<div class='hm-row'>{head}</div>")
    return ''.join(out) or "<div class='hm-kv'>-</div>"


def _breadth_box(m: dict, rich_kr: bool) -> str:
    b = m.get('breadth_all') or {}
    up, dn, fl = b.get('up') or 0, b.get('down') or 0, b.get('flat') or 0
    tot = up + dn + fl
    if not tot:
        return "<div class='hm-box'><h5>시장 폭</h5><div class='hm-kv'>등락 종목 수 없음</div></div>"
    bar = (f'<div class="hm-bar"><span style="width:{up / tot * 100:.1f}%;background:var(--pos)"></span>'
           f'<span style="width:{fl / tot * 100:.1f}%;background:#CBD5E1"></span>'
           f'<span style="width:{dn / tot * 100:.1f}%;background:var(--neg)"></span></div>')
    kv = [f"상승 <b class='p'>{up:,}</b> · 보합 {fl:,} · 하락 <b class='n'>{dn:,}</b> — 상승 비율 {up / tot * 100:.0f}%"]
    if rich_kr:
        kv.append(f"상한가 {b.get('limit_up', '-')} · 하한가 {b.get('limit_down', '-')}")
        kv.append(' · '.join(f"{k} 거래대금 {v:,.1f}조" for k, v in (m.get('turnover_tn') or {}).items()) or '거래대금 -')
        kv.append(f"대형주(시총 1조+) {m.get('universe', '-')}종 중 상승 {m.get('breadth_up', '-')}%")
        lab = '시장 폭 — 코스피+코스닥 전 종목'
    else:
        tt = m.get('turnover_txt') or (f"${m['turnover_bn']:,.0f}B" if m.get('turnover_bn') else None)
        kv.append(f"거래대금 합계 {tt}" if tt else '거래대금 -')
        if m.get('big_n'):
            kv.append(f"대형주 {m['big_n']:,}종 중 상승 {m.get('breadth_up', '-')}%")
        lab = f"시장 폭 — {m.get('basis_label') or ''}{tot:,}종"
    return f"<div class='hm-box'><h5>{lab}</h5>{bar}<div class='hm-kv'>{'<br>'.join(kv)}</div></div>"


def _rank_box(title: str, rows: list[dict], tag_key: str | None = None, note: str = '') -> str:
    li = ''.join(f"<div class='hm-row'><span>{_a(x['name'], x.get('sym'))}"
                 f"{f' <em>{_e(x.get(tag_key))}</em>' if tag_key and x.get(tag_key) else ''}"
                 f"{' <em>상장 1년 미만</em>' if x.get('young') else ''}</span>{_pct(x.get('ret'), nd=1)}</div>" for x in rows)
    return f"<div class='hm-box'><h5>{title}</h5>{li or '<div class=hm-kv>해당 없음</div>'}{note}</div>"


_SUB = "<span style='font-weight:500;color:var(--ink-3);font-size:11.5px'>{}</span>"
PERIOD_LABEL = {'d1': '1일', 'w1': '최근 5거래일', 'm1': '최근 21거래일'}


def market_today(m: dict, kr: bool, asof: str, flow: dict | None = None, period: str = 'd1'):
    """시장 내부(한국·미국 × 일간·주간·월간 같은 모양). 종목 이름 = 새 창 종목 분석 링크.
    한국 일간만 네이버 원천이라 칸이 다르다(수급·테마·특징주). 나머지는 일봉에서 계산한 공통 모양:
    1줄: 시장 폭 · 거래대금 상위 · 강한 업종 · 약한 업종 / 2줄: 급등(돈 몰린 순) · 52주 신고가 · 대형주 상승 상위 · 하락 상위 / 3줄: 시총 상위 10."""
    rich = kr and period == 'd1'
    sec = sorted([s for s in (m.get('sectors') or []) if s.get('ret') is not None], key=lambda s: -s['ret'])
    if rich:
        mid = flow_box(flow or {})
    else:
        mid = _rank_box('돈이 몰린 종목 ' + _SUB.format('(거래대금 상위)'),
                        [dict(x, tag=x.get('tag') or (f"${x['amt_b']:,.1f}B" if x.get('amt_b') is not None else None))
                         for x in (m.get('turnover_top') or [])[:6]], 'tag')
    row1 = (_breadth_box(m, rich) + mid +
            f"<div class='hm-box'><h5>강한 업종 {_SUB.format('(시총가중 · 누르면 구성 종목)')}</h5>{_sec_rows(sec[:5])}</div>"
            f"<div class='hm-box'><h5>약한 업종 {_SUB.format('(시총가중)')}</h5>{_sec_rows(sorted(sec[-5:], key=lambda s: s['ret']))}</div>")
    nh = m.get('new_high_52w') or {}
    nh_box = _rank_box(f"52주 신고가 {nh.get('n', '-')}종 <span style='font-weight:500;color:var(--ink-3)'>/ {nh.get('universe', '-'):,}종</span>"
                       if isinstance(nh.get('universe'), int) else f"52주 신고가 {nh.get('n', '-')}종", (nh.get('top') or [])[:6])
    if rich:
        tt, tb = m.get('themes_top') or [], m.get('themes_bottom') or []

        def lead(t):
            return ' · '.join(f"{_a(x['name'], x.get('sym'))} {_pct(x.get('ret'), nd=1)}" for x in (t.get('lead') or [])[:3])
        th = ''.join(f"<div class='hm-row' style='display:block'><b>{_e(t['name'])}</b> {_pct(t.get('ret'), nd=1)} "
                     f"<em>{t.get('up', '-')}/{t.get('n', '-')}종 상승</em><br><span style='font-size:11.5px'>{lead(t)}</span></div>"
                     for t in tt[:3]) or "<div class='hm-kv'>-</div>"
        if tb:
            th += "<div class='hm-kv' style='margin-top:6px'>약세: " + ', '.join(f"{_e(t['name'])} {_pct(t.get('ret'), nd=1)}" for t in tb[:3]) + "</div>"
        row2 = (f"<div class='hm-box'><h5>강세 테마</h5>{th}</div>" + nh_box
                + _rank_box('특징주 ' + _SUB.format('(상한가 · 거래대금 300억+ 급등)'), (m.get('featured') or [])[:6], 'tag'))
        cols2 = 3
    else:
        th_ = {'d1': 7, 'w1': 14, 'm1': 28}.get(period, 7)
        row2 = (_rank_box('급등주 ' + _SUB.format(f'(+{th_}% 이상 · 돈이 몰린 순)'), (m.get('featured') or [])[:6], 'tag') + nh_box
                + _rank_box('대형주 상승 상위', (m.get('top') or [])[:6]) + _rank_box('대형주 하락 상위', (m.get('bottom') or [])[:6]))
        cols2 = 4
    # 시총 상위 10 — 등락 크기만큼 칸을 칠한다(일간 ±4% · 주간 ±8% · 월간 ±16% 에서 포화)
    sat = {'d1': 4, 'w1': 8, 'm1': 16}.get(period, 4)
    mc_of = {h.get('sym'): h.get('mc') for h in (m.get('heatmap') or [])}
    tiles = []
    for x in (m.get('megacaps') or [])[:10]:
        r = x.get('ret')
        a = min(abs(r or 0) / sat, 1) * 0.22
        bg = (f"color-mix(in srgb, var({'--pos' if (r or 0) > 0 else '--neg'}) {a * 100:.0f}%, var(--surface))" if r else 'var(--surface)')
        mc = x.get('mc') if x.get('mc') is not None else mc_of.get(x.get('sym'))
        mct = ('-' if mc is None else (f"시총 {mc:,.0f}조" if kr else f"시총 ${mc:,.0f}B"))
        tiles.append(f"<div class='hm-tile' style='background:{bg}'><span class='t1'>{_a(x.get('name'), x.get('sym'))}</span>"
                     f"<span class='t2'>{_pct(r, nd=1)}</span><span class='t3'>{mct}</span></div>")
    if rich:
        src = '네이버 금융 전 종목 시세·업종·테마·투자자별 매매(market_report.py · tools/kr_flow.py)'
    else:
        src = (f"Yahoo Finance 일봉 · {'시총 1,000억+ · 업종 = KSIC' if kr else '시총 $3억+ 전 종목(NYSE·나스닥) · 업종 = Yahoo industry'}"
               f"(3종+ 묶음) · 대형주 = {'시총 1조+' if kr else '시총 상위 500'} · market_internals.py"
               + (f" · 기간 {m.get('since')} 종가 → {m.get('asof')} 종가" if period != 'd1' and m.get('since') else ''))
    st.html(CSS + f"""<div class="hm">
      <div class="hm-four">{row1}</div>
      <div class="hm-two" style="grid-template-columns:repeat({cols2},minmax(0,1fr));margin-top:10px">{row2}</div>
      <div class="hm-sec" style="margin-top:12px"><b style="font-size:13px">시총 상위 10</b><span>지수를 움직이는 종목 · 색이 진할수록 등락이 큼 · 종목 이름을 누르면 새 창에서 종목 분석</span></div>
      <div class="hm-tiles">{''.join(tiles) or '<span>-</span>'}</div>
      <div class="hm-src">출처: {src} · 마지막 갱신: {_e(asof)}</div></div>""")


def sector_table(m: dict) -> list[dict]:
    """업종 전체 표(누락 없이) — 업종·종목 수·등락·대표 종목 2개."""
    return [{'업종': s['name'], '종목 수': s.get('n'), '등락(%)': s.get('ret'),
             '대표 종목': ', '.join(x['name'] for x in (s.get('members') or [])[:3]) or s.get('lead')}
            for s in sorted([s for s in (m.get('sectors') or []) if s.get('ret') is not None], key=lambda s: -s['ret'])]


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
    return (f"<div class='hm-box'><h5>수급 — 투자자별 매매 <span style='font-weight:500;color:var(--ink-3);font-size:11.5px'>"
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
        # 고점은 **원장값(보유 중 최고 종가)** 그대로 쓴다. 2026-11-13: 여기서 현재가와 max 를 씌우는 바람에
        # 장중 신고가 종목은 고점만 올라가고 손절가(원장)는 그대로라 '손절 여유'가 규칙(-20%)과 어긋나 보였다.
        peak, stop = p.get('peak'), p.get('stop')
        mval = (px or avg or 0) * sh                       # 평가액
        pnl = (px - avg) * sh if (px is not None and avg is not None) else None
        sd = (sectors or {}).get(code) or {}
        rows.append(dict(종목=p.get('name') or h.get('name'), 코드=code, 업종=sd.get('upjong'), **{
            '수량(주)': sh, '평단(원)': avg, '현재가(원)': px, '평가액(원)': mval, '평가손익(원)': pnl,
            '수익률(%)': (px / avg - 1) * 100 if px and avg else None,
            '보유 고점(원)': peak, '손절가(원)': stop,
            # 손절 여유 = **지금 가격에서 손절가까지 남은 하락폭.** 고점에 있을 때 정확히 20.0 이 된다.
            # (옛 식 px/stop-1 은 분모가 손절가라 같은 상태에서 25% 로 나왔다 — 2026-11-13 정정)
            '손절 여유(%)': (1 - stop / px) * 100 if px and stop else None,
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
         card('보유', f"{a['n']}종", f"평가 {a['ev']:,.0f}원 · 평가손익 {a['unreal']:+,.0f}원",
              'z' if not a['unreal'] else ('p' if a['unreal'] > 0 else 'n')),
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
    tag = {'보유': ('#B91C1C', '#FEE2E2'), '실전 규칙': ('#1D4ED8', '#DBEAFE'), '내 규칙': ('#1D4ED8', '#DBEAFE'), '한국': ('#374151', '#F3F4F6'),
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
      <span>날짜순 · 시각은 한국 시간</span></div><div class="hm-steps">{body}</div></div>""")


_PULSE_HELP = """<details style="margin:0 2px 8px"><summary style="cursor:pointer;font-size:12px;color:var(--accent);font-weight:650">
  오닐 방식이란? — 지수에 남은 '큰손의 매도 흔적'으로 시장 방향을 읽는 법</summary>
  <div class="hm-kv" style="padding:6px 2px 2px;max-width:980px">
  윌리엄 오닐(IBD 창업자, CAN SLIM 저자)은 개별 종목보다 <b>시장 방향</b>을 먼저 본다. 판단 재료는 지수의 가격과 거래량 두 가지.<br>
  ① <b>분배일</b> — 지수가 0.2% 이상 떨어졌는데 거래량은 전날보다 많은 날(기관이 판 흔적). 최근 25거래일 안에 5개 이상 쌓이면 상승세가 <b>압력</b>을 받는다.<br>
  ② <b>조정 → 반등 시도</b> — 고점 대비 7% 이상 밀린 뒤, 저점 다음 날부터 '반등 시도 n일째'를 센다. 저점을 다시 깨면 처음부터.<br>
  ③ <b>팔로스루 데이</b> — 반등 4일째 이후 지수가 1.25% 이상 오르고 거래량이 늘면 <b>상승 확인</b>. 오닐은 이때부터 신규 매수를 시작한다.<br>
  <span style="color:var(--ink-3)">이 사이트의 신규 매수 신호(주봉 5주선)와는 별개인 참고 지표 — 이 사이트에서 백테스트하지 않음.</span></div></details>"""
_PULSE_LEGEND = ("<div class='hm-legend'>단계: <b>조정 중</b>→<b>반등 시도 n일째</b>→<b>상승 확인</b>→<b>상승 추세</b>"
                 " · 상승 중 분배일 5개+ = <b>압력 받는 상승</b></div>")


def _trend_card(label: str, pts: list[tuple], basis: str) -> str:
    """상승 비율 막대 — 가로 폭을 꽉 채운다(2026-11-14: 막대 2개가 왼쪽에 몰려 빈칸이 컸다). 50% 점선 = 반반."""
    if not pts:
        return f"<div class='hm-card'><div class='nm'>{_e(label)}</div><div class='sub' style='margin-top:8px'>자료 준비 중 — 다음 시황 갱신부터 표시</div></div>"
    # 칸은 언제나 30개 — 기록이 짧으면 앞을 빈 칸으로(막대 2개가 폭을 다 차지해 '꽉 찬 자료'처럼 보이지 않게)
    pad = ''.join("<i style='height:2px;background:var(--line)'></i>" for _ in range(max(0, 30 - len(pts))))
    bars = pad + ''.join(f"<i title='{_e(d)} 상승 {p:.0f}%' style='height:{max(2, p / 100 * 64):.0f}px;"
                         f"background:{'var(--pos)' if p >= 50 else 'var(--neg)'};opacity:{0.55 + 0.45 * (i == len(pts) - 1):.2f}'></i>"
                         for i, (d, p) in enumerate(pts))
    last = pts[-1][1]
    avg = sum(p for _, p in pts) / len(pts)
    upd = sum(p >= 50 for _, p in pts)
    return (f"<div class='hm-card'><div class='nm'>{_e(label)}<span style='font-weight:500'>{_e(basis)}</span></div>"
            f"<div style='display:flex;gap:14px;align-items:baseline;margin-top:2px'><span class='px {'p' if last >= 50 else 'n'}'>{last:.0f}%</span>"
            f"<span class='sub'>최근 {len(pts)}거래일 평균 {avg:.0f}% · 오른 종목이 많은 날 {upd}일</span></div>"
            f"<div class='hm-trend'><div class='mid'></div>{bars}</div>"
            f"<div class='sub'>{_e(pts[0][0][5:])} → {_e(pts[-1][0][5:])} · 점선 = 50% · 초록 = 오른 종목이 더 많은 날</div></div>")


def pulse_box(idx_rows: list[dict], trends: list[tuple]):
    """시장 추세 판정(오닐 방식, 참고) — 한·미 지수 카드 + 대형주 상승 비율 30거래일(한·미)."""
    tone = {'상승 추세': 'p', '상승 확인': 'p', '압력 받는 상승': 'n'}
    cards = []
    for x in idx_rows:
        pz = x.get('pulse') or {}
        if not pz:
            continue
        st_ = pz.get('state', '-')
        cls = tone.get(st_, 'z' if '반등' in st_ else 'n')
        sub = [f"분배일 {pz.get('dist_n', '-')}개(25거래일)"]
        if pz.get('ftd_date'):
            sub.append(f"팔로스루 {pz['ftd_date'][5:]}")
        if pz.get('low_date'):
            sub.append(f"저점 {pz['low_date'][5:]} ({pz.get('corr_dd', 0):+.1f}%)")
        cards.append(f"""<div class="hm-card"><div class="nm">{_e(x.get('name'))}</div>
          <div class="px {cls}" style="font-size:17px">{_e(st_)}</div><div class="sub">{' · '.join(sub)}</div></div>""")
    tr = ''.join(_trend_card(*t) for t in trends)
    if not cards and not tr:
        return
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>시장 추세 판정 — 오닐 방식 (참고)</b>
      <span>지수의 가격·거래량으로 본 상승·조정 단계 · 매수 신호(주봉 5주선)와 별개</span></div>{_PULSE_HELP}{_PULSE_LEGEND}
      <div class="hm-grid" style="grid-template-columns:repeat(auto-fit,minmax(200px,1fr))">{''.join(cards)}</div>
      <div class="hm-two" style="margin-top:8px">{tr}</div></div>""")


def trend_points(hist: list[dict]) -> list[tuple]:
    """[{date,up,down,flat}] → [(date, 상승 비율 %)]"""
    out = []
    for h in hist or []:
        t = (h.get('up') or 0) + (h.get('down') or 0) + (h.get('flat') or 0)
        if t and h.get('up') is not None:
            out.append((str(h['date']), h['up'] / t * 100))
    return out


def macro_cards(V: dict):
    """매크로 국면 요약(2026-11-14 옛 '참고 — 미국 코어 스위치·옛 목표 비중' 접이식 대체). 매매 신호 아님 — 근거는 🌍 매크로."""
    c, ph, g, fl, ec = (V.get(k) or {} for k in ('core', 'phase', 'greed', 'flow', 'econ'))

    def card(nm, big, sub, cls='z'):
        return f'<div class="hm-card"><div class="nm">{nm}</div><div class="px {cls}" style="font-size:17px">{big}</div><div class="sub">{sub}</div></div>'
    cs = [card('경기 사이클 국면', f"{_e(ph.get('emoji', ''))} {_e(ph.get('name') or '-')}",
               f"과열 경고 {g.get('n', '-')}/3 — 우라가미 4계절 기준" if g else '우라가미 4계절 기준'),
          card('돈의 흐름', _e(fl.get('word') or '-'), '유동성·신용 스프레드·달러 종합'),
          card('경기', _e(ec.get('word') or '-'), '선행·동행 지표 종합'),
          card('미국 장기 추세', '-' if not c else ('200일선 위' if c.get('on') else '200일선 아래'),
               '-' if not c else f"S&P500 200일선 대비 {c.get('gap', 0):+.1f}%",
               'z' if not c else ('p' if c.get('on') else 'n'))]
    st.html(CSS + f"""<div class="hm"><div class="hm-sec"><b>매크로 국면</b>
      <span>경기·유동성의 큰 그림 · 매매 신호 아님 · 근거는 🌍 매크로 탭</span></div>
      <div class="hm-grid" style="grid-template-columns:repeat(4,minmax(0,1fr))">{''.join(cs)}</div></div>""")


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


def today_box(me: list[tuple], bot: list[str], asof: str):
    """오늘 — '내가 할 일'(대부분 없음이어야 정상) + '봇이 한 일'. 1억 손실의 원인은 규율 → 화면이 '손대지 마라'를 먼저 말한다."""
    col = {'g': 'var(--pos)', 'y': '#D97706', 'r': 'var(--neg)'}
    mine = ''.join(f"<div style='display:flex;gap:8px;align-items:baseline;font-size:13.5px;margin:3px 0'>"
                   f"<i style='width:9px;height:9px;border-radius:50%;background:{col.get(t, '#9CA3AF')};flex:none;transform:translateY(1px)'></i>"
                   f"<span>{v}</span></div>" for t, v in me)
    done = ''.join(f"<div class='hm-row'><span>{_e(b)}</span></div>" for b in bot[:6]) or "<div class='hm-kv'>오늘 매매 없음</div>"
    st.html(CSS + f"""<div class="hm"><div class="hm-two" style="grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);margin-top:10px">
      <div class="hm-box" style="border-left:4px solid var(--accent)"><h5>🙋 오늘 내가 할 일</h5>{mine}</div>
      <div class="hm-box"><h5>🤖 오늘 봇이 한 일 <span style='font-weight:500;color:var(--ink-3)'>({_e(asof)})</span></h5>{done}</div>
    </div></div>""")


def last_session(now) -> str:
    """지금(KST) 기준 '이미 끝난' 마지막 한국 거래일(주말만 보정, 휴장일 미보정). 15:30 전이면 전 거래일."""
    import datetime as _dt
    d = now.date() if hasattr(now, 'date') else now
    if not (now.weekday() < 5 and (now.hour, now.minute) >= (15, 30)):
        d -= _dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return str(d)


def date_items(now, kr: str, us: str, plan: str, bot: str | None = None) -> list[tuple]:
    """홈 '기준 시각' 한 줄(2026-11-12) — 상자마다 흩어진 날짜를 한 곳에. (라벨, 값, 낡음 여부).
    낡음 = 한국 종가가 마지막 장보다 앞 / 계획표가 8일+ / 봇이 평일 09:20 이후인데 오늘 안 돎."""
    import datetime as _dt
    ls = last_session(now)
    today = str(now.date())
    kr10, pl10, bt10 = str(kr or '')[:10], str(plan or '')[:10], str(bot or '')[:10]
    try:
        pl_old = (now.date() - _dt.date.fromisoformat(pl10)).days > 8
    except Exception:
        pl_old = True
    bot_due = now.weekday() < 5 and (now.hour, now.minute) >= (9, 20)
    return [('한국 종가', kr10 or '-', not kr10 or kr10 < ls),
            ('미국 종가', str(us or '-')[:10], False),
            ('주간 판정', pl10 or '-', pl_old)] + \
           ([('봇 실행', str(bot)[:16], bool(bot_due and bt10 != today))] if bot is not None else []) + \
           [('지금', now.strftime('%m-%d %H:%M KST'), False)]


def dates_strip(items: list[tuple]):
    bits = ''.join(f"<span style='margin-right:14px;white-space:nowrap'>{_e(k)} <b style='color:{'#D97706' if old else 'var(--ink-1)'}'>"
                   f"{_e(v)}{' ⚠' if old else ''}</b></span>" for k, v, old in items)
    st.html(CSS + f"<div class='hm'><div style='font-size:12.5px;color:var(--ink-3);padding:6px 2px 2px;"
                  f"font-variant-numeric:tabular-nums'>📅 {bits}<span style='color:var(--ink-3)'>· ⚠ = 늦음(주말만 보정·휴장일 미보정)</span></div></div>")


def rule_checkpoints(idx_rows: list[dict], kr: dict, flow_sum: dict | None, events: list[dict] | None) -> list[str]:
    """이번에 볼 것 — 숫자 조건(2026-11-12). 계산은 market_report.rule_checks 한 곳 — 봇 '확인할 것'과 같은 문장."""
    import re
    import importlib
    import market_report as _mr
    if not hasattr(_mr, 'rule_checks'):          # 배포 서버가 옛 모듈을 메모리에 들고 있는 일이 있었다(11-12 ui_home)
        _mr = importlib.reload(_mr)
    return [re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', _e(r)) for r in _mr.rule_checks(idx_rows, kr, flow_sum, events)]


def checkpoints_box(rows: list[str], asof: str):
    if not rows:
        return
    li = ''.join(f"<div class='hm-row' style='display:block;padding:5px 0'>{r}</div>" for r in rows)
    st.html(CSS + f"""<div class="hm"><div class="hm-box"><h5>🎯 이번에 볼 것 — 숫자 조건 <span style='font-weight:500;color:var(--ink-3)'>({_e(asof)} 기준)</span></h5>{li}
      <div class="hm-src">출처: 시황 리포트 facts(지수 주봉 5주선·시장 폭) · tools/kr_flow.py · events.py — 규칙 계산, AI 아님 · 마지막 갱신: {_e(asof)}</div></div></div>""")


def report_card(date: str, kind: str, summary: str, why: list[str], checks: list[str], rules: list[str], engine: str):
    """시황 리포트(2026-11-14 2차) — 결론(한 줄) → 해설(지수·수급·업종·종목) → 다음에 볼 것. 숫자 표는 위 카드가 이미 보여 주므로 싣지 않는다."""
    import re as _re

    def _b(x):          # **굵게** 만 허용
        return _re.sub(r'\*\*(.+?)\*\*:?', r'<b>\1</b>', _e(x))
    wy = ''.join(f"<li>{_b(w)}</li>" for w in why[:5])
    ck = ''.join(f"<li>{_e(c)}</li>" for c in checks[:4])
    ru = ''.join(f"<div class='hm-row' style='display:block;padding:4px 0'>{r}</div>" for r in rules)
    st.html(CSS + f"""<div class="hm"><div class="hm-box" style="padding:18px 20px">
      <div style="font-size:11.5px;font-weight:700;letter-spacing:.06em;color:var(--ink-3)">{_e(date)} · {_e(kind)}</div>
      <div style="font-size:17px;font-weight:750;line-height:1.55;margin:6px 0 12px;color:var(--ink);letter-spacing:-.01em;max-width:980px">{_e(summary) or '요약 없음'}</div>
      {f'<ul class="hm-why">{wy}</ul>' if wy else ''}
      <div class="hm-two" style="grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px">
        <div><h5>다음 거래일에 볼 것</h5><ol style="margin:0;padding-left:18px;font-size:12.5px;color:var(--ink-2);line-height:1.7">{ck or '<li>-</li>'}</ol></div>
        {f'<div><h5>숫자 조건 — 규칙 계산</h5>{ru}</div>' if ru else ''}
      </div>
      <div class="hm-src">작성: {_e(engine)} · 문장은 이 사이트 숫자만 근거(뉴스·전망 없음) · 숫자 조건 = 지수 5주선·시장 폭·수급·일정(규칙 계산) · 투자 권유 아님</div></div></div>""")


# ── 사용법 패널 (2026-11-14 재편: 한눈에 · 활용 루틴 · 전체 설명서) ─────────────────
# 문구·규칙 값·갱신 시각은 전부 manual.py 한 곳에서 온다(화면과 PDF 가 같은 원천). 여기는 그리기만.
import manual as MN

_MN_VER = '2026-11-14a'                     # manual.VERSION 과 같아야 함(tests/test_manual) — 클라우드 옛 모듈 재적재
if getattr(MN, 'VERSION', None) != _MN_VER:
    import importlib as _il
    MN = _il.reload(MN)


def tour_head():
    st.html(CSS + MN.CSS + """<div class="mn"><div class="mn-lead" style="font-size:13.5px;margin-bottom:4px">
      <b style="color:var(--ink)">시장 → 종목 → 내 계좌, 위에서 아래로 좁혀 갑니다.</b>
      공식 공시(DART · SEC EDGAR)와 시장 가격을 매일 모아 <b>지금 들어가도 되나 · 뭘 살까 · 얼마에 자를까</b>를 숫자로 답합니다.
      같은 규칙(실전 v1.9 — 한국)으로 운영자의 자동매매 봇이 실제 계좌를 굴립니다.</div>
      <div class="mn-src" style="margin:0 2px 2px">""" + MN._legend() + """</div></div>""")


def tour_card(i: int, tab: str, q: str, d: str, feats: list, on: bool):
    """탭 하나 = 카드 하나: 질문 → 탭 이름 → 한 줄 → 기능 전부(등급). 버튼은 dashboard 가 카드 아래에 단다."""
    li = ''.join(f"<li>{_e(f.split(' — ')[0])}{MN._tag(g)}</li>" for f, g in feats)
    st.html(CSS + MN.CSS + f"""<div class="mn"><div class="mn-card mn-tour" style="height:100%;{
        'border-color:var(--accent);box-shadow:0 0 0 3px var(--accent-2)' if on else ''}">
      <div class="k">{i} · {_e(tab)}</div><div class="t">{_e(q)}</div><div class="q">{_e(d)}</div><ul>{li}</ul></div></div>""")


def tour_foot():
    pr = ''.join(f'<div class="mn-card {c}"><div class="t">{_e(t)}</div><p>{_e(d)}</p></div>' for c, t, d in MN.PRINCIPLES)
    st.html(CSS + MN.CSS + f"""<div class="mn"><div class="mn-grid">{pr}</div>
      <div class="mn-src">📲 매일 아침 요약은 텔레그램 <a href="{MN.BOT}" target="_blank" style="color:var(--accent);font-weight:650;text-decoration:none">@buza_alarm_bot</a>
      · 규칙의 이유·데이터 출처·한계는 '📚 전체 설명서'에 있습니다.</div></div>""")


def routines_panel():
    st.html(CSS + MN.CSS + f"""<div class="mn"><div class="mn-lead">도구보다 순서가 먼저입니다 — 판정 → 후보 → 검증 → 손절가.</div>
      {MN.sec_routines()}</div>""")


def manual_panel():
    """전체 설명서 — 절별 하위 탭 + PDF. 활용 루틴은 옆 탭에 있어 여기서는 뺀다(PDF 에는 들어간다)."""
    import os
    secs = [x for x in MN.SECTIONS if x[0] != 'routines']
    c1, c2 = st.columns([5, 1.4], vertical_alignment='center')
    c1.caption(f"최근 개선 {MN.updated()} · 규칙 값·백테스트 숫자·갱신 시각은 원천에서 자동으로 읽습니다 — 화면이 바뀌면 설명서도 같이 바뀝니다.")
    pdf = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'manual.pdf')
    if os.path.exists(pdf):
        with open(pdf, 'rb') as f:
            c2.download_button("PDF 내려받기", f.read(), file_name=f"stock-dashboard_사용설명서_{MN.updated()}.pdf",
                               mime='application/pdf', key='mn_pdf', width='stretch')
    for tab, (_sid, title, lead, fn) in zip(st.tabs([x[1] for x in secs]), secs):
        with tab:
            st.html(CSS + MN.CSS + f'<div class="mn"><div class="mn-src" style="margin:0 2px 10px">{_e(lead)}</div>{fn()}</div>')
    st.caption(MN.DISCLAIMER)
