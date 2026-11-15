# -*- coding: utf-8 -*-
"""💬 AI 질문 원형 버튼 — 화면 위에 떠 있고 마우스·손가락으로 끌어 옮길 수 있다(2026-11-16, 차니 요청).

구조: dashboard 가 `st.container(key='ai_fab')` 안에 st.popover 를 그린다 → 여기 CSS 가 그 컨테이너를
화면 고정 원형 버튼으로 바꾸고, 높이 0 짜리 components.html 스크립트가 부모 문서의 버튼에 끌기 처리를 붙인다.
- 위치는 브라우저 localStorage('ai_fab_pos')에 기억(방문자별 · 서버 저장 없음).
- 4px 넘게 움직이면 '끌기'로 보고 그 직후의 클릭(팝오버 열기)을 한 번 막는다.
- 창 크기가 바뀌어 화면 밖으로 나가면 안쪽으로 되돌린다.
"""
import streamlit as st
import streamlit.components.v1 as components

VERSION = '2026-11-16b'

CSS = """<style>
  .st-key-ai_fab { position:fixed !important; right:24px; bottom:24px; z-index:1000; width:56px !important;
                   min-width:0 !important; touch-action:none; }
  .st-key-ai_fab [data-testid="stPopover"], .st-key-ai_fab [data-testid="stPopover"] > div { width:56px !important; }
  .st-key-ai_fab [data-testid="stPopoverButton"], .st-key-ai_fab button {
      position:relative; width:56px !important; height:56px !important; min-height:56px !important; border-radius:50% !important;
      padding:0 !important; border:2px solid #7cb342 !important; color:transparent !important;
      background:#fff url("__LOGO__") center / 78% no-repeat !important;
      box-shadow:0 6px 18px rgba(15,23,42,.22) !important; cursor:grab; overflow:visible !important; }
  .st-key-ai_fab button:hover { box-shadow:0 8px 22px rgba(15,23,42,.32) !important; transform:translateY(-1px); }
  .st-key-ai_fab button > div { position:static !important; }
  .st-key-ai_fab button p { position:absolute; right:-6px; bottom:-4px; margin:0 !important; padding:1px 6px; border-radius:999px;
      background:#1b1f24; color:#fff !important; font-size:11px !important; font-weight:800; line-height:16px !important;
      letter-spacing:.02em; border:2px solid #fff; }
  .st-key-ai_fab button [data-testid="stIconMaterial"], .st-key-ai_fab button svg { display:none !important; }
  .st-key-ai_fab.dragging button { cursor:grabbing; }
  [data-testid="stPopoverBody"]:has(.st-key-ai_pane) { width:min(480px, 94vw) !important; max-width:94vw !important; }
  @media print { .st-key-ai_fab { display:none !important; } }
</style>"""

JS = """<script>
(function(){
  const D = window.parent.document, W = window.parent;
  const KEY = 'ai_fab_pos';
  function clamp(x, y, el){
    const w = el.offsetWidth || 56, h = el.offsetHeight || 56;
    return [Math.min(Math.max(4, x), W.innerWidth - w - 4), Math.min(Math.max(4, y), W.innerHeight - h - 4)];
  }
  function place(el, x, y){
    const p = clamp(x, y, el);
    el.style.left = p[0] + 'px'; el.style.top = p[1] + 'px'; el.style.right = 'auto'; el.style.bottom = 'auto';
  }
  function restore(el){
    try { const p = JSON.parse(W.localStorage.getItem(KEY) || 'null'); if (p) place(el, p[0], p[1]); } catch(e) {}
  }
  function bind(el){
    if (el.dataset.fabBound === '1') return;
    el.dataset.fabBound = '1';
    restore(el);
    let sx = 0, sy = 0, ox = 0, oy = 0, down = false, moved = false;
    el.addEventListener('pointerdown', function(e){
      if (e.button !== undefined && e.button !== 0) return;
      const r = el.getBoundingClientRect();
      sx = e.clientX; sy = e.clientY; ox = r.left; oy = r.top; down = true; moved = false;
    });
    W.addEventListener('pointermove', function(e){
      if (!down) return;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (!moved && Math.abs(dx) + Math.abs(dy) < 5) return;
      moved = true; el.classList.add('dragging');
      place(el, ox + dx, oy + dy);
      e.preventDefault();
    }, {passive:false});
    W.addEventListener('pointerup', function(){
      if (!down) return;
      down = false; el.classList.remove('dragging');
      if (moved) {
        const r = el.getBoundingClientRect();
        try { W.localStorage.setItem(KEY, JSON.stringify([r.left, r.top])); } catch(e) {}
        el.addEventListener('click', function stop(ev){ ev.stopPropagation(); ev.preventDefault();
          el.removeEventListener('click', stop, true); }, true);
      }
    });
    W.addEventListener('resize', function(){
      const r = el.getBoundingClientRect(); if (el.style.left) place(el, r.left, r.top);
    });
  }
  function tick(){ const el = D.querySelector('.st-key-ai_fab'); if (el) bind(el); }
  tick(); setInterval(tick, 800);
})();
</script>"""


def _logo_uri() -> str:
    """assets/studian_mark.png(스터디언 로고 96px) → data URI. 없으면 빈 문자열(흰 원 + AI 배지만)."""
    import base64, os
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'assets', 'studian_mark.png')
    try:
        return 'data:image/png;base64,' + base64.b64encode(open(p, 'rb').read()).decode()
    except Exception:
        return ''


def mount():
    """CSS 와 끌기 스크립트를 한 번 심는다. 실패해도 버튼은 고정 위치로 동작."""
    st.html(CSS.replace('__LOGO__', _logo_uri()))
    try:
        components.html(JS, height=0)
    except Exception:
        pass
