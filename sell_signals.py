"""
매도 신호 엔진 — "언제 팔까"를 4가지 룰로 자동 점검 (살아남기 핵심)
─────────────────────────────────────────────────────────────────
연도별 백테스트 결론: 종목 선정 엣지는 약하다 → 돈은 '매도·리스크 관리'에서 난다.
멍거 inversion: "어떻게 이길까"보다 "어떻게 안 망할까".

매도 3종 (우선순위 순):
  ① 🔴 방어 손절   진입가 -손절% 도달 (진입이 틀림) — 가장 견고한 엣지, 100% 통제
  ② 🟢 분할 익절   목표가 도달 (절반 익절, 나머지는 계속 보유)
  ③ 🟡 시간 매도   N주째 제자리(±5%) — 자본 회수(기회비용)
  ④ ✅ 보유        위 어디에도 안 걸림 → 이기는 포지션은 안 건드림

※ 이평(MA) 이탈 매도는 뺐다 — 사후적으로 끼워맞춘 룰이고,
   백테스트상 가격 기반 청산은 추세장에서 오히려 손해(-16%p)였다.
   매도는 '미리 정한 손절·목표·시간' 같은 사전 규칙으로만 한다.
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
                  flat_band=5.0):
    """
    한 보유 종목의 매도 신호 평가 (사전 규칙만: 손절·목표·시간).
    반환: dict(signal, reason, action, current, pnl_pct, weeks_held)
    """
    w = _weekly(sym, market)
    if w is None or len(w) < 12:
        return {'signal': '⚪ 데이터없음', 'reason': '가격 조회 실패',
                'action': '확인필요', 'current': None, 'pnl_pct': None,
                'weeks_held': None}

    cur = float(w.iloc[-1])
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

    # ── 우선순위 평가 (사전 규칙) ──
    # ① 방어 손절
    if cur <= stop_px:
        return _r('🔴 방어손절', f'진입가 -{stop_pct:.0f}% 이탈 (현재 {pnl:+.1f}%)',
                  '전량 매도 — 진입이 틀림', cur, pnl, weeks_held)
    # ② 분할 익절 (목표 도달)
    if cur >= tgt_px:
        return _r('🟢 분할익절', f'목표 +{target_pct:.0f}% 도달 (현재 {pnl:+.1f}%)',
                  '절반 익절 + 나머지는 계속 보유', cur, pnl, weeks_held)
    # ③ 시간 매도 (제자리)
    if weeks_held is not None and weeks_held >= time_weeks and pnl is not None and abs(pnl) < flat_band:
        return _r('🟡 시간매도', f'{weeks_held}주째 제자리(±{flat_band:.0f}%) — 기회비용',
                  '자본 회수 → 더 강한 셋업으로', cur, pnl, weeks_held)
    # ④ 보유
    return _r('✅ 보유', f'손절·목표 사이 정상 보유 ({pnl:+.1f}%)' if pnl is not None else '정상 보유',
              '계속 보유 — 이기는 포지션은 안 건드림', cur, pnl, weeks_held)


def _r(signal, reason, action, cur, pnl, weeks):
    return {'signal': signal, 'reason': reason, 'action': action,
            'current': round(cur, 2) if cur else None,
            'pnl_pct': round(pnl, 1) if pnl is not None else None,
            'weeks_held': weeks}


if __name__ == '__main__':
    for sym, mkt, buy in [('005930', 'KR', 70000), ('AAPL', 'US', 200)]:
        r = evaluate_sell(sym, mkt, buy, buy_date='2026-03-01')
        print(f"{sym}: {r['signal']} | {r['reason']} | 현재 {r['current']} ({r['pnl_pct']}%)")
