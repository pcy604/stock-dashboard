"""
백테스트 엔진 — 주봉 신호 검증
- 유니버스  : KR 1000억+, US $3B+
- 기간      : 2021-01-01 ~ 현재 (5년)
- 타임프레임: 주봉 (weekly)
- 캐싱      : data/price_cache/*.parquet (최초 1회 다운로드)
- 검증 항목 : 개별 신호 6개 + 주요 조합 5개
- 성과 지표 : 발생수 / 승률 / 평균수익 / 기대값 / 샤프 / 중앙값
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import time, threading, warnings, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr

warnings.filterwarnings('ignore')
socket.setdefaulttimeout(12)   # FDR hang 방지: 12초 초과 시 OSError

CACHE_DIR  = Path('data/price_cache')
START_DATE = '2021-01-01'

# 신호 파라미터 (screener와 동일)
VOL_RATIO_MIN  = 2.5
ALREADY_UP_MAX = 50.0
MA5_MIN_WEEKS  = 5

# ── 실거래 비용 (편도 기준) ────────────────────────────────────────────
# KR: 증권사 수수료 0.015% (온라인), 증권거래세 0.18%(매도), 슬리피지 0.1%
# US: 수수료 0.025% (양방향), 슬리피지 0.1%
# → 왕복(매수+매도) 합산
COSTS = {
    'KR': 0.015/100 + 0.18/100 + 0.1/100*2,  # ~0.395%
    'US': 0.025/100*2 + 0.1/100*2,            # ~0.25%
}

# 벤치마크 심볼
BENCHMARK = {'KR': 'KS11', 'US': 'SPY'}

_lock = threading.Lock()


# ══════════════════════════════════════════════════════════════════
# 1. 가격 데이터 다운로드 & 캐싱
# ══════════════════════════════════════════════════════════════════

def _cache_path(sym: str) -> Path:
    return CACHE_DIR / f"{sym.replace('/', '_')}.parquet"


def _fetch(sym):
    df = fdr.DataReader(sym, START_DATE)
    if df.empty or len(df) < 200:
        return None
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
    df.index = pd.to_datetime(df.index).tz_localize(None)
    return df


def _load_or_download(sym: str, force: bool = False):
    cp = _cache_path(sym)
    if cp.exists() and not force:
        try:
            return pd.read_parquet(cp)
        except:
            pass
    try:
        time.sleep(0.04)
        df = _fetch(sym)   # socket.setdefaulttimeout(12) 로 hang 방지
        if df is None:
            return None
        df.to_parquet(cp)
        return df
    except:
        return None


def download_all(pairs: list, market: str, workers: int = 8, force: bool = False) -> dict:
    """병렬 다운로드 + 캐싱. 이미 캐시 있으면 즉시 로드."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    total   = len(pairs)
    counter = [0]
    results = {}

    def _run(item):
        sym, name = item
        df = _load_or_download(sym, force)
        with _lock:
            counter[0] += 1
            cached = '캐시' if _cache_path(sym).exists() else '다운'
            if counter[0] % 100 == 0 or counter[0] == total:
                print(f"\r  [{market}] {counter[0]}/{total} ({cached})     ", end='', flush=True)
        return sym, df

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_run, item): item[0] for item in pairs}
        for future in as_completed(futures):
            try:
                sym, df = future.result(timeout=20)
                if df is not None:
                    results[sym] = df
            except Exception:
                pass
    print()
    return results


# ══════════════════════════════════════════════════════════════════
# 2. 신호 + 수익률 계산 (완전 벡터라이즈)
# ══════════════════════════════════════════════════════════════════

