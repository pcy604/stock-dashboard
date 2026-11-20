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
  -- 2026-11-20 이미지 첨부(마이그레이션 voc_images): 열 + 공개 읽기 Storage 버킷. 쓰기는 서버(service_role)만.
  alter table voc add column if not exists images text[] not null default '{}';
  insert into storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
  values ('voc', 'voc', true, 2097152, array['image/webp','image/png','image/jpeg']) on conflict (id) do nothing;
"""
import io
import uuid
from datetime import datetime, timezone

import requests

import user_store as _U

_T = 'voc'
KINDS = ['기능 요청', '개선', '버그', '데이터 오류', '기타']
STATUS = ['접수', '검토', '진행', '완료', '보류']
MAX_TITLE, MAX_BODY = 80, 2000
MAX_IMG, MAX_IMG_MB, IMG_PX = 3, 10, 1600          # 장수 · 원본 상한 · 긴 변(줄여서 webp 로 저장)
_BUCKET = 'voc'
_SEL = 'id,display,area,kind,title,body,status,reply,votes,created_at,updated_at'


def ready() -> bool:
    return _U.ready()


def _url():
    return _U._url(_U._cfg()).rsplit('/', 1)[0] + '/' + _T


def _base():
    return _url().rsplit('/rest/v1/', 1)[0]


def img_bytes(raw: bytes) -> bytes:
    """이미지 → 긴 변 IMG_PX 이하 webp. 이미지가 아니면 ValueError."""
    from PIL import Image
    if len(raw) > MAX_IMG_MB * 1024 * 1024:
        raise ValueError(f'이미지는 장당 {MAX_IMG_MB}MB 까지입니다')
    try:
        im = Image.open(io.BytesIO(raw))
        im.load()
    except Exception:
        raise ValueError('이미지 파일이 아닙니다')
    im = im.convert('RGBA' if im.mode in ('RGBA', 'LA', 'P') else 'RGB')
    im.thumbnail((IMG_PX, IMG_PX))
    out = io.BytesIO()
    im.save(out, 'WEBP', quality=82)
    return out.getvalue()


def upload(raw: bytes) -> str:
    """서버 키로만 올린다(버킷은 읽기만 공개). 반환 = 공개 URL."""
    c = _U._cfg()
    name = f"{datetime.now(timezone.utc):%Y%m}/{uuid.uuid4().hex}.webp"
    h = {k: v for k, v in _U._h(c).items() if k != 'Content-Type'}
    r = requests.post(f'{_base()}/storage/v1/object/{_BUCKET}/{name}', data=img_bytes(raw),
                      headers={**h, 'Content-Type': 'image/webp'}, timeout=15)
    r.raise_for_status()
    return f'{_base()}/storage/v1/object/public/{_BUCKET}/{name}'


def _now():
    return datetime.now(timezone.utc).isoformat()


def clean(area: str, kind: str, title: str, body: str) -> dict:
    title, body = (title or '').strip(), (body or '').strip()
    if len(title) < 2:
        raise ValueError('제목을 2자 이상 적어 주십시오')
    if kind not in KINDS:
        raise ValueError('분류를 골라 주십시오')
    return dict(area=(area or '전체')[:30], kind=kind, title=title[:MAX_TITLE], body=body[:MAX_BODY])


def submit(uid: str, display: str, area: str, kind: str, title: str, body: str, page: str = '',
           images: list | None = None) -> None:
    """uid = access.uid()(해시) — 이 모듈은 원문 계정 정보를 받지 않는다. images = upload() 가 준 URL."""
    c = _U._cfg()
    row = dict(clean(area, kind, title, body), uid=uid or None,
               display=(display or '익명').strip()[:24], page=(page or '')[:200], created_at=_now(), updated_at=_now())
    if images:                       # 열이 아직 없는 DB 에서도 글만은 접수되게 — 있을 때만 보낸다
        row['images'] = list(images)[:MAX_IMG]
    r = requests.post(_url(), json=[row], headers=_U._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def items(limit: int = 300) -> list:
    """공개 목록 — uid 는 빼고. 최신순."""
    c = _U._cfg()
    for sel in (_SEL + ',images', _SEL):      # images 열이 없는 DB(마이그레이션 전) → 글만
        r = requests.get(_url(), params={'select': sel, 'order': 'created_at.desc', 'limit': limit}, headers=_U._h(c), timeout=6)
        if getattr(r, 'status_code', 200) != 400:
            break
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
