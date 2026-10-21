"""bot_watchdog.py — 부자알람(buza-bot)이 '아예 안 도는' 고장을 바깥에서 잡는다 (2026-10-21).
─────────────────────────────────────────────────────────────────
봇 안의 감시(buza-bot health.py)는 봇이 돌아야 울린다. 그런데 가장 나쁜 고장은 봇이 안 도는 것이다:
  · 비공개 레포 Actions 무료 한도(월 2,000분) 소진 → 크론·웹훅 실행이 전부 멈춤
  · 크론 정지·워크플로 비활성화·러너 장애
이때 사용자는 명령을 보내도 침묵만 받는다. 그래서 감시를 **이 공개 레포**(Actions 무료)에 둔다.

본다: buza-bot 의 마지막 성공 실행 시각, job_state.json 의 last_job_run(주기작업 6시간 게이트).
알린다: 기준을 넘으면 운영자 텔레그램(TELEGRAM_TOKEN·TELEGRAM_CHAT_ID — 이 레포의 기존 알림 채널).
필요: 레포 비밀 BUZA_READ_TOKEN — buza-bot 만 고른 fine-grained 토큰(Actions: Read · Contents: Read).
      없으면 경고만 찍고 성공으로 끝난다(소음 금지).
"""
import json
import os
import sys
from base64 import b64decode
from datetime import datetime, timezone

import requests

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

REPO = 'pcy604/buza-bot'
RUN_STALE_H = 8      # 크론 3시간 + 무료 크론 지연(실측 최대 105분) 여유
JOB_STALE_H = 14     # 주기작업 게이트 6시간 × 2 + 여유


def _age_h(iso):
    d = datetime.fromisoformat(iso.replace('Z', '+00:00'))
    return (datetime.now(timezone.utc) - d).total_seconds() / 3600


def check(tok):
    h = {'Authorization': f'Bearer {tok}', 'Accept': 'application/vnd.github+json'}
    problems = []
    runs = requests.get(f'https://api.github.com/repos/{REPO}/actions/workflows/run.yml/runs',
                        params={'per_page': 30}, headers=h, timeout=30)
    runs.raise_for_status()
    rs = runs.json().get('workflow_runs') or []
    ok = [r for r in rs if r.get('conclusion') == 'success']
    if not ok:
        problems.append('최근 30회 실행 중 성공 0회')
    else:
        a = _age_h(ok[0]['updated_at'])
        if a > RUN_STALE_H:
            problems.append(f'마지막 성공 실행이 {a:.0f}시간 전 (기준 {RUN_STALE_H}시간)')
    bad = [r for r in rs[:6] if r.get('conclusion') == 'failure']
    if len(bad) >= 3:
        problems.append(f'최근 6회 중 {len(bad)}회 실패')
    js = requests.get(f'https://api.github.com/repos/{REPO}/contents/job_state.json', headers=h, timeout=30)
    if js.ok:
        st = json.loads(b64decode(js.json()['content']).decode('utf-8'))
        if st.get('last_job_run'):
            a = _age_h(st['last_job_run'])
            if a > JOB_STALE_H:
                problems.append(f'주기작업(공시 감시·영상 갱신)이 {a:.0f}시간째 안 돎 (기준 {JOB_STALE_H}시간)')
        stuck = {k: v for k, v in (st.get('health') or {}).items() if v.get('streak', 0) >= 3}
        for k, v in list(stuck.items())[:4]:
            problems.append(f'{k} {v["streak"]}회 연속 실패 — {str(v.get("last", ""))[:70]}')
    else:
        problems.append(f'job_state.json 읽기 실패 (HTTP {js.status_code})')
    return problems, (rs[0]['html_url'] if rs else f'https://github.com/{REPO}/actions')


def main():
    tok = os.environ.get('BUZA_READ_TOKEN', '').strip()
    if not tok:
        print('::warning::BUZA_READ_TOKEN 미설정 — 부자알람 감시를 건너뜀 (tools/bot_watchdog.py 상단 참고)')
        return 0
    try:
        problems, url = check(tok)
    except Exception as e:
        problems, url = [f'GitHub API 조회 실패: {str(e)[:80]}'], f'https://github.com/{REPO}/actions'
    if not problems:
        print('✅ 부자알람 정상')
        return 0
    text = ('🐕 <b>부자알람 감시</b> — 봇이 멈췄을 수 있어요\n\n' + '\n'.join(f'• {p}' for p in problems) +
            f'\n\n<a href="{url}">Actions 열기</a>')
    print(text)
    tg_tok, chat = os.environ.get('TELEGRAM_TOKEN', ''), os.environ.get('TELEGRAM_CHAT_ID', '')
    if tg_tok and chat:
        from telegram_notifier import send_message
        send_message(tg_tok, chat, text)
    print('::error::부자알람 이상 — ' + ' / '.join(problems))
    return 1


if __name__ == '__main__':
    sys.exit(main())
