"""quant_engine — 합성 패널로 체결·손절·불타기·노출·달력 확인 (2026-11-01)."""
import numpy as np
import pandas as pd
import quant_engine as Q


def _panel(prices, n_wk=None):
    d = pd.date_range('2020-01-06', periods=len(next(iter(prices.values()))), freq='W-MON')
    rows = []
    for s, px in prices.items():
        for t, p in zip(d, px):
            rows.append(dict(sym=s, name=s, market='US', date=t, open=p, high=p * 1.01, low=p * 0.99, close=p, volume=1e6,
                             marcap=1e10, per=10.0, pbr=1.0, psr=1.0, rev_yoy=10.0, op_yoy=10.0, op_turn=0, acc=0, sector='x'))
    return Q.Panel(pd.DataFrame(rows))


BASE = dict(start='2020-01-06', filters=[], rank=dict(field='marcap', desc=True), max_pos=1, max_w=1.0,
            exit=dict(signals=[]), cost=0.0)


def test_buy_and_hold_tracks_price():
    P = _panel({'A': list(np.linspace(100, 200, 30))})
    r = Q.run(P, BASE)
    # 첫 주 종가 판단 → 둘째 주 시가 매수(≈103.4) → 마지막 200
    assert abs(r['equity'].iloc[-1] - 200 / P.base('open').iloc[1, 0]) < 1e-6
    assert (r['trades'].구분 == '매수').sum() == 1


def test_stop_sells_at_level():
    px = [100] * 3 + [100, 80, 70, 60] + [60] * 5
    P = _panel({'A': px})
    r = Q.run(P, dict(BASE, exit=dict(stop=10, signals=[])))
    s = r['trades'][r['trades'].구분 == '매도']
    assert len(s) >= 1 and abs(s.iloc[0].가격 - 80) < 1e-6        # 갭으로 손절선(90) 아래 시가 → 시가 80 에 체결
    assert s.iloc[0].사유.startswith('손절')


def test_pyramid_adds_once_per_tier():
    P = _panel({'A': list(np.linspace(100, 300, 40))})
    r = Q.run(P, dict(BASE, entry=dict(init=0.5, pyramid=[[20, 0.25], [40, 0.25]])))
    assert (r['trades'].구분 == '불타기').sum() == 2


def test_calendar_months_off_means_cash():
    P = _panel({'A': list(np.linspace(100, 200, 60))})
    r = Q.run(P, dict(BASE, exposure=dict(months=[11, 12, 1, 2, 3, 4])))
    ex = r['exposure']
    summer = ex[(ex.index.month >= 6) & (ex.index.month <= 9)]
    assert (summer < 0.01).all()


def test_fields_dist_hi_never_positive():
    P = _panel({'A': list(np.linspace(100, 200, 60)), 'B': list(np.linspace(200, 100, 60))})
    assert (P.get('dist_hi:52').max().max() <= 0)
