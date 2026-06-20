"""
레짐 적응형 보유·청산 백테스트 — "어떻게 들고 있어야 제일 버나?"
─────────────────────────────────────────────────────────────────
앞선 발견: 수익은 신호보다 '레짐 × 보유기간'이 갈랐다.
  · 추세장(KR 2026): 길게 들수록 수익 ↑ (1주 1% → 13주 20%)
  · 횡보장(US 2026): 길게 들수록 무의미/역전

그래서 진짜 질문: 청산 규칙을 바꾸면 수익이 어떻게 달라지나?
A등급(위닝 스코어≥65) 진입에 대해, 같은 진입을 여러 청산법으로 시뮬레이션:

  ① 고정 4주      ② 고정 13주
  ③ 트레일링 15%  ④ 트레일링 20%   (고점 대비 X% 빠지면 청산, 최대 26주)
  ⑤ 레짐적응: 진입 시 추세장 → 트레일링15%(길게 타기) / 횡보·하락장 → 1주 손절후 청산

모든 신호 shift(1), 비용 차감, 레짐은 벤치마크 13주 이평 기준(point-in-time).
※ 생존편향 존재 → 절대수익보다 '청산법 간 상대비교'를 봐라.

실행:  python regime_backtest.py --year 2026 --grade 65
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import argparse
import numpy as np
import pandas as pd
from pathlib import Path

from backtest_engine import CACHE_DIR, compute_signals_returns, COSTS
from backtest_validation import benchmark_regime
import winning_score as ws

SIG_COLS = ['sig_52w', 'sig_vol', 'sig_ma5', 'sig_cup', 'sig_maconv', 'sig_rsimacd']


def load_cached():
    kr, us = {}, {}
    for f in CACHE_DIR.glob('*.parquet'):
        if f.stem.startswith('_benchmark'):
            continue
        sym = f.stem
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        (kr if (sym.isdigit() and len(sym) == 6) else us)[sym] = df
    return kr, us


def _trail_exit(prices, stop=0.15, max_w=26):
    """주봉 종가 트레일링 스톱. prices[0]=진입가. 반환 (수익률, 보유주수)."""
    entry = prices[0]
    peak = entry
    for i in range(1, min(max_w, len(prices) - 1) + 1):
        p = prices[i]
        peak = max(peak, p)
        if p <= peak * (1 - stop):
            return p / entry - 1, i
    last_i = min(max_w, len(prices) - 1)
    return prices[last_i] / entry - 1, last_i


def _fixed_exit(prices, weeks):
    if len(prices) <= weeks:
        return None, None
    return prices[weeks] / prices[0] - 1, weeks


def run(year=2026, grade_min=65.0):
    kr, us = load_cached()
    print(f"  캐시: KR {len(kr)} · US {len(us)}")
    start = f'{year}-01-01'
    end = f'{year + 1}-01-01'

    results = {m: {k: [] for k in ['고정4주', '고정13주', '트레일15', '트레일20', '레짐적응']}
               for m in ['KR', 'US']}
    hold_w = {m: {'트레일15': [], '레짐적응': []} for m in ['KR', 'US']}

    for market, pool in [('KR', kr), ('US', us)]:
        regime = benchmark_regime(market)
        regime = regime.reindex(regime.index).sort_index()
        cost = COSTS.get(market, 0.004)
        done = 0
        for sym, df in pool.items():
            done += 1
            if done % 400 == 0:
                print(f"\r  [{market}] {done}/{len(pool)}", end='', flush=True)
            sig = compute_signals_returns(df)
            if sig is None or sig.empty:
                continue
            wclose = df['Close'].resample('W-SUN').last().dropna()
            # 진입주: 해당 연도 + 위닝스코어>=grade_min
            cand = sig[(sig.index >= start) & (sig.index < end)]
            for t, row in cand.iterrows():
                sd = {c: bool(row.get(c)) for c in SIG_COLS}
                sd['dist_52w'] = row.get('dist_52w')
                score, _, _, _ = ws.score_stock(sd, None, {})
                if score < grade_min:
                    continue
                if t not in wclose.index:
                    continue
                fut = wclose.loc[t:].values
                if len(fut) < 2:
                    continue
                # 레짐 (진입 시점 이하 가장 최근)
                rg = regime.reindex(regime.index.union([t])).sort_index().ffill().get(t, 'bull')

                f4, _ = _fixed_exit(fut, 4)
                f13, _ = _fixed_exit(fut, 13)
                t15, h15 = _trail_exit(fut, 0.15)
                t20, _ = _trail_exit(fut, 0.20)
                if rg == 'bull':
                    adp, hadp = _trail_exit(fut, 0.15)
                else:
                    adp, hadp = _fixed_exit(fut, 1)

                R = results[market]
                if f4 is not None:  R['고정4주'].append(f4 - cost)
                if f13 is not None: R['고정13주'].append(f13 - cost)
                R['트레일15'].append(t15 - cost); hold_w[market]['트레일15'].append(h15)
                R['트레일20'].append(t20 - cost)
                if adp is not None:
                    R['레짐적응'].append(adp - cost); hold_w[market]['레짐적응'].append(hadp)
        print()

    # ── 리포트 ──
    print("\n" + "═" * 76)
    print(f"  🔄 레짐 적응형 청산 백테스트  |  {year}년  |  진입조건: 위닝스코어 ≥ {grade_min:.0f}")
    print("  같은 진입, 청산법만 바꿨을 때 평균수익 (비용 차감)")
    print("═" * 76)
    for market in ['KR', 'US']:
        R = results[market]
        n = len(R['트레일15'])
        if n == 0:
            continue
        print(f"\n┌─ [{market}]  진입 {n}건 ──────────────────────────────────")
        print(f"   {'청산법':<12}{'평균수익':>10}{'승률':>9}{'중앙값':>10}{'평균보유':>10}")
        best = None
        for k in ['고정4주', '고정13주', '트레일15', '트레일20', '레짐적응']:
            arr = np.array(R[k]) if R[k] else np.array([])
            if len(arr) < 10:
                print(f"   {k:<12}{'표본부족':>10}")
                continue
            avg = arr.mean() * 100
            wr = (arr > 0).mean() * 100
            med = np.median(arr) * 100
            hw = ''
            if k in hold_w[market] and hold_w[market][k]:
                hw = f"{np.mean(hold_w[market][k]):.1f}주"
            mark = ''
            if best is None or avg > best[1]:
                best = (k, avg)
            print(f"   {k:<12}{avg:>9.2f}%{wr:>8.1f}%{med:>9.2f}%{hw:>10}{mark}")
        if best:
            print(f"   → 최고 수익 청산법: ★ {best[0]} ({best[1]:+.2f}%)")
    print("\n" + "─" * 76)
    print("  해석: '레짐적응'이 고정보유보다 높으면 → 레짐 맞춰 들고 있는 게 더 번다는 증거.")
    print("  트레일링이 고정13주보다 높으면 → 되돌림 전 탈출이 수익을 지킨다는 증거.")
    print("  ⚠️ 생존편향·표본수 유의. 등급/연도 바꿔 강건성 확인 권장.")
    print("═" * 76)


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=2026)
    ap.add_argument('--grade', type=float, default=65.0, help='최소 위닝스코어 (A=65)')
    args = ap.parse_args()
    run(args.year, args.grade)


if __name__ == '__main__':
    _main()
