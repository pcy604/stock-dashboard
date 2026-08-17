# -*- coding: utf-8 -*-
"""
marketcap_refresh.py — 미국 시총을 매일 다시 만든다 (SEC 공시 주식수 × 최신 종가)

왜 만들었나 (2026-08-18):
  data/us_marketcap.csv 가 **2024년 4~5월 손수 받은 스냅샷**이었다. 27개월간 아무도
  갱신하지 않았고, 생산 스크립트도 없었다. 결과가 셋 겹쳐 터졌다.

    1) 수집 유니버스가 낡은 시총으로 정해진다(leaders_build.universe).
       AXTI 는 스냅샷 당시 $151M 이라 하한을 겨우 넘겼고, 그 뒤 60배 올라
       실제 $5.4B 인데 우리 DB 는 여전히 $151M 로 본다.
    2) leaders_build 가 주식수를 `낡은시총 ÷ 최신종가` 로 역산한다(line 395).
       → 주식수가 (실제주가/스냅샷주가) 배만큼 틀리고, 그 오차가
         marcap·PER·PSR **전부**에 그대로 곱해진다. 전 주차 동일 배수로.
       실측: 2,476종 중 시총 오차 ±25% 안은 681종(27.5%)뿐.
    3) 그래서 규칙⑥의 `marcap >= $2B` 문턱이 실제로는
       `진짜시총 >= 2B × 오차배수` 가 된다. 오차배수는 '스냅샷 이후 많이 오른 종목'
       일수록 크므로, **가장 크게 오른 종목일수록 구조적으로 배제**된다.
       실측: 실제로 $2B 넘는데 DB가 못 보는 종목 212종 (RKLB·ASTS·IONQ·SITM…).

설계:
  · 주식수는 역산하지 않는다. SEC XBRL `dei:EntityCommonStockSharesOutstanding`
    을 쓴다 — 표지에 찍히는 공시 주식수이고 `filed`(제출일)가 붙어 있어
    "그 시점에 알 수 있었던 값"으로 쓸 수 있다(look-ahead 없음).
  · 시총 = 주식수 × 종가. 종가는 매일 갱신되므로 **시총도 매일 자동으로 맞다.**
    주식수만 분기에 한 번 바뀌니 SEC 조회는 20일 캐시로 충분하다.
  · ⚠️ 분할 주의. SEC 주식수는 '그때 그대로' 값이고 우리 가격 캐시는
    소급 분할조정된 값이다. **현재 시총**은 둘 다 오늘 기준이라 문제없지만,
    **과거 시계열**은 분할배수로 보정해야 한다 → us_shares.csv 의 shares_adj
    (오늘 주식수 기준으로 환산) 를 쓴다. 분할 이력은 Yahoo events=split.

산출물:
  data/us_marketcap.csv  — 기존 스키마 유지(Rank,Name,Symbol,marketcap,price (USD),country)
                           + shares, px_date, as_of 추가. 소비자 5곳이 이 스키마를 읽는다.
  data/us_shares.csv     — sym,filed,end,shares,shares_adj  (백테스트용 point-in-time 시계열)

CLI
  python marketcap_refresh.py frames     # SEC frames — 분기당 1콜로 5천개사 (주경로)
  python marketcap_refresh.py shares     # 종목별 companyconcept — frames 빈칸 메우기
  python marketcap_refresh.py splits     # 분할 이력 (Yahoo)
  python marketcap_refresh.py build      # 위 결과 + 종가 → us_marketcap.csv
  python marketcap_refresh.py all        # frames → shares → splits → build
    --all-tickers   가격캐시 없는 종목까지 (edgar_cik 전체 1만종, 신규 발굴용)
    --net-price     가격캐시가 없으면 시세를 받아 온다 (GitHub Actions 용)
    --force         주식수 캐시 무시하고 다시 받는다

운영:
  · 매일  : `build --net-price`  — 주가만 바뀌므로 이것만으로 시총이 최신이 된다
  · 주 1회: `frames` + `shares`  — 새 공시 반영 (us_shares.csv 갱신)
"""
import json, os, sys, time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
CACHE = os.path.join(DATA, "leaders_cache")
SHDIR = os.path.join(DATA, "shares_cache")
OUT_MC = os.path.join(DATA, "us_marketcap.csv")
OUT_SH = os.path.join(DATA, "us_shares.csv")
SPLITS = os.path.join(DATA, "us_splits.csv")

