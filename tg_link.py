"""🤖 텔레그램 봇 계정 연결 (2026-11-12) — buza-bot account_link.py 와 짝.

표 account_links(uid=user_store._uid(email), code, code_expires, chat_id, linked_at, watch_sync) — 같은 Supabase([store]).
이메일 원문은 저장하지 않는다. 표가 아직 없으면(sql 미실행) status() 가 'no_table' 을 돌려 화면이 안내한다.
"""
import secrets
from datetime import datetime, timedelta, timezone

import requests

import user_store as _us

BOT = 'buza_alarm_bot'
_ALPH = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'      # 헷갈리는 0/O·1/I 제외


def _url():
    return _us._url(_us._cfg()).rsplit('/', 1)[0] + '/account_links'


def status(email: str) -> dict:
    """{'state': 'linked'|'pending'|'none'|'no_table'|'error', ...}"""
    try:
        c = _us._cfg()
        r = requests.get(_url(), params={'uid': f'eq.{_us._uid(email)}', 'select': 'chat_id,linked_at,code,code_expires,watch_sync'},
                         headers=_us._h(c), timeout=6)
        if r.status_code == 404 or 'account_links' in r.text and r.status_code >= 400:
            return {'state': 'no_table'}
        r.raise_for_status()
        rows = r.json()
        if not rows:
            return {'state': 'none'}
        row = rows[0]
        if row.get('chat_id'):
            return {'state': 'linked', **row}
        if row.get('code'):
            return {'state': 'pending', **row}
        return {'state': 'none'}
    except Exception as e:
        return {'state': 'error', 'why': f'{type(e).__name__}: {str(e)[:80]}'}


def new_code(email: str) -> str:
    code = ''.join(secrets.choice(_ALPH) for _ in range(8))
    c = _us._cfg()
    now = datetime.now(timezone.utc)
    r = requests.post(_url(), json=[{'uid': _us._uid(email), 'code': code,
                                     'code_expires': (now + timedelta(minutes=30)).isoformat(),
                                     'updated_at': now.isoformat()}],
                      headers=_us._h(c, {'Prefer': 'resolution=merge-duplicates,return=minimal'}), timeout=6)
    r.raise_for_status()
    return code


def link_url(code: str) -> str:
    return f'https://t.me/{BOT}?start=link_{code}'


def push_watch(email: str, syms: list):
    c = _us._cfg()
    r = requests.patch(_url(), params={'uid': f'eq.{_us._uid(email)}'},
                       json={'watch_sync': [str(s) for s in syms][:30],
                             'updated_at': datetime.now(timezone.utc).isoformat()},
                       headers=_us._h(c, {'Prefer': 'return=minimal'}), timeout=6)
    r.raise_for_status()


def unlink(email: str):
    c = _us._cfg()
    r = requests.delete(_url(), params={'uid': f'eq.{_us._uid(email)}'}, headers=_us._h(c), timeout=6)
    r.raise_for_status()
