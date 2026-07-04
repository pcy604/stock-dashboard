"""
주도주 발굴 v2 — "주도주 지문" 기반 (2026-07 재설계)
─────────────────────────────────────────────────────────────────
역대 주도주(TSLA 20-21 · NVDA 23-24 · PLTR 24-25 · 삼전닉스/MU/SNDK/BE 25-26)
공식 재무 분석에서 도출한 공통 지문:

  ① 이익 변곡 (필수): 흑자전환 OR 영업이익 YoY ≥ +100%   ← DART/EDGAR 공식
  ② 매출 가속 (보너스): 매출 성장률 > 전년 성장률
  ③ RS ≥ 85: 12개월 수익률의 시장 내 백분위 (시장별 풀)
  ④ 52주 신고가 -15% 이내
  ⑤ 유니버스: KR 시총 상위 150 + US 상위 300 (+ data/leaders_watch.txt)
  ⑥ 클러스터: 같은 섹터 통과 2개+ → '주도 테마'

출력: results/leaders_v2.json  (대시보드 '주도주' 탭이 읽음)
실행: python leaders_run.py            (daily-refresh 에서 매일)
"""
import sys
import json
import time
from pathlib import Path
from datetime import datetime, timedelta

RETURNS = Path('results/returns.json')
OUT = Path('results/leaders_v2.json')
WATCH = Path('data/leaders_watch.txt')

RS_MIN = 85            # 12개월 수익률 백분위 하한
DIST_MIN = -25.0       # 52주 신고가 대비 하한(%) — 주도주도 강세장 조정에서 -20~30% 눌림(오닐)
OP_ACCEL = 100.0       # 영업이익 YoY 급가속 기준(%)
KR_TOP, US_TOP = 150, 300


def _load_returns():
    d = json.loads(RETURNS.read_text(encoding='utf-8'))
    ss = [s for s in d.get('stocks', []) if s.get('ret_12m') is not None]
    kr = [s for s in ss if s['market'] == 'KR' and str(s['sym']).isdigit()]
    us = [s for s in ss if s['market'] == 'US' and str(s['sym']).isalpha()]   # 오염행 제거
    return kr, us


def _rs_pct(pool):
    """풀 내 12개월 수익률 백분위 {sym: 0~100}."""
    arr = sorted(pool, key=lambda s: s['ret_12m'])
    n = len(arr)
    return {s['sym']: round((i + 1) / n * 100, 1) for i, s in enumerate(arr)}


def _watchlist():
    try:
        return [x.strip().upper() for x in WATCH.read_text(encoding='utf-8').splitlines()
                if x.strip() and not x.startswith('#')]
    except Exception:
        return []


def _dist_52w(sym, market):
    """1년 일봉에서 52주 고가 대비 현재가 거리(%). 실패 시 None."""
    try:
        import FinanceDataReader as fdr
        start = (datetime.now() - timedelta(days=370)).strftime('%Y-%m-%d')
        df = fdr.DataReader(sym if market == 'KR' else sym, start)
        if df is None or df.empty or 'Close' not in df.columns:
            return None
        hi = float(df['High'].max() if 'High' in df.columns else df['Close'].max())
        cur = float(df['Close'].iloc[-1])
        return round((cur / hi - 1) * 100, 1) if hi > 0 else None
    except Exception:
        return None


def _yoy(cur, prev):
    if cur is None or prev is None:
        return None
    if prev <= 0:
        return '흑자전환' if cur > 0 else None
    return round((cur / prev - 1) * 100, 1)


def _hits(g):
    """성장률 값이 변곡 기준(흑자전환 or ≥OP_ACCEL%)을 넘는가."""
    return (g == '흑자전환') or (isinstance(g, (int, float)) and g >= OP_ACCEL)