SUA = {"User-Agent": "leaders-research pcy604604@gmail.com",
       "Accept-Encoding": "gzip, deflate"}
YUA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"}
STALE_DAYS = 20          # 주식수는 분기 공시라 20일이면 충분하다
WORKERS = 8

# dei 가 없는 종목(외국계·구형 제출인)을 위한 대체 태그. 앞에서부터 먼저 잡히는 걸 쓴다.
FALLBACK = ["CommonStockSharesOutstanding", "CommonStockSharesIssued"]


class Missing(Exception):
    """그 태그가 정말 없다(404). 재시도해도 소용없고 다음 태그로 넘어가야 한다."""


def get(url, hdr, tries=4):
    """⚠️ 403 을 '없음'으로 처리하면 안 된다. SEC 는 속도제한을 403 으로 응답한다.
    첫 판에서 이걸 즉시 포기 처리하는 바람에 BAC·IBM 처럼 데이터가 멀쩡히 있는
    종목이 763종이나 '주식수 없음'으로 캐시됐다. 404 만 확정 부재로 본다."""
    import urllib.request, urllib.error
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=hdr)
            with urllib.request.urlopen(req, timeout=25) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise Missing()
            time.sleep(1.2 * (k + 1))          # 403=속도제한 → 물러섰다 다시
        except Exception:
            time.sleep(0.8 * (k + 1))
    return None


def cikmap():
    return {k.upper(): str(v).zfill(10) for k, v in
            json.load(open(os.path.join(DATA, "edgar_cik.json"), encoding="utf-8")).items()}


# ───────────────────────── 1) SEC 주식수 ─────────────────────────
def _pull_shares(sym, cik):
    """dei 우선, 없으면 us-gaap 대체 태그.

    ⚠️ 복수 종류주식(GOOG·KO 등)은 태그에 ClassOfStockAxis 차원이 붙는데
    companyconcept API 는 차원 붙은 사실을 빼고 준다 → 여기서 빈값이 나온다.
    그런 종목은 frames 로도 안 잡히는 경우가 있어 최종적으로 못 얻을 수 있다.
    실패를 빈 리스트로 캐시하지 않는다 — None 을 돌려 다음 실행에서 다시 시도한다.
    """
    hit = False
    for ns, tag in [("dei", "EntityCommonStockSharesOutstanding")] + \
                   [("us-gaap", t) for t in FALLBACK]:
        try:
            raw = get(f"https://data.sec.gov/api/xbrl/companyconcept/"
                      f"CIK{cik}/{ns}/{tag}.json", SUA)
        except Missing:
            hit = True                    # 404 = 확정 부재. 조회 자체는 성공한 셈.
            continue
        if not raw:
            continue                      # 403/타임아웃 — 실패지 '없음'이 아니다
        hit = True
        try:
            units = json.loads(raw).get("units", {}).get("shares", [])
        except Exception:
            continue
        rows = [dict(end=e.get("end"), filed=e.get("filed"), shares=float(e["val"]))
                for e in units
                if e.get("end") and e.get("filed") and e.get("val")]
        if rows:
            return rows
    return [] if hit else None            # None = 네트워크 실패 → 캐시하지 않는다


