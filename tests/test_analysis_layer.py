"""종목 분석 화면의 계산 층 고정 (2026-10-20) — 부문 XBRL 파서 · 월별 통계 · 데이터/리스크 점검.

화면은 네트워크가 있어야 그려지지만, 숫자를 만드는 부분은 여기서 네트워크 없이 검증한다."""
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import analysis_checks as AC  # noqa: E402
import monthly_stats as MS  # noqa: E402
import segment_xbrl as SX  # noqa: E402

AX = 'us-gaap:StatementBusinessSegmentsAxis'


def _ctx(i, st, en, dims=()):
    d = ''.join(f'<xbrldi:explicitMember dimension="{a}">{m}</xbrldi:explicitMember>' for a, m in dims)
    seg = f'<xbrli:segment>{d}</xbrli:segment>' if d else ''
    return (f'<xbrli:context id="{i}"><xbrli:entity><xbrli:identifier scheme="x">1</xbrli:identifier>{seg}'
            f'</xbrli:entity><xbrli:period><xbrli:startDate>{st}</xbrli:startDate>'
            f'<xbrli:endDate>{en}</xbrli:endDate></xbrli:period></xbrli:context>')


def _doc(ctxs, facts):
    x = ('<xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:xbrldi="http://xbrl.org/2006/xbrldi" '
         'xmlns:us-gaap="http://fasb.org/us-gaap/2026" xmlns:dei="http://xbrl.sec.gov/dei/2026">')
    x += ''.join(ctxs)
    x += ('<dei:DocumentPeriodEndDate contextRef="d">2026-06-30</dei:DocumentPeriodEndDate>'
          '<dei:DocumentType contextRef="d">10-Q</dei:DocumentType>')
    for c, n, v in facts:
        x += f'<us-gaap:{n} contextRef="{c}" unitRef="usd" decimals="-6">{int(v)}</us-gaap:{n}>'
    return (x + '</xbrli:xbrl>').encode()


def test_segment_xbrl_tesla_shape():
    """TSLA 2026-06 10-Q 구조(부문 매출·매출총이익, 분기·누적) — 실제 공시 값."""
    ctx = [_ctx('d', '2026-04-01', '2026-06-30'),
           _ctx('q1', '2026-04-01', '2026-06-30', [(AX, 'tsla:AutomotiveSegmentMember')]),
           _ctx('q2', '2026-04-01', '2026-06-30', [(AX, 'tsla:EnergyGenerationAndStorageSegmentMember')]),
           _ctx('y1', '2026-01-01', '2026-06-30', [(AX, 'tsla:AutomotiveSegmentMember')]),
           _ctx('y2', '2026-01-01', '2026-06-30', [(AX, 'tsla:EnergyGenerationAndStorageSegmentMember')]),
           _ctx('py', '2025-04-01', '2025-06-30', [(AX, 'tsla:AutomotiveSegmentMember')]),
           _ctx('el', '2026-04-01', '2026-06-30', [(AX, 'x:IntersegmentEliminationMember')])]
    facts = [('d', 'Revenues', 28236e6), ('q1', 'Revenues', 25097e6), ('q2', 'Revenues', 3139e6),
             ('q1', 'GrossProfit', 4111e6), ('q2', 'GrossProfit', 640e6),
             ('y1', 'Revenues', 45076e6), ('y2', 'Revenues', 5547e6), ('py', 'Revenues', 1), ('el', 'Revenues', -5)]
    r = SX.parse(_doc(ctx, facts))
    q = r['periods']['q']
    assert r['period_end'] == '2026-06-30' and r['form'] == '10-Q'
    assert [s['name'] for s in q['segments']] == ['Automotive', 'Energy Generation And Storage']
    assert q['segments'][0]['gross_profit'] == 4111e6
    assert abs(q['check_pct']) < 1e-9                       # 부문 합 = 연결 매출
    assert 'ytd' in r['periods'] and r['periods']['ytd']['segments'][0]['revenue'] == 45076e6
    assert all('Elimination' not in s['member'] for s in q['segments'])   # 조정 항목은 부문이 아니다


