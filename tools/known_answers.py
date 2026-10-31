# -*- coding: utf-8 -*-
"""
정답 점검 (known answers) — 2026-10-19

왜: 행 수·파일 날짜만 보는 감시는 '구멍 난 정상'을 못 잡았다.
  · 미국 시총 3,577행이 '정상'이었는데 S~Z 로 시작하는 1,300종이 0개였다(TSLA·V·WMT 부재).
  · 주도주 신호 파일은 매주 갱신됐는데 NVDA·PLTR·AXTI 의 시총이 2018년부터 NULL 이었다.
  · 컨센서스 스냅샷은 석 달 동안 매주 '✅ 저장: 0종목'으로 초록불이었다.
  셋 다 **답을 아는 질문 하나**("TSLA 가 있는가?" "NVDA 는 신호가 있었는가?")로 즉시 잡혔다.

무엇: 화면이 쓰는 산출물마다 '이건 반드시 참이어야 한다'는 사실을 코드로 박는다.
  저장소에 커밋된 파일만 읽는다(DB 불필요) → 어느 러너에서도, 로컬에서도 돈다.

출력: results/known_answers.json (화면 '데이터 신선도'에 표시) + 실패마다 ::error
  --strict 이면 하나라도 실패 시 exit 1 (잡을 빨간불로 → 텔레그램 실패 알림).

규칙: 기준을 바꿀 때는 **왜 그 숫자인지** 주석으로 남긴다. 실패를 끄려고 기준을 낮추지 말 것 —
  먼저 데이터가 맞는지 확인한다. 정말 세상이 바뀐 거면(상장폐지 등) 파수꾼을 교체한다.
"""
import json
import os
import sys
from datetime import date, datetime

import pandas as pd

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, 'results', 'known_answers.json')
TODAY = date.today()

# 미국 초대형 파수꾼 — 시총 상위·업종 분산·티커 첫 글자 분산(A~X). 어느 하나라도 빠지면 유니버스 결손이다.
US_BIG = ['AAPL', 'MSFT', 'NVDA', 'AMZN', 'GOOGL', 'META', 'AVGO', 'TSLA', 'JPM', 'V', 'WMT', 'XOM',
          'MA', 'ORCL', 'COST', 'NFLX', 'AMD', 'PLTR', 'UBER', 'LLY', 'CMCSA']
# 한국 파수꾼 — 코스피 대형 + 코스닥 대형
KR_BIG = ['005930', '000660', '373220', '207940', '005380', '035420', '068270', '247540']
# 주도주 이력 파수꾼 — 2018~ 실제로 이익가속+급등 신호가 있었던 시대의 주도주(2026-09 정상 결과 기준).
#   최솟값은 9월 정상치의 약 70% — 규칙을 바꾸면 줄 수 있지만 0 이 되면 데이터 고장이다.
ACCEL_HIST = {'TSLA': 15, 'NVDA': 9, 'PLTR': 7, 'MU': 15, 'AXTI': 10, 'BE': 11}


def _j(rel):
    with open(os.path.join(BASE, rel), encoding='utf-8') as f:
        return json.load(f)


def _age(s):
    try:
        return (TODAY - pd.Timestamp(str(s)[:10]).date()).days
    except Exception:
        return 9999


def _stocks(rel):
    d = _j(rel)
    return d, {x['sym']: x for x in d.get('stocks', [])}


CHECKS = []


def check(area, question):
    def deco(fn):
        CHECKS.append((area, question, fn))
        return fn
    return deco


# ───────────────────────── 미국 유니버스 ─────────────────────────
@check('미국 유니버스', '초대형주 21종이 시총 파일에 다 있는가')
def _():
    m = pd.read_csv(os.path.join(BASE, 'data/us_marketcap.csv'))
    lost = [s for s in US_BIG if s not in set(m.Symbol.astype(str))]
    return not lost, f"{len(m):,}종 · 누락 {lost or '없음'}"


@check('미국 유니버스', '애플 시총이 1조~10조 달러 사이인가 (단위·주식수 오류 감지)')
def _():
    m = pd.read_csv(os.path.join(BASE, 'data/us_marketcap.csv'))
    v = m.loc[m.Symbol == 'AAPL', 'marketcap']
    x = float(v.iloc[0]) if len(v) else None
    return bool(x and 1e12 <= x <= 1e13), f"AAPL ${x/1e12:.2f}T" if x else 'AAPL 없음'


