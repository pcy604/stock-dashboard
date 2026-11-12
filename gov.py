# -*- coding: utf-8 -*-
"""🏛️ 경영실 데이터 층 (2026-11-12) — Supabase REST (user_store 와 같은 [store] 비밀값·service_role).

왜
  KPI·로드맵·결정·이슈·회의록이 채팅·문서·커밋에 흩어져 매번 다시 맞춰야 했다(차니 11-12).
  화면에서 언제든 고치고, **모든 수정은 DB 트리거가 전/후 그대로 gov_audit 에 남긴다**(앱이 지울 수 없음).

표 (SQL 은 docs/sql/gov.sql)
  gov_items       kind = kpi|roadmap|decision|issue|meeting 한 표. 삭제는 deleted=true(이력 보존)
  gov_kpi_weekly  (week=월요일, key) → value. source = auto(앱이 계산)|manual(사람 입력)
  gov_audit       변경 이력(append-only 트리거)
  usage_events    방문·탭 사용 — WAU·기능 사용률 측정(이메일 원문 없음, access.uid 해시)
"""
from __future__ import annotations

import datetime as _dt
import threading

import requests

API_VERSION = 1

KINDS = {
    'roadmap': ('🗺️ 로드맵', ['예정', '진행', '완료', '보류']),
    'decision': ('⚖️ 결정 로그', ['제안', '승인', '기각', '폐기']),
    'issue': ('🚨 이슈', ['열림', '조치 중', '종결']),
    'meeting': ('📝 회의록', ['예정', '완료']),
    'kpi': ('⚙️ KPI 정의', ['활성', '중지']),
}
DEPTS = ['이사회', '경영·전략', 'R&D', '운용', '리스크', '영업·마케팅']
MEETINGS = ['주간 리뷰', '월간 리뷰', '분기 이사회', '반기 리뷰', '연간 결산', '수시']

# 기본 KPI (2026-11-12 차니 합의) — key 는 코드가 자동값을 채울 때 쓰는 이름이라 바꾸지 않는다.
#   tier 회사 = 이사회가 보는 것, 부서 = 주간 스코어카드. better = up(클수록 좋음)|down. auto = 앱이 계산
DEFAULT_KPIS = [
    # key, 이름, 부서, tier, 단위, 목표, better, auto, 측정 방법
    ('wau', '★ 주간 활성 사용자(WAU)', '영업·마케팅', '회사', '명', 30, 'up', True, '대시보드 방문(소유자 제외) 7일 고유 + 봇 사용자 — usage_events'),
    ('lab_excess', '💰 랩 초과수익(원장 TWR − KODEX 200)', '운용', '회사', '%p', 0, 'up', True, '📒 실전 원장과 같은 계산(live/perf.py)'),
    ('clean_streak', '⚙️ 사람 개입 없는 무사고 연속 주', '경영·전략', '회사', '주', 12, 'up', True, '주간 운영 사고 0·오버라이드 0 인 주가 몇 주 연속인지'),
    ('lab_mdd', '⛔ 계좌 MDD', '리스크', '회사', '%', -20, 'up', True, '원장 TWR 고점 대비 최대 낙폭 — −20% 아래면 이사회 긴급 소집'),
    ('incidents', '운영 사고', '리스크', '부서', '건', 0, 'down', True, '그 주에 생긴 이슈 중 종류=사고'),
    ('overrides', '규칙 위반·오버라이드', '리스크', '부서', '건', 0, 'down', False, '사전 등록 규칙을 사람이 덮어쓴 횟수'),
    ('sector_max', '최대 업종 비중', '리스크', '부서', '%', 30, 'down', False, '토스 스냅샷 기준'),
    ('deposit_month', '이번 달 입금', '운용', '부서', '만원', 100, 'up', True, 'live/ledger.json 입금(월 100만원 원칙)'),
    ('ka_pass', '데이터 정답 점검 통과율', 'R&D', '부서', '%', 100, 'up', True, 'results/known_answers.json'),
    ('ci_success', '정기 실행(CI) 성공률 7일', 'R&D', '부서', '%', 99, 'up', True, 'GitHub Actions 최근 7일'),
    ('lead_time', '요청→배포 리드타임', 'R&D', '부서', '일', 2, 'down', False, '차니 요청이 배포 화면에 반영되기까지'),
    ('bot_users', '봇 가입자(누적)', '영업·마케팅', '부서', '명', 50, 'up', True, 'buza-bot users 표'),
    ('posts', '주간 게시 수', '영업·마케팅', '부서', '개', 7, 'up', False, '블로그·스레드·X·인스타 합'),
    ('reach', 'SNS·블로그 주간 도달', '영업·마케팅', '부서', '회', None, 'up', False, '각 플랫폼 통계 합(손 입력)'),
    ('channel_subs', '텔레그램 공개 채널 구독', '영업·마케팅', '부서', '명', None, 'up', False, '채널 관리자 화면'),
]


