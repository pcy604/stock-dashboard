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
    h = {'apikey': c['key'], 'Content-Type': 'application/json'}
    if str(c['key']).startswith('eyJ'):      # 옛 JWT 키만 Bearer 로 — 새 sb_secret_ 키는 apikey 헤더만 받는다
        h['Authorization'] = f"Bearer {c['key']}"
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


def ping():
    """(ok, 사람이 읽을 사유) — 화면에서 '왜 저장이 안 되나'를 바로 보이게(2026-10-21). 비밀값은 출력하지 않는다."""
    c = _cfg()
    if c is None:
        try:
            s = st.secrets.get('store')
        except Exception:
            s = None
        if not s:
            return False, 'Secrets 에 [store] 칸이 없습니다'
        miss = [k for k in ('url', 'key', 'master_key') if not s.get(k)]
        return False, f"[store] 에 빈 항목: {', '.join(miss)}"
    try:
        r = requests.get(_url(c), params={'select': 'uid', 'limit': 1}, headers=_h(c), timeout=6)
    except Exception as e:
        return False, f'DB 연결 실패: {type(e).__name__}'
    if r.status_code == 200:
        return True, '정상'
    hint = {401: 'key 가 틀렸거나 anon 키입니다 — service_role 키를 넣으세요',
            404: 'portfolios 표가 안 보입니다 — SQL 실행 여부, url 프로젝트, Data API 노출 설정 확인'}.get(r.status_code, '')
    return False, f'HTTP {r.status_code} {hint} {r.text[:80]}'.strip()
