"""백테스트 실행 — python backtest_run.py"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import os
import pandas as pd
from datetime import datetime
import FinanceDataReader as fdr
from backtest_engine import download_all, run_backtest, build_report, CACHE_DIR

DATE_STR = datetime.now().strftime('%Y-%m-%d')


# ── 유니버스 ──────────────────────────────────────────────────────

def get_kr_universe():
    print("  KR 유니버스 로딩...", end=' ', flush=True)
    krx = fdr.StockListing('KRX')
    f = krx[krx['Marcap'] >= 100_000_000_000].sort_values('Marcap', ascending=False)
    pairs = list(zip(
        f['Code'].astype(str).str.zfill(6),
        f['Name'].astype(str),
    ))
    print(f"{len(pairs)}개 (1,000억+)")
    return pairs


def get_us_universe():
    print("  US 유니버스 로딩...", end=' ', flush=True)
    csv = os.path.join(os.path.dirname(__file__), 'data', 'us_marketcap.csv')
    df  = pd.read_csv(csv)
    df  = df[df['country'] == 'United States'].copy()
    df['marketcap'] = pd.to_numeric(df['marketcap'], errors='coerce')
    df  = df[df['marketcap'] >= 3_000_000_000].dropna(subset=['Symbol'])
    df['Symbol'] = df['Symbol'].astype(str).str.strip()
    df  = df[df['Symbol'].str.replace('-', '').str.isalpha() & (df['Symbol'].str.len() <= 5)]
    pairs = list(zip(df['Symbol'], df['Name'].astype(str)))
    print(f"{len(pairs)}개 ($3B+)")
    return pairs


# ── 메인 ─────────────────────────────────────────────────────────

def main():
    print(f"\n{'═'*60}")
    print(f"  📊 백테스트  |  2021~{DATE_STR}  |  KR+US")
    print(f"{'═'*60}\n")

    # ── Step 1: 유니버스 로딩 ──
    print("[Step 1] 유니버스 로딩")
    kr_pairs = get_kr_universe()
    us_pairs = get_us_universe()
    total    = len(kr_pairs) + len(us_pairs)
    print(f"  → 총 {total}개\n")

    # ── Step 2: 가격 데이터 다운로드/로드 ──
    cached_kr = sum(1 for sym, _ in kr_pairs if (CACHE_DIR / f"{sym}.parquet").exists())
    cached_us = sum(1 for sym, _ in us_pairs if (CACHE_DIR / f"{sym}.parquet").exists())
    print(f"[Step 2] 가격 데이터 (KR 캐시 {cached_kr}/{len(kr_pairs)}, US 캐시 {cached_us}/{len(us_pairs)})")

    if cached_kr < len(kr_pairs) or cached_us < len(us_pairs):
        print("  미캐시 종목 다운로드 중... (최초 1회, 이후 즉시 로드)")

    price_kr = download_all(kr_pairs, 'KR')
    price_us = download_all(us_pairs, 'US')
    print(f"  → KR {len(price_kr)}개 / US {len(price_us)}개 로드 완료\n")

    # ── Step 3: 신호 계산 ──
    print("[Step 3] 신호 계산 (벡터라이즈)")
    combined = run_backtest(price_kr, price_us)
    if combined.empty:
        print("데이터 없음")
        return
    print(f"  → 총 {len(combined):,}행 (종목×주봉 조합)\n")

    # ── Step 4: 리포트 생성 ──
    print("[Step 4] 성과 분석")
    os.makedirs('results', exist_ok=True)

    full_report = ''
    for market in ['ALL', 'KR', 'US']:
        r = build_report(combined, market)
        full_report += r + '\n\n'
        print(r)

    fname = f"results/backtest_{DATE_STR}.txt"
    with open(fname, 'w', encoding='utf-8') as f:
        f.write(full_report)
    print(f"\n리포트 저장: {fname}")

    # ── Step 5: 신호별 최강 조합 요약 ──
    print(f"\n{'═'*60}")
    print("  🏆 결론: 어떤 신호를 쓸 것인가")
    print(f"{'═'*60}")
    print("  → 위 결과에서 기대값(EV) > +1% 이고 샤프 > 0.8인 신호만 스크리너에 유지")
    print("  → 기대값 < 0%인 신호는 다음 주 스크리너에서 제거")


if __name__ == '__main__':
    main()
