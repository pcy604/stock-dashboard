"""
계절성 + MDD 사전계산 (캐시 1회 스캔) → results/seasonality.json, results/mdd.json
─────────────────────────────────────────────────────────────────
무거운 계산이라 미리 돌려 JSON으로 저장 → 대시보드는 읽기만.

계절성: 종목별 '캘린더 월별' 평균수익·승률 (몇 월에 잘 오르나)
MDD:    종목별 역대 최대낙폭 · 현재 고점대비 낙폭 · 1년 MDD (많이 빠진 종목 = 턴어라운드 후보)

실행:  python screen_precompute.py
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime

from backtest_engine import CACHE_DIR

SEASON_OUT = Path('results/seasonality.json')
MDD_OUT = Path('results/mdd.json')


def _name_map():
    m = {}
    for f in ['perf_latest', 'screener_latest', 'canslim_latest']:
        p = Path(f'results/{f}.json')
        if p.exists():
            try:
                for s in json.loads(p.read_text(encoding='utf-8')).get('stocks', []):
                    m.setdefault(s['sym'], (s.get('name', s['sym']), s.get('market', 'US')))
            except Exception:
                pass
    return m


def _mdd(close):
    """최대낙폭 % (음수)."""
    peak = close.cummax()
    dd = (close / peak - 1) * 100
    return float(dd.min())


def run():
    names = _name_map()
    files = [f for f in CACHE_DIR.glob('*.parquet') if not f.stem.startswith('_benchmark')]
    print(f"  캐시 {len(files)}개 스캔...")

    season, mdd = [], []
    done = 0
    for f in files:
        sym = f.stem
        mkt = 'KR' if (sym.isdigit() and len(sym) == 6) else 'US'
        name = names.get(sym, (sym, mkt))[0]
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if df.empty or len(df) < 250:
            continue
        close = df['Close'].dropna()
        done += 1
        if done % 400 == 0:
            print(f"\r  {done}", end='', flush=True)

        # ── 계절성: 월별 수익률 ──
        mclose = close.resample('ME').last().dropna()
        mret = mclose.pct_change().dropna() * 100
        if len(mret) >= 24:
            by_month = {}
            for mo in range(1, 13):
                vals = mret[mret.index.month == mo]
                if len(vals) >= 2:
                    by_month[mo] = {
                        'ret': round(float(vals.mean()), 1),
                        'wr': round(float((vals > 0).mean() * 100), 0),
                        'n': int(len(vals)),
                    }
            if by_month:
                season.append({'sym': sym, 'name': name, 'market': mkt, 'months': by_month})

        # ── MDD ──
        cur = float(close.iloc[-1])
        peak_all = float(close.cummax().iloc[-1])
        cur_dd = round((cur / peak_all - 1) * 100, 1)
        yr = close.tail(252)
        mdd.append({
            'sym': sym, 'name': name, 'market': mkt,
            'mdd_all': round(_mdd(close), 1),
            'mdd_1y': round(_mdd(yr), 1),
            'cur_dd': cur_dd,
            'price': round(cur, 2),
        })
    print()

    SEASON_OUT.write_text(json.dumps(
        {'date': datetime.now().strftime('%Y-%m-%d'), 'stocks': season},
        ensure_ascii=False), encoding='utf-8')
    MDD_OUT.write_text(json.dumps(
        {'date': datetime.now().strftime('%Y-%m-%d'), 'stocks': mdd},
        ensure_ascii=False), encoding='utf-8')
    print(f"  ✅ 계절성 {len(season)}종목 → {SEASON_OUT}")
    print(f"  ✅ MDD {len(mdd)}종목 → {MDD_OUT}")


if __name__ == '__main__':
    run()
