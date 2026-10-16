"""kr_fin_naver — 네이버 기업분석 응답 파싱 (2026-10-17 실응답 발췌 · 숫자는 공시와 대조한 값)"""
import pytest

import kr_fin_naver as N

Y = lambda *ps: [f'{p}<br />(IFRS연결)' for p in ps] + ['전년대비<br />(YoY)', '전년대비<br />(YoY)']
Q = lambda *ps: [f'{p}<br />(IFRS연결)' for p in ps] + ['전분기대비<br />(QoQ)', '전년동기대비<br />(YoY)']


def row(nm, lvl, *vals):
    d = {'ACC_NM': nm, 'LVL': lvl}
    d.update({f'DATA{i + 1}': v for i, v in enumerate(vals)})
    return d


# 삼성전자 연간(억원) — IR 확정치: FY25 매출 333.6조·영업익 43.6조·순익 45.2조·EPS 6,605·Capex 47.52조
SS_IS_Y = {'YYMM': Y('2021/12', '2022/12', '2023/12', '2024/12', '2025/12', '2026/12(E)'), 'DATA': [
    row('매출액(수익)', 1, 2796047.99, 3022313.6, 2589354.94, 3008709.03, 3336059.38, 7119241.2),
    row('매출총이익', 1, 1131934.57, 1121895.9, 785469.14, 1143086.35, 1313704.25, 5020348.8),
    row('영업이익', 1, 516338.56, 433766.3, 65669.76, 327259.61, 436010.51, 3716393.4),
    row('영업이익(발표기준)', 1, 516338.56, 433766.3, 65669.76, 327259.61, 436010.51, None),
    row('당기순이익', 1, 399074.5, 556540.77, 154871, 344513.51, 452068.05, 3070142.5),
    row('*(지배주주지분)주당순이익', 1, 5777, 8057, 2131, 4950, 6605, 45520.8)]}
SS_CF_Y = {'YYMM': Y('2021/12', '2022/12', '2023/12', '2024/12', '2025/12', '2026/12(E)'), 'DATA': [
    row('영업활동으로인한현금흐름', 1, 651054.48, 621813.46, 441374.27, 729826.21, 853151.48, None),
    row('....당기순이익', 3, 399074.5, 556540.77, 154871, 344513.51, 452068.05, None),
    row('투자활동으로인한현금흐름', 1, -330477.63, -316028.04, -169228.17, -853817.02, -685122.06, None),
    row('........유형자산의증가', 4, 471221.06, 494304.28, 576112.92, 514063.55, 475221.79, None),
    row('재무활동으로인한현금흐름', 1, -239910.33, -193900.49, -85930.59, -77972.43, -134780.4, None)]}
# 분기 — *CAPEX(누적) 와 유형자산의증가(3개월)가 함께 온다. 4Q25 Capex 3개월 = 11.55조(IR 일치)
SS_BS_Q = {'YYMM': Q('2025/06', '2025/09', '2025/12', '2026/03', '2026/06', '2026/09(E)'), 'DATA': [
    row('자산총계', 1, 5048752, 5236596, 5669421, 6333396, 7594805, None),
    row('*CAPEX', 1, 268312, 359729, 475222, 171270, 312348, None)]}
SS_CF_Q = {'YYMM': Q('2025/06', '2025/09', '2025/12', '2026/03', '2026/06', '2026/09(E)'), 'DATA': [
    row('영업활동으로인한현금흐름', 1, 173601, 225745, 287997, 402741, 1050811, None),
    row('........유형자산의증가', 4, 147033, 91417, 115493, 171270, 141078, None)]}
# 에이피알 분기 — 표준화 영업이익 ≠ 발표(DART). 2Q26 발표 1,906억
APR_IS_Q = {'YYMM': Q('2025/06', '2025/09', '2025/12', '2026/03', '2026/06', '2026/09(E)'), 'DATA': [
    row('매출액(수익)', 1, 3277, 3859, 5476, 5934, 7675, 7846),
    row('영업이익', 1, 846, 961, 1303, 1456, 1855, 1819),
    row('영업이익(발표기준)', 1, 813, 961, 1303, 1523, 1906, None),
    row('*주당순이익', 1, 1, 2, None, 3, 4, None)]}


def test_annual_income_matches_ir():
    p = N.parse(SS_IS_Y, 0, 'annual')
    assert set(p) == {'2021', '2022', '2023', '2024', '2025'}          # (E)·증감 열 제외
    assert p['2025']['revenue'] == pytest.approx(333.605938e12)
    assert p['2025']['op_income'] == pytest.approx(43.601051e12)
    assert p['2025']['net_income'] == pytest.approx(45.206805e12)
    assert p['2025']['eps'] == 6605                                      # 주당값은 억원 환산 안 함


def test_cf_capex_is_quarterly_not_cumulative():
    q = {}
    for rpt, j in ((1, SS_BS_Q), (2, SS_CF_Q)):
        for k, v in N.parse(j, rpt, 'quarter').items():
            q.setdefault(k, {}).update(v)
    assert q['2025.4Q']['capex'] == pytest.approx(11.5493e12)             # 누적 47.5조가 아니라 3개월
    assert q['2025.4Q']['op_cf'] == pytest.approx(28.7997e12)             # IR 4Q25 영업CF 28.80조
    assert q['2025.4Q']['assets'] == pytest.approx(566.9421e12)


def test_cf_net_income_subrow_does_not_leak():
    a = N.parse(SS_CF_Y, 2, 'annual')
    assert 'net_income' not in a['2025']
    assert a['2025']['capex'] == pytest.approx(47.522179e12)


def test_reported_operating_income_wins():
    q = N.parse(APR_IS_Q, 0, 'quarter')
    assert q['2026.2Q']['op_income'] == pytest.approx(1906e8)            # 표준화 1,855억 아님
    assert q['2026.1Q']['op_income'] == pytest.approx(1523e8)
    assert q['2025.4Q']['eps'] is None                                     # 비어 있으면 비운다


def test_statements_shape_and_sign(monkeypatch):
    monkeypatch.setattr(N, '_session', lambda code: (None, 'x', 'ref'))
    monkeypatch.setattr(N.time, 'sleep', lambda s: None)
    fx = {0: SS_IS_Y, 1: {'YYMM': SS_IS_Y['YYMM'], 'DATA': []}, 2: SS_CF_Y}
    monkeypatch.setattr(N, '_report', lambda s, e, r, c, frq, rpt: fx[rpt])
    rows = N.statements('5930', 'annual', 3)
    assert [r['period'] for r in rows] == ['2025', '2024', '2023']
    assert rows[0]['capex'] < 0 and rows[0]['_src'] == 'naver'