@check('미국 유니버스', '복수 종류주식·복수 티커 회사의 시총이 제 자리에 있는가 (BRK·CMCSA·GOOGL)')
def _():
    # 2026-10-19 — 같은 회사 티커 중 '짧은 것'을 고르던 규칙 때문에 Comcast 가 CCZ(교환사채)로 들어가
    #   $225B 로 잡히고 CMCSA 는 사라졌다. 대표 티커와 그 규모가 맞는지 본다.
    m = pd.read_csv(os.path.join(BASE, 'data/us_marketcap.csv')).set_index('Symbol').marketcap
    want = {'BRK-A': (4e11, 2.5e12), 'CMCSA': (4e10, 3e11), 'GOOGL': (1e12, 1e13)}
    bad = {k: (round(m[k] / 1e9) if k in m else None) for k, (lo, hi) in want.items()
           if not (k in m and lo <= m[k] <= hi)}
    stray = [t for t in ('CCZ', 'GOOG', 'BRK-B') if t in m]     # 대표가 아닌 티커가 남아 있으면 이중 계상
    return not bad and not stray, f"범위 밖 {bad or '없음'} · 대표 아닌 티커 {stray or '없음'}"


@check('미국 유니버스', '티커 첫 글자 A~W 가 고르게 있는가 (순서 편향 결손 감지)')
def _():
    m = pd.read_csv(os.path.join(BASE, 'data/us_marketcap.csv'))
    lead = m.Symbol.astype(str).str[0].value_counts()
    thin = [c for c in 'ABCDEFGHIJKLMNOPRSTUVW' if lead.get(c, 0) < 5]
    return not thin, f"5종 미만인 글자: {''.join(thin) or '없음'}"


@check('미국 유니버스', 'SEC 주식수가 5,000종 이상이고 애플이 100억~200억주인가')
def _():
    s = pd.read_csv(os.path.join(BASE, 'data/us_shares.csv'), usecols=['sym', 'filed', 'shares'])
    n = s.sym.nunique()
    a = s[s.sym == 'AAPL'].sort_values('filed').shares
    x = float(a.iloc[-1]) if len(a) else None
    return n >= 5000 and bool(x and 1e10 <= x <= 2e10), f"{n:,}종 · AAPL {x/1e9:.1f}B주" if x else f"{n:,}종 · AAPL 없음"


# ───────────────────────── 한국 유니버스 ─────────────────────────
@check('한국 유니버스', '상장목록 2,500종 이상 · 삼성전자 시총 100조~3,000조원')
def _():
    k = pd.read_csv(os.path.join(BASE, 'data/krx_listing_last.csv'), dtype={'Code': str})
    v = k.loc[k.Code == '005930', 'Marcap']
    x = float(v.iloc[0]) if len(v) else None
    return len(k) >= 2500 and bool(x and 1e14 <= x <= 3e15), f"{len(k):,}종 · 삼성 {x/1e12:,.0f}조" if x else f"{len(k):,}종 · 삼성 없음"


@check('한국 유니버스', '업종 분류가 2,000종 이상이고 대형 8종이 다 있는가')
def _():
    s = _j('data/sectors.json')
    lost = [x for x in KR_BIG if x not in s]
    return len(s) >= 2000 and not lost, f"{len(s):,}종 · 누락 {lost or '없음'}"


# ───────────────────────── 한국 재무 ─────────────────────────
def _q_due():
    """오늘 기준 '공시가 이미 나왔어야 하는' 최신 분기.
    분기·반기보고서 마감은 분기말 + 45일, 사업보고서(4분기)는 + 90일. 수집 주기(주 1회)를 감안해 +30일 여유."""
    y, q = TODAY.year, (TODAY.month - 1) // 3 + 1
    for _ in range(8):
        q -= 1
        if q == 0:
            y, q = y - 1, 4
        qend = pd.Timestamp(year=y, month=q * 3, day=1) + pd.offsets.MonthEnd(0)
        if (qend + pd.Timedelta(days=120 if q == 4 else 75)).date() <= TODAY:
            return y, q
    return y, q