def week_of(d: _dt.date | None = None) -> _dt.date:
    d = d or (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) + _dt.timedelta(hours=9)).date()     # KST 기준 주
    return d - _dt.timedelta(days=d.weekday())


# ── REST ──────────────────────────────────────────────────────────────────
def _cfg():
    try:
        import user_store as _us
        c = _us._cfg()
    except Exception:
        return None
    if not c:
        return None
    base = str(c['url']).strip().rstrip('/')
    for suf in ('/rest/v1', '/rest'):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return {'base': base + '/rest/v1/', 'key': c['key']}


def ready() -> bool:
    return _cfg() is not None


def _h(c, prefer=None):
    h = {'apikey': c['key'], 'Content-Type': 'application/json'}
    if str(c['key']).startswith('eyJ'):
        h['Authorization'] = f"Bearer {c['key']}"
    if prefer:
        h['Prefer'] = prefer
    return h


def _req(method, table, params=None, body=None, prefer=None, timeout=8):
    c = _cfg()
    if c is None:
        raise RuntimeError('Secrets [store] 없음')
    r = requests.request(method, c['base'] + table, params=params, json=body,
                         headers=_h(c, prefer), timeout=timeout)
    if r.status_code >= 400:
        raise RuntimeError(f'{table} HTTP {r.status_code} {r.text[:160]}')
    return r


# ── 항목 ──────────────────────────────────────────────────────────────────
def items(kind: str | None = None, include_deleted=False) -> list[dict]:
    p = {'select': '*', 'order': 'id.asc'}
    if kind:
        p['kind'] = f'eq.{kind}'
    if not include_deleted:
        p['deleted'] = 'eq.false'
    return _req('GET', 'gov_items', p).json()


_ITEM_COLS = ('kind', 'title', 'body', 'status', 'dept', 'owner', 'period', 'due', 'progress', 'meta')


def save_item(row: dict, actor: str) -> dict:
    """id 있으면 수정, 없으면 추가. 바뀐 칸만 보내지 않아도 된다 — 트리거가 내용이 같으면 이력을 안 남긴다."""
    body = {k: row.get(k) for k in _ITEM_COLS if k in row}
    if isinstance(body.get('due'), _dt.date):
        body['due'] = body['due'].isoformat()
    body['updated_by'] = actor
    if row.get('id'):
        r = _req('PATCH', 'gov_items', {'id': f"eq.{int(row['id'])}"}, body, 'return=representation')
    else:
        r = _req('POST', 'gov_items', None, body, 'return=representation')
    out = r.json()
    return out[0] if out else {}


def delete_item(item_id: int, actor: str):
    """지우지 않고 숨긴다 — 이력과 되살리기를 위해."""
    _req('PATCH', 'gov_items', {'id': f'eq.{int(item_id)}'}, {'deleted': True, 'updated_by': actor})


def restore_item(item_id: int, actor: str):
    _req('PATCH', 'gov_items', {'id': f'eq.{int(item_id)}'}, {'deleted': False, 'updated_by': actor})


