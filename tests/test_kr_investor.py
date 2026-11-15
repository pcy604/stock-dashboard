import kr_investor as K

HTML = """<table><tr><th>날짜</th><th>종가</th><th>전일비</th><th>등락률</th><th>거래량</th><th>기관 순매매량</th><th>외국인 순매매량</th><th>외국인 보유주수</th><th>외국인 보유율</th></tr>
<tr><td>2026.11.13</td><td>100,000</td><td>1</td><td>+1%</td><td>10</td><td>+2,000</td><td>-1,000</td><td>5</td><td>50.10%</td></tr>
<tr><td>2026.11.12</td><td>99,000</td><td>1</td><td>+1%</td><td>10</td><td>-500</td><td>3,000</td><td>5</td><td>50.00%</td></tr></table>"""


def test_parse_summary():
    d = K.parse(HTML)
    assert list(d['날짜'].dt.day) == [12, 13] and d['외국인'].tolist() == [3000, -1000]
    s = K.summary(d, 20)
    assert round(s['frgn'], 4) == round((3000 * 99000 - 1000 * 100000) / 1e8, 4)
    assert round(s['hold_chg'], 2) == 0.10
