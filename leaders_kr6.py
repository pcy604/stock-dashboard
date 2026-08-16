"""
leaders_kr6.py — 미국 규칙⑥을 한국시장에 **그대로** 이식
──────────────────────────────────────────────────────────
US 규칙⑥ (leaders_boost.signal + leaders_publish 의 base 필터) 원문:
    진입: rs_13w > 1.5  AND  adv_20d >= $5M  AND  marcap >= $2B  AND  close >= $5
          AND (op_turn == 1  OR  b_any == 1)  AND  opm > 0
    운용: 고점대비 -20% 트레일링 · 8종목 × 12.5% · 재진입 허용

    b_any = 아래 넷 중 하나 (leaders_boost.boost_flags 와 동일 정의)
      b_ophigh  영업이익 > 직전 8분기 최고 (min 4분기) AND > 0
      b_nihigh  순이익  > 직전 8분기 최고 AND > 0
      b_opjump  직전 영업익 > 0 AND 영업익 QoQ >= +50%
      b_opmjump OPM - 직전 OPM >= +3%p

이식하며 KR에 없던 것을 만든 부분(전부 근사이므로 한계로 표시):
  · 시총 시계열: universe.marcap(현재) / 현재종가 = 주식수 로 역산 → 과거종가 × 주식수.
    자사주 소각·증자에 따른 주식수 변화를 무시한다. 절대 정확치가 아니라 규모 구간용.
  · 벤치마크: US 는 SPY. KR 은 KOSPI(KS11) 를 쓴다.
  · 임계값: $1 = 1,400원 환산. $2B=2.8조 · $5M=70억.

⚠️ 앞선 'RS13 기각' 결과와 혼동 금지
  KR-P1에서 RS13을 기각한 것은 **52주 신고가 진입에 RS를 덧붙였을 때**다.
  규칙⑥은 신고가를 쓰지 않고 **RS 자체가 진입 조건**이다. 구조가 다르므로 다시 잰다.

실행:
  python leaders_kr6.py backtest      # US 임계값 그대로 + KR 환산 임계값 비교
  python leaders_kr6.py eco           # 에코프로가 잡히는지 사례 점검
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

import leaders_kr as K

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, 'data', 'longcache')
BENCH = os.path.join(CACHE, '_bench_ks11.parquet')

FX = 1400.0                    # $1 = 1,400원
TRAIL = 20.0                   # US 규칙⑥ 운용값
START = '2018-06-01'           # US 백테스트와 동일 시작
RS_MIN = 1.5

# (라벨, 시총하한, 거래대금하한)
PRESETS = {
    'US그대로': (2e9 * FX, 5e6 * FX),          # $2B=2.8조 · $5M=70억
    'KR환산':   (3000e8, 30e8),                # 3,000억 · 30억 — 코스닥 중형까지
    'KR완화':   (1000e8, 10e8),                # 1,000억 · 10억
}


def benchmark() -> pd.Series:
    """KOSPI 종가. 없으면 FDR로 받아 캐시."""
    if os.path.exists(BENCH):
        d = pd.read_parquet(BENCH)
        d.index = pd.to_datetime(d.index)
        return d.iloc[:, 0].dropna()
    import FinanceDataReader as fdr
    df = fdr.DataReader('KS11', '2016-01-01')[['Close']]
    df.index = pd.to_datetime(df.index)
    df.to_parquet(BENCH)
    return df['Close'].dropna()


def shares_map() -> dict:
    """현재 시총 ÷ 현재 종가 = 주식수(근사). 과거 시총 시계열을 만들기 위한 재료."""
    import sqlite3
    out = {}
    try:
        with sqlite3.connect(K.DB) as c:
            rows = c.execute('SELECT sym, marcap FROM universe WHERE marcap IS NOT NULL').fetchall()
    except Exception:
        return out
    for sym, mc in rows:
        px = K.load_close(sym)
        if px is None or len(px) == 0 or not mc:
            continue
        last = float(px.iloc[-1])
        if last > 0:
            out[sym] = float(mc) / last
    return out


def boost_flags(q: pd.DataFrame) -> pd.DataFrame:
    """leaders_boost.boost_flags 와 **같은 정의**로 KR 분기 데이터에 적용."""
    q = q.sort_values(['sym', 'year', 'q']).copy()
    q['opm'] = np.where((q['revenue'].notna()) & (q['revenue'] != 0),
                        q['op_income'] / q['revenue'] * 100, np.nan)
    g = q.groupby('sym')
    q['op_max8'] = g['op_income'].transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q['ni_max8'] = g['net_income'].transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q['op_prev'] = g['op_income'].shift(1)
    q['opm_prev'] = g['opm'].shift(1)
    q['b_ophigh'] = ((q['op_income'] > q['op_max8']) & (q['op_income'] > 0)).astype(int)
    q['b_nihigh'] = ((q['net_income'] > q['ni_max8']) & (q['net_income'] > 0)).astype(int)
    q['b_opjump'] = ((q['op_prev'] > 0) &
                     (q['op_income'] / q['op_prev'] - 1 >= 0.5)).astype(int)
    q['b_opmjump'] = ((q['opm'] - q['opm_prev']) >= 3).astype(int)
    q['b_any'] = q[['b_ophigh', 'b_nihigh', 'b_opjump', 'b_opmjump']].max(axis=1)
    return q


def rule6_map() -> dict:
    """sym → DataFrame[available_from, pass6]  (흑자전환 OR 이익폭증) AND OPM>0.

    공시 시차는 leaders_kr.earnings_map 과 동일 기준(분기말+50일, 사업보고서 90일).
    """
    import ingest_dart_quarterly as IQ
    q = IQ.quarterly()
    if q is None or len(q) == 0:
        return {}
    q = boost_flags(q)
    qend = {1: '-03-31', 2: '-06-30', 3: '-09-30', 4: '-12-31'}
    q['qend'] = pd.to_datetime(q['year'].astype(str) + q['q'].map(qend))
    q['available_from'] = q['qend'] + pd.to_timedelta(
        [90 if x == 4 else 50 for x in q['q']], unit='D')
    q['pass6'] = (((q['op_turn'] == 1) | (q['b_any'] == 1)) & (q['opm'] > 0))
    out = {}
    for sym, g in q.groupby('sym'):
        out[sym] = (g.sort_values('available_from')[['available_from', 'pass6']]
                     .reset_index(drop=True))
    return out


def trades_rule6(sym, c, bench, shares, r6, marcap_min, adv_min,
                 trail=TRAIL, rs_min=RS_MIN, start=START):
    """규칙⑥ 진입 → -trail% 트레일링 청산 → 재진입 허용."""
    if c is None or len(c) < 80:
        return []
    b = bench.reindex(c.index).ffill()
    rs = (c / c.shift(63)) / (b / b.shift(63))          # 13주 ≈ 63거래일
    adv = K.load_adv(sym)
    ok = (rs > rs_min)
    if adv is not None:
        ok &= (adv.reindex(c.index).ffill() >= adv_min)
    else:
        return []
    sh = shares.get(sym)
    if not sh:
        return []
    ok &= (c * sh >= marcap_min)
    g = r6.get(sym)
    if g is None or len(g) == 0:
        return []
    m = pd.merge_asof(pd.DataFrame({'d': c.index}),
                      pd.DataFrame({'available_from': g['available_from'].values,
                                    'f': g['pass6'].values}),
                      left_on='d', right_on='available_from', direction='backward')
    ok &= pd.Series(m['f'].fillna(False).to_numpy(dtype=bool), index=c.index)

    px = c[c.index >= start]
    s = ok.reindex(px.index).fillna(False)
    out, pos, entry, peak, ed = [], False, 0.0, 0.0, None
    for d, p in px.items():
        if not pos:
            if s.loc[d]:
                pos, entry, peak, ed = True, float(p), float(p), d
        else:
            peak = max(peak, float(p))
            if p <= peak * (1 - trail / 100):
                out.append(dict(sym=sym, entry=ed, exit=d, ret=float(p) / entry - 1,
                                days=(d - ed).days)); pos = False
    if pos:
        out.append(dict(sym=sym, entry=ed, exit=px.index[-1],
                        ret=float(px.iloc[-1]) / entry - 1,
                        days=(px.index[-1] - ed).days, open=True))
    return out


def backtest(presets=None):
    bench, shares, r6 = benchmark(), shares_map(), rule6_map()
    print(f'벤치 {len(bench)}일 · 주식수 {len(shares)}종 · 규칙⑥ 재무 {len(r6)}종', flush=True)
    syms = K.kr_symbols()
    closes = {s: K.load_close(s) for s in syms}
    closes = {s: c for s, c in closes.items() if c is not None}
    print(f'가격 {len(closes)}종', flush=True)
    res = {}
    for label, (mc, adv) in (presets or PRESETS).items():
        rows = []
        for s, c in closes.items():
            rows += trades_rule6(s, c, bench, shares, r6, mc, adv)
        res[label] = K.summarize(rows, label)
        r = res[label]
        print(f"  {label:<8} 시총≥{mc/1e12:.2f}조·거래대금≥{adv/1e8:.0f}억 → "
              f"n={r['n']:>5,} 승률 {r['winrate']:>4.1f}% 평균 {r['avg']:>6.2f}% "
              f"중앙 {r['med']:>7.2f}% 손익비 {r['payoff']} 보유 {r['hold_d']}일", flush=True)
    return res


BT = {   # 실측 결과 박제 (2018-06~2026-08, 왕복비용 0.3% 차감)
    'trail20': {'US그대로': dict(n=312, winrate=33.3, avg=3.46, med=-11.20, payoff=2.66, tail=79.4),
                'KR환산': dict(n=1667, winrate=31.0, avg=1.34, med=-11.21, payoff=2.51, tail=191.0),
                'KR완화': dict(n=2544, winrate=32.0, avg=1.49, med=-11.31, payoff=2.42, tail=173.9)},
    'trail30': {'US그대로': dict(n=235, winrate=33.2, avg=11.50, med=-16.68, payoff=3.53, tail=35.9),
                'KR환산': dict(n=1251, winrate=30.1, avg=5.22, med=-16.60, payoff=3.09, tail=87.6),
                'KR완화': dict(n=1890, winrate=32.1, avg=5.14, med=-15.50, payoff=2.83, tail=90.6)},
}


def live(marcap_min=None, adv_min=None, trail=30.0, weeks=10):
    """현재 후보 — 최근 N주 안에 규칙⑥ 진입 신호가 났고 아직 트레일링에 안 걸린 종목."""
    mc, adv_m = (marcap_min, adv_min) if marcap_min else PRESETS['US그대로']
    bench, shares, r6, nm = benchmark(), shares_map(), rule6_map(), K.names()
    cutoff = pd.Timestamp.today() - pd.Timedelta(weeks=weeks)
    out = []
    for s in K.kr_symbols():
        c = K.load_close(s)
        if c is None:
            continue
        tr = trades_rule6(s, c, bench, shares, r6, mc, adv_m, trail=trail,
                          start=str((pd.Timestamp.today() - pd.Timedelta(days=420)).date()))
        if not tr or not tr[-1].get('open') or tr[-1]['entry'] < cutoff:
            continue
        t = tr[-1]
        a = K.load_adv(s)
        sh = shares.get(s, 0)
        out.append(dict(sym=s, name=nm.get(s, s), entry_date=str(t['entry'].date()),
                        entry_px=round(float(c.loc[t['entry']]), 0),
                        close=round(float(c.iloc[-1]), 0), ret=round(t['ret'] * 100, 1),
                        stop=round(float(c.loc[t['entry']:].max()) * (1 - trail / 100), 0),
                        adv_eok=(round(float(a.dropna().iloc[-1]) / 1e8) if a is not None
                                 and len(a.dropna()) else None),
                        marcap_jo=round(float(c.iloc[-1]) * sh / 1e12, 2) if sh else None,
                        days=t['days']))
    return sorted(out, key=lambda x: -x['ret'])


def publish():
    import json
    from datetime import date
    sig = live()
    out = dict(
        generated=str(date.today()),
        rule=('미국 규칙⑥ 원문 이식 — RS13>1.5 AND (흑자전환 OR 이익폭증) AND OPM>0, '
              '시총 2.8조↑·거래대금 70억↑ · 고점대비 -30% 트레일링 · 재진입 허용'),
        params=dict(rs_min=RS_MIN, trail=30.0, marcap_min_jo=2.8, adv_min_eok=70, fx=FX),
        period=f'{START} ~ {date.today()}', backtest=BT,
        n=len(sig), candidates=sig[:60],
        caveats=[
            '시총 시계열은 현재 주식수 × 과거 종가로 역산 — 증자·소각 무시(규모 구간용 근사)',
            '벤치마크는 KOSPI(KS11). 미국판은 SPY',
            '생존편향 미보정 — 현재 상장 종목만',
            '진입가는 당일 종가 가정(실제는 익일 시가)',
            'n=235는 표본이 작다. 상위 1% 거래가 수익의 35.9%를 만든다',
        ])
    p = os.path.join(BASE, 'results', 'leaders_kr6.json')
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'→ {p} (후보 {len(sig)}종)')
    return out


def eco_check():
    """에코프로·에코프로비엠이 각 임계값에서 잡히는지."""
    bench, shares, r6 = benchmark(), shares_map(), rule6_map()
    for sym, nm in (('086520', '에코프로'), ('247540', '에코프로비엠')):
        c = K.load_close(sym)
        sh = shares.get(sym)
        print(f'\n=== {nm} ({sym}) · 추정 주식수 {sh:,.0f} ===' if sh else f'\n=== {nm} 주식수 없음 ===')
        if sh and c is not None:
            for when in ('2023-02-06', '2023-01-02'):
                if pd.Timestamp(when) in c.index:
                    print(f"  {when} 종가 {c.loc[when]:,.0f}원 → 추정시총 "
                          f"{c.loc[when]*sh/1e12:.2f}조")
        for label, (mc, adv) in PRESETS.items():
            t = [x for x in trades_rule6(sym, c, bench, shares, r6, mc, adv)
                 if str(x['entry'].date()).startswith('2023')]
            print(f"  {label:<8} 2023년 진입 {len(t)}건 " +
                  (' · '.join(f"{x['entry'].date()}→{x['ret']*100:+.0f}%" for x in t) or '없음'))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'backtest'
    if cmd == 'eco':
        eco_check()
    elif cmd == 'publish':
        publish()
    else:
        backtest()
