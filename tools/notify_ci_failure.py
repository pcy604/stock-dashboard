"""
notify_ci_failure.py — 잡이 실패했다는 사실 자체를 텔레그램으로 보낸다.
─────────────────────────────────────────────────────────────────
배경(2026-10-03): daily-refresh 가 17일간 매일 실패했는데 아무도 몰랐다.
감시 장치가 3개나 있었는데 전부 구조적으로 못 보는 자리에 있었다.

  · pipeline_health.py      — 커밋 '앞'에서 러너 로컬 파일을 본다. 방금 생성한
                              파일이라 항상 신선 → "✅ 정상". 푸시 실패는 원리적
                              으로 볼 수 없다.
  · tools/check_freshness_ci.py — 커밋 '뒤' 스텝. 커밋이 exit 1 이면 스킵된다.
                              조용한 고장 차단기가 조용한 고장 때 안 돈다.
  · push_with_retry 안 텔레그램 — 함수 속 heredoc. 깨져도 `|| true` 가 삼킨다.
                              실제 실패 로그에 발송 흔적이 한 줄도 없었다.

교훈: **'산출물이 신선한가'를 보는 감시는 이 고장을 영원히 못 잡는다** —
러너 안에서는 항상 신선하니까. 그래서 이 스크립트는 산출물을 보지 않는다.
`if: failure()` 로만 실행되며, "잡이 실패했다"는 사실과 로그 링크만 보낸다.
위 세 구멍 어디에도 걸리지 않는다.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os


def main():
    wf  = os.environ.get('GITHUB_WORKFLOW', 'workflow')
    rid = os.environ.get('GITHUB_RUN_ID', '')
    repo = os.environ.get('GITHUB_REPOSITORY', '')
    url = f"https://github.com/{repo}/actions/runs/{rid}" if repo and rid else '(로그 URL 없음)'

    msg = (f"🚨 [screener] {wf} 실행 실패\n"
           f"이번 실행 산출물이 origin 에 반영되지 않았다 — "
           f"다음 성공까지 화면 데이터가 멈춘다.\n\n"
           f"로그: {url}")
    print(msg)
    try:
        import config
        from telegram_notifier import send_message
        if not config.TELEGRAM_ENABLED:
            print('(TELEGRAM_ENABLED=False — 발송 생략)')
            return
        send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
        print('(텔레그램 경보 발송됨)')
    except Exception as e:
        # 여기서 죽어도 잡은 이미 실패다. 다만 '왜 알림이 안 왔는지'는 남겨야 한다.
        print(f'(텔레그램 발송 실패: {e})')


if __name__ == '__main__':
    main()
