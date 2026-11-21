# -*- coding: utf-8 -*-
"""quant_engine — 손으로 계산한 정답과 숫자를 그대로 대조한다 (2026-11-22, 백로그 #3).

tests/test_quant_engine.py 는 '성질'을 본다(가격을 따라가나, 손절이 터지나).
이 파일은 다르다 — **종이에 적을 수 있는 정확한 값**을 박아 둔다. 거래비용·1주 지연·
수량 계산 중 하나라도 어긋나면 어긋난 만큼 숫자가 틀어지므로, 리팩터링이 조용히
깨뜨리는 것을 잡는다.

엔진 규약(quant_engine.py 머리말):
  · 체결은 주봉. 그 주 **종가로 판정 → 다음 주 시가**에 체결(1주 지연).
  · 매수는 cash -= amt*(1+cost), 매도는 cash += amt*(1-cost). 양방향 모두 비용.
  · equity 는 각 주 종가 평가액. 첫 원소는 t0 주의 값(= 아직 현금 1.0).
"""
import numpy as np
import pandas as pd
import pytest

import quant_engine as Q


def _panel(prices, opens=None):
    """주봉 패널. opens 를 주면 시가를 따로 지정(갭·체결가 대조용)."""
    n = len(next(iter(prices.values())))
    d = pd.date_range('2020-01-06', periods=n, freq='W-MON')
    rows = []
    for s, px in prices.items():
        op = (opens or {}).get(s, px)
        for t, p, o in zip(d, px, op):
            rows.append(dict(sym=s, name=s, market='US', date=t, open=o, high=max(p, o) * 1.0,
                             low=min(p, o) * 1.0, close=p, volume=1e6, marcap=1e10,
                             per=10.0, pbr=1.0, psr=1.0, rev_yoy=10.0, op_yoy=10.0,
                             op_turn=0, acc=0, sector='x'))
    return Q.Panel(pd.DataFrame(rows))


BASE = dict(start='2020-01-06', filters=[], rank=dict(field='marcap', desc=True),
            max_pos=1, max_w=1.0, exit=dict(signals=[]), cost=0.0)


# ──────────────────────────────────────────────────────────────────────────
# 1. 수량·평가액 — 손으로 적은 값 그대로
# ──────────────────────────────────────────────────────────────────────────
def test_golden_단일종목_수량과_최종평가액():
    """1주차 종가 100 으로 판정 → 2주차 시가 110 에 전액 매수 → 5주차 종가 150.

    현금 1.0, 비용 0 → 수량 = 1.0 / 110 = 0.00909090...
    최종 평가액 = 수량 × 150 = 150 / 110 = 1.3636363636...
    """
    P = _panel({'A': [100, 120, 130, 140, 150]},
               opens={'A': [100, 110, 125, 135, 145]})
    r = Q.run(P, BASE)
    units = 1.0 / 110
    assert r['equity'].iloc[-1] == pytest.approx(units * 150, rel=1e-6)
    assert r['equity'].iloc[-1] == pytest.approx(1.3636363636363635, rel=1e-6)

    t = r['trades']
    assert len(t) == 1
    assert t.iloc[0].구분 == '매수'
    assert t.iloc[0].가격 == pytest.approx(110.0)        # 다음 주 '시가' 다 — 판정 주 종가(100) 가 아니다
    assert t.iloc[0].날짜 == P.dates[1]                   # 1주 지연


def test_golden_1주지연은_첫주_상승을_놓친다():
    """지연이 없으면 1주차 시가 100 에 사서 100→150 (1.5배).
    지연이 있으면 2주차 시가 110 에 사서 110→150 (1.3636배).
    둘의 차이가 '지연이 실제로 걸려 있다'는 증거다."""
    P = _panel({'A': [100, 120, 130, 140, 150]},
               opens={'A': [100, 110, 125, 135, 145]})
    got = Q.run(P, BASE)['equity'].iloc[-1]
    지연없음 = 150 / 100
    지연있음 = 150 / 110
    assert got == pytest.approx(지연있음, rel=1e-6)
    assert got < 지연없음 - 0.1


