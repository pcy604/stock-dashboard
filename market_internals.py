# -*- coding: utf-8 -*-
"""시장 내부(폭·업종·신고가·돈이 몰린 종목) — 미국 전 종목 + 한국 주간·월간 + 대형주 상승 비율 추이. 2026-11-14 신설.

왜: 종합 탭 '오늘의 시장'은 한국만 있었다(한국 = KRX 전 종목 목록 한 장으로 계산). 미국은 같은 목록이 없어
   **시총 상위 500(perf_latest, ≈ S&P500)** 의 1년 일봉을 Yahoo 에서 받아 같은 모양으로 만든다.
   상승 비율 추이는 한국 로그(kr_breadth_log)가 2026-11-12 부터라 이틀뿐이었다 → **일봉에서 바로 30거래일**을 계산한다
   (한국은 시총 1조+ 대형주, 미국은 시총 상위 500 — 두 시장 모두 '대형주' 기준으로 맞춤).

market_report.facts('daily') 가 부른다(CI). 화면은 결과 JSON 만 읽는다. 실패하면 빈 dict — 지어내지 않는다.
"""
from __future__ import annotations

import json
import os

BASE = os.path.dirname(os.path.abspath(__file__))

# Yahoo 업종(industry) → 한국어. 상위 500에 자주 나오는 것만 — 없는 건 영문 그대로(지어내지 않는다).
IND_KO = {
    'Software - Infrastructure': '인프라 소프트웨어', 'Software - Application': '응용 소프트웨어',
    'Utilities - Regulated Electric': '전력 유틸리티', 'Aerospace & Defense': '항공우주·방산',
    'Semiconductors': '반도체', 'Semiconductor Equipment & Materials': '반도체 장비·소재',
    'Specialty Industrial Machinery': '산업 기계', 'Diagnostics & Research': '진단·연구',
    'Asset Management': '자산운용', 'Oil & Gas Midstream': '송유·가스관', 'Biotechnology': '바이오',
    'Banks - Regional': '지역 은행', 'Banks - Diversified': '대형 은행', 'Oil & Gas E&P': '석유·가스 탐사',
    'Drug Manufacturers - General': '대형 제약', 'Medical Devices': '의료기기', 'Credit Services': '카드·신용',
    'Capital Markets': '증권·투자은행', 'Specialty Chemicals': '특수 화학', 'Computer Hardware': '컴퓨터 하드웨어',
    'Financial Data & Stock Exchanges': '거래소·금융 데이터', 'Insurance - Property & Casualty': '손해보험',
    'Communication Equipment': '통신장비', 'Healthcare Plans': '건강보험', 'Restaurants': '외식',
    'REIT - Specialty': '특수 리츠', 'Internet Retail': '온라인 유통', 'Discount Stores': '할인점',
    'Household & Personal Products': '생활용품', 'Information Technology Services': 'IT 서비스',
    'Electronic Components': '전자부품', 'Telecom Services': '통신서비스', 'Medical Instruments & Supplies': '의료 소모품',
    'Travel Services': '여행', 'Insurance Brokers': '보험 중개', 'Integrated Freight & Logistics': '물류',
    'Scientific & Technical Instruments': '계측기기', 'Auto Manufacturers': '자동차', 'Insurance - Diversified': '종합 보험',
    'Beverages - Non-Alcoholic': '음료', 'Entertainment': '엔터테인먼트', 'Railroads': '철도',
    'Electrical Equipment & Parts': '전기장비', 'Engineering & Construction': '건설·엔지니어링',
    'Specialty Business Services': '기업 서비스', 'Oil & Gas Equipment & Services': '유전 서비스',
    'Specialty Retail': '전문 소매', 'Packaging & Containers': '포장재', 'Internet Content & Information': '인터넷 플랫폼',
    'Oil & Gas Integrated': '석유 메이저', 'Farm & Heavy Construction Machinery': '농기계·중장비',
    'REIT - Industrial': '물류 리츠', 'Medical Distribution': '의약품 유통', 'Oil & Gas Refining & Marketing': '정유',
    'Lodging': '호텔', 'Utilities - Independent Power Producers': '발전 사업자', 'Building Products & Equipment': '건축자재',
    'Industrial Distribution': '산업재 유통', 'Insurance - Life': '생명보험', 'Steel': '철강',
    'Home Improvement Retail': '주택용품 소매', 'Consumer Electronics': '가전', 'Tobacco': '담배',
    'Utilities - Diversified': '종합 유틸리티', 'Utilities - Regulated Gas': '가스 유틸리티',
    'Gold': '금광', 'Copper': '구리', 'Chemicals': '화학', 'Agricultural Inputs': '비료·농자재',
    'Packaged Foods': '가공식품', 'Apparel Retail': '의류 소매', 'Residential Construction': '주택 건설',
    'REIT - Residential': '주거 리츠', 'REIT - Retail': '상업 리츠', 'REIT - Healthcare Facilities': '헬스케어 리츠',
    'Waste Management': '폐기물', 'Rental & Leasing Services': '렌탈·리스', 'Airlines': '항공사',
    'Trucking': '트럭 운송', 'Security & Protection Services': '보안', 'Staffing & Employment Services': '인력 서비스',
    'Consulting Services': '컨설팅', 'Advertising Agencies': '광고', 'Electronic Gaming & Multimedia': '게임',
    'Leisure': '레저', 'Resorts & Casinos': '카지노·리조트', 'Auto Parts': '자동차 부품',
    'Medical Care Facilities': '병원', 'Drug Manufacturers - Specialty & Generic': '특수·제네릭 제약',
    'Conglomerates': '복합기업', 'Tools & Accessories': '공구', 'Building Materials': '건자재',
    'Solar': '태양광', 'Uranium': '우라늄', 'Mortgage Finance': '모기지', 'Insurance - Reinsurance': '재보험',
    'Apparel Manufacturing': '의류', 'Footwear & Accessories': '신발·잡화', 'Grocery Stores': '식료품점',
    'Food Distribution': '식품 유통', 'Beverages - Brewers': '맥주', 'Beverages - Wineries & Distilleries': '주류',
    'Confectioners': '제과', 'Pollution & Treatment Controls': '환경 설비', 'Metal Fabrication': '금속 가공',
    'Personal Services': '개인 서비스', 'Education & Training Services': '교육', 'Publishing': '출판',
    'Broadcasting': '방송', 'Health Information Services': '헬스케어 IT', 'Marine Shipping': '해운',
    'Airports & Air Services': '공항 서비스', 'Thermal Coal': '석탄', 'Oil & Gas Drilling': '시추',
    'Other Industrial Metals & Mining': '비철금속', 'Aluminum': '알루미늄', 'Lumber & Wood Production': '목재',
    'Real Estate Services': '부동산 서비스', 'Shell Companies': '스팩', 'Pharmaceutical Retailers': '약국',
    'Department Stores': '백화점', 'Luxury Goods': '명품', 'Recreational Vehicles': '레저 차량',
    'Furnishings, Fixtures & Appliances': '가구·가전', 'Electronics & Computer Distribution': '전자 유통',
}