@check('한국 재무', '삼성전자 최신 분기가 공시 마감 분기까지 들어와 있고 매출이 50조~250조원인가')
def _():
    q = pd.read_parquet(os.path.join(BASE, 'data/kr_fundamentals_q.parquet'))
    s = q[q.sym == '005930'].sort_values(['year', 'q'])
    if s.empty:
        return False, '삼성 없음'
    last = s.iloc[-1]
    y, qq = _q_due()
    rev = last.revenue if last.q != 4 else None        # q=4 는 연간 합계 저장 규칙이라 범위 판정 제외
    ok_q = (last.year, last.q) >= (y, qq)
    ok_r = rev is None or 5e13 <= rev <= 2.5e14
    return ok_q and ok_r, f"최신 {int(last.year)}Q{int(last.q)} (기대 ≥{y}Q{qq}) · 매출 {last.revenue/1e12:,.1f}조"


@check('한국 재무', '재무가 있는 종목의 70% 이상이 공시 마감 분기까지 갱신됐는가')
def _():
    q = pd.read_parquet(os.path.join(BASE, 'data/kr_fundamentals_q.parquet'), columns=['sym', 'year', 'q'])
    last = (q.year * 10 + q.q).groupby(q.sym).max()
    y, qq = _q_due()
    r = (last >= y * 10 + qq).mean()
    return r >= 0.7, f"{r:.0%} ({len(last):,}종 중) · 기준 {y}Q{qq}"


@check('한국 재무', '아직 끝나지 않은 미래 분기가 없는가 (사업연도·달력 분기 혼동 감지)')
def _():
    # 2026-10-19 — 12월 결산이 아닌 회사(3월·11월·리츠)가 사업연도 분기로 저장돼 10월에 '2026Q4'가 있었다.
    q = pd.read_parquet(os.path.join(BASE, 'data/kr_fundamentals_q.parquet'), columns=['sym', 'year', 'q'])
    cur = TODAY.year * 10 + (TODAY.month - 1) // 3 + 1
    f = q[(q.year * 10 + q.q) >= cur]
    return f.empty, f"미래·진행 중 분기 {len(f)}행 · {f.sym.nunique()}종 {sorted(f.sym.unique())[:6]}"


@check('한국 재무', '가치 스냅샷에 삼성·하이닉스 PER·PBR 이 양수로 있는가')
def _():
    _, s = _stocks('results/value_kr.json')
    bad = [x for x in ('005930', '000660') if not (s.get(x) and (s[x].get('pbr') or 0) > 0 and (s[x].get('per') or 0) > 0)]
    return not bad, f"{len(s)}종 · 문제 {bad or '없음'}"


@check('한국 잠재 희석', 'CB·BW·EB 저장본이 있으면: 100종 이상이고 전환가·청구기간이 80% 이상 채워졌으며 미래 결정일이 없는가')
def _():
    # 2026-10-21 신설. 한국은 CB·BW 발행 결정이 해마다 수백 건이라 4년 창에 100종 미만이면 수집 결손이다.
    #   파일이 없을 수 있다(DART 가 해외 러너를 막는 주) — 그때는 화면이 실시간 조회만 쓴다고 적고 통과.
    p = os.path.join(BASE, 'data/kr_dilution.parquet')
    if not os.path.exists(p):
        return True, '저장본 없음(첫 생성 전 또는 DART 미접속) — 화면은 실시간 조회만'
    d = pd.read_parquet(p)
    n = d['sym'].nunique()
    fill_p = d['price'].gt(0).mean()
    fill_e = d['end'].notna().mean()
    fut = (pd.to_datetime(d['decided'], errors='coerce') > pd.Timestamp(TODAY)).sum()
    ok = n >= 100 and fill_p >= 0.8 and fill_e >= 0.8 and fut == 0 and set(d['kind']) <= {'CB', 'BW', 'EB'}
    return ok, f"{len(d):,}건 · {n}종 · 전환가 {fill_p:.0%} · 청구기간 {fill_e:.0%} · 미래 결정일 {fut}"


# ───────────────────────── 화면 공용 산출물 ─────────────────────────
for _rel, _lab in [('results/returns.json', '기간 수익률'), ('results/mdd.json', '고점대비 낙폭'),
                   ('results/seasonality.json', '계절성'), ('results/perf_latest.json', '월간 성과')]:
    @check(_lab, f'{_lab}: 한·미 대형 파수꾼이 다 있고 양 시장 모두 300종 이상인가')
    def _(_rel=_rel):
        d, s = _stocks(_rel)
        lost = [x for x in US_BIG[:12] + KR_BIG[:4] if x not in s]
        mk = pd.Series([x.get('market') for x in d['stocks']]).value_counts()
        ok = not lost and mk.get('US', 0) >= 300 and mk.get('KR', 0) >= 300
        return ok, f"US {mk.get('US', 0):,} · KR {mk.get('KR', 0):,} · 누락 {lost or '없음'}"


