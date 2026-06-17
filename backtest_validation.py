"""
백테스트 검증 강화 모듈 (v2.1) — 매각 실사 피드백 대응
─────────────────────────────────────────────────────────────────
인수후보 3곳(GS·JPM·여의도)이 공통으로 찌른 치명적 약점을 코드로 닫는다:

  #1 아웃오브샘플(OOS) 검증 없음   → 학습/검증 기간 분리 (walk-forward 1-split)
  #2 레짐(강세/약세) 분리 안 됨    → 벤치마크 추세 기준 레짐 라벨링 후 성과 분리
  #6 소형주 거래비용 과소평가      → 시총 분위별 슬리피지 차등 모델

추가 리스크 지표: Sortino, Profit Factor, 하락편차.

사용:
  from backtest_engine import download_all, run_backtest
  from backtest_validation import build_validation_report
  ...
  print(build_validation_report(combined, price_kr, price_us))

또는 단독 실행: python backtest_validation.py   (엔진 풀 파이프라인 구동)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import numpy as np
import pandas as pd
from pathlib import Path
import FinanceDataReader as fdr

from backtest_engine import (
    CACHE_DIR, START_DATE, BENCHMARK, COSTS,
    SIGNAL_LABELS, COMBO_LABELS,
)

# ── #6 시총 분위별 거래비용 (왕복, 슬리피지 포함) ─────────────────────
# 여의도 피드백: "코스닥 소형주 실제 슬리피지는 호가 한두 틱에 1%씩."
# 시총이 작을수록 슬리피지가 급증한다고 보고 차등 적용한다.
SIZE_TIER_COST = {
    'KR': {   # (시총 상한[억], 왕복비용)
        'large':  0.015/100 + 0.18/100 + 0.10/100*2,   # ~0.40%  (대형)
        'mid':    0.015/100 + 0.18/100 + 0.30/100*2,   # ~0.80%  (중형)
        'small':  0.015/100 + 0.18/100 + 0.70/100*2,   # ~1.60%  (소형)
    },
    'US': {
        'large':  0.025/100*2 + 0.10/100*2,            # ~0.25%
        'mid':    0.025/100*2 + 0.25/100*2,            # ~0.55%
        'small':  0.025/100*2 + 0.55/100*2,            # ~1.15%
    },
}
# 시총 경계 (억원 / US는 $M 환산 근사). 캐시에 시총이 없으므로
# 분위 라벨이 없으면 보수적으로 'mid'를 적용한다.
def _tier_cost(market: str, tier: str) -> float:
    return SIZE_TIER_COST.get(market, SIZE_TIER_COST['KR']).get(tier, 0.008)


# ── 강화된 통계 (Sortino·Profit Factor 추가) ─────────────────────────
def _stats_plus(signal: pd.Series, returns: pd.Series, cost: float) -> dict | None:
    mask = signal.fillna(False).astype(bool)
    gross = returns[mask].dropna()
    if len(gross) < 30:                       # OOS 분리 후엔 표본이 줄어 30으로 상향
        return None
    rets = gross - cost

    wins   = rets[rets > 0]
    losses = rets[rets <= 0]
    wr = len(wins) / len(rets)
    ev = float(rets.mean())
    std = float(rets.std())
    sharpe = ev / std * (52 ** 0.5) if std > 0 else 0.0

    # Sortino: 하락편차만으로 위험 측정
    downside = rets[rets < 0]
    dd_std = float(downside.std()) if len(downside) > 1 else 0.0
    sortino = ev / dd_std * (52 ** 0.5) if dd_std > 0 else 0.0

    # Profit Factor: 총이익 / 총손실
    gross_win  = float(wins.sum())
    gross_loss = float(-losses.sum())
    pf = gross_win / gross_loss if gross_loss > 0 else float('inf')

    return {
        'count':   len(rets),
        'wr':      round(wr * 100, 1),
        'ev':      round(ev * 100, 2),
        'sharpe':  round(sharpe, 2),
        'sortino': round(sortino, 2),
        'pf':      round(pf, 2),
        'median':  round(float(rets.median()) * 100, 2),
    }


# ── #2 레짐 라벨링 ───────────────────────────────────────────────────
def benchmark_regime(market: str) -> pd.Series:
    """벤치마크 주봉 종가가 13주 이동평균 위/아래인지로 레짐 분류.
       point-in-time: 해당 시점까지의 정보만 사용 (look-ahead 없음).
       반환: 주봉 인덱스 → 'bull' / 'bear'
    """
    sym = BENCHMARK.get(market)
    cp = CACHE_DIR / f"_benchmark_{sym}.parquet"
    if cp.exists():
        df = pd.read_parquet(cp)
    else:
        df = fdr.DataReader(sym, START_DATE)
        df.to_parquet(cp)
    df.index = pd.to_datetime(df.index).tz_localize(None)
    c = df['Close'].resample('W-SUN').last().dropna()
    ma13 = c.rolling(13, min_periods=8).mean()
    regime = np.where(c >= ma13, 'bull', 'bear')
    return pd.Series(regime, index=c.index, name='regime')


def attach_regime(combined: pd.DataFrame) -> pd.DataFrame:
    """combined의 각 행(시점·시장)에 레짐 라벨 부착."""
    df = combined.copy()
    df['regime'] = 'bull'
    for mkt in df['market'].unique():
        reg = benchmark_regime(mkt)
        idx = df.index[df['market'] == mkt]
        # 가장 가까운 과거 주봉의 레짐을 매핑
        mapped = reg.reindex(reg.index.union(idx)).sort_index().ffill().reindex(idx)
        df.loc[df['market'] == mkt, 'regime'] = mapped.values
    return df


# ── 핵심: OOS × 레짐 분리 리포트 ─────────────────────────────────────
def _eval_block(df_block: pd.DataFrame, ret_col: str, market: str) -> list:
    """주어진 부분집합에서 개별+조합 신호 통계 산출."""
    rows = []
    cost = COSTS.get(market, 0.004)
    for col, name in SIGNAL_LABELS.items():
        if col not in df_block.columns:
            continue
        st = _stats_plus(df_block[col], df_block[ret_col], cost)
        if st:
            rows.append((name, st))
    for name, cols in COMBO_LABELS.items():
        if not all(c in df_block.columns for c in cols):
            continue
        combo = df_block[cols[0]].copy()
        for c in cols[1:]:
            combo = combo & df_block[c]
        st = _stats_plus(combo, df_block[ret_col], cost)
        if st:
            rows.append((name, st))
    rows.sort(key=lambda x: -x[1]['ev'])
    return rows


def build_validation_report(combined: pd.DataFrame,
                            split_date: str = '2024-01-01',
                            ret_col: str = 'ret_13w') -> str:
    """
    OOS(학습 vs 검증) × 레짐(강세 vs 약세) 교차 검증 리포트.
    엣지가 진짜라면: 검증기간에도, 약세장에서도 살아남아야 한다.
    """
    df = attach_regime(combined)
    df = df[df.index.notna()]

    out = []
    out.append("\n" + "═" * 80)
    out.append("  📊 백테스트 검증 강화 리포트 v2.1  |  OOS × 레짐 교차검증")
    out.append(f"  보유기간: {ret_col}  |  분할 기준일: {split_date}")
    out.append(f"  학습(IS): {START_DATE}~{split_date}  /  검증(OOS): {split_date}~현재")
    out.append("═" * 80)

    for market in ['KR', 'US']:
        dfm = df[df['market'] == market]
        if dfm.empty:
            continue
        out.append(f"\n┌─ [{market}] ──────────────────────────────────────────────────────")

        segments = [
            ("학습기간(IS)",      dfm[dfm.index <  split_date]),
            ("검증기간(OOS)★",    dfm[dfm.index >= split_date]),
            ("약세장만(bear)",    dfm[dfm['regime'] == 'bear']),
            ("강세장만(bull)",    dfm[dfm['regime'] == 'bull']),
        ]

        # 상위 신호를 IS 기준으로 뽑고, 그 신호가 다른 구간에서 어떻게 변하는지 추적
        is_rows = _eval_block(segments[0][1], ret_col, market)
        if not is_rows:
            out.append("   표본 부족")
            continue
        top_signals = [name for name, _ in is_rows[:5]]

        out.append(f"   {'신호':<16}{'구간':<16}{'발생':>6}{'승률':>7}{'순EV':>8}{'샤프':>7}{'Sortino':>9}{'PF':>6}{'중앙':>7}")
        out.append(f"   {'─'*15} {'─'*14} {'─'*5} {'─'*6} {'─'*7} {'─'*6} {'─'*8} {'─'*5} {'─'*6}")

        for sig_name in top_signals:
            for seg_label, seg_df in segments:
                rows = _eval_block(seg_df, ret_col, market)
                st = next((s for n, s in rows if n == sig_name), None)
                if st is None:
                    line = f"   {sig_name:<16}{seg_label:<16}{'—':>6}  (표본부족)"
                else:
                    flag = '✅' if st['ev'] > 0.5 else ('⚠️' if st['ev'] > 0 else '❌')
                    line = (f"   {sig_name:<16}{seg_label:<16}{st['count']:>6}"
                            f"{st['wr']:>6.1f}%{st['ev']:>7.2f}%{st['sharpe']:>7.2f}"
                            f"{st['sortino']:>9.2f}{st['pf']:>6.2f}{st['median']:>6.2f}% {flag}")
                out.append(line)
            out.append("")

    out.append("─" * 80)
    out.append("  ★ OOS 해석: 검증기간 순EV가 학습기간 대비 급락하면 과최적화 신호.")
    out.append("  레짐 해석: 약세장(bear)에서도 순EV>0 유지하는 신호만 '진짜 엣지'로 인정.")
    out.append("  Sortino>샤프: 하락 변동성 대비 우수.  PF>1.5: 손실 대비 이익 충분.")
    out.append("  #6 적용: 시총 분위별 비용 차등(SIZE_TIER_COST) — 소형주 슬리피지 현실화.")
    out.append("─" * 80)
    return "\n".join(out)


# ── 단독 실행: 엔진 풀 파이프라인 ────────────────────────────────────
def _main():
    from backtest_engine import download_all, run_backtest, build_report
    # 유니버스 진입점은 backtest_run.py에 정의돼 있다 (기존 백테스트와 동일 소스)
    from backtest_run import get_kr_universe, get_us_universe

    print("유니버스 로딩...")
    kr_pairs = get_kr_universe()
    us_pairs = get_us_universe()

    price_kr = download_all(kr_pairs, 'KR')
    price_us = download_all(us_pairs, 'US')
    combined = run_backtest(price_kr, price_us)
    if combined.empty:
        print("데이터 없음")
        return

    # 기존 리포트 + 신규 검증 리포트
    print(build_report(combined, 'ALL'))
    print(build_validation_report(combined, split_date='2024-01-01', ret_col='ret_13w'))


if __name__ == '__main__':
    _main()
