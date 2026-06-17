import pandas as pd
import numpy as np


def _add_indicators(df):
    df = df.copy()
    for p in [5, 20, 60, 120]:
        df[f'MA{p}'] = df['Close'].rolling(p).mean()

    delta = df['Close'].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['RSI'] = 100 - (100 / (1 + rs))

    ema12 = df['Close'].ewm(span=12, adjust=False).mean()
    ema26 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = ema12 - ema26
    df['Signal_line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    df['MACD_hist'] = df['MACD'] - df['Signal_line']
    return df


def sig_52w_high(df):
    """52주 신고가 근접 또는 돌파"""
    if len(df) < 200:
        return False, {}
    high_52w = df['High'].iloc[-252:-1].max() if len(df) >= 252 else df['High'].iloc[:-1].max()
    curr = df['Close'].iloc[-1]
    dist = (curr / high_52w - 1) * 100
    ok = dist >= -3.0  # 신고가 3% 이내 또는 돌파
    return ok, {'52w_high': round(high_52w, 2), 'dist_pct': round(dist, 1)}


def sig_ma5_ride(df, min_days=5):
    """5일선 위에서 연속 상승"""
    df = _add_indicators(df)
    if df['MA5'].iloc[-min_days:].isna().any():
        return False, {}
    recent = df.iloc[-min_days:]
    above = (recent['Close'] > recent['MA5']).all()
    rising = df['MA5'].iloc[-1] > df['MA5'].iloc[-min_days]
    max_dip = ((recent['Low'] - recent['MA5']) / recent['MA5']).min() * 100
    ok = above and rising and max_dip > -3.0
    return ok, {'ma5': round(df['MA5'].iloc[-1], 2), 'days': min_days, 'max_dip_pct': round(max_dip, 1)}


def sig_cup_handle(df):
    """컵위드핸들 돌파 직전 패턴"""
    if len(df) < 120:
        return False, {}

    # 정수 인덱스로 작업 (DatetimeIndex idxmax 버그 회피)
    df_r = df.reset_index(drop=True)
    lookback = min(len(df_r) - 5, 252)
    w = df_r.iloc[-lookback:-5]

    if w.empty or w['High'].isna().all():
        return False, {}

    # 좌측 고점
    peak_pos_in_w = int(w['High'].idxmax())
    peak_price = w['High'].max()
    peak_pos = w.index.get_loc(peak_pos_in_w)

    if peak_pos < 20 or peak_pos > len(w) - 20:
        return False, {}

    # 컵 바닥
    cup = w.iloc[peak_pos:]
    bottom_price = cup['Low'].min()
    cup_depth = (peak_price - bottom_price) / peak_price

    if not (0.12 <= cup_depth <= 0.65):
        return False, {}

    # 우측 림 회복
    bottom_pos_in_cup = cup['Low'].idxmin()
    recovery = cup.loc[bottom_pos_in_cup:]
    if len(recovery) < 5:
        return False, {}
    right_rim = recovery['High'].max()
    recovery_ratio = (right_rim - bottom_price) / (peak_price - bottom_price + 1e-9)

    if recovery_ratio < 0.7:
        return False, {}

    # 핸들: 최근 15일 좁은 레인지
    handle = df_r.iloc[-15:]
    h_range = (handle['High'].max() - handle['Low'].min()) / (handle['High'].max() + 1e-9) * 100
    curr = df_r['Close'].iloc[-1]
    dist_from_peak = (peak_price - curr) / peak_price * 100

    ok = (0 <= dist_from_peak <= 12) and (h_range <= 15)
    return ok, {
        'peak': round(peak_price, 2),
        'cup_depth_pct': round(cup_depth * 100, 1),
        'dist_to_breakout_pct': round(dist_from_peak, 1),
        'handle_range_pct': round(h_range, 1),
    }


def sig_ma_convergence(df):
    """이평선 수렴 → 골든크로스 임박"""
    df = _add_indicators(df)
    mas = ['MA5', 'MA20', 'MA60', 'MA120']
    if df[mas].iloc[-1].isna().any():
        return False, {}

    curr = df['Close'].iloc[-1]
    ma_vals = {m: df[m].iloc[-1] for m in mas}

    # 모든 이평선이 현재가 아래에 있거나 이제 막 올라온 상태
    all_below = all(curr > v for v in ma_vals.values())

    # 이평선 스프레드 좁아지는 중
    spread_now = (max(ma_vals.values()) - min(ma_vals.values())) / curr * 100
    spread_prev = None
    if len(df) >= 130:
        ma_vals_prev = {m: df[m].iloc[-15] for m in mas}
        spread_prev = (max(ma_vals_prev.values()) - min(ma_vals_prev.values())) / df['Close'].iloc[-15] * 100

    converging = spread_prev is not None and spread_now < spread_prev * 0.85

    # 골든크로스: 5일선이 최근 20일선 상향 돌파
    cross_now = df['MA5'].iloc[-1] > df['MA20'].iloc[-1]
    cross_prev = df['MA5'].iloc[-6] <= df['MA20'].iloc[-6]
    golden_cross = cross_now and cross_prev

    ok = (all_below or golden_cross) and (converging or golden_cross)
    return ok, {
        'spread_pct': round(spread_now, 1),
        'converging': converging,
        'golden_cross': golden_cross,
        'ma5': round(ma_vals['MA5'], 2),
        'ma20': round(ma_vals['MA20'], 2),
    }


def sig_rsi_macd(df):
    """RSI 과매도 회복 + MACD 골든크로스"""
    df = _add_indicators(df)
    if df['RSI'].iloc[-3:].isna().any():
        return False, {}

    rsi = df['RSI'].iloc[-1]

    # MACD 골든크로스 (최근 3일 이내)
    macd_cross = any(
        df['MACD'].iloc[-i] > df['Signal_line'].iloc[-i] and
        df['MACD'].iloc[-i - 1] <= df['Signal_line'].iloc[-i - 1]
        for i in range(1, 4)
    )

    # 히스토그램 3연속 증가
    hist_up = (df['MACD_hist'].iloc[-1] > df['MACD_hist'].iloc[-2] > df['MACD_hist'].iloc[-3])

    # RSI 과매도 탈출 (30 이하에서 회복)
    rsi_bounce = rsi > 32 and df['RSI'].iloc[-6:-1].min() < 33

    # RSI 50선 돌파 (모멘텀 확인)
    rsi_50_cross = rsi > 50 and df['RSI'].iloc[-3] < 50

    ok = macd_cross or rsi_bounce or rsi_50_cross
    return ok, {
        'rsi': round(rsi, 1),
        'macd_cross': macd_cross,
        'rsi_bounce': rsi_bounce,
        'hist_up': hist_up,
        'rsi_50_cross': rsi_50_cross,
    }


def sig_volume_explosion(df, ratio=2.5):
    """거래량 폭발 + 강한 양봉 (상승 초기 한정)"""
    if len(df) < 20:
        return False, {}
    avg_vol = df['Volume'].iloc[-60:-1].mean()
    if avg_vol == 0:
        return False, {}
    today_vol = df['Volume'].iloc[-1]
    vol_ratio = today_vol / avg_vol

    candle_range = df['High'].iloc[-1] - df['Low'].iloc[-1]
    if candle_range == 0:
        return False, {}
    body = abs(df['Close'].iloc[-1] - df['Open'].iloc[-1])
    body_ratio = body / candle_range
    close_pos = (df['Close'].iloc[-1] - df['Low'].iloc[-1]) / candle_range
    is_bull = df['Close'].iloc[-1] > df['Open'].iloc[-1]

    # 박병창 원칙: 이미 +50% 이상 상승 후 거래량 급증 = 상투 신호 → 매수 신호 제외
    lookback = min(60, len(df) - 1)
    low_recent = df['Low'].iloc[-lookback:].min()
    curr_close = df['Close'].iloc[-1]
    already_up_pct = (curr_close / low_recent - 1) * 100 if low_recent > 0 else 0
    if already_up_pct > 50:
        return False, {'vol_ratio': round(vol_ratio, 1), 'skipped': 'extended'}

    ok = vol_ratio >= ratio and body_ratio >= 0.5 and close_pos >= 0.6 and is_bull
    return ok, {
        'vol_ratio': round(vol_ratio, 1),
        'body_pct': round(body_ratio * 100, 1),
        'close_pos_pct': round(close_pos * 100, 1),
        'up_from_low_pct': round(already_up_pct, 1),
    }


def run_all_signals(df, config=None):
    """모든 신호 실행 후 결과 딕셔너리 반환"""
    min_days = config.MA5_RIDE_MIN_DAYS if config else 5
    vol_ratio = config.VOLUME_EXPLOSION_RATIO if config else 2.5

    results = {}
    checks = [
        ('52w_high',        sig_52w_high(df)),
        ('ma5_ride',        sig_ma5_ride(df, min_days)),
        ('cup_handle',      sig_cup_handle(df)),
        ('ma_convergence',  sig_ma_convergence(df)),
        ('rsi_macd',        sig_rsi_macd(df)),
        ('volume',          sig_volume_explosion(df, vol_ratio)),
    ]
    for name, (ok, detail) in checks:
        results[name] = {'signal': ok, **detail}

    results['total_signals'] = sum(v['signal'] for v in results.values() if isinstance(v, dict) and 'signal' in v)
    return results
