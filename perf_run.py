"""월간 성과 분석 — 상승률 순위 + 4주 전 신호 소급 분석
실행: python perf_run.py
"""
import sys, json, os, time, threading, socket
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
import FinanceDataReader as fdr

socket.setdefaulttimeout(12)

CACHE_DIR    = Path('data/price_cache')
DATE_STR     = datetime.now().strftime('%Y-%m-%d')
LOOKBACK_W   = 4        # 월간 = 4주
MIN_WEEKS    = 24       # 최소 주봉 수
WORKERS      = 10
_lock        = threading.Lock()


# ── 가격 데이터 ───────────────────────────────────────────────────

def _cache_path(sym):
    return CACHE_DIR / f"{sym.replace('/', '_')}.parquet"

def load_price(sym):
    cp = _cache_path(sym)
    if cp.exists():
        try:
            return pd.read_parquet(cp)
        except:
            pass
    try:
        start = (datetime.now() - timedelta(days=900)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym, start)
        if df.empty or len(df) < 60:
            return None
        df = df[['Open','High','Low','Close','Volume']].dropna(subset=['Close'])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        df.to_parquet(cp)
        return df
    except:
        return None

def to_weekly(daily_df):
    try:
        wdf = daily_df.resample('W-SUN').agg(
            {'Open':'first','High':'max','Low':'min','Close':'last','Volume':'sum'}
        ).dropna(subset=['Close'])
        return wdf if len(wdf) >= MIN_WEEKS else None
    except:
        return None


# ── 신호 계산 ─────────────────────────────────────────────────────

SIG_MAP = {
    'sig_52w':    '52주신고가',
    'sig_vol':    '거래량폭발',
    'sig_ma5':    '5일라이딩',
    'sig_cup':    '컵위드핸들',
    'sig_maconv': '이평수렴',
    'sig_rsimacd':'RSI/MACD',
}

def calc_signals(wdf):
    try:
        from signals import (sig_52w_high, sig_volume_explosion, sig_ma5_ride,
                             sig_cup_handle, sig_ma_convergence, sig_rsi_macd)
        res = {}
        res['sig_52w'],    _ = sig_52w_high(wdf)
        res['sig_vol'],    _ = sig_volume_explosion(wdf, ratio=2.0)
        res['sig_ma5'],    _ = sig_ma5_ride(wdf)
        res['sig_cup'],    _ = sig_cup_handle(wdf)
        res['sig_maconv'], _ = sig_ma_convergence(wdf)
        res['sig_rsimacd'],_ = sig_rsi_macd(wdf)
        return res
    except:
        return {k: False for k in SIG_MAP}

def sig_labels(sig_dict, prefix=''):
    return [label for k, label in SIG_MAP.items() if sig_dict.get(prefix+k)]


# ── 종목 분석 ─────────────────────────────────────────────────────

def analyze_one(sym, name, marcap, market):
    try:
        df = load_price(sym)
        if df is None:
            return None
        wdf = to_weekly(df)
        if wdf is None or len(wdf) < LOOKBACK_W + MIN_WEEKS:
            return None

        # 월간 수익률 (4주)
        curr  = float(wdf['Close'].iloc[-1])
        past  = float(wdf['Close'].iloc[-(LOOKBACK_W+1)])
        ret4w = (curr / past - 1) * 100

        # 1주 수익률
        ret1w = (curr / float(wdf['Close'].iloc[-2]) - 1) * 100 if len(wdf) >= 2 else 0

        # 4주 전 신호 (소급)
        wdf_past  = wdf.iloc[:-(LOOKBACK_W)]
        sigs_past = calc_signals(wdf_past)

        # 현재 신호
        sigs_now  = calc_signals(wdf)

        return {
            'market':      market,
            'sym':         sym,
            'name':        name,
            'marcap':      int(marcap) if marcap else 0,
            'ret_4w':      round(ret4w, 2),
            'ret_1w':      round(ret1w, 2),
            'curr_price':  round(curr, 2),
            # 신호 레이블
            'sigs_past':   sig_labels(sigs_past),
            'sigs_now':    sig_labels(sigs_now),
            # 개별 raw (필터용)
            **{f'past_{k}': bool(v) for k, v in sigs_past.items()},
            **{f'now_{k}':  bool(v) for k, v in sigs_now.items()},
        }
    except:
        return None


# ── 유니버스 ──────────────────────────────────────────────────────

def get_kr_universe():
    print("  KR 유니버스...", end=' ', flush=True)
    krx = fdr.StockListing('KRX')
    f = krx[krx['Marcap'] >= 300_000_000_000].sort_values('Marcap', ascending=False)
    pairs = list(zip(
        f['Code'].astype(str).str.zfill(6),
        f['Name'].astype(str),
        f['Marcap'].astype(int),
    ))
    print(f"{len(pairs)}개")
    return pairs

def get_us_universe():
    print("  US 유니버스...", end=' ', flush=True)
    csv = Path(__file__).parent / 'data' / 'us_marketcap.csv'
    df  = pd.read_csv(csv)
    df  = df[df['country'] == 'United States'].copy()
    df['marketcap'] = pd.to_numeric(df['marketcap'], errors='coerce')
    df  = df[df['marketcap'] >= 3_000_000_000].dropna(subset=['Symbol'])
    df['Symbol'] = df['Symbol'].astype(str).str.strip()
    df  = df[df['Symbol'].str.replace('-','').str.isalpha() & (df['Symbol'].str.len() <= 5)]
    pairs = list(zip(df['Symbol'], df['Name'].astype(str), df['marketcap'].astype(int)))
    print(f"{len(pairs)}개")
    return pairs


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*55}")
    print(f"  📈 월간 성과 분석  |  {DATE_STR}  |  KR+US")
    print(f"{'═'*55}\n")

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    print("[유니버스 로딩]")
    kr_pairs = get_kr_universe()
    us_pairs = get_us_universe()
    all_pairs = [(*p, 'KR') for p in kr_pairs] + [(*p, 'US') for p in us_pairs]
    print(f"  → 총 {len(all_pairs)}개\n")

    print("[분석 중...]")
    results  = []
    counter  = [0]
    total    = len(all_pairs)

    def _run(item):
        sym, name, marcap, market = item
        r = analyze_one(sym, name, marcap, market)
        with _lock:
            counter[0] += 1
            if counter[0] % 200 == 0 or counter[0] == total:
                print(f"\r  {counter[0]}/{total}     ", end='', flush=True)
        return r

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futures = {ex.submit(_run, item): item for item in all_pairs}
        for fut in as_completed(futures):
            try:
                r = fut.result(timeout=20)
                if r is not None:
                    results.append(r)
            except:
                pass
    print()

    # 월간 수익률 내림차순 정렬
    results.sort(key=lambda x: -x['ret_4w'])

    # 저장
    os.makedirs('results', exist_ok=True)
    out = {
        'date':   DATE_STR,
        'total':  len(results),
        'stocks': results,
    }
    path = 'results/perf_latest.json'
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"\n저장 완료: {path}  ({len(results)}개 종목)")
    print("\n[상위 20개 미리보기]")
    print(f"{'순위':>4}  {'시장':>3}  {'종목명':<20}  {'4주수익률':>8}  {'4주전신호'}")
    print("─" * 70)
    for i, s in enumerate(results[:20], 1):
        past = ', '.join(s['sigs_past']) if s['sigs_past'] else '없음'
        print(f"{i:>4}  {s['market']:>3}  {s['name']:<20}  {s['ret_4w']:>+7.1f}%  {past}")


if __name__ == '__main__':
    main()
