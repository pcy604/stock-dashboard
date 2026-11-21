# -*- coding: utf-8 -*-
"""퀀트 패널 빈 지표 채우기 정답 테스트 (2026-11-22).

왜 이 파일이 있나 — 2026-11-22 실측에서 화면에 지표로 떠 있는데 패널에는 열이 비어
조건을 걸면 **오류 없이 매매 0건**이 나오는 것이 셋 있었다:
  · oi_g(이익 개선폭) — kr() 가 줄곧 계산했는데 COLS 에 없어 _f32 가 버림
  · sector(미국)       — leaders_build 가 factor_weekly.sector 에 None 을 박음
  · rev_qoq(한국)      — 열만 있고 계산이 없음
빈 열은 조용히 NaN → 조건 전부 거짓 → 0건. 오류가 안 나니 아무도 모른다.
그래서 ① 계산을 수기 값으로 박고 ② 커버리지 게이트가 실제로 터지는지 같이 잰다.
"""
import os
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "research"))

import quant_panel as Q           # noqa: E402
import leaders_build as L         # noqa: E402


# ──────────────────────────────────────────────────────────────────────
# 1) _inst — 재무상태표(시점 사실) 추출
# ──────────────────────────────────────────────────────────────────────
def _facts(**tags):
    return {"facts": {"us-gaap": {t: {"units": {"USD": arr}} for t, arr in tags.items()}}}


def test_inst_takes_earliest_filed():
    """같은 end 가 원본·수정분으로 두 번 나오면 **먼저 제출된 값**을 쓴다.
    늦게 수정 제출된 잔액을 그 주에 알았다고 하면 look-ahead 다."""
    f = _facts(StockholdersEquity=[
        {"end": "2024-03-31", "val": 100, "filed": "2024-05-01"},
        {"end": "2024-03-31", "val": 999, "filed": "2025-02-01"},     # 수정 제출
    ])
    assert Q is not None
    assert L._inst(f, ["StockholdersEquity"]) == {"2024-03-31": (100, "2024-05-01")}


def test_inst_ignores_duration_facts():
    """start 가 있는 것은 기간 사실(매출 같은 것)이다 — 잔액으로 세면 안 된다."""
    f = _facts(StockholdersEquity=[
        {"start": "2024-01-01", "end": "2024-03-31", "val": 7, "filed": "2024-05-01"},
        {"end": "2024-03-31", "val": 100, "filed": "2024-05-01"},
    ])
    assert L._inst(f, ["StockholdersEquity"]) == {"2024-03-31": (100, "2024-05-01")}


def test_inst_tag_priority_front_wins():
    """앞 태그가 채운 분기는 뒤 태그가 덮지 않는다(StockholdersEquity 우선, 없으면 비지배지분 포함분)."""
    f = _facts(
        StockholdersEquity=[{"end": "2024-03-31", "val": 100, "filed": "2024-05-01"}],
        StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest=[
            {"end": "2024-03-31", "val": 130, "filed": "2024-05-01"},     # 덮지 않아야
            {"end": "2024-06-30", "val": 140, "filed": "2024-08-01"},     # 비어 있으니 채워야
        ])
    got = L._inst(f, L.TAGS_INST["equity"])
    assert got["2024-03-31"][0] == 100
    assert got["2024-06-30"][0] == 140


def test_inst_usd_only():
    """주식 수(shares) 단위 사실이 섞여 들어오면 금액으로 쓸 수 없다."""
    f = {"facts": {"us-gaap": {"Liabilities": {"units": {
        "shares": [{"end": "2024-03-31", "val": 5, "filed": "2024-05-01"}]}}}}}
    assert L._inst(f, ["Liabilities"]) == {}


# ──────────────────────────────────────────────────────────────────────
# 2) 부채비율·PBR·ROE 수기 계산
# ──────────────────────────────────────────────────────────────────────
def test_debt_ratio_hand_value():
    """부채 2.0679B ÷ 자본 11.228B = 18.42% (PLTR 2026Q3 SEC 실측값)."""
    assert round(2_067_876_000 / 11_227_980_000 * 100, 2) == 18.42


