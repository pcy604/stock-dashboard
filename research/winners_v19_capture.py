# -*- coding: utf-8 -*-
"""대박주(winners_reverse 한국 상위) 중 실전 v1.9 가 실제로 몇 개를 샀고, 손절 뒤 다시 탔나 (2026-11-10, 역분석 '보유' 결론의 숙제).
결과: results/winners_v19_capture.json — ui_winners._lessons 가 읽는다."""
import os, sys, json
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); os.chdir(ROOT)
import pandas as pd
import ui_quant as U


def main():
    s = U.Q.merged(U._fill(U.PRESETS['🟢 지금 실전 규칙 (v1.9 · 교집합 10종목)'], 'KR')); s['start'] = '2018-06-01'
    T = U._run('KR', json.dumps(s, sort_keys=True))['trades']
    R = json.load(open('results/winners_reverse.json', encoding='utf-8'))['markets']['KR']
    ws = {str(w['sym']) for w in R['winners']}
    T['코드'] = T['코드'].astype(str); T['날짜'] = pd.to_datetime(T['날짜'])
    t = T[(T['날짜'] >= pd.Timestamp(R['window'][0])) & T['코드'].isin(ws)]
    rows = []
    for c, x in t.groupby('코드'):
        sells = x[x['구분'] == '매도']
        rows.append(dict(코드=c, 종목=x['종목'].iloc[0], 매수=int((x['구분'] == '매수').sum()),
                         손절=int(sells['사유'].str.contains('손절|래칫').sum()),
                         누적수익률=round(float(((sells['수익률'].fillna(0) / 100 + 1).prod() - 1) * 100), 1) if len(sells) else None))
    D = pd.DataFrame(rows)
    import time
    out = dict(run=time.strftime('%Y-%m-%d %H:%M'), window=R['window'], winners=len(ws), bought=len(D), stopped=int((D['손절'] > 0).sum()),
               rebought=int(((D['손절'] > 0) & (D['매수'] > 1)).sum()),
               net_loss=int((D['누적수익률'].fillna(0) < 0).sum()), rows=D.sort_values('매수', ascending=False).to_dict('records'))
    json.dump(out, open('results/winners_v19_capture.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print({k: v for k, v in out.items() if k != 'rows'})


if __name__ == '__main__':
    main()
