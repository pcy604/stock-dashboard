"""
leaders_kr.py — 코스닥/코스피 주도주 규칙 (가격 기반) 백테스트 + 신호 발행
──────────────────────────────────────────────────────────────────────────
왜 US 규칙⑥을 그대로 못 쓰나:
  규칙⑥의 핵심 조건은 '이익 변곡(흑자전환 OR 이익폭증)'인데 이건 **분기 재무**가 있어야
  판정된다. 그런데 이 저장소의 KR 재무는 `fundamentals` 테이블의 **연간 2023~2025, 835종**
  뿐이고, factor_weekly(주간 팩터)는 US 1,312종 전용이다. 2023년 이전 KR 분기 데이터가
  아예 없어 백테스트 자체가 불가능하다.

그래서 순서를 뒤집는다:
  2023 에코프로 실측에서 드러난 건 "진입(52주 신고가)은 단순했고 **문제는 전부 청산·재진입**"
  이었다. 그 부분은 **가격만으로** 검증된다. 가격 규칙을 먼저 세우고, KR 분기 재무가
  적재되면 그때 펀더멘털 필터를 얹어 개선폭을 측정한다.

규칙 (KR-P1):
  진입   종가가 직전 252거래일 최고가 초과 (52주 신고가 돌파) · 종가 ≥ MIN_PRICE
  청산   고점 대비 TRAIL%(-30%) 트레일링
  재진입 허용

  ⚠️ 손절폭은 단일 종목이 아니라 **전 종목 1,476종·2018~2026** 으로 정했다.
  에코프로 한 종목만 보면 -10%가 최적이었지만(포트 기여 +39%), 유니버스 전체로는
  넓을수록 좋았다: 평균수익 -7% 1.6% → -10% 2.3% → -20% 5.9% → **-30% 12.0%**,
  손익비도 2.49 → 3.08로 단조 개선. 단일 사례로 파라미터를 정하면 안 된다는
  교과서적 사례라 기록으로 남긴다.

⚠️ 알려진 한계 (결과를 읽을 때 반드시 감안)
  · 생존편향: longcache에는 **현재 상장 종목만** 있다. 상장폐지분이 빠져 낙관적이다.
  · 유동성 필터 불가: 캐시에 거래량이 없어 거래대금 컷을 못 건다. 실거래 불가능한
    소형주 신호가 섞인다 → 실제 체결은 이보다 나쁘다.
  · 진입가를 **당일 종가**로 가정한다(실제로는 다음날 시가). 약간 낙관적.
  · 거래비용 미반영은 아니다 — COST_PCT로 왕복 비용을 뺀다.

실행:
  python leaders_kr.py backtest        # 전 종목 백테스트 (파라미터 스펙트럼)
  python leaders_kr.py publish         # results/leaders_kr.json 생성 (대시보드용)
"""
from __future__ import annotations

import glob
import json
import os
import sys
from datetime import date

import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(BASE, 'data', 'longcache')
OUT = os.path.join(BASE, 'results', 'leaders_kr.json')
DB = os.path.join(BASE, 'data', 'market.db')

LOOKBACK = 252          # 52주
TRAIL = 30.0            # 고점대비 트레일링 % — 전 종목 백테스트에서 확정(아래 REJECTED 참고)
MIN_PRICE = 1000        # 동전주 제외
MIN_ADV = 10e8          # 20일 평균 거래대금 하한(원) = 10억
# ⚠️ 이 컷은 '수익을 높이려고' 넣은 게 아니다. 오히려 백테스트 수익을 **깎는다**:
#   컷 0억 12.0% → 5억 10.8% → 10억 9.8% → 30억 8.0% → 100억 6.4% (단조 감소)
# 그런데도 넣는 이유: 컷 없는 12.0% 안에는 **실제로는 체결할 수 없는** 소형주 신호가
# 섞여 있다. 낮아진 9.8%가 '진짜 값'이다. 필터가 성과를 깎는다고 빼면 백테스트만
# 예뻐지고 실전은 그대로다. 10억은 개인 자금 규모에서 체결 가능한 최소선으로 잡았다.
COST_PCT = 0.30         # 왕복 거래비용·슬리피지 가정 (%)
START = '2018-01-01'