# ──────────────────────────────────────────────────────────────────────────
# 2. 거래비용 — 매수·매도 양방향으로 정확히 한 번씩
# ──────────────────────────────────────────────────────────────────────────
def test_golden_매수비용만_반영된_평가액():
    """cost=0.003. 현금 1.0 으로 '비용 포함' 1.0 을 쓴다 → amt = 1/(1+0.003).

    수량 = amt / 110 = 1 / (1.003 × 110)
    최종 = 수량 × 150 = 150 / (1.003 × 110) = 1.359557...
    """
    P = _panel({'A': [100, 120, 130, 140, 150]},
               opens={'A': [100, 110, 125, 135, 145]})
    r = Q.run(P, dict(BASE, cost=0.003))
    expected = 150 / (1.003 * 110)
    assert r['equity'].iloc[-1] == pytest.approx(expected, rel=1e-6)
    assert r['equity'].iloc[-1] == pytest.approx(1.3595576, rel=1e-6)
    # 비용 0 대비 정확히 1/1.003 배
    r0 = Q.run(P, BASE)
    assert r['equity'].iloc[-1] / r0['equity'].iloc[-1] == pytest.approx(1 / 1.003, rel=1e-6)


def test_golden_왕복비용은_두번_물린다():
    """손절로 되팔아 현금이 된 뒤의 금액 = (1/(1+c)) × (매도가/매수가) × (1-c).

    1주 종가 100 판정 → 2주 시가 110 매수 → 손절선 110×(1−0.50) = 55.
    4주차는 시가 70(> 55) 에 저가 50(< 55) → 주중에 손절선 55 를 때린다 → 55 에 체결.
    현금 = (1/1.003) × (55/110) × (1−0.003) = 0.49701...
    """
    P = _panel({'A': [100, 120, 100, 50, 50]},
               opens={'A': [100, 110, 115, 70, 50]})
    r = Q.run(P, dict(BASE, cost=0.003, exit=dict(stop=50, signals=[])))
    s = r['trades'][r['trades'].구분 == '매도']
    assert len(s) == 1
    assert s.iloc[0].가격 == pytest.approx(55.0)          # 손절선에 체결(주중 스탑)
    expected_cash = (1 / 1.003) * (55 / 110) * (1 - 0.003)
    assert r['equity'].iloc[-1] == pytest.approx(expected_cash, rel=1e-6)
    # 비용을 두 번 물었는지: 비용 0 대비 (1/1.003)×0.997
    r0 = Q.run(P, dict(BASE, exit=dict(stop=50, signals=[])))
    assert r['equity'].iloc[-1] / r0['equity'].iloc[-1] == pytest.approx(0.997 / 1.003, rel=1e-6)