def test_segment_xbrl_nvda_consolidation_dim():
    """NVDA 형: 부문 값에 ConsolidationItemsAxis=OperatingSegments 가 같이 붙는다 → 받아야 한다."""
    CI = ('srt:ConsolidationItemsAxis', 'us-gaap:OperatingSegmentsMember')
    ctx = [_ctx('d', '2026-04-01', '2026-06-30'),
           _ctx('a', '2026-04-01', '2026-06-30', [CI, (AX, 'nvda:ComputeAndNetworkingSegmentMember')]),
           _ctx('b', '2026-04-01', '2026-06-30', [CI, (AX, 'nvda:GraphicsSegmentMember')])]
    facts = [('d', 'Revenues', 100), ('a', 'Revenues', 90), ('b', 'Revenues', 10),
             ('a', 'OperatingIncomeLoss', 60), ('b', 'OperatingIncomeLoss', 3)]
    q = SX.parse(_doc(ctx, facts))['periods']['q']
    assert {s['name'] for s in q['segments']} == {'Compute And Networking', 'Graphics'}
    assert q['segments'][0]['op_income'] == 60


def test_segment_xbrl_single_segment_is_none():
    ctx = [_ctx('d', '2026-04-01', '2026-06-30'), _ctx('a', '2026-04-01', '2026-06-30', [(AX, 'x:OnlyMember')])]
    assert SX.parse(_doc(ctx, [('d', 'Revenues', 10), ('a', 'Revenues', 10)])) is None


def test_monthly_stats_order_and_parity():
    idx = pd.bdate_range('2019-01-01', '2026-10-19')
    c = pd.Series(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, .02, len(idx)))), index=idx)
    raw, summ = MS.build(c)
    assert list(raw['연도']) == sorted(raw['연도'])          # 오래된 해 → 최신 해
    assert list(summ['구분']) == ['전체 평균', '전체 승률', '홀수해 평균', '홀수해 승률', '짝수해 평균', '짝수해 승률']
    odd = raw[raw['연도'].astype(int) % 2 == 1]['1월'].dropna()
    assert abs(summ.loc[2, '1월'] - odd.mean()) < 1e-9
    assert summ.loc[1, '연간'] is not None                   # 연간 승률도 채운다


def test_integrity_checks_flags():
    r = {x['name']: x for x in AC.integrity_checks(
        today=date(2026, 10, 20), last_price_date=date(2026, 10, 9), latest_quarter='2026-03',
        per_ttm=300, yf_trailing_pe=200, rev_ttm=95e9, yf_total_revenue=95.5e9,
        mcap=1.45e12, price=368, shares=3.2e9, seg_check_pct=0.0, n_analysts=2)}
    assert r['주가 최신']['state'] == 'warn'                 # 평일 7일 공백
    assert r['재무 최신']['state'] == 'warn'                 # 2026-03 분기 말부터 203일
    assert r['PER 교차검증']['state'] == 'warn' and r['매출 교차검증']['state'] == 'ok'
    assert r['시총 정합']['state'] == 'warn'                 # 368×3.2B = 1.18T ≠ 1.45T
    assert r['부문 합계 검산']['state'] == 'ok' and r['컨센서스 표본']['state'] == 'warn'
    na = AC.integrity_checks(today=date(2026, 10, 20), last_price_date=None, latest_quarter=None)
    assert all(x['state'] == 'na' for x in na if x['name'] != '현재가')   # 못 재면 '확인 불가' — 통과로 치지 않는다
    assert [x for x in na if x['name'] == '현재가'][0]['state'] == 'warn'
    nan_px = {x['name']: x for x in AC.integrity_checks(today=date(2026, 10, 20), last_price_date=date(2026, 10, 19),
                                                         latest_quarter='2026-06', price=float('nan'), bad_bars=1)}
    assert nan_px['현재가']['state'] == 'warn'               # 2026-10-20 $nan 사고 재발 방지