def _inflection_kr(sym, cmap):
    """KR 이익 변곡: 최근 2개 연간 + 최근 분기 중 하나라도 흑전/급가속이면 통과.
    (변곡 원년이 작년이어도 대세 상승은 이어짐 — 삼성 2024 +396% 사례)"""
    cc = cmap.get(sym)
    if not cc:
        return None, None, None
    try:
        import dart_client
        g = dart_client.canslim_growth(cc)
        vals = [g.get('op_growth'), g.get('c_growth'), g.get('a_growth_y1'), g.get('a_growth_y2')]
        ok = any(_hits(v) for v in vals)
        best = next((v for v in vals if _hits(v)), g.get('op_growth') or g.get('c_growth'))
        if all(v is None for v in vals):
            return None, None, None
        return ok, best, None
    except Exception:
        return None, None, None


def _inflection_us(sym):
    """US 이익 변곡: EDGAR 최근 2개 연간 YoY 중 하나라도 흑전/급가속이면 통과."""
    try:
        import edgar_client
        f = edgar_client.facts(sym)
        yrs = sorted([y for y in f if isinstance(f[y], dict)], reverse=True)
        if len(yrs) < 2:
            return None, None, None
        def _og(i):
            a, b = f[yrs[i]], f[yrs[i + 1]]
            v = _yoy(a.get('op_income'), b.get('op_income'))
            return v if v is not None else _yoy(a.get('net_income'), b.get('net_income'))
        vals = [_og(0)] + ([_og(1)] if len(yrs) >= 3 else [])
        ok = any(_hits(v) for v in vals)
        best = next((v for v in vals if _hits(v)), vals[0])
        # ② 매출 가속: 최근 성장률 > 직전 성장률
        accel = None
        if len(yrs) >= 3:
            g1 = _yoy(f[yrs[0]].get('revenue'), f[yrs[1]].get('revenue'))
            g2 = _yoy(f[yrs[1]].get('revenue'), f[yrs[2]].get('revenue'))
            if isinstance(g1, (int, float)) and isinstance(g2, (int, float)):
                accel = g1 > g2
        if all(v is None for v in vals):
            return None, None, None
        return ok, best, accel
    except Exception:
        return None, None, None


_GICS_KO = {'Information Technology': 'IT·반도체', 'Health Care': '헬스케어',
            'Consumer Staples': '필수소비재', 'Consumer Discretionary': '임의소비재',
            'Industrials': '산업재', 'Materials': '소재', 'Energy': '에너지',
            'Financials': '금융', 'Communication Services': '커뮤니케이션',
            'Utilities': '유틸리티', 'Real Estate': '부동산'}

_JUNK_SECTORS = {'중견기업부', '우량기업부', '벤처기업부', '기술성장기업부', '기타', '미분류'}


def _sector_map():
    """섹터맵 — KR: KRX-DESC 'Industry'(진짜 업종명; 'Sector' 컬럼은 소속부 쓰레기값),
    US: S&P500 GICS(한글 변환). 폴백: 기존 sectors.json(소속부 값 필터)."""
    m = {}
    try:
        import FinanceDataReader as fdr
        desc = fdr.StockListing('KRX-DESC')
        for _, r in desc.iterrows():
            c = str(r.get('Code', '')).zfill(6)
            ind = r.get('Industry')
            if c.isdigit() and isinstance(ind, str) and ind.strip():
                m[c] = ind.strip()
    except Exception:
        pass
    try:
        import FinanceDataReader as fdr
        sp = fdr.StockListing('S&P500')
        for _, r in sp.iterrows():
            sec = r.get('Sector')
            if isinstance(sec, str) and sec.strip():
                m[str(r.get('Symbol', '')).upper()] = _GICS_KO.get(sec.strip(), sec.strip())
    except Exception:
        pass
    try:
        from sectors import get_sector_map
        for k, v in get_sector_map().items():
            if isinstance(v, str) and v.strip() and v.strip() not in _JUNK_SECTORS:
                m.setdefault(k, v.strip())
    except Exception:
        pass
    return m


