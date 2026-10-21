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
RETRY_WAIT_S = 45      # 수집 실패분 재시도 전 대기(초)


def _us_pool():
    d = json.loads(RETURNS.read_text(encoding='utf-8'))
    ss = [s for s in d.get('stocks', [])
          if s['market'] == 'US' and str(s['sym']).isalpha() and s.get('ret_12m') is not None]
    arr = sorted(ss, key=lambda s: s['ret_12m'])
    n = len(arr)
    for i, s in enumerate(arr):
        s['rs_pct'] = round((i + 1) / n * 100, 1)
    return ss


FETCH_FAIL = 'fetch_fail'   # _price_block 이 '수집 실패'(조건 미달 아님)를 알리는 표식
PRICE_CACHE = Path('data/price_cache')   # perf_run 이 같은 CI 실행에서 먼저 받아 둔 일봉(parquet)
CACHE_MAX_AGE_D = 4                      # 마지막 봉이 이보다 오래면 캐시를 믿지 않는다(주말·휴장 포함)
_SRC = {'cache': 0, 'fdr': 0, 'yahoo': 0}  # 어디서 받았는지 — 결과 파일에 남긴다


def _ohlcv_cache(sym):
    """같은 실행에서 perf_run 이 저장한 일봉. 신선하지 않으면 None (낡은 값으로 신고가를 재지 않는다)."""
    import pandas as pd
    cp = PRICE_CACHE / f"{sym.replace('/', '_')}.parquet"
    if not cp.exists():
        return None
    try:
        df = pd.read_parquet(cp)
        if len(df) and (datetime.now() - pd.Timestamp(df.index[-1]).to_pydatetime()).days <= CACHE_MAX_AGE_D:
            return df
    except Exception:
        pass
    return None


def _ohlcv_yahoo(sym):
    """FinanceDataReader 를 거치지 않는 Yahoo v8 직접 호출 (query1 → query2)."""
    import urllib.request
    import pandas as pd
    for host in ('query1', 'query2'):
        try:
            url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}?range=1y&interval=1d"
            r = json.loads(urllib.request.urlopen(
                urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'}), timeout=15).read())['chart']['result'][0]
            q = r['indicators']['quote'][0]
            df = pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'],
                               'Close': q['close'], 'Volume': q['volume']},
                              index=pd.to_datetime(r['timestamp'], unit='s')).dropna(subset=['Close'])
            if len(df):
                return df
        except Exception:
            continue
    return None


def _ohlcv(sym):
    """1년 일봉. 캐시 → FDR → Yahoo 직접. 셋 다 실패하면 None."""
    df = _ohlcv_cache(sym)
    if df is not None:
        _SRC['cache'] += 1
        return df
    try:
        import FinanceDataReader as fdr
        df = fdr.DataReader(sym, (datetime.now() - timedelta(days=370)).strftime('%Y-%m-%d'))
        if df is not None and len(df):
            _SRC['fdr'] += 1
            return df
    except Exception:
        pass
    df = _ohlcv_yahoo(sym)
    if df is not None:
        _SRC['yahoo'] += 1
    return df


def _price_block(sym):
    """1년 일봉 → (n_dist_pct, vol_ratio, body_pct, is_bull). 데이터가 짧으면 None, 수집 실패면 FETCH_FAIL.

    2026-10-21: 예전엔 수집 실패도 None 이라 '조건 미달'과 구분되지 않았다. 10-20·10-21 정기 실행에서
    250개 중 1개만 남았는데(이 단계가 28~51초 — 정상 80~107초), 원인은 Yahoo 가 CI 서버를 막은 것이었다.
    이제 ① 같은 실행의 perf_run 캐시를 먼저 쓰고 ② FDR·Yahoo 직접 두 길로 받고 ③ 실패를 따로 센다.
    """
    df = _ohlcv(sym)
    if df is None:
        return FETCH_FAIL
    try:
        df = df[df.index >= df.index[-1] - timedelta(days=366)]
        if len(df) < 60:
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
        return FETCH_FAIL


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
    print(f"US 풀 {len(pool)} → RS{RS_PREFILTER}+·시총$3억+ 후보 {len(cands)}개. 가격/재무 검사...")

    def _check(s):
        """통과면 hit dict, 조건 미달이면 None, 수집 실패면 FETCH_FAIL."""
        pb = _price_block(s['sym'])
        if pb is None or pb == FETCH_FAIL:
            return pb
        n_dist, vol_ratio, body_pct, bull = pb
        if n_dist is None or n_dist != n_dist or n_dist < N_PREFILTER:   # None/NaN 차단
            return None
        e = _earnings(s['sym'])
        return {
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
        }

    hits, failed = [], []
    for i, s in enumerate(cands, 1):
        h = _check(s)
        if h == FETCH_FAIL:
            failed.append(s)
        elif h:
            hits.append(h)
        if i % 25 == 0:
            print(f"  {i}/{len(cands)}  (통과 {len(hits)} · 수집 실패 {len(failed)})")
        time.sleep(0.05)

    # 속도제한은 대개 몇십 초면 풀린다 — 실패분만 쉬었다가 천천히 한 번 더
    if failed:
        print(f"  수집 실패 {len(failed)}종 → {RETRY_WAIT_S}초 쉬고 재시도")
        time.sleep(RETRY_WAIT_S)
        still = []
        for s in failed:
            h = _check(s)
            if h == FETCH_FAIL:
                still.append(s)
            elif h:
                hits.append(h)
            time.sleep(0.4)
        failed = still
    hits.sort(key=lambda h: -h['rs_pct'])
    n_fail = len(failed)

    m_ok, m_dir = _market_dir()
    OUT.write_text(json.dumps({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'generated': datetime.now().isoformat(timespec='seconds'),
        'market_ok': m_ok, 'market_dir': m_dir,
        'n_cands': len(cands), 'price_fail': n_fail,
        'fetch_fail_pct': round(n_fail / len(cands) * 100, 1) if cands else None,
        'price_src': dict(_SRC),
        'stocks': hits,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ US CANSLIM: 후보 {len(hits)}개 (M: {m_dir}) · 가격 수집 실패 {n_fail}/{len(cands)} · 출처 {_SRC} → {OUT}")
    if cands and n_fail / len(cands) >= 0.3:
        print(f"::error::US CANSLIM 가격 수집 실패 {n_fail}/{len(cands)} — 후보 수가 아니라 수집 고장이다(캐시·FDR·Yahoo 모두 실패, 출처 {_SRC})")
    for h in hits[:8]:
        print(f"  {h['name'][:18]:<18} RS{h['rs_pct']:>5} N{h['n_dist_pct']:>6}% "
              f"C={h['c_growth_pct']} A={h['a_growth_y1']}/{h['a_growth_y2']}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=250)
    a = ap.parse_args()
    run(top=a.top)
