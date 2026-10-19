# -*- coding: utf-8 -*-
"""
매크로 두 축 — 돈의 흐름 · 경제 (2026-10-20, 매크로 탭 v2)

  축 1 · 돈의 흐름: 어느 자산으로 돈이 가나(자산군 흐름) · 공급은 늘고 있나(유동성·신용·심리)
  축 2 · 경제:      선행 → 동행 → 물가·금리 순서로 읽는다

화면(dashboard.py)과 계산을 나눈다 — 여기 함수는 Streamlit 을 모르고, 받은 시계열로만 계산한다.
그래서 헤드리스 테스트(tests/test_macro_flow.py)로 판정 규칙을 고정해 둘 수 있다.

판정 기준은 전부 공개 임계값이다. 맞추려는 게 아니라 '무엇을 근거로 경고라 했나'를 보이려는 것.
비중을 바꾸는 확정 규칙은 200일선 하나뿐이다(research/macro_regime_result_2026-10-20.md).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── 축 1 · 자산군 ────────────────────────────────────────────────────
# (이름, Yahoo 심볼, 무엇을 보나). 코스피는 달러로 환산해 다른 자산과 같은 잣대로 본다.
ASSETS = [
    ('미국 주식 (S&P500)', 'SPY', '위험자산의 기준'),
    ('한국 주식 (코스피·$)', '^KS11', '신흥국·반도체 사이클 — 원/달러 환산'),
    ('미국 장기채 (TLT)', 'TLT', '안전자산·금리 하락 베팅'),
    ('달러 인덱스', 'DX-Y.NYB', '강하면 신흥국·원자재에 역풍'),
    ('금', 'GC=F', '실질금리·불안 헤지'),
    ('구리', 'HG=F', '실물 경기'),
    ('원유 (WTI)', 'CL=F', '수요·물가'),
    ('비트코인', 'BTC-USD', '유동성의 신흥 바로미터'),
]
FX_KRW = 'KRW=X'
RISK_ASSETS = {'미국 주식 (S&P500)', '한국 주식 (코스피·$)', '구리', '비트코인'}


def _clean(s: pd.Series | None) -> pd.Series:
    if s is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(s, errors='coerce').dropna()
    idx = pd.to_datetime(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    return s[~s.index.duplicated(keep='last')].sort_index()


def ret_pct(s: pd.Series, n: int) -> float:
    return (float(s.iloc[-1]) / float(s.iloc[-1 - n]) - 1) * 100 if len(s) > n else np.nan


def ma_gap(s: pd.Series, n: int = 200) -> float:
    """종가가 n일 이평에서 몇 % 떨어져 있나. 데이터 부족이면 NaN."""
    if len(s) < n:
        return np.nan
    return (float(s.iloc[-1]) / float(s.tail(n).mean()) - 1) * 100


def asset_table(closes: dict) -> pd.DataFrame:
    """closes: {Yahoo 심볼: 종가 Series}. 코스피는 원/달러로 나눠 달러 기준으로 바꾼다."""
    rows = []
    fx = _clean(closes.get(FX_KRW))
    for name, sym, why in ASSETS:
        s = _clean(closes.get(sym))
        if sym == '^KS11' and len(s) and len(fx):
            f = fx.reindex(s.index.union(fx.index)).ffill().reindex(s.index)
            s = (s / f).dropna()
        if len(s) < 30:
            rows.append({'자산': name, '1주(%)': np.nan, '1개월(%)': np.nan, '3개월(%)': np.nan,
                         '1년(%)': np.nan, '200일선 이격(%)': np.nan, '보는 이유': why, 'asof': None})
            continue
        rows.append({'자산': name, '1주(%)': ret_pct(s, 5), '1개월(%)': ret_pct(s, 21),
                     '3개월(%)': ret_pct(s, 63), '1년(%)': ret_pct(s, 252),
                     '200일선 이격(%)': ma_gap(s), '보는 이유': why, 'asof': s.index[-1]})
    return pd.DataFrame(rows)


def flow_verdict(at: pd.DataFrame) -> dict:
    """돈의 흐름 요약 — 위험자산이 200일선 위에 몇 개, 안전자산은?"""
    g = at.set_index('자산')['200일선 이격(%)']
    known = g.dropna()
    up = int((known > 0).sum())
    risk = [a for a in RISK_ASSETS if a in known.index]
    risk_up = int((known[risk] > 0).sum()) if risk else 0
    if not len(known):
        word = '-'
    elif risk and risk_up >= max(1, round(len(risk) * 0.75)):
        word = '위험자산으로 유입'
    elif risk and risk_up <= len(risk) // 4:
        word = '위험자산에서 이탈'
    else:
        word = '엇갈림'
    return dict(word=word, up=up, n=len(known), risk_up=risk_up, risk_n=len(risk))


# ── FRED 시계열 도우미 ───────────────────────────────────────────────
def to_series(obs) -> pd.Series:
    """fetch_fred() 반환 [(date, value)] → Series."""
    if not obs:
        return pd.Series(dtype=float)
    return pd.Series([v for _, v in obs], index=pd.to_datetime([d for d, _ in obs])).sort_index()


def yoy(s: pd.Series, k: int = 12) -> float:
    return (float(s.iloc[-1]) / float(s.iloc[-1 - k]) - 1) * 100 if len(s) > k and s.iloc[-1 - k] else np.nan


def chg(s: pd.Series, k: int) -> float:
    return float(s.iloc[-1] - s.iloc[-1 - k]) if len(s) > k else np.nan


def net_liquidity(walcl: pd.Series, tga: pd.Series, rrp: pd.Series) -> pd.Series:
    """순유동성(십억 달러) = 연준 총자산(WALCL, 백만) − 재무부 일반계정(WTREGEN, 백만) − 역레포(RRPONTSYD, 십억).
    ⚠️ 단위가 계열마다 다르다(FRED 표기 확인 2026-10-20: WALCL·WTREGEN 은 백만 달러, RRPONTSYD 는 십억 달러).
    WALCL 발표일(수요일) 기준으로 나머지를 그날까지 값으로 맞춘다."""
    if walcl.empty or tga.empty:
        return pd.Series(dtype=float)
    idx = walcl.index
    a = lambda s: s.reindex(s.index.union(idx)).ffill().reindex(idx) if len(s) else pd.Series(0.0, index=idx)
    return (walcl / 1000 - a(tga) / 1000 - a(rrp)).dropna()


# ── 축 2 · 경제 판정 ─────────────────────────────────────────────────
# tone: pos=확장(좋음) · muted=중립 · warn=경고 · neg=위험
def _st(v, warn, mid, higher_is_bad=False):
    """v 가 warn 쪽이면 경고, mid 쪽이면 중립, 아니면 확장."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return '자료없음', 'muted'
    if higher_is_bad:
        return ('경고', 'warn') if v >= warn else (('중립', 'muted') if v >= mid else ('확장', 'pos'))
    return ('경고', 'warn') if v <= warn else (('중립', 'muted') if v <= mid else ('확장', 'pos'))


