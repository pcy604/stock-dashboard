"""
위닝 스코어 백테스트 — "점수가 실제 미래수익을 갈랐나?"
─────────────────────────────────────────────────────────────────
방법(멍거식 정직):
  · backtest_engine이 만든 '답지' = 과거 매주 시점의 신호 + 그 이후 1·4·13주 실제수익
    (모든 신호는 shift(1) 기반 → look-ahead 없음)
  · 그 각 시점·종목에 winning_score를 그대로 매긴다(과거에 알 수 있던 정보만으로)
  · 등급(S/A/B/C)별로 '이후 실제 수익'을 모아 비교
  · 점수가 진짜면 → S > A > B > C 로 수익이 단조 증가해야 한다

정직한 한계:
  · 과거 펀더멘털(CANSLIM) 재구성 불가 → 기술점수만으로 채점(US/KR 공통)
  · 가중치를 백테스트 샤프로 정했으므로 전기간은 in-sample → '내부 일관성' 검증
    이라서, 올해(2026)만 따로도 보여줘 최근 구간 확인
  · 생존편향: 현재 상장 종목만 → 낙관 편향. 절대수익 아닌 '등급간 상대'를 봐라

실행:  python winning_backtest.py            (전기간 + 2026)
       python winning_backtest.py --year 2026
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import argparse
import pandas as pd
from pathlib import Path

from backtest_engine import CACHE_DIR, compute_signals_returns, COSTS
import winning_score as ws

SIG_COLS = ['sig_52w', 'sig_vol', 'sig_ma5', 'sig_cup', 'sig_maconv', 'sig_rsimacd']


def load_cached_prices():
    kr, us = {}, {}
    for f in CACHE_DIR.glob('*.parquet'):
        if f.stem.startswith('_benchmark'):
            continue
        sym = f.stem
        try:
            df = pd.read_parquet(f)
        except Exception:
            continue
        if sym.isdigit() and len(sym) == 6:
            kr[sym] = df
        else:
            us[sym] = df
    return kr, us


def build_scored_panel(start_date=None):
    """모든 캐시 종목 → 주봉 신호+미래수익 → 각 행에 winning_score 채점."""
    kr, us = load_cached_prices()
    print(f"  캐시 로드: KR {len(kr)} · US {len(us)}")
    frames = []
    done = 0
    total = len(kr) + len(us)
    for market, pool in [('KR', kr), ('US', us)]:
        for sym, df in pool.items():
            sig = compute_signals_returns(df)
            done += 1
            if done % 400 == 0:
                print(f"\r  신호계산 {done}/{total}", end='', flush=True)
            if sig is None or sig.empty:
                continue
            sig = sig.copy()
            sig['market'] = market
            if start_date:
                sig = sig[sig.index >= start_date]
            if not sig.empty:
                frames.append(sig)
    print()
    if not frames:
        return pd.DataFrame()
    panel = pd.concat(frames)

    # 각 행 채점 (기술점수만, 펀더/라이브 중립)
    def _row_score(r):
        sd = {c: bool(r.get(c)) for c in SIG_COLS}
        sd['dist_52w'] = r.get('dist_52w')
        score, _, grade, _ = ws.score_stock(sd, can=None, live={})
        return score, grade

    print("  위닝 스코어 채점 중...")
    scores = panel.apply(lambda r: _row_score(r), axis=1)
    panel['win_score'] = [s for s, _ in scores]
    panel['grade'] = [g for _, g in scores]
    return panel


def _agg(panel, ret_col, market):
    cost = COSTS.get(market, 0.004)
    sub = panel[panel['market'] == market]
    rows = []
    for grade in ['S', 'A', 'B', 'C']:
        g = sub[sub['grade'] == grade]
        rets = (g[ret_col] - cost).dropna()
        if len(rets) < 20:
            rows.append((grade, len(rets), None, None, None))
            continue
        rows.append((grade, len(rets), rets.mean() * 100,
                     (rets > 0).mean() * 100, rets.median() * 100))
    return rows


def report(panel, label):
    print("\n" + "═" * 74)
    print(f"  🏅 위닝 스코어 백테스트  |  {label}  |  표본 {len(panel):,}건(종목·주)")
    print("  등급이 높을수록 이후 실제수익이 큰가? (비용 차감 후)")
    print("═" * 74)
    horizons = [('ret_1w', '1주 후(≈일간)'), ('ret_4w', '4주 후(≈주간)'), ('ret_13w', '13주 후(≈월간)')]
    for market in ['KR', 'US']:
        if (panel['market'] == market).sum() == 0:
            continue
        print(f"\n┌─ [{market}] ───────────────────────────────────────────────")
        for ret_col, hl in horizons:
            print(f"  · {hl}")
            print(f"     {'등급':<5}{'표본':>8}{'평균수익':>10}{'승률':>9}{'중앙값':>9}")
            rows = _agg(panel, ret_col, market)
            vals = {}
            for grade, n, avg, wr, med in rows:
                if avg is None:
                    print(f"     {grade:<5}{n:>8}{'표본부족':>10}")
                    continue
                vals[grade] = avg
                print(f"     {grade:<5}{n:>8}{avg:>9.2f}%{wr:>8.1f}%{med:>8.2f}%")
            if 'S' in vals and 'C' in vals:
                spread = vals['S'] - vals['C']
                mono = all(vals.get(a, -9) >= vals.get(b, 9) for a, b in [('S', 'A'), ('A', 'B'), ('B', 'C')] if a in vals and b in vals)
                print(f"     → S−C 스프레드 {spread:+.2f}%p  {'✅단조증가' if mono else '⚠️비단조'}")
    print("\n" + "─" * 74)
    print("  해석: S−C 스프레드가 +면 점수에 변별력 있음. 단조증가면 등급이 의미 있음.")
    print("  ⚠️ 생존편향으로 절대수익은 낙관적 → '등급 간 차이'에 집중.")
    print("═" * 74)


def _main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--year', type=int, default=None, help='특정 연도만 (예: 2026)')
    args = ap.parse_args()

    if args.year:
        panel = build_scored_panel(start_date=f'{args.year}-01-01')
        panel = panel[panel.index < f'{args.year + 1}-01-01']
        report(panel, f'{args.year}년')
    else:
        panel = build_scored_panel(start_date='2021-01-01')
        report(panel, '전기간 2021~현재')
        p26 = panel[(panel.index >= '2026-01-01')]
        if not p26.empty:
            report(p26, '2026년 (최근 구간)')


if __name__ == '__main__':
    _main()
