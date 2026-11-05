"""8-K 실적 보도자료 손익 파서 — 네트워크 없이 정답 대조 (2026-11-06)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import edgar_client as E  # noqa: E402

# 미국 소형주 보도자료의 흔한 모양: '$' 가 따로 떨어진 칸, 음수는 괄호, 당기 3개월이 맨 앞, 단위 천 달러
AXT_LIKE = """
<html><body><p>AXT, Inc. CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (Unaudited, in thousands, except per share data)</p>
<table>
<tr><td></td><td colspan=2>Three Months Ended September 30,</td><td colspan=2>Nine Months Ended September 30,</td></tr>
<tr><td></td><td>2026</td><td>2025</td><td>2026</td><td>2025</td></tr>
<tr><td>Revenue</td><td>$</td><td>52,310</td><td>$</td><td>28,010</td><td>$</td><td>140,500</td><td>$</td><td>80,100</td></tr>
<tr><td>Cost of revenue</td><td>27,900</td><td>23,400</td><td>78,000</td><td>70,000</td></tr>
<tr><td>Gross profit</td><td>24,410</td><td>4,610</td><td>62,500</td><td>10,100</td></tr>
<tr><td>Operating expenses:</td><td></td><td></td><td></td><td></td></tr>
<tr><td>Selling, general and administrative</td><td>8,100</td><td>7,700</td><td>24,000</td><td>23,000</td></tr>
<tr><td>Research and development</td><td>3,300</td><td>3,100</td><td>9,800</td><td>9,000</td></tr>
<tr><td>Income (loss) from operations</td><td>13,010</td><td>(6,190)</td><td>28,700</td><td>(21,900)</td></tr>
<tr><td>Net income (loss)</td><td>12,100</td><td>(7,000)</td><td>26,000</td><td>(24,000)</td></tr>
<tr><td>Net income attributable to noncontrolling interests</td><td>(200)</td><td>(100)</td><td>(500)</td><td>(300)</td></tr>
<tr><td>Net income (loss) attributable to AXT, Inc.</td><td>$</td><td>11,900</td><td>$</td><td>(7,100)</td><td>$</td><td>25,500</td><td>$</td><td>(24,300)</td></tr>
<tr><td>Net income (loss) per share - Diluted</td><td>$</td><td>0.26</td><td>$</td><td>(0.16)</td><td>$</td><td>0.56</td><td>$</td><td>(0.55)</td></tr>
<tr><td>Gross margin %</td><td>46.7%</td><td>16.5%</td><td>44.5%</td><td>12.6%</td></tr>
</table></body></html>"""


def test_axt_like_release():
    r = E.parse_release(AXT_LIKE, prev_revenue=47.6e6)
    assert r['revenue'] == 52_310_000                      # 당기 3개월 · 천 달러 → 달러
    assert r['gross'] == 24_410_000
    assert r['sga'] == 8_100_000
    assert r['op_income'] == 13_010_000
    assert r['net_income'] == 12_100_000                   # 처음 나온 순이익 행(괄호 음수·'$' 칸 무시 확인은 아래)
    assert r['eps'] == 0.26


def test_negative_and_cogs_fallback():
    html = AXT_LIKE.replace('<tr><td>Gross profit</td><td>24,410</td><td>4,610</td><td>62,500</td><td>10,100</td></tr>', '') \
                   .replace('<td>Revenue</td><td>$</td><td>52,310</td>', '<td>Revenue</td><td>$</td><td>28,010</td>') \
                   .replace('<td>Income (loss) from operations</td><td>13,010</td>', '<td>Income (loss) from operations</td><td>(6,190)</td>')
    r = E.parse_release(html, prev_revenue=30e6)
    assert r['gross'] == 28_010_000 - 27_900_000           # 매출총이익 행이 없으면 매출 − 원가
    assert r['op_income'] == -6_190_000                     # 괄호 = 음수


def test_scale_guard_rejects_absurd_size():
    # 직전 분기 매출이 4,760만 달러인데 천 달러·백만 달러·그대로 어느 단위로도 0.2~5배가 안 되면 버린다
    assert E.parse_release(AXT_LIKE, prev_revenue=9e12) is None


def test_millions_unit():
    html = AXT_LIKE.replace('in thousands', 'in millions').replace('52,310', '52.3').replace('27,900', '27.9') \
                   .replace('24,410', '24.4').replace('8,100', '8.1').replace('13,010', '13.0').replace('12,100', '12.1')
    r = E.parse_release(html, prev_revenue=47.6e6)
    assert abs(r['revenue'] - 52.3e6) < 1


def test_no_income_table():
    assert E.parse_release('<table><tr><td>Cash</td><td>1,000</td></tr></table>', 1e6) is None
    assert E.parse_release('<p>no tables</p>', 1e6) is None


class _R:
    def __init__(self, j=None, t=''):
        self._j, self.text = j, t

    def json(self):
        return self._j


def test_finds_item_202_8k_after_quarter_end(monkeypatch):
    sub = {'filings': {'recent': {
        'form': ['10-Q', '8-K', '8-K', '8-K'], 'items': ['', '5.02', '2.02,9.01', '2.02,9.01'],
        'filingDate': ['2026-11-04', '2026-11-01', '2026-10-30', '2026-07-30'],
        'accessionNumber': ['a-1', 'b-2', '0001437749-26-033941', 'c-3'],
        'primaryDocument': ['q.htm', 'x.htm', 'axti20261030_8k.htm', 'y.htm']}}}
    idx = {'directory': {'item': [{'name': 'axti20261030_8k.htm'}, {'name': 'ex_1013304.htm'},
                                  {'name': '0001437749-26-033941-index.htm'}]}}

    def fake_get(url, tries=None):
        if 'submissions' in url:
            return _R(sub)
        if url.endswith('index.json'):
            return _R(idx)
        assert url.endswith('ex_1013304.htm'), url                 # 본문 8-K 가 아니라 첨부 보도자료만
        return _R(t=AXT_LIKE)
    monkeypatch.setattr(E, '_get', fake_get)
    monkeypatch.setattr(E, 'cik_map', lambda *a, **k: {'AXTI': '0001051627'})
    r, why = E.earnings_release_quarter('AXTI', '2026-06', 47.6e6)
    assert why == 'ok' and r['period'] == '2026-09' and r['filed'] == '2026-10-30' and r['revenue'] == 52_310_000
    # 분기말 뒤 실적 8-K 가 아직 없으면(가장 최근 2.02 가 7월) 이유를 돌려준다
    r2, why2 = E.earnings_release_quarter('AXTI', '2026-09', 52e6)
    assert r2 is None and '없음' in why2
