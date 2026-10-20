"""CANSLIM US C·A — 일회성 손익 제외 근사(영업이익 기준, 2026-10-20 점검 #6)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from canslim_us_run import growth_pair


def test_lite_like_debt_extinguishment_loss():
    # 순이익은 흑자→대규모 적자(부채 소멸 손실), 영업이익은 +40% → 판정은 영업이익, 일회성 의심
    core, gaap, odd, b = growth_pair(-7_800, 29, 140, 100)
    assert (core, gaap, odd, b) == (40.0, '적자전환', True, 'OP')


def test_tax_benefit_inflates_net_income():
    core, gaap, odd, _ = growth_pair(300, 100, 120, 100)
    assert core == 20.0 and gaap == 200.0 and odd


def test_consistent_growth_not_flagged():
    core, gaap, odd, _ = growth_pair(130, 100, 125, 100)
    assert core == 25.0 and gaap == 30.0 and not odd


def test_bank_without_operating_income_falls_back_to_net_income():
    assert growth_pair(120, 100, None, None) == (20.0, 20.0, False, 'NI')


def test_turnaround_both_agree():
    assert growth_pair(50, -10, 40, -5) == ('흑자전환', '흑자전환', False, 'OP')