def test_risk_checks():
    r = {x['name']: x for x in AC.risk_checks(price=70, high52=100, band_rank=90, ttm_net_income=-1,
                                               opm_now=5, opm_4q_ago=10, debt_to_equity=50,
                                               eps_fy0_now=0.9, eps_fy0_30d=1.0, vol_annual=70,
                                               top_segment_share=88)}
    for k in ('청산선 아래(보유 시)', '밸류 부담', '적자', '마진 악화', '추정치 하향', '고변동성', '사업 집중'):
        assert r[k]['state'] == 'warn', k
    assert r['부채 부담']['state'] == 'ok'
    assert all(x['state'] == 'na' for x in AC.risk_checks())


# ── 2026-10-21 추세(Trend Template)·분기 이익 추이 ─────────────────────
def test_trend_template_rebound_not_called_breakdown():
    """저점에서 3배 오른 뒤 고점 −23% 조정 중인 종목(삼아알미늄형)을 '하락'이라 부르지 않는다."""
    import numpy as np, pandas as pd
    import stock_extras as sx
    idx = pd.bdate_range('2024-01-01', periods=520)
    down = np.linspace(100, 30, 300)            # 하락 → 저점 30
    up = np.linspace(30, 130, 180)              # 4배 넘게 반등 → 고점 130
    pull = np.linspace(130, 100, 40)            # 고점 −23%
    c = pd.Series(np.r_[down, up, pull], index=idx)
    t = sx.trend_template(c)
    assert t['n'] >= 6 and t['state'].startswith('상승 추세'), t
    assert round(t['from_high']) == -23
    assert t['weeks_since_high'] == 40 // 5 or t['weeks_since_high'] in (7, 8)
    # 계속 내리는 종목은 하락·바닥
    t2 = sx.trend_template(pd.Series(np.linspace(100, 40, 300), index=idx[:300]))
    assert t2['state'] == '하락·바닥 국면'
    assert sx.trend_template(c.head(100))['n'] is None


def test_earnings_trend_states():
    """가속 = 매출 YoY 와 (이익증가÷매출) 이 둘 다 직전 분기보다 커짐(leaders_accel 정의) + 연속 분기 수."""
    import stock_extras as sx

    def rows(ops, revs=None):   # 오래된 → 최근, 2024.1Q 부터. 매출 단위 1e9(하한 $10M 위)
        revs = revs or [100.0] * len(ops)
        out = [{'period': f'{2024 + i // 4}.{i % 4 + 1}Q', 'op_income': o * 1e9, 'revenue': r * 1e9}
               for i, (o, r) in enumerate(zip(ops, revs))]
        return out[::-1]
    # 수준 판정(가속 아님: 매출이 그대로라 Δrv = 0)
    assert sx.earnings_trend(rows([-5, -5, -5, -5, 3]))['level'] == '흑자전환'
    assert sx.earnings_trend(rows([-9, -5, -5, -5, -4]))['state'] == '적자 축소'
    assert sx.earnings_trend(rows([-4, -5, -5, -5, -9]))['state'] == '적자 확대'
    assert sx.earnings_trend(rows([5, 5, 5, 5, -1]))['state'] == '적자전환'
    assert sx.earnings_trend(rows([10, 10, 10, 10, 9]))['state'] == '이익 감소'
    assert sx.earnings_trend(rows([1, 2]))['state'] == '데이터 부족'
    # 매출·이익 둘 다 3분기 연속 빨라짐 → 3분기 연속 가속
    ops = [10, 10, 10, 10, 10, 11, 13, 17]
    revs = [100, 100, 100, 100, 100, 102, 106, 112]
    t = sx.earnings_trend(rows(ops, revs))
    assert t['streak'] == 3 and t['state'] == '이익 가속 · 3분기 연속' and t['tone'] == 'good', t['state']
    # 마지막 분기만 빨라짐 → 확인 전
    t = sx.earnings_trend(rows([10] * 7 + [12], [100] * 7 + [103]))
    assert t['streak'] == 1 and t['state'] == '가속 1분기 · 확인 전'
    # 이익은 늘지만 증가 속도가 줄면 '감속'
    t = sx.earnings_trend(rows([10, 10, 10, 10, 15, 15, 15, 14], [100, 100, 100, 100, 110, 110, 110, 108]))
    assert t['state'] == '이익 증가 · 감속', t['state']
    # 기저효과: 1년 전 이익이 아주 작았다
    assert sx.earnings_trend(rows([10, 10, 10, 0.5, 10, 10, 10, 12]))['base_warn'] is True


