"""
pipeline_health.py — 데이터 파이프라인 신선도 감시 + 텔레그램 경보
─────────────────────────────────────────────────────────────────
배경: daily-refresh의 모든 스텝이 continue-on-error라 스크립트가 죽어도
Actions는 초록불 → 성적표 데이터가 몇 주씩 조용히 멈춘 사고 재발 방지.
(실제로 2026-06-14~07-13 한 달간 screener/페이퍼 기록이 정지했는데 아무도 몰랐음)

동작: 핵심 산출물의 '내부 날짜'(파일 mtime 아님 — CI 체크아웃 시각이라 무의미)를
읽어 허용 나이를 넘으면 텔레그램 경보 + 콘솔 출력. 항상 exit 0 (경보가 빌드를 죽이면 안 됨).

daily-refresh.yml 마지막(커밋 직전)에 실행.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
from datetime import datetime
from pathlib import Path

# (파일, 내부 날짜 추출 함수, 허용 나이 일수)
def _screener_date(p):
    return json.loads(p.read_text(encoding='utf-8')).get('date')

def _paper_date(p):
    trades = json.loads(p.read_text(encoding='utf-8')).get('trades', [])
    return max((t.get('log_date') for t in trades), default=None)

def _wp_date(p):
    return (json.loads(p.read_text(encoding='utf-8')).get('p10') or {}).get('date')

def _generic_date(p):
    d = json.loads(p.read_text(encoding='utf-8'))
    for k in ('date', 'updated', 'generated'):
        v = d.get(k)
        if v:
            return str(v)[:10]
    return None

CHECKS = [
    ('results/screener_latest.json',  _screener_date, 4,  '주봉 스크리너(weekly_run)'),
    ('results/paper_trades.json',     _paper_date,    9,  '페이퍼 트레이딩 기록'),
    ('results/weekly_portfolio.json', _wp_date,       9,  '주간 추천 포트폴리오'),
    ('results/canslim_latest.json',   _generic_date,  4,  'CANSLIM(KR)'),
    ('results/value_kr.json',         _generic_date,  4,  '가치 스냅샷(DART)'),
]

# 2종 감시: 위는 '멈춤'(날짜 안 늙음), 아래는 '조용한 저하'(매일 갱신되지만
# 내용이 나빠지는 것 — 예: 소스 차단으로 대부분 종목이 데이터수집 실패)
DEGRADE_MAX_FAIL_PCT = 30

def _screener_fail_pct(p):
    return json.loads(p.read_text(encoding='utf-8')).get('fetch_fail_pct', {})


def check():
    today = datetime.now()
    stale = []
    for path, getter, max_days, label in CHECKS:
        p = Path(path)
        if not p.exists():
            stale.append(f"{label}: 파일 없음 ({path})")
            continue
        try:
            ds = getter(p)
            if not ds:
                stale.append(f"{label}: 날짜 필드 없음")
                continue
            age = (today - datetime.strptime(ds[:10], '%Y-%m-%d')).days
            if age > max_days:
                stale.append(f"{label}: {age}일 정지 (마지막 {ds[:10]}, 허용 {max_days}일)")
        except Exception as e:
            stale.append(f"{label}: 검사 실패 ({e})")

    p = Path('results/screener_latest.json')
    if p.exists():
        try:
            for market, pct in _screener_fail_pct(p).items():
                if pct > DEGRADE_MAX_FAIL_PCT:
                    stale.append(f"주봉 스크리너[{market}]: 데이터수집 실패율 {pct}% "
                                 f"(허용 {DEGRADE_MAX_FAIL_PCT}%) — 파일은 갱신되나 내용 저하, 소스 차단 의심")
        except Exception as e:
            stale.append(f"주봉 스크리너 실패율 검사 실패 ({e})")
    return stale


def main():
    stale = check()
    if not stale:
        print("✅ 파이프라인 신선도 정상 — 전 산출물이 허용 나이 이내")
        return
    msg = "🚨 [screener] 데이터 파이프라인 정지 감지\n" + "\n".join(f"· {s}" for s in stale) \
          + "\n→ GitHub Actions daily-refresh 로그에서 해당 스텝 에러 확인 필요"
    print(msg)
    try:
        import config
        from telegram_notifier import send_message
        if config.TELEGRAM_ENABLED:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
            print("(텔레그램 경보 발송됨)")
    except Exception as e:
        print(f"(텔레그램 발송 실패: {e})")


if __name__ == '__main__':
    main()
