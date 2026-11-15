# -*- coding: utf-8 -*-
"""종목 분석 '흐름 카드' 그리기 (2026-11-16) — 점(지금 값) 대신 선(지나온 길 → 지금 → 갈 길).

카드 = 라벨 · 큰 값(+방향 화살표) · 스파크라인(실선 = 실적·가격, 점선 = 컨센서스 등 앞으로) · 한 줄 보조.
계산은 stock_snapshot.compute(봇 /report 와 같은 정본), 여기는 그리기만. 순수 HTML/SVG — plotly 보다 가볍다.
spark = {'y': [...], 'fwd': [...]?, 'ref': float?, 'kind': 'line'|'bar'}
"""
from __future__ import annotations

import html as _h

TONE_COLOR = {'good': '#15803D', 'mid': '#B45309', 'bad': '#B91C1C', 'na': '#475569'}
ARROW = {'up': '↗', 'flat': '→', 'down': '↘'}

CSS = """<style>
.fc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:4px 0 10px}
.fc{background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:10px 12px 8px;display:flex;flex-direction:column;gap:2px}
.fc .l{font-size:12px;color:#6B7280;font-weight:600}
.fc .v{font-size:19px;font-weight:700;line-height:1.25;word-break:keep-all}
.fc .s{font-size:12px;color:#6B7280;line-height:1.35;word-break:keep-all}
.fc svg{display:block;width:100%;height:42px;margin:4px 0 2px}
.fc.good{border-top:3px solid #16A34A}.fc.mid{border-top:3px solid #F59E0B}.fc.bad{border-top:3px solid #DC2626}.fc.na{border-top:3px solid #D1D5DB}
.cc{background:#fff;border:1px solid #E5E7EB;border-radius:10px;padding:12px 14px;margin:4px 0 10px}
.cc .hd{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}
.cc .nm{font-size:16px;font-weight:700}.cc .df{font-size:14px;margin-top:2px;word-break:keep-all}
.cc .tag{font-size:12px;padding:2px 8px;border-radius:6px;background:#FEF3C7;color:#92400E;white-space:nowrap}
.cc .kp{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}
.cc .kp div{background:#F8FAFC;border-radius:8px;padding:6px 9px}.cc .kp b{display:block;font-size:16px}
.cc .kp span{font-size:11.5px;color:#6B7280}
.cc .tx{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px;font-size:13px;line-height:1.5;word-break:keep-all}
.cc .tx span{display:block;font-size:11.5px;color:#6B7280}
.cc .src{font-size:11px;color:#9CA3AF;margin-top:8px}
</style>"""


def spark_svg(sp: dict | None, tone: str = 'na', w: int = 220, h: int = 42) -> str:
    if not sp or not sp.get('y'):
        return ''
    ys = [v for v in sp['y'] if v is not None]
    fw = [v for v in (sp.get('fwd') or []) if v is not None]
    if len(ys) < 2:
        return ''
    allv = ys + fw + ([sp['ref']] if sp.get('ref') is not None else [])
    lo, hi = min(allv), max(allv)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    n = len(ys) + len(fw)
    pad = 3
    X = lambda i: pad + (w - 2 * pad) * i / max(1, n - 1)
    Y = lambda v: pad + (h - 2 * pad) * (1 - (v - lo) / (hi - lo))
    col = TONE_COLOR.get(tone, '#475569')
    out = [f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" role="img">']
    if sp.get('ref') is not None:
        out.append(f'<line x1="0" x2="{w}" y1="{Y(sp["ref"]):.1f}" y2="{Y(sp["ref"]):.1f}" stroke="#CBD5E1" stroke-dasharray="2 3" stroke-width="1"/>')
    if sp.get('kind') == 'bar':
        bw = max(1.0, (w - 2 * pad) / n * 0.7)
        base = Y(max(lo, 0))
        for i, v in enumerate(ys):
            y = Y(v)
            out.append(f'<rect x="{X(i) - bw / 2:.1f}" y="{min(y, base):.1f}" width="{bw:.1f}" height="{abs(base - y):.1f}" '
                       f'fill="{col if i >= len(ys) - 5 else "#CBD5E1"}"/>')
    else:
        pts = ' '.join(f'{X(i):.1f},{Y(v):.1f}' for i, v in enumerate(ys))
        out.append(f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="1.8" vector-effect="non-scaling-stroke"/>')
        if fw:
            i0 = len(ys) - 1
            fp = ' '.join(f'{X(i0 + k):.1f},{Y(v):.1f}' for k, v in enumerate([ys[-1]] + fw))
            out.append(f'<polyline points="{fp}" fill="none" stroke="{col}" stroke-width="1.6" stroke-dasharray="4 3" '
                       f'vector-effect="non-scaling-stroke"/>')
        out.append(f'<circle cx="{X(len(ys) - 1):.1f}" cy="{Y(ys[-1]):.1f}" r="2.6" fill="{col}"/>')
    out.append('</svg>')
    return ''.join(out)


def card_html(c: dict) -> str:
    t = c.get('tone', 'na')
    arr = ARROW.get(c.get('dir') or '', '')
    return (f'<div class="fc {t}"><span class="l">{_h.escape(c["label"])}</span>'
            f'<span class="v" style="color:{TONE_COLOR.get(t)}">{_h.escape(str(c["value"]))}{(" " + arr) if arr else ""}</span>'
            f'{spark_svg(c.get("spark"), t)}'
            f'<span class="s">{_h.escape(str(c.get("sub") or ""))}</span></div>')


def cards_html(cards: list[dict]) -> str:
    return '<div class="fc-grid">' + ''.join(card_html(c) for c in cards) + '</div>'


def company_html(co: dict) -> str:
    """기업 요약 카드(A안) — 한 줄 정의 · 핵심 수치 4 · 수익 구조/경쟁 우위/핵심 리스크 각 한 줄. 잘라 쓰지 않는다(줄바꿈)."""
    if not co:
        return ''
    e = _h.escape
    kp = ''.join(f'<div><span>{e(k["label"])}</span><b style="color:{TONE_COLOR.get(k.get("tone", "na"))}">{e(k["value"])}</b>'
                 f'<span>{e(k.get("sub") or "")}</span></div>' for k in co.get('kpis') or [])
    tx = ''.join(f'<div><span>{e(lb)}</span>{e(co[k])}</div>'
                 for k, lb in (('revenue', '수익 구조'), ('moat', '경쟁 우위'), ('risk', '핵심 리스크')) if co.get(k))
    return (f'<div class="cc"><div class="hd"><div><div class="nm">{e(co.get("name") or "")}</div>'
            f'<div class="df">{e(co.get("definition") or "")}</div></div>'
            + (f'<span class="tag">{e(co["type"])}</span>' if co.get('type') else '') + '</div>'
            + (f'<div class="kp">{kp}</div>' if kp else '')
            + (f'<div class="tx">{tx}</div>' if tx else '')
            + f'<div class="src">{e(co.get("src") or "")}</div></div>')
