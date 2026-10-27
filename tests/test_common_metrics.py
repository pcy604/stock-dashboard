

def test_peer_rank_basic():
    import pandas as pd
    import common_metrics as cm
    b = pd.DataFrame({'종목': list('ABCD'), '시장': ['US'] * 3 + ['KR'], '_mc_usd': [3e9, 2e9, 1e9, 9e9],
                      'RS': [90, 50, None, 99], '1개월(%)': [1, 2, 3, 4], '52주고점대비(%)': [-1, -5, -9, 0],
                      '매출YoY(%)': [10, 20, 30, 40], '영업익YoY(%)': [None] * 4, 'PER(배)': [30, 10, 20, 5],
                      '업종': ['X'] * 4, '_업종full': ['X'] * 4}, index=['A', 'B', 'C', 'D'])
    r = cm.peer_rank(b, 'A')
    assert r['n'] == 3                      # KR 'D' 는 다른 시장 — 빠진다
    d = {x['지표']: x for x in r['rows']}
    assert d['시총']['순위'] == 1 and d['RS']['순위'] == 1 and d['RS']['비교수'] == 2   # 결측은 분모에서 뺀다
    assert d['PER(배)']['순위'] == 3        # PER 은 싼 순 — 30배는 3등
    assert d['영업익YoY(%)']['순위'] is None
    assert r['peers'][0] == 'A'
    assert cm.peer_rank(b, 'ZZZ') is None


def test_peer_rank_custom_group():
    import pandas as pd
    import common_metrics as cm
    b = pd.DataFrame({'종목': list('ABC'), '시장': ['KR'] * 3, '_mc_usd': [3e9, 2e9, 1e9], 'RS': [10, 50, 90],
                      '1개월(%)': [1, 2, 3], '52주고점대비(%)': [-1, -2, -3], '매출YoY(%)': [1, 2, 3],
                      '영업익YoY(%)': [1, 2, 3], 'PER(배)': [1, 2, 3], '업종': ['X', 'Y', 'Y'], '_업종full': ['X', 'Y', 'Y']},
                     index=['A', 'B', 'C'])
    r = cm.peer_rank(b, 'A', codes=['B', 'C', 'ZZ'], label='반도체 장비')
    assert r['sector'] == '반도체 장비' and r['n'] == 3          # 자기 자신은 항상 포함 · 없는 코드는 무시
    assert {x['지표']: x['순위'] for x in r['rows']}['RS'] == 3
