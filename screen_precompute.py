"""
계절성 + MDD 사전계산 → results/seasonality.json, results/mdd.json
─────────────────────────────────────────────────────────────────
종목명·시가총액 보강(#1,#5) + 장기 히스토리 옵션(#2).

기본(빠름):   캐시(2021~, 5년) 사용 → python screen_precompute.py
장기(권장):   직접 다운로드 → python screen_precompute.py --start 2008-01-01
              (수십 년 표본으로 계절성 신뢰도 ↑, 단 30~60분 소요)

계절성: 종목별 캘린더 월별 평균수익·승률 (표본 많을수록 신뢰)
MDD:    역대/1년 최대낙폭 · 현재 고점대비 낙폭
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

from backtest_engine import CACHE_DIR

SEASON_OUT = Path('results/seasonality.json')
MDD_OUT = Path('results/mdd.json')


def _enrich_maps():
    """sym → (name, marcap) 보강: JSON + FDR 리스팅."""
    names, caps = {}, {}
    for f in ['perf_latest', 'screener_latest', 'canslim_latest']:
        p = Path(f'results/{f}.json')
        if p.exists():
            try:
                for s in json.loads(p.read_text(encoding='utf-8')).get('stocks', []):
                    if s.get('name'): names.setdefault(s['sym'], s['name'])
                    if s.get('marcap'): caps.setdefault(s['sym'], s['marcap'])
            except Exception:
                pass
    try:
        import FinanceDataReader as fdr
        krx = fdr.StockListing('KRX')
        for _, r in krx.iterrows():
            code = str(r.get('Code', '')).zfill(6) if r.get('Code') else ''
            if code:
                if r.get('Name'): names.setdefault(code, str(r['Name']))
                if r.get('Marcap'): caps.setdefault(code, int(r['Marcap']))
        sp = fdr.StockListing('S&P500')
        for _, r in sp.iterrows():
            if r.get('Symbol') and r.get('Name'):
                names.setdefault(str(r['Symbol']), str(r['Name']))
    except Exception as e:
        print(f"  (FDR 리스팅 보강 실패: {e})")
    return names, caps


def _mdd(close):
    peak = close.cummax()
    return float(((close / peak - 1) * 100).min())


LONG_CACHE = Path('data/longcache')


def _series_for(sym, mkt, init_start):
    """증분 캐시: 기존 데이터는 두고 '새로 생긴 날짜'만 받아 붙인다.
       data/longcache/{sym}.parquet 에 장기 종가 저장.
       - 캐시 없으면: init_start(예 2008)부터 전체 다운로드 (최초 1회만 느림)
       - 캐시 있으면: 마지막 날짜 이후만 받아 append (매번 빠름)
    """
    from datetime import timedelta
    LONG_CACHE.mkdir(parents=True, exist_ok=True)
    cp = LONG_CACHE / f"{sym}.parquet"
    fsym = sym if mkt == 'KR' else sym
    try:
        import FinanceDataReader as fdr
        if cp.exists():
            old = pd.read_parquet(cp)
            last = old.index.max()
            fstart = (last - timedelta(days=7)).strftime('%Y-%m-%d')   # 7일 겹쳐 받아 누락 방지
            new = fdr.DataReader(fsym, fstart)
            if new is not None and not new.empty:
                add = new[['Close']] if 'Close' in new.columns else new
                comb = pd.concat([old[['Close']], add])
                comb = comb[~comb.index.duplicated(keep='last')].sort_index()
            else:
                comb = old[['Close']]
        else:
            df = fdr.DataReader(fsym, init_start)
            if df is None or df.empty:
                return None
            comb = df[['Close']]
        comb.to_parquet(cp)
        return comb['Close'].dropna()
    except Exception:
        if cp.exists():
            try:
                return pd.read_parquet(cp)['Close'].dropna()
            except Exception:
                pass
        return None


def _universe():
    """종목 목록: 5년 캐시(있으면) ∪ 커밋된 JSON(perf·screener·canslim·longcache).
       → Actions(캐시 없음)에서도 JSON으로 동작."""
    syms = set(f.stem for f in CACHE_DIR.glob('*.parquet') if not f.stem.startswith('_benchmark'))
    syms |= set(f.stem for f in LONG_CACHE.glob('*.parquet')) if LONG_CACHE.exists() else set()
    for f in ['perf_latest', 'screener_latest', 'canslim_latest']:
        p = Path(f'results/{f}.json')
        if p.exists():
            try:
                for s in json.loads(p.read_text(encoding='utf-8')).get('stocks', []):
                    if s.get('sym'):
                        syms.add(s['sym'])
            except Exception:
                pass
    return sorted(syms)


def run(start=None):
    init_start = start or '2008-01-01'
    names, caps = _enrich_maps()
    syms = _universe()
    _seeded = LONG_CACHE.exists() and any(LONG_CACHE.glob('*.parquet'))
    print(f"  대상 {len(syms)}종목 · 모드: {'증분 갱신(빠름)' if _seeded else f'최초 다운로드 {init_start}~ (느림, 1회만)'}")

    season, mdd = [], []

    def _one(sym):
        mkt = 'KR' if (sym.isdigit() and len(sym) == 6) else 'US'
        close = _series_for(sym, mkt, init_start)
        if close is None or len(close) < 250:
            return None
        name = names.get(sym, sym)
        marcap = caps.get(sym)
        # 계절성
        mclose = close.resample('ME').last().dropna()
        mret = mclose.pct_change().dropna() * 100
        s_entry = None
        if len(mret) >= 24:
            bym = {}
            for mo in range(1, 13):
                v = mret[mret.index.month == mo]
                if len(v) >= 2:
                    bym[mo] = {'ret': round(float(v.mean()), 1),
                               'wr': round(float((v > 0).mean() * 100), 0), 'n': int(len(v))}
            if bym:
                s_entry = {'sym': sym, 'name': name, 'market': mkt, 'marcap': marcap, 'months': bym}
        # MDD
        cur = float(close.iloc[-1]); peak = float(close.cummax().iloc[-1])
        m_entry = {'sym': sym, 'name': name, 'market': mkt, 'marcap': marcap,
                   'mdd_all': round(_mdd(close), 1), 'mdd_1y': round(_mdd(close.tail(252)), 1),
                   'cur_dd': round((cur / peak - 1) * 100, 1), 'price': round(cur, 2),
                   'years': round(len(close) / 252, 1)}
        return s_entry, m_entry

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for fut in as_completed([ex.submit(_one, s) for s in syms]):
            done += 1
            if done % 200 == 0: print(f"\r  {done}/{len(syms)}", end='', flush=True)
            r = fut.result()
            if r:
                if r[0]: season.append(r[0])
                mdd.append(r[1])
    print()

    SEASON_OUT.write_text(json.dumps({'date': datetime.now().strftime('%Y-%m-%d'),
        'history': f'{init_start}~', 'stocks': season}, ensure_ascii=False), encoding='utf-8')
    MDD_OUT.write_text(json.dumps({'date': datetime.now().strftime('%Y-%m-%d'),
        'stocks': mdd}, ensure_ascii=False), encoding='utf-8')
    print(f"  ✅ 계절성 {len(season)} · MDD {len(mdd)}종목 저장")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--start', default=None, help='장기 다운로드 시작일 (예: 2008-01-01)')
    args = ap.parse_args()
    run(args.start)
