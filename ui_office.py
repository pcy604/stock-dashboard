# -*- coding: utf-8 -*-
"""🏛️ 경영실 한 장 (2026-11-27 차니 결정) — 손으로 입력하던 7개 탭(스코어카드·로드맵·결정·이슈·회의록·변경이력·KPI)을 폐지.

왜: 입력해야 굴러가는 화면이라 아무도 쓰지 않았고, 실제 상태는 docs/현황.md · docs/changelog.md 에 있었다.
→ 이 화면은 그 두 파일을 **그대로 읽어** 보여 준다. 새로 입력할 곳이 없다 = 어긋날 곳이 없다.
구성: 운영 상태 한 줄 → 지금 할 일(현황의 첫 큰 절) → 차니 작업 → 최근 변경 → (접기) 현황 전문 · 비공개 설명서.
"""
import json
import re
from pathlib import Path

BASE = Path(__file__).resolve().parent


def _read(p):
    try:
        return (BASE / p).read_text(encoding='utf-8')
    except Exception:
        return ''


def _section(md: str, head_re: str) -> str:
    """'## <제목>' 절 하나(다음 '## ' 전까지)."""
    m = re.search(rf'^## {head_re}.*?$', md, re.M)
    if not m:
        return ''
    nxt = re.search(r'^## ', md[m.end():], re.M)
    return md[m.start(): m.end() + (nxt.start() if nxt else len(md))].strip()


def _sub(md: str, head: str) -> str:
    m = re.search(rf'^### {re.escape(head)}.*?$', md, re.M)
    if not m:
        return ''
    nxt = re.search(r'^#{2,3} ', md[m.end():], re.M)
    return md[m.end(): m.end() + (nxt.start() if nxt else len(md))].strip()


def render(st, ops_counts=None):
    hy = _read('docs/현황.md')
    cl = [x for x in _read('docs/changelog.md').splitlines() if x.startswith('- 20')]
    heal = {}
    try:
        heal = json.loads(_read('results/auto_heal.json') or '{}')
    except Exception:
        pass

    # ① 운영 상태 — 한 줄
    ka, stl = ops_counts or (None, None)
    bits = [f"정답 점검 {'✅' if not ka else f'🔴 {ka}건'}", f"데이터 신선도 {'✅' if not stl else f'🔴 {stl}건 정지'}"]
    if heal:
        bits.append(f"자가 복구 {heal.get('checked', '-')} · 재실행 {len(heal.get('runs') or {})}종"
                    + (f" · 🔴 반복 실패 {', '.join(heal['escalate'])}" if heal.get('escalate') else ''))
    title = (re.search(r'^# (.+)$', hy, re.M) or [None, '현황'])[1]
    st.markdown(f"#### 🏛️ 경영실 — {title}")
    st.caption(' · '.join(bits) + " — 상세는 📘 사용법 › 🗄️ 데이터")

    # ② 지금 할 일 — 현황의 첫 '##' 절(가장 최근 우선순위)
    first = _section(hy, r'')
    if first:
        st.markdown(first)

    # ③ 차니 작업 · ④ 최근 변경 — 나란히
    c1, c2 = st.columns(2, gap='medium')
    with c1:
        st.markdown('##### 🙋 차니 작업')
        todo = _sub(hy, '차니 작업')
        st.markdown(todo or '_없음_')
    with c2:
        st.markdown('##### 🕘 최근 변경 (10)')
        st.markdown('\n'.join(cl[-10:][::-1]) or '_없음_')

    with st.expander('📄 현황 전문 (docs/현황.md)', expanded=False):
        st.markdown(hy)
    with st.expander('📘 설명서 비공개 절 (개선 내역 · 검증·한계)', expanded=False):
        try:
            import ui_home as _UH
            _UH.manual_internal()
        except Exception as e:
            st.caption(f'`설명서 비공개 절 실패: {str(e)[:120]}`')
    st.caption('원천: GitHub docs/현황.md · docs/changelog.md (정본) — 이 화면에서 고치지 않는다. 세션이 끝날 때 Claude 가 갱신한다.')
