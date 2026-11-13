# -*- coding: utf-8 -*-
"""시장 내부(폭·업종·신고가·돈이 몰린 종목) — 미국판 + 대형주 상승 비율 추이(한·미). 2026-11-14 신설.

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
    """대형주 상승 비율 — 최근 n거래일. 그날 값이 있는 종목이 80% 미만인 날(휴장·결측)은 뺀다."""
    r = close.pct_change(fill_method=None) * 100
    out = []
    for dt, row in r.iloc[-(n + 5):].iterrows():
        v = row.dropna()
        if len(v) < 0.8 * close.shape[1]:
            continue
        out.append(dict(date=str(dt.date()), up=int((v > 0).sum()), down=int((v < 0).sum()), flat=int((v == 0).sum())))
    return out[-n:]


def kr_trend(n=30):
    """한국 대형주(시총 1조+) 상승 비율 30거래일 — KRX 목록(data/krx_listing_last.csv)의 시장 구분으로 .KS/.KQ."""
    import pandas as pd
    try:
        df = pd.read_csv(os.path.join(BASE, 'data', 'krx_listing_last.csv'), dtype={'Code': str})
        big = df[(pd.to_numeric(df['Marcap'], errors='coerce') >= 1e12) & df['MarketId'].isin(['STK', 'KSQ'])]
        syms = [f"{c.zfill(6)}.{'KS' if m == 'STK' else 'KQ'}" for c, m in zip(big['Code'], big['MarketId'])]
        d = _dl(syms, period='3mo')
        c = d['Close'].dropna(how='all')
        if c.empty:
            return {}
        return dict(universe=c.shape[1], basis='시총 1조+', hist=_trend(c, n))
    except Exception as e:
        print('  한국 상승 비율 추이 생략:', str(e)[:80])
        return {}


def us_internals(top_n=500, n_hist=30):
    """미국 시총 상위 top_n — 시장 폭·업종(시총가중)·신고가·급등(돈이 몰린 순)·시총 상위·상승 비율 추이."""
    import pandas as pd
    p = _j('results/perf_latest.json')
    us = sorted([s for s in p.get('stocks', []) if s.get('market') == 'US' and s.get('marcap')],
                key=lambda s: -s['marcap'])[:top_n]
    if len(us) < 100:
        return {}
    meta = {s['sym']: s for s in us}
    sd = (_j('data/sector_detail.json') or {}).get('us') or {}
    d = _dl([s['sym'] for s in us])
    c, h, v = d['Close'], d['High'], d['Volume']
    if c.empty or len(c) < 60:
        return {}
    c = c.dropna(how='all')
    last = c.index[-1]
    if c.loc[last].notna().mean() < 0.8:           # 마지막 줄이 반쪽(장중·결측)이면 전날까지
        c = c.iloc[:-1]
        last = c.index[-1]
    r1 = (c.iloc[-1] / c.iloc[-2] - 1) * 100
    r1 = r1.dropna()
    nm = lambda s: NAME_KO.get(s, s)
    breadth = dict(up=int((r1 > 0).sum()), down=int((r1 < 0).sum()), flat=int((r1 == 0).sum()),
                   limit_up=None, limit_down=None)
    dv = (c.iloc[-1] * v.reindex(columns=c.columns).loc[last]).dropna()          # 거래대금($)
    rank = dv.rank(ascending=False, method='first')
    # 업종 — Yahoo industry, 3종+ 묶음만, 시총가중
    rows = pd.DataFrame([dict(sym=s, ret=float(r1[s]), mc=float(meta[s]['marcap']),
                              ind=(sd.get(s) or {}).get('industry')) for s in r1.index if s in meta])
    sectors = []
    for ind, g in rows[rows['ind'].notna()].groupby('ind'):
        if len(g) < 3:
            continue
        g = g.sort_values('mc', ascending=False)
        w = g['mc'] / g['mc'].sum()
        sectors.append(dict(name=IND_KO.get(ind, ind), n=len(g), ret=_r((g['ret'] * w).sum(), 1),
                            lead=nm(g.iloc[0]['sym']), lead_ret=_r(g.iloc[0]['ret'], 1),
                            members=[dict(name=nm(x.sym), sym=x.sym, ret=_r(x.ret, 1)) for x in g.itertuples()]))
    sectors.sort(key=lambda x: -x['ret'])
    mega = [dict(name=nm(x.sym), sym=x.sym, ret=_r(x.ret, 1), mc=_r(x.mc / 1e9, 0))
            for x in rows.sort_values('mc', ascending=False).head(10).itertuples()]
    # 52주 신고가 — 오늘 고가 ≥ 직전 252거래일 최고 고가
    nh = []
    hh = h.reindex(columns=c.columns).loc[:last]
    for s in r1.index:
        col = hh[s].dropna()
        if len(col) < 30:
            continue
        prev = col.iloc[-253:-1].max()
        if col.iloc[-1] >= prev:
            nh.append(dict(name=nm(s), sym=s, ret=_r(r1[s], 1), young=len(col) < 250, _a=float(dv.get(s, 0))))
    nh.sort(key=lambda x: -x['_a'])
    # 급등(돈이 몰린 순) — +7% 이상
    hot = [dict(name=nm(s), sym=s, ret=_r(r1[s], 1), tag=f"거래대금 {int(rank[s])}위", _a=float(dv.get(s, 0)))
           for s in r1.index if r1[s] >= 7 and s in rank]
    hot.sort(key=lambda x: -x['_a'])
    tv = [dict(name=nm(s), sym=s, ret=_r(r1[s], 1), amt_b=_r(dv[s] / 1e9, 1)) for s in dv.sort_values(ascending=False).index[:10]]
    strip = lambda L: [{k: v for k, v in x.items() if k != '_a'} for x in L]
    return dict(asof=str(last.date()), universe=int(len(r1)), basis='d1', breadth_all=breadth,
                breadth_up=round(float((r1 > 0).mean() * 100)), sectors=sectors, megacaps=mega,
                new_high_52w=dict(n=len(nh), universe=int(len(r1)), top=strip(nh[:8])),
                featured=strip(hot[:8]), turnover_top=tv, turnover_bn=_r(float(dv.sum()) / 1e9, 0),
                breadth_hist=_trend(c, n_hist))
