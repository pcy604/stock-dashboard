"""월봉 마감 후 실행 — 전종목 월봉 분석 리포트"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from datetime import datetime, timedelta
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import FinanceDataReader as fdr
import config
from signals import run_all_signals
from report import build_summary, build_detail_kr, save_report
from telegram_notifier import send_message
from weekly_run import get_sector_kr
from universe import get_universe

MODE = 'monthly'
DATE_STR = datetime.now().strftime('%Y-%m-%d')


def fetch(symbol):
    try:
        start = (datetime.now() - timedelta(days=1000)).strftime('%Y-%m-%d')
        df = fdr.DataReader(symbol, start)
        if df.empty or len(df) < 60:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except:
        return None


_PRIMARY = ('52w_high', 'volume', 'cup_handle')
_print_lock = threading.Lock()


def _process_one(sym, market, name, marcap):
    from signals import sig_52w_high
    time.sleep(0.05)
    df = fetch(sym)
    if df is None:
        return None
    try:
        mdf = df.resample('ME').agg(
            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        ).dropna(subset=['Close'])
    except:
        mdf = df
    if len(mdf) < 12:
        return None
    curr_close = mdf['Close'].iloc[-1]
    recent_high = mdf['High'].iloc[-3:].max()
    if recent_high == 0:
        return None
    prev_close = mdf['Close'].iloc[-2] if len(mdf) >= 2 else curr_close
    if (curr_close / recent_high - 1) * 100 < -7:
        return None
    if (curr_close / prev_close - 1) * 100 < -5:
        return None
    result = run_all_signals(mdf, config)
    # 52주신고가는 월봉으로 200바 불가능 → 일봉 기준으로 재계산
    ok_52, detail_52 = sig_52w_high(df)
    result['52w_high'] = {'signal': ok_52, **detail_52}
    # KR 거래량 기준 완화 (2.5 → 2.0)
    if market == 'KR':
        from signals import sig_volume_explosion
        ok_vol, detail_vol = sig_volume_explosion(mdf, ratio=2.0)
        result['volume'] = {'signal': ok_vol, **detail_vol}
    result['total_signals'] = sum(
        v['signal'] for v in result.values() if isinstance(v, dict) and 'signal' in v
    )
    if result['total_signals'] < config.MIN_SIGNALS_TO_SHOW:
        return None
    if not any(result.get(s, {}).get('signal') for s in _PRIMARY):
        return None
    sector = get_sector_kr(sym) if market == 'KR' else 'US'
    return (market, sym, name, result, None, [], df, sector, marcap)


def screen(symbols, market, name_map=None, marcap_map=None):
    hits = []
    counter = [0]
    total = len(symbols)

    def _run(sym):
        name = name_map.get(sym, sym) if name_map else sym
        marcap = marcap_map.get(sym, 0) if marcap_map else 0
        result = _process_one(sym, market, name, marcap)
        with _print_lock:
            counter[0] += 1
            print(f"\r  [{market}] {counter[0]}/{total} {sym}          ", end='', flush=True)
        return result

    with ThreadPoolExecutor(max_workers=8) as ex:
        for item in ex.map(_run, symbols):
            if item is not None:
                hits.append(item)

    print()
    return hits


def _refresh_us_marcap(hits: list) -> list:
    """US 히트 종목 시총을 yfinance 실시간으로 갱신"""
    try:
        import yfinance as yf
    except ImportError:
        return hits

    us_syms = [sym for market, sym, *_ in hits if market == 'US']
    if not us_syms:
        return hits

    print(f'  [US 시총 갱신] {len(us_syms)}개...', end=' ', flush=True)
    live = {}
    for sym in us_syms:
        try:
            info = yf.Ticker(sym).info
            mc = info.get('marketCap') or info.get('market_cap')
            if mc:
                live[sym] = int(mc)
        except:
            pass
    print(f'완료 ({len(live)}/{len(us_syms)}개 갱신)')

    result = []
    for item in hits:
        market, sym, name, res, e, tf, df, sector, marcap = item
        if market == 'US' and sym in live:
            marcap = live[sym]
        result.append((market, sym, name, res, e, tf, df, sector, marcap))
    return result


def main():
    print(f"\n{'═'*55}")
    print(f"  📊 월봉 리포트  |  {DATE_STR}")
    print(f"{'═'*55}\n")

    all_hits = []

    print('[유니버스 로딩]')
    universe = get_universe(config)

    if config.USE_KR_MARKET:
        print('[한국 월봉 스캔]')
        pairs = universe['kr']  # [(code, name, marcap), ...]
        name_map   = {t: n for t, n, m in pairs}
        marcap_map = {t: m for t, n, m in pairs}
        kr_hits = screen([t for t, n, m in pairs], 'KR', name_map, marcap_map)
        all_hits += kr_hits
        print(f"  → 신호 종목: {len(kr_hits)}개\n")

    if config.USE_US_MARKET:
        print('[미국 월봉 스캔]')
        pairs = universe['us']  # [(symbol, name, marcap_usd), ...]
        name_map   = {t: n for t, n, m in pairs}
        marcap_map = {t: m for t, n, m in pairs}
        us_hits = screen([t for t, n, m in pairs], 'US', name_map, marcap_map)
        all_hits += us_hits
        print(f"  → 신호 종목: {len(us_hits)}개\n")

    if not all_hits:
        print('신호 종목 없음')
        return

    all_hits = _refresh_us_marcap(all_hits)

    summary = build_summary(all_hits, MODE, DATE_STR)
    detail  = build_detail_kr(all_hits, MODE)
    full    = summary + '\n\n' + '='*50 + '\n개별 종목 상세\n' + '='*50 + '\n\n' + detail

    fname = save_report(full, MODE)
    print(f'\n리포트 저장: {fname}')
    print('\n' + summary[:1000])

    if config.TELEGRAM_ENABLED:
        chunks = [summary[i:i+4000] for i in range(0, len(summary), 4000)]
        for chunk in chunks:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, chunk)
        print('✅ 텔레그램 전송 완료')


if __name__ == '__main__':
    main()
