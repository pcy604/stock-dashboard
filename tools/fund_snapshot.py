"""공통 재무 스냅샷 — 종목 발굴 모든 표가 같은 '매출YoY · 영업익YoY · PER' 을 쓰게 한다 (2026-10-26).

전에는 표마다 재무 숫자를 다른 파일에서 가져왔다(CANSLIM 매출%, 이익가속 매출YoY, 가치 발굴 매출성장…).
같은 종목이 탭마다 다른 값으로 보였다. 이 스냅샷 하나를 만들어 화면이 시총(현재)과 합쳐 쓴다.

  KR : data/kr_fundamentals_q.parquet → ingest_dart_quarterly.quarterly() (Q4 = FY − 9M 차분)
  US : data/leaders_cache/fq_*.csv (weekly-accel 이 SEC EDGAR 로 갱신 — 러너에만 있다)

결과 results/fund_snapshot.json
  {date, n_kr, n_us, stocks: {sym: {market, q_end, rev_yoy, op_yoy, op_turn, ttm_rev, ttm_op, ttm_ni}}}
  · 금액은 원값(KR 원 · US 달러). PER·PSR 은 화면이 '지금 시총 ÷ TTM' 으로 계산한다.
  · 전년 같은 분기 값이 0 이하이면 YoY 는 비운다(부호가 바뀌면 % 가 뜻을 잃는다) — op_turn 으로 따로 표시.
  · 분기가 빠진 종목(간격 100일 초과)은 싣지 않는다. 없는 숫자를 만들지 않는다.

실행: python tools/fund_snapshot.py
"""
import glob
import json
import os
import sys
from datetime import date

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, 'results', 'fund_snapshot.json')
STALE_DAYS = 200          # 최신 분기가 이보다 오래되면 싣지 않는다(turnaround_run 과 같은 기준)


def _row(ends, rev, op, ni):
    """최신 먼저 정렬된 분기 시계열 → 스냅샷 한 줄. 조건이 안 맞으면 None."""
    if len(ends) < 5:
        return None
    if (pd.Timestamp(date.today()) - pd.Timestamp(ends[0])).days > STALE_DAYS:
        return None
    if any((pd.Timestamp(a) - pd.Timestamp(b)).days > 100 for a, b in zip(ends[:5], ends[1:5])):
        return None

    def _yoy(x):
        a, b = x[0], x[4]
        if a is None or b is None or pd.isna(a) or pd.isna(b) or b <= 0:
            return None
        return round((a / b - 1) * 100, 1)

    def _ttm(x):
        v = x[:4]
        return None if any(y is None or pd.isna(y) for y in v) else float(sum(v))

    o0, o4 = op[0], op[4]
    turn = None
    if o0 is not None and o4 is not None and not pd.isna(o0) and not pd.isna(o4):
        turn = '흑자전환' if (o0 > 0 >= o4) else '적자전환' if (o0 <= 0 < o4) else None
    return dict(q_end=str(pd.Timestamp(ends[0]).date()), rev_yoy=_yoy(rev), op_yoy=_yoy(op), op_turn=turn,
                ttm_rev=_ttm(rev), ttm_op=_ttm(op), ttm_ni=_ttm(ni))


def kr_rows():
    import ingest_dart_quarterly as Q
    d = Q.quarterly()
    if d is None or d.empty:
        return {}
    d = d.copy()
    d['_end'] = pd.to_datetime(d.year.astype(int).astype(str) + '-' + (d.q.astype(int) * 3).astype(str) + '-01') \
        + pd.offsets.MonthEnd(0)
    out = {}
    for sym, g in d.sort_values('_end', ascending=False).groupby('sym'):
        r = _row(list(g._end), list(g.revenue), list(g.op_income), list(g.net_income))
        if r:
            out[str(sym)] = dict(market='KR', **r)
    return out


def us_rows():
    out = {}
    for fp in glob.glob(os.path.join(ROOT, 'data', 'leaders_cache', 'fq_*.csv')):
        sym = os.path.basename(fp)[3:-4]
        try:
            g = pd.read_csv(fp)
            if g.empty or 'revenue' not in g:
                continue
            g['period_end'] = pd.to_datetime(g.period_end, errors='coerce')
            g = g.dropna(subset=['period_end']).drop_duplicates('period_end').sort_values('period_end', ascending=False)
            r = _row(list(g.period_end), list(g.revenue), list(g.get('opinc', [None] * len(g))),
                     list(g.get('netinc', [None] * len(g))))
            if r:
                out[sym] = dict(market='US', **r)
        except Exception:
            continue
    return out


def main():
    old = {}
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8')).get('stocks', {})
        except Exception:
            old = {}
    kr, us = kr_rows(), us_rows()
    # 러너가 아닌 곳(US 재무 캐시 없음)에서 돌리면 US 가 0 이 된다 — 그때는 직전 US 값을 지우지 않는다
    if not us:
        us = {k: v for k, v in old.items() if v.get('market') == 'US'}
    stocks = {**kr, **us}
    json.dump(dict(date=str(date.today()), n_kr=len(kr), n_us=len(us), stocks=stocks),
              open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    print(f'fund_snapshot: KR {len(kr):,} · US {len(us):,}')
    if not kr:
        print('::error::fund_snapshot KR 0종 — kr_fundamentals_q.parquet 를 확인할 것')


if __name__ == '__main__':
    main()
