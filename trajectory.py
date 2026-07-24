"""
trajectory.py — 펀더멘털 벡터(궤적) 계산
─────────────────────────────────────────────────────────────────
문제: PER·ROE 같은 스칼라(한 시점의 위치)로는 밸류 함정을 못 거른다.
  · "싸고 개선 중"(진짜 기회) vs "이익 무너져 싸 보임"(함정) — 위치는 같아도 벡터는 반대.
해법(자문사·학계 표준): 각 지표를 [위치(level) + 속도(Δ, 전년대비) + 가속(Δ², 성장률의 변화)]로 본다.
  · Piotroski F-Score의 9신호 중 다수가 Δ(ΔROA·ΔMargin·ΔTurnover) — 그 궤적 개념을 우리 DART 다년 재무에 적용.

입력: db.get_fundamentals(sym, 'KR', 'annual')  — 최신순 다년 리스트
출력: {ROE·OPM·매출성장·자산회전율·순마진}의 위치+Δ + 궤적점수(0~7) + 판정
한계: 이 DB 접근자엔 영업현금흐름·부채가 없어 Piotroski 9점 전체는 불가 →
      수익성·마진·성장·효율 축의 7점 궤적으로 적용(현금흐름 축은 로드맵).
"""
from __future__ import annotations


def _safe(n, d):
    return (n / d) if (n is not None and d) else None


def _metrics(row):
    """한 회계연도 행 → 핵심 비율 5종."""
    rv, op, ni, eq, at = (row.get('revenue'), row.get('op_income'),
                          row.get('net_income'), row.get('equity'), row.get('assets'))
    return {
        'roe': _pct(_safe(ni, eq)),
        'opm': _pct(_safe(op, rv)),
        'npm': _pct(_safe(ni, rv)),
        'turn': _safe(rv, at),          # 자산회전율 (배)
        'rev': rv,
    }


def _pct(x):
    return round(x * 100, 1) if x is not None else None


def _delta(cur, prev):
    if cur is None or prev is None:
        return None
    return round(cur - prev, 1)


def compute(fund_rows: list) -> dict | None:
    """fund_rows: db.get_fundamentals 반환(최신순). 최소 2개년 필요."""
    if not fund_rows or len(fund_rows) < 2:
        return None
    m0 = _metrics(fund_rows[0])          # 최신
    m1 = _metrics(fund_rows[1])          # 전년
    m2 = _metrics(fund_rows[2]) if len(fund_rows) >= 3 else None

    # 매출성장률과 그 가속(성장률의 변화 = Δ²)
    g0 = _pct(_safe(m0['rev'], m1['rev']) - 1) if (m0['rev'] and m1['rev']) else None
    g1 = _pct(_safe(m1['rev'], m2['rev']) - 1) if (m2 and m1['rev'] and m2['rev']) else None
    growth_accel = _delta(g0, g1)        # 성장 가속(+면 성장이 빨라지는 중)

    d_roe = _delta(m0['roe'], m1['roe'])
    d_opm = _delta(m0['opm'], m1['opm'])
    d_npm = _delta(m0['npm'], m1['npm'])
    d_turn = _delta(m0['turn'], m1['turn'])

    # ── 궤적 점수 (Piotroski 개념 적용, 7점 만점: 수익성·마진·성장·효율) ──
    score = sum([
        (m0['roe'] is not None and m0['roe'] > 0),     # 1) 흑자
        (d_roe is not None and d_roe > 0),             # 2) ROE 개선
        (d_opm is not None and d_opm > 0),             # 3) 영업마진 개선
        (d_npm is not None and d_npm > 0),             # 4) 순마진 개선
        (g0 is not None and g0 > 0),                   # 5) 매출 성장
        (growth_accel is not None and growth_accel > 0),  # 6) 성장 가속
        (d_turn is not None and d_turn > 0),           # 7) 자산 효율 개선
    ])

    # ── 판정: 위치(싼가)가 아니라 벡터(개선/악화)로 ──
    up = sum(1 for d in (d_roe, d_opm, d_npm) if d is not None and d > 0)
    down = sum(1 for d in (d_roe, d_opm, d_npm) if d is not None and d < 0)
    if score >= 5 and up >= 2:
        verdict, vlab = 'improving', '📈 개선 가속'
    elif down >= 2 or (m0['roe'] is not None and m0['roe'] < 0):
        verdict, vlab = 'deteriorating', '📉 악화(함정 주의)'
    else:
        verdict, vlab = 'stable', '➖ 정체'

    return {
        'roe': m0['roe'], 'd_roe': d_roe,
        'opm': m0['opm'], 'd_opm': d_opm,
        'npm': m0['npm'], 'd_npm': d_npm,
        'turn': round(m0['turn'], 2) if m0['turn'] else None, 'd_turn': d_turn,
        'growth': g0, 'growth_accel': growth_accel,
        'traj_score': score, 'verdict': verdict, 'verdict_label': vlab,
        'years': [r.get('period') for r in fund_rows[:3]],
    }


def fmt_lv(level, delta, unit='%'):
    """'17.6% ▲+8.8' 형식 — 위치와 화살표(속도)를 한 셀에."""
    if level is None:
        return '-'
    if delta is None:
        return f"{level:.1f}{unit}"
    arr = '▲' if delta > 0 else ('▼' if delta < 0 else '·')
    return f"{level:.1f}{unit} {arr}{abs(delta):.1f}"