# 검증에서 기각된 조건 — 넣으면 오히려 나빠진 것들. 화면에 그대로 노출한다.
REJECTED = [
    ('상대강도 RS13 ≥ 1.2', '평균 11.9% → 10.5%'),
    ('상대강도 RS13 ≥ 1.5', '평균 11.9% → 8.4%'),
    ('상대강도 RS13 ≥ 2.0', '평균 11.9% → 3.7%, 손익비 3.09 → 2.54'),
]
# US 규칙⑥의 핵심 조건(RS13>1.5)이 KR에서는 단조로 성과를 깎았다. 52주 신고가 자체가
# 이미 강한 모멘텀 필터라, RS를 겹치면 '이미 너무 오른 것'만 남아 되돌림이 커지는 것으로 보인다.


# ── 데이터 ─────────────────────────────────────────────────────────
def kr_symbols() -> list[str]:
    out = []
    for f in glob.glob(os.path.join(CACHE, '*.parquet')):
        s = os.path.basename(f)[:-8]
        if s.isdigit() and len(s) == 6:
            out.append(s)
    return sorted(out)


def load_close(sym: str) -> pd.Series | None:
    try:
        df = pd.read_parquet(os.path.join(CACHE, f'{sym}.parquet'))
    except Exception:
        return None
    if df.empty:
        return None
    df.index = pd.to_datetime(df.index)
    c = (df.iloc[:, 0] if df.shape[1] == 1 else df['Close']).dropna()
    return c if len(c) > LOOKBACK + 20 else None


def load_adv(sym: str, close: pd.Series | None = None) -> pd.Series | None:
    """20일 평균 거래대금(원). 캐시에 Volume 이 없으면 None → 필터 미적용."""
    try:
        df = pd.read_parquet(os.path.join(CACHE, f'{sym}.parquet'))
    except Exception:
        return None
    if 'Volume' not in df.columns:
        return None
    df.index = pd.to_datetime(df.index)
    v = (df['Close'] * df['Volume']).dropna()
    return v.rolling(20).mean() if len(v) > 25 else None


def names() -> dict:
    try:
        import sqlite3
        with sqlite3.connect(DB) as c:
            return dict(c.execute('SELECT sym, name FROM universe').fetchall())
    except Exception:
        return {}


# ── 규칙 ───────────────────────────────────────────────────────────
def trades_for(c: pd.Series, trail=TRAIL, start=START, end=None,
               min_price=MIN_PRICE, lookback=LOOKBACK, adv=None, min_adv=0) -> list[dict]:
    """52주 신고가 진입 → 고점대비 trail% 이탈 청산 → 재진입 허용.

    adv: 20일 평균 거래대금 시계열(원). min_adv 이상일 때만 진입한다 —
    '신호는 떴지만 실제로는 못 사는' 종목을 백테스트에서 빼기 위한 컷.
    """
    hi = c.rolling(lookback).max().shift(1)          # shift(1): 당일 종가는 비교에서 제외
    sig = (c > hi) & (c >= min_price)
    if adv is not None and min_adv > 0:
        sig = sig & (adv.reindex(c.index).ffill() >= min_adv)
    px = c[(c.index >= start) & ((c.index <= end) if end else True)]
    s = sig.reindex(px.index).fillna(False)
    out, pos, entry, peak, edate = [], False, 0.0, 0.0, None
    for d, p in px.items():
        if not pos:
            if s.loc[d]:
                pos, entry, peak, edate = True, float(p), float(p), d
        else:
            peak = max(peak, float(p))
            if p <= peak * (1 - trail / 100):
                out.append(dict(entry=edate, exit=d, ret=float(p) / entry - 1,
                                days=(d - edate).days, peak_gain=peak / entry - 1))
                pos = False
    if pos:
        out.append(dict(entry=edate, exit=px.index[-1], ret=float(px.iloc[-1]) / entry - 1,
                        days=(px.index[-1] - edate).days, peak_gain=peak / entry - 1,
                        open=True))
    return out


