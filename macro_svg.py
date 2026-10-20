# -*- coding: utf-8 -*-
"""
사이클 도식 — 우라가미 4계절 바퀴 · 코스톨라니 달걀 (2026-10-21)

표(알약 목록) 대신 '돌아가는 그림'으로 지금 위치를 보인다. 순수 SVG 문자열만 만든다(Streamlit 모름).
색은 CSS 변수(var(--ink) 등)를 써서 다크 모드에서도 읽히게 한다. 계절 색만 고정색이다.
"""
from __future__ import annotations

import html
import math

SEASON_ORDER = ['FIN', 'EARN', 'RFIN', 'RERN']          # 시계 방향: 봄 → 여름 → 가을 → 겨울
SEASON_COLOR = {'FIN': '#16a34a', 'EARN': '#ca8a04', 'RFIN': '#ea580c', 'RERN': '#2563eb'}
SEASON_TINT = {'FIN': '#dcfce7', 'EARN': '#fef3c7', 'RFIN': '#ffedd5', 'RERN': '#dbeafe'}


def _pt(cx, cy, r, deg):
    a = math.radians(deg)
    return cx + r * math.cos(a), cy + r * math.sin(a)


def _arc(cx, cy, r0, r1, a0, a1):
    """도넛 조각 경로 (각도: 0=오른쪽, 시계 방향 +)."""
    large = 1 if (a1 - a0) % 360 > 180 else 0
    x0, y0 = _pt(cx, cy, r1, a0); x1, y1 = _pt(cx, cy, r1, a1)
    x2, y2 = _pt(cx, cy, r0, a1); x3, y3 = _pt(cx, cy, r0, a0)
    return (f"M{x0:.1f},{y0:.1f} A{r1},{r1} 0 {large} 1 {x1:.1f},{y1:.1f} "
            f"L{x2:.1f},{y2:.1f} A{r0},{r0} 0 {large} 0 {x3:.1f},{y3:.1f} Z")


def season_wheel(phase: str, scores: dict, seasons: dict, conf_txt: str = '', width: int = 360) -> str:
    """우라가미 4계절 바퀴. phase = 현재 국면 키, scores = {키: 점수}, seasons = SEASONS(이름·이모지)."""
    cx, cy, r0, r1 = 180, 150, 66, 124
    starts = {'FIN': 180, 'EARN': 270, 'RFIN': 0, 'RERN': 90}  # 봄=좌상, 여름=우상, 가을=우하, 겨울=좌하
    parts = []
    for k in SEASON_ORDER:
        a0 = starts[k] + 2; a1 = starts[k] + 88
        on = (k == phase)
        mid = (a0 + a1) / 2
        dx, dy = (_pt(0, 0, 7, mid) if on else (0, 0))
        fill = SEASON_COLOR[k] if on else SEASON_TINT[k]
        parts.append(f"<path d='{_arc(cx + dx, cy + dy, r0, r1 + (6 if on else 0), a0, a1)}' "
                     f"style='fill:{fill};stroke:var(--surface,#fff);stroke-width:2'/>")
        lx, ly = _pt(cx + dx, cy + dy, (r0 + r1) / 2 + 3, mid)
        s = seasons[k]
        tc = '#ffffff' if on else 'var(--ink-2,#4B5058)'
        parts.append(f"<text x='{lx:.1f}' y='{ly - 4:.1f}' text-anchor='middle' style='font-size:{13 if on else 12}px;"
                     f"font-weight:{800 if on else 600};fill:{tc}'>{s['emoji']} {html.escape(s['name'])}</text>")
        parts.append(f"<text x='{lx:.1f}' y='{ly + 13:.1f}' text-anchor='middle' style='font-size:11px;"
                     f"fill:{tc};opacity:.85'>{scores.get(k, '-')}점</text>")
    # 회전 방향 화살표 (바깥 고리)
    for b in (270, 0, 90, 180):
        x, y = _pt(cx, cy, r1 + 14, b)
        rot = b + 90
        parts.append(f"<path d='M-5,-4 L5,0 L-5,4 Z' transform='translate({x:.1f},{y:.1f}) rotate({rot})' "
                     f"style='fill:var(--ink-3,#767C86)'/>")
    s = seasons.get(phase, {})
    parts.append(f"<text x='{cx}' y='{cy - 6}' text-anchor='middle' style='font-size:11px;fill:var(--ink-3,#767C86)'>지금</text>")
    parts.append(f"<text x='{cx}' y='{cy + 13}' text-anchor='middle' style='font-size:16px;font-weight:800;"
                 f"fill:{SEASON_COLOR.get(phase, '#333')}'>{html.escape(s.get('name', '-'))}</text>")
    if conf_txt:
        parts.append(f"<text x='{cx}' y='{cy + 30}' text-anchor='middle' style='font-size:10.5px;fill:var(--ink-3,#767C86)'>"
                     f"{html.escape(conf_txt[:14])}</text>")
    return (f"<svg viewBox='0 0 360 300' width='100%' style='max-width:{width}px;display:block;margin:0 auto' "
            f"role='img' aria-label='우라가미 4계절 — 현재 {html.escape(s.get('name', '-'))}'>{''.join(parts)}</svg>")


