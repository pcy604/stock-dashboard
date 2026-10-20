"""
CANSLIM 스크리너 — 미국 (US)
─────────────────────────────────────────────────────────────────
KR(canslim_run.py)과 동일 스키마로 results/canslim_us_latest.json 생성.
C·A = SEC EDGAR 공식 재무 (분기/연간 순이익 YoY)
N   = 52주 신고가 거리, S = 거래량 배수·캔들, L = RS(12개월 수익률 백분위)
I   = 무료 일간 수급 소스 없음(13F는 분기) → None('?')
M   = SPY > 200일선

실행: python canslim_us_run.py [--top 250]   (daily-refresh에서 매일)
"""
import sys
import json
import time
import argparse
from pathlib import Path
from datetime import datetime, timedelta

RETURNS = Path('results/returns.json')
OUT = Path('results/canslim_us_latest.json')

RS_PREFILTER = 60      # RS 백분위 사전필터 (대시보드 슬라이더로 정밀 조정)
N_PREFILTER = -20.0    # 신고가 거리 사전필터(%)
MIN_MARCAP = 3e8       # $3억 (2026-10-19 공통 커버 기준, 전 $2B)


def _us_pool():
    d = json.loads(RETURNS.read_text(encoding='utf-8'))
    ss = [s for s in d.get('stocks', [])
          if s['market'] == 'US' and str(s['sym']).isalpha() and s.get('ret_12m') is not None]
    arr = sorted(ss, key=lambda s: s['ret_12m'])
    n = len(arr)
    for i, s in enumerate(arr):
        s['rs_pct'] = round((i + 1) / n * 100, 1)
    return ss


def _price_block(sym):
    """1년 일봉 → (n_dist_pct, vol_ratio, body_pct, is_bull). 실패 시 None."""
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=370)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym, start)
        if df is None or len(df) < 60:
            return None
        hi52 = float(df['High'].max())
        c = float(df['Close'].iloc[-1])
        n_dist = round((c / hi52 - 1) * 100, 1) if hi52 > 0 else None
        v60 = float(df['Volume'].tail(60).mean())
        v5 = float(df['Volume'].tail(5).mean())
        vol_ratio = round(v5 / v60, 2) if v60 > 0 else None
        last = df.iloc[-1]
        rng = float(last['High'] - last['Low'])
        body = abs(float(last['Close'] - last['Open']))
        body_pct = round(body / rng * 100, 0) if rng > 0 else 0
        return n_dist, vol_ratio, body_pct, bool(last['Close'] >= last['Open'])
    except Exception:
        return None


def _yoy(cur, prev):
    if cur is None or prev is None:
        return None
    if prev < 0:
        return '흑자전환' if cur > 0 else None
    if prev == 0:
        return None
    # 2026-10-14 — 흑자→적자를 숫자로 내면 LITE 처럼 -26,876% 가 나온다(FY26 일회성
    #   부채소멸손실 78억$). 계산은 맞지만 표에서 '성장률'로 읽히면 안 되는 값이다.
    if cur < 0:
        return '적자전환'
    return round((cur / prev - 1) * 100, 1)


ONEOFF_GAP_PP = 50     # 순이익 성장과 영업이익 성장이 이만큼(%p) 벌어지면 '일회성 의심'


def growth_pair(ni_cur, ni_prev, op_cur, op_prev):
    """(판정용 성장률, GAAP 순이익 성장률, 일회성 의심 여부, 기준 'OP'|'NI').

    2026-10-20 (점검 #6) — 오닐은 **일회성 손익을 뺀 EPS** 로 C·A 를 본다. SEC 무료 데이터에는
    '조정 EPS' 가 없어서, 영업외 일회성(부채 소멸 손실·투자 평가손익·세금 효과)이 빠진
    **영업이익**을 근사로 쓴다. 금융·리츠처럼 영업이익 계정이 없으면 순이익 그대로(기준 'NI').
    한계: 영업이익 안의 구조조정·손상차손은 못 거르고, 주당(희석) 효과도 반영하지 않는다."""
    gaap = _yoy(ni_cur, ni_prev)
    if op_cur is None or op_prev is None:
        return gaap, gaap, False, 'NI'
    core = _yoy(op_cur, op_prev)
    if gaap is None or core is None:
        return core, gaap, False, 'OP'
    if isinstance(core, str) or isinstance(gaap, str):
        odd = core != gaap
    else:
        odd = abs(core - gaap) > ONEOFF_GAP_PP
    return core, gaap, odd, 'OP'


