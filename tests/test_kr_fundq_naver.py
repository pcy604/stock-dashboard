"""kr_fundq_naver — 네이버 분기재무 병합 규칙 (2026-10-19)"""
import pandas as pd

import kr_fin_naver as N
import kr_fundq_naver as K
from tests.test_kr_fin_naver import Q, Y, row

IS_Q = {'YYMM': Q('2025/12', '2026/03', '2026/06', '2026/09(E)'), 'DATA': [
    row('매출액(수익)', 1, 938374, 1338734, 1714995, 1800000),
    row('영업이익(발표기준)', 1, 200737, 572328, 894924, None),
    row('당기순이익', 1, 196417, 472253, 716245, None)]}
BS_Q = {'YYMM': Q('2025/12', '2026/03', '2026/06', '2026/09(E)'), 'DATA': [
    row('자산총계', 1, 5669421, 6333396, 7594805, None),
    row('부채총계', 1, 1300000, 1400000, 1500000, None),
    row('자본총계', 1, 4369421, 4933396, 6094805, None)]}
IS_Y = {'YYMM': Y('2024/12', '2025/12', '2026/12(E)'), 'DATA': [
    row('매출액(수익)', 1, 3008709.03, 3336059.38, 7119241.2),
    row('영업이익(발표기준)', 1, 327259.61, 436010.51, None),
    row('당기순이익', 1, 344513.51, 452068.05, 3070142.5)]}
BS_Y = {'YYMM': Y('2024/12', '2025/12', '2026/12(E)'), 'DATA': [
    row('자본총계', 1, 4000000, 4369421, None)]}


def _patch(monkeypatch, is_y=IS_Y):
    monkeypatch.setattr(N, '_session', lambda code: (None, 'x', 'ref'))
    monkeypatch.setattr(K.time, 'sleep', lambda s: None)
    fx = {(1, 0): IS_Q, (1, 1): BS_Q, (0, 0): is_y, (0, 1): BS_Y}
    monkeypatch.setattr(N, '_report', lambda s, e, r, c, frq, rpt: fx[(frq, rpt)])


def test_fetch_one_quarters_and_annual_q4(monkeypatch):
    _patch(monkeypatch)
    r = {(x['year'], x['q']): x for x in K.fetch_one('005930')}
    assert r[(2026, 2)]['revenue'] == 1714995 * 1e8           # 분기 흐름 = 3개월
    assert r[(2026, 2)]['equity'] == 6094805 * 1e8            # 잔액
    assert r[(2025, 4)]['revenue'] == 3336059.38 * 1e8        # q=4 흐름 = 연간 합계(저장 규칙)
    assert r[(2025, 4)]['equity'] == 4369421 * 1e8
    assert (2026, 3) not in r                                  # 추정(E) 열은 버린다


def test_non_december_fiscal_year_skipped(monkeypatch):
    _patch(monkeypatch, is_y={'YYMM': Y('2025/06', '2026/06'), 'DATA': IS_Y['DATA']})
    assert K.fetch_one('950250') == []


def test_merge_keeps_dart_fills_gaps_appends_new():
    old = pd.DataFrame([
        dict(sym='005930', year=2026, q=1, revenue=1.338734e14, op_income=5.72328e13, net_income=None,
             fs_div='CFS', updated='2026-10-14'),
        dict(sym='000660', year=2026, q=1, revenue=1.0e14, op_income=1.0e13, net_income=1.0e13,
             fs_div='CFS', updated='2026-10-14')])
    new = [dict(sym='005930', year=2026, q=1, revenue=9.9e13, op_income=1.0, net_income=4.7e13, equity=4.9e14),
           dict(sym='005930', year=2026, q=2, revenue=1.7e14, op_income=8.9e13, net_income=7.1e13, equity=6.0e14)]
    df, st = K.merge(old, new, '2026-10-19')
    a = df[(df.sym == '005930') & (df.q == 1)].iloc[0]
    assert a.revenue == 1.338734e14          # DART 값 유지
    assert a.op_income == 5.72328e13
    assert a.net_income == 4.7e13            # 빈칸만 채움
    assert a.equity == 4.9e14
    b = df[(df.sym == '005930') & (df.q == 2)].iloc[0]
    assert b.fs_div == 'NAVER' and b.updated == '2026-10-19'
    assert st['new'] == 1 and st['mismatch_syms'] == 1   # 매출 26% 차이 → 불일치로 센다
    assert len(df) == 3
