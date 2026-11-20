# -*- coding: utf-8 -*-
"""🤖 퀀트 자동 탐색 — 조건을 한 축씩 바꿔 가며 전 조합을 돌리고, 과적합을 걸러 '우수 전략'만 남긴다 (2026-11-20, 차니 요구 6)

research/opt_search_2026_11_08.py 의 사전 등록 절차를 화면용 함수로 일반화했다. 고르는 법·합격 기준은 **결과를 보기 전에 고정**:
  · 표본 분할: 학습 [start, split) / 검증 [split, end] — 따로 돌린다(검증은 빈 계좌에서 시작 = 학습 보유가 넘어가지 않음).
  · 고르기(학습만 봄): 학습 Calmar(수익÷낙폭) 최대, 단 학습 CAGR > 비교 지수. 없으면 Calmar 최대.
  · 합격 ①~④ (검증 구간):
     ① 검증 CAGR > 비교 지수 그리고 > 출발 전략(base)
     ② 검증 MDD 가 출발 전략보다 5%p 넘게 나쁘지 않음
     ③ 학습 상위 10% 조합의 검증 CAGR 중앙 > 전체 조합 검증 CAGR 중앙 (순위가 이어지나 — 아니면 고르기 자체가 운)
     ④ 이웃 안정성: 축 하나만 한 칸 바꾼 이웃들의 검증 CAGR 중앙 ≥ 출발 전략 검증 CAGR (한 점에서만 좋은 건 우연)
  · 다중 시도 보정(참고, research/overfit.py): DSR(시도 수만큼 기대 최대 샤프를 뺀 확률) · PBO(CSCV — 학습 1등이 검증 중앙 이하일 확률)
  넷 다 통과 → '실전 후보'. 아니면 '관찰'. 숫자가 좋아도 기준을 낮추지 않는다(CLAUDE.md 원칙).
화면 비의존 — run(spec)->dict(stats, equity) 만 받는다(테스트·연구 스크립트에서 그대로 쓴다).
"""
from __future__ import annotations

import copy
import importlib.util
import itertools
import os

import numpy as np
import pandas as pd


def _rs_min(s, v):
    f = [x for x in s.get('filters', []) if not (x.get('field') == 'rs' and x.get('op') in ('>=', '>'))]
    if v:
        f.append(dict(field='rs', op='>=', value=float(v)))
    s['filters'] = f


def _rs_exit(s, v):
    ex = s.setdefault('exit', {})
    sig = [x for x in ex.get('signals', []) if not (x.get('type') == 'field' and x.get('field') == 'rs')]
    if v:
        sig.append(dict(type='field', field='rs', op='<', value=float(v)))
    ex['signals'] = sig


def _trail(s, v):
    s.setdefault('exit', {})['trail'] = [[0, float(v)]] if v else []


def _max_pos(s, v):
    s['max_pos'] = int(v)
    s['max_w'] = max(float(s.get('max_w') or 0), round(1.0 / int(v), 4))     # 종목 수를 줄였는데 상한이 그대로면 현금이 남는다


def _init(s, v):
    v = float(v)
    s['entry'] = dict(init=v, pyramid=[] if v >= 1 else [[10, (1 - v) / 2], [20, (1 - v) / 2]])


def _index_ma(s, v, idx=''):
    ex = s.setdefault('exposure', {})
    if v:
        ex['index'] = ex.get('index') or idx
        ex['ma'] = int(v)
    else:
        ex['index'] = ''


# 축 key → (화면 이름, 기본 후보, 적용 함수). 0 = '안 씀'. 새 축은 여기 한 줄.
AXES = {
    'max_pos':   ('보유 종목 수', [5, 10, 20], _max_pos),
    'trail':     ('손절 — 고점 대비 %(0=없음)', [15, 20, 25, 30], _trail),
    'rs_min':    ('RS 하한(0=없음)', [70, 80, 90], _rs_min),
    'rs_exit':   ('RS 탈락 매도 기준(0=없음)', [0, 50, 70], _rs_exit),
    'rebalance': ('리밸런싱 주기(주)', [1, 2, 4], lambda s, v: s.update(rebalance=int(v))),
    'min_hold':  ('최소 보유(주)', [0, 4, 8], lambda s, v: s.setdefault('exit', {}).update(min_hold=int(v))),
    'init':      ('첫 매수 비중(1=한 번에)', [1.0, 0.5], _init),
    'index_ma':  ('지수 n주선 아래 신규 중지(0=없음)', [0, 5, 10], _index_ma),
}
MAX_COMBOS = 120          # 조합 하나 ≈ 2초(학습+검증 2회) → 120개 ≈ 4분. 클라우드 화면이 버티는 선


def combos(axes: dict) -> list[dict]:
    keys = list(axes)
    return [dict(zip(keys, vals)) for vals in itertools.product(*[axes[k] for k in keys])]


def apply(base: dict, combo: dict, idx: str = '') -> dict:
    s = copy.deepcopy(base)
    for k, v in combo.items():
        fn = AXES[k][2]
        fn(s, v, idx) if k == 'index_ma' else fn(s, v)
    return s


def _wk(eq: pd.Series) -> pd.Series:
    return eq.pct_change().dropna() if eq is not None and len(eq) > 1 else pd.Series(dtype=float)