def test_golden_비용은_거래수에_비례한다():
    """왕복이 2번이면 비용은 4번 물린다 — 매수 2 × (1+c), 매도 2 × (1−c).
    cooldown=0 으로 손절 직후 재진입하게 만들어 두 왕복을 만든다.
    저가가 손절선 아래로 내려가야 발동하므로 종가를 50 까지 떨어뜨렸다."""
    px = [100, 120, 50, 100, 120, 50, 100]
    op = [100, 110, 70, 90, 110, 70, 95]
    P = _panel({'A': px}, opens={'A': op})
    sp = dict(BASE, exit=dict(stop=50, cooldown=0, signals=[]))
    r0 = Q.run(P, sp)
    rc = Q.run(P, dict(sp, cost=0.003))
    n_buy = int((r0['trades'].구분 == '매수').sum())
    n_sell = int((r0['trades'].구분 == '매도').sum())
    assert n_buy >= 2 and n_sell >= 1          # 비용 사건이 3번 이상 — 왕복 1번보다 많다
    ratio = rc['equity'].iloc[-1] / r0['equity'].iloc[-1]
    expected = (1 / 1.003) ** n_buy * (0.997 ** n_sell)
    assert ratio == pytest.approx(expected, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# 3. 갭 손절 — 손절선이 아니라 시가에 체결된다
# ──────────────────────────────────────────────────────────────────────────
def test_golden_갭하락은_손절선이_아니라_시가():
    """stop=20 → 손절선 110×0.8 = 88. 4주차 시가 70 이 이미 88 아래(갭) → 70 에 체결.
    손절선 88 에 체결됐다고 가정하면 성과가 부풀려진다 — 그 실수를 잡는 케이스."""
    P = _panel({'A': [100, 120, 100, 65, 65]},
               opens={'A': [100, 110, 115, 70, 65]})
    r = Q.run(P, dict(BASE, exit=dict(stop=20, signals=[])))
    s = r['trades'][r['trades'].구분 == '매도']
    assert len(s) == 1
    assert s.iloc[0].가격 == pytest.approx(70.0)
    assert r['equity'].iloc[-1] == pytest.approx(70 / 110, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# 4. 불타기 — 목표 비중의 몫만큼, 단계마다 한 번
# ──────────────────────────────────────────────────────────────────────────
def test_golden_불타기_수량을_단계별로_계산():
    """init=0.5 · pyramid=[[20, 0.5]] · max_w=1.0 · cost=0.

    1주 종가 100 판정 → 2주 시가 100 에 목표의 50% = 0.5 매수 → 수량 0.005
    2주 종가 125(= 진입가 100 대비 +25% ≥ 20%) 판정 → 3주 시가 125 에 추가.
      추가액 = 목표(E) × 0.5. 이때 E = 2주 종가 평가액 = 0.5(현금) + 0.005×125 = 1.125
      → 추가액 0.5625, 수량 += 0.5625/125 = 0.0045 → 총 0.0095, 현금 0.5-0.5625 < 0?
      현금이 부족하면 엔진은 cash/(1+cost) 로 깎는다 → 추가액 = 0.5 전액
      수량 += 0.5/125 = 0.004 → 총 0.009, 현금 0
    4주 종가 200 → 평가액 = 0.009 × 200 = 1.8
    """
    P = _panel({'A': [100, 125, 150, 200]},
               opens={'A': [100, 100, 125, 180]})
    r = Q.run(P, dict(BASE, entry=dict(init=0.5, pyramid=[[20, 0.5]])))
    assert (r['trades'].구분 == '불타기').sum() == 1
    assert r['equity'].iloc[-1] == pytest.approx(0.009 * 200, rel=1e-6)
    assert r['equity'].iloc[-1] == pytest.approx(1.8, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────────
# 5. 상장폐지(가격 끊김) 처리 — 지금 엔진이 '마지막 종가'로 턴다는 사실을 박제
# ──────────────────────────────────────────────────────────────────────────
def test_golden_상폐는_마지막종가에_전액_청산된다():
    """이건 '옳다'는 테스트가 아니라 **현재 동작을 고정하는** 테스트다.

    실제 상장폐지는 마지막 종가에 전량 매도할 수 없다(정리매매에서 보통 큰 손실).
    즉 이 처리는 낙관적이다. 생존편향 감사의 근거 — docs/research/2026-11-22_백테스트_엔진_감사.md
    가격이 끊기면 그 주에 마지막 종가로 팔고 '가격 끊김(상폐·이탈)' 로 기록한다.
    """
    P = _panel({'A': [100, 120, 140, np.nan, np.nan, np.nan, np.nan],
                'B': [100, 100, 100, 100, 100, 100, 100]},
               opens={'A': [100, 110, 130, np.nan, np.nan, np.nan, np.nan],
                      'B': [100, 100, 100, 100, 100, 100, 100]})
    r = Q.run(P, dict(BASE, max_pos=2, max_w=0.5))
    s = r['trades'][r['trades'].사유.astype(str).str.contains('가격 끊김')]
    assert len(s) == 1
    assert s.iloc[0].코드 == 'A'
    assert s.iloc[0].가격 == pytest.approx(140.0)         # 마지막 종가 전액 — 손실 가정 없음


# ──────────────────────────────────────────────────────────────────────────
# 6. 생존편향 — 상폐 충격을 넣는 손잡이가 엔진에 있는지
# ──────────────────────────────────────────────────────────────────────────
def test_상폐충격_손잡이가_없다는_사실을_고정():
    """CLAUDE.md: '생존편향은 한계라고 적지 말고 크기를 재라'(leaders_port_bt 는 shock= 로 잰다).
    quant_engine 에는 그 손잡이가 없다 — 이 테스트는 **생기면 실패해서** 감사 문서를
    갱신하라고 알린다. 손잡이가 추가되면 이 테스트를 지우고 충격 반영 테스트를 쓸 것."""
    assert 'shock' not in Q.DEFAULT_SPEC, 'shock 이 생겼다 → 감사 문서와 이 테스트를 갱신'
    import inspect
    assert 'shock' not in inspect.signature(Q.run).parameters