def compute_signals_returns(daily_df: pd.DataFrame) -> pd.DataFrame | None:
    """
    일봉 → 주봉 변환 후 모든 신호 + 순방향 수익률 계산.
    look-ahead bias 없음: 모든 rolling은 shift(1) 기반.
    """
    try:
        wdf = daily_df.resample('W-SUN').agg(
            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        ).dropna(subset=['Close'])
        if len(wdf) < 60:
            return None

        c, h, l, o, v = wdf['Close'], wdf['High'], wdf['Low'], wdf['Open'], wdf['Volume']

        # ── 이동평균 ──────────────────────────────────────────────
        ma5   = c.rolling(5).mean()
        ma20  = c.rolling(20).mean()
        ma60  = c.rolling(60).mean()
        ma120 = c.rolling(120).mean()

        # ── RSI ───────────────────────────────────────────────────
        delta = c.diff()
        gain  = delta.clip(lower=0).rolling(14).mean()
        loss  = (-delta.clip(upper=0)).rolling(14).mean()
        rsi   = 100 - 100 / (1 + gain / (loss + 1e-9))

        # ── MACD ──────────────────────────────────────────────────
        ema12     = c.ewm(span=12, adjust=False).mean()
        ema26     = c.ewm(span=26, adjust=False).mean()
        macd      = ema12 - ema26
        macd_sig  = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - macd_sig

        # ── 캔들 공통 ─────────────────────────────────────────────
        rng        = (h - l).replace(0, np.nan)
        body_ratio = (c - o).abs() / rng
        close_pos  = (c - l) / rng
        is_bull    = c > o

        # ── 신호 1: 52주 신고가 ───────────────────────────────────
        high_52w = h.shift(1).rolling(52, min_periods=26).max()
        dist_52w = (c / high_52w.replace(0, np.nan) - 1) * 100
        sig_52w  = dist_52w >= -3.0

        # ── 신호 2: 거래량 폭발 ───────────────────────────────────
        avg_vol    = v.shift(1).rolling(60, min_periods=20).mean().replace(0, np.nan)
        vol_ratio  = v / avg_vol
        low_60     = l.rolling(60, min_periods=10).min().replace(0, np.nan)
        already_up = (c / low_60 - 1) * 100
        sig_vol    = (
            (vol_ratio >= VOL_RATIO_MIN) &
            (body_ratio >= 0.5) &
            (close_pos  >= 0.6) &
            is_bull &
            (already_up < ALREADY_UP_MAX)
        )

        # ── 신호 3: 5주선 라이딩 ─────────────────────────────────
        above_ma5  = c > ma5
        ma5_rising = ma5 > ma5.shift(MA5_MIN_WEEKS)
        max_dip    = ((l - ma5) / ma5.replace(0, np.nan)).rolling(MA5_MIN_WEEKS).min() * 100
        sig_ma5    = above_ma5 & ma5_rising & (max_dip > -3.0)

        # ── 신호 4: 컵위드핸들 (간소화) ──────────────────────────
        handle_hi  = h.rolling(15).max().replace(0, np.nan)
        handle_lo  = l.rolling(15).min()
        h_range    = (handle_hi - handle_lo) / handle_hi * 100
        sig_cup    = (h_range <= 15) & (dist_52w >= -12) & (dist_52w <= 0)

        # ── 신호 5: 이평선 수렴 ───────────────────────────────────
        ma_stack      = pd.concat([ma5, ma20, ma60, ma120], axis=1)
        valid_mas     = ma_stack.notna().all(axis=1)
        ma_max        = ma_stack.max(axis=1)
        ma_min        = ma_stack.min(axis=1)
        spread_now    = (ma_max - ma_min) / c.replace(0, np.nan) * 100
        spread_prev   = spread_now.shift(15)
        converging    = spread_now < spread_prev * 0.85
        golden_cross  = (ma5 > ma20) & (ma5.shift(6) <= ma20.shift(6))
        all_above_mas = (c > ma5) & (c > ma20) & (c > ma60) & (c > ma120)
        sig_maconv    = valid_mas & (
            (all_above_mas | golden_cross) & (converging | golden_cross)
        )

        # ── 신호 6: RSI/MACD ─────────────────────────────────────
        macd_cross   = (macd > macd_sig) & (macd.shift(1) <= macd_sig.shift(1))
        rsi_bounce   = (rsi > 32) & (rsi.rolling(6).min().shift(1) < 33)
        rsi_50_cross = (rsi > 50) & (rsi.shift(3) < 50)
        sig_rsimacd  = macd_cross | rsi_bounce | rsi_50_cross

        # ── 하락 필터 (공통 적용) ────────────────────────────────
        recent_high = h.shift(1).rolling(4).max().replace(0, np.nan)
        prev_close  = c.shift(1).replace(0, np.nan)
        not_falling = (
            ((c / recent_high - 1) * 100 >= -7) &
            ((c / prev_close  - 1) * 100 >= -5)
        )
        for s in [sig_52w, sig_vol, sig_ma5, sig_cup, sig_maconv, sig_rsimacd]:
            s &= not_falling

        # ── 순방향 수익률 (look-ahead) ────────────────────────────
        ret_1w  = c.shift(-1)  / c - 1
        ret_4w  = c.shift(-4)  / c - 1
        ret_13w = c.shift(-13) / c - 1

        return pd.DataFrame({
            'sig_52w':     sig_52w,
            'sig_vol':     sig_vol,
            'sig_ma5':     sig_ma5,
            'sig_cup':     sig_cup,
            'sig_maconv':  sig_maconv,
            'sig_rsimacd': sig_rsimacd,
            'vol_ratio':   vol_ratio,
            'dist_52w':    dist_52w,
            'ret_1w':      ret_1w,
            'ret_4w':      ret_4w,
            'ret_13w':     ret_13w,
        })
    except Exception as e:
        import traceback; traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════
# 3. 집계 & 통계
# ══════════════════════════════════════════════════════════════════

