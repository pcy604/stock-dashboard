"""종목 분석 화면의 '데이터 점검'과 '리스크 점검' (2026-10-20) — 순수 함수(네트워크 없음), 테스트 가능.

데이터 점검: 화면의 숫자가 **서로 맞는지, 최신인지**를 종목마다 그 자리에서 확인한다.
  조용한 실패(값이 비거나 낡았는데 화면은 멀쩡해 보임)를 눈에 보이게 하는 게 목적이다.
  기준을 못 재면 '확인 불가'로 둔다 — 통과로 치지 않는다.
리스크 점검: 사실·규칙 판정만(매수·매도 의견 아님). 데이터가 있는 항목만 판정한다.

각 항목: {'name', 'state': 'ok'|'warn'|'na', 'detail'}
"""
from __future__ import annotations

from datetime import date


def _pct_gap(a, b):
    try:
        a, b = float(a), float(b)
        return None if b == 0 else (a / b - 1) * 100
    except Exception:
        return None


def _bdays_between(d0: date, d1: date) -> int:
    """d0 다음 날부터 d1 까지 평일 수(주말 제외). 휴장일은 모른다 → 허용폭으로 흡수."""
    n, d = 0, d0
    from datetime import timedelta
    while d < d1:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return n


def _qend(period: str) -> date | None:
    """'2026-06' · '2026.2Q' → 분기 말일."""
    p = str(period)
    try:
        if 'Q' in p:
            y, q = int(p[:4]), int(p[5])
            m = q * 3
        else:
            y, m = int(p[:4]), int(p[5:7])
        import calendar
        return date(y, m, calendar.monthrange(y, m)[1])
    except Exception:
        return None


def integrity_checks(*, today: date, last_price_date: date | None, latest_quarter: str | None,
                     per_ttm=None, yf_trailing_pe=None, rev_ttm=None, yf_total_revenue=None,
                     mcap=None, price=None, shares=None, seg_check_pct=None, seg_src_ai=False,
                     n_analysts=None, is_kr=False, bad_bars=0) -> list[dict]:
    out = []

    def add(name, state, detail):
        out.append({'name': name, 'state': state, 'detail': detail})

    # 0. 현재가 자체 — NaN·0 이면 화면의 거의 모든 숫자가 깨진다(2026-10-20 $nan 사고)
    import math
    try:
        _pv = float(price) if price is not None else float('nan')
    except Exception:
        _pv = float('nan')
    if math.isfinite(_pv) and _pv > 0:
        add('현재가', 'ok', f"{_pv:,.2f}" + (f" · 종가 없는 미완성 봉 {bad_bars}개 제외" if bad_bars else ''))
    else:
        add('현재가', 'warn', '현재가를 계산하지 못함 — 가격 소스가 빈 봉을 보냄(아래 숫자 대부분이 무효)')

    # 1. 주가 최신성 — 평일 3일 넘게 비면 수집이 멈춘 것(휴장 연휴 감안)
    if last_price_date:
        lag = _bdays_between(last_price_date, today)
        add('주가 최신', 'ok' if lag <= 3 else 'warn',
            f"마지막 봉 {last_price_date.isoformat()} (평일 {lag}일 전)")
    else:
        add('주가 최신', 'na', '가격 데이터 없음')

    # 2. 재무 최신성 — 분기 말 + 공시 기한(미국 40~45일, 한국 45일) + 여유. 135일을 넘으면 한 분기를 놓친 것
    qe = _qend(latest_quarter) if latest_quarter else None
    if qe:
        age = (today - qe).days
        add('재무 최신', 'ok' if age <= 135 else 'warn',
            f"최신 분기 {latest_quarter} (분기 말부터 {age}일)" + (' — 다음 분기 공시가 빠졌을 수 있음' if age > 135 else ''))
    else:
        add('재무 최신', 'na', '분기 재무 없음')

    # 3. PER(TTM) 교차 — 우리 계산(공시 4분기 합) vs yfinance trailingPE
    g = _pct_gap(per_ttm, yf_trailing_pe) if per_ttm and yf_trailing_pe else None
    if g is None:
        add('PER 교차검증', 'na', '비교할 값이 없음(적자이거나 yfinance 미제공)')
    else:
        add('PER 교차검증', 'ok' if abs(g) <= 15 else 'warn',
            f"공시 TTM {float(per_ttm):.1f}x vs yfinance {float(yf_trailing_pe):.1f}x ({g:+.0f}%)"
            + ('' if abs(g) <= 15 else ' — 주식수·일회성 손익·분기 정의 차이 확인'))

    # 4. 매출(TTM) 교차
    g = _pct_gap(rev_ttm, yf_total_revenue) if rev_ttm and yf_total_revenue else None
    if g is None:
        add('매출 교차검증', 'na', '비교할 값이 없음')
    else:
        add('매출 교차검증', 'ok' if abs(g) <= 5 else 'warn', f"공시 TTM vs yfinance 차이 {g:+.1f}%")

    # 5. 시총 = 주가 × 주식수
    if mcap and price and shares:
        g = _pct_gap(mcap, float(price) * float(shares))
        add('시총 정합', 'ok' if abs(g) <= 5 else 'warn',
            f"시총 vs 주가×주식수 차이 {g:+.1f}%" + ('' if abs(g) <= 5 else ' — 주식수(우선주·자사주)나 시총 갱신 지연'))
    else:
        add('시총 정합', 'na', '주식수 또는 시총 없음')

    # 6. 사업부문 합계 검산
    if seg_check_pct is None:
        add('부문 합계 검산', 'na', '부문 데이터 없음 또는 연결 매출과 비교 불가')
    else:
        tol = 3.0 if seg_src_ai else 1.0
        add('부문 합계 검산', 'ok' if abs(seg_check_pct) <= tol else 'warn',
            f"부문 매출 합 vs 연결 매출 {seg_check_pct:+.1f}%" + (' (AI 추출본)' if seg_src_ai else ' (XBRL 원본)'))

    # 7. 컨센서스 표본
    if n_analysts is None:
        add('컨센서스 표본', 'na', '애널리스트 수 미제공')
    else:
        add('컨센서스 표본', 'ok' if n_analysts >= 3 else 'warn',
            f"애널리스트 {int(n_analysts)}명" + ('' if n_analysts >= 3 else ' — 3명 미만이면 평균이 한두 명 의견'))
    return out