def summarize(rows: list[dict], label: str) -> dict:
    if not rows:
        return dict(label=label, n=0)
    r = pd.DataFrame(rows)
    net = r['ret'] * 100 - COST_PCT                  # 왕복 비용 차감
    win = net > 0
    payoff = (net[win].mean() / abs(net[~win].mean())) if (win.any() and (~win).any()) else None
    return dict(
        label=label, n=int(len(r)),
        winrate=round(float(win.mean()) * 100, 1),
        avg=round(float(net.mean()), 2),
        med=round(float(net.median()), 2),
        p90=round(float(net.quantile(0.90)), 1),
        p99=round(float(net.quantile(0.99)), 1),
        best=round(float(net.max()), 1),
        worst=round(float(net.min()), 1),
        payoff=(round(payoff, 2) if payoff else None),
        hold_d=int(r['days'].median()),
        # 기대값이 소수의 대박에서만 나오는지 = 꼬리 의존도
        top1pct_share=round(float(net.nlargest(max(1, len(r) // 100)).sum() / net.sum() * 100), 1)
        if net.sum() > 0 else None,
    )


# ── 백테스트 ───────────────────────────────────────────────────────
def backtest(trails=(7, 8, 10, 15, 20, 30), min_adv=MIN_ADV) -> dict:
    syms = kr_symbols()
    print(f'KR 유니버스 {len(syms)}종 · {START}~ · 트레일링 {trails} · '
          f'거래대금 컷 {min_adv/1e8:.0f}억', flush=True)
    per_trail = {t: [] for t in trails}
    used = no_vol = 0
    for i, s in enumerate(syms, 1):
        c = load_close(s)
        if c is None:
            continue
        adv = load_adv(s)
        if adv is None:
            no_vol += 1
        used += 1
        for t in trails:
            for tr in trades_for(c, trail=t, adv=adv, min_adv=min_adv):
                tr['sym'] = s
                per_trail[t].append(tr)
        if i % 400 == 0:
            print(f'  {i}/{len(syms)}', flush=True)
    print(f'  사용 {used}종 (거래량 없음 {no_vol}종)', flush=True)
    return {'universe': used, 'no_volume': no_vol,
            'rows': {t: summarize(v, f'-{t}% 트레일링') for t, v in per_trail.items()},
            'raw': per_trail}


def adv_spectrum(trail=TRAIL, cuts=(0, 5e8, 10e8, 30e8, 50e8, 100e8)):
    """거래대금 컷을 올리면 성과가 어떻게 변하나 — 필터가 진짜 도움이 되는지 확인."""
    syms = kr_symbols()
    cache = []
    for s in syms:
        c = load_close(s)
        if c is None:
            continue
        cache.append((s, c, load_adv(s)))
    print(f'  로드 {len(cache)}종', flush=True)
    out = {}
    for cut in cuts:
        rows = []
        for s, c, adv in cache:
            if cut > 0 and adv is None:
                continue                       # 거래량 없으면 검증 불가 → 제외
            rows += trades_for(c, trail=trail, adv=adv, min_adv=cut)
        out[cut] = summarize(rows, f'{cut/1e8:.0f}억')
        r = out[cut]
        print(f"  컷 {cut/1e8:>4.0f}억: n={r['n']:>6,} 승률 {r['winrate']:>4.1f}% "
              f"평균 {r['avg']:>6.2f}% 중앙 {r['med']:>7.2f}% 손익비 {r['payoff']} "
              f"상위1%의존 {r['top1pct_share']}%", flush=True)
    return out


def live_signals(trail=TRAIL, weeks=8, min_adv=MIN_ADV) -> list[dict]:
    """최근 N주 안에 진입 신호가 났고 아직 트레일링에 안 걸린 종목 = 현재 후보."""
    nm, out = names(), []
    cutoff = pd.Timestamp.today() - pd.Timedelta(weeks=weeks)
    for s in kr_symbols():
        c = load_close(s)
        if c is None:
            continue
        adv = load_adv(s)
        tr = trades_for(c, trail=trail, adv=adv, min_adv=min_adv,
                        start=str((pd.Timestamp.today() - pd.Timedelta(days=400)).date()))
        if not tr or not tr[-1].get('open'):
            continue
        t = tr[-1]
        if t['entry'] < cutoff:
            continue
        out.append(dict(sym=s, name=nm.get(s, s), entry_date=str(t['entry'].date()),
                        entry_px=round(float(c.loc[t['entry']]), 0),
                        close=round(float(c.iloc[-1]), 0),
                        ret=round(t['ret'] * 100, 1),
                        peak_gain=round(t['peak_gain'] * 100, 1),
                        stop=round(float(c.loc[t['entry']:].max()) * (1 - trail / 100), 0),
                        adv_eok=(round(float(adv.dropna().iloc[-1]) / 1e8) if adv is not None
                                 and len(adv.dropna()) else None),
                        days=t['days']))
    return sorted(out, key=lambda x: -x['ret'])


def publish():
    bt = backtest()
    sig = live_signals()
    out = dict(
        generated=str(date.today()),
        rule=f'52주 신고가 돌파 진입 · 고점대비 -{TRAIL:.0f}% 트레일링 청산 · 재진입 허용',
        params=dict(lookback=LOOKBACK, trail=TRAIL, min_price=MIN_PRICE,
                    cost_pct=COST_PCT, min_adv_eok=int(MIN_ADV / 1e8)),
        adv_spectrum={'0': dict(avg=12.01, n=5414, payoff=3.08, tail=44.3),
                      '5': dict(avg=10.75, n=5232, payoff=3.02, tail=47.1),
                      '10': dict(avg=9.79, n=5079, payoff=2.96, tail=49.3),
                      '30': dict(avg=7.95, n=4494, payoff=2.83, tail=58.7),
                      '50': dict(avg=6.87, n=4030, payoff=2.73, tail=64.4),
                      '100': dict(avg=6.39, n=3171, payoff=2.80, tail=69.6)},
        universe=bt['universe'], period=f'{START} ~ {date.today()}',
        backtest={str(k): v for k, v in bt['rows'].items()},
        n=len(sig), candidates=sig[:60],
        caveats=[
            '생존편향: 현재 상장 종목만 포함 — 상장폐지분이 빠져 낙관적',
            f'거래대금 20일평균 {int(MIN_ADV/1e8)}억 이상만 진입 — 체결 가능한 신호만 남긴다',
            '진입가를 당일 종가로 가정(실제는 익일 시가)',
            f'왕복 거래비용 {COST_PCT}% 차감 반영',
            'KR 분기 재무 부재로 이익 변곡(흑자전환·이익폭증) 필터 미적용 — US 규칙⑥과 다름',
        ])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'→ {OUT} (후보 {len(sig)}종)')
    return out


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'backtest'
    if cmd == 'publish':
        publish()
    elif cmd == 'adv':
        adv_spectrum()
    else:
        bt = backtest()
        print(f"\n{'규칙':<16}{'거래':>7}{'승률':>7}{'평균':>8}{'중앙':>8}{'p90':>8}"
              f"{'최대':>9}{'손익비':>7}{'보유일':>7}{'상위1%비중':>10}")
        print('─' * 96)
        for t, r in bt['rows'].items():
            print(f"-{t:<15}{r['n']:>7,}{r['winrate']:>6.1f}%{r['avg']:>7.1f}%{r['med']:>7.1f}%"
                  f"{r['p90']:>7.0f}%{r['best']:>8.0f}%{str(r['payoff']):>7}"
                  f"{r['hold_d']:>7}{str(r['top1pct_share']):>9}%")
