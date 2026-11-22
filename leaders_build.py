# -*- coding: utf-8 -*-
"""
주도주 탐지 DB 백필 — 미국 전용
  1) 유니버스 선정 (시총 $2B+)
  2) 주봉 가격 (Yahoo)  3) 분기재무+공시일 (EDGAR companyfacts)
  4) 실적발표일 (EDGAR 8-K item 2.02)   5) factor_weekly 적재

  python leaders_build.py fetch 250      # 상위 250종 수집
  python leaders_build.py build          # 팩터 계산 → DB
"""
import json, os, sqlite3, sys, time, random, urllib.request, urllib.error
# 2026-10-10: 로컬(Windows cp949)에서 print 의 em-dash 하나로 update 가 통째로
# 죽었다. 다른 스크립트는 전부 이 줄을 갖고 있는데 여기만 없었다.
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "leaders_cache")
os.makedirs(CACHE, exist_ok=True)
# ⚠️ 장기 재구축을 샤드로 병렬화하기 위해 DB 경로도 환경변수로 뺐다(2026-09-13).
#    주차별 파이썬 루프라 단일 프로세스로는 2,700종 × 654주 = 19시간이 걸린다.
#    샤드마다 제 DB 에 쓰고 나중에 ATTACH 로 합친다(SQLite 동시쓰기 회피).
DB = os.environ.get("MARKET_DB", os.path.join(DATA, "market.db"))
# ⚠️ 백테스트용 장기 재구축을 위해 환경변수로 갈아끼울 수 있게 했다(2026-09-13).
#    운영(대시보드)은 v1 을 그대로 쓰고, 장기판은 다른 버전으로 **나란히** 쌓는다.
#    같은 테이블을 지우고 다시 쓰면 재구축 몇 시간 동안 화면이 죽는다.
VER = os.environ.get("FACTOR_VER", "v1")

YUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
# SEC 연락처는 설정에서 읽는다(2026-11-22 백로그 #4 — 공개 저장소에 이메일을 박지 않는다).
#   edgar_client.contact(): 환경변수 SEC_CONTACT → st.secrets['sec']['contact'] → secrets.toml
#   없으면 RuntimeError. import 시점이 아니라 '요청할 때' 읽는다.
_SUA_CACHE = {}


def _sua():
    from edgar_client import contact
    c = contact()
    if _SUA_CACHE.get('c') != c:
        _SUA_CACHE.clear()
        _SUA_CACHE.update({'c': c, 'h': {'User-Agent': f'leaders-research {c}',
                                         'Accept-Encoding': 'gzip, deflate'}})
    return _SUA_CACHE['h']

REV = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet',
       'RevenueFromContractWithCustomerIncludingAssessedTax']
TAGS = {'revenue': REV, 'gross': ['GrossProfit'],
        'opinc': ['OperatingIncomeLoss'], 'netinc': ['NetIncomeLoss']}

# 2026-11-22 — 재무상태표(순간값). 여기까지 안 받아서 미국 PBR·ROE·부채비율이 패널에서 0% 였다.
#   ⚠️ 손익계산서(TAGS)는 기간(start~end) 사실이고 이쪽은 **시점(end) 사실**이라 추출 함수가 다르다(_inst).
#   ⚠️ Liabilities 를 아예 태깅하지 않는 제출자가 많다(총부채를 따로 안 적고
#      LiabilitiesAndStockholdersEquity = 총자산만 적는다) → 없으면 자산 − 자본으로 메운다.
TAGS_INST = {'equity': ['StockholdersEquity',
                        'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest'],
             'liab':   ['Liabilities'],
             'assets': ['Assets']}


_SESS = requests.Session()


def get(url, hdr, tries=5):
    """SEC/Yahoo 공통. requests가 gzip 자동 해제 (urllib은 안 해서 파싱 실패했었음)"""
    delay = 2.0
    for _ in range(tries):
        try:
            r = _SESS.get(url, headers=hdr, timeout=45)
            if r.status_code == 200:
                return r.content
            if r.status_code == 404:
                return None
            if r.status_code in (429, 403, 401):
                time.sleep(delay + random.random() * 2); delay *= 1.8; continue
            time.sleep(delay); delay *= 1.5
        except Exception:
            time.sleep(delay); delay *= 1.5
    return None


def universe(n, lo=1.5e8, hi=None):
    """수집 대상 선정. 2026-08-12: lo 2e9 -> 5e8.

    여기서 쓰는 marketcap은 us_marketcap.csv 의 **현재 시총**이다. 이 함수는
    '무엇을 수집할지'만 정하고, '무엇을 매매할지'는 factor_weekly 의 주차별
    marcap 으로 건다(point-in-time). 수집 하한이 낮을수록 그 시점엔 컸다가
    지금 작아진 종목이 덜 빠진다.

    ⚠️ 2026-08-18 사고 — 이 CSV 가 2024-04 손수 받은 스냅샷인 채 27개월 방치됐다.
    수집 단계에서 걸러지면 팩터가 아예 계산되지 않아 **영원히 후보가 못 된다**.
    AXTI 는 스냅샷 $151M 로 하한에 걸려 빠졌고 그 사이 60배 올랐다.
    이제 marketcap_refresh.py 가 매일 다시 만든다(daily-refresh). 손으로 받지 마라.
    """
    d = pd.read_csv(os.path.join(DATA, "us_marketcap.csv"))
    d = d[d.country == "United States"]
    d = _clean_tickers(d)
    d = d[d.marketcap >= lo]
    if hi:
        d = d[d.marketcap <= hi]
    d = d.sort_values("marketcap", ascending=False).head(n)
    return d[["Symbol", "Name", "marketcap"]].rename(columns={"Symbol": "sym", "Name": "name"})


# 우선주·워런트·ETF 는 CIK 를 모회사와 공유하거나(JPM-PC → JPM 의 주식수를 가져온다)
# 애초에 영업회사가 아니다(GLD 는 금 ETF). 2026-08-18 유니버스 재구축에서
# JPM-PC $964B, GLD $143B, USOI 같은 것들이 상위에 올라와 드러났다.
_ETF_SIC = {"6726",   # Investment offices NEC — 폐쇄형펀드·ETF·트러스트
            "6221",   # Commodity contracts — 원자재 ETF
            "6770"}   # Blank checks — SPAC


def _clean_tickers(d):
    d = d.copy()
    sym = d.Symbol.astype(str).str.upper()
    ok = (~sym.str.contains(r"-P")                 # 우선주 (JPM-PC, BAC-PB…)
          & ~sym.str.match(r"^[A-Z]{4}W$")         # 워런트 (TBLAW…)
          & (sym.str.len() <= 5))
    # 같은 CIK 를 공유하면 주식수가 같은 회사의 것이다 → 하나만 남긴다.
    # 짧은 쪽을 대표로 본다(GOOGL/GOOG/GOOGM/GOOGN → GOOG).
    try:
        cm = json.load(open(os.path.join(DATA, "edgar_cik.json"), encoding="utf-8"))
        cik = sym.map({k.upper(): str(v) for k, v in cm.items()})
        d2 = d.assign(_s=sym, _c=cik, _ok=ok, _l=sym.str.len())
        d2 = d2[d2._ok]
        d2 = (d2.sort_values(["_c", "_l", "_s"])
                .drop_duplicates("_c", keep="first"))
        d = d2.drop(columns=["_s", "_c", "_ok", "_l"])
    except Exception:
        d = d[ok]
    # 업종(SIC)으로 ETF·트러스트·SPAC 제거
    p = os.path.join(DATA, "us_domicile.csv")
    if os.path.exists(p):
        dom = pd.read_csv(p)
        if "sic" in dom.columns:
            bad = set(dom.loc[dom.sic.astype(str).str.split(".").str[0].isin(_ETF_SIC),
                              "sym"].astype(str))
            d = d[~d.Symbol.astype(str).isin(bad)]
    return d