def _row(st: dict) -> dict:
    g = lambda k: float(st[k]) if st and st.get(k) is not None and np.isfinite(st.get(k)) else np.nan   # noqa: E731
    return dict(CAGR=g('CAGR'), MDD=g('MDD'), Sharpe=g('Sharpe'), Calmar=g('Calmar'), BM=g('BM_CAGR'), n=g('매도건수'))


def _overfit():
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'research', 'overfit.py')
    sp = importlib.util.spec_from_file_location('_overfit', p)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def search(base: dict, axes: dict, run, split: str, idx: str = '', progress=None) -> dict:
    """base 에서 axes 의 전 조합을 학습·검증으로 따로 돌린다. run(spec) -> {'stats':…, 'equity':Series}."""
    cs = combos(axes)
    if len(cs) > MAX_COMBOS:
        raise ValueError(f'조합 {len(cs)}개 — 상한 {MAX_COMBOS}개. 축이나 후보 값을 줄여 주십시오.')
    start, end = base.get('start'), base.get('end')
    pre = (pd.Timestamp(split) - pd.Timedelta(days=1)).strftime('%Y-%m-%d')

    def both(spec):
        tr = run(dict(copy.deepcopy(spec), start=start, end=pre))
        te = run(dict(copy.deepcopy(spec), start=split, end=end))
        return tr, te

    b_tr, b_te = both(base)
    rows, rets = [], {}
    for i, c in enumerate(cs):
        tr, te = both(apply(base, c, idx))
        a, b = _row(tr.get('stats')), _row(te.get('stats'))
        rows.append(dict(**c, **{f'학습_{k}': v for k, v in a.items()}, **{f'검증_{k}': v for k, v in b.items()}))
        rets[i] = pd.concat([_wk(tr.get('equity')), _wk(te.get('equity'))])
        if progress:
            progress((i + 1) / len(cs), f'{i + 1}/{len(cs)}')
    df = pd.DataFrame(rows)
    return dict(df=df, rets=rets, axes=axes, split=split,
                base_tr=_row(b_tr.get('stats')), base_te=_row(b_te.get('stats')),
                verdict=judge(df, axes, _row(b_te.get('stats')), rets))


def _neighbors(df: pd.DataFrame, axes: dict, i: int) -> list[int]:
    me = df.loc[i]
    out = []
    for k, vals in axes.items():
        pos = list(vals).index(me[k])
        for d in (-1, 1):
            if 0 <= pos + d < len(vals):
                m = np.ones(len(df), bool)
                for k2 in axes:
                    m &= (df[k2] == (vals[pos + d] if k2 == k else me[k2])).to_numpy()
                out += list(np.where(m)[0])
    return out


def judge(df: pd.DataFrame, axes: dict, base_te: dict, rets: dict | None = None) -> dict:
    ok = df[df['학습_CAGR'] > df['학습_BM']]
    pool = ok if len(ok) else df
    i = int(pool['학습_Calmar'].fillna(-1e9).idxmax())
    sel = df.loc[i]
    bm_te = sel['검증_BM']
    k = max(1, int(round(len(df) * 0.1)))
    top = df.nlargest(k, '학습_Calmar')
    nb = _neighbors(df, axes, i)
    nb_med = float(df.loc[nb, '검증_CAGR'].median()) if nb else np.nan
    crit = [
        ('① 검증 수익 > 지수·출발 전략', bool(sel['검증_CAGR'] > bm_te and sel['검증_CAGR'] > base_te['CAGR']),
         f"{sel['검증_CAGR']:.1f}% vs 지수 {bm_te:.1f}% · 출발 {base_te['CAGR']:.1f}%"),
        ('② 검증 낙폭 악화 ≤ 5%p', bool(sel['검증_MDD'] >= base_te['MDD'] - 5),
         f"{sel['검증_MDD']:.1f}% vs 출발 {base_te['MDD']:.1f}%"),
        ('③ 학습 순위가 검증까지 이어짐', bool(top['검증_CAGR'].median() > df['검증_CAGR'].median()),
         f"학습 상위 {k}개 검증 중앙 {top['검증_CAGR'].median():.1f}% vs 전체 {df['검증_CAGR'].median():.1f}%"),
        ('④ 이웃 조합도 좋음(한 점 우연 아님)', bool(np.isfinite(nb_med) and nb_med >= base_te['CAGR']),
         f"이웃 {len(nb)}개 검증 중앙 {nb_med:.1f}% vs 출발 {base_te['CAGR']:.1f}%" if nb else '이웃 없음(축이 1칸)'),
    ]
    out = dict(pick=i, crit=crit, passed=all(c[1] for c in crit), n=len(df))
    if rets and len(rets) >= 4:
        try:
            O = _overfit()
            R = pd.concat(rets, axis=1).fillna(0.0).to_numpy()
            out['dsr'] = O.dsr(R[:, i], O.sharpe(R))
            out['pbo'] = O.pbo(R, s=16 if len(R) >= 160 else 8)
        except Exception as e:                      # 참고 지표 — 실패해도 판정 ①~④ 는 남긴다
            out['overfit_err'] = f'{type(e).__name__}: {e}'
    return out