# ───────────────────────── 커버율 (2026-10-19 사용자 결정: 한국 1,000억+ · 미국 $3억+) ─────────────────────────
def _cover_targets():
    """커버 기준 명단 — universe.kr_cover/us_cover 와 같은 규칙을 커밋된 파일로 재현(네트워크 없이)."""
    k = pd.read_csv(os.path.join(BASE, 'data/krx_listing_last.csv'), dtype={'Code': str})
    k = k[(k.Marcap >= 1e11) & k.Code.str.fullmatch(r'\d{5}0') & (k.get('Market', '') != 'KONEX')]
    m = pd.read_csv(os.path.join(BASE, 'data/us_marketcap.csv'))
    m = m[(m.country == 'United States') & (m.marketcap >= 3e8)]
    m = m[m.Symbol.astype(str).str.replace('-', '').str.isalpha() & (m.Symbol.astype(str).str.len() <= 5)]
    return set(k.Code), set(m.Symbol.astype(str))


for _rel, _lab in [('results/returns.json', '기간 수익률'), ('results/mdd.json', '고점대비 낙폭'),
                   ('results/seasonality.json', '계절성'), ('results/perf_latest.json', '월간 성과')]:
    @check(_lab, f'{_lab}: 커버 기준(한국 1,000억+ · 미국 $3억+)의 95% 이상을 담고 있는가')
    def _(_rel=_rel):
        kr, us = _cover_targets()
        if 'seasonality' in _rel:
            # 계절성은 월간 수익률 24개(약 2년) 이상이어야 계산된다 — 분모를 이력 2년+ 종목으로(신규 상장 제외)
            _, md = _stocks('results/mdd.json')
            old = {k for k, v in md.items() if (v.get('years') or 0) >= 2.1}
            kr, us = kr & old, us & old
        _, s = _stocks(_rel)
        ck, cu = len(kr & set(s)) / max(len(kr), 1), len(us & set(s)) / max(len(us), 1)
        # 신규 상장·거래정지·시세 실패로 몇 %는 빠질 수 있다 — 95% 아래면 명단 자체가 좁아진 것이다
        return ck >= 0.95 and cu >= 0.95, f"한국 {ck:.0%} ({len(kr):,}종 중) · 미국 {cu:.0%} ({len(us):,}종 중)"


@check('고점대비 낙폭', '낙폭 값이 전부 0 이하인가 (부호 오류 감지)')
def _():
    d, _ = _stocks('results/mdd.json')
    bad = [x['sym'] for x in d['stocks'] if any((x.get(k) or 0) > 0.01 for k in ('mdd_all', 'mdd_1y', 'cur_dd'))]
    return not bad, f"양수 {len(bad)}종 {bad[:5]}"


@check('기간 수익률', '삼성전자 12개월 수익률이 상장목록 종가와 맞물리는가 (가격 시계열 정합)')
def _():
    _, s = _stocks('results/returns.json')
    k = pd.read_csv(os.path.join(BASE, 'data/krx_listing_last.csv'), dtype={'Code': str})
    r = s.get('005930', {}).get('ret_12m')
    mc_r = s.get('005930', {}).get('marcap')
    mc_k = k.loc[k.Code == '005930', 'Marcap']
    # 두 파일의 시총이 10% 안에서 맞으면 같은 날 가격 기준이다. 12M 수익률은 -90%~+1000% 범위.
    same = len(mc_k) and mc_r and abs(mc_r / float(mc_k.iloc[0]) - 1) < 0.10
    return bool(r is not None and -90 < r < 1000 and same), f"12M {r}% · 시총 일치 {bool(same)}"


@check('52주 신고가', '주간 신고가 이력(nh)이 월간 성과 종목의 90% 이상에 실려 있는가')
def _():
    # 2026-10-19 — 주간 그래프·연속 경신 필터의 재료. 비면 그래프가 0 으로 '조용히' 보인다.
    d, _ = _stocks('results/perf_latest.json')
    st_ = d.get('stocks', [])
    r = sum(1 for x in st_ if 'nh' in x) / max(len(st_), 1)
    n_now = sum(1 for x in st_ if x.get('new_high'))
    n_str = sum(1 for x in st_ if (x.get('nh_streak') or 0) >= 1)
    # '이번 주 경신'과 '연속 ≥ 1' 은 같은 정의라 수가 같아야 한다
    return r >= 0.9 and n_now == n_str, f"이력 보유 {r:.0%} · 이번 주 경신 {n_now} · 연속≥1 {n_str}"


