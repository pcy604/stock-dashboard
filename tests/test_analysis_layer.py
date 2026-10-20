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
    assert all(x['state'] == 'na' for x in na)               # 못 재면 '확인 불가' — 통과로 치지 않는다


def test_risk_checks():
    r = {x['name']: x for x in AC.risk_checks(price=70, high52=100, band_rank=90, ttm_net_income=-1,
                                               opm_now=5, opm_4q_ago=10, debt_to_equity=50,
                                               eps_fy0_now=0.9, eps_fy0_30d=1.0, vol_annual=70,
                                               top_segment_share=88)}
    for k in ('추세 이탈', '밸류 부담', '적자', '마진 악화', '추정치 하향', '고변동성', '사업 집중'):
        assert r[k]['state'] == 'warn', k
    assert r['부채 부담']['state'] == 'ok'
    assert all(x['state'] == 'na' for x in AC.risk_checks())