# 대형주 한국어 이름 — 화면 가독(나머지는 티커)
NAME_KO = {'NVDA': '엔비디아', 'MSFT': '마이크로소프트', 'AAPL': '애플', 'GOOGL': '알파벳', 'GOOG': '알파벳C',
           'AMZN': '아마존', 'META': '메타', 'AVGO': '브로드컴', 'TSLA': '테슬라', 'BRK-B': '버크셔', 'BRK-A': '버크셔',
           'JPM': 'JP모건', 'WMT': '월마트', 'LLY': '일라이릴리', 'V': '비자', 'ORCL': '오라클', 'MA': '마스터카드',
           'NFLX': '넷플릭스', 'XOM': '엑슨모빌', 'COST': '코스트코', 'JNJ': '존슨앤존슨', 'HD': '홈디포',
           'PG': 'P&G', 'BAC': '뱅크오브아메리카', 'ABBV': '애브비', 'PLTR': '팔란티어', 'AMD': 'AMD', 'KO': '코카콜라',
           'CVX': '셰브론', 'UNH': '유나이티드헬스', 'CSCO': '시스코', 'IBM': 'IBM', 'MU': '마이크론', 'INTC': '인텔',
           'TSM': 'TSMC', 'ASML': 'ASML', 'CRM': '세일즈포스', 'ADBE': '어도비', 'QCOM': '퀄컴', 'TXN': '텍사스인스트루먼트',
           'GS': '골드만삭스', 'MS': '모건스탠리', 'WFC': '웰스파고', 'DIS': '디즈니', 'MCD': '맥도날드',
           'PEP': '펩시', 'NKE': '나이키', 'BA': '보잉', 'CAT': '캐터필러', 'GE': 'GE에어로', 'LMT': '록히드마틴',
           'UBER': '우버', 'SHOP': '쇼피파이', 'ARM': 'ARM', 'ANET': '아리스타', 'NOW': '서비스나우', 'INTU': '인튜이트',
           'ISRG': '인튜이티브서지컬', 'PM': '필립모리스', 'T': 'AT&T', 'VZ': '버라이즌', 'MRK': '머크', 'PFE': '화이자',
           'AMAT': '어플라이드머티리얼즈', 'LRCX': '램리서치', 'KLAC': 'KLA', 'COIN': '코인베이스', 'HOOD': '로빈후드',
           'APP': '앱러빈', 'MSTR': '스트래티지', 'SMCI': '슈퍼마이크로', 'DELL': '델', 'VRT': '버티브'}


