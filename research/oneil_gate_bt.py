# -*- coding: utf-8 -*-
"""오닐 시장 방향(분배일·팔로스루)을 매수 게이트로 쓰면 v1.9 가 나아지나 (2026-11-28 차니: "빼고, 백테스팅은 ㄱㄱ")

  python research/oneil_gate_bt.py            # CI(research-oneil) — 지수 일봉은 yfinance 에서 받는다
결과: results/oneil_gate_bt.json

비교(한국 · v1.9 스펙 그대로 · 게이트만 바꿈)
  A 5주선(현행)   B 오닐만   C 오닐 엄격(압력 받는 상승도 막음)   D 5주선 AND 오닐   E 5주선 OR 오닐   F 게이트 없음
판정 기준: 현행(A) 대비 Calmar(CAGR÷|MDD|)가 높고, 워크포워드 4구간 중 3구간 이상에서도 Calmar 가 높을 때만 '채택 후보'.
  (CAGR 만 보면 낙폭을 키워 수익을 산 변형이 통과한다 — 로컬 가짜 거래량 리허설에서 확인)
오닐 상태는 그 주 마지막 거래일 종가 기준(5주선과 같은 시점) — 엔진이 다음 주에 실행(1주 지연)한다.
"""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'research'))
import quant_engine as Q                                   # noqa: E402
import market_pulse as MP                                  # noqa: E402
import live_v18_test as V8                                 # noqa: E402
import live_v19_test as V9                                 # noqa: E402

V19 = dict(market='KR', start='2017-06-05',
           filters=[dict(field='marcap', op='>=', value=1e11), dict(field='rs', op='>=', value=80),
                    dict(field='op_turn', op='==', value=1), dict(field='ma_gap:5', op='>', value=0)],
           rank=dict(field='rs', desc=True), rebalance=1, max_pos=10, max_w=0.30, trim='cap',
           entry=dict(init=0.5, pyramid=[[10, 0.25], [20, 0.25]]),
           exposure=dict(index='', ma=5, below=0.0, mode='entry'),
           exit=dict(stop=0, trail=[[0, 20]], cooldown=2,
                     signals=[dict(type='field', field='rs', op='<', value=70)]))
END = '2026-11-10'
WF = [('2017-06-05', '2019-07-01'), ('2019-07-01', '2021-07-01'),
      ('2021-07-01', '2023-07-01'), ('2023-07-01', END)]
IDX = {'KOSPI': '^KS11', 'KOSDAQ': '^KQ11'}
CACHE = os.path.join(ROOT, 'data/research/oneil_idx_daily.parquet')


def index_daily():
    """지수 일봉(종가·거래량). CI 에서 yfinance 로 받고 parquet 로 남긴다(로컬 재현용)."""
    if os.path.exists(CACHE) and not os.environ.get('ONEIL_REFRESH'):
        d = pd.read_parquet(CACHE)
    else:
        import yfinance as yf
        fr = []
        for name, tk in IDX.items():
            x = yf.download(tk, start='2015-01-01', interval='1d', progress=False, auto_adjust=False)
            if isinstance(x.columns, pd.MultiIndex):
                x.columns = x.columns.get_level_values(0)
            fr.append(pd.DataFrame({'market': name, 'date': x.index, 'close': x['Close'].values, 'volume': x['Volume'].values}))
        d = pd.concat(fr, ignore_index=True)
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        d.to_parquet(CACHE)
    d['date'] = pd.to_datetime(d['date'])
    return d


def daily_states(close: pd.Series, vol: pd.Series, start='2016-06-01') -> pd.Series:
    """날마다 그날까지의 데이터로만 오닐 상태(미래 참조 없음)."""
    out = {}
    for d in close.index[close.index >= pd.Timestamp(start)]:
        c = close[:d].iloc[-400:]
        p = MP.pulse(c, vol.reindex(c.index))
        out[d] = p.get('state', '')
    return pd.Series(out)


def weekly_allow(states: pd.Series, strict=False) -> pd.Series:
    ok = {'상승 추세', '상승 확인'} if strict else {'상승 추세', '상승 확인', '압력 받는 상승'}
    a = states.isin(ok).astype(float)
    return a.resample('W-MON', label='left', closed='left').last()      # 그 주 마지막 거래일 상태 = index_w 와 같은 정렬


