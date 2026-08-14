"""
volume_backfill.py — longcache 에 거래량(Volume) 채우기
──────────────────────────────────────────────────────────
왜:
  data/longcache/*.parquet 는 **종가만** 들고 있었다. 그래서 KR 주도주 규칙(KR-P1)에
  유동성 컷을 걸 수 없었고, 백테스트에 "실제로는 못 사는 소형주" 신호가 섞였다.
  (US 규칙⑥은 adv_20d ≥ $5M 필터가 있는데 KR만 없던 상태)

무엇을:
  기존 Close 이력(2008~)은 그대로 두고, START 이후 구간의 Volume 을 받아 붙인다.
  거래대금 = Close × Volume 은 사용처에서 계산한다(저장은 원자료만).

실행:  python volume_backfill.py            # KR 전 종목
       python volume_backfill.py 086520     # 특정 종목만
"""
from __future__ import annotations

import glob
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, 'data', 'longcache')
START = '2017-10-01'        # 2018 신호의 20일 평균 계산용 워밍업 포함
WORKERS = 8


def kr_symbols() -> list[str]:
    return sorted(os.path.basename(f)[:-8] for f in glob.glob(os.path.join(CACHE, '*.parquet'))
                  if os.path.basename(f)[:-8].isdigit() and len(os.path.basename(f)[:-8]) == 6)


def backfill_one(sym: str) -> tuple[str, str]:
    """(sym, 결과문자열). 기존 Close 는 보존하고 Volume 만 덧붙인다."""
    p = os.path.join(CACHE, f'{sym}.parquet')
    try:
        old = pd.read_parquet(p)
        old.index = pd.to_datetime(old.index)
    except Exception as e:
        return sym, f'read-fail {type(e).__name__}'
    if 'Volume' in old.columns and old['Volume'].notna().sum() > 100:
        return sym, 'skip(이미 있음)'
    try:
        import FinanceDataReader as fdr
        new = fdr.DataReader(sym, START)
    except Exception as e:
        return sym, f'fetch-fail {type(e).__name__}'
    if new is None or new.empty or 'Volume' not in new.columns:
        return sym, 'no-volume'
    new.index = pd.to_datetime(new.index)

    # Close 는 과거 이력(2008~)을 살리고 겹치는 구간은 새 값 우선
    close = pd.concat([old[['Close']], new[['Close']]])
    close = close[~close.index.duplicated(keep='last')].sort_index()
    out = close.join(new[['Volume']], how='left')
    try:
        out.to_parquet(p)
    except Exception as e:
        return sym, f'write-fail {type(e).__name__}'
    return sym, f'ok(v={int(out["Volume"].notna().sum())})'


def main():
    syms = [sys.argv[1]] if len(sys.argv) > 1 else kr_symbols()
    print(f'거래량 백필 대상 {len(syms)}종 · {START}~ · 워커 {WORKERS}', flush=True)
    t0, done, stats = time.time(), 0, {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(backfill_one, s): s for s in syms}
        for f in as_completed(futs):
            s, r = f.result()
            k = r.split('(')[0]
            stats[k] = stats.get(k, 0) + 1
            done += 1
            if done % 200 == 0:
                el = time.time() - t0
                print(f'  {done}/{len(syms)}  {el/60:.1f}분 경과 · 남은 예상 '
                      f'{el/done*(len(syms)-done)/60:.1f}분', flush=True)
    print(f'\n완료 {time.time()-t0:.0f}초 · 결과 {stats}', flush=True)


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    main()
