# -*- coding: utf-8 -*-
"""로그인 · 접근 권한 · 사용량 측정 (2026-10-21, 지인 테스트 단계)

왜
  사이트·저장소가 공개라 '내 포트폴리오'는 로그인한 사람만 써야 한다. 첫 단계는 지인 테스트라
  **허용 이메일 명단**(secrets)으로만 연다. 공개 탭(종합·매크로·발굴·분석)은 로그인 없이 그대로.

  사용량은 '언젠가 구독·광고·매각을 판단할 근거'다 — 첫날부터 쌓지 않으면 나중에 증명할 수 없다.
  PostHog EU(서버에서 직접 전송, 브라우저 추적 스크립트 없음)를 쓴다. 키가 없으면 아무것도 안 한다.
  이메일은 보내지 않는다 — 해시(sha256 앞 16자)만 보낸다.

secrets.toml
  [auth]                       # Streamlit 기본 구글 로그인(st.login)
  redirect_uri = "https://<앱주소>/oauth2callback"
  cookie_secret = "<임의 긴 문자열>"
  client_id = "..."
  client_secret = "..."
  server_metadata_url = "https://accounts.google.com/.well-known/openid-configuration"

  [access]
  owner_email = "pcy604604@gmail.com"      # 토스 연동 칸은 이 계정에만 보인다
  open = true                              # 로그인한 누구나 — 초대 없이 자동 입장
  allowed_emails = ["a@gmail.com"]         # open=false 일 때만 쓰는 명단
  blocked_emails = []                      # 문제 계정 차단(open 이어도 막힘)

  [analytics]
  posthog_key = "phc_..."                  # 없으면 측정 끔
  posthog_host = "https://eu.i.posthog.com"
"""
import hashlib
import threading
import uuid

import requests
import streamlit as st


def _sec(section, key=None, default=None):
    try:
        s = st.secrets.get(section)
    except Exception:          # secrets.toml 자체가 없을 때(로컬·테스트)
        return default
    if s is None:
        return default
    if key is None:
        return s
    try:
        return s.get(key, default)
    except Exception:
        return default


def auth_ready() -> bool:
    """구글 로그인이 설정돼 있나 — 없으면 st.login 이 예외를 던지므로 먼저 본다."""
    a = _sec('auth')
    return bool(a and a.get('client_id') and a.get('redirect_uri'))


def email() -> str:
    try:
        return (st.user.get('email') or '').strip().lower() if st.user.is_logged_in else ''
    except Exception:
        return ''


def owner() -> str:
    return str(_sec('access', 'owner_email', '') or '').strip().lower()


def allowed(em: str | None = None) -> bool:
    em = (em if em is not None else email())
    if not em:
        return False
    blk = [str(x).strip().lower() for x in (_sec('access', 'blocked_emails', []) or [])]
    if em in blk:
        return False
    # open = true → 구글 로그인만 하면 누구나(2026-10-21). 보유 종목은 세션에만 있어 서로 볼 수 없으므로 명단이 보안 장치가 아니다.
    if _sec('access', 'open', False):
        return True
    lst = [str(x).strip().lower() for x in (_sec('access', 'allowed_emails', []) or [])]
    return em == owner() or em in lst


def is_owner() -> bool:
    e = email()
    return bool(e) and e == owner()


def uid() -> str:
    """측정용 익명 ID — 로그인하면 이메일 해시, 아니면 세션 ID. 이메일 원문은 밖으로 안 나간다."""
    e = email()
    if e:
        return 'u_' + hashlib.sha256(e.encode()).hexdigest()[:16]
    if '_anon_id' not in st.session_state:
        st.session_state['_anon_id'] = 's_' + uuid.uuid4().hex[:16]
    return st.session_state['_anon_id']


def _post(payload, host):
    try:
        requests.post(host.rstrip('/') + '/i/v0/e/', json=payload, timeout=3)
    except Exception:
        pass                    # 측정 실패가 화면을 막으면 안 된다


def track(event: str, **props):
    key = _sec('analytics', 'posthog_key')
    if not key:
        return
    host = _sec('analytics', 'posthog_host', 'https://eu.i.posthog.com')
    props.setdefault('logged_in', bool(email()))
    payload = {'api_key': key, 'event': event, 'distinct_id': uid(), 'properties': props}
    threading.Thread(target=_post, args=(payload, host), daemon=True).start()


def track_session(tab: str | None):
    """세션 첫 렌더 1회 + 탭이 바뀔 때마다 1회. 매 상호작용마다 보내지 않는다(쿼터·잡음)."""
    if not st.session_state.get('_trk_started'):
        st.session_state['_trk_started'] = True
        track('session_start')
    if tab and st.session_state.get('_trk_tab') != tab:
        st.session_state['_trk_tab'] = tab
        track('tab_view', tab=tab)


def gate(feature: str = '내 포트폴리오') -> bool:
    """로그인 + 허용 명단을 통과해야 True. 아니면 안내 카드를 그리고 False."""
    if not auth_ready():
        st.info(f"🔒 **{feature}** — 로그인 후 쓸 수 있습니다. (운영자: 로그인 설정이 아직 없습니다 — `access.py` 머리말 참고)")
        return False
    e = email()
    if not e:
        with st.container(border=True):
            st.markdown(f"#### 🔒 {feature} — 본인만 봅니다")
            st.caption("구글 계정으로 로그인하면 열립니다. 보유 종목은 이 세션에만 머물고 서버 파일로 저장하지 않습니다. "
                       "지금은 지인 테스트 단계라 초대된 계정만 들어올 수 있습니다.")
            st.button("G  구글로 로그인", on_click=st.login, args=('google',) if _sec('auth', 'google') else (),
                      type='primary', key='acc_login')
        return False
    if not allowed(e):
        with st.container(border=True):
            st.markdown("#### ⏳ 테스트 초대 대기 중")
            st.caption(f"`{e}` 계정은 아직 테스트 명단에 없습니다. 운영자에게 이 이메일을 알려주세요.")
            st.button("로그아웃", on_click=st.logout, key='acc_logout_wait')
        track('gate_blocked')
        return False
    c1, c2 = st.columns([5, 1])
    c1.caption(f"🔓 {e} 로 로그인됨" + (" · 운영자" if is_owner() else ""))
    c2.button("로그아웃", on_click=st.logout, key='acc_logout', width='stretch')
    return True