@check('흑자전환', '한국 100종·미국 50종 이상 판정했는가')
def _():
    d = _j('results/turnaround_latest.json')
    return d.get('kr', 0) >= 100 and d.get('us', 0) >= 50, f"KR {d.get('kr')} · US {d.get('us')}"


@check('공통 재무', '한국 1,000종 이상 · 삼성전자 TTM 순이익이 양수인가')
def _():
    d = _j('results/fund_snapshot.json')
    sam = (d.get('stocks') or {}).get('005930') or {}
    return (d.get('n_kr') or 0) >= 1000 and (sam.get('ttm_ni') or 0) > 0, \
        f"KR {d.get('n_kr')} · US {d.get('n_us')} · 삼성 TTM 순이익 {sam.get('ttm_ni')}"


@check('CANSLIM', '미국 50종·한국 20종 이상 채점했는가')
def _():
    u = len(_j('results/canslim_us_latest.json').get('stocks', []))
    k = len(_j('results/canslim_latest.json').get('stocks', []))
    return u >= 50 and k >= 20, f"US {u} · KR {k}"


# ───────────────────────── 주도주 (이익 가속) ─────────────────────────
@check('주도주', '유니버스 2,000종 이상 · 최근 26주 내내 최대치의 90% 이상인가')
def _():
    d = _j('results/leaders_accel.json')
    f = d.get('funnel') or {}
    us = [v.get('universe', 0) for k, v in sorted(f.items())[-26:]]
    ok = d.get('universe', 0) >= 2000 and us and min(us) >= 0.9 * max(us)
    return bool(ok), f"현재 {d.get('universe')} · 26주 최저 {min(us) if us else '-'}"


@check('주도주', '최신 주 유동성 조건 통과가 1,500종 이상인가 (시총 결측 감지)')
def _():
    f = _j('results/leaders_accel.json').get('funnel') or {}
    k = max(f) if f else None
    n = f[k].get('liquid', 0) if k else 0
    return n >= 1500, f"{k}: {n:,}종"


@check('주도주', '시대의 주도주(TSLA·NVDA·PLTR·MU·AXTI·BE)가 과거 신호에 잡혀 있는가')
def _():
    w = _j('results/leaders_accel.json').get('weeks') or {}
    cnt = {s: 0 for s in ACCEL_HIST}
    first = {}
    for k in sorted(w):
        for r in w[k]:
            if r['sym'] in cnt:
                cnt[r['sym']] += 1
                first.setdefault(r['sym'], k)
    short = {s: cnt[s] for s, need in ACCEL_HIST.items() if cnt[s] < need}
    tsla_ok = first.get('TSLA', '9999') <= '2019-12-31'       # 2019Q3 흑자전환 서프라이즈 주를 잡아야 한다
    return not short and tsla_ok, f"신호 수 {cnt} · TSLA 첫 신호 {first.get('TSLA', '없음')}"


# 2026-10-23: 9일 → 14일. 주간 산출물(weekly-accel, 토 07:17 KST)은 signal_week=그 주 월요일이라
#   정상 운영에서도 다음 실행 직전 나이가 12~13일 → 매주 수~금 daily-refresh 가 빨간불(오경보, 10-22).
@check('주도주', '신호 주차가 14일 이내인가 (주간 갱신 + 예비 실행 여유)')
def _():
    d = _j('results/leaders_accel.json')
    return _age(d.get('signal_week')) <= 14, f"signal_week {d.get('signal_week')}"


@check('가격 곡선', 'TSLA·NVDA·AAPL 곡선이 있고 마지막 날짜가 14일 이내인가 (주간 갱신)')
def _():
    d = _j('results/price_curves.json')
    lost = [s for s in ('TSLA', 'NVDA', 'AAPL') if s not in d.get('curves', {})]
    last = (d.get('dates') or [None])[-1]
    return not lost and _age(last) <= 14, f"{len(d.get('curves', {})):,}종 · 마지막 {last} · 누락 {lost or '없음'}"


