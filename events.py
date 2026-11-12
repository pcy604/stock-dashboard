"""🗓️ 이벤트 캘린더 — 2026-11-12 종합 진단 '빠진 팩터 1위'(보유 종목 실적일을 모르고 들고 있었다).

세 가지를 합친다:
  ① 손으로 넣는 공식 일정  data/events_calendar.json (금통위·FOMC·CPI — 출처 기관 공식 발표)
  ② 규칙으로 계산되는 한국 일정  옵션 만기(매월 둘째 목요일, 3·6·9·12월 = 선물·옵션 동시 만기),
     분기·반기·사업보고서 법정 기한(분기 종료 후 45일 / 사업연도 종료 후 90일)
  ③ 내 보유 종목 — 그 분기 재무가 아직 없으면 '실적 미발표'로 기한 행에 종목명을 붙인다.
휴장일 보정은 하지 않는다(둘째 목요일이 휴장이면 전 영업일 — 화면에 그렇게 적는다).
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

VERSION = '2026-11-12b'
_ROOT = Path(__file__).resolve().parent
WD = '월화수목금토일'


def second_thursday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    first = d + dt.timedelta(days=(3 - d.weekday()) % 7)
    return first + dt.timedelta(days=7)


def option_expiries(start: dt.date, end: dt.date) -> list[dict]:
    out, y, m = [], start.year, start.month
    while dt.date(y, m, 1) <= end:
        d = second_thursday(y, m)
        if start <= d <= end:
            quad = m in (3, 6, 9, 12)
            out.append(dict(date=d.isoformat(), time='15:20', kind='한국',
                            name='선물·옵션 동시 만기(쿼드러플 위칭)' if quad else '코스피200 옵션 만기',
                            src='KRX 규정(매월 둘째 목요일, 휴장이면 전 영업일)'))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def report_deadlines(start: dt.date, end: dt.date) -> list[dict]:
    """(마감일, 대상 연도, 분기) — 12월 결산 기준. 분기 q 의 재무가 kr_fundamentals_q 에 들어오는지로 '발표'를 판정."""
    out = []
    for y in (start.year - 1, start.year, start.year + 1):
        for (mm, dd, fy, q, nm) in ((5, 15, y, 1, '1분기 보고서'), (8, 14, y, 2, '반기 보고서'),
                                    (11, 14, y, 3, '3분기 보고서'), (3, 31, y - 1, 4, '사업보고서')):
            d = dt.date(y, mm, dd)
            while d.weekday() >= 5:              # 기간 말일이 토·일이면 다음 월요일(민법 161조) — 휴장일 미보정
                d += dt.timedelta(days=1)
            if start <= d <= end:
                out.append(dict(date=d.isoformat(), time='', kind='보유', name=f'{nm} 법정 기한({fy}년 {q}분기)',
                                src='자본시장법(분기·반기 종료 후 45일, 사업연도 종료 후 90일 · 휴일이면 다음 영업일)',
                                _fy=fy, _q=q))
    return out


def build(today: dt.date | None = None, days: int = 35, holdings: dict | None = None,
          fundq=None) -> list[dict]:
    """today 부터 days 일 안의 일정. holdings = {code: name}, fundq = kr_fundamentals_q DataFrame(없으면 판정 생략)."""
    today = today or dt.date.today()
    end = today + dt.timedelta(days=days)
    ev = []
    try:
        cal = json.loads((_ROOT / 'data' / 'events_calendar.json').read_text(encoding='utf-8'))
        ev += [e for e in cal.get('events', []) if today.isoformat() <= e['date'] <= end.isoformat()]
    except Exception:
        pass
    ev += option_expiries(today, end)
    for r in report_deadlines(today, end):
        if holdings:
            pend = list(holdings.values())
            if fundq is not None:
                try:
                    have = set(fundq[(fundq['year'] == r['_fy']) & (fundq['q'] == r['_q'])]['sym'].astype(str))
                    pend = [n for c, n in holdings.items() if c not in have]
                except Exception:
                    pass
            r['detail'] = (f"보유 {len(holdings)}종 중 실적 미반영 {len(pend)}종: " + ', '.join(pend[:6])
                           + (' 외' if len(pend) > 6 else '')) if pend else f"보유 {len(holdings)}종 모두 반영됨"
            r['hot'] = bool(pend)
        ev.append({k: v for k, v in r.items() if not k.startswith('_')})
    for e in ev:
        d = dt.date.fromisoformat(e['date'])
        e['dday'] = (d - today).days
        e['wd'] = WD[d.weekday()]
    return sorted(ev, key=lambda e: (e['date'], e.get('time') or ''))