def fetch_shares(sym, cik, force=False):
    p = os.path.join(SHDIR, f"{sym}.json")
    if not force and os.path.exists(p):
        age = (time.time() - os.path.getmtime(p)) / 86400
        try:
            empty = json.load(open(p, encoding="utf-8")) == []
        except Exception:
            empty = True
        # 빈 결과는 짧게만 믿는다. 첫 판에 403 을 '없음'으로 굳혀버린 사고 재발 방지.
        if age < (2 if empty else STALE_DAYS):
            return None
    rows = _pull_shares(sym, cik)
    if rows is None:
        return None                       # 실패 — 파일을 쓰지 않는다
    os.makedirs(SHDIR, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(rows, f)
    return len(rows)


# ── frames: 한 번에 전 종목 ────────────────────────────────────────
# companyconcept 는 종목당 1콜(2,460종 = 20분)인데 frames 는 분기당 1콜로
# 4,000~5,000개사를 한꺼번에 준다. 이게 주경로여야 한다.
#   I 접미(CY2026Q2I) = 시점값(주식수), 접미 없음(CY2026Q2) = 기간값(가중평균주식수)
FRAMES = [("dei", "EntityCommonStockSharesOutstanding", True),
          ("us-gaap", "CommonStockSharesOutstanding", True),
          ("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding", False),
          ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", False)]
FRAMES_CSV = os.path.join(DATA, "shares_frames.csv")


def cmd_frames(since=2017):
    cm = cikmap()
    inv = {}
    for s, c in cm.items():                      # 같은 CIK 에 티커 여럿이면 짧은 쪽
        k = c.lstrip("0")
        if k not in inv or len(s) < len(inv[k]):
            inv[k] = s
    now = pd.Timestamp.today()
    qs = [f"CY{y}Q{q}" for y in range(since, now.year + 1) for q in (1, 2, 3, 4)
          if not (y == now.year and (q - 1) * 3 + 1 > now.month)]
    jobs = [(ns, tag, q + ("I" if inst else "")) for ns, tag, inst in FRAMES for q in qs]
    print(f"frames {len(jobs)}콜 ({len(qs)}분기 × {len(FRAMES)}태그)", flush=True)
    rows, n = [], {"i": 0}

    def work(a):
        ns, tag, q = a
        try:
            raw = get(f"https://data.sec.gov/api/xbrl/frames/{ns}/{tag}/shares/{q}.json", SUA)
        except Missing:
            raw = None
        n["i"] += 1
        if n["i"] % 40 == 0:
            print(f"  {n['i']}/{len(jobs)}", flush=True)
        if not raw:
            return []
        try:
            data = json.loads(raw)["data"]
        except Exception:
            return []
        out = []
        for c in data:
            s = inv.get(str(c.get("cik")))
            if s and c.get("val") and c.get("end"):
                out.append((s, c["end"], float(c["val"]), tag))
        return out

    with ThreadPoolExecutor(WORKERS) as ex:
        for r in ex.map(work, jobs):
            rows += r
    d = pd.DataFrame(rows, columns=["sym", "end", "shares", "tag"])
    # 같은 (종목, 분기말)에 태그가 겹치면 FRAMES 우선순위대로 하나만 남긴다
    order = {t: i for i, (_, t, _) in enumerate(FRAMES)}
    d["o"] = d.tag.map(order)
    d = d.sort_values("o").drop_duplicates(["sym", "end"], keep="first").drop(columns="o")
    d.sort_values(["sym", "end"]).to_csv(FRAMES_CSV, index=False)
    print(f"→ {FRAMES_CSV}  ({len(d):,}행 · {d.sym.nunique():,}종)", flush=True)


def cmd_shares(syms, force=False):
    cm = cikmap()
    todo = [(s, cm[s]) for s in syms if s in cm]
    print(f"SEC 주식수 조회 {len(todo)}종 (캐시 {STALE_DAYS}일)", flush=True)
    done = {"n": 0, "hit": 0}

    def work(a):
        r = fetch_shares(*a, force=force)
        done["n"] += 1
        if r:
            done["hit"] += 1
        if done["n"] % 250 == 0:
            print(f"  {done['n']}/{len(todo)}  (신규 {done['hit']})", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, todo))
    print(f"완료 — 신규·갱신 {done['hit']}종", flush=True)


# ───────────────────────── 2) 분할 이력 ─────────────────────────
def _pull_splits(sym):
    """월봉 + events=split. 페이로드가 작아 전 종목 돌려도 가볍다."""
    raw = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
              f"?period1=946684800&period2=1893456000&interval=1mo&events=split", YUA)
    if not raw:
        return []
    try:
        ev = json.loads(raw)["chart"]["result"][0].get("events", {}).get("splits", {})
    except Exception:
        return []
    out = []
    for e in ev.values():
        try:
            out.append(dict(sym=sym,
                            date=str(pd.Timestamp(int(e["date"]), unit="s").date()),
                            ratio=float(e["numerator"]) / float(e["denominator"])))
        except Exception:
            pass
    return out


