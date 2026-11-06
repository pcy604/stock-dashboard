# -*- coding: utf-8 -*-
"""배포 빌드 확인 (2026-11-06)

사고: 배포 서버가 10-31 무렵 저장소 상태에 멈춘 채 일주일 가까이 옛 화면을 보여 줬다.
실화면 점검(keepalive)은 '예외가 없나'만 봐서 7/7 초록불이었고, 그동안 '표 정렬 No. 51·66 · 원장 30만원 안 보임 ·
AXTI 분기 없음'을 코드 탓으로 알고 고쳤다. 재부팅 한 번에 전부 풀렸다.

→ 화면 맨 아래에 '배포 빌드 <sha> · 커밋 <UTC 시각>' 을 찍고, keepalive 가 그것을 GitHub main 과 대조한다.
   main 에 이 빌드보다 새 커밋이 생긴 지 GRACE_MIN 분이 넘었는데 화면이 그대로면 '배포 정지' 로 실패·텔레그램.
"""
import os
import re
import subprocess
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
GRACE_MIN = 45                     # Streamlit Cloud 는 보통 푸시 몇 분 안에 다시 띄운다
STAMP_RE = re.compile(r'배포 빌드 ([0-9a-f]{7,40}) · 커밋 (\d{4}-\d\d-\d\d \d\d:\d\d) UTC')


def local_build(root: str = ROOT) -> dict:
    """이 서버에 깔린 코드의 커밋 {sha, ts(UTC epoch), at('YYYY-MM-DD HH:MM')} — 모르면 {}."""
    try:
        out = subprocess.run(['git', '-C', root, 'log', '-1', '--format=%H %ct'],
                             capture_output=True, text=True, timeout=5).stdout.split()
        if len(out) == 2:
            ts = int(out[1])
            return dict(sha=out[0], ts=ts, at=datetime.fromtimestamp(ts, timezone.utc).strftime('%Y-%m-%d %H:%M'))
    except Exception:
        pass
    try:                                    # git 실행 파일이 없을 때 — 시각은 모르지만 sha 는 읽는다
        g = os.path.join(root, '.git')
        head = open(os.path.join(g, 'HEAD')).read().strip()
        if head.startswith('ref:'):
            ref = head.split()[1]
            p = os.path.join(g, ref)
            if os.path.exists(p):
                return dict(sha=open(p).read().strip())
            for line in open(os.path.join(g, 'packed-refs')):
                if line.strip().endswith(ref):
                    return dict(sha=line.split()[0])
        elif re.fullmatch(r'[0-9a-f]{40}', head):
            return dict(sha=head)
    except Exception:
        pass
    return {}


def stamp(b: dict) -> str:
    """화면에 찍는 문구 — keepalive 가 STAMP_RE 로 읽는다. 바꾸면 둘 다 바꾼다(테스트가 대조)."""
    if not b.get('sha'):
        return '배포 빌드 - (git 정보 없음)'
    return f"배포 빌드 {b['sha'][:12]} · 커밋 {b.get('at', '-')} UTC"


def parse_stamp(text: str):
    m = STAMP_RE.search(text or '')
    if not m:
        return None
    ts = datetime.strptime(m.group(2), '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc).timestamp()
    return dict(sha=m.group(1), ts=int(ts), at=m.group(2))


def lag_verdict(deployed: dict, main_commits, now_ts: float, grace_min: int = GRACE_MIN) -> dict:
    """deployed = {sha, ts} · main_commits = [(sha, ct), ...] 최신이 앞(git log 순서).
    배포보다 새 main 커밋 중 가장 오래된 것이 grace 를 넘겼으면 stale."""
    if not deployed or not deployed.get('sha'):
        return dict(ok=False, why='화면에 배포 빌드 표시가 없다')
    sha = deployed['sha']
    newer = []
    for s, ct in main_commits:
        if s.startswith(sha):
            break
        newer.append((s, int(ct)))
    else:                                   # main 최근 목록에 이 빌드가 없다 — 시각으로 판정
        newer = [(s, int(ct)) for s, ct in main_commits if int(ct) > int(deployed.get('ts') or 0)]
        if not deployed.get('ts'):
            return dict(ok=False, why=f'배포 빌드 {sha[:7]} 가 main 최근 {len(main_commits)}개 커밋에 없다')
    if not newer:
        return dict(ok=True, why='최신 main 과 같다', behind=0, lag_min=0)
    lag = (now_ts - min(ct for _, ct in newer)) / 60
    ok = lag <= grace_min
    return dict(ok=ok, behind=len(newer), lag_min=round(lag, 1),
                why=(f'main 보다 커밋 {len(newer)}개 뒤 · 가장 오래된 새 커밋이 {lag:.0f}분 전'
                     + ('' if ok else f' — {grace_min}분 넘게 반영 안 됨(배포 정지 의심 → share.streamlit.io 에서 Reboot)')))