def test_dilution_parse_and_summary():
    import dart_client as D
    assert D.parse_kdate('2026년 03월 05일') == '2026-03-05' and D.parse_kdate('20251231') == '2025-12-31'
    assert D.parse_kdate('-') is None
    cb = D.parse_dilution_row('CB', {'rcept_no': '20250310000123', 'bd_tm': '5', 'bd_fta': '10,000,000,000',
                                     'cv_prc': '5,000', 'act_mktprcfl_cvprc_lwtrsprc': '3,500',
                                     'cvisstk_cnt': '2,000,000', 'cvisstk_tisstk_vs': '10.00',
                                     'cvrqpd_bgd': '2026년 03월 10일', 'cvrqpd_edd': '2030년 02월 10일', 'bddd': '2025년 03월 07일'})
    bw = D.parse_dilution_row('BW', {'rcept_no': '20220101000001', 'bd_fta': '1,000,000,000', 'ex_prc': '10,000',
                                     'nstk_isstk_cnt': '100,000', 'expd_edd': '2024-12-31'})
    eb = D.parse_dilution_row('EB', {'rcept_no': '20250601000002', 'ex_prc': '6,000', 'extg_stkcnt': '500,000',
                                     'exrqpd_edd': '20290101'})
    assert cb['price'] == 5000 and cb['floor'] == 3500 and cb['end'] == '2030-02-10' and cb['decided'] == '2025-03-07'
    assert bw['price'] == 10000 and bw['end'] == '2024-12-31' and bw['decided'] == '2022-01-01'
    assert D.classify_event('[기재정정]전환청구권 행사') == '전환청구' and D.classify_event('전환가액의조정') == '가액 조정(리픽싱)'
    assert D.classify_event('분기보고서 (2026.06)') is None
    s = AC.summarize_dilution([cb, bw, eb], shares_out=20_000_000, price=6000, today='2026-10-21')
    assert round(s['pot_pct'], 1) == 10.0            # BW 는 행사기간 끝 → 제외
    assert round(s['max_pct'], 1) == round(1e10 / 3500 / 2e7 * 100, 1)   # 리픽싱 바닥까지 = 14.3%
    assert round(s['itm_pct'], 1) == 10.0 and round(s['eb_pct'], 1) == 2.5 and s['n_active'] == 2
    r = {x['name']: x for x in AC.risk_checks(dilution_pct=10.0)}
    assert r['잠재 희석']['state'] == 'warn'