def _j(p):
    try:
        return json.load(open(os.path.join(BASE, p), encoding='utf-8'))
    except Exception:
        return {}


def _r(v, n=2):
    return None if v is None or v != v else round(float(v), n)


def _dl(syms, period='1y', batch=100):
    """Yahoo 일봉 — 100종씩 끊어 받는다(한 번에 수백 종은 중간에 끊긴 적이 있다, price_store 문서)."""
    import pandas as pd
    import yfinance as yf
    parts = {k: [] for k in ('Close', 'High', 'Volume')}
    for i in range(0, len(syms), batch):
        try:
            d = yf.download(list(syms[i:i + batch]), period=period, interval='1d', progress=False,
                            auto_adjust=False, threads=True)
            for k in parts:
                if k in d:
                    parts[k].append(d[k])
        except Exception as e:
            print('  Yahoo 묶음 실패:', str(e)[:80])
    return {k: (pd.concat(v, axis=1) if v else pd.DataFrame()) for k, v in parts.items()}


def _trend(close, n=30):
    """상승 비율 — 최근 n거래일. 그날 값이 있는 종목이 80% 미만인 날(휴장·결측)은 뺀다."""
    r = close.pct_change(fill_method=None) * 100
    out = []
    for dt, row in r.iloc[-(n + 5):].iterrows():
        v = row.dropna()
        if len(v) < 0.8 * close.shape[1]:
            continue
        out.append(dict(date=str(dt.date()), up=int((v > 0).sum()), down=int((v < 0).sum()), flat=int((v == 0).sum())))
    return out[-n:]


_LIM = {1: 60, 5: 100, 21: 200}     # 기간 수익률 상한(%) — 넘으면 분할·시세 오류 의심으로 순위에서 뺀다
PERIODS = (('d1', 1), ('w1', 5), ('m1', 21))