def _stats(signal: pd.Series, returns: pd.Series, cost: float = 0.0) -> dict | None:
    mask = signal.fillna(False).astype(bool)
    rets_gross = returns[mask].dropna()
    if len(rets_gross) < 10:
        return None

    rets = rets_gross - cost  # 비용 차감

    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    wr     = len(wins) / len(rets)
    ag     = float(wins.mean())   if len(wins)   > 0 else 0.0
    al     = float(losses.mean()) if len(losses) > 0 else 0.0
    ev     = wr * ag + (1 - wr) * al
    sharpe = float(rets.mean() / rets.std() * 52**0.5) if rets.std() > 0 else 0.0
    ev_gross = float((rets_gross).mean()) * 100

    # 최대 낙폭 (equity curve 기반 단순 추정)
    cum = (1 + rets.sort_index()).cumprod()
    roll_max = cum.cummax()
    dd = (cum - roll_max) / roll_max
    max_dd = float(dd.min()) * 100

    return {
        'count':    len(rets),
        'win_rate': round(wr * 100, 1),
        'avg_gain': round(ag * 100, 2),
        'avg_loss': round(al * 100, 2),
        'ev':       round(ev * 100, 2),       # 비용 차감 후
        'ev_gross': round(ev_gross, 2),        # 비용 차감 전
        'cost_pct': round(cost * 100, 3),      # 적용된 비용
        'sharpe':   round(sharpe, 2),
        'median':   round(float(rets.median()) * 100, 2),
        'max_dd':   round(max_dd, 2),
    }


def run_backtest(price_kr: dict, price_us: dict) -> pd.DataFrame:
    """전종목 신호 계산 → 하나의 DataFrame으로 합치기"""
    frames = []
    for market, price_data in [('KR', price_kr), ('US', price_us)]:
        print(f"  [{market}] {len(price_data)}개 신호 계산 중...")
        done = 0
        for sym, df in price_data.items():
            sig_df = compute_signals_returns(df)
            if sig_df is not None and len(sig_df) > 0:
                sig_df['market'] = market
                sig_df['sym']    = sym
                sig_df = sig_df[sig_df.index >= START_DATE]
                if len(sig_df) > 0:
                    frames.append(sig_df)
            done += 1
            if done % 200 == 0 or done == len(price_data):
                print(f"\r    {done}/{len(price_data)} 완료...", end='', flush=True)
        print()
    return pd.concat(frames) if frames else pd.DataFrame()


def get_benchmark_returns(market: str) -> dict:
    """벤치마크(KOSPI / SPY) 주봉 수익률 계산"""
    sym = BENCHMARK.get(market)
    if not sym:
        return {}
    try:
        cp = CACHE_DIR / f"_benchmark_{sym}.parquet"
        if cp.exists():
            df = pd.read_parquet(cp)
        else:
            df = fdr.DataReader(sym, START_DATE)
            df.to_parquet(cp)
        df.index = pd.to_datetime(df.index).tz_localize(None)
        c = df['Close'].resample('W-SUN').last().dropna()
        ret_4w  = c.shift(-4)  / c - 1
        ret_13w = c.shift(-13) / c - 1
        bh_4w   = float(ret_4w.dropna().mean()) * 100
        bh_13w  = float(ret_13w.dropna().mean()) * 100
        # 연율화 수익률 (보유 4주 기준 × 13회)
        ann = float((1 + c.pct_change().dropna().mean()) ** 52 - 1) * 100
        return {
            'symbol':   sym,
            'bh_4w':    round(bh_4w, 2),
            'bh_13w':   round(bh_13w, 2),
            'ann_ret':  round(ann, 2),
        }
    except Exception as e:
        print(f"  [벤치마크 오류] {e}")
        return {}


# ══════════════════════════════════════════════════════════════════
# 4. 리포트 생성
# ══════════════════════════════════════════════════════════════════

SIGNAL_LABELS = {
    'sig_52w':     '52주신고가',
    'sig_vol':     '거래량폭발',
    'sig_cup':     '컵위드핸들',
    'sig_ma5':     '5주선라이딩',
    'sig_maconv':  '이평선수렴',
    'sig_rsimacd': 'RSI/MACD',
}

COMBO_LABELS = {
    '52주+거래량':     ('sig_52w', 'sig_vol'),
    '52주+컵핸들':     ('sig_52w', 'sig_cup'),
    '52주+이평수렴':   ('sig_52w', 'sig_maconv'),
    '거래량+RSI/MACD': ('sig_vol', 'sig_rsimacd'),
    '52주+거래량+RSI': ('sig_52w', 'sig_vol', 'sig_rsimacd'),
}