# ───────────────────────── 이번 주 판정 ─────────────────────────
@check('이번 주 판정', 'FRED 경제지표가 들어왔는가 (축 2 경기·국면 판정의 원자료 — 2026-10-22 fred_ok=False 로 조용히 비어 있었음)')
def _():
    d = _j('results/macro.json')
    err = d.get('fred_err') or {}
    return bool(d.get('fred_ok')), f"fred_ok {d.get('fred_ok')} · 경기 {(d.get('econ') or {}).get('word')} · 사유 {next(iter(err.values()), '기록 없음(구버전 산출물)')}"


@check('이번 주 판정', 'SPY 가 200일선 대비 ±40% 안이고, ON/OFF 가 이격 부호와 맞고, 목표 비중 합이 100인가')
def _():
    d = _j('results/macro.json')
    c, a = d.get('core') or {}, d.get('alloc') or {}
    if not c:
        return False, 'core 없음'
    gap = c.get('gap') or 0
    tot = (a.get('core_now') or 0) + (a.get('satellite') or 0) + (a.get('cash_total') or 0)
    ok = abs(gap) < 40 and (gap > 0) == bool(c.get('on')) and tot == 100 and _age(d.get('asof')) <= 5
    return ok, f"{d.get('asof')} {'ON' if c.get('on') else 'OFF'} {gap:+.1f}% · 비중합 {tot}"


# ───────────────────────── 시황·컨센서스 ─────────────────────────
@check('시황 리포트', '일간 리포트가 4일 이내인가')
def _():
    d = _j('results/market_report.json')
    t = (d.get('latest_daily') or {}).get('date')
    return _age(t) <= 4, f"latest_daily {t}"


@check('AI 생성물', '시황 리포트·신고가 요약이 최근 2일 안에 실제 AI 로 만들어졌는가 (키 누락 감지)')
def _():
    # 2026-10-20 — GitHub Actions 에 GEMINI_KEY 가 없어 시황 리포트가 10-14 부터 '숫자 템플릿'으로만 나갔고,
    #   신고가 AI 요약은 한 번도 만들어지지 않았다. 경고(WARN)만 떠서 일주일간 아무도 몰랐다.
    rep = _j('results/market_report.json')
    recent = [h for h in rep.get('history', []) if _age(h.get('date')) <= 2]
    rep_ok = any(str(h.get('engine', '')).startswith('gemini') for h in recent)
    try:
        nh = _j('results/new_high_ai.json')
    except Exception:
        nh = {}
    nh_ok = any(_age(str(v.get('generated', ''))[:10]) <= 2 for v in (nh.get('weeks') or {}).values())
    return rep_ok and nh_ok, (f"시황 리포트 AI {'✅' if rep_ok else '❌(최근 2일 템플릿만)'} · "
                              f"신고가 요약 {'✅' if nh_ok else '❌(최근 2일 생성 없음)'} — ❌면 GitHub Secrets 의 GEMINI_KEY 확인")


@check('KR 컨센서스', '최신 스냅샷이 10일 이내이고 삼성전자가 들어 있는가')
def _():
    rows = []
    with open(os.path.join(BASE, 'results/consensus_history.jsonl'), encoding='utf-8') as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except Exception:
                pass
    last = max((r.get('date', '') for r in rows), default=None)
    has = any(r.get('date') == last and r.get('sym') == '005930' for r in rows)
    return _age(last) <= 10 and has, f"최신 {last} · 그날 {sum(1 for r in rows if r.get('date') == last)}종 · 삼성 {has}"



@check('실적 이벤트', 'PEAD 검증용 실적 이벤트가 전 종목(2,000종+)으로 만들어져 있는가 — 옛 1,249종(시총 사후 선택) 재발 방지')
def _():
    d = _j('results/earnings_event_summary.json')
    n = d.get('syms') or 0
    return n >= 2000, f"{n:,}종 · {d.get('rows', 0):,}행 · {d.get('period')} · 기준 {d.get('factor_ver')}"


@check('CANSLIM US', 'C·A 가 일회성 제외 기준(영업이익)으로 계산돼 있는가 — 전 종목에 기준 표기(2026-10-20)')
def _():
    st = list(_stocks('results/canslim_us_latest.json')[1].values())
    nob = [x['sym'] for x in st if not x.get('earn_basis')]
    one = sum(1 for x in st if x.get('oneoff'))
    return bool(st) and not nob, f"{len(st)}종 · 기준 표기 없음 {len(nob)}종 · 일회성 의심 {one}종"

