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


def _fundq_quarter(p):
    """KR 분기재무 parquet 의 '내용 날짜' — 대다수 종목(80% 분위)의 최신 분기 말일.

    2026-10-14 — 이 파일은 _mtime 으로 판정됐다. 그래서 08-15 에 만든 내용(순이익 전 행
    공란·2026Q1)이 10-13 에 '수정 0일 · 정상'으로 보였다. 파일을 언제 건드렸는지가
    아니라 **안에 든 데이터가 언제 것인지**를 본다. 분기 말에서 150일(다음 분기 실적
    공시 마감 + 여유)이 지나도 새 분기가 없으면 낡은 것이다."""
    try:
        import pandas as pd
        r = pd.read_parquet(p, columns=['sym', 'year', 'q'])
        last = (r.year * 10 + r.q).groupby(r.sym).max().quantile(0.8)
        y, q = int(last // 10), int(last % 10)
        m = q * 3
        import calendar
        return f"{y}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"
    except Exception:
        return None


def _mtime(p):
    """내용에 날짜 컬럼이 없는 산출물(parquet 등)용 — 파일 수정시각을 신선도로 쓴다.
    raw=True 와 함께 쓴다. 내용 기반 날짜가 있으면 그쪽이 항상 낫다(파일을 건드리기만
    해도 갱신된 척하게 되므로)."""
    from datetime import datetime as _d
    return _d.fromtimestamp(p.stat().st_mtime).strftime('%Y-%m-%d')


def _cq_max_date(path):
    """consensus_q.json {sym: {분기: {'date': ...}}} 의 가장 최근 저장일."""
    try:
        d = json.loads(Path(path).read_text(encoding='utf-8'))
        ds = [v.get('date') for per in d.values() for v in per.values() if isinstance(v, dict) and v.get('date')]
        return max(ds) if ds else None
    except Exception:
        return None


def _jsonl_max_date(path):
    """JSONL 누적 산출물 — 행들의 date 최대값(2026-10-19, 컨센서스 스냅샷용)."""
    import json as _j
    best = None
    try:
        with open(path, encoding='utf-8') as f:
            for line in f:
                try:
                    d = _j.loads(line).get('date')
                except Exception:
                    continue
                if d and (best is None or d > best):
                    best = d
    except Exception:
        return None
    return best


def _csv_col(col):
    """CSV 산출물용. raw=True 와 함께 쓰며 getter 가 파일 경로를 받는다."""
    def get(path):
        import csv
        with open(path, encoding='utf-8', newline='') as f:
            r = csv.DictReader(f)
            row = next(r, None)
            return (row or {}).get(col)
    return get


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
    # ★ 2026-08-18 추가 — 이 레지스트리의 두 번째 사각지대였다.
    #   여기 있는 건 전부 results/ 의 **산출물**이었고, 그 산출물을 만드는 **입력**은
    #   아무도 안 봤다. data/us_marketcap.csv 가 2024-04 스냅샷인 채 27개월 방치돼
    #   미국 스크리너 전체가 틀린 시총으로 유니버스를 걸렀는데 경보가 없었다.
    #   입력도 산출물과 같은 자격으로 감시한다.
    dict(path='data/us_marketcap.csv', label='미국 시총 (유니버스 기준)',
         cycle='매일 06:00 (평일)', max_age=4, producer='marketcap_refresh.py build',
         job='daily-refresh',
         used_by='💎 펀더멘털 → 이익가속 · 🚀 주도주 → CANSLIM(US) · 🔥 모멘텀 → 상승 상위 · 전 미국 스크리너',
         getter=_csv_col('as_of'), raw=True),
    dict(path='data/us_shares.csv', label='미국 주식수 (SEC 공시)',
         cycle='주 1회 (일 08:00)', max_age=10,
         producer='marketcap_refresh.py frames+shares',
         job='weekly-profile', used_by='시총·PER·PSR 계산 전체 (point-in-time)',
         getter=_csv_col('as_of'), raw=True),
    dict(path='results/screener_latest.json', label='주봉 신호 스크리너',
         cycle='매일 06:00 (평일)', max_age=4, producer='weekly_run.py',
         job='daily-refresh', used_by='🔥 상승 상위',
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
    # ★ 2026-08-18 — 주도주 주력 신호가 규칙⑥ → L/S 로 교체됐다.
    # ★ 2026-08-23 신설 — 이익 가속 신호. 주도주 탭의 첫 화면이라 밀리면 바로 보인다.
    dict(path='results/leaders_accel.json', label='이익 가속 신호',
         cycle='주 1회 (토 08:00)', max_age=9, producer='leaders_accel.py',
         job='leaders_weekly (로컬 스케줄러)', used_by='💎 펀더멘털 → 이익가속 → ⚡ 이익 가속',
         getter=_key('generated')),
    # ★ 2026-08-25 신설 — 두 심층조회가 같은 곡선을 각자 갖고 있어 합쳤다(674종 중복).
    # 이게 밀리면 차트의 ▲ 는 최신인데 곡선만 지난주까지 그려진다 — 조용히 어긋난다.
    # ★ 2026-09-07 신설 — 이익 가속 규칙의 워크포워드 성적.
    # 규칙이 바뀌면 같이 다시 돌려야 한다. 안 그러면 화면의 '검증 결과'가
    # 지금 쓰는 규칙이 아닌 옛 규칙의 성적이 된다 — 가장 나쁜 종류의 거짓말이다.
    dict(path='results/leaders_accel_wf.json', label='이익 가속 워크포워드',
         cycle='규칙 변경 시 수동', max_age=400, producer='leaders_accel_wf.py',
         job='수동 (python leaders_accel_wf.py)',
         used_by='💎 펀더멘털 → 이익가속 → 🧪 워크포워드 검증',
         getter=_key('generated')),
    dict(path='results/price_curves.json', label='가격 곡선 (L/S·가속 공용)',
         cycle='주 1회 (토 08:00)', max_age=9, producer='curves_build.py',
         job='weekly-accel + leaders_weekly(로컬)',
         used_by='💎 펀더멘털 → 이익가속 → 심층조회 차트 (L/S·이익가속 양쪽)',
         getter=_key('generated')),
    # 종료된 규칙이지만 화면에 기록으로 남아 있어 계속 감시한다.
    # ★ 2026-08-22 추가 — 이 파일이 밀리면 새 주차의 vw 가 NaN 이 되어
    #   `vw < 1.5` 가 항상 거짓이 되고 **가짜 '신호 0종'**이 뜬다. 그날 사이클은
    #   EXIT=0 으로 성공을 보고했다. 감시하지 않으면 또 조용히 죽는다.
    # 파일 자체(data/_volwk.parquet)는 1.6M행이라 저장소에 없다. 러너에 없는 파일을
    # 등록하면 스모크의 '레지스트리에 있으나 파일 없음' 검사가 깨진다(2026-08-22 CI
    # 실패가 그것이었다). 그래서 leaders_ab.py 가 발행물에 기준일(vol_asof)을 실어
    # 보내고, 여기서는 그 값을 본다 — 배포된 화면에서도 보인다.
        dict(path='data/kr_fundamentals_q.parquet', label='KR 분기재무 (KR-U6 입력)',
         cycle='분기 1회', max_age=150, producer='export_kr_fundq.py export',
         job='weekly-profile (tools/refresh_kr_fundq.py)', used_by='💎 펀더멘털 → 이익가속 → 🇰🇷 · 🔄 흑자전환(KR)',
         getter=_fundq_quarter, raw=True),
    # 2026-10-19 — 07-24 한 번 쌓이고 석 달 멈춰 있었는데 감시 목록에 없었다.
    dict(path='results/consensus_history.jsonl', label='KR 컨센서스 주간 스냅샷',
         cycle='주 1회 (월)', max_age=10, producer='consensus_snapshot.py',
         job='daily-refresh (월요일)', used_by='🔍 종목 분석 → 컨센서스 추세(KR)',
         getter=_jsonl_max_date, raw=True),
    # 2026-10-21 — 애널 추정이 없는 종목 목록(화면이 '수집 대상 아님'과 '추정 없음'을 구분). 첫 수집은 10-26(월).
    # 2026-10-23 — 분기 컨센서스(발표 직전 값). 실적 vs 컨센서스 비교의 유일한 원천. 첫 수집 10-26(월).
    dict(path='results/consensus_q.json', label='KR 분기 컨센서스(발표 직전)',
         cycle='주 1회 (월)', max_age=10, producer='consensus_snapshot.py',
         job='daily-refresh (월요일)', used_by='🔍 종목 분석 → 실적 발표 · 서프라이즈(KR)',
         getter=_cq_max_date, raw=True),
    dict(path='results/consensus_nocover.json', label='KR 컨센서스 미커버 종목',
         cycle='주 1회 (월)', max_age=10, producer='consensus_snapshot.py',
         job='daily-refresh (월요일)', used_by='🔍 종목 분석 → 컨센서스 추세(KR)',
         getter=_key('date')),
    dict(path='results/new_high_ai.json', label='52주 신고가 AI 공통점 요약',
         cycle='매일 06:00 (평일)', max_age=4, producer='new_high_ai.py',
         job='daily-refresh', used_by='📈 52주 신고가 → AI 공통점 요약',
         getter=_key('generated')),
    dict(path='results/leaders_kr6.json', label='주도주 KR (KR-U6·규칙⑥ 이식)',
         cycle='주 1회', max_age=9, producer='leaders_kr6.py publish',
         job='weekly-profile', used_by='💎 펀더멘털 → 이익가속 → 🇰🇷 → 규칙⑥ 이식',
         getter=_key('generated')),
    dict(path='results/leaders_kr.json', label='주도주 KR (KR-P1)',
         cycle='주 1회', max_age=9, producer='leaders_kr.py publish',
         job='weekly-profile', used_by='💎 펀더멘털 → 이익가속 → 🇰🇷 한국',
         getter=_key('generated')),
    dict(path='results/leaders_kr_paper.json', label='주도주 KR 포워드 원장',
         cycle='주 1회', max_age=9, producer='leaders_kr_paper.py update',
         job='weekly-profile', used_by='💎 펀더멘털 → 이익가속 → 🇰🇷 (포워드 검증)',
         getter=_key('updated')),
    # 2026-10-10 추가 — 소비자가 없어 레지스트리에도 없었다. 화면을 붙였으니
    #   같이 감시한다. 09-16 자 종목 0개인 채로 아무도 모르고 있었다.
    # 2026-10-21 — 이번 주 판정 단일 출처. 멈추면 상단 배지·🏠 종합이 라이브 계산으로 넘어가고
    #   시황 리포트·주간 포트폴리오·executor 는 낡은 판정을 읽는다.
    dict(path='results/macro.json', label='이번 주 판정 (코어 200일선 스위치)',
         cycle='매일 06:00', max_age=5, producer='verdict.py',
         job='daily-refresh · verdict(수동)', used_by='상단 배지 · 🏠 종합 · 📰 시황 리포트 · executor',
         getter=_key('asof')),
    dict(path='results/market_report.json', label='시황 리포트 (일간·주간)',
         cycle='매일 06:00 · 월 주간', max_age=4, producer='market_report.py',
         job='daily-refresh · weekly-profile', used_by='🏠 종합 → 시황 리포트 · 💬 챗봇',
         getter=lambda p: (__import__('json').load(open(p, encoding='utf-8')).get('latest_daily') or {}).get('date'), raw=True),
    dict(path='results/loss_cut_grid.json', label='손절선 올려잡기·재매수·냉각·불타기 격자(810조합)',
         cycle='수동(연구)', max_age=400, producer='research/loss_cut_grid.py',
         job='research-rs (수동·코드 변경 시)', used_by='🔎 종목 발굴 → 🚀 주도주 → 교집합 후보 → 🛡️ 손절선 올려 잡기',
         getter=_key('run')),
    dict(path='results/robust_rs.json', label='RS순 우선 강건성 격자(144조합)',
         cycle='수동(연구)', max_age=400, producer='research/robust_rs.py',
         job='research-rs (수동·코드 변경 시)', used_by='🔎 종목 발굴 → 🚀 주도주 → 교집합 후보 → 🧪 RS순 우선 강건성',
         getter=_key('run')),
    dict(path='results/rs_accel_detail.json', label='RS × 이익가속 백테스트 상세(원장·낙폭)',
         cycle='수동(연구)', max_age=400, producer='research/rs_accel_detail.py',
         job='research-rs (수동·코드 변경 시)', used_by='🔎 종목 발굴 → 🚀 주도주 → 교집합 후보 → 🔬 백테스트 상세',
         getter=_key('run')),
    dict(path='results/rs_accel_bt.json', label='RS × 이익가속 백테스트 판정',
         cycle='수동(연구)', max_age=400, producer='research/rs_accel_bt.py',
         job='research-rs (수동·코드 변경 시)', used_by='🔎 종목 발굴 → 🚀 주도주 → 교집합 후보',
         getter=_key('run')),
    dict(path='results/turnaround_latest.json', label='흑자전환 (턴어라운드)',
         cycle='주 1회', max_age=9, producer='turnaround_run.py',
         job='weekly-accel (금 22:17 UTC)', used_by='🔎 종목 발굴 → 💎 펀더멘털 → 흑자전환 · 🚀 주도주 → 교집합 후보',
         getter=_key('date')),
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
            if s.get('raw'):                       # CSV 등 — getter 가 경로를 받는다
                ds = s['getter'](p)
            else:
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


# ═══════════════════════════════════════════════════════════════════
# 의존 그래프 · 중요도 — 2026-10-10 신설
# ═══════════════════════════════════════════════════════════════════
# 왜 만들었나: SOURCES 는 '이 파일이 신선한가'만 알았다. 그래서 화면은 17줄짜리
# 평면 표였고, 무엇이 무엇에서 나오는지·무엇부터 고쳐야 하는지가 없었다.
# 실제로 이 표를 보고 "뭔 말인지 하나도 모르겠다"는 말이 나왔다 — 표가 아니라
# 구조가 안 보인 것이다.
#
# ORIGINS : 파일이 아닌 외부 원천과 중간 저장소. 모든 사슬의 시작점이다.
# DEPS    : path → 그것이 **직접** 의존하는 것 (ORIGINS 키 또는 다른 path)
#
# ⚠️ 중요도는 손으로 매기지 않는다. '이게 죽으면 같이 멈추는 산출물 수'를 세서
#    자동으로 정한다. 손으로 매긴 등급은 구조가 바뀌는 순간 거짓말이 된다 —
#    이 프로젝트가 '초록불인데 실은 죽어 있는' 사고를 세 번 겪은 이유가 그것이다.

ORIGINS = {
    'src:yahoo': dict(label='Yahoo Finance\n(일봉)', kind='외부'),
    'src:edgar': dict(label='SEC EDGAR\n(US 공시)', kind='외부'),
    'src:dart':  dict(label='DART\n(KR 공시)', kind='외부'),
    'src:yf':    dict(label='yfinance\n(분기재무)', kind='외부'),
    'src:fdr':   dict(label='FinanceDataReader\n(KR·US 가격)', kind='외부'),
    'store:cache': dict(label='일봉 캐시\n(실적반응 전용)', kind='저장소'),
    'store:db':    dict(label='market.db\nprices · factor_weekly', kind='저장소'),
}

# 저장소 자체도 무엇에서 채워지는지 기록한다(사슬의 허리가 비면 안 보인다)
# 2026-10-10: 주봉이 market.db(prices)로 들어오면서 방향이 바뀌었다.
#   전: Yahoo → 가격캐시(CSV) → market.db
#   후: Yahoo → market.db(prices) → factor_weekly.  캐시에는 일봉만 남고,
#       그건 실적반응 2개 열을 만드는 데만 쓰이므로 market.db 의 입력이다.
STORE_DEPS = {
    'store:cache': ['src:yahoo'],
    # 일봉 캐시는 **선택적** 입력이라 의존으로 걸지 않는다. 없으면
    #   earn_react_gap · earn_react_d2 두 열만 비고(코드에 None 가드가 있다)
    #   factor_weekly 자체는 그대로 만들어진다. 여기에 걸면 '일봉이 멈추면
    #   11개가 멈춘다'는 과장이 되고, 고치는 순서를 틀리게 만든다.
    'store:db':    ['src:yahoo', 'src:edgar'],
}

DEPS = {
    'data/us_shares.csv':                ['src:edgar'],
    'data/us_marketcap.csv':             ['data/us_shares.csv', 'store:db'],
    'results/screener_latest.json':      ['src:fdr', 'data/us_marketcap.csv'],
    'results/perf_latest.json':          ['src:fdr'],
    'results/canslim_latest.json':       ['src:fdr', 'src:dart'],
    'results/canslim_us_latest.json':    ['src:fdr', 'data/us_marketcap.csv'],
    'results/value_kr.json':             ['src:dart'],
    'results/returns.json':              ['store:db'],
    'results/seasonality.json':          ['store:db'],
    'results/mdd.json':                  ['store:db'],
    'results/price_curves.json':         ['store:db'],
    'results/leaders_accel.json':        ['store:db'],
    'results/leaders_accel_wf.json':     ['results/leaders_accel.json'],
    'data/kr_fundamentals_q.parquet':    ['src:dart'],
    'results/leaders_kr6.json':          ['data/kr_fundamentals_q.parquet', 'src:fdr'],
    'results/leaders_kr.json':           ['src:fdr', 'src:dart'],
    'results/leaders_kr_paper.json':     ['results/leaders_kr6.json', 'results/leaders_kr.json'],
    'results/turnaround_latest.json':    ['src:yf', 'src:fdr'],
}


def _children():
    """node → 그 노드에 직접 의존하는 것들."""
    out = {}
    for path, deps in list(DEPS.items()) + list(STORE_DEPS.items()):
        for d in deps:
            out.setdefault(d, []).append(path)
    return out


def impact(node, _kids=None):
    """이 노드가 멈추면 같이 멈추는 **하위 산출물 수**(자기 제외, 중복 제외).

    중요도를 이것으로 정한다. 사람이 '중요해 보이는 순서'로 적으면 구조가
    바뀔 때마다 어긋나지만, 이 수치는 DEPS 만 맞으면 늘 따라온다.
    """
    kids = _kids if _kids is not None else _children()
    seen, stack = set(), list(kids.get(node, []))
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(kids.get(n, []))
    return len(seen)


def ranked(today=None):
    """중요도(impact) 내림차순 산출물 목록. statuses() 결과에 그래프 정보를 붙인다."""
    kids = _children()
    rows = statuses(today)
    by_path = {r['path']: r for r in rows}
    for r in rows:
        r['impact'] = impact(r['path'], kids)
        r['deps'] = DEPS.get(r['path'], [])
        # 상류가 이미 죽어 있으면 이 항목의 '정상'은 신뢰할 수 없다
        r['upstream_bad'] = [d for d in r['deps']
                             if d in by_path and by_path[d].get('state') != 'ok']
    rows.sort(key=lambda r: (-r['impact'], r['path']))
    return rows


def node_label(n):
    if n in ORIGINS:
        return ORIGINS[n]['label']
    for s in SOURCES:
        if s['path'] == n:
            return s['label']
    return n


_SHAPE = {'외부': ('ellipse', '#f1f5f9', '#64748b'),
          '저장소': ('cylinder', '#dbeafe', '#2563eb')}
_STATE_COLOR = {'ok': ('#dcfce7', '#16a34a'), 'stale': ('#fee2e2', '#dc2626'),
                'missing': ('#f3f4f6', '#6b7280'), 'nodate': ('#fef9c3', '#ca8a04'),
                'error': ('#fef9c3', '#ca8a04')}


def dot(rows=None):
    """의존 그래프를 Graphviz DOT 문자열로. st.graphviz_chart 가 그대로 받는다.

    graphviz 파이썬 패키지는 쓰지 않는다 — Streamlit 프론트엔드가 DOT 를 직접
    렌더하므로 의존성을 늘릴 이유가 없다.
    """
    rows = rows if rows is not None else ranked()
    st_of = {r['path']: r for r in rows}
    kids = _children()
    L = ['digraph G {', '  rankdir=LR;', '  bgcolor="transparent";',
         '  node [fontname="Malgun Gothic,sans-serif" fontsize=10 style="filled,rounded"];',
         '  edge [color="#94a3b8" arrowsize=0.7];']

    for n, meta in ORIGINS.items():
        shape, fill, line = _SHAPE[meta['kind']]
        imp = impact(n, kids)
        L.append(f'  "{n}" [label="{meta["label"]}\n▼{imp}개가 여기 의존" '
                 f'shape={shape} fillcolor="{fill}" color="{line}" penwidth=1.6];')

    for path, r in st_of.items():
        fill, line = _STATE_COLOR.get(r['state'], ('#f3f4f6', '#6b7280'))
        imp = r.get('impact', 0)
        age = f"{max(r['age'], 0)}일 전" if r.get('age') is not None else '날짜없음'
        tail = f'\n▼{imp}' if imp else ''
        L.append(f'  "{path}" [label="{r["label"]}\n{age}{tail}" shape=box '
                 f'fillcolor="{fill}" color="{line}" penwidth=1.4];')

    for path, deps in list(DEPS.items()) + list(STORE_DEPS.items()):
        for d in deps:
            if (d in ORIGINS or d in st_of) and (path in ORIGINS or path in st_of):
                L.append(f'  "{d}" -> "{path}";')
    L.append('}')
    return '\n'.join(L)
