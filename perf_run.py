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
        wdf['Days'] = daily_df['Close'].resample('W-SUN').count().reindex(wdf.index)   # 진행 중 주 판별용
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

        # 52주 신고가 상세 — 📈 52주 신고가 탭용 (2026-10-14)
        #   고점은 직전 52주 '주봉 고가'(장중 고가 포함), 거리는 이번 주 종가 기준.
        #   이번 주 고가가 직전 52주 고가를 넘었으면 '신고가 경신'.
        try:
            _hi = float(wdf['High'].iloc[-53:-1].max())
            _dist = (curr / _hi - 1) * 100 if _hi > 0 else None
            _new = bool(float(wdf['High'].iloc[-1]) > _hi) if _hi > 0 else False
            _wk_since = None
            _hh = wdf['High'].iloc[-53:]
            if len(_hh):
                _wk_since = int(len(_hh) - 1 - int(_hh.values.argmax()))   # 52주 최고가를 찍은 뒤 지난 주 수
        except Exception:
            _hi, _dist, _new, _wk_since = None, None, False, None

        # 주차별 신고가 경신 이력 — 최근 52주 (2026-10-19 사용자 요청: 주간 그래프·연속 경신 필터)
        #   정의는 위와 같다: 그 주 고가 > 직전 52주 고가. 주 이름은 그 주 금요일(W-SUN 일요일 − 2일).
        #   nh = [[금요일, 그 주 종가], ...] — 그 주 종가를 같이 실어 '그 뒤 얼마나 갔나'를 화면이 계산한다.
        _nh, _streak, _nh8 = [], 0, 0
        try:
            _H = wdf['High'].astype(float)
            _prev = _H.shift(1).rolling(52, min_periods=52).max()
            _flag = (_H > _prev) & _prev.notna()
            _f52 = _flag.iloc[-52:]
            _c52 = wdf['Close'].iloc[-52:]
            _nh = [[str((t - pd.Timedelta(days=2)).date()), round(float(c), 2)]
                   for t, f, c in zip(_f52.index, _f52.values, _c52.values) if f]
            for f in reversed(_f52.values.tolist()):
                if not f:
                    break
                _streak += 1
            _nh8 = int(_f52.iloc[-8:].sum())
        except Exception:
            pass

        return {
            'market':      market,
            'sym':         sym,
            'name':        name,
            'marcap':      int(marcap) if marcap else 0,
            'ret_4w':      round(ret4w, 2),
            'ret_1w':      round(ret1w, 2),
            'curr_price':  round(curr, 2),
            'hi52':        round(_hi, 2) if _hi else None,
            'dist52':      round(_dist, 2) if _dist is not None else None,
            'new_high':    _new,
            'wk_since_hi': _wk_since,
            'nh':          _nh,          # 최근 52주 중 신고가 경신 주 [[금요일, 종가], ...]
            'nh_streak':   _streak,      # 이번 주까지 연속 경신 주 수
            'nh_8w':       _nh8,         # 최근 8주 중 경신 주 수
            'ret_12w':     round((curr / float(wdf['Close'].iloc[-13]) - 1) * 100, 2) if len(wdf) >= 13 else None,
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
    """2026-10-19 — 공통 커버 기준(universe.kr_cover). 전에는 3,000억+ 로 따로 걸려 있었다."""
    import universe
    pairs = universe.kr_cover()
    print(f"  KR 유니버스... {len(pairs)}개")
    return pairs

def get_us_universe():
    """2026-10-19 — 공통 커버 기준(universe.us_cover). 전에는 $3B+ 라 미국 중소형이 통째로 빠졌다."""
    import universe
    pairs = universe.us_cover()
    print(f"  US 유니버스... {len(pairs)}개")
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
