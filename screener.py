import sys
import os
import warnings
warnings.filterwarnings('ignore')

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import FinanceDataReader as fdr
import config
from signals import run_all_signals
from earnings import check_earnings, fmt_earnings
from telegram_notifier import send_message, build_message

os.makedirs(config.OUTPUT_DIR, exist_ok=True)

SIGNAL_LABELS = {
    '52w_high':       '📈 52주신고가',
    'ma5_ride':       '🚀 5일선라이딩',
    'cup_handle':     '🏆 컵위드핸들',
    'ma_convergence': '🔀 이평선수렴',
    'rsi_macd':       '⚡ RSI/MACD',
    'volume':         '💥 거래량폭발',
}


# ── 리샘플링 ────────────────────────────────────────────────────────

def to_weekly(df):
    return df.resample('W').agg(
        {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
    ).dropna(subset=['Close'])


def to_monthly(df):
    return df.resample('ME').agg(
        {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
    ).dropna(subset=['Close'])


# ── 종목 유니버스 ───────────────────────────────────────────────────

def get_us_symbols():
    if config.US_UNIVERSE == "CUSTOM":
        return config.US_CUSTOM_SYMBOLS
    try:
        if config.US_UNIVERSE == "SP500":
            url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
            syms = pd.read_html(url, header=0)[0]['Symbol'].str.replace('.', '-').tolist()
        elif config.US_UNIVERSE == "NASDAQ100":
            url = "https://en.wikipedia.org/wiki/Nasdaq-100"
            for t in pd.read_html(url):
                if 'Ticker' in t.columns:
                    syms = t['Ticker'].tolist()
                    break
        print(f"  → US 종목 {len(syms)}개 로드")
        return syms
    except Exception as e:
        print(f"  ⚠ US 유니버스 로드 실패({e}) → 커스텀 사용")
        return config.US_CUSTOM_SYMBOLS


def get_kr_symbols():
    if config.KR_UNIVERSE == "CUSTOM":
        return [(s, s) for s in config.KR_CUSTOM_SYMBOLS]
    try:
        from pykrx import stock
        idx_id = "1028" if config.KR_UNIVERSE == "KOSPI200" else "2150"
        tickers = stock.get_index_portfolio_deposit_file(idx_id)
        names = {t: stock.get_market_ticker_name(t) for t in tickers}
        print(f"  → KR 종목 {len(tickers)}개 로드")
        return [(t, names.get(t, t)) for t in tickers]
    except Exception as e:
        print(f"  ⚠ KR 유니버스 로드 실패({e})")
        return [(s, s) for s in config.KR_CUSTOM_SYMBOLS]


# ── 데이터 패치 ─────────────────────────────────────────────────────

def _clean(df):
    """공통 컬럼 정리"""
    df = df[['Open', 'High', 'Low', 'Close', 'Volume']].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None)
    df = df.dropna(subset=['Close'])
    return df if len(df) >= 60 else None


def fetch_us(symbol):
    try:
        start = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        df = fdr.DataReader(symbol, start)
        if df.empty:
            return None
        return _clean(df)
    except Exception:
        return None


def fetch_kr(ticker):
    try:
        start = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')
        df = fdr.DataReader(ticker, start)
        if df.empty:
            return None
        return _clean(df)
    except Exception:
        return None


# ── 신호 분석 (멀티 타임프레임) ───────────────────────────────────

def analyze(df, is_us=True):
    """일봉 + 주봉 + 월봉 신호 통합 분석"""
    # 일봉
    daily_res = run_all_signals(df, config)
    tf_active = []

    # 주봉
    weekly_res = None
    if config.USE_WEEKLY:
        try:
            wdf = to_weekly(df)
            if len(wdf) >= 30:
                weekly_res = run_all_signals(wdf, config)
                if weekly_res['total_signals'] >= 1:
                    tf_active.append('주봉')
        except:
            pass

    # 월봉
    monthly_res = None
    if config.USE_MONTHLY:
        try:
            mdf = to_monthly(df)
            if len(mdf) >= 12:
                monthly_res = run_all_signals(mdf, config)
                if monthly_res['total_signals'] >= 1:
                    tf_active.append('월봉')
        except:
            pass

    # 타임프레임 가중 합산
    total = daily_res['total_signals']
    if weekly_res:
        total += weekly_res['total_signals']
    if monthly_res:
        total += monthly_res['total_signals']

    daily_res['_total_cross_tf'] = total
    daily_res['_tf_labels'] = tf_active

    return daily_res


# ── 출력 포맷 ───────────────────────────────────────────────────────

def print_result(symbol, name, result, earnings, market):
    total = result['total_signals']
    stars = '★' * total + '☆' * max(0, 6 - total)
    label = f"[{market}] {symbol}" + (f" ({name})" if name != symbol else '')

    active = [SIGNAL_LABELS[k] for k, v in result.items()
              if isinstance(v, dict) and v.get('signal')]

    tf_line = ''
    if result.get('_tf_labels'):
        tf_line = f"\n  추가 타임프레임: {' | '.join(result['_tf_labels'])}"

    e_line = ''
    if earnings:
        e_str = fmt_earnings(earnings)
        if e_str:
            e_line = f"\n  실적: {e_str}"

    cup_info = ''
    if result.get('cup_handle', {}).get('signal'):
        d = result['cup_handle']
        cup_info = (f"\n  [컵] 깊이 {d.get('cup_depth_pct')}%  "
                    f"돌파까지 {d.get('dist_to_breakout_pct')}%  "
                    f"핸들 {d.get('handle_range_pct')}%")

    vol_info = ''
    if result.get('volume', {}).get('signal'):
        d = result['volume']
        vol_info = f"\n  [거래량] {d.get('vol_ratio')}배  봉몸통 {d.get('body_pct')}%"

    rsi_info = ''
    if 'rsi_macd' in result and isinstance(result['rsi_macd'], dict):
        rsi_info = f"\n  RSI: {result['rsi_macd'].get('rsi')}"

    print(
        f"\n{'─'*56}\n"
        f"{stars}  {label}\n"
        f"  신호: {' | '.join(active)}"
        f"{tf_line}{cup_info}{vol_info}{rsi_info}{e_line}"
    )


# ── 메인 ────────────────────────────────────────────────────────────

def screen_market(symbols, fetch_fn, market, name_map=None, is_us=True):
    hits = []
    for i, sym in enumerate(symbols):
        name = name_map.get(sym, sym) if name_map else sym
        print(f"\r  진행: {i+1}/{len(symbols)} ({sym})          ", end='', flush=True)

        time.sleep(0.5)  # rate limit 방지
        df = fetch_fn(sym)
        if df is None:
            continue

        result = analyze(df, is_us=is_us)

        # 일봉 기준 최소 신호 수 충족 여부
        if result['total_signals'] < config.MIN_SIGNALS_TO_SHOW:
            continue

        # 실적 데이터 (미국만)
        earnings = None
        if is_us and config.USE_EARNINGS:
            earnings = check_earnings(sym)

        hits.append((market, sym, name, result, earnings, result.get('_tf_labels', [])))
        print_result(sym, name, result, earnings, market)

    print()
    return hits


def main():
    now_str = datetime.now().strftime('%Y-%m-%d %H:%M')
    print(f"\n{'═'*56}")
    print(f"  📊 주식 스크리너  |  {now_str}")
    print(f"  최소 신호: {config.MIN_SIGNALS_TO_SHOW}개  |  "
          f"주봉: {'ON' if config.USE_WEEKLY else 'OFF'}  |  "
          f"월봉: {'ON' if config.USE_MONTHLY else 'OFF'}  |  "
          f"실적: {'ON' if config.USE_EARNINGS else 'OFF'}")
    print(f"{'═'*56}")

    all_hits = []

    if config.USE_US_MARKET:
        print("\n[미국 시장 스캔 중...]")
        syms = get_us_symbols()
        all_hits += screen_market(syms, fetch_us, 'US', is_us=True)

    if config.USE_KR_MARKET:
        print("\n[한국 시장 스캔 중...]")
        pairs = get_kr_symbols()
        name_map = {t: n for t, n in pairs}
        all_hits += screen_market([t for t, _ in pairs], fetch_kr, 'KR',
                                  name_map=name_map, is_us=False)

    # 요약
    print(f"\n{'═'*56}")
    print(f"  ✅ 신호 종목: {len(all_hits)}개")

    # CSV 저장
    if config.OUTPUT_CSV and all_hits:
        rows = []
        for market, sym, name, res, earn, tfs in all_hits:
            row = {
                'date': datetime.now().strftime('%Y-%m-%d'),
                'market': market, 'symbol': sym, 'name': name,
                'total_signals': res['total_signals'],
                'timeframes': ','.join(tfs),
            }
            for sig in ['52w_high', 'ma5_ride', 'cup_handle', 'ma_convergence', 'rsi_macd', 'volume']:
                row[sig] = res.get(sig, {}).get('signal', False)
            if earn:
                row['profit_turn'] = earn.get('profit_turn', False)
                row['rev_growth_yoy'] = earn.get('rev_growth_yoy')
                row['eps_streak'] = earn.get('eps_positive_streak')
            rows.append(row)

        df_out = pd.DataFrame(rows).sort_values('total_signals', ascending=False)
        fname = os.path.join(config.OUTPUT_DIR,
                             f"signals_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        df_out.to_csv(fname, index=False, encoding='utf-8-sig')
        print(f"  💾 {fname}")

    # 텔레그램
    if config.TELEGRAM_ENABLED and all_hits:
        msg = build_message(all_hits, now_str)
        ok = send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, msg)
        print(f"  {'✅ 텔레그램 전송 완료' if ok else '⚠ 텔레그램 전송 실패'}")
    elif config.TELEGRAM_ENABLED and not all_hits:
        send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
                     f"📊 {now_str}\n신호 종목 없음")

    print(f"{'═'*56}\n")


if __name__ == '__main__':
    main()
