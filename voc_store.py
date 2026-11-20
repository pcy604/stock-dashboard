# -*- coding: utf-8 -*-
"""💬 VOC — 기능 개선 요청·버그·데이터 오류 접수 (2026-11-20, 차니 요구 4) — Supabase REST, user_store 와 같은 연결.

- 누구나 남긴다(로그인 없으면 uid 없음 = 익명). uid = access.uid() 해시(원문 계정 정보는 DB 에 없음).
- 목록은 전원에게 공개(제목·분류·상태·답변·공감 수만 — uid 는 내보내지 않는다). 상태·답변은 소유자만 바꾼다.
- 상태 흐름: 접수 → 검토 → 진행 → 완료 | 보류.

SQL (Supabase BUZA_ALARM 에 2026-11-20 적용 — 마이그레이션 create_voc)
  create table if not exists voc (
    id bigserial primary key, uid text, display text, area text not null, kind text not null,
    title text not null, body text, page text, status text not null default '접수', reply text, votes int not null default 0,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now());
  create index if not exists voc_status on voc(status, created_at desc);
  alter table voc enable row level security;
"""
from datetime import datetime, timezone

import requests

import user_store as _U

_T = 'voc'
KINDS = ['기능 요청', '개선', '버그', '데이터 오류', '기타']
STATUS = ['접수', '검토', '진행', '완료', '보류']
MAX_TITLE, MAX_BODY = 80, 2000


def ready() -> bool:
    return _U.ready()


def _url():
    return _U._url(_U._cfg()).rsplit('/', 1)[0] + '/' + _T


def _now():
    return datetime.now(timezone.utc).isoformat()


def clean(area: str, kind: str, title: str, body: str) -> dict:
    title, body = (title or '').strip(), (body or '').strip()
    if len(title) < 2:
        raise ValueError('제목을 2자 이상 적어 주십시오')
    if kind not in KINDS:
        raise ValueError('분류를 골라 주십시오')
    return dict(area=(area or '전체')[:30], kind=kind, title=title[:MAX_TITLE], body=body[:MAX_BODY])


def submit(uid: str, display: str, area: str, kind: str, title: str, body: str, page: str = '') -> None:
    """uid = access.uid()(해시) — 이 모듈은 원문 계정 정보를 받지 않는다."""
    c = _U._cfg()
    row = dict(clean(area, kind, title, body), uid=uid or None,
               display=(display or '익명').strip()[:24], page=(page or '')[:200], created_at=_now(), updated_at=_now())
    r = requests.post(_url(), json=[row], headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def items(limit: int = 300) -> list:
    """공개 목록 — uid 는 빼고. 최신순."""
    c = _U._cfg()
    r = requests.get(_url(), params={'select': 'id,display,area,kind,title,body,status,reply,votes,created_at,updated_at',
                                     'order': 'created_at.desc', 'limit': limit}, headers=_U._h(c), timeout=6)
    r.raise_for_status()
    return r.json()


def set_status(vid: int, status: str, reply: str | None = None) -> None:
    """소유자 전용 — 호출부(ui_voc)가 access.is_owner() 로 막는다."""
    if status not in STATUS:
        raise ValueError(status)
    c = _U._cfg()
    f = dict(status=status, updated_at=_now())
    if reply is not None:
        f['reply'] = reply.strip()[:MAX_BODY]
    r = requests.patch(_url(), params={'id': f'eq.{int(vid)}'}, json=f, headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def vote(vid: int, current: int) -> None:
    c = _U._cfg()
    r = requests.patch(_url(), params={'id': f'eq.{int(vid)}'}, json=dict(votes=int(current) + 1),
                       headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()