def run():
    kr, us = _load_returns()
    rs_kr, rs_us = _rs_pct(kr), _rs_pct(us)
    watch = set(_watchlist())

    kr.sort(key=lambda s: -(s.get('marcap') or 0))
    us.sort(key=lambda s: -(s.get('marcap') or 0))
    uni = kr[:KR_TOP] + us[:US_TOP]
    uni += [s for s in kr[KR_TOP:] + us[US_TOP:] if str(s['sym']).upper() in watch]

    # ③ RS 필터
    cands = []
    for s in uni:
        rs = (rs_kr if s['market'] == 'KR' else rs_us).get(s['sym'], 0)
        if rs >= RS_MIN:
            s = dict(s); s['rs'] = rs
            cands.append(s)
    print(f"유니버스 {len(uni)} → RS{RS_MIN}+ 통과 {len(cands)}개. 신고가·이익변곡 검사...")

    cmap = {}
    try:
        import dart_client
        cmap = dart_client.corp_map()
    except Exception:
        pass
    smap = _sector_map()

    out = []
    for i, s in enumerate(cands, 1):
        sym, mkt = s['sym'], s['market']
        d = _dist_52w(sym, mkt)                              # ④
        if d is not None and d < DIST_MIN:
            continue
        if mkt == 'KR':
            ok, og, accel = _inflection_kr(sym, cmap)        # ①②
        else:
            ok, og, accel = _inflection_us(sym)
        sec = smap.get(sym) or smap.get(str(sym).zfill(6)) or s.get('sector') or '미분류'
        out.append({'sym': sym, 'market': mkt, 'name': s['name'], 'marcap': s.get('marcap'),
                    'rs': s['rs'], 'ret_12m': s.get('ret_12m'), 'ret_1m': s.get('ret_1m'),
                    'dist_52w': d, 'sector': sec,
                    'op_growth': og, 'rev_accel': accel,
                    'inflection': ok})                        # True/False/None(데이터없음)
        if i % 20 == 0:
            print(f"  {i}/{len(cands)}...")
        time.sleep(0.05)

    # 정렬: 변곡 통과 → 데이터없음 → 미통과, 각 그룹 내 RS 내림차순
    rank = {True: 0, None: 1, False: 2}
    out.sort(key=lambda x: (rank.get(x['inflection'], 2), -x['rs']))
    leaders = [x for x in out if x['inflection'] is True]

    # ⑥ 클러스터 (변곡 통과 종목 기준, 미분류 제외 없이 표시용 그룹만)
    from collections import defaultdict
    clus = defaultdict(list)
    for x in leaders:
        clus[x['sector']].append(x)
    themes = [{'sector': k, 'n': len(v),
               'members': sorted(v, key=lambda m: -m['rs'])}
              for k, v in clus.items() if len(v) >= 2 and k != '미분류']
    themes.sort(key=lambda t: -t['n'])

    OUT.write_text(json.dumps({
        'generated': datetime.now().isoformat(timespec='seconds'),
        'criteria': {'rs_min': RS_MIN, 'dist_min': DIST_MIN, 'op_accel': OP_ACCEL,
                     'kr_top': KR_TOP, 'us_top': US_TOP},
        'themes': themes, 'all': out,
    }, ensure_ascii=False), encoding='utf-8')
    print(f"\n✅ 주도주 v2: 후보 {len(out)} · 변곡통과 {len(leaders)} · 주도테마 {len(themes)}개 → {OUT}")
    for t in themes[:5]:
        print(f"  [테마] {t['sector']}: {', '.join(m['name'][:10] for m in t['members'][:5])}")
    for x in leaders[:12]:
        og = x['op_growth']
        ogs = og if isinstance(og, str) else (f"{og:+.0f}%" if og is not None else '?')
        print(f"  {x['market']} {x['name'][:14]:<14} RS{x['rs']:>5} 신고가{x['dist_52w'] if x['dist_52w'] is not None else '?':>6} 영익{ogs}")


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    run()