def econ_rows(S: dict) -> list[dict]:
    """S: {FRED 코드: Series}. 반환 행 = 묶음·이름·값·설명·판정·톤·기준·관측일."""
    R = []

    def add(grp, name, val, fmt, desc, verdict, rule, s):
        st_, tone = verdict
        unit = fmt.rsplit('}', 1)[-1] if '}' in fmt else ''
        num = None if val is None or (isinstance(val, float) and np.isnan(val)) else float(val)
        R.append(dict(num=num, unit=unit, 묶음=grp, 지표=name, 값=('-' if val is None or (isinstance(val, float) and np.isnan(val)) else fmt.format(val)),
                      설명=desc, 판정=st_, tone=tone, 기준=rule,
                      관측일=(s.index[-1].strftime('%Y-%m-%d') if s is not None and len(s) else '-')))

    # ── 선행
    ic = S.get('ICSA', pd.Series(dtype=float))
    if len(ic) >= 30:
        ic4 = ic.rolling(4).mean().dropna()
        lo = ic4.tail(52).min()
        r = (float(ic4.iloc[-1]) / lo - 1) * 100
        add('선행', '신규 실업수당 (4주 평균)', float(ic4.iloc[-1]) / 1000, '{:,.0f}K',
            f'52주 최저 대비 {r:+.1f}%', _st(r, 15, 8, higher_is_bad=True),
            '52주 최저 대비 +15% 이상 경고 · +8% 이상 중립', ic4)
    else:
        add('선행', '신규 실업수당 (4주 평균)', None, '', '', _st(None, 0, 0), '', None)
    t = S.get('T10Y3M', pd.Series(dtype=float))
    add('선행', '장단기 금리차 10Y−3M', float(t.iloc[-1]) if len(t) else None, '{:+.2f}%p',
        '역전(0 미만)은 침체 선행 — 단, 비중 신호로는 검증 탈락', _st(float(t.iloc[-1]) if len(t) else None, 0, 0.5),
        '0 미만 경고 · 0.5 미만 중립', t)
    cf = S.get('CFNAI', pd.Series(dtype=float))
    cf3 = float(cf.tail(3).mean()) if len(cf) >= 3 else None
    add('선행', 'CFNAI 3개월 평균 (ISM 대용)', cf3, '{:+.2f}', '시카고연준 85개 지표 합성 · 0 = 추세 성장',
        _st(cf3, -0.7, 0), '−0.7 이하 경고(침체 기준) · 0 이하 중립', cf)
    no = S.get('NEWORDER', pd.Series(dtype=float))
    v = yoy(no)
    add('선행', '비국방 자본재 신규수주', v, '{:+.1f}%', 'YoY · 기업 설비투자 의향', _st(v, 0, 3), '0% 이하 경고 · 3% 이하 중립', no)
    kx = S.get('XTEXVA01KRM667S', pd.Series(dtype=float))
    v = yoy(kx)
    add('선행', '한국 수출', v, '{:+.1f}%', 'YoY · OECD(달러 기준, 발표 1~2개월 지연)', _st(v, 0, 5), '0% 이하 경고 · 5% 이하 중립', kx)
    gn = S.get('GDPNOW', pd.Series(dtype=float))
    add('선행', 'GDPNow (이번 분기 추정)', float(gn.iloc[-1]) if len(gn) else None, '{:.1f}%', '애틀랜타 연준 실시간 성장률 추정(연율)',
        _st(float(gn.iloc[-1]) if len(gn) else None, 1, 2), '1% 이하 경고 · 2% 이하 중립', gn)
    # ── 동행
    ip = S.get('INDPRO', pd.Series(dtype=float))
    v = yoy(ip)
    add('동행', '산업생산', v, '{:+.1f}%', 'YoY · 실적 사이클 대용', _st(v, -1, 1), '−1% 이하 경고 · 1% 이하 중립', ip)
    pe = S.get('PAYEMS', pd.Series(dtype=float))
    v = float(pe.diff().tail(3).mean()) if len(pe) >= 4 else None
    add('동행', '비농업 고용 (3개월 평균)', v, '{:+,.0f}K', '월 증가 인원', _st(v, 50, 100), '+50K 이하 경고 · +100K 이하 중립', pe)
    ur = S.get('UNRATE', pd.Series(dtype=float))
    if len(ur) >= 15:
        u3 = ur.rolling(3).mean()
        sahm = float(u3.iloc[-1] - u3.iloc[-13:-1].min())
        add('동행', '실업률 · 삼의 법칙', float(ur.iloc[-1]), '{:.1f}%', f'삼 지표 {sahm:+.2f}%p (0.50 발동)',
            _st(sahm, 0.5, 0.3, higher_is_bad=True), '삼 지표 0.50 이상 경고 · 0.30 이상 중립', ur)
    else:
        add('동행', '실업률 · 삼의 법칙', float(ur.iloc[-1]) if len(ur) else None, '{:.1f}%', '', _st(None, 0, 0), '', ur)
    # ── 물가·금리
    pc = S.get('PCEPILFE', pd.Series(dtype=float))
    v = yoy(pc)
    add('물가·금리', '근원 PCE', v, '{:.1f}%', 'YoY · 연준 목표 2%', _st(v, 3, 2.5, higher_is_bad=True), '3% 이상 경고 · 2.5% 이상 중립', pc)
    cp = S.get('CPIAUCSL', pd.Series(dtype=float))
    v = yoy(cp)
    add('물가·금리', 'CPI', v, '{:.1f}%', 'YoY', _st(v, 3.5, 2.5, higher_is_bad=True), '3.5% 이상 경고 · 2.5% 이상 중립', cp)
    ff = S.get('FEDFUNDS', pd.Series(dtype=float))
    c6 = chg(ff, 6)
    if c6 is None or np.isnan(c6):
        vd = ('자료없음', 'muted')
    else:
        vd = ('인하 중', 'pos') if c6 <= -0.25 else (('인상 중', 'warn') if c6 >= 0.25 else ('동결', 'muted'))
    add('물가·금리', '기준금리 (Fed)', float(ff.iloc[-1]) if len(ff) else None, '{:.2f}%',
        f'6개월 {c6:+.2f}%p' if c6 == c6 else '', vd, '6개월 ±0.25%p 기준 방향', ff)
    d10 = S.get('DGS10', pd.Series(dtype=float))
    c3 = chg(d10, 63)
    if c3 != c3:
        vd = ('자료없음', 'muted')
    elif c3 >= 0.5:
        vd = ('급등', 'warn')
    elif c3 >= 0:
        vd = ('상승', 'muted')
    else:
        vd = ('하락', 'pos')
    add('물가·금리', '미국 10년물', float(d10.iloc[-1]) if len(d10) else None, '{:.2f}%',
        f'3개월 {c3:+.2f}%p' if c3 == c3 else '', vd, '3개월 +0.5%p 이상 급등', d10)
    return R


