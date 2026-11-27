# -*- coding: utf-8 -*-
"""한국거래소 추가 자료 (2026-11-28 차니: "거래소 데이터 다 가져와서 활용해보자").

  python tools/krx_extra.py      # CI(index-valuation-long) — KRX_ID·KRX_PW 필요(2025~ 로그인)
결과: results/krx_extra.json

  ① sectors   업종 지수 PER·PBR·배당수익률 — 지금 값과 10년 월말 분포 안 위치(백분위)
  ② dividend  코스피·코스닥 지수 배당수익률 월말 2000~
  ③ foreign   외국인 보유 비중(시총 가중) 월말 2015~ = Σ(외국인 보유주식 × 종가) ÷ Σ(상장주식 × 종가)
  ④ short     공매도 거래대금(투자자별) 최근 1년 일별 + 공매도 잔고 상위 50(오늘)
각 부분은 따로 실패한다 — 실패하면 그 칸만 비우고 이유를 남긴다(지어내지 않는다).
"""
import json
import os
import time
from datetime import date, timedelta

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results/krx_extra.json')
SLEEP = 0.6


def _ymd(d):
    return d.strftime('%Y%m%d')


def _col(df, *names):
    for n in names:
        for c in df.columns:
            if n in str(c):
                return c
    return None


def _chunks(start: date, end: date, years=3):
    a = start
    while a <= end:
        b = min(date(a.year + years - 1, 12, 31), end)
        yield _ymd(a), _ymd(b)
        a = date(b.year + 1, 1, 1)


def index_monthly(stock, tk, start=date(2000, 1, 1)):
    fr = []
    for a, b in _chunks(start, date.today()):
        try:
            d = stock.get_index_fundamental(a, b, tk)
            if d is not None and len(d):
                fr.append(d)
        except Exception as e:
            print(f'  지수 {tk} {a}: {str(e)[:60]}')
        time.sleep(SLEEP)
    if not fr:
        return pd.DataFrame()
    d = pd.concat(fr)
    d = d[~d.index.duplicated()].sort_index()
    return d.resample('ME').last()


def sectors(stock, today):
    out = []
    for mk in ('KOSPI', 'KOSDAQ'):
        try:
            cur = stock.get_index_fundamental(today, market=mk)
        except Exception as e:
            print(f'  업종 {mk} 오늘: {str(e)[:80]}')
            continue
        print(f'  업종 {mk} 열', list(cur.columns)[:8], len(cur))
        cp, cb, cd = _col(cur, 'PER'), _col(cur, 'PBR'), _col(cur, '배당')
        for tk in list(cur.index):
            try:
                name = stock.get_index_ticker_name(tk)
            except Exception:
                name = str(tk)
            h = index_monthly(stock, tk, start=date(date.today().year - 10, 1, 1))
            row = dict(market=mk, ticker=str(tk), name=name)
            for key, c in (('per', cp), ('pbr', cb), ('div', cd)):
                v = pd.to_numeric(cur.loc[tk, c], errors='coerce') if c else None
                row[key] = round(float(v), 2) if v is not None and pd.notna(v) and v > 0 else None
                hc = _col(h, {'per': 'PER', 'pbr': 'PBR', 'div': '배당'}[key]) if len(h) else None
                if hc and row[key] is not None:
                    s = pd.to_numeric(h[hc], errors='coerce')
                    s = s[s > 0].dropna()
                    if len(s) >= 24:
                        row[f'{key}_pct10y'] = round(float((s <= row[key]).mean() * 100), 0)
                        row[f'{key}_med10y'] = round(float(s.median()), 2)
            out.append(row)
    return out


def dividend(stock):
    res = {}
    for name, tk in (('코스피', '1001'), ('코스닥', '2001')):
        m = index_monthly(stock, tk)
        c = _col(m, '배당') if len(m) else None
        if c:
            s = pd.to_numeric(m[c], errors='coerce')
            s = s[s > 0].dropna()
            res[name] = [[str(i.date()), round(float(v), 2)] for i, v in s.items()]
    return res


def foreign(stock, start=date(2015, 1, 1)):
    res = {}
    months = pd.date_range(start, date.today(), freq='BME')
    for mk in ('KOSPI', 'KOSDAQ'):
        pts = []
        for m in list(months) + [pd.Timestamp(date.today())]:
            d = _ymd(m)
            try:
                d = stock.get_nearest_business_day_in_a_week(d)
                ex = stock.get_exhaustion_rates_of_foreign_investment(d, mk)
                cap = stock.get_market_cap(d, market=mk)
                hold, lst = _col(ex, '보유수량'), _col(cap, '상장주식수')
                px = _col(cap, '종가')
                j = cap[[px, lst]].join(ex[[hold]], how='inner')
                v = float((j[hold] * j[px]).sum() / (j[lst] * j[px]).sum() * 100)
                pts.append([str(pd.Timestamp(d).date()), round(v, 2)])
            except Exception as e:
                print(f'  외국인 {mk} {d}: {str(e)[:60]}')
            time.sleep(SLEEP)
        res[mk] = sorted({p[0]: p for p in pts}.values())
    return res


def short(stock, today):
    res = {}
    a = _ymd(date.today() - timedelta(days=370))
    for mk in ('KOSPI', 'KOSDAQ'):
        try:
            v = stock.get_shorting_investor_value_by_date(a, today, mk)
            print(f'  공매도 {mk} 열', list(v.columns))
            tot = _col(v, '합계')
            res[f'{mk}_value'] = [[str(i.date()), int(x)] for i, x in pd.to_numeric(v[tot], errors='coerce').dropna().items()] if tot else []
            res[f'{mk}_by_investor'] = {str(c): int(pd.to_numeric(v[c], errors='coerce').iloc[-20:].sum()) for c in v.columns}
        except Exception as e:
            res[f'{mk}_err'] = str(e)[:150]
        time.sleep(SLEEP)
        try:
            t = stock.get_shorting_balance_top50(today, mk)
            print(f'  공매도 잔고 {mk} 열', list(t.columns))
            nm, bal, ratio = _col(t, '종목명'), _col(t, '공매도잔고'), _col(t, '비중', '비율')
            res[f'{mk}_top'] = [dict(sym=str(i), name=str(r[nm]) if nm else str(i),
                                     balance=float(r[bal]) if bal else None, ratio=float(r[ratio]) if ratio else None)
                                for i, r in t.head(20).iterrows()]
        except Exception as e:
            res[f'{mk}_top_err'] = str(e)[:150]
        time.sleep(SLEEP)
    return res


def main():
    from pykrx import stock
    today = stock.get_nearest_business_day_in_a_week(_ymd(date.today()))
    out = dict(made=str(date.today()), asof=str(pd.Timestamp(today).date()))
    for key, fn in (('dividend', lambda: dividend(stock)), ('short', lambda: short(stock, today)),
                    ('sectors', lambda: sectors(stock, today)), ('foreign', lambda: foreign(stock))):
        try:
            out[key] = fn()
            print(key, '완료', (len(out[key]) if hasattr(out[key], '__len__') else ''))
        except Exception as e:
            out[f'{key}_err'] = str(e)[:200]
            print(key, '실패', e)
        json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)   # 부분 저장(뒤에서 죽어도 앞 결과는 남게)
    print('저장', OUT)


if __name__ == '__main__':
    main()
