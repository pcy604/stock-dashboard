# -*- coding: utf-8 -*-
"""실전 원장 성과 — 손으로 푼 정답과 맞춘다 (네트워크 없음)."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "live"))
import perf as P  # noqa: E402

D = pd.to_datetime(["2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"])
BENCH = pd.Series([100.0, 110.0, 99.0, 121.0], index=D)


def test_cash_only_is_flat_and_bench_moves():
    df = P.build([("2026-11-03", 300000)], [], pd.DataFrame(index=D), BENCH)
    s, me, bm = P.summary(df)
    assert s["twr"] == 0 and s["pnl"] == 0 and s["mdd"] == 0 and s["cash_share"] == 1
    assert s["bench_twr"] == pytest.approx(0.21)
    assert s["bench_mdd"] == pytest.approx(99 / 110 - 1)          # −10%
    assert s["excess"] == pytest.approx(-0.21)


def test_trade_and_second_deposit_twr():
    # 11-03 100만 입금, 11-04 A 10주 @1만 매수(수수료 1,000), 11-05 50만 추가 입금, 11-06 A 5주 @1.3만 매도
    px = pd.DataFrame({"A": [None, 10000.0, 12000.0, 13000.0]}, index=D)
    tr = [dict(day="2026-11-04", sym="A", side="BUY", qty=10, px=10000, fee=1000),
          dict(day="2026-11-06", sym="A", side="SELL", qty=5, px=13000, fee=500)]
    df = P.build([("2026-11-03", 1_000_000), ("2026-11-05", 500_000)], tr, px, BENCH)
    # 손으로: 11-04 nav = 999,000-? → 현금 1,000,000-100,000-1,000=899,000 + 주식 100,000 = 999,000
    assert df["nav"].iloc[1] == pytest.approx(999_000)
    # 11-05: 현금 1,399,000 + 120,000 = 1,519,000
    assert df["nav"].iloc[2] == pytest.approx(1_519_000)
    # 11-06: 현금 1,399,000+65,000-500 = 1,463,500 + 5주×13,000=65,000 → 1,528,500
    assert df["nav"].iloc[3] == pytest.approx(1_528_500)
    s, me, _ = P.summary(df)
    exp = (999_000 / 1_000_000) * (1_519_000 / (999_000 + 500_000)) * (1_528_500 / 1_519_000)
    assert me.iloc[-1] == pytest.approx(exp)
    assert s["pnl"] == pytest.approx(28_500)
    # 지수 계좌: 10,000단위 + 5,050.5단위(50만/99) → 15,050.5 × 121
    assert s["bench_nav"] == pytest.approx((10_000 + 500_000 / 99) * 121)


def test_deposit_on_holiday_snaps_forward():
    df = P.build([("2026-11-01", 100)], [], pd.DataFrame(index=D), BENCH)   # 일요일 입금
    assert df.index[0] == D[0] and df["invested"].iloc[0] == 100


def test_no_deposit_empty():
    s, me, bm = P.summary(P.build([], [], pd.DataFrame(), BENCH))
    assert s == {} and me.empty


def test_real_ledger_loads():
    dep, tr = P.load("KR")
    assert dep and all(a > 0 for _, a in dep)