def _earnings(sym):
    """EDGAR: C(최근 분기 YoY) + A(연간 y1/y2) + 매출·영업익 YoY. C·A 는 growth_pair 기준(영업이익 근사)."""
    import edgar_client

    out = dict(c_g=None, c_q='', a1=None, a2=None, rev_g=None, op_g=None,
               c_gaap=None, a1_gaap=None, a2_gaap=None, oneoff=[], basis=None)
    try:
        q = edgar_client.statements(sym, 'quarter', 8)
        q = [r for r in q if r.get('net_income') is not None or r.get('op_income') is not None]
        if q:
            latest = q[0]
            ly, lm = int(latest['period'][:4]), int(latest['period'][5:7])
            prev = next((r for r in q[1:]
                         if int(r['period'][:4]) == ly - 1 and abs(int(r['period'][5:7]) - lm) <= 1), None)
            if prev:
                core, gaap, odd, b = growth_pair(latest.get('net_income'), prev.get('net_income'),
                                                 latest.get('op_income'), prev.get('op_income'))
                out.update(c_g=core, c_gaap=gaap, c_q=latest['period'], basis=b)
                if odd:
                    out['oneoff'].append('C')
    except Exception:
        pass

    try:
        f = edgar_client.facts(sym)
        yrs = sorted(f.keys(), reverse=True)
        ni = [f[y].get('net_income') for y in yrs]
        rv = [f[y].get('revenue') for y in yrs]
        op = [f[y].get('op_income') for y in yrs]
        if len(yrs) >= 2:
            core, gaap, odd, b = growth_pair(ni[0], ni[1], op[0], op[1])
            out.update(a1=core, a1_gaap=gaap, rev_g=_yoy(rv[0], rv[1]), op_g=_yoy(op[0], op[1]))
            out['basis'] = out['basis'] or b
            if odd:
                out['oneoff'].append('A최근')
        if len(yrs) >= 3:
            core, gaap, odd, _ = growth_pair(ni[1], ni[2], op[1], op[2])
            out.update(a2=core, a2_gaap=gaap)
            if odd:
                out['oneoff'].append('A전년')
    except Exception:
        pass
    return out


def _market_dir():
    """[M] S&P500 200일선 — verdict.core_switch (코어 스위치와 같은 함수, 2026-10-21)."""
    import verdict as V
    sw = V.core_switch(V.daily_closes(V.CORE_SYM))
    return (sw['on'], V.market_dir(sw)) if sw else (True, '판단불가')


def run(top=250):
    pool = _us_pool()
    cands = [s for s in pool
             if s['rs_pct'] >= RS_PREFILTER and (s.get('marcap') or 0) >= MIN_MARCAP]
    cands.sort(key=lambda s: -s['rs_pct'])
    cands = cands[:top]
    print(f"US 풀 {len(pool)} → RS{RS_PREFILTER}+·시총$2B+ 후보 {len(cands)}개. 가격/재무 검사...")

    hits = []
    for i, s in enumerate(cands, 1):
        pb = _price_block(s['sym'])
        if pb is None:
            continue
        n_dist, vol_ratio, body_pct, bull = pb
        if n_dist is None or n_dist != n_dist or n_dist < N_PREFILTER:   # None/NaN 차단
            continue
        e = _earnings(s['sym'])
        hits.append({
            'sym': s['sym'], 'name': s['name'], 'market': 'US',
            'marcap': s.get('marcap'),
            'rs_pct': s['rs_pct'], 'n_dist_pct': n_dist,
            's_vol_ratio': vol_ratio, 's_body_pct': body_pct, 's_bull': bull,
            'c_growth_pct': e['c_g'], 'c_quarter': e['c_q'],
            'a_growth_y1': e['a1'], 'a_growth_y2': e['a2'],
            'earn_basis': e['basis'],                # 'OP'=영업이익(일회성 제외 근사) · 'NI'=순이익
            'c_growth_gaap': e['c_gaap'], 'a_growth_y1_gaap': e['a1_gaap'], 'a_growth_y2_gaap': e['a2_gaap'],
            'oneoff': e['oneoff'],                   # 순이익과 영업이익 성장이 크게 갈린 글자
            'i_inst_pct': None,                      # US 일간 수급 무료소스 없음
            'rev_growth': e['rev_g'], 'op_growth': e['op_g'],
        })
        if i % 25 == 0:
            print(f"  {i}/{len(cands)}  (통과 {len(hits)})")
        time.sleep(0.05)

    m_ok, m_dir = _market_dir()
    OUT.write_text(json.dumps({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'generated': datetime.now().isoformat(timespec='seconds'),
        'market_ok': m_ok, 'market_dir': m_dir,
        'stocks': hits,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ US CANSLIM: 후보 {len(hits)}개 (M: {m_dir}) → {OUT}")
    for h in hits[:8]:
        print(f"  {h['name'][:18]:<18} RS{h['rs_pct']:>5} N{h['n_dist_pct']:>6}% "
              f"C={h['c_growth_pct']} A={h['a_growth_y1']}/{h['a_growth_y2']}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=250)
    a = ap.parse_args()
    run(top=a.top)