@check('스윙 정류장', '전 종목 스윙 표본이 충분한가 (미국 하락 5만+·한국 2만+, 변동성 경계 오름차순)')
def _():
    import json as _j
    d = _j.load(open(os.path.join(BASE, 'results/swing_stations.json'), encoding='utf-8'))['markets']
    us, kr = d['US']['buckets']['all']['n_dec'], d['KR']['buckets']['all']['n_dec']
    cuts_ok = all(m['cut'][0] < m['cut'][1] for m in d.values())
    return us > 50000 and kr > 20000 and cuts_ok, f"미국 하락 {us:,} · 한국 {kr:,} · 경계 {[d[m]['cut'] for m in d]}"


@check('세부 업종', '네이버 테마가 살아 있는가 (테마 150+ · 한미반도체·주성엔지니어링이 반도체 장비 · NVDA 반도체)')
def _():
    import json as _j
    d = _j.load(open(os.path.join(BASE, 'data/sector_detail.json'), encoding='utf-8'))
    kr, us = d.get('kr') or {}, d.get('us') or {}
    eq = all('반도체 장비' in ((kr.get(c) or {}).get('themes') or []) for c in ('042700', '036930'))
    nv = 'Semiconductor' in str((us.get('NVDA') or {}).get('industry'))
    n_us = sum(1 for v in us.values() if v)
    return len(d.get('themes') or {}) >= 150 and eq and nv and n_us >= 1500, \
        f"테마 {len(d.get('themes') or {})} · KR {len(kr):,} · US {n_us:,} · 장비 {eq} · NVDA {(us.get('NVDA') or {}).get('industry')}"


def run():
    out = []
    for area, q, fn in CHECKS:
        try:
            ok, detail = fn()
        except Exception as e:
            ok, detail = False, f"점검 자체 실패: {type(e).__name__}: {e}"[:300]
        out.append(dict(area=area, question=q, ok=bool(ok), detail=str(detail)))
    return out



# ───────────────────────── 종목별 익절 래칫 (2026-10-31) ─────────────────────────
@check('익절 래칫', '미국·한국 각각 승자100·대조100 표본이 있고, 승자 중앙 상승이 2배 이상인가(정의상 참)')
def _():
    d = _j('results/stock_ratchet.json')
    info, res = d.get('info', {}), d.get('results', {})
    bad = [f"{m}|{g}" for m in ('US', 'KR') for g in ('승자100', '대조100')
           if ((res.get(f"{m}|{g}|start") or {}).get('매수보유') or {}).get('n') != 100]
    low = [m for m in ('US', 'KR') if (info.get(m) or {}).get('winner_med', 0) < 2]
    age = _age(d.get('asof'))
    return not bad and not low and age <= 14, f"기준 {d.get('asof')}({age}일) · 표본 부족 {bad or '없음'} · 승자 중앙<2배 {low or '없음'}"


@check('관점 합의 배분', '결과 JSON 이 끝까지 저장됐고(판정 포함) 평가 구간이 10년 이상인가')
def _():
    d = _j('results/consensus_alloc.json')
    w = d.get('window') or ['', '']
    yrs = (pd.Timestamp(w[1]) - pd.Timestamp(w[0])).days / 365.25 if all(w) else 0
    return bool(d.get('verdict')) and yrs >= 10, f"구간 {w[0]}~{w[1]}({yrs:.1f}년) · 판정 {'있음' if d.get('verdict') else '없음'}"

def main():
    strict = '--strict' in sys.argv
    res = run()
    bad = [r for r in res if not r['ok']]
    for r in res:
        print(f"{'✅' if r['ok'] else '❌'} [{r['area']}] {r['question']} — {r['detail']}")
        if not r['ok']:
            print(f"::error title=정답 점검 실패 · {r['area']}::{r['question']} — {r['detail']}")
    print(f"\n정답 점검: {len(res) - len(bad)}/{len(res)} 통과")
    if '--no-write' not in sys.argv:
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        json.dump(dict(generated=datetime.now().strftime('%Y-%m-%d %H:%M'), passed=len(res) - len(bad),
                       total=len(res), checks=res), open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    if strict and bad:
        sys.exit(1)


if __name__ == '__main__':
    main()