def group_summary(rows: list[dict], grp: str) -> tuple[str, str]:
    g = [r for r in rows if r['묶음'] == grp and r['판정'] != '자료없음']
    w = sum(r['tone'] in ('warn', 'neg') for r in g)
    if not g:
        return '자료없음', 'muted'
    if grp == '선행':
        return f'경고 {w} / {len(g)}', ('warn' if w >= 2 else 'accent')
    return ('주의' if w else '양호'), ('warn' if w else 'accent')


def econ_verdict(rows: list[dict]) -> tuple[str, str]:
    """경기 한 줄 — 동행이 좋고 선행 경고가 적으면 확장."""
    lead = [r for r in rows if r['묶음'] == '선행' and r['판정'] != '자료없음']
    coin = [r for r in rows if r['묶음'] == '동행' and r['판정'] != '자료없음']
    lw = sum(r['tone'] == 'warn' for r in lead)
    cw = sum(r['tone'] == 'warn' for r in coin)
    if not lead and not coin:
        return '-', '자료 없음'
    if cw >= 2:
        word = '둔화'
    elif lw >= 3:
        word = '확장 · 꺾일 조짐'
    elif lw >= 1 or cw == 1:
        word = '확장 · 일부 경고'
    else:
        word = '확장'
    return word, f'선행 {len(lead)}개 중 {lw}개 · 동행 {len(coin)}개 중 {cw}개 경고'


