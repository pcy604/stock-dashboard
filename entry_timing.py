"""
entry_timing.py — 일봉 기반 진입 타이밍 판단
주봉 신호 발생 종목에 대해 "지금 사도 괜찮은가?"를 일봉 데이터로 체크

등급:
  🟢 진입적정  — 지금 진입 좋음
  🟡 눌림대기  — 조금 더 올라왔거나 조정 대기
  🔴 추격위험  — 이미 너무 올라 손익비 불리
  ⚪ 데이터없음

판단 기준:
  1. 확장도 (Extension)  — 주봉 신고가 신호 이후 얼마나 올랐나
  2. 거래량 확인         — 오늘 거래량 >= 20일 평균
  3. RSI 과매수 여부     — RSI(14일) < 75
  4. 일봉 MA5 위치       — 현재가 > 일봉 MA5 (단기 추세 유지)
  5. 당일 갭·급등 여부   — 오늘 시가 대비 이미 +3% 이상 오른 경우 추격 위험
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# 파라미터
MAX_CHASE_PCT      = 5.0   # 주봉 종가 기준 최대 추격 허용 % (이 이상이면 눌림대기)
DANGER_CHASE_PCT   = 15.0  # 이 이상이면 추격위험
RSI_OVERBOUGHT     = 75    # RSI 이 이상이면 과매수 경고
RSI_DANGER         = 80    # RSI 이 이상이면 추격위험
VOL_MIN_RATIO      = 0.8   # 진입일 최소 거래량 / 20일평균 (이 미만이면 거래량 미확인)
INTRADAY_CHASE_PCT = 3.0   # 오늘 장중 이미 +N% 이상 올랐으면 당일 추격 경고


def calc_rsi(closes: pd.Series, period: int = 14) -> pd.Series:
    delta = closes.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    return 100 - 100 / (1 + gain / (loss + 1e-9))


def check_entry(sym: str, market: str,
                weekly_signal_close: float | None = None) -> dict:
    """
    sym                  : 티커 (KR: '005930', US: 'AAPL')
    market               : 'KR' or 'US'
    weekly_signal_close  : 주봉 신호 발생 시 종가 (없으면 최근 주봉 종가 추정)

    Returns dict:
      grade      : '🟢 진입적정' | '🟡 눌림대기' | '🔴 추격위험' | '⚪ 데이터없음'
      score      : int (높을수록 좋음, -5 ~ +5)
      reasons    : list[str]
      cur_price  : float | None
      rsi        : float | None
      vol_ratio  : float | None
      ext_pct    : float | None  (주봉 종가 기준 현재 확장도 %)
    """
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')
        code  = sym.replace('.KS', '').replace('.KQ', '')
        df    = fdr.DataReader(code if market == 'KR' else sym, start)
        if df is None or len(df) < 30:
            return _no_data()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df = df[['Open','High','Low','Close','Volume']].dropna()
        if len(df) < 20:
            return _no_data()
    except Exception:
        return _no_data()

    close   = df['Close']
    cur_px  = float(close.iloc[-1])
    open_px = float(df['Open'].iloc[-1])
    vol     = float(df['Volume'].iloc[-1])

    # ── 지표 계산 ──────────────────────────────────────────────────
    ma5   = close.rolling(5).mean()
    ma20  = close.rolling(20).mean()
    rsi   = calc_rsi(close)
    avg_vol20 = df['Volume'].rolling(20).mean()

    cur_rsi      = float(rsi.iloc[-1]) if not pd.isna(rsi.iloc[-1]) else None
    cur_ma5      = float(ma5.iloc[-1])  if not pd.isna(ma5.iloc[-1])  else None
    cur_ma20     = float(ma20.iloc[-1]) if not pd.isna(ma20.iloc[-1]) else None
    cur_avg_vol  = float(avg_vol20.iloc[-1]) if not pd.isna(avg_vol20.iloc[-1]) else None
    vol_ratio    = vol / cur_avg_vol if cur_avg_vol and cur_avg_vol > 0 else None

    # 주봉 신호 종가 = 제공 안 됐으면 5일 전 종가로 추정
    if weekly_signal_close is None or weekly_signal_close <= 0:
        weekly_signal_close = float(close.iloc[-5]) if len(close) >= 5 else cur_px
    ext_pct = (cur_px / weekly_signal_close - 1) * 100

    # 당일 갭·장중 상승
    intraday_up = (cur_px / open_px - 1) * 100 if open_px > 0 else 0

    # ── 점수 산출 ──────────────────────────────────────────────────
    score   = 0
    reasons = []

    # 1. 확장도
    if ext_pct < MAX_CHASE_PCT:
        score += 2
        reasons.append(f'확장 {ext_pct:+.1f}% (주봉 종가 기준) ✅')
    elif ext_pct < DANGER_CHASE_PCT:
        score -= 1
        reasons.append(f'확장 {ext_pct:+.1f}% — 눌림 대기 권장 ⚠️')
    else:
        score -= 3
        reasons.append(f'확장 {ext_pct:+.1f}% — 이미 과도 상승 ❌')

    # 2. 거래량
    if vol_ratio is not None:
        if vol_ratio >= 1.5:
            score += 2
            reasons.append(f'거래량 {vol_ratio:.1f}x (폭발) ✅')
        elif vol_ratio >= VOL_MIN_RATIO:
            score += 1
            reasons.append(f'거래량 {vol_ratio:.1f}x (정상) ✅')
        else:
            score -= 1
            reasons.append(f'거래량 {vol_ratio:.1f}x (부족) ⚠️')

    # 3. RSI
    if cur_rsi is not None:
        if cur_rsi < RSI_OVERBOUGHT:
            score += 1
            reasons.append(f'RSI {cur_rsi:.0f} (과매수 아님) ✅')
        elif cur_rsi < RSI_DANGER:
            score -= 1
            reasons.append(f'RSI {cur_rsi:.0f} (과매수 주의) ⚠️')
        else:
            score -= 2
            reasons.append(f'RSI {cur_rsi:.0f} (과매수 위험) ❌')

    # 4. MA5 위치
    if cur_ma5:
        if cur_px >= cur_ma5:
            score += 1
            reasons.append(f'MA5({cur_ma5:.1f}) 위 — 단기 추세 유지 ✅')
        elif cur_ma20 and cur_px >= cur_ma20:
            reasons.append(f'MA5 아래, MA20 위 — 단기 조정 중 ⚠️')
        else:
            score -= 1
            reasons.append(f'MA5·MA20 모두 아래 ❌')

    # 5. 당일 갭·장중 급등
    if intraday_up > INTRADAY_CHASE_PCT:
        score -= 1
        reasons.append(f'장중 이미 +{intraday_up:.1f}% 상승 — 당일 추격 주의 ⚠️')
    elif intraday_up < -3:
        score -= 1
        reasons.append(f'장중 {intraday_up:.1f}% 하락 — 당일 약세 ⚠️')

    # ── 등급 분류 ──────────────────────────────────────────────────
    if score >= 4:
        grade = '🟢 진입적정'
    elif score >= 1:
        grade = '🟡 눌림대기'
    else:
        grade = '🔴 추격위험'

    return {
        'grade':     grade,
        'score':     score,
        'reasons':   reasons,
        'cur_price': cur_px,
        'rsi':       round(cur_rsi, 1) if cur_rsi else None,
        'vol_ratio': round(vol_ratio, 2) if vol_ratio else None,
        'ext_pct':   round(ext_pct, 1),
        'ma5':       round(cur_ma5, 2) if cur_ma5 else None,
    }


def _no_data() -> dict:
    return {
        'grade': '⚪ 데이터없음', 'score': 0, 'reasons': [],
        'cur_price': None, 'rsi': None, 'vol_ratio': None,
        'ext_pct': None, 'ma5': None,
    }


def batch_check(stocks: list, max_workers: int = 6) -> dict:
    """
    stocks: [{'sym': str, 'market': str, 'dist_52w': float | None}, ...]
    Returns: {sym: check_entry result}
    """
    import concurrent.futures, time
    results = {}

    def _run(s):
        time.sleep(0.05)
        return s['sym'], check_entry(
            s['sym'], s.get('market', 'US'),
            weekly_signal_close=None,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(_run, s): s['sym'] for s in stocks}
        for fut in concurrent.futures.as_completed(futs):
            try:
                sym, res = fut.result(timeout=20)
                results[sym] = res
            except Exception:
                results[futs[fut]] = _no_data()
    return results


if __name__ == '__main__':
    # 테스트
    test = [
        {'sym': 'AAPL',   'market': 'US'},
        {'sym': 'TSLA',   'market': 'US'},
        {'sym': '005930', 'market': 'KR'},
    ]
    for s in test:
        r = check_entry(s['sym'], s['market'])
        print(f"[{s['sym']}] {r['grade']}  점수:{r['score']}  RSI:{r['rsi']}  "
              f"거래량:{r['vol_ratio']}x  확장:{r['ext_pct']}%")
        for reason in r['reasons']:
            print(f"  • {reason}")
        print()
