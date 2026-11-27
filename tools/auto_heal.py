"""자가 복구 (2026-11-27) — 감시가 '멈춤'을 찾으면 사람을 기다리지 않고 그 산출물을 만드는 워크플로를 다시 돌린다.

왜: 데이터 점검 빨간불이 몇 주씩 떠 있었다. 감시는 찾기만 하고 고치는 건 사람이 해야 했다.
규칙:
  - data_freshness 에서 state != ok 인 산출물 → job 문자열에서 실제 워크플로 이름을 뽑는다.
  - '수동'·research-* (48분짜리 등 비싼 것)·자기 자신은 자동으로 돌리지 않는다 → 목록만 남긴다.
  - 같은 워크플로는 20시간에 1번, 하루 최대 MAX_PER_RUN 개. 기록 = results/auto_heal.json.
  - 재실행해도 이틀 연속 안 풀리면 'escalate' 로 표시 → 사람 작업(텔레그램은 platform_watch 가 이미 보낸다).
"""
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
LOG = ROOT / 'results/auto_heal.json'
WF_DIR = ROOT / '.github/workflows'
REPO = os.environ.get('GITHUB_REPOSITORY', 'pcy604/stock-dashboard')
MAX_PER_RUN = 3
COOLDOWN_H = 20
NEVER = {'platform-watch'}                      # 자기 자신
EXPENSIVE = re.compile(r'^research-')           # 사람이 고르는 무거운 재계산
INPUTS = {'daily-refresh': {'force_monday': 'true'}}   # 놓친 월요일 단계까지 같이 복구


def workflows_in(job: str) -> list[str]:
    if not job or job.startswith('수동'):
        return []
    have = {p.stem for p in WF_DIR.glob('*.yml')}
    return [w for w in re.findall(r'[a-z][a-z0-9-]+', job) if w in have and w not in NEVER]


def plan(statuses, log, now=None):
    now = now or time.time()
    runs = log.get('runs', {})
    todo, manual = [], []
    for r in statuses:
        if r.get('state') == 'ok':
            continue
        wfs = workflows_in(r.get('job', ''))
        if not wfs:
            manual.append(r.get('label') or r.get('path'))
            continue
        for w in wfs:
            if EXPENSIVE.match(w):
                manual.append(f"{r.get('label') or r.get('path')} ← {w}(수동)")
            elif w not in todo and now - runs.get(w, {}).get('at', 0) > COOLDOWN_H * 3600:
                todo.append(w)
    return todo[:MAX_PER_RUN], manual


def dispatch(wf: str) -> bool:
    tok = os.environ.get('GITHUB_TOKEN')
    if not tok:
        print(f'  (GITHUB_TOKEN 없음 — {wf} 재실행 건너뜀)')
        return False
    r = requests.post(f'https://api.github.com/repos/{REPO}/actions/workflows/{wf}.yml/dispatches',
                      headers={'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'},
                      json={'ref': 'main', 'inputs': INPUTS.get(wf, {})}, timeout=20)
    print(f'  {wf}: HTTP {r.status_code}')
    return r.status_code == 204


def main():
    import data_freshness as df
    log = json.loads(LOG.read_text(encoding='utf-8')) if LOG.exists() else {}
    todo, manual = plan(df.statuses(), log)
    runs = log.setdefault('runs', {})
    for w in todo:
        prev = runs.get(w, {})
        ok = dispatch(w)
        runs[w] = {'at': time.time(), 'date': time.strftime('%Y-%m-%d'), 'ok': ok,
                   'tries': prev.get('tries', 0) + 1 if time.time() - prev.get('at', 0) < 3 * 86400 else 1}
    log['escalate'] = sorted(w for w, v in runs.items() if v.get('tries', 0) >= 2)
    log['manual'] = manual
    log['checked'] = time.strftime('%Y-%m-%d %H:%M')
    LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding='utf-8')
    print(f'재실행 {todo or "없음"} · 사람 작업 {len(manual)} · 반복 실패 {log["escalate"] or "없음"}')


if __name__ == '__main__':
    main()
