"""
data_freshness.py — 데이터 산출물 신선도 레지스트리 (단일 진실 원천)
──────────────────────────────────────────────────────────────────
왜 만들었나 (2026-08-13):
  results/returns.json 이 07-26에 멈춰 있는데 18일간 아무도 몰랐다. 원인이 셋 겹쳤다.
    1) weekly-profile.yml 의 `git add` 가 seasonality·mdd 만 넣고 returns 를 빠뜨림
    2) pipeline_health.py 의 감시 목록에도 그 셋이 없었음 (감시 사각지대)
    3) 대시보드 푸터가 파일 mtime(=클라우드 체크아웃 시각)을 '데이터 갱신일'로 표시
       → 18일 지난 데이터가 '어제 갱신'으로 보임
  같은 사고가 06-27→07-26 에도 있었고 그때는 손으로만 고쳤다(커밋 5f459fa). 그래서 재발했다.

설계 원칙:
  · 목록은 **여기 한 곳**에만 둔다. 대시보드(표시)와 pipeline_health(경보)가 같은 걸 읽는다.
    새 산출물을 여기 등록하면 화면 표기와 정지 경보가 동시에 붙는다 — 사각지대가 구조적으로 안 생긴다.
  · 날짜는 **파일 내부 날짜**만 쓴다. mtime 은 CI 체크아웃 시각이라 의미가 없다.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent


# ── 날짜 추출기 ────────────────────────────────────────────────────
def _key(*names):
    def get(d):
        for n in names:
            v = d.get(n)
            if v:
                return str(v)[:10]
        return None
    return get


def _paper_max_log(d):
    """원장은 created(시작일)가 아니라 마지막 기록일이 신선도다."""
    return max((t.get('log_date') for t in d.get('trades', []) if t.get('log_date')),
               default=None)


# ── 레지스트리 ─────────────────────────────────────────────────────
#   path        : results/ 하위 경로
#   label       : 사람이 읽는 이름
#   cycle       : 갱신 주기(사람 읽는 말)
#   max_age     : 이 일수를 넘으면 '정지'로 본다 (주기 + 여유)
#   producer    : 이 파일을 만드는 스크립트
#   job         : 그 스크립트를 돌리는 자동화 (없으면 수동)
#   used_by     : 이 데이터를 쓰는 화면 — "이 숫자가 언제 것인가"를 화면에 붙이는 근거
#   getter      : 파일 내부 날짜 추출
SOURCES = [
    dict(path='results/screener_latest.json', label='주봉 신호 스크리너',
         cycle='매일 06:00 (평일)', max_age=4, producer='weekly_run.py',
         job='daily-refresh', used_by='🔥 상승 상위 · 💼 포트폴리오',
         getter=_key('date')),
    dict(path='results/perf_latest.json', label='월간 성과 · 현재 신호',
         cycle='매일 06:00 (평일)', max_age=4, producer='perf_run.py',
         job='daily-refresh', used_by='🔥 상승 상위',
         getter=_key('date')),
    dict(path='results/canslim_latest.json', label='CANSLIM (KR)',
         cycle='매일 06:00 (평일)', max_age=4, producer='canslim_run.py',
         job='daily-refresh', used_by='🏆 CANSLIM · 🔥 상승 상위',
         getter=_key('date')),
    dict(path='results/canslim_us_latest.json', label='CANSLIM (US)',
         cycle='매일 06:00 (평일)', max_age=4, producer='canslim_us_run.py',
         job='daily-refresh', used_by='🏆 CANSLIM',
         getter=_key('date', 'generated')),
    dict(path='results/value_kr.json', label='가치 스냅샷 (DART 공식)',
         cycle='매일 06:00 (평일)', max_age=4, producer='ingest_dart.py → value_export.py',
         job='daily-refresh', used_by='💎 가치 발굴',
         getter=_key('generated')),
    # ★ 2026-08-13 추가 — 여기 없어서 18일 정지를 놓쳤다
    dict(path='results/returns.json', label='기간 수익률 (1주~1년·YTD)',
         cycle='주 1회 (일 08:00)', max_age=9, producer='screen_precompute.py',
         job='weekly-profile', used_by='🔥 상승 상위 (상승률 전체)',
         getter=_key('date')),
    dict(path='results/seasonality.json', label='계절성 (월별 승률)',
         cycle='주 1회 (일 08:00)', max_age=9, producer='screen_precompute.py',
         job='weekly-profile', used_by='🔥 상승 상위 (계절성 열·타이밍 필터)',
         getter=_key('date')),
    dict(path='results/mdd.json', label='고점대비 낙폭 (MDD)',
         cycle='주 1회 (일 08:00)', max_age=9, producer='screen_precompute.py',
         job='weekly-profile', used_by='전 서브탭 (고점대비% 열)',
         getter=_key('date')),
    dict(path='results/leaders_signal.json', label='주도주 신호 (규칙⑥)',
         cycle='주 1회', max_age=9, producer='leaders_publish.py',
         job='수동 (로컬)', used_by='🚀 주도주',
         getter=_key('generated')),
    dict(path='results/leaders_kr.json', label='주도주 KR (KR-P1)',
         cycle='주 1회', max_age=9, producer='leaders_kr.py publish',
         job='수동 (로컬 · longcache 필요)', used_by='🚀 주도주 → 🇰🇷 한국',
         getter=_key('generated')),
    dict(path='results/leaders_paper.json', label='주도주 페이퍼 원장',
         cycle='주 1회', max_age=9, producer='leaders_paper.py',
         job='수동 (로컬)', used_by='🚀 주도주 (포워드 검증)',
         getter=_key('updated')),
    dict(path='results/paper_trades.json', label='페이퍼 트레이딩 원장',
         cycle='주 1회 (weekly_run 동시)', max_age=9, producer='paper_trade.py',
         job='daily-refresh', used_by='📒 성적표',
         getter=_paper_max_log),
    dict(path='results/weekly_portfolio.json', label='주간 추천 포트폴리오',
         cycle='주 1회 (월 06:00)', max_age=9, producer='weekly_portfolio.py',
         job='daily-refresh', used_by='💼 포트폴리오 (AI 추천) · 📒 성적표',
         getter=_key('updated')),
    # 검증 루프의 심장 — 이게 멈추면 '못 하는 신호를 자동 감액'이 조용히 멈춘다
    dict(path='results/signal_live_weights.json', label='실전 신뢰계수 (신호별 가중)',
         cycle='주 1회 (weekly_run 동시)', max_age=9, producer='paper_trade.py',
         job='daily-refresh', used_by='auto_recommend · winning_score · 📒 성적표',
         getter=_key('updated')),
    dict(path='results/guru_insights.json', label='구루 유튜브 요약',
         cycle='매일', max_age=3, producer='guru_youtube.py',
         job='guru-digest', used_by='텔레그램 다이제스트 (화면에는 없음)',
         getter=_key('updated')),
]


def statuses(today: datetime | None = None) -> list[dict]:
    """각 산출물의 마지막 데이터 날짜·경과일·상태를 계산한다."""
    today = today or datetime.now()
    out = []
    for s in SOURCES:
        row = dict(label=s['label'], path=s['path'], cycle=s['cycle'],
                   max_age=s['max_age'], producer=s['producer'], job=s['job'],
                   used_by=s['used_by'], date=None, age=None, state='unknown', note='')
        p = BASE / s['path']
        if not p.exists():
            row.update(state='missing', note='파일 없음')
            out.append(row); continue
        try:
            d = json.loads(p.read_text(encoding='utf-8'))
            ds = s['getter'](d) if isinstance(d, dict) else None
            if not ds:
                row.update(state='nodate', note='내부 날짜 필드 없음')
                out.append(row); continue
            age = (today - datetime.strptime(ds[:10], '%Y-%m-%d')).days
            row.update(date=ds[:10], age=age,
                       state=('stale' if age > s['max_age'] else 'ok'))
            if row['state'] == 'stale':
                row['note'] = f"{age}일 정지 (허용 {s['max_age']}일)"
        except Exception as e:                       # 형식이 바뀌어도 감시는 계속돼야 한다
            row.update(state='error', note=f'검사 실패: {type(e).__name__}')
        out.append(row)
    return out


def date_for(path: str, today: datetime | None = None) -> dict | None:
    """화면에 '이 숫자는 언제 것인가'를 붙이기 위한 단건 조회."""
    for r in statuses(today):
        if r['path'] == path:
            return r
    return None


def stale_lines(today: datetime | None = None) -> list[str]:
    """경보용 — 정지·누락·오류만 사람이 읽는 문장으로."""
    lines = []
    for r in statuses(today):
        if r['state'] == 'ok':
            continue
        where = f" [{r['job']}]" if r['job'] else ''
        if r['state'] == 'stale':
            lines.append(f"{r['label']}{where}: {r['note']} — 마지막 {r['date']} "
                         f"· 생산자 {r['producer']}")
        else:
            lines.append(f"{r['label']}{where}: {r['note']} — 생산자 {r['producer']}")
    return lines


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    print(f"{'산출물':<26} {'마지막':<12} {'경과':<6} {'주기':<22} 상태")
    print('─' * 92)
    for r in statuses():
        mark = {'ok': '🟢', 'stale': '🔴', 'missing': '⚫', 'nodate': '⚠️', 'error': '⚠️'}[r['state']]
        print(f"{r['label']:<26} {str(r['date'] or '-'):<12} "
              f"{(str(r['age']) + '일') if r['age'] is not None else '-':<6} "
              f"{r['cycle']:<22} {mark} {r['note']}")
