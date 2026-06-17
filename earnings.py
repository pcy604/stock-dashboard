"""
실적 데이터 분석 — 흑자전환 / 매출 가속 감지 (미국 종목)
"""
import warnings
warnings.filterwarnings('ignore')


def check_earnings(symbol: str) -> dict:
    """
    반환값 예시:
    {
        'profit_turn': True,       # 적자→흑자 전환 여부
        'rev_accel': True,         # 매출 성장 가속 여부
        'rev_growth_yoy': 0.43,    # 최근 분기 YoY 매출 성장률
        'net_income_q': [...],     # 최근 4분기 순이익
        'eps_positive_streak': 2,  # 연속 흑자 분기 수
        'error': None
    }
    """
    result = {
        'profit_turn': False,
        'rev_accel': False,
        'rev_growth_yoy': None,
        'net_income_q': [],
        'eps_positive_streak': 0,
        'gross_margin': None,
        'error': None,
    }
    try:
        import yfinance as yf
        t = yf.Ticker(symbol)
        fin = t.quarterly_financials  # columns = 날짜(최신순)

        if fin is None or fin.empty:
            result['error'] = 'no_data'
            return result

        fin = fin.sort_index(axis=1)  # 오래된 것 → 최신 순

        # ── 순이익 ──────────────────────────────────
        ni_row = None
        for cand in ['Net Income', 'Net Income Common Stockholders']:
            if cand in fin.index:
                ni_row = fin.loc[cand]
                break

        if ni_row is not None:
            ni = ni_row.dropna()
            result['net_income_q'] = [round(v / 1e6, 1) for v in ni.values[-4:]]

            # 흑자 연속 분기
            streak = 0
            for v in reversed(ni.values):
                if v > 0:
                    streak += 1
                else:
                    break
            result['eps_positive_streak'] = streak

            # 흑자전환: 최근 1분기 흑자 + 직전 1분기 적자
            if len(ni) >= 2 and ni.values[-1] > 0 and ni.values[-2] <= 0:
                result['profit_turn'] = True

        # ── 매출 성장 가속 ──────────────────────────
        rev_row = None
        for cand in ['Total Revenue', 'Revenue']:
            if cand in fin.index:
                rev_row = fin.loc[cand]
                break

        if rev_row is not None:
            rev = rev_row.dropna()
            if len(rev) >= 5:
                # YoY 성장률 (최근 분기)
                yoy = (rev.values[-1] - rev.values[-5]) / abs(rev.values[-5])
                result['rev_growth_yoy'] = round(yoy, 3)

                # 가속: 이번 YoY > 지난 YoY
                yoy_prev = (rev.values[-2] - rev.values[-6]) / abs(rev.values[-6]) if len(rev) >= 6 else None
                if yoy_prev is not None:
                    result['rev_accel'] = yoy > yoy_prev and yoy > 0.15

        # ── 매출총이익률 ─────────────────────────────
        for gp_label in ['Gross Profit']:
            if gp_label in fin.index and rev_row is not None:
                gp = fin.loc[gp_label].dropna()
                rev2 = rev_row.dropna()
                if len(gp) >= 1 and len(rev2) >= 1:
                    gm = gp.values[-1] / rev2.values[-1]
                    result['gross_margin'] = round(gm, 3)

    except Exception as e:
        result['error'] = str(e)[:60]

    return result


def fmt_earnings(e: dict) -> str:
    if e.get('error'):
        return ''
    parts = []
    if e['profit_turn']:
        parts.append('🔥 흑자전환')
    elif e['eps_positive_streak'] > 0:
        parts.append(f"✅ 흑자 {e['eps_positive_streak']}Q 연속")
    if e['rev_accel']:
        parts.append(f"📈 매출가속 YoY+{e['rev_growth_yoy']*100:.0f}%")
    elif e['rev_growth_yoy'] is not None and e['rev_growth_yoy'] > 0:
        parts.append(f"매출 YoY+{e['rev_growth_yoy']*100:.0f}%")
    if e['gross_margin'] is not None:
        parts.append(f"GP마진 {e['gross_margin']*100:.0f}%")
    if e['net_income_q']:
        ni_str = ' → '.join(f"{v:+.0f}M" for v in e['net_income_q'][-4:])
        parts.append(f"순이익(분기): {ni_str}")
    return '\n  '.join(parts)