def risk_checks(*, price=None, high52=None, band_rank=None, band_kind='P/E', ttm_net_income=None,
                opm_now=None, opm_4q_ago=None, debt_to_equity=None, eps_fy0_now=None, eps_fy0_30d=None,
                vol_annual=None, top_segment_share=None) -> list[dict]:
    """사실·규칙 판정. warn = 해당, ok = 해당 없음, na = 판정 불가."""
    out = []

    def add(name, cond, detail_hit, detail_ok, have):
        out.append({'name': name, 'state': 'na' if not have else ('warn' if cond else 'ok'),
                    'detail': '데이터 없음' if not have else (detail_hit if cond else detail_ok)})

    dd = (price / high52 - 1) * 100 if price and high52 else None
    add('추세 이탈', dd is not None and dd <= -20, f"52주 고점 대비 {dd:.0f}% — 원칙상 청산 기준선(−20%) 아래" if dd is not None else '',
        f"52주 고점 대비 {dd:.0f}%" if dd is not None else '', dd is not None)
    add('밸류 부담', band_rank is not None and band_rank >= 80,
        f"{band_kind} 과거 분포 상위 {100 - band_rank:.0f}% 구간" if band_rank is not None else '',
        f"{band_kind} 과거 분포 하위 {band_rank:.0f}%" if band_rank is not None else '', band_rank is not None)
    add('적자', ttm_net_income is not None and ttm_net_income <= 0, '최근 4분기 순이익 합이 적자', '최근 4분기 흑자',
        ttm_net_income is not None)
    dm = (opm_now - opm_4q_ago) if (opm_now is not None and opm_4q_ago is not None) else None
    add('마진 악화', dm is not None and dm <= -3, f"영업이익률 1년 새 {dm:+.1f}%p" if dm is not None else '',
        f"영업이익률 1년 새 {dm:+.1f}%p" if dm is not None else '', dm is not None)
    add('부채 부담', debt_to_equity is not None and debt_to_equity >= 200,
        f"부채비율(D/E) {debt_to_equity:.0f}%" if debt_to_equity is not None else '',
        f"부채비율(D/E) {debt_to_equity:.0f}%" if debt_to_equity is not None else '', debt_to_equity is not None)
    rv = _pct_gap(eps_fy0_now, eps_fy0_30d) if (eps_fy0_now and eps_fy0_30d) else None
    add('추정치 하향', rv is not None and rv <= -3, f"올해 EPS 컨센서스 30일 새 {rv:+.1f}%" if rv is not None else '',
        f"올해 EPS 컨센서스 30일 새 {rv:+.1f}%" if rv is not None else '', rv is not None)
    add('고변동성', vol_annual is not None and vol_annual >= 60, f"연환산 변동성 {vol_annual:.0f}%" if vol_annual is not None else '',
        f"연환산 변동성 {vol_annual:.0f}%" if vol_annual is not None else '', vol_annual is not None)
    add('사업 집중', top_segment_share is not None and top_segment_share >= 80,
        f"최대 부문이 매출의 {top_segment_share:.0f}%" if top_segment_share is not None else '',
        f"최대 부문 매출 비중 {top_segment_share:.0f}%" if top_segment_share is not None else '',
        top_segment_share is not None)
    return out
