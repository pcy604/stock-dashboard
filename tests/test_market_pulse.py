import numpy as np
import pandas as pd

import market_pulse as mp


def _s(vals, vols):
    idx = pd.bdate_range('2026-01-01', periods=len(vals))
    return pd.Series(vals, idx, dtype=float), pd.Series(vols, idx, dtype=float)


def test_uptrend_no_correction():
    c, v = _s(np.linspace(100, 120, 120), np.full(120, 100))
    assert mp.pulse(c, v)['state'] == '상승 추세'


def test_correction_then_ftd():
    vals = list(np.linspace(100, 120, 60)) + list(np.linspace(120, 100, 40))   # −16.7% 조정, 최저 = 마지막
    vals += [100.5, 101, 101.2, 103]                                            # 4일째 +1.78%
    vols = [100] * (len(vals) - 1) + [150]
    c, v = _s(vals, vols)
    r = mp.pulse(c, v)
    assert r['state'] == '상승 확인' and r['ftd_date'] == str(c.index[-1].date())


def test_rally_attempt_without_ftd():
    vals = list(np.linspace(100, 120, 60)) + list(np.linspace(120, 100, 40)) + [100.3, 100.6]
    c, v = _s(vals, [100] * len(vals))
    assert mp.pulse(c, v)['state'] == '반등 시도 2일째'


def test_distribution_day_counts_and_expires():
    vals = list(np.linspace(100, 110, 100)) + [109.5]      # −0.45% 거래량 증가 → 분배일
    vols = [100] * 100 + [200]
    c, v = _s(vals, vols)
    assert mp.pulse(c, v)['dist_n'] == 1
    vals2 = vals + [116]                                     # 그 뒤 +5.9% → 지움
    c2, v2 = _s(vals2, vols + [100])
    assert mp.pulse(c2, v2)['dist_n'] == 0