# ───────────────────────── 1) 가격 ─────────────────────────
def fetch_px(sym, last=None, force_full=False):
    """일봉을 받아 월요일 기준 주봉으로 직접 리샘플.
       ※ Yahoo의 interval=1wk는 period1 앵커 요일로 묶여(목~수) 실적주 정렬이 틀어짐.

    2026-10-10 증분화:
      last       — 이미 갖고 있는 마지막 주차(YYYY-MM-DD). 주면 그 2주 전부터만 받는다.
      force_full — 분할 등으로 과거가 소급 변경된 종목. 2013년부터 전수 재수집.

    왜 바꿨나: 워크플로가 매주 캐시를 통째로 지우고 2,900종을 다시 받았다.
    Yahoo 가 그걸 못 버텨 실측 ~300종에서 끊겼고, universe 가 2,429 → 242종으로
    무너져 이익 가속 신호가 한 달간 0종이었다. 파일이 DB 밖에 있으면 '어디까지
    받았나'를 물어볼 곳이 없어 전체 재수집 외에 길이 없었다 — 그래서 보관소를
    market.db(prices)로 옮기고 여기서 그 날짜를 받아 쓴다.

    ⚠️ 수정주가 소급 변경 문제는 증분으로 바꾼다고 사라지지 않는다. 분할 난 종목은
       반드시 force_full 로 불러야 한다(호출자 책임 · data/us_splits.csv 로 추적).
    """
    pd_ = os.path.join(CACHE, f"dy_{sym}.csv")
    # last 는 호출자가 prices 에서 조회해 넘긴다. None 이면 아직 없는 종목이므로
    # 전수로 받는다 — 여기서 CSV 존재로 판단하던 것이 순환의 한 축이었다.
    if last is not None and not force_full and os.path.exists(pd_):
        pass
    # 미완성 주와 경계 어긋남을 피해 2주 겹쳐 받는다(INSERT OR REPLACE 라 겹쳐도 안전)
    if last and not force_full:
        p1 = int((pd.Timestamp(last) - pd.Timedelta(days=14)).timestamp())
    else:
        p1 = 1356998400
    raw = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
              f"?period1={p1}&period2=1893456000&interval=1d", YUA)
    if not raw:
        return False
    try:
        r = json.loads(raw)['chart']['result'][0]
        q = r['indicators']['quote'][0]
        adj = r['indicators'].get('adjclose', [{}])[0].get('adjclose')
        d = pd.DataFrame({'Open': q['open'], 'High': q['high'], 'Low': q['low'],
                          'Close': q['close'], 'Volume': q['volume'],
                          'Adj': adj if adj else q['close']},
                         index=pd.to_datetime(r['timestamp'], unit='s')).dropna(subset=['Close'])
        d.index = d.index.tz_localize(None).normalize()
        # 전수 수집일 때만 '너무 짧으면 버린다'. 증분은 며칠치가 정상이다.
        if (last is None or force_full) and len(d) < 300:
            return False
        if not len(d):
            return False
        ratio = d['Adj'] / d['Close']
        for c in ('Open', 'High', 'Low'):
            d[c] = d[c] * ratio
        d['Close'] = d['Adj']
        d = d[['Open', 'High', 'Low', 'Close', 'Volume']]
        # 증분이면 기존 일봉에 이어 붙인다(겹친 날짜는 새 값 채택 — 소급 조정 반영)
        if last and not force_full and os.path.exists(pd_):
            try:
                old = pd.read_csv(pd_, index_col=0, parse_dates=True)
                d = pd.concat([old, d])
                d = d[~d.index.duplicated(keep='last')].sort_index()
            except Exception:
                pass
        d.to_csv(pd_)
        # 월요일 라벨 주봉 (W-MON: 그 주 월요일이 인덱스)
        w = d.resample('W-MON', label='left', closed='left').agg(
            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        # ★ 진행 중인 주(미완성 봉) 제거 — 금요일까지 데이터가 없으면 그 주는 버린다
        if len(w) and (d.index[-1] - w.index[-1]).days < 4:
            w = w.iloc[:-1]
        # 2026-10-10: px_*.csv 쓰기를 없앴다. 읽는 쪽(update · marketcap_refresh)을
        #   전부 prices 로 옮겼으므로 같은 내용을 두 군데 두지 않는다.
        #   dy_(일봉)만 남긴다 — 실적 발표일 전후 3일로 earn_react_* 를 만드는 데
        #   쓰이고, 그건 아직 대체 경로가 없다.
        try:
            import price_store
            price_store.put(sym, w, 'US')
        except Exception as _e:
            print(f"  [warn] {sym} prices 적재 실패: {str(_e)[:80]}", flush=True)
            return False
        return True
    except Exception:
        return False


# ─────────────────── 2) 재무 + 공시일 (EDGAR) ───────────────────
def cikmap():
    return {k.upper(): str(v).zfill(10) for k, v in
            json.load(open(os.path.join(DATA, 'edgar_cik.json'), encoding='utf-8')).items()}


def _dur(facts, tags, lo, hi):
    us = facts.get('facts', {}).get('us-gaap', {})
    out = {}
    for t in tags:
        for unit, arr in us.get(t, {}).get('units', {}).items():
            if unit != 'USD':
                continue
            for e in arr:
                s, en, fl = e.get('start'), e.get('end'), e.get('filed')
                if not (s and en and fl):
                    continue
                d = (pd.Timestamp(en) - pd.Timestamp(s)).days
                if lo <= d <= hi:
                    k = (s, en)
                    if k not in out or fl < out[k][1]:
                        out[k] = (e['val'], fl)
    return out


def qseries(facts, tags):
    """분기 + 10-K 역산 Q4 → {end: (val, filed)}"""
    q = _dur(facts, tags, 60, 100)
    a = _dur(facts, tags, 350, 380)
    m = {en: v for (s, en), v in q.items()}
    for (as_, ae), (av, af) in a.items():
        s0, e0 = pd.Timestamp(as_), pd.Timestamp(ae)
        inner = [v for (s, en), (v, f) in q.items()
                 if pd.Timestamp(s) >= s0 - pd.Timedelta(days=5)
                 and pd.Timestamp(en) <= e0 + pd.Timedelta(days=5)]
        if len(inner) == 3 and ae not in m:
            m[ae] = (av - sum(inner), af)
    return m


def _inst(facts, tags):
    """재무상태표 같은 **시점(instant) 사실** → {end: (val, filed)} (2026-11-22).

    duration 사실과 달리 start 가 없다. 같은 end 가 분기보고서·연차보고서·수정분으로 여러 번
    나오는데 값은 같은 날짜의 잔액이라 같다 → **가장 먼저 제출된 것**을 쓴다(look-ahead 방지:
    늦게 수정 제출된 값을 그 주에 알았다고 하면 안 된다). tags 는 우선순위 순 — 앞 태그가 있으면 그걸 쓴다."""
    us = facts.get('facts', {}).get('us-gaap', {})
    out = {}
    for t in tags:                          # 우선순위: 앞 태그가 채운 end 는 덮지 않는다
        got = {}
        for unit, arr in us.get(t, {}).get('units', {}).items():
            if unit != 'USD':
                continue
            for e in arr:
                en, fl = e.get('end'), e.get('filed')
                if not (en and fl) or e.get('start'):
                    continue
                if en not in got or fl < got[en][1]:
                    got[en] = (e['val'], fl)
        for en, v in got.items():
            out.setdefault(en, v)
    return out


def _cache_due(p, col, gap_days, min_age_days=7, need_cols=()):
    """캐시 파일을 다시 받을 때가 됐나.

    2026-10-14 — fq_(EDGAR 분기재무)·ek_(실적 발표일)는 **파일이 있으면 영원히
    다시 받지 않았다.** 갱신은 leaders_weekly.sh 의 REFRESH_FUND=1 을 사람이 분기마다
    켜야 했고, CI(weekly-accel)는 그 경로가 아예 없었다. 실측(10-13 PC):
    fq_ 2,799종 전부 08-02 에 받은 그대로 — 851종이 2026Q1 에 멈춰 있었다.
    이익 가속 신호(분기 매출·영업익 가속)와 🔄흑자전환이 둘 다 이 파일을 읽는다.

    규칙: 파일의 최신 기간(col)이 gap_days 보다 오래됐으면 새 분기가 나왔을 때다.
          그래도 min_age_days 안에 받은 파일은 건드리지 않는다(매주 SEC 를 두드리지 않게).

    2026-11-22 — need_cols: 캐시에 **없는 열**이 생기면(수집 항목을 늘렸을 때) 나이와 무관하게 다시 받는다.
    이게 없으면 TAGS 에 항목을 추가해도 기존 2,800개 캐시가 그대로 쓰여 새 열이 영원히 빈다.
    """
    if not os.path.exists(p):
        return True
    try:
        head = pd.read_csv(p, nrows=0).columns
        if need_cols and any(c not in head for c in need_cols):
            return True
        if (time.time() - os.path.getmtime(p)) / 86400 < min_age_days:
            return False
        last = pd.to_datetime(pd.read_csv(p, usecols=[col])[col], errors="coerce").max()
        return pd.isna(last) or (pd.Timestamp.today() - last).days > gap_days
    except Exception:
        return True


def fetch_fund(sym, cik):
    p = os.path.join(CACHE, f"fq_{sym}.csv")
    # 최신 분기 말 + 다음 분기(91일) + 대부분의 10-Q 제출(~30일) ≈ 120일.
    #   그 전에 다시 받아도 같은 내용이라 SEC 요청만 낭비한다.
    if not _cache_due(p, "period_end", gap_days=120, need_cols=("equity", "liabilities")):
        return True
    raw = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", _sua())
    if not raw:
        return False
    try:
        facts = json.loads(raw)
        ser = {k: qseries(facts, v) for k, v in TAGS.items()}
        bs = {k: _inst(facts, v) for k, v in TAGS_INST.items()}      # 2026-11-22 재무상태표
        ends = sorted(ser['revenue'])
        if len(ends) < 8:
            return False
        rows = []
        for en in ends:
            fl = min(x[1] for x in (ser[k].get(en) for k in TAGS) if x)
            r = dict(period_end=en, filed_at=fl,
                     **{k: (ser[k][en][0] if en in ser[k] else None) for k in TAGS})
            eq = bs['equity'].get(en)
            lb = bs['liab'].get(en)
            at = bs['assets'].get(en)
            r['equity'] = None if eq is None else float(eq[0])
            if lb is not None:
                r['liabilities'] = float(lb[0])
            elif at is not None and eq is not None:
                r['liabilities'] = float(at[0]) - float(eq[0])       # 총부채 미태깅 제출자 보정
            else:
                r['liabilities'] = None
            #   재무상태표는 손익계산서와 같은 보고서에 실린다 → 제출일도 같은 날이어야 한다.
            #   늦게 수정 제출된 잔액(filed > filed_at)은 그 주에 알 수 없었으므로 버린다.
            for _k, _v in (('equity', eq), ('liabilities', lb if lb is not None else at)):
                if _v is not None and str(_v[1]) > str(fl):
                    r[_k] = None
            rows.append(r)
        pd.DataFrame(rows).to_csv(p, index=False)
        return True
    except Exception:
        return False


def fetch_8k(sym, cik):
    """8-K item 2.02 = 실적 발표. acceptanceDateTime으로 BMO/AMC 판정"""
    p = os.path.join(CACHE, f"ek_{sym}.csv")
    # 실적 발표는 대략 91일 간격 → 마지막 발표가 80일 넘었으면 다음 발표를 확인
    if not _cache_due(p, "earn_date", gap_days=80):
        return True
    raw = get(f"https://data.sec.gov/submissions/CIK{cik}.json", _sua())
    if not raw:
        return False
    try:
        j = json.loads(raw)
        recent = j.get('filings', {}).get('recent', {})
        frames = [recent]
        for f in j.get('filings', {}).get('files', [])[:4]:
            r2 = get(f"https://data.sec.gov/submissions/{f['name']}", _sua())
            if r2:
                frames.append(json.loads(r2))
        rows = []
        for fr in frames:
            forms = fr.get('form', []); dates = fr.get('filingDate', [])
            items = fr.get('items', []); acc = fr.get('acceptanceDateTime', [])
            for i, form in enumerate(forms):
                if form != '8-K':
                    continue
                it = items[i] if i < len(items) else ''
                if '2.02' not in (it or ''):
                    continue
                a = acc[i] if i < len(acc) else ''
                hh = int(a[11:13]) if len(a) >= 13 else 12
                tm = 'AMC' if hh >= 16 else ('BMO' if hh < 9 else 'INTRADAY')
                rows.append(dict(earn_date=dates[i], earn_time=tm))
        if not rows:
            return False
        pd.DataFrame(rows).drop_duplicates('earn_date').sort_values('earn_date') \
            .to_csv(p, index=False)
        return True
    except Exception:
        return False


def recent_split_syms(days=400):
    """최근 `days` 일 안에 분할이 있었던 종목. 이들은 과거 전체가 소급 변경되므로
    증분으로 이어 붙이면 과거가 어긋난다 — 반드시 전수 재수집한다."""
    pth = os.path.join(DATA, "us_splits.csv")
    if not os.path.exists(pth):
        return set()
    try:
        d = pd.read_csv(pth)
        cut = pd.Timestamp.today() - pd.Timedelta(days=days)
        return set(d[pd.to_datetime(d.date, errors="coerce") >= cut].sym.astype(str))
    except Exception:
        return set()


def cmd_fetch(n, lo=1.5e8, hi=None, full=False):   # 2026-08-14: 5e8 -> 1.5e8 (대시세는 소형에서 시작한다)
    u = universe(n, lo, hi)
    # 2026-10-19 — 한 번 들어온 종목은 빼지 않는다(생존편향).
    #   유니버스를 '오늘 시총'으로 고르니, 그 사이 $150M 아래로 쪼그라든 종목(CDLX·HRTX·CHGG…)은
    #   과거 신호까지 통째로 사라졌다 — 백테스트가 '살아남은 종목'만 보고 낙관적으로 나온다.
    #   지금은 작아도 과거엔 유니버스였던 종목은 계속 이력을 유지한다. 목록은 커밋된다.
    ever_p = os.path.join(DATA, "universe_ever.csv")
    try:
        ever = pd.read_csv(ever_p).sym.astype(str)
    except Exception:
        ever = pd.Series([], dtype=str)
    extra = sorted(set(ever) - set(u.sym))
    if extra:
        u = pd.concat([u, pd.DataFrame({"sym": extra, "name": extra, "marketcap": np.nan})], ignore_index=True)
        print(f"  과거 유니버스 유지 {len(extra):,}종 (지금은 하한 아래·목록 밖)", flush=True)
    pd.DataFrame({"sym": sorted(set(ever) | set(u.sym))}).to_csv(ever_p, index=False)
    cm = cikmap()
    print(f"유니버스 {len(u)}종 (시총 {lo/1e9:.0f}B~{(hi/1e9 if hi else 999):.0f}B)", flush=True)
    syms = u.sym.tolist()

    # 2026-10-10 — 증분 수집. 전에는 워크플로가 캐시를 통째로 지우고 2,900종을
    # 매주 다시 받았고, Yahoo 가 ~300종에서 끊어 universe 가 242종으로 무너졌다.
    # 이제 market.db(prices) 에 '어디까지 받았나'를 물어, 없는 구간만 받는다.
    try:
        import price_store
        have = price_store.last_date('US')
    except Exception as _e:
        print(f"  [warn] prices 조회 실패 — 전수 수집으로 진행: {str(_e)[:80]}", flush=True)
        have = {}
    splits = recent_split_syms()
    # 2026-10-19 — 중간이 빈 종목도 전수 재수집 대상(증분은 끝 이후만 받아 중간 구멍을 못 메운다)
    try:
        gaps = price_store.gap_syms('US')
    except Exception:
        gaps = set()
    if gaps:
        print(f"  최근 30주 주봉 결손 {len(gaps)}종 → 전수 재수집", flush=True)
    splits = set(splits) | gaps
    n_inc = sum(1 for s in syms if s in have and s not in splits and not full)
    print(f"  증분 {n_inc}종 · 전수 {len(syms) - n_inc}종"
          f"{' (--full)' if full else ''}  분할 재수집 {len(splits & set(syms))}종", flush=True)

    # 2026-10-14 — 실패 기억. 처음부터 받아야 하는(전수) 종목 중 상장폐지·ETF·ADR 처럼
    #   Yahoo 가 안 주는 것이 매번 같은 자리에서 실패하며 요청 한도를 먹었다(10-10 실측:
    #   10회 돌려 1,068종 증가에 그침). 전수 수집이 3회 연속 실패한 종목은 28일간 건너뛰고,
    #   이전에 실패했던 종목은 순서를 뒤로 보낸다 — 받을 수 있는 종목이 먼저 받게.
    fail_p = os.path.join(CACHE, "_fetch_fail.json")
    try:
        fail = json.load(open(fail_p, encoding="utf-8"))
    except Exception:
        fail = {}
    today = pd.Timestamp.today().normalize()

    def _blocked(s):
        f = fail.get(s)
        return bool(f) and f[0] >= 3 and (today - pd.Timestamp(f[1])).days < 28

    is_full = lambda s: full or s in splits or s not in have
    skipped = [s for s in syms if is_full(s) and _blocked(s)]
    syms = [s for s in syms if s not in set(skipped)]
    syms.sort(key=lambda s: (s in fail, 0))          # 실패 이력 없는 것 먼저(안정 정렬)
    if skipped:
        print(f"  실패 기억으로 건너뜀 {len(skipped)}종 (3회 연속 실패 · 28일)", flush=True)

    def job(s):
        _full = full or s in splits
        ok_px = fetch_px(s, last=(None if _full else have.get(s)), force_full=_full)
        cik = cm.get(s.upper())
        ok_f = fetch_fund(s, cik) if cik else False
        ok_e = fetch_8k(s, cik) if cik else False
        return s, ok_px, ok_f, ok_e
    t0 = time.time(); done = [0, 0, 0]
    px_fail = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (s, a, b, c) in enumerate(ex.map(job, syms), 1):
            done[0] += a; done[1] += b; done[2] += c
            if not a:
                px_fail.append(s)
            if a:
                fail.pop(s, None)
            elif is_full(s):
                fail[s] = [(fail.get(s) or [0])[0] + 1, today.strftime("%Y-%m-%d")]
            if i % 25 == 0:
                print(f"  {i}/{len(syms)}  가격{done[0]} 재무{done[1]} 8K{done[2]}  "
                      f"{time.time()-t0:.0f}s", flush=True)
    # 2026-10-24 — 금요일 밤 정기 실행이 2주 연속(10-17·10-24) 가격 대부분을 못 받고(Yahoo 제한 추정)
    #   새 주차가 31~34종에만 생겨 fixcap 파수꾼에서 실패했다. 실패분만 1개씩 천천히 다시 받는다.
    if px_fail:
        print(f"  가격 실패 {len(px_fail):,}종 → 순차 재시도(최대 25분)", flush=True)
        t1 = time.time(); ok2 = 0
        for j, s in enumerate(px_fail, 1):
            if time.time() - t1 > 1500:
                break
            _full = full or s in splits
            if fetch_px(s, last=(None if _full else have.get(s)), force_full=_full):
                ok2 += 1; done[0] += 1; fail.pop(s, None)
            time.sleep(0.4)
            if j % 100 == 0:
                print(f"    재시도 {j}/{len(px_fail)} 성공 {ok2}", flush=True)
        print(f"  재시도 성공 {ok2:,}/{len(px_fail):,}", flush=True)
    rate = done[0] / max(len(syms), 1)
    # Actions 로그를 못 여는 환경에서도 원인이 보이게 주석(annotation)으로 남긴다
    lvl = "error" if rate < 0.8 else "notice"
    print(f"::{lvl} title=가격 수집::{done[0]:,}/{len(syms):,}종 성공({rate:.0%}) · 재무 {done[1]:,} · 8K {done[2]:,}", flush=True)
    u.to_csv(os.path.join(CACHE, "_universe.csv"), index=False)
    try:
        json.dump(fail, open(fail_p, "w", encoding="utf-8"))
        print(f"  실패 기록 {len(fail)}종 (그중 차단 {sum(1 for k in fail if _blocked(k))}종)", flush=True)
    except Exception as _e:
        print(f"  [warn] 실패 기록 저장 실패: {_e}", flush=True)
    print(f"완료 {time.time()-t0:.0f}s  가격{done[0]} 재무{done[1]} 8K{done[2]}")


# ───────────────────── 3) 팩터 계산 → DB ─────────────────────
def bench():
    """SPY 주봉 종가. 2026-10-10: px_SPY.csv → prices 테이블."""
    import price_store
    d = price_store.get("SPY", "US")
    if d is None or not len(d):
        fetch_px("SPY")
        d = price_store.get("SPY", "US")
    if d is None:
        raise RuntimeError("SPY 주봉을 얻지 못했다 — 벤치마크 없이는 알파를 못 낸다")
    return d["Close"]


_SHARES = {}


def load_shares():
    """SEC 공시 주식수 시계열을 {sym: (제출일배열, 주식수배열)} 로 올린다.

    data/us_shares.csv 는 marketcap_refresh.py 가 만든다(SEC companyconcept + frames).
    shares_adj = 오늘 분할 기준으로 환산한 주식수 — 가격 캐시가 소급 분할조정돼
    있어서 주식수도 같은 기준이어야 시총이 맞는다.
    """
    global _SHARES
    if _SHARES:
        return _SHARES
    p = os.path.join(DATA, "us_shares.csv")
    if not os.path.exists(p):
        print("⚠️ data/us_shares.csv 없음 — 시총·PER·PSR 을 채우지 않는다. "
              "`python marketcap_refresh.py all` 을 먼저 돌려라.", flush=True)
        _SHARES = {"__none__": None}
        return _SHARES
    d = pd.read_csv(p).dropna(subset=["sym", "filed", "shares_adj"])
    d = d.sort_values(["sym", "filed"])
    # 2026-10-20 — 상장 전 공시의 '100주'(설립 주식, CHWY·FNKO)가 첫 공시로 잡혀 상장 직후 몇 주의
    #   시총이 $0.00B 가 됐다 → 9월엔 있던 신호(CHWY 2019·FNKO 2018)가 시총 하한에서 사라짐.
    #   그 종목 중앙값의 1% 미만이거나 10만 주 미만인 기록은 버린다(분할 환산 후 값 기준).
    med = d.groupby("sym").shares_adj.transform("median")
    bad = (d.shares_adj < 1e5) | (d.shares_adj < med * 0.01)
    if bad.any():
        print(f"주식수 이상치 제외 {int(bad.sum())}행 · {d[bad].sym.nunique()}종", flush=True)
    d = d[~bad]
    _SHARES = {s: (pd.to_datetime(g.filed.values), g.shares_adj.values.astype(float))
               for s, g in d.groupby("sym", sort=False)}
    print(f"주식수 시계열 {len(d):,}행 · {len(_SHARES):,}종", flush=True)
    return _SHARES


#   2026-11-22 — leaders_schema.sql 은 CREATE TABLE IF NOT EXISTS 라서 표가 이미 있으면 새 열을 만들지 않는다.
#   그런데 적재부는 `PRAGMA table_info` 로 표의 열만 골라 넣는다 → DDL 에만 추가하면 새 열이 **조용히 버려진다.**
#   SQLite 에 ADD COLUMN IF NOT EXISTS 가 없으므로 직접 확인하고 붙인다.
_NEW_COLS = (("equity", "REAL"), ("liabilities", "REAL"), ("debt", "REAL"), ("roe", "REAL"))


def _add_cols(con):
    have = {x[1] for x in con.execute("PRAGMA table_info(factor_weekly)")}
    add = [(c, t) for c, t in _NEW_COLS if c not in have]
    for c, t in add:
        con.execute(f"ALTER TABLE factor_weekly ADD COLUMN {c} {t}")
    if add:
        con.commit()
        print(f"factor_weekly 열 추가: {', '.join(c for c, _ in add)}", flush=True)


# 2026-11-23 — **증분 적재가 과거를 썩히는 것**을 고친다(근본 수리).
#   증상: 증분 적재는 새 주차만 붙이고 과거 행을 고치지 않는다. 그 뒤 분할이 일어나면
#   `prices`(일봉)는 수정주가로 **과거까지** 보정되는데 factor_weekly 의 과거 행은 분할 전 값으로 남는다.
#   오류도 결측도 없이 틀린 가격이 백테스트·주도주 신호로 흘러간다.
#   실측(11-22): 겹침 959,977행 중 105,618행(11.0%)·252종 — AAPL·BAC·AMGN·ADM·AEP 포함.
#   수리: 증분을 시작하기 **전에** 저장값과 일봉 원본을 대조해 어긋난 종목을 찾고,
#   그 종목의 행을 지운다 → build 의 종목별 시작 주차 로직(_last 없음 = start 부터)이 전 기간을 다시 쌓는다.
#
#   ⚠️ 깨지는 지점 — 먼저 적는다:
#     ① 한 번에 다 고치면 주간 파이프라인이 몇 시간 늘어난다 → 회당 상한(REPAIR_MAX)을 둔다.
#        그러면 **새로 썩는 속도가 고치는 속도를 앞지를 수 있다** → 어긋난 행 수가 많은 종목부터
#        고치고, 썩음 추이를 정답 점검이 매주 재서 줄고 있는지 본다(줄지 않으면 상한을 올려야 한다).
#     ② 분할이 아니라 **일봉 쪽이 틀린** 경우도 이 대조에 걸린다. 그때는 재적재가 틀린 값을
#        베껴 온다 — 일봉이 정본이라는 전제 위에 서 있다(us_capfix·kr_adjust 가 그 전제를 지킨다).
#     ③ 상장폐지·거래정지로 일봉이 없는 주차는 판정하지 않는다(결측을 썩음으로 세면 전 종목이 걸린다).
REPAIR_MAX = int(os.environ.get("REPAIR_MAX", "60"))     # 회당 재적재 종목 수 상한
#   ⚠️ 임계를 10% 로 둔 이유 — 11-23 전수 측정에서 **두 가지 다른 문제가 섞여 있었다**:
#
#     어긋남        행              종목    정체
#     10% 초과      6,736 (0.66%)   30종    분할 보정 미전파 (APH·MNST 2:1 · SUPN·WLFC 3:1 정수배)
#     0.5~10%       237,732 (23%)   681종   배당 조정 누적 (DOC·EPR·LAND·ADM 등 고배당·REIT)
#
#   재적재로 고칠 수 있는 건 **앞쪽뿐**이다. 배당은 지급될 때마다 과거 조정값이 바뀌므로
#   매주 새로 어긋나고, 681종을 매주 다시 쌓는 것은 사실상 전체 재적재다(회당 상한으로는
#   영원히 못 따라간다). 임계를 0.5% 로 두면 매주 상한이 배당주로 꽉 차고 **분할이 밀린다** —
#   정작 2~3배 틀린 30종이 뒤로 가는, 가장 나쁜 우선순위가 된다.
#   배당 쪽 해결은 재적재가 아니다 → docs/research/2026-11-22_미국_시계열_접합.md 의 '남은 일'.
REPAIR_TOL = 0.10


ROT_LOG = "results/split_rot.json"


def _rot_log(rec, keep=26):
    """분할 썩음 측정·수리 이력을 추가만 한다(최근 keep 회차). 정답 점검이 추이를 본다."""
    p = os.path.join(BASE, ROT_LOG)
    try:
        old = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    except Exception:
        old = {}
    hist = [h for h in (old.get("history") or []) if h.get("asof") != rec["asof"]]
    hist.append(rec)
    out = dict(latest=rec, history=hist[-keep:])
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print(f"썩음 기록 → {ROT_LOG} (최근 {len(out['history'])}회차)", flush=True)


def find_rot(con, ver, since="2018-01-01", tol=REPAIR_TOL, limit=None):
    """저장된 주봉 종가가 일봉 원본과 어긋난 종목 — (목록, 어긋난 행 수 합계, 전체 종목 수).
    어긋난 행이 많은 종목부터. limit 로 회당 상한을 건다.

    `recent_split_syms()` 와 **역할이 다르다 — 지우지 말 것.**
      · `recent_split_syms()` = `us_splits.csv` 목록 기반. **가격 캐시(prices)** 를 전수 재수집한다.
      · 여기(`find_rot`) = 결과 기반. **factor_weekly 의 과거 행**이 그 일봉과 맞는지 직접 본다.
    앞쪽이 prices 를 고쳐도 factor_weekly 과거는 그대로이므로 둘 다 필요하다.

    왜 목록이 아니라 결과로 판정하나 — 11-23 실측. 썩은 30종을 `us_splits.csv` 와 대조하니:
      · 목록에 **아예 없음 22종** (그 파일이 2026-08-14 이후 멈춰 있다 — 감시 밖이었다)
      · 목록엔 있으나 400일 창 밖 6종
      · 최근 400일 창 안 = 기존 방어가 잡는 것 **2종**
    목록을 믿으면 30종 중 2종만 고친다. 결과를 보면 원인이 분할이든 단위 오류든 다 걸린다.
    """
    rows = con.execute("""
        SELECT f.sym, COUNT(*) n FROM factor_weekly f
        WHERE f.factor_ver = ? AND f.as_of >= ? AND f.close IS NOT NULL
          AND EXISTS (SELECT 1 FROM prices p
                      WHERE p.sym = f.sym AND p.market = 'US'
                        AND p.date >= f.as_of AND p.date < date(f.as_of, '+7 day'))
          AND abs(f.close - (SELECT p.close FROM prices p
                             WHERE p.sym = f.sym AND p.market = 'US'
                               AND p.date >= f.as_of AND p.date < date(f.as_of, '+7 day')
                             ORDER BY p.date DESC LIMIT 1))
              > ? * abs((SELECT p.close FROM prices p
                         WHERE p.sym = f.sym AND p.market = 'US'
                           AND p.date >= f.as_of AND p.date < date(f.as_of, '+7 day')
                         ORDER BY p.date DESC LIMIT 1))
        GROUP BY f.sym ORDER BY n DESC, f.sym""", (ver, since, tol)).fetchall()
    syms = [s for s, _ in rows]
    return (syms[:limit] if limit else syms), sum(n for _, n in rows), len(syms)


def shares_at(sym, when):
    """그 주차 시점에 **이미 제출돼 있던** 가장 최근 공시의 주식수.

    첫 공시보다 앞선 주차는 첫 공시값을 쓴다 — 그 시절 주식수를 알 방법이 없고,
    비우면 그 구간이 통째로 유니버스에서 빠져 백테스트 앞부분이 사라진다.
    """
    e = load_shares().get(sym)
    if e is None:
        return None
    f, v = e
    k = int(np.searchsorted(f, pd.Timestamp(when), side="right")) - 1
    if k < 0:
        k = 0
    return float(v[k]) if len(v) else None


def build(start="2018-01-01", incremental=False, newsyms=False, repair=True):
    """newsyms=True: 아직 factor_weekly 에 없는 종목만 전 기간 적재한다.

    2026-08-18 유니버스 재구축용. 시총 버그를 고치고 유니버스를 3,181종으로 넓혔는데,
    기존 2,208종은 marketcap_fix_db.py 로 marcap·per·psr 이 이미 제자리 보정됐다
    (저장된 종가 × SEC 공시 주식수 — build 의 shares_at() 과 같은 값이다).
    나머지 팩터는 가격에서만 나오므로 주식수 버그와 무관하다.
    따라서 기존 종목을 다시 계산할 이유가 없다 — 신규만 채우면 결과가 동일하고
    전체 재적재(6시간+)를 피할 수 있다.
    """
    u = pd.read_csv(os.path.join(CACHE, "_universe.csv"))
    load_shares()
    spy = bench()
    con = sqlite3.connect(DB)
    con.executescript(open(os.path.join(BASE, "leaders_schema.sql"), encoding="utf-8").read())
    _add_cols(con)
    base_start = start      # 증분 모드에서 start 가 덮어써지기 전 원래 시작일(수리 종목이 쓴다)
    _repair = set()         # 이번 회차에 **전 기간 다시 쌓을** 종목(분할 썩음 수리)
    if newsyms:
        # 2026-10-19 — '있다'의 기준을 **52주 이상 이력**으로 바꿨다.
        #   Actions 캐시의 market.db 는 10-10 사고 때 243종 이력만 남았고, 그 뒤 증분은
        #   최신 주만 붙였다. 10-12 주에 1,912종이 '있어서' 신규로 안 잡혔지만 이력이
        #   1주뿐이라 이익 가속(4분기 전 대비)을 계산할 수 없었다 → 신호 0종.
        #   이력이 짧은 종목은 지우고 전 기간을 다시 적재한다.
        have = {r[0] for r in con.execute(
            "SELECT sym FROM factor_weekly WHERE factor_ver=? GROUP BY sym HAVING COUNT(*) >= 52",
            (VER,))}
        thin = [r[0] for r in con.execute(
            "SELECT sym FROM factor_weekly WHERE factor_ver=? GROUP BY sym HAVING COUNT(*) < 52",
            (VER,))]
        # 2026-10-19 — 이력은 길어도 **최근 30주 중간이 빈** 종목(09-14~09-28 결손분)도 다시 적재
        _cut = (pd.Timestamp.today() - pd.Timedelta(weeks=30)).strftime("%Y-%m-%d")
        _rc = con.execute("SELECT sym, COUNT(*) FROM factor_weekly WHERE factor_ver=? AND as_of>=? "
                          "GROUP BY sym", (VER, _cut)).fetchall()
        if _rc:
            _mx = max(n for _, n in _rc)
            _gap = {s_ for s_, n in _rc if n < _mx - 2}
            print(f"최근 30주 결손 {len(_gap):,}종도 재적재", flush=True)
            thin = sorted(set(thin) | _gap)
            have -= _gap
        if thin:
            con.executemany("DELETE FROM factor_weekly WHERE factor_ver=? AND sym=?",
                            [(VER, x) for x in thin])
            con.commit()
            print(f"이력 52주 미만 {len(thin):,}종 삭제 후 재적재", flush=True)
        before = len(u)
        u = u[~u.sym.isin(have)]
        print(f"신규 종목 모드 — 기존 {len(have):,}종 건너뜀, "
              f"{len(u):,}종만 적재 (유니버스 {before:,})", flush=True)
    elif incremental:
        # 2026-11-23 — 증분 **전에** 분할 썩음을 수리한다. 여기 둔 이유: 수리 종목의 행을
        #   지우면 아래 `_last` 조회에서 그 종목이 빠지고, 종목별 시작 주차 로직이
        #   base_start 부터 전 기간을 다시 쌓는다(별도 패스가 필요 없다).
        if repair and REPAIR_MAX > 0:
            rot, rot_rows, rot_syms = find_rot(con, VER, since=base_start, limit=None)
            #   ⚠️ 유니버스에 없는 종목은 **지우면 안 된다.** 아래 루프가 u 만 돌기 때문에
            #      다시 쌓이지 않고 행만 사라진다(상장폐지·유니버스 축소 종목이 그렇다).
            #      썩은 값이라도 지우는 것보다는 남기는 게 낫다 — 지우면 복구 수단이 없다.
            _univ = set(u.sym.astype(str))
            _skip = [s for s in rot if s not in _univ]
            rot = [s for s in rot if s in _univ][:REPAIR_MAX]
            if _skip:
                print(f"분할 썩음이지만 유니버스에 없어 건드리지 않는 종목 {len(_skip)}: "
                      f"{_skip[:15]}{' …' if len(_skip) > 15 else ''}", flush=True)
            if rot_syms:
                print(f"분할 썩음 {rot_syms}종 · {rot_rows:,}행 — 이번 회차는 영향 큰 {len(rot)}종 재적재 "
                      f"(상한 REPAIR_MAX={REPAIR_MAX}): {rot[:15]}{' …' if len(rot) > 15 else ''}", flush=True)
                con.executemany("DELETE FROM factor_weekly WHERE factor_ver=? AND sym=?",
                                [(VER, s) for s in rot])
                con.commit()
                _repair = set(rot)
                if rot_syms > len(rot):
                    print(f"  남은 {rot_syms - len(rot)}종은 다음 회차에 — 정답 점검이 썩음 추이를 "
                          f"매주 재니 줄지 않으면 REPAIR_MAX 를 올려야 한다", flush=True)
            else:
                print("분할 썩음 없음", flush=True)
            #   다음 주기부터 **계속 검증**하기 위한 기록. known_answers 가 이 파일을 읽는다.
            #   (썩음 측정 쿼리는 100만 행에 상관 서브쿼리라 무겁다 → 매 검사마다 다시 재지 않고
            #    수리한 쪽이 남긴 숫자를 본다. 추이가 보여야 상한이 모자란지 알 수 있다.)
            _rot_log(dict(asof=time.strftime("%Y-%m-%d"), ver=VER, tol=REPAIR_TOL,
                          since=base_start, syms=rot_syms, rows=rot_rows,
                          repaired=sorted(rot), repaired_n=len(rot),
                          remaining=max(rot_syms - len(rot) - len(_skip), 0),
                          skipped_not_in_universe=len(_skip), repair_max=REPAIR_MAX))
        last = con.execute("SELECT MAX(as_of) FROM factor_weekly WHERE factor_ver=?",
                           (VER,)).fetchone()[0]
        if last:
            start = (pd.Timestamp(last) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            print(f"증분 모드 — 기존 최신 {last} 이후만 계산 (start={start})")
        else:
            print("증분 요청됐으나 기존 데이터 없음 → 전체 적재")
    else:
        # 2026-08-12 추가. 전체 재적재는 기존 데이터를 지우고 6시간 넘게 돈다.
        # 중간에 끊기면 되돌릴 방법이 없어 한 번 DB를 통째로 날린 적이 있다.
        n_old = con.execute("SELECT COUNT(*) FROM factor_weekly WHERE factor_ver=?",
                            (VER,)).fetchone()[0]
        if n_old:
            bak = DB + f".bak-{pd.Timestamp.now():%Y%m%d-%H%M}"
            print(f"기존 {n_old:,}행 → 백업 {os.path.basename(bak)}", flush=True)
            con.commit()
            import shutil; shutil.copy2(DB, bak)
        con.execute("DELETE FROM factor_weekly WHERE factor_ver=?", (VER,))
    cols = None
    # 샤드 — SHARD/NSHARD 가 있으면 자기 몫만 계산한다
    _ns = int(os.environ.get("NSHARD", "1")); _sh = int(os.environ.get("SHARD", "0"))
    if _ns > 1:
        u = u[[i % _ns == _sh for i in range(len(u))]].reset_index(drop=True)
        print(f"샤드 {_sh}/{_ns} — 담당 {len(u)}종", flush=True)

    try:
        import price_store as _PS
        _PSC = _PS._conn()
    except Exception as _e:
        print(f"[WARN] price_store 사용 불가: {str(_e)[:80]}", flush=True)
        _PS, _PSC = None, None

    total = 0
    # 2026-11-15 — 종목별 시작 주차. 예전엔 전역 MAX(as_of)+1 하나라, 한 주가 일부 종목만 들어간 채
    #   저장되면 나머지 종목은 그 주를 **영영** 건너뛰었다(구멍). 종목마다 자기 마지막 주차 다음부터.
    _last = {}
    if incremental:
        _last = dict(con.execute("SELECT sym, MAX(as_of) FROM factor_weekly WHERE factor_ver=? GROUP BY sym",
                                 (VER,)).fetchall())
    _tail = {}          # 종목별 가장 최근 주봉 날짜 — 주차 완성도 판정용
    # 2026-10-19 — 유니버스 2,900 중 1,900 만 적재되는 이유를 센다(어디서 빠지나)
    why = {"재무파일 없음": 0, "주봉 없음/80주 미만": 0, "새 주차 없음": 0, "공시 분기 6개 미만": 0}
    for _, row in u.iterrows():
        s = row.sym
        fp = os.path.join(CACHE, f"fq_{s}.csv")
        if not os.path.exists(fp):
            why["재무파일 없음"] += 1
            continue
        # 2026-10-10: px_*.csv → market.db(prices). 가격의 보관소가 하나가 됐다.
        w = _PS.get(s, 'US', conn=_PSC) if _PS else None
        if w is None or len(w) < 80:
            why["주봉 없음/80주 미만"] += 1
            continue
        _tail[s] = w.index[-1]
        #   수리 종목은 행을 지웠으므로 _last 에 없다 → base_start 부터 전 기간을 다시 쌓는다.
        #   (start 는 증분 모드에서 '최신 주차+1'로 덮어써져 있어 그대로 쓰면 아무것도 안 쌓인다.)
        _st = (base_start if s in _repair else
               ((pd.Timestamp(_last[s]) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
                if s in _last and _last[s] else start))
        # ★ 계산할 새 주차가 없으면 일봉·재무 로드 전에 바로 스킵
        if w.index[-1] < pd.Timestamp(_st):
            why["새 주차 없음"] += 1
            continue
        dyp = os.path.join(CACHE, f"dy_{s}.csv")
        dly = (pd.read_csv(dyp, index_col=0, parse_dates=True).sort_index()
               if os.path.exists(dyp) else None)
        f = pd.read_csv(fp)
        f["period_end"] = pd.to_datetime(f.period_end)
        f["filed_at"] = pd.to_datetime(f.filed_at, errors="coerce")
        f = f.dropna(subset=["filed_at"]).sort_values("filed_at").reset_index(drop=True)
        if len(f) < 6:
            why["공시 분기 6개 미만"] += 1
            continue
        f["gpm"] = f.gross / f.revenue * 100
        f["opm"] = f.opinc / f.revenue * 100
        f["npm"] = f.netinc / f.revenue * 100
        f["rev_yoy"] = f.revenue.pct_change(4) * 100
        f["rev_qoq"] = f.revenue.pct_change() * 100
        ek = None
        ekp = os.path.join(CACHE, f"ek_{s}.csv")
        if os.path.exists(ekp):
            ek = pd.read_csv(ekp)
            ek["earn_date"] = pd.to_datetime(ek.earn_date)
            ek = ek.sort_values("earn_date")

        c = w["Close"]
        w["ma5"] = c.rolling(5).mean(); w["ma10"] = c.rolling(10).mean()
        w["ma20"] = c.rolling(20).mean()
        w["hi52"] = c.rolling(52).max()
        w["vma20"] = w.Volume.rolling(20).mean()
        sp = spy.reindex(w.index, method="nearest")
        rec = []
        i_start = max(60, int(np.searchsorted(w.index, pd.Timestamp(_st))))
        for i in range(i_start, len(w)):
            d = w.index[i]
            px = float(c.iloc[i])
            r = dict(as_of=str(d.date()), sym=s, name=row["name"], sector=None,
                     close=px, factor_ver=VER, built_at=time.strftime("%Y-%m-%d"))
            # ── T ──
            ma20 = w.ma20.iloc[i]; ma10 = w.ma10.iloc[i]
            r["ma5"] = float(w.ma5.iloc[i]); r["ma10"] = float(ma10); r["ma20"] = float(ma20)
            r["close_gt_ma20"] = int(px > ma20); r["ma10_gt_ma20"] = int(ma10 > ma20)
            for k, lb in [("hi_5w", 5), ("hi_10w", 10), ("hi_20w", 20), ("hi_52w", 52)]:
                r[k] = int(px >= c.iloc[max(0, i-lb+1):i+1].max() * 0.999)
            hi52 = float(w.hi52.iloc[i])
            r["dist_52w"] = (px / hi52 - 1) * 100
            seg = c.iloc[max(0, i-51):i+1]
            r["days_since_hi52"] = int((d - seg.idxmax()).days)
            for k, lb in [("rs_4w", 4), ("rs_13w", 13), ("rs_26w", 26)]:
                j = max(0, i - lb)
                b0 = float(sp.iloc[j]); b1 = float(sp.iloc[i])
                r[k] = float((px / float(c.iloc[j])) / (b1 / b0)) if b0 and c.iloc[j] else None
            s52 = c.iloc[max(0, i-51):i+1]; m52 = w.ma20.iloc[max(0, i-51):i+1]
            ok = m52.notna()
            r["above_ma20_52w"] = float((s52[ok] > m52[ok]).mean() * 100) if ok.any() else None
            r["break_ma20_52w"] = int(((s52 < m52) & (s52.shift() >= m52.shift())).sum())
            for k, lb in [("ret_1w", 1), ("ret_4w", 4), ("ret_13w", 13)]:
                r[k] = (px / float(c.iloc[max(0, i-lb)]) - 1) * 100
            yr = c.iloc[:i+1]; yr = yr[yr.index.year == d.year]
            r["ret_ytd"] = (px / float(yr.iloc[0]) - 1) * 100 if len(yr) else None
            r["mdd_52w"] = float((s52 / s52.cummax() - 1).min() * 100)
            r["low_52w_dist"] = (px / float(s52.min()) - 1) * 100
            vm = w.vma20.iloc[i]
            r["vol_x_20w"] = float(w.Volume.iloc[i] / vm) if vm and vm > 0 else None
            r["adv_20d"] = float((w.Volume.iloc[max(0, i-19):i+1] * c.iloc[max(0, i-19):i+1]).mean() / 5)

            # ── V (그 시점에 공시된 것만) ──
            av = f[f.filed_at <= d]
            if len(av) >= 5:
                k = av.index[-1]
                r["period_end"] = str(f.period_end[k].date())
                for src in ("revenue", "gross", "opinc", "netinc"):
                    key = {"gross": "gross_profit", "opinc": "op_income",
                           "netinc": "net_income"}.get(src, src)
                    v = f[src][k]
                    r[key] = None if pd.isna(v) else float(v)
                for a, b in [("rev_yoy", "rev_yoy"), ("rev_qoq", "rev_qoq"),
                             ("gpm", "gpm"), ("opm", "opm"), ("npm", "npm")]:
                    v = f[b][k]
                    r[a] = None if pd.isna(v) else float(v)
                # 2026-11-22 재무상태표 — 자본·부채와 부채비율. PBR·ROE 는 아래 P 블록(시총이 필요)
                for _c in ("equity", "liabilities"):
                    v = f[_c][k] if _c in f.columns else np.nan
                    r[_c] = None if pd.isna(v) else float(v)
                r["debt"] = (None if (r["equity"] is None or r["liabilities"] is None or r["equity"] <= 0)
                             else r["liabilities"] / r["equity"] * 100)
                for m_, tag in [("gpm", "gpm"), ("opm", "opm"), ("npm", "npm")]:
                    v0, v1 = f[m_][k], (f[m_][k-1] if k >= 1 else np.nan)
                    r[tag + "_qoq"] = None if (pd.isna(v0) or pd.isna(v1)) else float(v0 - v1)
                    r[tag + "_up2"] = int(k >= 2 and not pd.isna(f[m_][k-2])
                                          and v0 > v1 > f[m_][k-2]) if k >= 2 else 0
                op = f.opinc.values
                past = op[max(0, k-4):k]
                r["op_turn"] = int((op[k] or 0) > 0 and any((x or 0) <= 0 for x in past))
                st = 0
                for x in reversed(op[:k+1]):
                    if x is not None and x > 0:
                        st += 1
                    else:
                        break
                r["op_pos_streak"] = st
                r["rev_q_count"] = int(f.revenue[:k+1].notna().sum())
                # ── E ──
                if ek is not None and len(ek[ek.earn_date <= d]):
                    e = ek[ek.earn_date <= d].iloc[-1]
                    ed = e.earn_date; r["earn_src"] = "8K"; r["earn_time"] = e.earn_time
                else:
                    ed = f.filed_at[k]; r["earn_src"] = "10Q"; r["earn_time"] = None
                r["earn_date"] = str(ed.date())
                # 반응일 = AMC면 다음 거래일, 아니면 당일 → 그 날이 속한 주봉이 반응 주
                react = ed + pd.Timedelta(days=1) if r.get("earn_time") == "AMC" else ed
                ei = int(np.searchsorted(w.index, react, side="right")) - 1
                r["weeks_since_earn"] = round((d - ed).days / 7.0, 1)
                r["earn_week_flag"] = int(ei == i)
                if 0 < ei < len(w):
                    r["earn_react_w0"] = (float(c.iloc[ei]) / float(c.iloc[ei-1]) - 1) * 100
                    if dly is not None:
                        di = int(np.searchsorted(dly.index, react))
                        if 0 < di < len(dly) - 1:
                            p0 = float(dly.Close.iloc[di - 1])
                            r["earn_react_gap"] = (float(dly.Open.iloc[di]) / p0 - 1) * 100
                            r["earn_react_d2"] = (float(dly.Close.iloc[di + 1]) / p0 - 1) * 100
            # ── P ──
            # 2026-08-18: 주식수를 `시총 ÷ 최신종가` 로 역산하던 걸 걷어냈다.
            # us_marketcap.csv 가 2024-04 스냅샷이라 역산 주식수가 (실제주가/스냅샷주가)
            # 배만큼 틀렸고, 그 오차가 marcap·per·psr 전부에 전 주차 동일 배수로 곱해졌다.
            # 실측 2,476종 중 오차 ±25% 안은 27.5%뿐. 지금은 SEC 공시 주식수를
            # 제출일(filed) 기준으로 그 주차에 알 수 있던 값만 쓴다(look-ahead 없음).
            sh = shares_at(s, d)
            if sh:
                mc = px * sh
                r["marcap"] = mc
                ttm = f.revenue[max(0, k-3):k+1].sum() if len(av) >= 5 else None
                ni = f.netinc[max(0, k-3):k+1].sum() if len(av) >= 5 else None
                r["psr"] = mc / ttm if ttm and ttm > 0 else None
                r["per"] = mc / ni if ni and ni > 0 else None
                # 2026-11-22 — PBR·ROE. 자본총계가 음수(결손 누적)면 둘 다 뜻이 없어 빈값으로 둔다
                #   ('싸 보이는 자본잠식'을 만들지 않는다). ROE 는 PER 과 같은 TTM 순이익 ÷ 자본.
                eq = r.get("equity")
                r["pbr"] = mc / eq if eq and eq > 0 else None
                r["roe"] = (ni / eq * 100) if (eq and eq > 0 and ni is not None and ni == ni) else None
            rec.append(r)
        if not rec:
            continue
        df = pd.DataFrame(rec)
        if incremental:      # 중복 방지 (재실행 안전)
            con.executemany("DELETE FROM factor_weekly WHERE as_of=? AND sym=? AND factor_ver=?",
                            [(a, s, VER) for a in df.as_of.tolist()])
        if cols is None:
            cols = [x[1] for x in con.execute("PRAGMA table_info(factor_weekly)")]
        for cc in cols:
            if cc not in df.columns:
                df[cc] = None
        df[cols].to_sql("factor_weekly", con, if_exists="append", index=False)
        total += len(df)
        if not incremental:
            print(f"  {s:6s} {len(df):5d}행  누적 {total:,}", flush=True)
    con.commit()
    print(f"\nfactor_weekly 적재 {total:,}행")
    _w = " · ".join(f"{k} {v:,}" for k, v in why.items())
    print(f"유니버스 {len(u):,}종 중 제외 — {_w}", flush=True)
    print(f"::notice title=factor_weekly 제외 사유::유니버스 {len(u):,}종 · {_w}", flush=True)
    # 2026-11-15 주차 완성도 — 11-07·11-14 토요일 새벽 실행은 Yahoo 주봉 최신 주가 1/3 종목(979~1,050종)에
    #   아직 없었다. 그 상태로 발행하면 후보가 2/3 유니버스로 뽑힌다. 워크플로가 이 파일을 읽고 발행을 미룬다.
    if _tail:
        _tgt = max(_tail.values())
        _stale = sum(1 for v in _tail.values() if v < _tgt)
        _wk = dict(target=str(_tgt.date()), stale=_stale, checked=len(_tail),
                   ratio=round(_stale / len(_tail), 3))
        json.dump(_wk, open(os.environ.get("ACCEL_WEEK_STATS", "/tmp/accel_week.json"), "w"))
        print(f"::notice title=주차 완성도::최신 주봉 {_wk['target']} — 아직 없는 종목 {_stale:,}/{len(_tail):,}종"
              f"({_wk['ratio']:.0%})", flush=True)
    print(con.execute("SELECT COUNT(DISTINCT sym), MIN(as_of), MAX(as_of) FROM factor_weekly").fetchone())
    con.close()


def fixcap(sentinels=("NVDA", "AAPL", "MSFT", "TSLA", "AXTI", "PLTR")):
    """시총이 빈 행만 다시 채운다 — marcap = 종가 × 그 주차에 알 수 있던 공시 주식수.

    ⚠️ 2026-10-19 사고 — us_shares.csv 가 매일 6,500 ↔ 2,000종을 오갔다(weekly-profile 이
    전체를 쓰고, daily-refresh 가 덜 복원된 캐시로 덮었다). 이력을 쌓는 날 2,000종판이
    걸리면 빠진 종목(NVDA·AXTI·PLTR…)의 marcap 이 **2018년부터 전부 NULL** 로 저장됐고,
    '시총 $0.3B+' 조건에서 통째로 탈락했다. 9월엔 신호가 있던 461종이 0회가 됐다.
    newsyms 는 '이력이 짧은' 종목만 다시 쌓으므로 이 결손을 못 고친다 → 이 함수가 매주 돈다.
    PER·PSR 도 같이 채운다(TTM = 최근 4개 분기 합, 분기 5개 이상일 때만 — build 와 같은 규칙).
    """
    sh = load_shares()
    con = sqlite3.connect(DB)
    d = pd.read_sql("SELECT rowid AS rid, sym, as_of, close, period_end, revenue, net_income "
                    "FROM factor_weekly WHERE factor_ver=? AND close IS NOT NULL "
                    # 2026-10-20: 빈 값뿐 아니라 '주식수 10만 주 미만'에 해당하는 시총(상장 전 100주 공시)도 다시 계산
                    "AND (marcap IS NULL OR marcap < close * 100000)",
                    con, params=(VER,))
    print(f"시총 빈·이상 행 {len(d):,} · {d.sym.nunique():,}종", flush=True)
    upd = []
    for s_, g in d.groupby("sym"):
        if s_ not in sh:
            continue
        allq = pd.read_sql("SELECT DISTINCT period_end, revenue, net_income FROM factor_weekly "
                           "WHERE factor_ver=? AND sym=? AND period_end IS NOT NULL ORDER BY period_end",
                           con, params=(VER, s_)).drop_duplicates("period_end")
        allq["rv4"] = allq.revenue.rolling(4, min_periods=4).sum()
        allq["ni4"] = allq.net_income.rolling(4, min_periods=4).sum()
        allq["k"] = range(len(allq))
        qm = allq.set_index("period_end")
        for r in g.itertuples():
            n = shares_at(s_, r.as_of)
            if not n:
                continue
            mc = float(r.close) * n
            psr = per = None
            if r.period_end in qm.index:
                q = qm.loc[r.period_end]
                if q.k >= 4:
                    psr = mc / q.rv4 if q.rv4 and q.rv4 > 0 else None
                    per = mc / q.ni4 if q.ni4 and q.ni4 > 0 else None
            upd.append((mc, psr, per, int(r.rid)))
    con.executemany("UPDATE factor_weekly SET marcap=?, psr=?, per=? WHERE rowid=?", upd)
    con.commit()
    last = con.execute("SELECT MAX(as_of) FROM factor_weekly WHERE factor_ver=?", (VER,)).fetchone()[0]
    left = con.execute("SELECT COUNT(DISTINCT sym) FROM factor_weekly WHERE factor_ver=? AND as_of=? "
                       "AND marcap IS NULL", (VER, last)).fetchone()[0]
    tot = con.execute("SELECT COUNT(DISTINCT sym) FROM factor_weekly WHERE factor_ver=? AND as_of=?",
                      (VER, last)).fetchone()[0]
    # 2026-11-15 — '행이 없음'(그 주 주봉이 아직 안 들어옴)과 '시총이 빔'을 구분한다. 예전엔 둘 다 '시총 결측'으로 보고했다.
    _r = {x: con.execute("SELECT marcap IS NULL FROM factor_weekly WHERE factor_ver=? AND as_of=? AND sym=?",
                         (VER, last, x)).fetchone() for x in sentinels}
    bad = [x for x, v in _r.items() if v == (1,)]
    miss = [x for x, v in _r.items() if v is None]
    if miss:
        print(f"::error title=파수꾼 주차 없음::{miss} 의 최신주({last}) 행이 없다 — 주봉 미도착(주차 완성도 확인 단계가 막았어야 함)", flush=True)
        sys.exit(1)
    con.close()
    print(f"→ {len(upd):,}행 채움 · 최신주({last}) 시총 결측 {left:,}/{tot:,}종", flush=True)
    if bad:
        print(f"::error title=시총 결측 파수꾼::{bad} 의 최신주 시총이 비어 있다", flush=True)
        sys.exit(1)
    if tot and left / tot > 0.15:
        print(f"::error title=시총 결측::최신주 {left}/{tot}종({left/tot:.0%}) 시총이 비어 있다", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "fetch":
        _args = [a for a in sys.argv[2:] if not a.startswith('--')]
        # --full: 분할 소급조정을 전부 반영하는 전수 재수집(분기 1회면 충분하다)
        cmd_fetch(int(_args[0]) if _args else 250, full='--full' in sys.argv)
    elif cmd == "update":
        # --no-repair: 분할 썩음 수리를 건너뛴다(시간이 급할 때. 썩음은 다음 회차로 밀린다)
        build(incremental=True, repair='--no-repair' not in sys.argv)
    elif cmd == "rot":
        # 측정만 — 고치지 않는다. `python leaders_build.py rot [since] [--log]`
        #   --log: 측정 결과를 results/split_rot.json 에 남긴다(repaired_n=0, mode=measure).
        #   정답 점검은 mode=measure 기록을 '수리 전 측정'으로 보고 상한 비교를 하지 않는다.
        _c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        _since = next((a for a in sys.argv[2:] if not a.startswith('--')), "2018-01-01")
        _rot, _n, _k = find_rot(_c, VER, since=_since)
        _tot = _c.execute("SELECT COUNT(*) FROM factor_weekly WHERE factor_ver=? AND as_of>=?",
                          (VER, _since)).fetchone()[0]
        _c.close()
        print(f"[{VER}] {_since}~ 분할 썩음: {_k}종 · {_n:,}행 / 전체 {_tot:,}행 ({_n / max(_tot, 1):.2%})")
        print(f"  영향 큰 순 상위 30: {_rot[:30]}")
        if '--log' in sys.argv:
            _rot_log(dict(asof=time.strftime("%Y-%m-%d"), ver=VER, tol=REPAIR_TOL, since=_since,
                          syms=_k, rows=_n, repaired=[], repaired_n=0, remaining=_k,
                          skipped_not_in_universe=0, repair_max=0, mode="measure"))
    elif cmd == "newsyms":
        build(newsyms=True)
    elif cmd == "fixcap":
        fixcap()
    else:
        build(sys.argv[2] if len(sys.argv) > 2 else "2018-01-01")