def seed_kpis(actor='system') -> int:
    """KPI 정의가 하나도 없을 때만 기본값을 넣는다."""
    if items('kpi', include_deleted=True):
        return 0
    rows = [{'kind': 'kpi', 'title': n, 'dept': d, 'status': '활성', 'body': how, 'updated_by': actor,
             'meta': {'key': k, 'tier': t, 'unit': u, 'target': tg, 'better': b, 'auto': a}}
            for k, n, d, t, u, tg, b, a, how in DEFAULT_KPIS]
    _req('POST', 'gov_items', None, rows, 'return=minimal')
    return len(rows)


# ── KPI 주간 값 ────────────────────────────────────────────────────────────
def kpi_values(weeks: int = 12) -> list[dict]:
    since = week_of() - _dt.timedelta(weeks=weeks - 1)
    return _req('GET', 'gov_kpi_weekly', {'select': '*', 'week': f'gte.{since.isoformat()}',
                                          'order': 'week.asc'}).json()


def put_kpi(week: _dt.date, key: str, value, note: str = '', source: str = 'manual', actor: str = 'system'):
    body = [{'week': week.isoformat(), 'key': key, 'value': None if value is None else float(value),
             'note': note or '', 'source': source, 'updated_by': actor}]
    _req('POST', 'gov_kpi_weekly', {'on_conflict': 'week,key'}, body, 'resolution=merge-duplicates,return=minimal')


# ── 이력 ──────────────────────────────────────────────────────────────────
def audit(limit: int = 300, tbl: str | None = None, row_key: str | None = None) -> list[dict]:
    p = {'select': '*', 'order': 'at.desc', 'limit': str(limit)}
    if tbl:
        p['tbl'] = f'eq.{tbl}'
    if row_key:
        p['row_key'] = f'eq.{row_key}'
    return _req('GET', 'gov_audit', p).json()


_SKIP = {'updated_at', 'updated_by', 'created_at'}


def diff(before: dict | None, after: dict | None) -> str:
    """사람이 읽는 한 줄 — '상태: 열림 → 종결 · 진행률: 40 → 100'."""
    if before is None:
        return '추가 — ' + str((after or {}).get('title') or (after or {}).get('value') or '')[:60]
    if after is None:
        return '삭제'
    parts = []
    for k in sorted(set(before) | set(after)):
        if k in _SKIP:
            continue
        a, b = before.get(k), after.get(k)
        if a != b:
            if k == 'deleted':
                parts.append('🗑 숨김' if b else '♻️ 되살림')
                continue
            sa, sb = str(a if a is not None else '-'), str(b if b is not None else '-')
            if len(sa) > 40 or len(sb) > 40:
                parts.append(f'{k}: (내용 수정)')
            else:
                parts.append(f'{k}: {sa} → {sb}')
    return ' · '.join(parts) or '(변화 없음)'


# ── 사용량 ────────────────────────────────────────────────────────────────
def log_usage(uid: str, event: str, tab: str = ''):
    """방문·탭 기록 — 실패해도 화면을 막지 않는다(백그라운드)."""
    if not ready():
        return

    def _go():
        try:
            _req('POST', 'usage_events', None, [{'uid': uid, 'event': event, 'tab': tab or ''}], 'return=minimal', timeout=4)
        except Exception:
            pass
    threading.Thread(target=_go, daemon=True).start()


def usage(days: int = 28) -> list[dict]:
    since = (_dt.datetime.now(_dt.timezone.utc).replace(tzinfo=None) - _dt.timedelta(days=days)).isoformat()
    return _req('GET', 'usage_events', {'select': 'at,uid,event,tab', 'at': f'gte.{since}',
                                        'order': 'at.asc', 'limit': '20000'}).json()


def bot_users() -> int | None:
    try:
        r = _req('GET', 'users', {'select': 'chat_id'}, prefer='count=exact')
        cr = r.headers.get('Content-Range', '')
        return int(cr.split('/')[-1]) if '/' in cr and cr.split('/')[-1].isdigit() else len(r.json())
    except Exception:
        return None
