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
from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd
import requests

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "leaders_cache")
os.makedirs(CACHE, exist_ok=True)
DB = os.path.join(DATA, "market.db")
VER = "v1"

YUA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                     '(KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
SUA = {'User-Agent': 'leaders-research pcy604604@gmail.com', 'Accept-Encoding': 'gzip, deflate'}
REV = ['RevenueFromContractWithCustomerExcludingAssessedTax', 'Revenues', 'SalesRevenueNet',
       'RevenueFromContractWithCustomerIncludingAssessedTax']
TAGS = {'revenue': REV, 'gross': ['GrossProfit'],
        'opinc': ['OperatingIncomeLoss'], 'netinc': ['NetIncomeLoss']}


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
def fetch_px(sym):
    """일봉을 받아 월요일 기준 주봉으로 직접 리샘플.
       ※ Yahoo의 interval=1wk는 period1 앵커 요일로 묶여(목~수) 실적주 정렬이 틀어짐."""
    pd_, pw = os.path.join(CACHE, f"dy_{sym}.csv"), os.path.join(CACHE, f"px_{sym}.csv")
    if os.path.exists(pw) and os.path.exists(pd_):
        return True
    raw = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
              f"?period1=1356998400&period2=1893456000&interval=1d", YUA)
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
        if len(d) < 300:
            return False
        ratio = d['Adj'] / d['Close']
        for c in ('Open', 'High', 'Low'):
            d[c] = d[c] * ratio
        d['Close'] = d['Adj']
        d = d[['Open', 'High', 'Low', 'Close', 'Volume']]
        d.to_csv(pd_)
        # 월요일 라벨 주봉 (W-MON: 그 주 월요일이 인덱스)
        w = d.resample('W-MON', label='left', closed='left').agg(
            {'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'}).dropna()
        # ★ 진행 중인 주(미완성 봉) 제거 — 금요일까지 데이터가 없으면 그 주는 버린다
        if len(w) and (d.index[-1] - w.index[-1]).days < 4:
            w = w.iloc[:-1]
        w.to_csv(pw)
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


def fetch_fund(sym, cik):
    p = os.path.join(CACHE, f"fq_{sym}.csv")
    if os.path.exists(p):
        return True
    raw = get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json", SUA)
    if not raw:
        return False
    try:
        facts = json.loads(raw)
        ser = {k: qseries(facts, v) for k, v in TAGS.items()}
        ends = sorted(ser['revenue'])
        if len(ends) < 8:
            return False
        rows = []
        for en in ends:
            fl = min(x[1] for x in (ser[k].get(en) for k in TAGS) if x)
            rows.append(dict(period_end=en, filed_at=fl,
                             **{k: (ser[k][en][0] if en in ser[k] else None) for k in TAGS}))
        pd.DataFrame(rows).to_csv(p, index=False)
        return True
    except Exception:
        return False


def fetch_8k(sym, cik):
    """8-K item 2.02 = 실적 발표. acceptanceDateTime으로 BMO/AMC 판정"""
    p = os.path.join(CACHE, f"ek_{sym}.csv")
    if os.path.exists(p):
        return True
    raw = get(f"https://data.sec.gov/submissions/CIK{cik}.json", SUA)
    if not raw:
        return False
    try:
        j = json.loads(raw)
        recent = j.get('filings', {}).get('recent', {})
        frames = [recent]
        for f in j.get('filings', {}).get('files', [])[:4]:
            r2 = get(f"https://data.sec.gov/submissions/{f['name']}", SUA)
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


def cmd_fetch(n, lo=1.5e8, hi=None):   # 2026-08-14: 5e8 -> 1.5e8 (대시세는 소형에서 시작한다)
    u = universe(n, lo, hi)
    cm = cikmap()
    print(f"유니버스 {len(u)}종 (시총 {lo/1e9:.0f}B~{(hi/1e9 if hi else 999):.0f}B)", flush=True)
    syms = u.sym.tolist()

    def job(s):
        ok_px = fetch_px(s)
        cik = cm.get(s.upper())
        ok_f = fetch_fund(s, cik) if cik else False
        ok_e = fetch_8k(s, cik) if cik else False
        return s, ok_px, ok_f, ok_e
    t0 = time.time(); done = [0, 0, 0]
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, (s, a, b, c) in enumerate(ex.map(job, syms), 1):
            done[0] += a; done[1] += b; done[2] += c
            if i % 25 == 0:
                print(f"  {i}/{len(syms)}  가격{done[0]} 재무{done[1]} 8K{done[2]}  "
                      f"{time.time()-t0:.0f}s", flush=True)
    u.to_csv(os.path.join(CACHE, "_universe.csv"), index=False)
    print(f"완료 {time.time()-t0:.0f}s  가격{done[0]} 재무{done[1]} 8K{done[2]}")


# ───────────────────── 3) 팩터 계산 → DB ─────────────────────
def bench():
    p = os.path.join(CACHE, "px_SPY.csv")
    if not os.path.exists(p):
        fetch_px("SPY")
    return pd.read_csv(p, index_col=0, parse_dates=True)["Close"]


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
    _SHARES = {s: (pd.to_datetime(g.filed.values), g.shares_adj.values.astype(float))
               for s, g in d.groupby("sym", sort=False)}
    print(f"주식수 시계열 {len(d):,}행 · {len(_SHARES):,}종", flush=True)
    return _SHARES


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


def build(start="2018-01-01", incremental=False, newsyms=False):
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
    if newsyms:
        have = {r[0] for r in con.execute(
            "SELECT DISTINCT sym FROM factor_weekly WHERE factor_ver=?", (VER,))}
        before = len(u)
        u = u[~u.sym.isin(have)]
        print(f"신규 종목 모드 — 기존 {len(have):,}종 건너뜀, "
              f"{len(u):,}종만 적재 (유니버스 {before:,})", flush=True)
    elif incremental:
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
    total = 0
    for _, row in u.iterrows():
        s = row.sym
        pp = os.path.join(CACHE, f"px_{s}.csv")
        fp = os.path.join(CACHE, f"fq_{s}.csv")
        if not (os.path.exists(pp) and os.path.exists(fp)):
            continue
        w = pd.read_csv(pp, index_col=0, parse_dates=True).sort_index()
        if len(w) < 80:
            continue
        # ★ 계산할 새 주차가 없으면 일봉·재무 로드 전에 바로 스킵
        if w.index[-1] < pd.Timestamp(start):
            continue
        dyp = os.path.join(CACHE, f"dy_{s}.csv")
        dly = (pd.read_csv(dyp, index_col=0, parse_dates=True).sort_index()
               if os.path.exists(dyp) else None)
        f = pd.read_csv(fp)
        f["period_end"] = pd.to_datetime(f.period_end)
        f["filed_at"] = pd.to_datetime(f.filed_at, errors="coerce")
        f = f.dropna(subset=["filed_at"]).sort_values("filed_at").reset_index(drop=True)
        if len(f) < 6:
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
        i_start = max(60, int(np.searchsorted(w.index, pd.Timestamp(start))))
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
    print(con.execute("SELECT COUNT(DISTINCT sym), MIN(as_of), MAX(as_of) FROM factor_weekly").fetchone())
    con.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fetch"
    if cmd == "fetch":
        cmd_fetch(int(sys.argv[2]) if len(sys.argv) > 2 else 250)
    elif cmd == "update":
        build(incremental=True)
    elif cmd == "newsyms":
        build(newsyms=True)
    else:
        build(sys.argv[2] if len(sys.argv) > 2 else "2018-01-01")
