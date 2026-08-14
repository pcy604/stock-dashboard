"""
portfolio_store.py — 보유종목 영구 저장 (로컬 파일 ↔ GitHub 저장소)
──────────────────────────────────────────────────────────────────
왜 필요한가:
  Streamlit Cloud 컨테이너의 디스크는 휘발성이다. 웹에서 보유종목을 추가하면
  "저장됐습니다"가 뜨지만 서버가 재시작되는 순간 사라진다. 포트폴리오를
  '나를 증명하는 트랙레코드'로 쓰려면 기록이 남아야 하므로, 이 저장소는
  results/*.json 과 같은 방식 — **깃 저장소 자체를 DB로** 쓴다.

백엔드 선택 (자동):
  · GITHUB_TOKEN 이 있으면 → GitHub Contents API 로 커밋 (영구)
  · 없으면            → 로컬 파일 (기존 동작, 개발·오프라인용)

토큰은 코드가 만들지 않는다. 사용자가 직접 발급해 Streamlit Secrets 에 넣는다.
(설정 방법은 README_PORTFOLIO.md 참고)
"""
from __future__ import annotations

import base64
import json
import os
from datetime import datetime
from pathlib import Path

import requests

PATH = 'data/portfolio.json'
LOCAL = Path(__file__).resolve().parent / PATH
API = 'https://api.github.com'
DEFAULT_REPO = 'pcy604/stock-dashboard'
TIMEOUT = 12


# ── 설정 ───────────────────────────────────────────────────────────
def _cfg(name: str, secrets=None, default: str = '') -> str:
    """Streamlit Secrets → 환경변수 → 로컬파일 순. secrets 는 st.secrets 를 넘긴다."""
    if secrets is not None:
        try:
            if name in secrets:
                return str(secrets[name])
        except Exception:
            pass
    if os.environ.get(name):
        return os.environ[name]
    f = Path(__file__).resolve().parent / 'data' / f'.{name.lower()}'
    if f.exists():
        try:
            return f.read_text(encoding='utf-8').strip()
        except Exception:
            pass
    return default


def backend(secrets=None) -> str:
    """'github' 이면 영구 저장, 'local' 이면 이 컨테이너가 살아있는 동안만."""
    return 'github' if _cfg('GITHUB_TOKEN', secrets) else 'local'


def _repo(secrets=None) -> str:
    return _cfg('GITHUB_REPO', secrets, DEFAULT_REPO)


def _headers(token: str) -> dict:
    return {'Authorization': f'Bearer {token}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'}


# ── 읽기 ───────────────────────────────────────────────────────────
def _parse(raw: str) -> list:
    try:
        return json.loads(raw).get('positions', [])
    except Exception:
        return []


def load(secrets=None) -> list:
    """보유종목 목록. 원격이 있으면 원격을 진실로 본다(다른 기기에서 넣은 것도 보이게)."""
    token = _cfg('GITHUB_TOKEN', secrets)
    if token:
        try:
            r = requests.get(f'{API}/repos/{_repo(secrets)}/contents/{PATH}',
                             headers=_headers(token), timeout=TIMEOUT)
            if r.status_code == 200:
                return _parse(base64.b64decode(r.json()['content']).decode('utf-8'))
            if r.status_code == 404:
                return []                      # 아직 한 번도 저장 안 함
        except Exception:
            pass                               # 네트워크 실패 → 로컬로 폴백
    if LOCAL.exists():
        try:
            return _parse(LOCAL.read_text(encoding='utf-8'))
        except Exception:
            return []
    return []


# ── 쓰기 ───────────────────────────────────────────────────────────
def save(positions: list, secrets=None, note: str = '') -> tuple[bool, str]:
    """저장. 반환 (영구저장 여부, 사용자에게 보여줄 메시지).

    로컬에는 항상 쓴다(같은 세션 안에서 즉시 반영). 토큰이 있으면 원격 커밋까지 한다.
    """
    payload = json.dumps(
        {'updated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'positions': positions},
        ensure_ascii=False, indent=2)
    try:
        LOCAL.parent.mkdir(parents=True, exist_ok=True)
        LOCAL.write_text(payload, encoding='utf-8')
    except Exception as e:
        return False, f'로컬 저장 실패: {e}'

    token = _cfg('GITHUB_TOKEN', secrets)
    if not token:
        return False, ('이 서버에만 저장됐습니다 — 재시작하면 사라집니다. '
                       '영구 저장은 Secrets 에 GITHUB_TOKEN 등록 후 가능합니다.')
    try:
        repo, url = _repo(secrets), f'{API}/repos/{_repo(secrets)}/contents/{PATH}'
        h = _headers(token)
        sha = None
        g = requests.get(url, headers=h, timeout=TIMEOUT)
        if g.status_code == 200:
            sha = g.json().get('sha')          # 기존 파일 갱신엔 sha 가 필요
        body = {'message': f"portfolio: {note or '보유종목 갱신'} "
                           f"{datetime.now().strftime('%Y-%m-%d %H:%M')}",
                'content': base64.b64encode(payload.encode('utf-8')).decode('ascii')}
        if sha:
            body['sha'] = sha
        p = requests.put(url, headers=h, json=body, timeout=TIMEOUT)
        if p.status_code in (200, 201):
            return True, f'✅ {repo} 에 커밋 — 서버가 재시작돼도 남습니다.'
        if p.status_code == 409:
            return False, '⚠️ 다른 기기에서 먼저 저장했습니다. 새로고침 후 다시 시도하세요.'
        if p.status_code in (401, 403):
            return False, '⚠️ GITHUB_TOKEN 권한 부족 — contents:write 스코프가 필요합니다.'
        return False, f'⚠️ 원격 저장 실패 (HTTP {p.status_code}) — 이 서버에만 남았습니다.'
    except Exception as e:
        return False, f'⚠️ 원격 저장 실패({type(e).__name__}) — 이 서버에만 남았습니다.'


def status(secrets=None) -> dict:
    """화면에 '지금 어디에 저장되는가'를 정직하게 보여주기 위한 정보."""
    b = backend(secrets)
    return {
        'backend': b,
        'permanent': b == 'github',
        'where': f'{_repo(secrets)} · {PATH}' if b == 'github' else f'이 서버의 {PATH}',
        'label': ('🟢 영구 저장 켜짐' if b == 'github'
                  else '🔴 임시 저장 — 서버 재시작 시 사라짐'),
    }
