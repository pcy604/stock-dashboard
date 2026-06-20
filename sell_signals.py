"""
매도 신호 엔진 — "언제 팔까"를 4가지 룰로 자동 점검 (살아남기 핵심)
─────────────────────────────────────────────────────────────────
연도별 백테스트 결론: 종목 선정 엣지는 약하다 → 돈은 '매도·리스크 관리'에서 난다.
멍거 inversion: "어떻게 이길까"보다 "어떻게 안 망할까".

매도 4종 (우선순위 순):
  ① 🔴 방어 손절   진입가 -손절% 도달 (진입이 틀림) — 가장 견고한 엣지, 100% 통제
  ② 🟠 추세 이탈   주봉 종가가 10주 이평 이탈 (노이즈 아닌 추세 붕괴)
  ③ 🟢 분할 익절   목표가 도달 (절반 익절 + 나머지는 추세까지)
  ④ 🟡 시간 매도   N주째 제자리(±5%) — 자본 회수(기회비용)
  ⑤ ✅ 보유        위 어디에도 안 걸림 → 이기는 포지션은 안 건드림

백테스트 교훈: 가격 트레일링 스톱은 추세장에서 독(-16%p) → ②는 '이평 이탈'로만.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

from datetime import datetime, timedelta


def _weekly(sym, market, days=400):
    """주봉 종가 시리즈 반환 (없으면 None)."""
    try:
        import FinanceDataReader as fdr
        import pandas as pd
        code = sym.replace('.KS', '').replace('.KQ', '')
        fdr_sym = code if market == 'KR' else sym
        start = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
        df = fdr.DataReader(fdr_sym, start)
        if df.empty:
            return None
        w = df['Close'].resample('W-SUN').last().dropna()
        return w if len(w) >= 12 else None
    except Exception:
        return None


def evaluate_sell(sym, market, buy_price, buy_date=None,
                  stop_pct=8.0, target_pct=20.0, time_weeks=8,
                  flat_band=5.0, regime_bear=False):
    """
    한 보유 종목의 매도 신호 평가.
    반환: dict(signal, reason, action, current, pnl_pct, ma10, weeks_held)
    """
    import math
    w = _weekly(sym, market)
    if w is None or len(w) < 12:
        return {'signal': '⚪ 데이터없음', 'reason': '가격 조회 실패',
                'action': '확인필요', 'current': None, 'pnl_pct': None,
                'ma10': None, 'weeks_held': None}

    cur = float(w.iloc[-1])
    ma10 = float(w.tail(10).mean())
    pnl = (cur / buy_price - 1) * 100 if buy_price else None

    weeks_held = None
    if buy_date:
        try:
            bd = datetime.strptime(str(buy_date)[:10], '%Y-%m-%d')
            weeks_held = int((datetime.now() - bd).days / 7)
        except Exception:
            pass

    stop_px = buy_price * (1 - stop_pct / 100)
    tgt_px = buy_price * (1 + target_pct / 100)

    # ── 우선순위 평가 ──
    # ① 방어 손절
    if cur <= stop_px:
        return _r('🔴 방어손절', f'진입가 -{stop_pct:.0f}% 이탈 (현재 {pnl:+.1f}%)',
                  '전량 매도 — 진입이 틀림', cur, pnl, ma10, weeks_held)
    # ② 추세 이탈 (10주 이평 아래)  — 약세장이면 더 엄격
    if cur < ma10:
        sev = '시장 약세장 동반 — ' if regime_bear else ''
        return _r('🟠 추세이탈', f'{sev}주봉 종가가 10주 이평({ma10:,.0f}) 이탈',
                  '전량/대부분 매도 — 추세 꺾임', cur, pnl, ma10, weeks_held)
    # ③ 분할 익절 (목표 도달, 추세는 살아있음)
    if cur >= tgt_px:
        return _r('🟢 분할익절', f'목표 +{target_pct:.0f}% 도달 (현재 {pnl:+.1f}%)',
                  '절반 익절 + 나머지는 10주 이평까지 보유', cur, pnl, ma10, weeks_held)
    # ④ 시간 매도 (제자리)
    if weeks_held is not None and weeks_held >= time_weeks and pnl is not None and abs(pnl) < flat_band:
        return _r('🟡 시간매도', f'{weeks_held}주째 제자리(±{flat_band:.0f}%) — 기회비용',
                  '자본 회수 → 더 강한 셋업으로', cur, pnl, ma10, weeks_held)
    # ⑤ 보유
    return _r('✅ 보유', f'추세 유지 (10주 이평 위, {pnl:+.1f}%)' if pnl is not None else '추세 유지',
              '계속 보유 — 이기는 포지션은 안 건드림', cur, pnl, ma10, weeks_held)


def _r(signal, reason, action, cur, pnl, ma10, weeks):
    return {'signal': signal, 'reason': reason, 'action': action,
            'current': round(cur, 2) if cur else None,
            'pnl_pct': round(pnl, 1) if pnl is not None else None,
            'ma10': round(ma10, 2) if ma10 else None, 'weeks_held': weeks}


def benchmark_is_bear(market):
    """벤치마크(코스피/SPY)가 13주 이평 아래면 약세장."""
    sym = 'KS11' if market == 'KR' else 'SPY'
    w = _weekly(sym, market, days=300)
    if w is None or len(w) < 13:
        return False
    return float(w.iloc[-1]) < float(w.tail(13).mean())


if __name__ == '__main__':
    # 간이 테스트
    for sym, mkt, buy in [('005930', 'KR', 70000), ('AAPL', 'US', 200)]:
        r = evaluate_sell(sym, mkt, buy, buy_date='2026-03-01')
        print(f"{sym}: {r['signal']} | {r['reason']} | 현재 {r['current']} ({r['pnl_pct']}%)")
