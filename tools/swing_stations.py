# -*- coding: utf-8 -*-
"""전 종목 스윙 '역 지도' (2026-10-27) — results/swing_stations.json

사용자 요청: "x% 빠지면/오르면 y% 까지 가더라"를 한 종목의 30~100개 스윙이 아니라 빅데이터로.
  · 원천: data/longcache/{sym}.parquet (커버 종목 전체 일봉 종가, 2008~) — weekly-profile 이 매주 갱신하는 캐시
  · 스윙: trade_plan.swings(일봉 종가 지그재그, 10% 되돌림) — 화면의 '이 종목' 계산과 같은 함수
  · 묶음: 시장(KR/US) × 연 변동성 3분위(낮음·중간·높음) + 전체 — 변동성이 다르면 스윙 크기 자체가 다르다
  · 저장: 칸별 '여기서 끝난 스윙 수'만(원자료 없이도 멈춤 확률·도달 확률을 다시 계산할 수 있다)
⚠️ 생존편향: 캐시는 지금 커버 종목만 있다(상장폐지 종목의 마지막 대폭락이 빠진다) → 큰 하락의 확률이 실제보다 낮게 나온다.
  python tools/swing_stations.py
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import trade_plan as TP

CACHE = ROOT / 'data' / 'longcache'
OUT = ROOT / 'results' / 'swing_stations.json'


def main():
    files = sorted(CACHE.glob('*.parquet'))
    if not files:
        print('::error title=swing_stations::data/longcache 비어 있음 — 캐시 복원 실패')
        return 1
    recs = []                                    # (market, vol, kind, size)
    nst = {'KR': 0, 'US': 0}
    for i, f in enumerate(files):
        sym = f.stem
        if sym.startswith('_'):
            continue
        mkt = 'KR' if (len(sym) == 6 and sym[:5].isdigit()) else 'US'
        try:
            c = pd.read_parquet(f)['Close'].dropna()
        except Exception:
            continue
        c = c[c > 0]
        if len(c) < 500:                         # 2년 미만은 스윙이 너무 적다
            continue
        vol = float(np.log(c).diff().std() * np.sqrt(252) * 100)
        if not np.isfinite(vol) or vol <= 0 or vol > 250:
            continue
        sw = TP.swings(c, theta=10)
        nst[mkt] += 1
        recs += [(mkt, vol, 'dec', s) for s in sw['declines']]
        recs += [(mkt, vol, 'ral', s) for s in sw['rallies']]
        if i % 500 == 0:
            print(f'  {i}/{len(files)} · 스윙 {len(recs):,}')
    if not recs:
        print('::error title=swing_stations::스윙 0개')
        return 1
    df = pd.DataFrame(recs, columns=['mkt', 'vol', 'kind', 'size'])
    out = {'asof': date.today().isoformat(), 'theta': 10, 'source': 'data/longcache 일봉 종가(커버 종목, 2008~)',
           'survivorship': '상장폐지 종목 없음 — 큰 하락 확률이 실제보다 낮게 나온다', 'markets': {}}
    for mkt, g in df.groupby('mkt'):
        # 종목 단위 변동성 3분위(스윙 수가 많은 고변동 종목이 분위를 끌지 않게 종목별 1개 값으로)
        vols = g.groupby(g['vol'].round(6))['vol'].first()
        cut = [float(np.percentile(vols, 33.3)), float(np.percentile(vols, 66.7))]
        m = {'cut': cut, 'n_stocks': nst.get(mkt, 0), 'buckets': {}}
        g = g.assign(b=[TP.vol_bucket(v, cut) for v in g['vol']])
        for b, gb in list(g.groupby('b')) + [('all', g)]:
            d = gb[gb.kind == 'dec']['size'].tolist()
            r = gb[gb.kind == 'ral']['size'].tolist()
            m['buckets'][b] = {'n_dec': len(d), 'n_ral': len(r),
                               'dec': TP.bin_counts(d, TP.DEC_EDGES), 'ral': TP.bin_counts(r, TP.RAL_EDGES),
                               'dec_median': float(np.median(d)) if d else None, 'ral_median': float(np.median(r)) if r else None}
        out['markets'][mkt] = m
        sm = TP.station_map(TP.DEC_EDGES, m['buckets']['all']['dec'])
        print(f"{mkt}: 종목 {m['n_stocks']:,} · 하락 스윙 {m['buckets']['all']['n_dec']:,} · 상승 {m['buckets']['all']['n_ral']:,} · "
              f"변동성 경계 {cut[0]:.0f}%/{cut[1]:.0f}% · 하락 역 {[TP.DEC_EDGES[i] for i in sm['stations']]}")
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'✅ {OUT.name}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
