"""quant_engine.report · dd_events · diagnose — 손으로 계산한 정답 (2026-11-22 결과 리포트 확장 · 0값 진단)."""
import numpy as np
import pandas as pd
import pytest
import quant_engine as Q


def _s(vals, start='2021-01-04'):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq='W-MON'), dtype=float)


def test_dd_events_two_episodes():
    # 100 → 110(고점) → 99 → 88(바닥 −20%) → 110(회복) → 120(고점) → 90(바닥 −25%) → 121(회복)
    ev = Q.dd_events(_s([100, 110, 99, 88, 110, 120, 90, 121]))
    assert len(ev) == 2
    a, b = ev.iloc[0], ev.iloc[1]
    assert a['깊이(%)'] == pytest.approx(-20.0)
    assert (a['바닥까지(주)'], a['회복까지(주)'], a['수중(주)']) == (2, 1, 3)
    assert b['깊이(%)'] == pytest.approx(-25.0)
    assert (b['바닥까지(주)'], b['회복까지(주)'], b['수중(주)']) == (1, 1, 2)


def test_dd_events_unrecovered_and_small_ignored():
    ev = Q.dd_events(_s([100, 97, 100, 100, 70, 80]))      # −3% 는 버림, −30% 는 미회복
    assert len(ev) == 1
    assert ev.iloc[0]['깊이(%)'] == pytest.approx(-30.0)
    assert ev.iloc[0]['회복일'] is None and ev.iloc[0]['회복까지(주)'] is None


def test_report_counts_and_yearly():
    idx = pd.to_datetime(['2020-12-28', '2021-06-07', '2021-12-27', '2022-06-06', '2022-12-26'])
    eq = pd.Series([100, 120, 110, 132, 121], index=idx, dtype=float)
    R = Q.report(eq, eq)                                     # 지수 = 전략 → 차이 0, 포착률은 표본 부족(5주 미만)이라 None
    Y = R['yearly'].set_index('연도')
    assert Y.loc[2021, '전략 수익(%)'] == pytest.approx(10.0)
    assert Y.loc[2021, '전략 MDD(%)'] == pytest.approx(-100 / 12, rel=1e-9)
    assert Y.loc[2022, '전략 수익(%)'] == pytest.approx(10.0)
    assert Y.loc[2022, '차이(%p)'] == pytest.approx(0.0)
    assert R['이긴연도'] == 0


def test_report_capture_beta_identity():
    rng = np.random.default_rng(0)
    eq = _s(100 * np.cumprod(1 + rng.normal(0.002, 0.03, 200)))
    R = Q.report(eq, eq)
    assert R['상승포착'] == pytest.approx(100.0)
    assert R['하락포착'] == pytest.approx(100.0)
    assert R['베타'] == pytest.approx(1.0)
    assert R['롤링1년']['지수상회비율'] == 0.0


def test_report_trades_hold_streak_contrib():
    d = pd.date_range('2021-01-04', periods=10, freq='W-MON')
    T = pd.DataFrame([
        dict(날짜=d[0], 종목='A', 코드='A', 구분='매수', 가격=1, 금액비중=10, 사유='', 수익률=None),
        dict(날짜=d[4], 종목='A', 코드='A', 구분='매도', 가격=1, 금액비중=15, 사유='', 수익률=50.0),   # 4주 · 기여 15×0.5/1.5 = 5
        dict(날짜=d[1], 종목='B', 코드='B', 구분='매수', 가격=1, 금액비중=10, 사유='', 수익률=None),
        dict(날짜=d[3], 종목='B', 코드='B', 구분='매도', 가격=1, 금액비중=8, 사유='', 수익률=-20.0),    # 2주 · 손실 1
        dict(날짜=d[5], 종목='C', 코드='C', 구분='매수', 가격=1, 금액비중=10, 사유='', 수익률=None),
        dict(날짜=d[8], 종목='C', 코드='C', 구분='매도', 가격=1, 금액비중=9, 사유='', 수익률=-10.0),    # 3주 · 손실 2(연속)
    ])
    R = Q.report(_s(np.linspace(100, 120, 60)), None, T)
    assert R['평균보유주'] == pytest.approx(3.0)
    assert R['최대연속손실'] == 1            # 날짜순: B 손실(d3) → A 이익(d4)이 끊음 → C 손실(d8) = 최대 연속 1
    top = R['상위기여'].set_index('종목')['실현 기여(%p)']
    assert top['A (A)'] == pytest.approx(5.0)
    assert R['신뢰']['등급'] == 'D'          # 매도 3건 — 표본 부족


def _panel(n=30):
    d = pd.date_range('2020-01-06', periods=n, freq='W-MON')
    rows = []
    for s, base in (('A', 100.0), ('B', 50.0)):
        for i, t in enumerate(d):
            p = base * (1 + 0.01 * i)
            rows.append(dict(sym=s, name=s, market='US', date=t, open=p, high=p, low=p, close=p, volume=1e6,
                             marcap=1e10, per=10.0 if s == 'A' else 30.0, pbr=1.0, psr=1.0, rev_yoy=10.0, op_yoy=10.0,
                             op_turn=0, acc=0, sector='x'))
    return Q.Panel(pd.DataFrame(rows))


BASE = dict(start='2020-01-06', rank=dict(field='marcap', desc=True), max_pos=1, max_w=1.0, exit=dict(signals=[]), cost=0.0)


def test_diagnose_missing_field():
    D, why = Q.diagnose(_panel(), dict(BASE, filters=[dict(field='roe', op='>=', value=10)]))
    assert D.iloc[0]['데이터 보유(%)'] == 0.0
    assert any('이 시장에 없는 데이터' in w for w in why)
    assert D.iloc[-1]['주 평균 충족(종목)'] == 0.0


def test_diagnose_unit_mismatch_message():
    D, why = Q.diagnose(_panel(), dict(BASE, filters=[dict(field='per', op='<=', value=0.1)]))   # PER 은 배수(10·30) — 0.1 은 불가능
    assert D.iloc[0]['데이터 보유(%)'] == 100.0
    assert any('단위' in w for w in why)


def test_diagnose_disjoint_and():
    f = [dict(field='per', op='<=', value=15), dict(field='per', op='>=', value=25)]   # A 만 · B 만 → AND 는 영원히 0
    D, why = Q.diagnose(_panel(), dict(BASE, filters=f))
    assert D.iloc[0]['주 평균 충족(종목)'] == 1.0 and D.iloc[1]['주 평균 충족(종목)'] == 1.0
    assert D.iloc[2]['주 평균 충족(종목)'] == 0.0
    assert any('동시에 충족된 적이 없음' in w for w in why)


def test_diagnose_normal_matches_run():
    spec = dict(BASE, filters=[dict(field='per', op='<=', value=15)])
    D, why = Q.diagnose(_panel(), spec)
    assert why == []
    assert D.iloc[-1]['주 평균 충족(종목)'] == 1.0
    r = Q.run(_panel(), spec)
    assert set(r['trades'].코드) == {'A'}     # 진단이 '후보 = A' 라고 한 것과 엔진 실제 매수가 같다