def block_from_allow(P, allow_by_mk: dict) -> np.ndarray:
    D, S = P.dates, P.syms
    m = P.sym_market.pivot_table(index='date', columns='sym', values='market', aggfunc='last')
    m = m.reindex(index=D, columns=S).ffill().bfill()
    out = np.zeros((len(D), len(S)), bool)
    for mk, al in allow_by_mk.items():
        blocked = (al.reindex(D, method='ffill').fillna(1.0) < 0.5).values
        out |= blocked[:, None] & (m.values == mk)
    return out


def seg(eq, a, b):
    e = eq[(eq.index >= pd.Timestamp(a)) & (eq.index < pd.Timestamp(b))]
    if len(e) < 10:
        return None
    yrs = (e.index[-1] - e.index[0]).days / 365.25
    cagr = (e.iloc[-1] / e.iloc[0]) ** (1 / yrs) - 1
    mdd = (e / e.cummax() - 1).min()
    return dict(CAGR=round(float(cagr) * 100, 2), MDD=round(float(mdd) * 100, 2))


def main(path):
    P, _ = V9.load(path)
    bench = V8.index_w('KOSPI')
    blk5 = Q.market_block(P, P.sym_market, {'KOSPI': V8.index_w('KOSPI'), 'KOSDAQ': V8.index_w('KOSDAQ')}, 5)

    d = index_daily()
    cover = {}
    st, al, al_s = {}, {}, {}
    for mk in IDX:
        x = d[d.market == mk].set_index('date').sort_index()
        cover[mk] = dict(start=str(x.index.min().date()), end=str(x.index.max().date()),
                         vol_zero_pct=round(float((x.volume.fillna(0) == 0).mean() * 100), 1))
        st[mk] = daily_states(x['close'], x['volume'])
        al[mk], al_s[mk] = weekly_allow(st[mk]), weekly_allow(st[mk], strict=True)
        print(mk, cover[mk], st[mk].value_counts().head(6).to_dict(), flush=True)
    blkO, blkOs = block_from_allow(P, al), block_from_allow(P, al_s)

    variants = {
        'A_5주선(현행)': blk5,
        'B_오닐만': blkO,
        'C_오닐엄격': blkOs,
        'D_5주선_AND_오닐': blk5 | blkO,
        'E_5주선_OR_오닐': blk5 & blkO,
        'F_게이트없음': np.zeros_like(blk5),
    }
    res = {}
    for k, b in variants.items():
        r = Q.run(P, V19, bench_px=bench, entry_block=b)
        eq = r['equity']
        res[k] = dict(full=seg(eq, V19['start'], END), wf=[seg(eq, a, z) for a, z in WF],
                      blocked_weeks_pct=round(float(b.any(axis=1).mean() * 100), 1),
                      trades=int(len(r['trades'])) if r.get('trades') is not None else None)
        print(f"{k:18s} {res[k]['full']}  wf={[w and w['CAGR'] for w in res[k]['wf']]}", flush=True)

    base = res['A_5주선(현행)']
    verdict = {}
    for k, v in res.items():
        if k.startswith('A_') or not v['full']:
            continue
        cal = lambda x: x['CAGR'] / abs(x['MDD']) if x and x['MDD'] else None   # noqa: E731
        better = (cal(v['full']) or -9) > (cal(base['full']) or -9)
        wf_wins = sum(1 for w, b0 in zip(v['wf'], base['wf']) if w and b0 and (cal(w) or -9) > (cal(b0) or -9))
        verdict[k] = dict(better_full=bool(better), wf_wins=wf_wins, adopt_candidate=bool(better and wf_wins >= 3))
    bm = seg(bench, V19['start'], END)
    out = dict(made=str(pd.Timestamp.today().date()), rule='v1.9', market='KR', index_cover=cover,
               kospi=bm, results=res, verdict=verdict,
               note='오닐 규칙 = market_pulse.py (IBD 공개 설명). 게이트만 바꾸고 v1.9 나머지는 그대로. 1주 지연·비용 0.3%·상폐 포함 패널.')
    p = os.path.join(ROOT, 'results/oneil_gate_bt.json')
    json.dump(out, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print('저장', p, json.dumps(verdict, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, 'results/quant_panel_KR.parquet'))