FORM4_XML = """<?xml version="1.0"?>
<ownershipDocument>
  <schemaVersion>X0508</schemaVersion><documentType>4</documentType>
  <periodOfReport>2026-03-02</periodOfReport>
  <aff10b5One>0</aff10b5One>
  <issuer><issuerCik>0001</issuerCik><issuerTradingSymbol>TEST</issuerTradingSymbol></issuer>
  <reportingOwner>
    <reportingOwnerId><rptOwnerCik>0002</rptOwnerCik><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId>
    <reportingOwnerRelationship><isDirector>0</isDirector><isOfficer>1</isOfficer><officerTitle>Chief Financial Officer</officerTitle></reportingOwnerRelationship>
  </reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <securityTitle><value>Common Stock</value></securityTitle>
      <transactionDate><value>2026-03-02</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>S</transactionCode><equitySwapInvolved>0</equitySwapInvolved><footnoteId id="F1"/></transactionCoding>
      <transactionAmounts><transactionShares><value>1,000</value></transactionShares><transactionPricePerShare><value>50.25</value><footnoteId id="F2"/></transactionPricePerShare><transactionAcquiredDisposedCode><value>D</value></transactionAcquiredDisposedCode></transactionAmounts>
      <postTransactionAmounts><sharesOwnedFollowingTransaction><value>9000</value></sharesOwnedFollowingTransaction></postTransactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
  <derivativeTable>
    <derivativeTransaction>
      <securityTitle><value>Restricted Stock Units</value></securityTitle>
      <conversionOrExercisePrice><footnoteId id="F3"/></conversionOrExercisePrice>
      <transactionDate><value>2026-03-01</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>4000</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
      <exerciseDate><footnoteId id="F4"/></exerciseDate><expirationDate><footnoteId id="F4"/></expirationDate>
      <underlyingSecurity><underlyingSecurityTitle><value>Common Stock</value></underlyingSecurityTitle><underlyingSecurityShares><value>4000</value></underlyingSecurityShares></underlyingSecurity>
    </derivativeTransaction>
    <derivativeTransaction>
      <securityTitle><value>Stock Option (Right to Buy)</value></securityTitle>
      <conversionOrExercisePrice><value>42.10</value></conversionOrExercisePrice>
      <transactionDate><value>2026-03-01</value></transactionDate>
      <transactionCoding><transactionFormType>4</transactionFormType><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts><transactionShares><value>12000</value></transactionShares><transactionPricePerShare><value>0</value></transactionPricePerShare><transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode></transactionAmounts>
      <exerciseDate><value>2027-03-01</value></exerciseDate><expirationDate><value>2036-03-01</value></expirationDate>
      <underlyingSecurity><underlyingSecurityTitle><value>Common Stock</value></underlyingSecurityTitle><underlyingSecurityShares><value>12000</value></underlyingSecurityShares></underlyingSecurity>
    </derivativeTransaction>
  </derivativeTable>
  <footnotes>
    <footnote id="F1">The sales reported were effected pursuant to a Rule 10b5-1 trading plan adopted by the reporting person on November 14, 2025.</footnote>
    <footnote id="F2">The price reported is a weighted average price.</footnote>
    <footnote id="F3">Each restricted stock unit represents a contingent right to receive one share of common stock.</footnote>
    <footnote id="F4">The RSUs vest in four equal annual installments beginning on the first anniversary of the grant date, subject to continued service.</footnote>
  </footnotes>
</ownershipDocument>"""


def test_form4_parse():
    import edgar_client as E
    rows = E.parse_form4(FORM4_XML, 'u')
    assert len(rows) == 3
    s, rsu, opt = rows
    assert s['code_label'] == '장내 매도' and s['shares'] == 1000 and s['price'] == 50.25 and s['plan_10b5_1']
    assert s['role'] == 'Chief Financial Officer' and s['owner'] == 'DOE JANE'
    assert any(t == '10b5-1 계획(채택 November 14, 2025)' for t in s['tags']), s['tags']
    assert rsu['sec_kind'] == 'RSU' and rsu['code_label'] == '부여(보상)' and rsu['underlying'] == 4000
    assert '4회 균등 분할(매년)' in rsu['tags'] and '재직 조건' in rsu['tags']
    assert opt['sec_kind'] == '스톡옵션' and opt['exercise_price'] == 42.10 and opt['expiration'] == '2036-03-01'
    assert E.classify_security('Warrants (right to buy)') == '워런트'
    assert '성과 조건: 상대 주주수익률(TSR)' in E.vesting_tags('PSUs vest based on relative total shareholder return over three years')