def cmd_splits(syms):
    print(f"분할 이력 조회 {len(syms)}종", flush=True)
    rows, n = [], {"i": 0}

    def work(s):
        r = _pull_splits(s)
        n["i"] += 1
        if n["i"] % 250 == 0:
            print(f"  {n['i']}/{len(syms)}", flush=True)
        return r

    with ThreadPoolExecutor(WORKERS) as ex:
        for r in ex.map(work, syms):
            rows += r
    d = pd.DataFrame(rows, columns=["sym", "date", "ratio"])
    d.to_csv(SPLITS, index=False)
    print(f"→ {SPLITS}  ({len(d)}건 · {d.sym.nunique() if len(d) else 0}종)", flush=True)


# ───────────────────────── 3) 조립 ─────────────────────────
FRAMES_LAG = 60          # frames 에는 제출일이 없다. 분기말 + 60일을 '알 수 있게 된 날'로 본다.
                         # 미국 대형가속제출인 10-Q 40일 / 10-K 60일 → 60은 보수적(늦게 잡음)이다.
                         # 보수적이어야 look-ahead 가 안 생긴다.


def load_shares_series():
    """{sym: DataFrame(end, filed, shares)} — filed 오름차순.

    두 출처를 합친다. 같은 (종목, 분기말) 이 겹치면 **companyconcept 우선** —
    거기엔 실제 제출일(filed)이 있어 point-in-time 이 정확하다.
    frames 는 제출일이 없어 분기말+60일로 근사하므로 빈칸 메우기용이다.
    """
    parts = []
    if os.path.isdir(SHDIR):
        for fn in os.listdir(SHDIR):
            if not fn.endswith(".json"):
                continue
            try:
                rows = json.load(open(os.path.join(SHDIR, fn), encoding="utf-8"))
            except Exception:
                continue
            if rows:
                d = pd.DataFrame(rows)
                d["sym"], d["src"] = fn[:-5], 0
                parts.append(d[["sym", "end", "filed", "shares", "src"]])
    if os.path.exists(FRAMES_CSV):
        f = pd.read_csv(FRAMES_CSV)
        if len(f):
            f["filed"] = (pd.to_datetime(f.end) +
                          pd.Timedelta(days=FRAMES_LAG)).dt.strftime("%Y-%m-%d")
            f["src"] = 1
            parts.append(f[["sym", "end", "filed", "shares", "src"]])
    if not parts:
        return {}
    a = pd.concat(parts, ignore_index=True).dropna(subset=["sym", "end", "filed", "shares"])
    a = (a.sort_values(["sym", "end", "src"])
           .drop_duplicates(["sym", "end"], keep="first")           # concept 우선
           .sort_values(["sym", "filed", "end"])
           .drop_duplicates(["sym", "filed"], keep="last"))         # 같은 제출일이면 최근 분기
    n_c = int((a.src == 0).sum())
    print(f"  주식수 출처 — companyconcept {n_c:,}행 · frames {len(a)-n_c:,}행")
    return {s: g.drop(columns="src").reset_index(drop=True)
            for s, g in a.groupby("sym", sort=False)}


def split_factors():
    """{sym: DataFrame(date, ratio)} — 그 날짜 '이전' 주식수에 곱해야 오늘 기준이 된다."""
    if not os.path.exists(SPLITS):
        return {}
    d = pd.read_csv(SPLITS)
    return {s: g.sort_values("date") for s, g in d.groupby("sym")} if len(d) else {}


def last_price(sym):
    p = os.path.join(CACHE, f"px_{sym}.csv")
    if not os.path.exists(p):
        return None, None
    try:
        d = pd.read_csv(p, index_col=0, parse_dates=True)
        if not len(d) or "Close" not in d.columns:
            return None, None
        return float(d.Close.iloc[-1]), str(d.index[-1].date())
    except Exception:
        return None, None


def quote(sym):
    """가격 캐시가 없을 때(=GitHub Actions) 최근 종가만 가볍게 받는다.
    data/leaders_cache 는 저장소에 없으므로 CI 에서는 이 경로를 탄다."""
    try:
        raw = get(f"https://query2.finance.yahoo.com/v8/finance/chart/{sym}"
                  f"?range=10d&interval=1d", YUA, tries=2)
    except Missing:
        return None, None
    if not raw:
        return None, None
    try:
        r = json.loads(raw)["chart"]["result"][0]
        cl = [v for v in r["indicators"]["quote"][0]["close"] if v]
        ts = r["timestamp"]
        if not cl:
            return None, None
        return float(cl[-1]), str(pd.Timestamp(int(ts[-1]), unit="s").date())
    except Exception:
        return None, None