# ── 욕심 조절 (검증 결과 · 2026-10-20) ────────────────────────────────
# 숫자는 research/macro_regime_bt.py 1988-01~2026-09 달러 기준, 200일선 위에 덧씌운 결과.
RULES = [
    # 키, 신호, CAGR, MDD, Calmar, 판정, 쓰는 법
    ('B0', 'S&P500 매수보유 (기준)', 11.65, -54.7, 0.213, '기준', '—'),
    ('B1', '200일선 스위치', 8.89, -29.5, 0.302, '확정 규칙', '코어: 위면 보유, 아래면 현금'),
    ('C1', '신용 스프레드 13주 +0.30%p 확대', 8.82, -23.4, 0.377, '참고', '주변값 2/4 탈락 · 비중 미사용'),
    ('C6', '우라가미 역금융·역실적 국면', 8.53, -26.9, 0.318, '참고', '200일선과 겹침 · 비중 미사용'),
    ('C8', '강달러 (DXY 200일선 위 + 13주 상승)', 8.01, -18.0, 0.444, '보류', '2004년 이후·원화 기준 역효과'),
    ('C5', '10Y−3M 역전', 8.69, -22.5, 0.386, '기각', '기준값만 통과, 주변값 1/3'),
    ('C3', '실업수당 추세 상승', 8.43, -26.4, 0.320, '기각', '2020~26 구간 CAGR −1.7%p'),
    ('C2', 'NFCI > 0 (금융여건 긴축)', 8.58, -29.3, 0.292, '기각', '200일선보다 못함'),
    ('C7', '막스 시계추 탐욕 ≥ 80', 8.16, -29.5, 0.277, '기각', '탐욕은 매도 신호가 아니다'),
]