def _view(c, h, v, meta, k, big, amt_fmt, mc_div, sec_of, min_sec=3):
    """k거래일 수익률로 본 시장 내부 — 일간(k=1)·주간(5)·월간(21) 같은 모양. 2026-11-14.
    meta {sym: (이름, 시총)} · big = 대형주 sym 집합(상승·하락 상위는 대형주에서만) · amt_fmt(거래대금) → 글자."""
    import pandas as pd
    if len(c) <= k + 1:
        return {}
    r = ((c.iloc[-1] / c.iloc[-1 - k] - 1) * 100).dropna()
    r = r[[s for s in r.index if s in meta]]
    r = r[r.abs() <= _LIM[k]]
    if len(r) < 50:
        return {}
    nm = lambda s: meta[s][0]
    dv = (c.iloc[-k:] * v.reindex(columns=c.columns).iloc[-k:]).sum().reindex(r.index).fillna(0)   # 기간 합계 거래대금
    rank = dv.rank(ascending=False, method='first')
    rows = pd.DataFrame(dict(sym=r.index, ret=r.values, mc=[float(meta[s][1]) for s in r.index],
                             ind=[sec_of(s) for s in r.index]))
    sectors = []
    for ind, g in rows[rows['ind'].notna()].groupby('ind'):
        if len(g) < min_sec:
            continue
        g = g.sort_values('mc', ascending=False)
        w = g['mc'] / g['mc'].sum()
        sectors.append(dict(name=ind, n=len(g), ret=_r((g['ret'] * w).sum(), 1), lead=nm(g.iloc[0]['sym']),
                            lead_ret=_r(g.iloc[0]['ret'], 1),
                            members=[dict(name=nm(x.sym), sym=x.sym, ret=_r(x.ret, 1)) for x in g.head(20).itertuples()]))
    sectors.sort(key=lambda x: -x['ret'])
    mega = [dict(name=nm(x.sym), sym=x.sym, ret=_r(x.ret, 1), mc=_r(x.mc / mc_div, 0 if mc_div == 1e9 else 1))
            for x in rows.sort_values('mc', ascending=False).head(10).itertuples()]
    hh = h.reindex(columns=c.columns)
    nh = []
    if len(hh) > 60:
        cur, prev = hh.iloc[-k:].max(), hh.iloc[-252 - k:-k].max()
        cnt = hh.iloc[-252 - k:].notna().sum()
        for s in r.index:
            if cur.get(s) == cur.get(s) and prev.get(s) == prev.get(s) and cur[s] >= prev[s] and cnt[s] >= 30:
                nh.append(dict(name=nm(s), sym=s, ret=_r(r[s], 1), young=bool(cnt[s] < 240), _a=float(dv[s])))
        nh.sort(key=lambda x: -x['_a'])
    bg = rows[rows['sym'].isin(big)].sort_values('ret')
    row = lambda x: dict(name=nm(x.sym), sym=x.sym, ret=_r(x.ret, 1))
    hot = [dict(name=nm(s), sym=s, ret=_r(r[s], 1), tag=f"거래대금 {int(rank[s])}위", _a=float(dv[s]))
           for s in r.index if r[s] >= 7 * (1 if k == 1 else 2 if k == 5 else 4)]
    hot.sort(key=lambda x: -x['_a'])
    strip = lambda L: [{a: b for a, b in x.items() if a != '_a'} for x in L]
    return dict(asof=str(c.index[-1].date()), since=str(c.index[-1 - k].date()), k=k, universe=int(len(r)),
                breadth_all=dict(up=int((r > 0).sum()), down=int((r < 0).sum()), flat=int((r == 0).sum())),
                big_n=int(len(bg)), breadth_up=(round(float((bg['ret'] > 0).mean() * 100)) if len(bg) else None),
                sectors=sectors, megacaps=mega, new_high_52w=dict(n=len(nh), universe=int(len(r)), top=strip(nh[:8])),
                featured=strip(hot[:8]), top=[row(x) for x in bg[::-1].head(8).itertuples()],
                bottom=[row(x) for x in bg.head(8).itertuples()],
                turnover_top=[dict(name=nm(s), sym=s, ret=_r(r[s], 1), tag=amt_fmt(dv[s]))
                              for s in dv.sort_values(ascending=False).index[:8]],
                turnover_txt=amt_fmt(float(dv.sum())))


def _clean(c):
    c = c.dropna(how='all')
    if len(c) and c.iloc[-1].notna().mean() < 0.8:      # 마지막 줄이 반쪽(장중·결측)이면 전날까지
        c = c.iloc[:-1]
    return c


def _pack(c, h, v, meta, big, amt_fmt, mc_div, sec_of, n_hist):
    views = {p: _view(c, h.loc[:c.index[-1]], v.loc[:c.index[-1]], meta, k, big, amt_fmt, mc_div, sec_of) for p, k in PERIODS}
    out = dict(views.get('d1') or {})
    if not out:
        return {}
    out['periods'] = {p: views[p] for p in ('w1', 'm1') if views.get(p)}
    bc = c[[s for s in c.columns if s in big]]
    out['breadth_hist'] = _trend(bc, n_hist)
    out['hist_universe'] = int(bc.shape[1])
    return out


