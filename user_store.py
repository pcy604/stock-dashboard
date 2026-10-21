# -*- coding: utf-8 -*-
"""계정별 포트폴리오 암호화 저장 (2026-10-21) — Supabase(Postgres) REST

왜
  세션에만 두면 브라우저를 닫을 때마다 사라진다. 그렇다고 서버 파일은 모든 방문자가 공유한다.
  → 로그인 계정마다 한 줄씩 DB 에 저장하되, **DB 가 통째로 새도 못 읽게** 앱이 암호화해서 넣는다.

설계
  - 행 키(uid): 이메일의 sha256 — DB 에 이메일 원문이 없다.
  - 내용: Fernet(AES-128-CBC + HMAC). 키 = HKDF-SHA256(master_key, info="pf:"+이메일).
    master_key 는 Streamlit Secrets 에만 있다. DB 운영자(Supabase)·DB 유출만으로는 복호화 불가.
  - 표에는 RLS 를 켜고 정책을 안 만든다 → 공개(anon) 키로는 아무것도 안 보인다. 앱은 service_role 키로만 접근.

secrets.toml
  [store]
  url = "https://<project>.supabase.co"
  key = "<service_role key>"
  master_key = "<임의 긴 문자열 — 바꾸면 기존 저장분을 못 읽는다>"

SQL (Supabase → SQL Editor 에서 한 번)
  create table if not exists portfolios (
    uid text primary key, blob text not null, updated_at timestamptz not null default now());
  alter table portfolios enable row level security;
"""
import base64
import hashlib
import json
from datetime import datetime, timezone

import requests
import streamlit as st

_T = 'portfolios'


def _cfg():
    try:
        s = st.secrets.get('store')
    except Exception:
        return None
    if not s or not s.get('url') or not s.get('key') or not s.get('master_key'):
        return None
    return s


def ready() -> bool:
    return _cfg() is not None


def _uid(email: str) -> str:
    return hashlib.sha256(email.strip().lower().encode()).hexdigest()


def _fernet(email: str):
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF
    mk = str(_cfg()['master_key']).encode()
    k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
             info=b'pf:' + email.strip().lower().encode()).derive(mk)
    return Fernet(base64.urlsafe_b64encode(k))


def _h(c, extra=None):
    h = {'apikey': c['key'], 'Authorization': f"Bearer {c['key']}", 'Content-Type': 'application/json'}
    h.update(extra or {})
    return h


def _url(c):
    return str(c['url']).rstrip('/') + f'/rest/v1/{_T}'


def load(email: str):
    """저장분 dict 또는 None(없음). 네트워크·복호화 실패는 예외 — 화면에서 '불러오기 실패'로 보여준다."""
    c = _cfg()
    r = requests.get(_url(c), params={'uid': f'eq.{_uid(email)}', 'select': 'blob,updated_at'},
                     headers=_h(c), timeout=6)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        return None
    d = json.loads(_fernet(email).decrypt(rows[0]['blob'].encode()).decode('utf-8'))
    d['_updated_at'] = rows[0].get('updated_at')
    return d


def save(email: str, obj: dict):
    c = _cfg()
    blob = _fernet(email).encrypt(json.dumps(obj, ensure_ascii=False).encode('utf-8')).decode()
    r = requests.post(_url(c), json=[{'uid': _uid(email), 'blob': blob, 'updated_at': datetime.now(timezone.utc).isoformat()}],
                      headers=_h(c, {'Prefer': 'resolution=merge-duplicates,return=minimal'}), timeout=6)
    r.raise_for_status()


def delete(email: str):
    c = _cfg()
    r = requests.delete(_url(c), params={'uid': f'eq.{_uid(email)}'}, headers=_h(c), timeout=6)
    r.raise_for_status()