def build_report(combined: pd.DataFrame, market: str = 'ALL') -> str:
    df = combined if market == 'ALL' else combined[combined['market'] == market]
    if df.empty:
        return f"[{market}] 데이터 없음"
    n_stocks   = df['sym'].nunique()
    date_range = f"{df.index.min().date()} ~ {df.index.max().date()}"

    # 벤치마크
    bm_lines = []
    for mkt in (['KR', 'US'] if market == 'ALL' else [market]):
        bm = get_benchmark_returns(mkt)
        if bm:
            bm_lines.append(
                f"  {mkt} 벤치마크({bm['symbol']}): "
                f"연환산 {bm['ann_ret']:+.1f}%  "
                f"4주평균 {bm['bh_4w']:+.2f}%  "
                f"13주평균 {bm['bh_13w']:+.2f}%"
            )

    header = [
        f"\n{'═'*78}",
        f"  📊 백테스트 결과  |  {market}  |  {date_range}  |  {n_stocks}개 종목",
        f"  [비용 반영: KR ~0.40% / US ~0.25% 왕복, 슬리피지 포함]",
        f"{'═'*78}",
    ] + bm_lines

    body = []
    for ret_col, label, period_wks in [
        ('ret_1w',  '1주 후',  1),
        ('ret_4w',  '4주 후',  4),
        ('ret_13w', '13주 후', 13),
    ]:
        body.append(f"\n  ── {label} 수익률 (비용 차감 후) ────────────────────────────────")
        body.append(
            f"  {'신호':<18} {'발생':>5}  {'승률':>6}  {'총EV':>7}  {'순EV':>7}  "
            f"{'샤프':>5}  {'중앙값':>7}  {'최대낙폭':>8}  {'vs BM':>7}"
        )
        body.append(f"  {'─'*18} {'─'*5}  {'─'*6}  {'─'*7}  {'─'*7}  {'─'*5}  {'─'*7}  {'─'*8}  {'─'*7}")

        rows = []
        for mkt_filter in (['KR', 'US'] if market == 'ALL' else [market]):
            df_m = df if market == 'ALL' else df
            df_m = df[df['market'] == mkt_filter] if market == 'ALL' else df
            cost = COSTS.get(mkt_filter, 0.003)
            bm   = get_benchmark_returns(mkt_filter)
            bm_ret = bm.get(f'bh_{period_wks}w') if bm and f'bh_{period_wks}w' in bm else None

            # 개별 신호
            for col, name in SIGNAL_LABELS.items():
                if col not in df_m.columns: continue
                st = _stats(df_m[col], df_m[ret_col], cost=cost)
                if st:
                    rows.append((f"[{mkt_filter}] {name}", st, bm_ret))

            # 조합 신호
            for name, cols in COMBO_LABELS.items():
                if not all(c in df_m.columns for c in cols): continue
                combo = df_m[cols[0]].copy()
                for c in cols[1:]:
                    combo = combo & df_m[c]
                st = _stats(combo, df_m[ret_col], cost=cost)
                if st:
                    rows.append((f"[{mkt_filter}] {name}", st, bm_ret))

        rows.sort(key=lambda x: -x[1]['ev'])

        for name, st, bm_ret in rows:
            flag = '✅' if st['ev'] > 1.0 else ('⚠️' if st['ev'] > 0 else '❌')
            ev_g  = f"+{st['ev_gross']:.2f}%"
            ev_n  = f"{st['ev']:+.2f}%"
            med_s = f"{st['median']:+.2f}%"
            dd_s  = f"{st['max_dd']:.1f}%"
            vs_bm = f"{st['ev'] - bm_ret:+.2f}%" if bm_ret is not None else '   -  '
            body.append(
                f"{flag} {name:<24} {st['count']:>5}회  "
                f"{st['win_rate']:>5.1f}%  "
                f"{ev_g:>7}  "
                f"{ev_n:>7}  "
                f"{st['sharpe']:>5.2f}  "
                f"{med_s:>7}  "
                f"{dd_s:>8}  "
                f"{vs_bm:>7}"
            )

    footer = [
        f"\n  {'─'*76}",
        f"  총EV=비용전 기대값  순EV=비용후 기대값  vs BM=순EV-벤치마크 4주평균수익",
        f"  ✅ 순EV > +1%   ⚠️ 순EV 0~+1%   ❌ 순EV < 0%",
        f"  샤프: 연환산(√52)  최대낙폭: equity curve 기준",
        f"  비용: KR 수수료0.015%+거래세0.18%+슬리피지0.2%  "
        f"US 수수료0.05%+슬리피지0.2%",
        f"  ⚠️ 생존편향: 유니버스가 '현재 상장 종목'이라 상장폐지·실패 종목이 빠짐.",
        f"     → 승률·기대값이 실제보다 낙관적으로 나옴. 참고 확률로만 보고 실투자 전 페이퍼 검증 필수.",
    ]

    return '\n'.join(header + body + footer)