def cmd_build(net_price=False):
    sh = load_shares_series()
    sp = split_factors()
    print(f"주식수 보유 {len(sh)}종 · 분할 이력 {len(sp)}종", flush=True)

    name = {}
    if os.path.exists(OUT_MC):
        old = pd.read_csv(OUT_MC)
        name = dict(zip(old.Symbol.astype(str), old.Name.astype(str)))

    # 캐시에 가격이 없는 종목은 (CI 등에서) 시세를 받아 온다. 로컬은 거의 안 탄다.
    prices = {}
    if net_price:
        need = [s for s in sh if not os.path.exists(os.path.join(CACHE, f"px_{s}.csv"))]
        print(f"가격 캐시 없는 {len(need)}종 시세 조회", flush=True)
        n = {"i": 0}

        def w(s):
            r = quote(s)
            n["i"] += 1
            if n["i"] % 500 == 0:
                print(f"  {n['i']}/{len(need)}", flush=True)
            return s, r

        with ThreadPoolExecutor(WORKERS) as ex:
            for s, r in ex.map(w, need):
                if r[0]:
                    prices[s] = r

    mc_rows, ts_rows = [], []
    for sym, d in sh.items():
        px, pxd = last_price(sym)
        if px is None:
            px, pxd = prices.get(sym, (None, None))
        latest = float(d.shares.iloc[-1])

        # ── 과거 주식수를 '오늘 기준'으로 환산 (분할 보정) ──
        # 가격 캐시는 소급 분할조정돼 있는데 SEC 주식수는 그때 그대로다.
        # 분할일 t 의 비율 r 은 t 이전 공시 주식수에 곱해야 오늘 기준이 된다.
        adj = d.shares.astype(float).copy()
        g = sp.get(sym)
        if g is not None:
            for _, e in g.iterrows():
                m = d.filed < str(e["date"])
                adj = adj.where(~m, adj * float(e["ratio"]))
        for k in range(len(d)):
            ts_rows.append(dict(sym=sym, filed=d.filed.iloc[k], end=d.end.iloc[k],
                                shares=float(d.shares.iloc[k]),
                                shares_adj=float(adj.iloc[k])))

        if px is None or latest <= 0:
            continue
        mc_rows.append(dict(Name=name.get(sym, sym), Symbol=sym,
                            marketcap=latest * px, **{"price (USD)": px},
                            country="United States", shares=latest,
                            px_date=pxd, as_of=str(pd.Timestamp.today().date())))

    ts = pd.DataFrame(ts_rows).sort_values(["sym", "filed"])
    ts["as_of"] = str(pd.Timestamp.today().date())   # data_freshness 감시용
    ts.to_csv(OUT_SH, index=False)
    print(f"→ {OUT_SH}  ({len(ts_rows):,}행 · {len(sh)}종)", flush=True)

    m = pd.DataFrame(mc_rows).sort_values("marketcap", ascending=False).reset_index(drop=True)
    m.insert(0, "Rank", m.index + 1)
    m = m[["Rank", "Name", "Symbol", "marketcap", "price (USD)", "country",
           "shares", "px_date", "as_of"]]
    m.to_csv(OUT_MC, index=False)
    print(f"→ {OUT_MC}  ({len(m):,}종)", flush=True)
    for lo, lab in [(2e9, "$2B+"), (1e9, "$1B+"), (3e8, "$300M+"), (1.5e8, "$150M+")]:
        print(f"    {lab:<8} {(m.marketcap >= lo).sum():>5}종")


def universe_syms(all_tickers=False):
    if all_tickers:
        return sorted(cikmap())
    return sorted({f[3:-4] for f in os.listdir(CACHE) if f.startswith("px_")})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    a = [x for x in sys.argv[1:] if not x.startswith("--")]
    fl = {x for x in sys.argv[1:] if x.startswith("--")}
    cmd = a[0] if a else "all"
    syms = universe_syms("--all-tickers" in fl)
    if cmd in ("frames", "all"):
        cmd_frames()
    if cmd in ("shares", "all"):
        cmd_shares(syms, force="--force" in fl)
    if cmd in ("splits", "all"):
        cmd_splits(syms)
    if cmd in ("build", "all"):
        cmd_build(net_price="--net-price" in fl)