def greed_signals(core_on: bool | None, c1: float | None, phase: str | None, dxy_gap: float | None, dxy_13w: float | None) -> dict:
    """지금 상태. core_on 만 비중을 정한다. 나머지는 참고 경고."""
    ref = {
        'C1': None if c1 is None or c1 != c1 else bool(c1 >= 0.30),
        'C6': None if not phase else phase in ('RFIN', 'RERN'),
        'C8': None if dxy_gap is None or dxy_gap != dxy_gap or dxy_13w is None or dxy_13w != dxy_13w else bool(dxy_gap > 0 and dxy_13w > 0),
    }
    n = sum(1 for v in ref.values() if v)
    if core_on is None:
        word, tone = '판정 불가', 'muted'
    elif not core_on:
        word, tone = '줄여라', 'neg'
    elif n >= 2:
        word, tone = '평소대로 · 주의', 'warn'
    else:
        word, tone = '평소대로', 'pos'
    return dict(word=word, tone=tone, ref=ref, n=n)


# ── 국가별 주식시장 시총 (세계은행 연말 값 × 그 뒤 대표 지수 변동) ─────────────
# 지수 이름 → (세계은행 국가코드, 그 나라 대표 지수 이름). 같은 나라 지수는 같은 시총을 보인다.
INDEX_COUNTRY = {
    'S&P500': ('USA', 'S&P500'), '나스닥': ('USA', 'S&P500'), '다우': ('USA', 'S&P500'), '러셀2000': ('USA', 'S&P500'),
    '코스피': ('KOR', '코스피'), '코스닥': ('KOR', '코스피'), '닛케이225': ('JPN', '닛케이225'),
    '대만 가권': ('TWN', '대만 가권'), '항셍': ('HKG', '항셍'), '상해종합': ('CHN', '상해종합'),
    '니프티50': ('IND', '니프티50'), 'DAX': ('DEU', 'DAX'), '유로스톡스50': ('EMU', '유로스톡스50'),
    'FTSE100': ('GBR', 'FTSE100'), '보베스파': ('BRA', '보베스파'),
}


def country_mcap(base: dict, closes_by_name: dict) -> dict:
    """{지수 이름: (조 달러 추정, 기준 연도, 추정 여부)}.
    base: data/world_mcap.json. 연말 값에 '연말 → 오늘' 대표 지수 변동률을 곱한다(현지 통화 지수 — 환율 변동은 미반영).
    연말 종가를 못 찾으면 작년 값까지만 그대로 쓰고, 그보다 오래됐으면 뺀다."""
    out = {}
    for name, (cc, ref) in INDEX_COUNTRY.items():
        b = (base or {}).get(cc)
        if not b or not b.get('usd'):
            continue
        v, y, est = b['usd'] / 1e12, int(b['year']), False
        s = _clean(closes_by_name.get(ref))
        if len(s):
            ye = s[s.index <= pd.Timestamp(y, 12, 31)]
            if len(ye) and (pd.Timestamp(y, 12, 31) - ye.index[-1]).days <= 10:
                v = v * float(s.iloc[-1]) / float(ye.iloc[-1])
                est = True
        if not est and y < pd.Timestamp.now().year - 1:
            continue        # 오래된 연말 값을 오늘 값처럼 보이지 않는다(영국 2022·유로존 2018 등) → '-'
        out[name] = (v, y, est)
    return out
