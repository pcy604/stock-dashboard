"""주봉 마감 후 실행 — 전종목 주봉 분석 리포트"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from datetime import datetime, timedelta
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr
import config
from signals import run_all_signals
from report import build_summary, build_detail_kr, save_report
from telegram_notifier import send_message
from universe import get_universe

MODE = 'weekly'
DATE_STR = datetime.now().strftime('%Y-%m-%d')


def get_sector_kr(ticker):
    try:
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock
            today = datetime.now().strftime('%Y%m%d')
            for mkt in ['KOSPI', 'KOSDAQ']:
                df = stock.get_market_sector_classifications(today, mkt)
                if ticker in df.index:
                    return df.loc[ticker, '업종명']
    except:
        pass
    return '기타'


def fetch(symbol, is_kr=False):
    try:
        start = (datetime.now() - timedelta(days=1600)).strftime('%Y-%m-%d')
        df = fdr.DataReader(symbol, start)
        if df.empty or len(df) < 60:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        return df
    except:
        return None


# 백테스트 결과 반영: 이평선수렴 1급 승격, 거래량폭발 2급 강등
_PRIMARY = ('52w_high', 'ma_convergence', 'cup_handle')
_print_lock = threading.Lock()


def _process_one(sym, market, name, marcap):
    time.sleep(0.05)
    df = fetch(sym, is_kr=(market == 'KR'))
    if df is None:
        return None
    try:
        wdf = df.resample('W').agg(
            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}
        ).dropna(subset=['Close'])
    except:
        wdf = df
    if len(wdf) < 20:
        return None
    curr_close = wdf['Close'].iloc[-1]
    recent_high = wdf['High'].iloc[-4:].max()
    if recent_high == 0:
        return None
    prev_close = wdf['Close'].iloc[-2] if len(wdf) >= 2 else curr_close
    if (curr_close / recent_high - 1) * 100 < -7:
        return None
    if (curr_close / prev_close - 1) * 100 < -5:
        return None
    result = run_all_signals(wdf, config)
    # KR 거래량 기준 완화 (2.5 → 2.0)
    if market == 'KR':
        from signals import sig_volume_explosion
        ok_vol, detail_vol = sig_volume_explosion(wdf, ratio=2.0)
        result['volume'] = {'signal': ok_vol, **detail_vol}
        result['total_signals'] = sum(
            v['signal'] for v in result.values() if isinstance(v, dict) and 'signal' in v
        )
    if result['total_signals'] < config.MIN_SIGNALS_TO_SHOW:
        return None
    if not any(result.get(s, {}).get('signal') for s in _PRIMARY):
        return None
    sector = '기타'  # pykrx 업종조회 속도 이슈로 스킵
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
    print(f"  📊 주봉 리포트  |  {DATE_STR}")
    print(f"{'═'*55}\n")

    all_hits = []

    print('[유니버스 로딩]')
    universe = get_universe(config)

    if config.USE_KR_MARKET:
        print('[한국 주봉 스캔]')
        pairs = universe['kr']  # [(code, name, marcap), ...]
        name_map   = {t: n for t, n, m in pairs}
        marcap_map = {t: m for t, n, m in pairs}
        kr_hits = screen([t for t, n, m in pairs], 'KR', name_map, marcap_map)
        all_hits += kr_hits
        print(f"  → 신호 종목: {len(kr_hits)}개\n")

    if config.USE_US_MARKET:
        print('[미국 주봉 스캔]')
        pairs = universe['us']  # [(symbol, name, marcap_usd), ...]
        name_map   = {t: n for t, n, m in pairs}
        marcap_map = {t: m for t, n, m in pairs}
        us_hits = screen([t for t, n, m in pairs], 'US', name_map, marcap_map)
        all_hits += us_hits
        print(f"  → 신호 종목: {len(us_hits)}개\n")

    if not all_hits:
        print('신호 종목 없음')
        return

    # all_hits = _refresh_us_marcap(all_hits)  # yfinance rate limit 이슈로 스킵

    # 리포트 생성
    summary = build_summary(all_hits, MODE, DATE_STR)
    detail  = build_detail_kr(all_hits, MODE)
    full_report = summary + '\n\n' + '='*50 + '\n개별 종목 상세\n' + '='*50 + '\n\n' + detail

    fname = save_report(full_report, MODE)
    print(f'\n리포트 저장: {fname}')
    print('\n' + summary[:1000])  # 미리보기

    # ── JSON 저장 (대시보드용) ──────────────────────────────────────
    import json, os
    from report import _calc_period_return, _get_signal_labels, _high_type
    stocks_json = []
    for item in all_hits:
        market, sym, name, result, _, _, df, sector, *rest = item
        marcap = rest[0] if rest else 0
        pct = _calc_period_return(df, MODE)
        stocks_json.append({
            'market':       market,
            'sym':          sym,
            'name':         name,
            'marcap':       int(marcap) if marcap else 0,
            'pct_change':   round(pct, 2),
            'signals':      _get_signal_labels(result),
            'total_signals': int(result.get('total_signals', 0)),
            'high_type':    _high_type(result),
            'sig_52w':      bool(result.get('52w_high',      {}).get('signal')),
            'sig_vol':      bool(result.get('volume',        {}).get('signal')),
            'sig_ma5':      bool(result.get('ma5_ride',      {}).get('signal')),
            'sig_cup':      bool(result.get('cup_handle',    {}).get('signal')),
            'sig_maconv':   bool(result.get('ma_convergence',{}).get('signal')),
            'sig_rsimacd':  bool(result.get('rsi_macd',      {}).get('signal')),
            'dist_52w':     result.get('52w_high', {}).get('dist_pct'),
            'vol_ratio':    result.get('volume',   {}).get('ratio'),
            'sector':       sector,
        })
    os.makedirs('results', exist_ok=True)
    json_path = 'results/screener_latest.json'
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({'date': DATE_STR, 'total': len(stocks_json), 'stocks': stocks_json}, f, ensure_ascii=False, indent=2)
    print(f'JSON 저장: {json_path}')

    # 포워드 페이퍼 트레이딩: 이번 주 신호를 가상 진입 기록 + 만기분 실현 갱신
    # (실패해도 본 작업에 영향 없도록 격리)
    try:
        import paper_trade
        paper_trade.log_from_screener(min_signals=2, max_log=40)
        paper_trade.update_outcomes()
        paper_trade.export_weights('4w')
    except Exception as e:
        print(f'⚠️ 페이퍼 트레이딩 기록 건너뜀: {e}')

    # 주간 추천 포트폴리오 10선·20선 생성 + 히스토리 누적 (격리)
    try:
        import weekly_portfolio
        _cash = weekly_portfolio._macro_cash_pct()
        _p10 = weekly_portfolio.generate(10, cash_pct=_cash)
        _p20 = weekly_portfolio.generate(20, cash_pct=_cash)
        weekly_portfolio.save_snapshot(_p10, _p20)
        print(f'주간 포트폴리오 생성: 10선/20선 · 현금 {_cash*100:.0f}%')
    except Exception as e:
        print(f'⚠️ 주간 포트폴리오 생성 건너뜀: {e}')

    # 텔레그램 전송 — 비활성화(2026-07): daily-refresh 워크플로가 이 스크립트를
    # 매일 돌려서 "주간 신호종목" 요약이 매일 발송되던 스팸을 차단.
    # 매도 알림은 portfolio_monitor.py에서 별도 발송되므로 영향 없음.
    # 다시 켜려면 config.WEEKLY_SIGNAL_TELEGRAM=True (기본 False).
    if config.TELEGRAM_ENABLED and getattr(config, 'WEEKLY_SIGNAL_TELEGRAM', False):
        chunks = [summary[i:i+4000] for i in range(0, len(summary), 4000)]
        for chunk in chunks:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, chunk)
        print('✅ 텔레그램 전송 완료')
    else:
        print('ⓘ 주간 신호 텔레그램 발송 생략 (WEEKLY_SIGNAL_TELEGRAM=False)')


if __name__ == '__main__':
    main()
