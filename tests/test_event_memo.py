import pandas as pd
import numpy as np
import event_memo as E


def test_build_facts_only():
    idx = pd.bdate_range('2024-01-01', periods=300)
    close = pd.Series(np.r_[np.linspace(100, 200, 150), np.linspace(200, 120, 150)], idx)
    rows = pd.DataFrame([{'라벨': '상승 1', '시작일': idx[0].date(), '종료일': idx[149].date()},
                         {'라벨': '하락 1 (진행 중)', '시작일': idx[149].date(), '종료일': idx[-1].date()}])
    earn = pd.DataFrame({'Earnings Date': [idx[50], idx[110], idx[200]], 'Surprise(%)': [5.0, -2.0, -10.0]})
    ix = pd.Series(np.linspace(100, 110, 300), idx)
    fl = [{'date': str(idx[60].date()), 'items': '1.01,9.01'}, {'date': str(idx[220].date()), 'items': '5.02'}]
    out = E.build(close, rows, earn, ix, fl, 'S&P500')
    assert [o['no'] for o in out] == [1, 2]
    assert round(out[0]['ret']) == 100 and '실적 2회 중 예상 상회 1회' in out[0]['memo'] and '주요 계약 1' in out[0]['memo']
    assert '경영진 변동 1' in out[1]['memo'] and 'S&P500' in out[1]['memo']
    assert E.build(close, rows, None, None, None)[0]['memo'].startswith('지수 자료 없음')
