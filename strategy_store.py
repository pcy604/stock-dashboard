# -*- coding: utf-8 -*-
"""🧪 퀀트 전략 저장 · 공개 게시판 (2026-11-16, 차니 요청) — Supabase(Postgres) REST, user_store 와 같은 연결.

- 계정별 저장: 행 키 uid = 이메일 sha256(원문 이메일은 DB 에 없음). 전략 명세(spec)·성과(stats)는 평문 JSON
  (공개 게시판에 그대로 보여야 하고, 개인정보가 아니다).
- 공개: public=true 인 행만 게시판에 나온다. 작성자 표기 = 고객이 고른 닉네임 또는 익명 번호('익명 #' + uid 앞 4자).
- 성과(stats)는 **서버가 계산한 값만** 저장한다(화면이 방금 돌린 결과) — 사용자가 숫자를 입력하지 않는다.
- 랭킹 기준은 미정(차니 2026-11-16 '천천히 정하자') — 게시판은 최신순 + 열 머리 정렬만.

SQL (Supabase → SQL Editor 에서 한 번)
  create table if not exists strategies (
    id bigserial primary key, uid text not null, name text not null, market text not null,
    spec jsonb not null, stats jsonb, public boolean not null default false, display text,
    created_at timestamptz not null default now(), updated_at timestamptz not null default now());
  create index if not exists strategies_uid on strategies(uid);
  create index if not exists strategies_pub on strategies(public, created_at desc);
  alter table strategies enable row level security;
"""
from datetime import datetime, timezone

import requests

import user_store as _U

_T = 'strategies'
MAX_PER_USER = 50
STAT_KEYS = ('CAGR', 'MDD', 'Sharpe', 'Calmar', '승률', '손익비', '매도건수', 'BM_CAGR', 'BM_MDD')
SQL = __doc__.split('SQL (Supabase → SQL Editor 에서 한 번)')[1].strip()


def ready() -> bool:
    return _U.ready()


def _url():
    return _U._url(_U._cfg()).rsplit('/', 1)[0] + '/' + _T


def anon_name(email: str) -> str:
    return '익명 #' + _U._uid(email)[:4].upper()


def slim_stats(S: dict, start=None, end=None) -> dict:
    out = {k: (round(float(S[k]), 3) if isinstance(S.get(k), (int, float)) else S.get(k)) for k in STAT_KEYS if k in S}
    out['start'], out['end'] = (str(start)[:10] if start is not None else None), (str(end)[:10] if end is not None else None)
    return out


def mine(email: str) -> list:
    c = _U._cfg()
    r = requests.get(_url(), params={'uid': f'eq.{_U._uid(email)}', 'select': 'id,name,market,spec,stats,public,display,created_at',
                                     'order': 'created_at.desc', 'limit': MAX_PER_USER},
                     headers=_U._h(c), timeout=6)
    r.raise_for_status()
    return r.json()


def save(email: str, name: str, market: str, spec: dict, stats: dict, public: bool, display: str) -> None:
    c = _U._cfg()
    if len(mine(email)) >= MAX_PER_USER:
        raise RuntimeError(f'계정당 최대 {MAX_PER_USER}개 — 오래된 전략을 지운 뒤 저장')
    now = datetime.now(timezone.utc).isoformat()
    row = dict(uid=_U._uid(email), name=name.strip()[:60] or '이름 없음', market=market, spec=spec, stats=stats,
               public=bool(public), display=(display or anon_name(email)).strip()[:24], created_at=now, updated_at=now)
    r = requests.post(_url(), json=[row], headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def update(email: str, sid: int, **fields) -> None:
    c = _U._cfg()
    fields = {k: v for k, v in fields.items() if k in ('name', 'public', 'display')}
    fields['updated_at'] = datetime.now(timezone.utc).isoformat()
    r = requests.patch(_url(), params={'id': f'eq.{int(sid)}', 'uid': f'eq.{_U._uid(email)}'}, json=fields,
                       headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def delete(email: str, sid: int) -> None:
    c = _U._cfg()
    r = requests.delete(_url(), params={'id': f'eq.{int(sid)}', 'uid': f'eq.{_U._uid(email)}'}, headers=_U._h(c), timeout=6)
    r.raise_for_status()


def public_list(market: str | None = None, limit: int = 200) -> list:
    """공개 전략 — uid 는 내보내지 않는다(작성자 = display 만)."""
    c = _U._cfg()
    p = {'public': 'is.true', 'select': 'id,name,market,spec,stats,display,created_at', 'order': 'created_at.desc', 'limit': limit}
    if market:
        p['market'] = f'eq.{market}'
    r = requests.get(_url(), params=p, headers=_U._h(c), timeout=6)
    r.raise_for_status()
    return r.json()