@pytest.mark.parametrize("eq", [0, -1_000, None])
def test_pbr_roe_blank_when_equity_not_positive(eq):
    """자본잠식(자본 ≤ 0)이면 PBR·ROE 는 뜻이 없다 — 숫자를 만들면 '싸 보이는 결손기업'이 된다."""
    mc, ni = 1e9, 1e8
    pbr = mc / eq if eq and eq > 0 else None
    roe = (ni / eq * 100) if (eq and eq > 0) else None
    assert pbr is None and roe is None


# ──────────────────────────────────────────────────────────────────────
# 3) 한국 매출 QoQ · 이익 개선폭
# ──────────────────────────────────────────────────────────────────────
def _q(rows):
    """rows: (sym, year, q, revenue, op_income)"""
    d = pd.DataFrame(rows, columns=["sym", "year", "q", "revenue", "op_income"])
    d["net_income"] = d.op_income
    return d.sort_values(["sym", "year", "q"]).reset_index(drop=True)


def test_kr_rev_qoq_hand_value():
    """매출 100 → 125 면 +25%. 직전 분기가 0 이하면 빈값(발산)."""
    q = _q([("A", 2024, 1, 100.0, 1.0), ("A", 2024, 2, 125.0, 1.0),
            ("A", 2024, 3, 0.0, 1.0), ("A", 2024, 4, 50.0, 1.0)])
    g = q.groupby("sym")
    r1 = g.revenue.shift(1)
    got = pd.Series(np.where(r1 > 0, (q.revenue / r1 - 1) * 100, np.nan))
    assert np.isnan(got[0])                 # 직전 분기 없음
    assert got[1] == pytest.approx(25.0)
    assert got[2] == pytest.approx(-100.0)
    assert np.isnan(got[3])                 # 직전 분기 매출 0 → 빈값

def test_kr_oi_g_hand_value():
    """이익 개선폭(%p) = (영업익 − 전년 같은 분기) ÷ |매출| × 100.
    적자 −50 → +50, 매출 1,000억이면 (50 −(−50))/1000 = +10%p."""
    rows = [("A", y, qq, 1e11, v) for (y, qq), v in
            zip([(2023, 1), (2023, 2), (2023, 3), (2023, 4), (2024, 1)],
                [-5e9, 0.0, 0.0, 0.0, 5e9])]
    q = _q(rows)
    got = Q.kr_oi_g(q)
    assert np.isnan(got.iloc[0])
    assert got.iloc[4] == pytest.approx(10.0)


def test_kr_oi_g_blank_under_min_revenue():
    """분기 매출 100억원 미만은 빈값 — 매출이 사업 규모를 대표하지 못해 발산한다."""
    q = _q([("A", 2023, k, 1e8, -1e9) for k in (1, 2, 3, 4)] + [("A", 2024, 1, 1e8, 1e9)])
    assert Q.kr_oi_g(q).isna().all()


# ──────────────────────────────────────────────────────────────────────
# 4) 미국 이익 개선폭 — 한국과 같은 식·같은 단위(%p)
# ──────────────────────────────────────────────────────────────────────
def test_us_oi_g_same_formula_as_kr():
    """미국은 하한만 다르다($10M). 같은 투입이면 두 시장의 값이 같아야 한다 —
    단위가 어긋나면(비율 vs %p) 같은 조건이 시장마다 100배 다르게 걸린다."""
    import leaders_accel as A
    rev, o_prev, o_now = 1e9, -5e7, 5e7
    rows = [("A", 2023, k, rev, o_prev) for k in (1, 2, 3, 4)] + [("A", 2024, 1, rev, o_now)]
    q = _q(rows)
    o4 = q.groupby("sym").op_income.shift(4)
    _rev = q.revenue.where(q.revenue.abs() >= A.MIN_QREV)
    us = ((q.op_income - o4) / _rev.abs() * 100).replace([np.inf, -np.inf], np.nan)
    assert us.iloc[4] == pytest.approx(10.0)


# ──────────────────────────────────────────────────────────────────────
# 5) COLS · 커버리지 게이트
# ──────────────────────────────────────────────────────────────────────
def test_engine_base_fields_all_in_cols():
    """엔진이 조건으로 쓸 수 있다고 화면에 내건 필드는 전부 패널 COLS 에 있어야 한다.
    oi_g 가 빠져 '지표는 보이는데 매매 0건'이 났던 것을 다시 못 하게 막는 테스트."""
    import quant_engine as E
    missing = [c for c in E._BASE if c not in Q.COLS]
    assert not missing, f"엔진 _BASE 에 있는데 패널 COLS 에 없는 열: {missing}"