EGG_POS = {  # 달걀 둘레 위 각도(0=오른쪽, 시계 방향 +). 오른쪽으로 내려가며 금리 하락, 왼쪽으로 올라가며 금리 상승
    'A1': -62, 'A2': 0, 'A3': 62, 'B1': 118, 'B2': 180, 'B3': 242,
}
EGG_SHORT = {'A1': '채권', 'A2': '채권·부동산', 'A3': '주식 매수', 'B1': '주식 보유', 'B2': '주식 축소', 'B3': '현금·예금'}


def kostolany_egg(code: str | None, flat: bool = False, width: int = 360) -> str:
    """코스톨라니 달걀. code = 'A1'~'B3' 또는 None. flat = 금리 방향 미확정."""
    cx, cy, rx, ry = 180, 150, 84, 112
    parts = [f"<ellipse cx='{cx}' cy='{cy}' rx='{rx}' ry='{ry}' style='fill:none;stroke:var(--line,#E3E5EA);stroke-width:10'/>"]
    # 방향 화살표: 오른쪽 위(내려가는 쪽), 왼쪽 아래(올라가는 쪽)
    for deg in (-30, 150):
        t = math.radians(deg)
        x, y = cx + rx * math.cos(t), cy + ry * math.sin(t)
        rot = math.degrees(math.atan2(ry * math.cos(t), -rx * math.sin(t)))   # 시계 방향 접선
        parts.append(f"<path d='M-6,-5 L6,0 L-6,5 Z' transform='translate({x:.1f},{y:.1f}) rotate({rot})' "
                     f"style='fill:var(--ink-3,#767C86)'/>")
    parts.append(f"<text x='{cx}' y='{cy - ry - 12}' text-anchor='middle' style='font-size:11px;fill:var(--ink-3,#767C86)'>▲ 금리 고점</text>")
    parts.append(f"<text x='{cx}' y='{cy + ry + 22}' text-anchor='middle' style='font-size:11px;fill:var(--ink-3,#767C86)'>▼ 금리 저점</text>")
    parts.append(f"<text x='{cx + rx + 30}' y='{cy - 32}' text-anchor='middle' style='font-size:10px;fill:var(--ink-3,#767C86)' "
                 f"transform='rotate(90 {cx + rx + 30} {cy - 32})'>금리 하락 ↓</text>")
    parts.append(f"<text x='{cx - rx - 30}' y='{cy + 32}' text-anchor='middle' style='font-size:10px;fill:var(--ink-3,#767C86)' "
                 f"transform='rotate(-90 {cx - rx - 30} {cy + 32})'>금리 상승 ↑</text>")
    for k, deg in EGG_POS.items():
        x, y = cx + rx * math.cos(math.radians(deg)), cy + ry * math.sin(math.radians(deg))
        on = (k == code)
        col = '#1F4E79' if k.startswith('A') else '#A32C2C'
        if on and flat:
            parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='17' style='fill:none;stroke:{col};stroke-width:2;stroke-dasharray:4 3'/>")
        parts.append(f"<circle cx='{x:.1f}' cy='{y:.1f}' r='{11 if on else 6}' style='fill:{col if on else 'var(--surface,#fff)'};"
                     f"stroke:{col};stroke-width:2'/>")
        right = math.cos(math.radians(deg)) >= -0.01
        if abs(math.cos(math.radians(deg))) < 0.3:     # 위·아래 끝은 가운데 정렬 대신 안쪽으로
            right = deg < 90 or deg > 270
        tx = x + (18 if right else -18)
        parts.append(f"<text x='{tx:.1f}' y='{y + 4:.1f}' text-anchor='{'start' if right else 'end'}' "
                     f"style='font-size:{12.5 if on else 11}px;font-weight:{800 if on else 500};"
                     f"fill:{col if on else 'var(--ink-2,#4B5058)'}'>{k} {EGG_SHORT[k]}</text>")
    if code:
        parts.append(f"<text x='{cx}' y='{cy - 4}' text-anchor='middle' style='font-size:11px;fill:var(--ink-3,#767C86)'>지금</text>")
        parts.append(f"<text x='{cx}' y='{cy + 15}' text-anchor='middle' style='font-size:15px;font-weight:800;fill:var(--ink,#16181D)'>"
                     f"{code} {EGG_SHORT[code]}</text>")
        if flat:
            parts.append(f"<text x='{cx}' y='{cy + 32}' text-anchor='middle' style='font-size:10.5px;fill:var(--warn,#8A5D0F)'>방향 미확정</text>")
    return (f"<svg viewBox='-10 0 380 300' width='100%' style='max-width:{width}px;display:block;margin:0 auto' "
            f"role='img' aria-label='코스톨라니 달걀 — 현재 {code or '판정 불가'}'>{''.join(parts)}</svg>")
