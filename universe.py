"""종목 유니버스 로딩 — 한국 시총 3000억+, 미국 시총 상위 2000개"""
import sys
import pandas as pd
import FinanceDataReader as fdr

sys.stdout.reconfigure(encoding='utf-8', errors='replace')


# ── 한국 ───────────────────────────────────────────────────────────

def get_kr_universe(min_marcap: int = 300_000_000_000) -> list[tuple[str, str, int]]:
    """KRX 전종목 중 시총 min_marcap(원) 이상 반환 → (code, name, marcap)"""
    print(f"  KRX 종목 로딩...", end=' ', flush=True)
    try:
        krx = fdr.StockListing('KRX')
        filtered = krx[krx['Marcap'] >= min_marcap].sort_values('Marcap', ascending=False)
        pairs = list(zip(
            filtered['Code'].astype(str).str.zfill(6),
            filtered['Name'].astype(str),
            filtered['Marcap'].astype(int),
        ))
        print(f"{len(pairs)}개 (3000억 이상)")
        return pairs
    except Exception as e:
        print(f"실패({e}) → KOSPI200 사용")
        return _kr_fallback()


def _kr_fallback() -> list[tuple[str, str, int]]:
    try:
        from pykrx import stock
        from datetime import datetime
        today = datetime.now().strftime('%Y%m%d')
        tickers = stock.get_index_portfolio_deposit_file('1028')
        return [(t, stock.get_market_ticker_name(t), 0) for t in tickers]
    except:
        return []


# ── 미국 ───────────────────────────────────────────────────────────

_US_CSV = 'data/us_marketcap.csv'  # stock_screener/data/ 기준

def get_us_universe(top_n: int = 2000) -> list[tuple[str, str, int]]:
    """companiesmarketcap CSV → 시총 상위 top_n개 (symbol, name, marketcap_usd)"""
    print(f"  US 종목 로딩...", end=' ', flush=True)
    try:
        import os
        csv_path = os.path.join(os.path.dirname(__file__), _US_CSV)
        df = pd.read_csv(csv_path)
        df = df[df['country'] == 'United States'].copy()
        df['marketcap'] = pd.to_numeric(df['marketcap'], errors='coerce')
        df = df.dropna(subset=['marketcap', 'Symbol'])
        df = df[df['marketcap'] > 0]
        df = df.sort_values('marketcap', ascending=False).head(top_n)
        # 심볼 정제: 알파벳+하이픈, 5자 이하
        df['Symbol'] = df['Symbol'].astype(str).str.strip()
        df = df[df['Symbol'].str.replace('-', '').str.isalpha() & (df['Symbol'].str.len() <= 5)]
        pairs = list(zip(
            df['Symbol'],
            df['Name'].astype(str),
            df['marketcap'].astype(int),
        ))
        print(f"{len(pairs)}개 (시총 $USD 순)")
        return pairs
    except Exception as e:
        print(f"CSV 실패({e}) → 빈 목록")
        return []


# ── 통합 ───────────────────────────────────────────────────────────

def get_universe(cfg) -> dict:
    """config 기반 전체 유니버스 반환: {'kr': [(code,name)], 'us': [symbol]}"""
    result = {'kr': [], 'us': []}

    if cfg.USE_KR_MARKET:
        if getattr(cfg, 'KR_UNIVERSE', 'MARCAP') == 'CUSTOM':
            result['kr'] = [(s, s, 0) for s in cfg.KR_CUSTOM_SYMBOLS]
            print(f"  KR 커스텀: {len(result['kr'])}개")
        else:
            min_cap = getattr(cfg, 'KR_MIN_MARCAP', 300_000_000_000)
            result['kr'] = get_kr_universe(min_cap)

    if cfg.USE_US_MARKET:
        if getattr(cfg, 'US_UNIVERSE', 'TOP_N') == 'CUSTOM':
            result['us'] = [(s, s, 0) for s in cfg.US_CUSTOM_SYMBOLS]
            print(f"  US 커스텀: {len(result['us'])}개")
        else:
            top_n = getattr(cfg, 'US_TOP_N', 2000)
            result['us'] = get_us_universe(top_n)
            if not result['us']:
                result['us'] = [(s, s, 0) for s in getattr(cfg, 'US_CUSTOM_SYMBOLS', [])]
                print(f"  → CSV 실패, 커스텀 {len(result['us'])}개 폴백")

    total = len(result['kr']) + len(result['us'])
    print(f"  → 총 유니버스: {total}개\n")
    return result
