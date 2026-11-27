# -*- coding: utf-8 -*-
"""지수 밸류에이션 역사 — 코스피·코스닥·미국 대형 500 의 주간 PER·PBR (2026-11-28 차니: "지수도 역사 PER·PBR · 추정치 플레이").

  python tools/index_valuation.py      # results/quant_panel_{KR,US}.parquet → results/index_valuation.json

계산 (지수 회사 방식과 같은 '합산' — 종목 PER 평균이 아님)
  PER = Σ시총 ÷ Σ(시총 ÷ PER)   = 구성 종목 시총 합 ÷ 이익 합
  PBR = Σ시총 ÷ Σ(시총 ÷ PBR)
  ⚠️ 패널의 PER 은 적자 종목이 비어 있다 → **이익 낸 종목 기준**(적자를 빼면 PER 이 실제보다 낮게 나온다).
     그래서 시총 커버율(cover_per)을 같이 남긴다. 같은 방법으로 매주 쟀으므로 '역사 대비 지금 위치'는 비교 가능하다.
  미국 = 그 주 시총 상위 500(S&P500 근사 — 공식 구성 종목 아님).
선행 PER(추정치): 한국은 results/consensus_q.json 의 컨센서스 순이익이 있으면 dashboard 가 따로 붙인다.
"""
import json
import os

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'results/index_valuation.json')


def agg(g: pd.DataFrame) -> dict:
    cap = g['marcap']
    tot = float(cap.sum())
    e = g[(g['per'] >= 1) & (g['per'] < 1000)]      # PER 1 미만은 일회성 이익·자료 오류(0.000003 같은 값)
    b = g[(g['pbr'] >= 0.05) & (g['pbr'] < 100)]
    per = float(e['marcap'].sum() / (e['marcap'] / e['per']).sum()) if len(e) else None
    pbr = float(b['marcap'].sum() / (b['marcap'] / b['pbr']).sum()) if len(b) else None
    return dict(per=round(per, 2) if per else None, pbr=round(pbr, 3) if pbr else None,
                cover_per=round(float(e['marcap'].sum()) / tot * 100, 1) if tot else None, n=int(len(g)))


def series(df: pd.DataFrame) -> list:
    out = []
    for d, g in df.groupby('date'):
        r = agg(g.dropna(subset=['marcap']))
        r['date'] = str(pd.Timestamp(d).date())
        out.append(r)
    return out


def stats(s: list) -> dict:
    v = np.array([x['per'] for x in s if x.get('per')])
    if len(v) < 20:
        return {}
    cur = s[-1]['per']
    return dict(now=cur, mean=round(float(v.mean()), 2), sd=round(float(v.std()), 2),
                pct=round(float((v <= cur).mean() * 100), 0), lo=round(float(v.min()), 2), hi=round(float(v.max()), 2))


def main():
    res = {}
    kr = pd.read_parquet(os.path.join(ROOT, 'results/quant_panel_KR.parquet'), columns=['date', 'market', 'marcap', 'per', 'pbr'])
    for mk, name in (('KOSPI', '코스피'), ('KOSDAQ', '코스닥')):
        s = series(kr[kr['market'] == mk])
        res[name] = dict(series=s, stats=stats(s))
    us = pd.read_parquet(os.path.join(ROOT, 'results/quant_panel_US.parquet'), columns=['date', 'marcap', 'per', 'pbr'])
    us = us.dropna(subset=['marcap'])
    us = us[us.groupby('date')['marcap'].rank(ascending=False) <= 500]
    s = series(us)
    res['미국 대형 500'] = dict(series=s, stats=stats(s))
    json.dump(dict(made=str(pd.Timestamp.today().date()), method='합산 PER·PBR(이익 낸 종목) · 주간 · quant_panel',
                   indices=res), open(OUT, 'w', encoding='utf-8'), ensure_ascii=False)
    for k, v in res.items():
        print(k, v['series'][-1], v['stats'])


if __name__ == '__main__':
    main()