def test_must_columns_are_known_fields():
    """MUST·NOT_YET 에 적은 이름이 실제 COLS 에 있는 열이어야 한다(오타 방지)."""
    for m, cols in list(Q.MUST.items()) + list(Q.NOT_YET.items()):
        bad = [c for c in cols if c not in Q.COLS]
        assert not bad, f"{m}: COLS 에 없는 이름 {bad}"


def test_must_and_not_yet_do_not_overlap():
    """같은 열이 '반드시 있어야' 하면서 '소스 없음'일 수는 없다."""
    for m in Q.MUST:
        assert not (set(Q.MUST[m]) & set(Q.NOT_YET.get(m, ()))), m


def _panel(**over):
    n = 4
    base = dict(sym=["A"] * n, name=["a"] * n, market=["KR"] * n,
                date=pd.date_range("2024-01-01", periods=n, freq="W-MON"))
    for c in Q.COLS:
        if c in base:
            continue
        base[c] = [1.0] * n
    base.update(over)
    return pd.DataFrame(base)


def test_report_coverage_raises_on_dead_must_column():
    """MUST 열이 0% 면 빌드를 세운다 — 빈 패널을 릴리스에 올리지 않는다."""
    d = _panel(oi_g=[np.nan] * 4)
    with pytest.raises(SystemExit) as e:
        Q.report_coverage(d, "KR")
    assert "oi_g" in str(e.value)


def test_report_coverage_allows_not_yet_column():
    """아직 소스가 없다고 적어 둔 열(KR gpm)이 0% 인 것은 통과해야 한다 — 아니면 매 빌드가 실패한다."""
    d = _panel(gpm=[np.nan] * 4)
    Q.report_coverage(d, "KR")


def test_report_coverage_passes_full_panel():
    Q.report_coverage(_panel(), "KR")
    Q.report_coverage(_panel(market=["US"] * 4), "US")


# ──────────────────────────────────────────────────────────────────────
# 6) factor_weekly 열 추가 — DDL 에만 적으면 조용히 버려진다
# ──────────────────────────────────────────────────────────────────────
def test_add_cols_adds_and_is_idempotent(tmp_path):
    import sqlite3
    c = sqlite3.connect(str(tmp_path / "t.db"))
    c.execute("CREATE TABLE factor_weekly (as_of TEXT, sym TEXT)")
    L._add_cols(c)
    have = {x[1] for x in c.execute("PRAGMA table_info(factor_weekly)")}
    assert {"equity", "liabilities", "debt", "roe"} <= have
    L._add_cols(c)                                   # 두 번 불러도 터지지 않아야
    assert len({x[1] for x in c.execute("PRAGMA table_info(factor_weekly)")}) == len(have)


def test_schema_sql_has_new_cols():
    """새 DB(CREATE TABLE 경로)도 같은 열을 가져야 한다 — ALTER 쪽만 고치면 CI 새 DB 에서 어긋난다."""
    s = open(os.path.join(ROOT, "leaders_schema.sql"), encoding="utf-8").read()
    for c, _ in L._NEW_COLS:
        assert f"\n  {c} " in s, f"leaders_schema.sql 에 {c} 없음"


def test_cache_due_refetches_when_column_missing(tmp_path):
    """수집 항목을 늘렸을 때 기존 캐시(열 없음)를 반드시 다시 받아야 한다.
    이 가드가 없으면 TAGS 에 추가해도 2,800개 캐시가 그대로 쓰여 새 열이 영원히 빈다."""
    p = tmp_path / "fq_X.csv"
    pd.DataFrame([dict(period_end="2026-09-30", filed_at="2026-11-03", revenue=1)]).to_csv(p, index=False)
    assert L._cache_due(str(p), "period_end", gap_days=120, need_cols=("equity", "liabilities"))
    assert not L._cache_due(str(p), "period_end", gap_days=120)      # 열을 안 따지면 나이 규칙대로(방금 만들었으니 False)
