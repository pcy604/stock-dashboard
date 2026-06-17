"""일봉 소형주 조기포착 스크리너 — 매일 장 마감 후 실행"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import FinanceDataReader as fdr
import config
from report import save_report
from telegram_notifier import send_message

DATE_STR = datetime.now().strftime('%Y-%m-%d')

MIN_MARCAP          = 20_000_000_000      # 200억
MAX_MARCAP          = 5_000_000_000_000   # 5조
MIN_AVG_TRADE_VALUE = 500_000_000         # 일평균 거래대금 5억
VOL_RATIO_MIN       = 3.0                 # 거래량 배수
BODY_RATIO_MIN      = 0.6                 # 몸통 비율
CLOSE_POS_MIN       = 0.7                 # 종가 위치 (당일 범위 내)
DAILY_RETURN_MIN    = 5.0                 # 당일 등락률 %
ALREADY_UP_MAX      = 100.0              # 60일 저가 대비 이미 상승 한도 %
NEAR_52W_THRESHOLD  = -5.0               # 52주 고가 대비 허용 거리 %


# ── 유니버스 ────────────────────────────────────────────────────────

def get_universe():
    print("  소형주 유니버스 로딩...", end=' ', flush=True)
    try:
        krx = fdr.StockListing('KRX')
        f = krx[(krx['Marcap'] >= MIN_MARCAP) & (krx['Marcap'] <= MAX_MARCAP)]
        f = f.sort_values('Marcap', ascending=False)
        pairs = list(zip(
            f['Code'].astype(str).str.zfill(6),
            f['Name'].astype(str),
            f['Marcap'].astype(int),
        ))
        print(f"{len(pairs)}개 (200억~5,000억)")
        return pairs
    except Exception as e:
        print(f"실패: {e}")
        return []


# ── 신호 ────────────────────────────────────────────────────────────

def check_signal(df):
    """
    일봉 신호 체크. 모든 1급 조건 동시 충족 필요.
    Returns (ok: bool, details: dict)
    """
    if len(df) < 61:
        return False, {}

    today = df.iloc[-1]
    prev_close = df['Close'].iloc[-2]

    # ① 거래량 폭발
    avg_vol = df['Volume'].iloc[-61:-1].mean()
    if avg_vol == 0:
        return False, {}
    vol_ratio = today['Volume'] / avg_vol

    # ② 캔들 품질
    rng = today['High'] - today['Low']
    if rng == 0:
        return False, {}
    body_ratio = abs(today['Close'] - today['Open']) / rng
    close_pos  = (today['Close'] - today['Low']) / rng
    is_bull    = today['Close'] > today['Open']
    daily_ret  = (today['Close'] / prev_close - 1) * 100

    # ③ 1급 조건 — 전부 충족해야 통과
    if not (
        vol_ratio  >= VOL_RATIO_MIN   and
        body_ratio >= BODY_RATIO_MIN  and
        close_pos  >= CLOSE_POS_MIN   and
        is_bull                        and
        daily_ret  >= DAILY_RETURN_MIN
    ):
        return False, {}

    # ④ 상투 필터: 60일 저가 대비 이미 100% 이상 올랐으면 제외
    low_60 = df['Low'].iloc[-60:].min()
    already_up = (today['Close'] / low_60 - 1) * 100 if low_60 > 0 else 0
    if already_up >= ALREADY_UP_MAX:
        return False, {}

    # ⑤ 유동성: 60일 평균 거래대금
    avg_trade_val = (df['Close'] * df['Volume']).iloc[-61:-1].mean()
    if avg_trade_val < MIN_AVG_TRADE_VALUE:
        return False, {}

    # ⑥ 추세: 종가 > MA20 > MA60
    ma20 = df['Close'].iloc[-20:].mean()
    ma60 = df['Close'].iloc[-60:].mean()
    if not (today['Close'] > ma20 > ma60):
        return False, {}

    # ⑦ 돌파: 52주 고가 -5% 이내 OR 20일 고점 돌파
    high_52w = df['High'].iloc[:-1].max()
    high_20d = df['High'].iloc[-21:-1].max() if len(df) >= 21 else high_52w
    near_52w  = (today['Close'] / high_52w - 1) * 100 >= NEAR_52W_THRESHOLD
    break_20d = today['Close'] >= high_20d
    if not (near_52w or break_20d):
        return False, {}

    return True, {
        'vol_ratio':    round(vol_ratio, 1),
        'body_pct':     round(body_ratio * 100, 1),
        'close_pos_pct':round(close_pos * 100, 1),
        'daily_ret':    round(daily_ret, 1),
        'already_up':   round(already_up, 1),
        'near_52w':     near_52w,
        'break_20d':    break_20d,
        'ma20':         round(ma20, 0),
        'ma60':         round(ma60, 0),
    }


# ── 섹터 ────────────────────────────────────────────────────────────
_sector_cache = {}

def get_sector(ticker):
    if ticker in _sector_cache:
        return _sector_cache[ticker]
    try:
        import contextlib, io
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pykrx import stock
            today = datetime.now().strftime('%Y%m%d')
            for mkt in ['KOSPI', 'KOSDAQ']:
                sdf = stock.get_market_sector_classifications(today, mkt)
                if ticker in sdf.index:
                    sec = sdf.loc[ticker, '업종명']
                    _sector_cache[ticker] = sec
                    return sec
    except:
        pass
    _sector_cache[ticker] = '기타'
    return '기타'


# ── 스캔 ────────────────────────────────────────────────────────────
_print_lock = threading.Lock()

def _process(item):
    sym, name, marcap = item
    time.sleep(0.05)
    try:
        start = (datetime.now() - timedelta(days=400)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym, start)
        if df.empty or len(df) < 61:
            return None
        df = df[['Open', 'High', 'Low', 'Close', 'Volume']].dropna(subset=['Close'])
        df.index = pd.to_datetime(df.index).tz_localize(None)
        ok, details = check_signal(df)
        if not ok:
            return None
        sector = get_sector(sym)
        return (sym, name, marcap, details, sector)
    except:
        return None


def screen(pairs):
    hits = []
    counter = [0]
    total = len(pairs)

    def _run(item):
        result = _process(item)
        with _print_lock:
            counter[0] += 1
            if counter[0] % 100 == 0 or counter[0] == total:
                print(f"\r  [{counter[0]}/{total}] 스캔 중...", end='', flush=True)
        return result

    with ThreadPoolExecutor(max_workers=8) as ex:
        for item in ex.map(_run, pairs):
            if item is not None:
                hits.append(item)
    print()
    return hits


# ── 리포트 ────────────────────────────────────────────────────────────

def build_report(hits):
    if not hits:
        return (
            f"📌 일봉 소형주 신호 없음 ({DATE_STR})\n"
            "  오늘 조건을 충족한 종목이 없습니다."
        )

    hits_sorted = sorted(hits, key=lambda x: -x[2])

    sector_map = defaultdict(list)
    for h in hits_sorted:
        sector_map[h[4]].append(h)

    clusters = {s: v for s, v in sector_map.items() if len(v) >= 2 and s != '기타'}
    clustered = {h[0] for items in clusters.values() for h in items}
    singles   = [h for h in hits_sorted if h[0] not in clustered]

    def _row(sym, name, marcap, d):
        cap = f"{marcap // 100_000_000:,}억"
        tag = "📈52주" if d['near_52w'] else "⚡20일돌파"
        return (
            f"  {cap:>6}  [+{d['daily_ret']:.1f}%]  {name}"
            f"  거래량{d['vol_ratio']}배  {tag}"
        )

    lines = [
        f"📌 일봉 소형주 신호 ({DATE_STR} 기준)",
        f"총 {len(hits)}개 | 유니버스 KRX 200억~5,000억",
    ]

    if clusters:
        lines += ['', '🔥 섹터 클러스터 (동시 신호 — 고신뢰)', '─' * 48]
        for sector, items in sorted(clusters.items(), key=lambda x: -len(x[1])):
            emoji = '🚨' if len(items) >= 3 else '🔥'
            lines.append(f"{emoji} [{sector}] {len(items)}개 동시 신호")
            for h in items:
                lines.append(_row(*h[:4]))

    if singles:
        lines += ['', '⚡ 단독 신호', '─' * 48]
        for h in singles:
            lines.append(_row(*h[:4]))

    lines += [
        '',
        '─' * 48,
        '📊 정량 기준',
        f'  유니버스:  시총 200억~5,000억 KRX 전종목',
        f'  유동성:   일평균 거래대금 ≥ 5억원 (60일)',
        f'  거래량:   60일 평균 대비 ≥ {VOL_RATIO_MIN}배',
        f'  캔들:     몸통 ≥ {int(BODY_RATIO_MIN*100)}%,  상단마감 ≥ {int(CLOSE_POS_MIN*100)}%,  양봉',
        f'  등락률:   당일 ≥ +{DAILY_RETURN_MIN}%',
        f'  추세:     종가 > MA20 > MA60',
        f'  돌파:     52주 고가 {NEAR_52W_THRESHOLD}% 이내  OR  20일 고점 돌파',
        f'  상투필터: 60일 저가 대비 상승 < {int(ALREADY_UP_MAX)}%',
        f'  섹터클러스터: 동일업종 2개+ 🔥 / 3개+ 🚨',
    ]

    return '\n'.join(lines)


# ── 메인 ────────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*55}")
    print(f"  📊 일봉 소형주 스크리너  |  {DATE_STR}")
    print(f"{'═'*55}\n")

    pairs = get_universe()
    if not pairs:
        print("유니버스 로딩 실패")
        return

    print(f"[스캔 시작]")
    hits = screen(pairs)
    print(f"  → 신호 종목: {len(hits)}개\n")

    report = build_report(hits)
    fname  = save_report(report, 'daily')
    print(f'리포트 저장: {fname}')
    print('\n' + report)

    if config.TELEGRAM_ENABLED and hits:
        for chunk in [report[i:i+4000] for i in range(0, len(report), 4000)]:
            send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID, chunk)
        print('✅ 텔레그램 전송 완료')


if __name__ == '__main__':
    main()