def us_internals(top_n=500, n_hist=30):
    """미국 — 유니버스 = perf_latest 미국 전 종목(시총 $3억+, NYSE·나스닥·AMEX ≈ 2,600종). 2026-11-14 확대(옛: 상위 500만).
    시장 폭·업종·신고가·거래대금은 전 종목, 상승·하락 상위·상승 비율 추이는 시총 상위 500(≈ S&P500)."""
    p = _j('results/perf_latest.json')
    us = sorted([s for s in p.get('stocks', []) if s.get('market') == 'US' and s.get('marcap')], key=lambda s: -s['marcap'])
    if len(us) < 100:
        return {}
    sd = (_j('data/sector_detail.json') or {}).get('us') or {}
    d = _dl([s['sym'] for s in us])
    c = _clean(d['Close'])
    if c.empty or len(c) < 60:
        return {}
    meta = {s['sym']: (NAME_KO.get(s['sym'], s['sym']), s['marcap']) for s in us if s['sym'] in c.columns}
    have = [s['sym'] for s in us if s['sym'] in c.columns and c[s['sym']].iloc[-1] == c[s['sym']].iloc[-1]]
    big = set(have[:top_n])                              # 값이 있는 종목으로 정확히 top_n(옛: 결측 1종 → 499)
    ind = lambda s: (lambda x: IND_KO.get(x, x) if x else None)((sd.get(s) or {}).get('industry'))
    fmt = lambda a: f"${a / 1e9:,.1f}B"
    out = _pack(c, d['High'], d['Volume'], meta, big, fmt, 1e9, ind, n_hist)
    if out:
        out['basis'] = 'd1'
    return out


def kr_internals(n_hist=30):
    """한국 — 시총 1,000억+ (≈ 1,200종) 일봉으로 주간·월간 시장 내부 + 대형주(1조+) 상승 비율 추이.
    일간은 네이버 전 종목 시세(market_report.kr_stock_facts)가 정본 — 여기 d1 은 화면에서 쓰지 않는다."""
    import pandas as pd
    try:
        df = pd.read_csv(os.path.join(BASE, 'data', 'krx_listing_last.csv'), dtype={'Code': str})
        df['Marcap'] = pd.to_numeric(df['Marcap'], errors='coerce')
        df = df[(df['Marcap'] >= 1e11) & df['MarketId'].isin(['STK', 'KSQ'])].sort_values('Marcap', ascending=False)
        df['y'] = [f"{c.zfill(6)}.{'KS' if m == 'STK' else 'KQ'}" for c, m in zip(df['Code'], df['MarketId'])]
        d = _dl(df['y'].tolist())
        ren = dict(zip(df['y'], df['Code'].str.zfill(6)))
        c, h, v = (d[k].rename(columns=ren) for k in ('Close', 'High', 'Volume'))
        c = _clean(c)
        if c.empty or len(c) < 30:
            return {}
        meta = {r.Code.zfill(6): (r.Name, r.Marcap) for r in df.itertuples() if r.Code.zfill(6) in c.columns}
        big = {r.Code.zfill(6) for r in df[df['Marcap'] >= 1e12].itertuples()} & set(c.columns)
        smap = _j('data/sectors.json') or {}
        try:
            from market_report import _sec_short
        except Exception:
            _sec_short = lambda x: x
        ind = lambda s: (_sec_short(smap[s]) if smap.get(s) else None)
        fmt = lambda a: (f"{a / 1e12:,.1f}조" if a >= 1e12 else f"{a / 1e8:,.0f}억")
        out = _pack(c, h, v, meta, big, fmt, 1e12, ind, n_hist)
        if out:
            out['basis'] = '시총 1,000억+'
        return out
    except Exception as e:
        print('  한국 시장 내부(주간·월간) 생략:', str(e)[:100])
        return {}
