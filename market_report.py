# -*- coding: utf-8 -*-
"""시황 리포트 — 매일(전일 시장)·매주(지난주) 발행. results/market_report.json

2026-10-14 신설 (사용자 요청: "사이트 내 챗봇 — 어제 시장·주간 시황 리포트 발행 용도")

구조
  1) facts()   — 숫자만 모은다. 지수(Yahoo) · 레포 산출물(perf_latest·CANSLIM·이익가속·흑자전환)
  2) render()  — Gemini 가 **facts 안의 숫자만으로** 한국어 리포트를 쓴다.
                 키가 없거나 한도(무료 하루 20건/모델)에 걸리면 숫자 템플릿으로 대체한다 —
                 리포트는 어떤 경우에도 발행된다. 어떤 방식으로 썼는지 'engine' 에 남긴다.
  3) 저장       — latest_daily / latest_weekly + history(최근 60건)
  대시보드 📰 시황 리포트 탭과 챗봇이 이 파일을 근거로 쓴다.

  python market_report.py daily [--telegram]   # 미국 장 마감 후(KST 06:30) — 미국 중심 + 전 시장 표
  python market_report.py kr                   # 한국 장 마감 후(KST 15:50) — 한국 지수·오늘 등락·수급 폭 (2026-10-21)
  python market_report.py weekly [--telegram]
"""
import json
import os
import sys
from datetime import datetime, date, timedelta, timezone


def _now_kst() -> str:
    """2026-11-12 리포트 꼬리 시각이 CI(UTC) 기준이라 15:45 KST 리포트가 '06:45' 로 보였다 — 한국 시각으로 찍는다."""
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "market_report.json")
INDICES = [("^KS11", "코스피"), ("^KQ11", "코스닥"), ("^GSPC", "S&P500"), ("^IXIC", "나스닥"), ("^DJI", "다우"),
           ("^SOX", "필라델피아 반도체"), ("^VIX", "VIX"), ("KRW=X", "원/달러"), ("^TNX", "미국 10년물(%)")]
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]   # 2026-11-14 gemini-2.0-flash 는 404(종료)


def _j(p):
    try:
        return json.load(open(os.path.join(BASE, p), encoding="utf-8"))
    except Exception:
        return {}


def _r(v, n=2):
    return None if v is None or v != v else round(float(v), n)


_FDR = {"^KS11": "KS11", "^KQ11": "KQ11"}   # Yahoo 가 막히면 한국 지수는 FDR 로


def _series(sym, df):
    s = None
    try:
        if df is not None and sym in df:
            s = df[sym].dropna()
    except Exception:
        s = None
    if (s is None or len(s) < 30) and sym in _FDR:
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            s = fdr.DataReader(_FDR[sym], (date.today() - timedelta(days=400)).isoformat())["Close"].dropna()
        except Exception:
            s = None
    return s


def kr_pulse(sym):
    """오닐 방식 시장 방향(market_pulse) — 종가·거래량 일봉. Yahoo 먼저, 안 되면 FDR. 2026-11-12 종합 진단."""
    import market_pulse as _mp
    c = v = None
    try:
        import yfinance as yf
        d = yf.download(sym, period="1y", interval="1d", progress=False, auto_adjust=False)
        if d is not None and len(d):
            c = d["Close"].squeeze().dropna()
            v = d["Volume"].squeeze()
            if (v.fillna(0) == 0).mean() > 0.2:      # Yahoo 지수 거래량 빈칸 많으면 FDR 로
                c = v = None
    except Exception:
        c = v = None
    if c is None and sym in _FDR:
        try:
            import FinanceDataReader as fdr
            from datetime import timedelta
            d = fdr.DataReader(_FDR[sym], (date.today() - timedelta(days=400)).isoformat())
            c, v = d["Close"].dropna(), d["Volume"]
        except Exception:
            return {}
    if c is None:
        return {}
    c = drop_open_bar(c, sym)
    return _mp.pulse(c, v.reindex(c.index))


# 2026-10-21: 10-21 일간 리포트가 한국 09:26(장중)에 만들어져 코스피 장중 값이 '종가'로 찍혔다(실제 그날 +4%대).
#   장이 아직 열려 있는 시장의 '오늘 봉'은 미완성이라 버린다 — 언제 돌려도 마지막 확정 종가만 쓴다.
_SESSION = {"KR": ("Asia/Seoul", 15, 35), "US": ("America/New_York", 16, 5)}   # 마감 + 5분(종가 단일가 반영). 2026-11-06: 생성을 마감+10·15분으로 앞당김 — 여유가 15분이면 오늘 봉을 버린다
_MKT_OF = {"^KS11": "KR", "^KQ11": "KR", "^GSPC": "US", "^IXIC": "US", "^DJI": "US", "^SOX": "US", "^VIX": "US", "^TNX": "US"}


def drop_open_bar(s, sym, now=None):
    """시장이 아직 마감 전이면 오늘 날짜의 마지막 봉을 뺀다. 환율(KRW=X)은 24시간이라 그대로."""
    m = _MKT_OF.get(sym)
    if m is None or s is None or not len(s):
        return s
    from zoneinfo import ZoneInfo
    from datetime import timezone as _tz
    tzname, hh, mm = _SESSION[m]
    loc = (now or datetime.now(_tz.utc)).astimezone(ZoneInfo(tzname))
    if s.index[-1].date() == loc.date() and (loc.hour, loc.minute) < (hh, mm):
        return s.iloc[:-1]
    return s


# 2026-10-21 디테일 보강(사용자: "디테일이 넘 떨어짐") — 전문 데일리(증권사 모닝·Bloomberg 류)가 늘 싣는 것:
#   자산(달러·금·유가·구리·비트코인·장기채) · 업종 · 시총 상위 대장주. 전부 Yahoo 한 번에 받는다.
US_ASSETS = [("DX-Y.NYB", "달러인덱스"), ("GC=F", "금"), ("CL=F", "WTI 유가"), ("HG=F", "구리"),
             ("BTC-USD", "비트코인"), ("TLT", "미 장기채(TLT)")]
US_SECTORS = [("XLK", "기술"), ("XLC", "통신서비스"), ("XLY", "경기소비재"), ("XLF", "금융"), ("XLV", "헬스케어"),
              ("XLI", "산업재"), ("XLE", "에너지"), ("XLB", "소재"), ("XLP", "필수소비재"), ("XLU", "유틸리티"),
              ("XLRE", "부동산")]
US_MEGA = [("NVDA", "엔비디아"), ("MSFT", "마이크로소프트"), ("AAPL", "애플"), ("GOOGL", "알파벳"),
           ("AMZN", "아마존"), ("META", "메타"), ("AVGO", "브로드컴"), ("TSLA", "테슬라"), ("BRK-B", "버크셔"),
           ("JPM", "JP모건")]


def _download(syms):
    try:
        import yfinance as yf
        return yf.download(list(syms), period="1y", interval="1d", progress=False,
                           auto_adjust=False, threads=True)["Close"]
    except Exception:
        return None


def _spark(s, n=63):
    """종합 글로벌 마켓 스파크라인 — 최근 3개월(≈63거래일) 종가, 유효숫자 5자리. 2026-11-15."""
    try:
        return [float(f"{float(x):.5g}") for x in s.iloc[-n:].tolist()]
    except Exception:
        return None


def quote_facts(pairs, df=None, short=False):
    """(심볼, 이름) 목록 → 1일·5일 등락. short=True 면 지수용 긴 항목(1개월·52주·200일선)은 뺀다."""
    df = df if df is not None else _download([s for s, _ in pairs])
    out = []
    for sym, name in pairs:
        try:
            s = drop_open_bar(_series(sym, df), sym)
            if s is None or len(s) < 30:
                raise ValueError("시세 없음")
            c = s.iloc[-1]
            row = dict(name=name, sym=sym, date=str(s.index[-1].date()), close=_r(c),
                       d1=_r((c / s.iloc[-2] - 1) * 100), d5=_r((c / s.iloc[-6] - 1) * 100))
            if not short:
                row.update(m1=_r((c / s.iloc[-22] - 1) * 100), from_52w_high=_r((c / s.max() - 1) * 100),
                           above_200d=bool(c > s.iloc[-200:].mean()) if len(s) >= 200 else None, spark=_spark(s))
            out.append(row)
        except Exception as e:
            out.append(dict(name=name, sym=sym, error=str(e)[:60]))
    return out


def us_extra_facts():
    pairs = US_ASSETS + US_SECTORS + US_MEGA
    df = _download([s for s, _ in pairs])
    q = {x["sym"]: x for x in quote_facts(pairs, df, short=True)}
    # 2026-11-14: 자산(달러·금·유가·비트코인)도 지수처럼 1개월·52주 고점·200일선 — 종합 카드 정보가 칸마다 달랐다
    q.update({x["sym"]: x for x in quote_facts(US_ASSETS, df, short=False)})
    pick = lambda L: [q[s] for s, _ in L if "close" in q.get(s, {})]
    sec = sorted(pick(US_SECTORS), key=lambda x: -x["d1"])
    return dict(assets=pick(US_ASSETS), sectors=sec, megacaps=pick(US_MEGA))


def intraday_range(rows):
    """2026-11-26 장중 흐름 — 종가만 보면 '나스닥 -4%까지 밀렸다가 회복' 같은 하루를 모른다(차니).
    같은 날짜 일봉의 고가·저가를 전일 종가 대비 %로(lo_pct·hi_pct)."""
    try:
        import yfinance as yf
        syms = [x["sym"] for x in rows if "close" in x and x["sym"] in ("^GSPC", "^IXIC", "^DJI", "^SOX", "^KS11", "^KQ11")]
        d = yf.download(syms, period="10d", interval="1d", progress=False, auto_adjust=False, threads=True)
    except Exception as e:
        print("  장중 범위 생략:", str(e)[:80])
        return rows
    for x in rows:
        try:
            if x["sym"] not in syms:
                continue
            hi, lo = d["High"][x["sym"]].dropna(), d["Low"][x["sym"]].dropna()
            day = next(i for i in hi.index if str(i.date()) == x["date"])
            prev = x["close"] / (1 + x["d1"] / 100)
            x["hi_pct"], x["lo_pct"] = _r((hi[day] / prev - 1) * 100), _r((lo[day] / prev - 1) * 100)
        except Exception:
            pass
    return rows


def index_facts():
    out = []
    df = _download([s for s, _ in INDICES])
    for sym, name in INDICES:
        try:
            s = drop_open_bar(_series(sym, df), sym)
            if s is None or len(s) < 30:
                raise ValueError("시세 없음")
            c = s.iloc[-1]
            out.append(dict(name=name, sym=sym, date=str(s.index[-1].date()), close=_r(c),
                            d1=_r((c / s.iloc[-2] - 1) * 100), d5=_r((c / s.iloc[-6] - 1) * 100),
                            m1=_r((c / s.iloc[-22] - 1) * 100), from_52w_high=_r((c / s.max() - 1) * 100),
                            above_200d=bool(c > s.iloc[-200:].mean()) if len(s) >= 200 else None, spark=_spark(s),
                            ma200=_r(s.iloc[-200:].mean()) if len(s) >= 200 else None))
            if sym in ("^GSPC", "^IXIC"):   # 2026-11-14 미국도 오닐식 시장 방향(종합 '시장 방향' 카드)
                try:
                    pz = kr_pulse(sym)
                    if pz:
                        out[-1]["pulse"] = pz
                except Exception as e:
                    print("  오닐 시장 방향(미국) 생략:", str(e)[:60])
            if sym in ("^KS11", "^KQ11"):   # 실전 v1.9 지수 게이트(주봉 5주선) — 봇 계획표·종합 탭과 같은 계산(verdict.weekly_gate). 2026-11-11
                try:
                    import verdict as _V
                    g = _V.weekly_gate(s)
                    if g:
                        out[-1]["gate5w"] = {k: g.get(k) for k in ("on", "gap", "week", "partial", "live_on", "live_gap")}
                except Exception as e:
                    print("  5주선 게이트 생략:", str(e)[:60])
                try:
                    pz = kr_pulse(sym)
                    if pz:
                        out[-1]["pulse"] = pz
                except Exception as e:
                    print("  오닐 시장 방향 생략:", str(e)[:60])
        except Exception as e:
            out.append(dict(name=name, sym=sym, error=str(e)[:60]))
    return out


def hy_fact():
    """하이일드 스프레드(ICE BofA US HY OAS, FRED BAMLH0A0HYM2) — 신용 스트레스. 2026-11-14 종합 카드.
    등락은 %가 아니라 bp(0.01%p) — 스프레드는 '수준의 변화'가 뜻이 있다. 키가 없으면 빈 값."""
    try:
        import verdict as _V
        obs = _V.fred_fetch("BAMLH0A0HYM2", 300)
        if len(obs) < 30:
            return {}
        v = [x[1] for x in obs]
        c = v[-1]
        bp = lambda k: _r((c - v[-1 - k]) * 100, 0) if len(v) > k else None
        ma = sum(v[-200:]) / len(v[-200:])
        return dict(name="하이일드 스프레드", sym="BAMLH0A0HYM2", date=obs[-1][0], close=_r(c), unit="bp",
                    d1=bp(1), d5=bp(5), m1=bp(21), from_52w_low=_r((c - min(v[-252:])) * 100, 0), spark=v[-63:],
                    above_200d=bool(c > ma))
    except Exception as e:
        print("  하이일드 스프레드 생략:", str(e)[:60])
        return {}


def stock_facts(kind):
    p = _j("results/perf_latest.json")
    st = p.get("stocks", [])
    key = "ret_1w" if kind == "daily" else "ret_4w"
    res = {"perf_date": p.get("date")}
    for m, cap in (("KR", 1e11), ("US", 3e8)):      # 2026-11-27 모수 통일 — 한국 1,000억+ · 미국 $3억+ (옛 1조+·$100억+)
        big = [s for s in st if s.get("market") == m and (s.get("marcap") or 0) >= cap and s.get(key) is not None]
        # 2026-10-15: 주간 리포트 강세 1위가 CFNB +4,465% 였다 — 대형주 4주 수익률로 불가능한 값
        #   (주식 분할·티커 재사용·시세 오류). 사실만 쓰는 리포트라 오류 숫자가 곧 거짓말이 된다.
        #   1주 ±60%·4주 ±150% 를 넘으면 데이터 의심으로 순위에서 빼고 개수만 남긴다.
        lim = 60 if key == "ret_1w" else 150
        sus = [s for s in big if abs(s[key]) > lim]
        big = [s for s in big if abs(s[key]) <= lim]
        big.sort(key=lambda s: s[key])
        row = lambda s: dict(name=s.get("name"), sym=s["sym"], ret=_r(s[key], 1))
        res[m] = dict(universe=len(big), basis=key, top=[row(s) for s in big[::-1][:6]],
                      bottom=[row(s) for s in big[:6]],
                      near_52w=sum(1 for s in st if s.get("market") == m and s.get("now_sig_52w")),
                      new_high=sum(1 for s in st if s.get("market") == m and s.get("new_high")),
                      excluded_suspect=[x["sym"] for x in sus],
                      breadth_up=round(sum(1 for s in big if s[key] > 0) / len(big) * 100) if big else None)
        hi = [s for s in st if s.get("market") == m and s.get("now_sig_52w")]
        hi.sort(key=lambda s: -(s.get("marcap") or 0))
        res[m]["52w_leaders"] = [dict(name=s.get("name"), sym=s["sym"]) for s in hi[:8]]
    return res


def signal_facts():
    md = _j("results/macro.json").get("canslim_m") or {}   # 지수 200일선 판정(verdict) — 2026-11-25 CANSLIM 산출물 폐기
    acc = _j("results/leaders_accel.json")
    ta = _j("results/turnaround_latest.json")
    return dict(
        market_direction={"KR": md.get("KR"), "US": md.get("US")},
        accel_week=acc.get("signal_week"),
        accel_new=[dict(sym=c.get("sym"), name=c.get("name"), up=c.get("up"), mc_b=c.get("mc"))
                   for c in (acc.get("candidates") or [])[:10]],
        turnaround={"KR": ta.get("kr"), "US": ta.get("us"), "date": ta.get("date")})


def verdict_facts():
    """이번 주 판정 — results/macro.json(verdict.py). 리포트가 지수를 따로 계산해 판정을 내리지 않는다(2026-10-21)."""
    v = _j("results/macro.json")
    c, a = v.get("core") or {}, v.get("alloc") or {}
    if not c:
        return {}
    return dict(asof=v.get("asof"), core_on=c.get("on"), core_gap_200d=c.get("gap"), changed=v.get("changed"),
                target_core_sat_cash=[a.get("core_now"), a.get("satellite"), a.get("cash_total")],
                kospi_above_200d=(v.get("kr_core") or {}).get("on"),
                phase_ref=(v.get("phase") or {}).get("name"), greed_ref=(v.get("greed") or {}).get("word"),
                greed_warn_n=(v.get("greed") or {}).get("n"), flow_ref=(v.get("flow") or {}).get("word"),
                econ_ref=(v.get("econ") or {}).get("word"), rule=v.get("rule"))


KR_INDICES = ("^KS11", "^KQ11", "KRW=X")


def kr_today_facts(today=None):
    """한국 장 마감 리포트용 — 오늘 KRX 대형주(시총 1조+) 등락률. 오늘자 목록이 아니면 빈 값(어제 걸 오늘이라 하지 않는다)."""
    from datetime import timezone as _tz, timedelta as _td
    today = today or (datetime.now(_tz.utc) + _td(hours=9)).date().isoformat()
    try:
        import krx_listing
        df = krx_listing.stock_listing("KRX", verbose=False, tradable=True)
    except Exception as e:
        print("  KRX 목록 실패:", str(e)[:100])
        return {}
    col = next((c for c in ("ChagesRatio", "ChangesRatio") if c in df), None)
    if col is None or str(df.attrs.get("asof")) != today:
        print(f"  KRX 오늘자 등락률 없음(asof={df.attrs.get('asof')}) → 종목 등락 생략")
        return {}
    import pandas as pd
    df = df.assign(_r=pd.to_numeric(df[col], errors="coerce"))
    big = df[(df["Marcap"] >= 1e11) & df["_r"].notna()].sort_values("_r")      # 2026-11-27 모수 통일(1,000억+). 히트맵만 1조+(면적 표시용) — 아래 kr_heatmap 호출부
    row = lambda r: dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1))
    allr = df[df["_r"].notna()]
    # 시장 폭 — 전 종목(코넥스·거래정지 제외) 상승/하락/보합, 상·하한가(±29.5% 이상)
    breadth = dict(up=int((allr["_r"] > 0).sum()), down=int((allr["_r"] < 0).sum()), flat=int((allr["_r"] == 0).sum()),
                   limit_up=int((allr["_r"] >= 29.5).sum()), limit_down=int((allr["_r"] <= -29.5).sum()))
    # 거래대금(조원) — 코스피·코스닥
    turnover = {}
    if "Amount" in df and "MarketId" in df:
        amt = pd.to_numeric(df["Amount"], errors="coerce")
        for mid, nm in (("STK", "코스피"), ("KSQ", "코스닥")):
            v = amt[df["MarketId"].astype(str) == mid].sum()
            if v > 0:
                turnover[nm] = _r(v / 1e12, 1)
    # 시총 상위 10 — 지수를 움직인 대장주
    mega = [row(r) for _, r in df[df["_r"].notna()].sort_values("Marcap", ascending=False).head(10).iterrows()]
    # 업종 — sectors.json(KSIC 업종) 기준, 시총 1조+ 3종 이상인 업종의 시총가중 등락
    sectors = []
    try:
        smap = _j("data/sectors.json") or {}
        b2 = big.assign(_sec=big["Code"].map(lambda c: smap.get(str(c).zfill(6))))
        b2 = b2[b2["_sec"].notna()]
        for sec, g in b2.groupby("_sec"):
            if len(g) >= 3:
                w = g["Marcap"] / g["Marcap"].sum()
                gs = g.sort_values("Marcap", ascending=False)
                lead = gs.iloc[0]
                # 2026-11-14 members: 화면에서 업종을 누르면 구성 종목(시총 순) — '대장' 한 종목만으론 업종을 알 수 없었다
                sectors.append(dict(name=_sec_short(sec), n=len(g), ret=_r((g["_r"] * w).sum(), 1),
                                    lead=lead["Name"], lead_ret=_r(lead["_r"], 1),
                                    members=[dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1),
                                                  mc=_r(float(r["Marcap"]) / 1e12, 1)) for _, r in gs.iterrows()]))
        sectors.sort(key=lambda x: -x["ret"])
    except Exception as e:
        print("  업종 집계 생략:", str(e)[:80])
    out = dict(universe=len(big), basis="d1", asof=today,
               top=[row(r) for _, r in big[::-1].head(6).iterrows()],
               bottom=[row(r) for _, r in big.head(6).iterrows()],
               breadth_up=round((big["_r"] > 0).mean() * 100) if len(big) else None,
               breadth_all=breadth, turnover_tn=turnover, megacaps=mega, sectors=sectors)
    try:
        out.update(kr_movers(allr, today))
    except Exception as e:
        print("  신고가·특징주 생략:", str(e)[:80])
    try:
        out["heatmap"] = kr_heatmap(big[big["Marcap"] >= 1e12], today)   # 히트맵 = 면적 표시라 1조+ 유지(1,000억 종목은 칸이 보이지 않음)
    except Exception as e:
        print("  히트맵 생략:", str(e)[:80])
    try:
        out["breadth_hist"] = breadth_log(today, breadth, out)
    except Exception as e:
        print("  시장 폭 기록 생략:", str(e)[:80])
    try:
        fl = kr_flow_today(today)
        if fl:
            out["flow"] = fl
    except Exception as e:
        print("  수급 생략:", str(e)[:80])
    return {"KR": out}


_HM_GROUP = [  # 네이버 업종(59종) → 히트맵 묶음(방송 히트맵 수준). 위에서부터 첫 일치. 2026-11-11
    ("반도체", ("반도체",)),
    ("2차전지·전기제품", ("전기제품",)),
    ("전력기기", ("전기장비",)),
    ("자동차", ("자동차",)),
    ("조선", ("조선",)),
    ("방산·항공", ("우주항공", "국방")),
    ("금융", ("은행", "증권", "보험", "금융", "창업투자", "카드")),
    ("바이오·제약", ("제약", "생물공학", "건강관리", "생명과학")),
    ("IT하드웨어", ("전자장비", "디스플레이", "전자제품", "핸드셋", "통신장비", "컴퓨터")),
    ("인터넷·게임·엔터", ("양방향미디어", "IT서비스", "소프트웨어", "게임", "방송", "광고", "출판")),
    ("에너지·소재", ("석유", "화학", "철강", "비철", "금속", "종이")),
    ("기계·건설", ("기계", "건설", "건축")),
    ("지주", ("복합기업",)),
    ("소비재", ("식품", "화장품", "음료", "담배", "백화점", "판매업체", "호텔", "레저", "섬유", "가정용", "교육")),
    ("통신·유틸리티", ("통신서비스", "유틸리티")),
    ("운송", ("항공사", "해운", "운송", "도로")),
]


def _hm_group(upjong):
    for g, keys in _HM_GROUP:
        if any(k in (upjong or "") for k in keys):
            return g
    return "기타"


def kr_heatmap(big, today):
    """업종 히트맵(봇 시황 카드 2장째, 2026-11-11) — 시총 1조+ 종목의 이름·업종 묶음·시총(조)·등락.
    업종은 네이버 업종(data/sector_detail.json) → _HM_GROUP 16묶음. KSIC 는 삼성전자를 '통신·방송장비'로 둬서 쓰지 않는다."""
    sd = (_j("data/sector_detail.json") or {}).get("kr") or {}
    rows = [dict(name=r["Name"], sym=r["Code"], sec=_hm_group((sd.get(str(r["Code"]).zfill(6)) or {}).get("upjong")),
                 mc=round(float(r["Marcap"]) / 1e12, 2), ret=_r(r["_r"], 1)) for _, r in big.iterrows()]
    rows.sort(key=lambda x: -x["mc"])
    return rows


def breadth_log(today, breadth, kr):
    """results/kr_breadth_log.json 에 오늘 시장 폭(상승·하락·보합·신고가 수)을 덧붙이고 최근 30개를 돌려준다.
    2026-11-12 시작 — 이전 날짜는 없다(지어내지 않는다). 같은 날짜는 덮어쓴다."""
    p = os.environ.get("MR_BREADTH_LOG") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "kr_breadth_log.json")
    try:
        log = json.load(open(p, encoding="utf-8"))
    except Exception:
        log = []
    b = breadth or {}
    row = dict(date=today, up=b.get("up"), down=b.get("down"), flat=b.get("flat"),
               new_high=(kr.get("new_high_52w") or {}).get("n"))
    log = [r for r in log if r.get("date") != today] + [row]
    log = sorted(log, key=lambda r: r["date"])[-400:]
    with open(p, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=0)
    return log[-30:]


def kr_flow_today(today):
    """오늘 투자자별 순매수(억원) — 코스피·코스닥. 네이버 모바일 API(tools/kr_flow.investor_day 재사용).
    장 마감 직후(15:50)엔 잠정치다 — 카드에 '잠정' 표기. 휴장일·실패면 빈 값."""
    import sys as _sys
    _sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "tools"))
    import kr_flow
    d = today.replace("-", "")
    out = {}
    for mk in ("KOSPI", "KOSDAQ"):
        r = kr_flow.investor_day(mk, d)
        if r:
            out[mk] = {k: r[k] for k in ("개인", "외국인", "기관")}
    return out


def kr_movers(allr, today):
    """2026-11-11 차니 요청 — 시황에 '52주 신고가·특징주 탑 몇 개'.

    · 52주 신고가: 오늘 **장중 고가 ≥ 52주 최고가**(perf_latest.hi52 = 주봉 고가). 뉴스의 '장중 52주 신고가'와 같은 정의.
      ⚠️ 처음엔 '종가 > hi52' 로 했다가 0종이 나왔다 — perf_run 이 장중에 다시 돌아 hi52 에 **오늘 고가가 이미 들어 있다**
      (11-11 에스텍 종가 = hi52). '≥ 고가' 는 hi52 가 오늘을 포함하든 안 하든 맞다. 종가까지 고점이면 close_high 표시.
      대상은 perf_run 유니버스(시총 1천억+). perf_latest 가 오늘 판이 아니면 생략. 목록에 High 열이 없으면(스냅샷) 생략.
    · 거래대금 상위: 오늘 돈이 몰린 곳 — 지수 대장주와 겹쳐도 그대로 보여 준다.
    · 특징주: 상한가 + (시총 1천억+ · 거래대금 300억+ 중 +10% 이상 급등). 이유 꼬리표를 같이 단다.
    """
    import pandas as pd
    res = {}
    amt = pd.to_numeric(allr["Amount"], errors="coerce") if "Amount" in allr else None
    a = allr.assign(_amt=amt if amt is not None else 0)
    if amt is not None:
        a["_amt_rank"] = a["_amt"].rank(ascending=False, method="first")
        tv = a.sort_values("_amt", ascending=False).head(10)
        res["turnover_top"] = [dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1), amt_b=int(round(r["_amt"] / 1e8)))
                               for _, r in tv.iterrows() if r["_amt"] > 0]
    # 특징주 — 상한가 + 거래대금 300억+ 급등. **거래대금 순**(11-11: 상한가 10종이 우선주·소형주로 칸을 다 채워
    #   주성엔지니어링 2,563억 +12.8% 가 밀렸다 — 돈이 몰린 쪽이 특징주다).
    feat = {}
    for _, r in a[a["_r"] >= 29.5].iterrows():
        feat[r["Code"]] = dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1), tag="상한가", _a=float(r["_amt"] or 0))
    if amt is not None:
        hot = a[(a["Marcap"] >= 1e11) & (a["_amt"] >= 3e10) & (a["_r"] >= 10)]
        for _, r in hot.iterrows():
            feat.setdefault(r["Code"], dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1),
                                            tag=f"거래대금 {int(r['_amt_rank'])}위", _a=float(r["_amt"])))
    fl = sorted(feat.values(), key=lambda x: -x["_a"])[:8]
    res["featured"] = [{k: v for k, v in x.items() if k != "_a"} for x in fl]
    lu = a[a["_r"] >= 29.5].sort_values("_amt", ascending=False)
    res["limit_up"] = [dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1)) for _, r in lu.iterrows()]
    try:   # 오늘의 테마 (2026-11-11)
        res.update(kr_themes(a))
    except Exception as e:
        print("  테마 생략:", str(e)[:80])
    # 52주 신고가
    p = _j("results/perf_latest.json")
    if p.get("date") == today and "High" in a:
        hi = {s["sym"]: s for s in p.get("stocks", []) if s.get("market") == "KR" and s.get("hi52")}
        nh = []
        for _, r in a.iterrows():
            s = hi.get(str(r["Code"]).zfill(6))
            hv = pd.to_numeric(r.get("High"), errors="coerce")
            if s and pd.notna(hv) and hv > 0 and float(hv) >= float(s["hi52"]):
                nh.append(dict(name=r["Name"], sym=r["Code"], ret=_r(r["_r"], 1), marcap=float(r["Marcap"]),
                               amt=float(r["_amt"] or 0), young=bool(s.get("young")),
                               close_high=bool(float(r["Close"]) >= float(hv))))
        nh.sort(key=lambda x: -x["amt"])          # 돈이 몰린 신고가부터
        res["new_high_52w"] = dict(n=len(nh), universe=len(hi),
                                   top=[{k: v for k, v in x.items() if k in ("name", "sym", "ret", "young", "close_high")} for x in nh[:8]])
    else:
        print(f"  perf_latest 날짜 {p.get('date')} ≠ {today} 또는 High 열 없음 → 52주 신고가 생략")
    return res


_THEME_SKIP = ("SPAC", "기업인수목적")


def kr_themes(a, min_theme=5):
    """오늘의 강세·약세 테마 — 네이버 테마(data/sector_detail.json, 주 1회 갱신)별 구성 종목 단순 평균 등락(구성 min_theme 종+).
    한국 마감시황 방송의 '오늘의 테마' 코너. 히트맵(kr_heatmap)이 업종 단위라면 이건 재료 단위다. 2026-11-11"""
    sd = _j("data/sector_detail.json") or {}
    det = sd.get("kr") or {}
    b = a.assign(Code=a["Code"].astype(str).str.zfill(6))
    # 테마
    th = {}
    for _, r in b.iterrows():
        for t in (det.get(r["Code"]) or {}).get("themes") or []:
            if not any(x in t for x in _THEME_SKIP):
                th.setdefault(t, []).append(r)
    rows = []
    for t, rs in th.items():
        if len(rs) < min_theme:
            continue
        rets = [x["_r"] for x in rs]
        lead = sorted(rs, key=lambda x: -x["_r"])[:3]
        rows.append(dict(name=t.split("(")[0].strip()[:16], n=len(rs), ret=_r(sum(rets) / len(rets), 1),
                         up=sum(1 for v in rets if v > 0),
                         lead=[dict(name=x["Name"], sym=str(x.get("Code") or "") or None, ret=_r(x["_r"], 1)) for x in lead],
                         lag=[dict(name=x["Name"], ret=_r(x["_r"], 1)) for x in sorted(rs, key=lambda x: x["_r"])[:3]]))
    rows.sort(key=lambda x: -x["ret"])
    # 같은 이름으로 잘린 테마(예: '코로나19') 중복 제거
    seen, uniq = set(), []
    for x in rows:
        if x["name"] not in seen:
            seen.add(x["name"]); uniq.append(x)
    return dict(themes_top=uniq[:6], themes_bottom=uniq[::-1][:4], themes_asof=sd.get("asof"))


_SEC_NAME = {  # KSIC 업종명 → 읽히는 이름. 없으면 _sec_short 규칙. (삼성전자는 KSIC상 '통신 및 방송 장비'다 — 대장주를 같이 적는 이유)
    "기타 금융업": "지주·기타금융", "특수 목적용 기계 제조업": "특수기계(장비)", "전자부품 제조업": "전자부품",
    "기타 화학제품 제조업": "화학제품", "의약품 제조업": "제약", "소프트웨어 개발 및 공급업": "소프트웨어",
    "일차전지 및 이차전지 제조업": "2차전지", "기초 의약물질 제조업": "바이오·원료의약", "기초 화학물질 제조업": "기초화학",
    "자연과학 및 공학 연구개발업": "바이오 R&D", "반도체 제조업": "반도체", "금융 지원 서비스업": "증권·금융지원",
    "보험업": "보험", "일반 목적용 기계 제조업": "일반기계", "전동기, 발전기 및 전기 변환 · 공급 · 제어 장치 제조업": "전력기기",
    "기타 식품 제조업": "식품", "종합 소매업": "유통", "자동차 신품 부품 제조업": "자동차부품", "자동차용 엔진 및 자동차 제조업": "자동차",
    "통신 및 방송 장비 제조업": "통신·방송장비", "선박 및 보트 건조업": "조선", "건축기술, 엔지니어링 및 관련 기술 서비스업": "엔지니어링",
    "절연선 및 케이블 제조업": "전선", "건물 건설업": "건설", "토목 건설업": "토목",
    "측정, 시험, 항해, 제어 및 기타 정밀기기 제조업; 광학기기 제외": "정밀기기", "기타 전문 도매업": "전문도매",
    "자료처리, 호스팅, 포털 및 기타 인터넷 정보매개 서비스업": "인터넷·포털", "1차 철강 제조업": "철강",
    "1차 비철금속 제조업": "비철금속", "전기 통신업": "통신서비스", "은행 및 저축기관": "은행",
    "오디오물 출판 및 원판 녹음업": "엔터(음반)", "의료용품 및 기타 의약 관련제품 제조업": "의료용품", "의료용 기기 제조업": "의료기기",
    "항공기,우주선 및 부품 제조업": "항공우주", "무기 및 총포탄 제조업": "방산",
}


def _sec_short(s):
    """'반도체 제조업' → '반도체' · 'XX, YY 및 ZZ 제조업; 무엇 제외' → 'XX'."""
    if s in _SEC_NAME:
        return _SEC_NAME[s]
    s = str(s).split(";")[0]
    for t in (" 제조업", " 도매업", " 소매업", " 서비스업", " 개발 및 공급업", "업"):
        if s.endswith(t) and len(s) > len(t) + 1:
            s = s[: -len(t)]
            break
    return s.split(",")[0].split(" 및 ")[0].strip()[:14]


def rule_checks(idx_rows, kr, flow_sum=None, events=None) -> list[str]:
    """이번에 볼 것 — 숫자 조건(2026-11-12). 대시보드 🎯 상자와 봇 '확인할 것'이 같은 함수를 쓴다(**굵게** 마크다운).
    ① 지수별 5주선까지 거리(금요일 종가 = 실전 v1.9 신규 매수 조건) ② 시장 폭 ③ 외국인 수급 방향 ④ 7일 안 일정."""
    out = []
    for x in idx_rows or []:
        g = x.get('gate5w') or {}
        c, lg = x.get('close'), g.get('live_gap')
        if c is None or lg is None:
            continue
        ma = c / (1 + lg / 100)
        if lg < 0:
            out.append(f"**{x['name']}** 금요일 종가가 **{ma:,.0f}**(5주선) 위면 다음 주 {x['name']} 종목 신규 매수 재개 — "
                       f"지금 {c:,.0f}, **{(ma / c - 1) * 100:.1f}%** 더 올라야 함")
        else:
            out.append(f"**{x['name']}** 금요일 종가가 **{ma:,.0f}**(5주선) 아래로 내려가면 다음 주 신규 매수 중지 — 지금 여유 {lg:+.1f}%")
    b = (kr or {}).get('breadth_all') or {}
    t = (b.get('up') or 0) + (b.get('down') or 0) + (b.get('flat') or 0)
    if t:
        r = b['up'] / t * 100
        out.append(f"시장 폭: 오늘 상승 종목 {r:.0f}% — " + ("반등이 소수 대형주가 아니라 넓게 퍼짐. 이런 날이 이어지는지(60%+)" if r >= 60
                   else "지수와 달리 오르는 종목이 적음 — 소수 종목 장세 주의" if r < 45 else "중립"))
    k = (flow_sum or {}).get('KOSPI') or {}
    # kr_flow 요약은 17:47 갱신 — 15:50 리포트 직후엔 어제 값이라 '오늘'로 쓰면 날짜가 섞인다 → 오늘 잠정치(facts.flow) 우선
    t1 = (((kr or {}).get('flow') or {}).get('KOSPI') or {}).get('외국인')
    d1 = t1 if t1 is not None else k.get('d1')
    if d1 is not None and k.get('d5') is not None:
        same = (d1 >= 0) == (k['d5'] >= 0)
        out.append(f"코스피 외국인: 오늘{' 잠정' if t1 is not None else ''} {d1 / 1e4:+.2f}조 · 5일 {k['d5'] / 1e4:+.1f}조"
                   f"({str(k.get('date') or '-')[5:]}까지) — "
                   + ("방향 같음(추세 지속)" if same else "오늘만 방향이 다름 — 5일 합계가 플러스로 돌아서야 추세 전환"))
    near = []
    for e in events or []:
        dd = e.get('dday')
        if dd is None:
            try:
                dd = (date.fromisoformat(str(e['date'])[:10]) - date.today()).days
            except Exception:
                continue
        if 0 <= dd <= 7 and e.get('kind') in ('한국', '미국', '실전 규칙'):
            near.append(e)
    if near:
        out.append("7일 안 일정: " + ' · '.join(f"{e['date'][5:]} {e['name'].split(' — ')[0]}" for e in near[:3]))
    return out


def us_rule_checks(idx_rows, us=None, events=None) -> list[str]:
    """미국 리포트의 숫자 조건 — 한국판(rule_checks)과 같은 자리·같은 말투. 2026-11-15 양식 통일.
    ① 지수별 200일선까지 거리(매크로 '미국 장기 추세') ② 오닐 분배일 ③ 대형주 시장 폭 ④ 7일 안 미국 일정."""
    out = []
    for x in idx_rows or []:
        c, ma = x.get('close'), x.get('ma200')
        if not c or not ma:
            continue
        gap = (c / ma - 1) * 100
        if gap >= 0:
            out.append(f"**{x['name']}** 200일선 **{ma:,.0f}** 위 {gap:+.1f}% — 이 선을 종가로 깨면 장기 추세 꺼짐")
        else:
            out.append(f"**{x['name']}** 200일선 **{ma:,.0f}** 아래 {gap:+.1f}% — 종가로 되찾아야 장기 추세 회복")
    for x in idx_rows or []:
        pz = x.get('pulse') or {}
        if pz.get('dist_n') is not None and x.get('name') == 'S&P500':
            n = pz['dist_n']
            out.append(f"S&P500 분배일 {n}개(25거래일) — " + ("5개 이상: 기관 매도 누적, 신고가 돌파 실패 주의" if n >= 5
                       else "4개: 하나 더 쌓이면 '압력 받는 상승'" if n == 4 else "여유 — 상승 추세 훼손 신호 없음"))
    bu = (us or {}).get('breadth_up')
    if bu is not None:
        out.append(f"시장 폭: 상승 종목(시총 $3억+) {bu}% — " + ("넓게 오른 날. 이어지는지(60%+)" if bu >= 60
                   else "지수와 달리 오르는 종목이 적음 — 소수 종목 장세 주의" if bu < 45 else "중립"))
    near = []
    for e in events or []:
        dd = e.get('dday')
        if dd is None:
            try:
                dd = (date.fromisoformat(str(e['date'])[:10]) - date.today()).days
            except Exception:
                continue
        if 0 <= dd <= 7 and e.get('kind') == '미국':
            near.append(e)
    if near:
        out.append("7일 안 일정: " + ' · '.join(f"{e['date'][5:]} {e['name'].split(' — ')[0]}" for e in near[:3]))
    return out


def _kr_rule_checks(f):
    """facts(kind='kr') 에 rule_checks 를 싣는다 — 봇이 AI 체크포인트 대신 쓴다. 실패해도 리포트는 나간다."""
    try:
        import json as _j
        from pathlib import Path as _P
        root = _P(__file__).resolve().parent
        fl = _P(root / 'results' / 'kr_flow.json')
        flow_sum = (_j.loads(fl.read_text(encoding='utf-8')) or {}).get('summary') if fl.exists() else None
        try:
            import events as _ev
            evs = _ev.build(days=8)
        except Exception:
            evs = None
        idx = [x for x in f.get('indices') or [] if x.get('name') in ('코스피', '코스닥')]
        return rule_checks(idx, (f.get('stocks') or {}).get('KR') or {}, flow_sum, evs)
    except Exception as e:
        print('  숫자 체크포인트 생략:', str(e)[:100])
        return []


# ═════ 2026-11-24 시황 첫 단추 — 정확성 관문 + 종합 탭 순서 재구성 ═════════════════════════════════════
#   ① 종가 확정 검사: 15:45 판이 장중 스냅샷(KRX 캐시 14시대)을 종가로 썼다(삼성 +7.7% → 실제 +6.76%).
#      대형주 시총가중 등락이 코스피 지수 등락과 0.45%p 넘게 어긋나면 '종가 아님'으로 보고 발행을 미룬다.
#   ② 방향 검사: AI 가 '반도체가 약세를 이끌었다'고 썼다(필라델피아 반도체 +14%). 이름·방향어가 한 절에 같이 있으면 대조.
#   ③ 발행판 덮어쓰기 금지 · ④ 5주선 '오늘' 거리 · ⑤ 이례적 급변 표시 · ⑥ 오닐·시장 폭 맥락·수급·신용·일정·실전 원장.
CLOSE_TOL = 0.45          # %p — 종가 확정본 0.1~0.2, 장중 스냅샷 0.65 (2026-11-24 실측)
ANOMALY_D1 = 15.0         # 대형주 하루 ±15% 이상은 '이례적 — 확인 필요'


def kr_close_check(kr, indices):
    """대형주(시총 1조+) 시총가중 오늘 등락 vs 코스피 지수 1일 등락. 어긋나면 종목 시세가 종가가 아니다."""
    hm = (kr or {}).get("heatmap") or []
    ks = next((x for x in indices or [] if x.get("sym") == "^KS11"), {})
    rows = [r for r in hm if r.get("mc") and r.get("ret") is not None]
    if len(rows) < 50 or ks.get("d1") is None:
        # 2026-11-26 — 11-25 는 KRX 오늘자 등락률이 15:45 에 없어(asof 11-24) 종목 칸이 통째로 빈 채 '통과'로 발행됐다.
        #   자료가 없으면 통과가 아니라 보류다(16:30 마지막 시도는 종목 칸 비우고 발행).
        return dict(ok=False, note="종목 시세 없음(KRX 오늘자 미반영)", big_w=None, kospi=ks.get("d1"), gap=None, tol=CLOSE_TOL)
    prev = [r["mc"] / (1 + r["ret"] / 100) for r in rows]
    w = sum(a * r["ret"] for a, r in zip(prev, rows)) / sum(prev)
    gap = w - ks["d1"]
    return dict(ok=abs(gap) <= CLOSE_TOL, big_w=round(w, 2), kospi=ks["d1"], gap=round(gap, 2), tol=CLOSE_TOL)


def _pulse_line(x):
    pz = x.get("pulse") or {}
    if not pz.get("state"):
        return None
    s = f"{x['name']} {pz['state']}"
    bits = [f"분배일 {pz.get('dist_n', '-')}개/25일"]
    if pz.get("ftd_date"):
        bits.append(f"팔로스루 {pz['ftd_date'][5:]}")
    elif str(pz.get("state", "")).startswith("반등 시도"):
        n = pz.get("rally_day") or 0
        bits.append("상승 확인 조건: 반등 4일째부터 +1.25%↑·거래량 증가" + (f"(앞으로 {4 - n}거래일 뒤부터)" if n < 4 else "(오늘부터 해당)"))
    if pz.get("low_date"):
        bits.append(f"이번 조정 저점 {pz['low_date'][5:]}(고점 대비 {pz.get('corr_dd', 0):+.1f}%)")
    return s + " — " + " · ".join(bits)


def _gate_line(indices):
    g = []
    for x in indices or []:
        z = x.get("gate5w") or {}
        if z.get("on") is None:
            continue
        live = z.get("live_gap")
        g.append(f"{x['name']} {'위' if z.get('on') else '아래'}(지난 금요일 {(z.get('gap') or 0):+.1f}%"
                 + (f" · 오늘 {live:+.1f}%" if live is not None else "") + ")")
    if not g:
        return None
    allon = all((x.get("gate5w") or {}).get("on") for x in indices if (x.get("gate5w") or {}).get("on") is not None)
    return (f"**실전 규칙 v1.9** — 주봉 5주선 {' · '.join(g)} → 신규 매수 {'가능' if allon else '중지(소속 지수가 5주선 아래)'}"
            " · 판정은 금요일 종가로만")


def breadth_context(hist):
    """[{date, up, down}] → 오늘 상승 비율과 최근 30거래일 맥락(평균·순위)."""
    pts = [(r["date"], r["up"] / max(r["up"] + r["down"], 1) * 100) for r in hist or [] if r.get("up") is not None]
    if len(pts) < 5:
        return None
    pts = pts[-30:]
    today = pts[-1][1]
    avg = sum(p for _, p in pts) / len(pts)
    rank = 1 + sum(p > today for _, p in pts)
    return dict(date=pts[-1][0], today=round(today), avg=round(avg), rank=rank, n=len(pts),
                up_days=sum(p >= 50 for _, p in pts))


def flow_context(today_flow):
    """오늘 투자자별(잠정) + kr_flow.json 의 외국인 5·20일 누적·신용잔고. 날짜를 같이 둔다."""
    s = (_j("results/kr_flow.json") or {}).get("summary") or {}
    out = {}
    if today_flow:
        out["today"] = today_flow
    cum = {mk: dict(date=v.get("date"), d5=v.get("d5"), d20=v.get("d20")) for mk, v in s.items() if mk in ("KOSPI", "KOSDAQ")}
    if cum:
        out["foreign_cum"] = cum
    cr = s.get("credit") or {}
    if cr.get("v"):
        out["credit"] = dict(date=cr.get("date"), tn=round(cr["v"] / 1e4, 1), chg20=round(cr.get("chg20") or 0, 1),
                             from_peak=round(cr.get("from_peak") or 0, 1), peak_date=cr.get("peak_date"))
    return out


_EV_KR = {"한국", "실적KR"}


def events_next(days=7, market=None):
    try:
        import events as _EV
        from datetime import timedelta as _td
        today = (datetime.now(timezone.utc) + _td(hours=9)).date()
        ev = _EV.build(today, days, None, None)
        # 2026-11-26 시장별 — 한국판엔 한국 일정, 미국판엔 한국 외 일정(미국 지표·실적 등)
        keep = (lambda k: k in _EV_KR) if market == "KR" else (lambda k: k not in _EV_KR) if market == "US" else (lambda k: True)
        return [dict(date=e["date"], wd=e.get("wd"), time=e.get("time"), name=e["name"], kind=e.get("kind")) for e in ev
                if e.get("kind") != "보유" and keep(e.get("kind"))][:6]
    except Exception as e:
        print("  일정 생략:", str(e)[:80])
        return []


def ledger_facts():
    """실전 원장(한국) — 2026-11-22 차니 결정: 원장 성과 전부 공개(종목 권유 문구는 금지). 오늘 종가 기준 손익·손절선 거리."""
    try:
        led = json.load(open(os.path.join(BASE, "live", "ledger.json"), encoding="utf-8"))
        import krx_listing
        df = krx_listing.stock_listing("KRX", verbose=False)
    except Exception as e:
        print("  실전 원장 생략:", str(e)[:80])
        return {}
    today = (datetime.now(timezone.utc) + timedelta(hours=9)).date().isoformat()
    if str(df.attrs.get("asof") or "")[:10] != today:
        # 2026-11-26 — 11-25(코스피 -6.1%) 원장에 전날 시세가 들어가 '오늘 평균 +6.3%'로 나갔다
        print(f"  실전 원장 생략 — 시세 기준일 {df.attrs.get('asof')} ≠ 오늘 {today}")
        return {}
    px = dict(zip(df["Code"].astype(str).str.zfill(6), df["Close"]))
    col = next((c for c in ("ChagesRatio", "ChangesRatio") if c in df), None)
    d1 = dict(zip(df["Code"].astype(str).str.zfill(6), df[col])) if col else {}
    pos = ((led.get("KR") or {}).get("positions") or {})
    rows = []
    for sym, p in pos.items():
        c = px.get(sym)
        if not c or not p.get("avg"):
            continue
        rows.append(dict(name=p.get("name"), sym=sym, d1=_r(d1.get(sym), 1), pnl=_r((c / p["avg"] - 1) * 100, 1),
                         to_stop=_r((p["stop"] / c - 1) * 100, 1) if p.get("stop") else None))
    if not rows:
        return {}
    trades = [i for i in led.get("done_ids", []) if today in str(i)]
    return dict(n=len(rows), d1_avg=_r(sum(r["d1"] or 0 for r in rows) / len(rows), 1),
                pnl_avg=_r(sum(r["pnl"] for r in rows) / len(rows), 1),
                near_stop=[r for r in rows if r["to_stop"] is not None and r["to_stop"] > -5],
                best=max(rows, key=lambda r: r["d1"] or -99), worst=min(rows, key=lambda r: r["d1"] or 99),
                trades_today=len(trades), rows=rows)


def hilo_weekly(mk):
    """주간 52주 신고가·신저가 종목 수 — 종합 탭 '주간 52주 신고가 · 신저가' 막대와 같은 집계(perf_latest nh·nl)."""
    p = _j("results/perf_latest.json") or {}
    wk = {}
    for x in p.get("stocks") or []:
        if x.get("market") != mk:
            continue
        for d, _c in x.get("nh") or []:
            wk.setdefault(d, [0, 0])[0] += 1
        for d in x.get("nl") or []:
            wk.setdefault(d, [0, 0])[1] += 1
    ds = sorted(wk)
    if len(ds) < 3:
        return {}
    last, prev = wk[ds[-1]], wk[ds[-2]]
    streak = 0
    for d in reversed(ds):
        if wk[d][1] > wk[d][0]:
            streak += 1
        else:
            break
    return dict(week=ds[-1], nh=last[0], nl=last[1], prev_nh=prev[0], prev_nl=prev[1], nl_over_nh_weeks=streak,
                asof=str(p.get("date") or "")[:10])


def anomalies(f):
    """대형주 하루 ±15% — 사실일 수도 있지만 두 번째 출처로 확인 전까지 '확인 필요' 표시."""
    out = []
    us = (f.get("internals") or {}).get("US") or {}
    for r in (us.get("megacaps") or []) or ((f.get("us") or {}).get("megacaps") or []):   # 같은 종목 두 이름(NVDA·엔비디아) 중복 방지
        v = r.get("ret", r.get("d1"))
        if v is not None and abs(v) >= ANOMALY_D1 and r.get("name") not in {a["name"] for a in out}:
            out.append(dict(name=r.get("name"), d1=v))
    kr = ((f.get("stocks") or {}).get("KR") or {})
    for r in kr.get("megacaps") or []:
        if r.get("ret") is not None and abs(r["ret"]) >= ANOMALY_D1:
            out.append(dict(name=r["name"], d1=r["ret"]))
    return out


def _fresher_kr(rows, db=None):
    """2026-11-24: 미국판(06:10 KST)이 Yahoo ^KS11 의 당일 봉 지연으로 코스피·코스닥을 전 거래일(11-20) 값으로 실었다.
    같은 날 15:45 한국판은 이미 11-23 종가를 갖고 있었다 → 한국판 지수 행이 더 새로우면 그것으로 바꾼다."""
    db = db if db is not None else (_j("results/market_report.json") or {})
    kr = {x.get("sym"): x for x in ((db.get("latest_kr") or {}).get("facts") or {}).get("indices", [])}
    out = []
    for x in rows:
        y = kr.get(x.get("sym"))
        if x.get("sym") in ("^KS11", "^KQ11") and y and str(y.get("date", "")) > str(x.get("date", "")):
            x = dict(y)
        out.append(x)
    return out


def facts(kind):
    if kind == "kr":
        sg = signal_facts()
        f = dict(kind=kind, generated=_now_kst(), verdict={},
                 indices=intraday_range([x for x in index_facts() if x.get("sym") in KR_INDICES]), stocks=kr_today_facts(),
                 signals=dict(market_direction={"KR": sg["market_direction"].get("KR")}))
        f["rule_checks"] = _kr_rule_checks(f)
        try:   # 2026-11-14 종합 '주간·월간' 보기 + 대형주 상승 비율 추이 — 장 마감 직후 값으로
            import market_internals as _MI
            f["internals_kr"] = _MI.kr_internals()
        except Exception as e:
            print("  한국 시장 내부(주간·월간) 생략:", str(e)[:100])
        kr = (f["stocks"] or {}).get("KR") or {}
        f["quality"] = dict(close_check=kr_close_check(kr, f["indices"]))
        f["ctx"] = dict(breadth=breadth_context((f.get("internals_kr") or {}).get("breadth_hist")),
                        flow=flow_context(kr.get("flow")), events=events_next(market="KR"), ledger=ledger_facts(), hilo=hilo_weekly("KR"))
        f["anomalies"] = anomalies(f)
        return f
    f = dict(kind=kind, generated=_now_kst(), verdict=verdict_facts(),
             indices=intraday_range(_fresher_kr(index_facts())), stocks=stock_facts(kind), signals=signal_facts())
    if kind == "daily":
        try:
            f["us"] = us_extra_facts()
        except Exception as e:
            print("  미국 자산·업종·대장주 생략:", str(e)[:100])
        try:   # 2026-11-14 종합 '오늘의 시장 — 미국' + 한·미 대형주 상승 비율 30거래일
            import market_internals as _MI
            f["internals"] = dict(US=_MI.us_internals(), KR_mkt=_MI.kr_internals())
        except Exception as e:
            print("  시장 내부(미국·추이) 생략:", str(e)[:100])
        try:
            f["hy"] = hy_fact()
        except Exception as e:
            print("  시장 내부(미국·추이) 생략:", str(e)[:100])
        f["ctx"] = dict(breadth=breadth_context(((f.get("internals") or {}).get("US") or {}).get("breadth_hist")),
                        events=events_next(market="US"), hilo=hilo_weekly("US"))
        try:   # 2026-11-26 경제 지표 — 그날 나온 지표의 실제치·예상치 + 7일 일정(ForexFactory + FRED)
            import market_econ as _EC
            d_us = next((x.get("date") for x in f["indices"] if x.get("sym") == "^GSPC" and x.get("date")), None)
            if d_us:
                ec = _EC.facts(d_us)
                f["ctx"]["econ"] = ec
                known = {e["name"] for e in f["ctx"]["events"]}
                wd = "월화수목금토일"
                for r in ec.get("upcoming") or []:
                    if r["name"] not in known:
                        dd = datetime.fromisoformat(r["kst_date"]).date()
                        f["ctx"]["events"].append(dict(date=r["kst_date"], wd=wd[dd.weekday()], time=r["kst"][6:],
                                                       name=r["name"] + (f" (예상 {r['forecast']})" if r.get("forecast") else ""),
                                                       kind="미국"))
                f["ctx"]["events"].sort(key=lambda e: (e["date"], e.get("time") or ""))
        except Exception as e:
            print("  경제 지표 생략:", str(e)[:100])
        f["anomalies"] = anomalies(f)
    return f


# 2026-10-21: AI 는 '문장'만 쓴다 — 표·숫자 나열은 template() 가 facts 에서 그대로 찍는다.
#   예전엔 AI 가 표까지 다시 썼고, 상승 비율 27%·67% 를 9.1%·9.5% 로 옮겨 적었다. 문장 안 숫자도 unbacked_pcts 로 검사.
PROMPT = """너는 증권사 데일리 시황을 쓰는 시니어 애널리스트다. 아래 JSON 은 {span} 시장 데이터다.
지수·종목·업종 숫자는 이미 표(카드)로 나간다. 너는 **숫자 표가 말해 주지 않는 것**만 쓴다.
규칙:
- JSON 에 있는 사실만. 뉴스·원인·전망을 지어내지 않는다. 숫자를 쓸 땐 JSON 값 그대로(소수 1자리 %).
- **표 숫자를 되풀이하지 말 것**: "코스피가 5.3% 하락" 같은 문장 금지. 쓸 거면 숫자 대신 관계를 말한다.
- 상투어 금지: "확인할 필요가 있습니다", "주목할 필요", "변동성에 유의", "전반적인 약세를 보였습니다".
- 문체는 증권사 리포트 — 평서체(~했다/~이다)로 단정하게 쓴다. 대화체("~해요", "~네요", "~것 같습니다"),
  감탄·구어("무섭게", "폭탄", "~군요"), 독자에게 말 거는 문장("~보세요", "~기억하세요")은 쓰지 않는다. 이모지 금지.
- 한국어, 마크다운. 아래 세 절만:
  ## 한 줄 요약
  두 문장, 합쳐 90자 이내. ① 오늘 장을 한 마디로(무엇이 지수를 끌었나: 업종·대장주) ② 시장 폭·쏠림의 특징
  (예: "반도체 대형주가 지수를 끌어내렸지만 하락 종목은 평소의 2배가 아니라 3배 — 투매에 가까운 장.")
  ## 해설
  글머리표(-) 정확히 4개, 각 70자 이내, 이 순서·이 꼬리표만: **지수** · **수급** · **업종·테마** · **종목**.
  **지수** 줄은 지수 등락 대신 시장 방향을 쓴다 — 실전 규칙(주봉 5주선, gate5w)과 오닐 국면(pulse)이 같은 말을 하는지 엇갈리는지,
  오늘 상승 비율이 최근 30거래일 맥락(ctx.breadth)에서 어떤 날인지.
  **수급** 줄은 오늘 투자자별 매매와 외국인 5·20일 누적(ctx.flow)의 방향이 같은지, 신용잔고 흐름을 쓴다(자료 있을 때).
  (한국·미국 리포트 양식을 같게 — 2026-11-15) 투자자별 매매 자료가 없으면(미국) **수급** 줄은 거래대금 쏠림·금리·달러로 돈의 방향을 쓴다.
  꼬리표마다 서로 다른 자료를 쓴다. 표에 없는 '관계'를 말한다 — 지수와 시장 폭의 괴리, 대형주와 중소형주의 방향 차이,
  강세 업종과 약세 업종이 같은 테마로 묶이는지, 거래대금이 몰린 곳과 오른 곳이 같은지. 숫자는 줄마다 최대 2개.
  ## 체크포인트
  번호 목록 3개, 각 60자 이내. **다음 거래일에 볼 구체 조건** — 무엇이 어떤 수준을 넘는지/돌아오는지.
  서로 다른 데이터를 잇는다(지수 vs 시장 폭, 업종 vs 대장주, 1일 vs 5일·1개월, 달러·금리·유가 vs 주식).
  예: "1. 반도체 낙폭(-12%)이 VIX 30 위에서 멈추는지 — 이탈 땐 투매 연장"
  7일 안 일정(ctx.events)이 있으면 그중 시장에 큰 것 하나를 체크포인트에 넣는다.
추가 규칙(2026-11-24):
- 방향을 뒤집지 말 것: 1일 등락이 +인 지수·업종·종목을 '약세·하락·부진'으로, −인 것을 '강세·상승'으로 쓰지 않는다. 발행 전 기계 검사가 막는다.
- anomalies 에 있는 이례적 급변 값은 결론의 근거로 쓰지 않는다(두 번째 출처 확인 전).
- ctx.ledger(실전 원장)는 사실만 쓸 수 있다. 특정 종목을 사라·팔라·유망하다는 문장은 금지.
JSON:
{facts}"""


def _gemini_key():
    k = os.environ.get("GEMINI_KEY", "")
    if not k:
        try:
            import config
            k = getattr(config, "GEMINI_KEY", "") or ""
        except Exception:
            k = ""
    return k


def ask_gemini(prompt, models=MODELS, key=None):
    key = key or _gemini_key()
    if not key:
        raise RuntimeError("GEMINI_KEY 없음")
    from google import genai
    cl = genai.Client(api_key=key)
    last = None
    import time as _time
    for rnd in range(3):                  # 2026-11-24 503(수요 폭주)으로 두 모델 다 실패 → 숫자 템플릿만 나갔다. 20·40초 쉬고 다시
        for m in models:                  # 무료 한도는 모델별로 따로다 — 막히면 다음 모델
            try:
                r = cl.models.generate_content(model=m, contents=prompt)
                if (r.text or "").strip():
                    return r.text.strip(), m
            except Exception as e:
                last = e
        if rnd < 2 and any(c in str(last) for c in ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "500")):
            print(f"  Gemini 일시 오류 → {20 * (rnd + 1)}초 뒤 재시도: {str(last)[:80]}")
            _time.sleep(20 * (rnd + 1))
        else:
            break
    raise RuntimeError(f"Gemini 실패: {str(last)[:120]}")


_TITLE = {"daily": "일간 시황", "weekly": "주간 시황", "kr": "한국 장 마감 시황"}
_BASIS = {"d1": "오늘", "ret_1w": "1주", "ret_4w": "4주"}


def _eok(v):
    """억원 → '+7,256억' / '-2.0조'."""
    if v is None:
        return "-"
    return f"{v / 1e4:+,.1f}조" if abs(v) >= 1e4 else f"{v:+,.0f}억"


def template(f):
    """AI 없이도 발행되는 숫자 리포트. 2026-11-24 — 종합 탭 순서(지수 → 시장 방향 → 시장 폭 → 돈 → 업종 → 종목 → 원장 → 일정)."""
    v = f.get("verdict") or {}
    kind = f["kind"]
    ctx = f.get("ctx") or {}
    idx = [x for x in f.get("indices") or [] if "close" in x]
    L = [f"## {_TITLE.get(kind, '시황')} — 숫자 요약", ""]
    an = f.get("anomalies") or []
    if an:
        L += ["⚠️ **이례적 급변 — 두 번째 출처로 확인 전**: " + ", ".join(f"{a['name']} {a['d1']:+.1f}%" for a in an), ""]

    # ① 지수
    rep = next((x.get("date") for x in idx if x.get("sym") == {"daily": "^GSPC", "kr": "^KS11"}.get(kind)), None)
    L += ["**① 지수**", "", "| 지수 | 종가 | 1일 | 5일 | 1개월 | 52주고 대비 |", "|---|---|---|---|---|---|"]
    for x in idx:
        nm = x["name"] + (f" ({x['date'][5:]})" if rep and x.get("date") and x["date"] != rep and x.get("sym") in ("^KS11", "^KQ11") else "")
        L.append(f"| {nm} | {x['close']:,} | {x['d1']:+.1f}% | {x['d5']:+.1f}% | {x['m1']:+.1f}% | {x['from_52w_high']:+.1f}% |")

    # ② 시장 방향 — 실전 규칙 + 오닐(참고) + 미국 코어 참고
    L += ["", "**② 시장 방향**"]
    gl = _gate_line(idx)
    if gl:
        L.append("- " + gl)
    want = ("^KS11", "^KQ11") if kind == "kr" else ("^GSPC", "^IXIC") if kind == "daily" else ("^KS11", "^KQ11", "^GSPC", "^IXIC")
    for x in idx:
        if x.get("sym") in want:
            pl = _pulse_line(x)
            if pl:
                L.append("- 오닐(참고) " + pl)
    if v:
        L.append("- " + ("⚠️ 미국 코어 스위치 전환 · " if v.get("changed") else "") +
                 f"참고 — 미국 S&P500 200일선 {v.get('core_gap_200d', 0):+.1f}% · 국면 {v.get('phase_ref') or '-'} · "
                 f"욕심 경고 {v.get('greed_warn_n', '-')}/3 (돈을 움직이지 않는 지표)")

    kr = (f.get("stocks") or {}).get("KR") or {}
    usi = ((f.get("internals") or {}).get("US") or {}) if kind == "daily" else {}
    # ③ 시장 폭
    L += ["", "**③ 시장 폭**"]
    if kind == "kr" and kr.get("breadth_all"):
        b, t = kr["breadth_all"], kr.get("turnover_tn") or {}
        L.append(f"- 상승 {b['up']:,} · 하락 {b['down']:,} · 보합 {b['flat']:,} · 상한가 {b['limit_up']} · 하한가 {b['limit_down']}"
                 + (" · 거래대금 " + " · ".join(f"{k} {val:,.1f}조" for k, val in t.items()) if t else ""))
    if usi.get("breadth_all"):
        b = usi["breadth_all"]
        L.append(f"- 미국 {usi.get('universe', 0):,}종 상승 {b['up']:,} · 하락 {b['down']:,}" + (f" · 거래대금 {usi['turnover_txt']}" if usi.get("turnover_txt") else ""))
    bc = ctx.get("breadth")
    if bc:
        L.append(f"- 대형주 상승 비율 {bc['today']}% — 최근 {bc['n']}거래일 평균 {bc['avg']}% · {bc['n']}일 중 {bc['rank']}위 · 오른 종목이 더 많은 날 {bc['up_days']}번")
    nh = kr.get("new_high_52w") if kind == "kr" else usi.get("new_high_52w")
    if nh:
        L.append(f"- 52주 신고가(장중) {nh['n']}종/{nh['universe']:,}종"
                 + (" — " + ", ".join(f"{r['name']} {r['ret']:+.1f}%" for r in nh["top"][:6]) if nh.get("top") else ""))

    # ④ 돈의 흐름
    fl = ctx.get("flow") or {}
    us = f.get("us") or {}
    if fl or us.get("assets") or f.get("hy"):
        L += ["", "**④ 돈의 흐름**"]
    for mk, nm in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
        tdy = (fl.get("today") or {}).get(mk)
        cum = (fl.get("foreign_cum") or {}).get(mk)
        if tdy or cum:
            parts = []
            if tdy:
                parts.append(" · ".join(f"{k} {_eok(tdy.get(k))}" for k in ("외국인", "기관", "개인")) + " (오늘 잠정)")
            if cum and cum.get("d5") is not None:
                parts.append(f"외국인 누적 5일 {_eok(cum['d5'])} · 20일 {_eok(cum['d20'])} ({str(cum.get('date'))[5:]} 기준)")
            L.append(f"- {nm} " + " / ".join(parts))
    cr = fl.get("credit")
    if cr:
        L.append(f"- 신용잔고 {cr['tn']:,}조 ({str(cr['date'])[5:]} 기준 · 20일 {cr['chg20']:+.1f}% · 고점 {str(cr.get('peak_date'))[5:]} 대비 {cr['from_peak']:+.1f}%)")
    if us.get("assets"):
        L.append("- 자산 " + ", ".join(f"{a['name']} {a['d1']:+.1f}%" for a in us["assets"]))
    hy = f.get("hy") or {}
    if hy.get("close") is not None:
        L.append(f"- 하이일드 스프레드 {hy['close']}% ({str(hy.get('date'))[5:]} · 1일 {hy.get('d1', 0):+.0f}bp · 5일 {hy.get('d5', 0):+.0f}bp)")

    # ⑤ 업종·테마
    L += ["", "**⑤ 업종·테마**"]
    if kr.get("sectors") and kind == "kr":
        sc = kr["sectors"]
        L.append("- 업종(시총가중) 강세 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[:3])
                 + " · 약세 " + (", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[::-1][:3] if r['ret'] < 0) or "없음"))
    if kr.get("themes_top") and kind == "kr":
        L.append("- 강세 테마 " + ", ".join(f"{t_['name']} {t_['ret']:+.1f}%({'·'.join(x['name'] for x in t_['lead'][:2])})" for t_ in kr["themes_top"][:3])
                 + " · 약세 " + ", ".join(f"{t_['name']} {t_['ret']:+.1f}%" for t_ in kr.get("themes_bottom", [])[:2]))
    if us.get("sectors"):
        sc = us["sectors"]
        L.append("- 미국 섹터 ETF 강세 " + ", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in sc[:3])
                 + " · 약세 " + (", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in sc[::-1][:3] if r['d1'] < 0) or "없음"))
    if usi.get("sectors"):
        sc = usi["sectors"]
        L.append("- 미국 업종(종목 집계) 강세 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[:3])
                 + " · 약세 " + (", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[::-1][:3] if r['ret'] < 0) or "없음"))

    # ⑥ 종목
    L += ["", "**⑥ 종목**"]
    if kind == "kr" and kr.get("top"):
        L.append(f"- 시총 1,000억+ {kr['universe']}종 · 오늘 수익률 강세 " + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in kr["top"])
                 + " · 약세 " + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in kr["bottom"]))
    if kind == "kr":
        if kr.get("featured"):
            L.append("- 특징주 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['tag']})" for r in kr["featured"]))
        if kr.get("turnover_top"):
            L.append("- 거래대금 상위 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['amt_b']:,}억)" for r in kr["turnover_top"][:5]))
        if kr.get("megacaps"):
            L.append("- 시총 상위 10 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%" for r in kr["megacaps"]))
    if usi.get("top"):
        L.append(f"- 미국 대형주(시총 상위 {usi.get('big_n', 500)}) 강세 " + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in usi["top"][:6])
                 + " · 약세 " + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in (usi.get("bottom") or [])[:6]))
    if usi.get("featured"):
        L.append("- 특징주 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['tag']})" for r in usi["featured"][:6]))
    if us.get("megacaps"):
        L.append("- 대장주 " + ", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in us["megacaps"]))
    if kind == "weekly":
        for m in ("KR", "US"):
            s = f["stocks"].get(m) or {}
            if s:
                L += [f"- {m} {_BASIS.get(s['basis'], s['basis'])} 수익률(대형주 {s['universe']}종 · 상승 비율 {s['breadth_up']}%) 강세 "
                      + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in s["top"]) + " · 약세 "
                      + ", ".join(f"{x['name']} {x['ret']:+.1f}%" for x in s["bottom"])]
    sg = f.get("signals") or {}
    if kind != "kr" and sg.get("accel_new") is not None and "accel_week" in sg:
        L.append(f"- 주도주 후보(이익 가속 신규 · {sg.get('accel_week')} 주) " + (", ".join(c['sym'] for c in sg['accel_new']) or "없음"))

    # ⑦ 실전 원장
    lg = ctx.get("ledger") or {}
    if lg:
        L += ["", "**⑦ 실전 원장 (규칙대로 운용하는 실제 계좌 · 공개)**",
              f"- 보유 {lg['n']}종 · 오늘 평균 {lg['d1_avg']:+.1f}% · 평균 손익 {lg['pnl_avg']:+.1f}% · 오늘 체결 {lg['trades_today']}건"
              + f" · 오늘 최고 {lg['best']['name']} {lg['best']['d1']:+.1f}% · 최저 {lg['worst']['name']} {lg['worst']['d1']:+.1f}%"]
        if lg.get("near_stop"):
            L.append("- 손절선 5% 안 " + ", ".join(f"{r['name']}(손절선까지 {r['to_stop']:+.1f}%)" for r in lg["near_stop"]))

    # ⑧ 다가오는 일정
    ev = ctx.get("events") or []
    if ev:
        L += ["", "**⑧ 다가오는 일정(7일)**"] + [f"- {e['date'][5:]}({e.get('wd', '')}) {e.get('time') or ''} {e['name']}".replace("  ", " ") for e in ev]
    L += ["", f"※ 자동 생성(숫자 템플릿) · 투자 권유 아님 · {f['generated']} KST"]
    # 내용 없는 절 머리(**② …**) 는 지운다
    out = []
    for i, ln in enumerate(L):
        if ln.startswith("**") and ln[2:3] in "①②③④⑤⑥⑦⑧":
            nxt = next((x for x in L[i + 1:] if x.strip()), "")
            if not (nxt.startswith("- ") or nxt.startswith("|")):
                if out and out[-1] == "":
                    out.pop()
                continue
        out.append(ln)
    return "\n".join(out)


def _fact_numbers(x, acc=None):
    acc = set() if acc is None else acc
    if isinstance(x, dict):
        for v in x.values():
            _fact_numbers(v, acc)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _fact_numbers(v, acc)
    elif isinstance(x, bool):
        pass
    elif isinstance(x, (int, float)):
        acc.add(round(abs(float(x)), 1))
    elif isinstance(x, str):
        import re
        for m in re.findall(r"\d+(?:\.\d+)?", x):
            acc.add(round(float(m), 1))
    return acc


def unbacked_pcts(md, f):
    """AI 글의 'n%' 중 facts 에 없는 숫자. 2026-10-21: AI 가 상승 비율 27%·67% 를 9.1%·9.5% 로 썼다
    (규칙에 '숫자는 JSON 것만'이라고 적어도 지킨다는 보장이 없다 — 그래서 검사한다)."""
    import re
    have = _fact_numbers(f)
    bad = []
    for m in re.findall(r"(\d+(?:\.\d+)?)\s*%", md or ""):
        v = round(float(m), 1)
        if not any(abs(v - h) <= 0.1 for h in have):
            bad.append(m + "%")
    return bad


_AI_DROP = {"spark", "breadth_hist_w", "breadth_hist_m", "heatmap", "members", "breadth_hist", "hist", "turnover_top", "periods", "KR_mkt", "internals_kr"}


def _ai_slim(x):
    """AI 프롬프트용 — 화면 전용 큰 목록(히트맵·업종 구성 종목·추이)은 뺀다. 2026-11-14(구성 종목 추가로 프롬프트가 커짐)."""
    if isinstance(x, dict):
        return {k: _ai_slim(v) for k, v in x.items() if k not in _AI_DROP}
    if isinstance(x, list):
        return [_ai_slim(v) for v in x]
    return x


def explain_move(f):
    """재료 해설 2문장 — 기사 제목만 근거, 검사 통과 못 하면 1회 고쳐 쓰게 하고 그래도 안 되면 빈칸(제목만 남는다)."""
    import market_narrate as N
    try:
        import market_why as W
        heads = W.headlines(f)
    except Exception as e:
        print("  해설용 기사 생략:", str(e)[:80])
        return ""
    if len(heads) < 2:
        return ""
    prompt = N.EXPLAIN_PROMPT.format(mkt="미국" if f["kind"] != "kr" else "한국", facts=N.explain_facts(f),
                                     heads="\n".join(f"- {h['title']} ({h['source']})" for h in heads))
    for attempt in (1, 2):
        try:
            txt, model = ask_gemini(prompt)
        except Exception as e:
            print("  재료 해설 실패:", str(e)[:80])
            return ""
        txt = " ".join(txt.split())
        bad = N.check_explain(txt, heads, f) + [w for w in direction_errors("## 한 줄 요약\n" + txt, f)]
        if not bad:
            print(f"  재료 해설 통과({model}, 시도 {attempt}): {txt}")
            return txt
        print(f"  재료 해설 검사 실패(시도 {attempt}): {bad[:5]} — {txt[:80]}")
        prompt += "\n[직전 답의 문제 — 고쳐서 다시]\n" + "\n".join(f"- {b}" for b in bad[:6])
    return ""


def english_wrap(f):
    import market_narrate_en as E
    import market_why as W
    heads = W.headlines_en()
    f["why_en"] = [dict(title=h["title"], source=h["source"]) for h in heads[:1]]
    exp = ""
    if len(heads) >= 2:
        prompt = E.EXPLAIN_PROMPT_EN.format(facts=E.explain_facts(f), heads="\n".join(f"- {h['title']} ({h['source']})" for h in heads))
        for attempt in (1, 2):
            try:
                txt, model = ask_gemini(prompt)
            except Exception as e:
                print("  EN explain failed:", str(e)[:80])
                break
            txt = " ".join(txt.split())
            bad = E.check_explain(txt, heads, f)
            if not bad:
                exp = txt
                break
            print(f"  EN explain check failed({attempt}): {bad[:4]}")
            prompt += "\n[Fix these problems]\n" + "\n".join(f"- {b}" for b in bad[:6])
    f["explain_en"] = exp
    n = E.narrate(f)
    ks = next((x.get("date") for x in f.get("indices") or [] if x.get("sym") == "^GSPC"), "")
    n["text"] = E.compose(f, n, ks)
    return n


def render_rules(f):
    """2026-11-25 기본 경로 — 문장은 market_narrate 가 사실에서 직접, 이유는 market_why 가 뉴스 제목 그대로."""
    import market_narrate as N
    try:
        import market_why as W
        f["why"] = W.find(W.targets_for(f))
    except Exception as e:
        print("  이유 뉴스 생략:", str(e)[:100])
        f["why"] = []
    f["explain"] = explain_move(f)
    n = N.narrate(f)
    f["narrative"] = n
    if f["kind"] == "daily":   # 2026-11-26 글로벌판 1단계 — 미국 마감 영어(같은 사실·같은 순서)
        try:
            f["narrative_en"] = english_wrap(f)
        except Exception as e:
            print("  영어판 생략:", str(e)[:100])
    body = [ln for ln in template(f).splitlines()[1:] if not ln.startswith("※")]
    out = [N.compose(f, n), "", "## 숫자"] + body
    if n["checkpoints"]:
        out += ["", "## 체크포인트"] + [f"{i}. {c}" for i, c in enumerate(n["checkpoints"], 1)]
    out += ["", f"※ 사실에서 자동 작성(AI 문장 없음) · '왜'는 뉴스 제목 그대로 · 투자 권유 아님 · {f['generated']} KST"]
    return "\n".join(out), "rules"


def render(f):
    if f["kind"] != "weekly" and not os.environ.get("MR_AI"):   # 2026-11-25 'AI체 없애자'(차니) — 일간·한국은 규칙 문장
        return render_rules(f)
    asof = next((x.get("date") for x in f["indices"] if x.get("date")), f["generated"][:10])
    span = {"daily": "전일 미국 장(한국 지수는 오후 한국 리포트가 다루니 언급하지 말 것)", "weekly": "지난 1주",
            "kr": "오늘 한국 장(마감 기준)"}.get(f["kind"], "최근")
    try:
        txt, model = ask_gemini(PROMPT.format(span=span, asof=asof,
                                              facts=json.dumps(_ai_slim(f), ensure_ascii=False)))
    except Exception as e:
        print("  Gemini 생략 →", str(e)[:120])
        return template(f), "template"
    for attempt in (1, 2):
        bad, wrong = unbacked_pcts(txt, f), direction_errors(txt, f)
        if not bad and not wrong:
            return compose(txt, f), f"gemini:{model}" + ("" if attempt == 1 else "(재작성)")
        print(f"  ⚠️ AI 글 검사 실패(시도 {attempt}) — 근거 없는 숫자 {bad[:6]} · 방향 오류 {wrong[:4]}")
        if attempt == 2:
            break
        fix = ("\n\n[직전 답의 오류 — 고쳐서 다시 써라]\n" + "\n".join(
            [f"- 근거 없는 숫자: {', '.join(bad[:8])}"] * bool(bad) + [f"- 방향 오류: {w}" for w in wrong[:6]]))
        try:
            txt, model = ask_gemini(PROMPT.format(span=span, asof=asof, facts=json.dumps(_ai_slim(f), ensure_ascii=False)) + fix)
        except Exception as e:
            print("  재작성 실패:", str(e)[:100])
            break
    # 사실만 쓰는 리포트 — 두 번 다 틀리면 AI 문장을 버리고 숫자 템플릿으로
    return template(f), f"template(ai_check:{len(bad)}숫자·{len(wrong)}방향)"


_UP = ("상승", "강세", "반등", "급등", "올랐", "오름", "끌어올", "견인", "회복", "랠리")
_DN = ("하락", "약세", "급락", "내렸", "부진", "끌어내", "밀렸", "투매", "폭락", "끌어내렸")


def _direction_book(f):
    """이름 → 1일 등락. 지수·업종·테마·대장주·종목 이름(그리고 흔한 별칭)."""
    book = {}
    def put(name, v):
        if name and v is not None and len(str(name)) >= 2:
            book.setdefault(str(name), float(v))
    alias = {"^GSPC": ("S&P500", "S&P"), "^IXIC": ("나스닥",), "^DJI": ("다우",), "^SOX": ("필라델피아 반도체", "반도체 지수", "반도체 업종", "반도체주"),
             "^KS11": ("코스피",), "^KQ11": ("코스닥",), "^VIX": ("VIX",)}
    for x in f.get("indices") or []:
        for a in alias.get(x.get("sym"), (x.get("name"),)):
            put(a, x.get("d1"))
    kr = (f.get("stocks") or {}).get("KR") or {}
    us = f.get("us") or {}
    usi = (f.get("internals") or {}).get("US") or {}
    for r in kr.get("sectors") or []:
        put(r.get("name"), r.get("ret"))
    for r in (kr.get("themes_top") or []) + (kr.get("themes_bottom") or []):
        put(r.get("name"), r.get("ret"))
    for r in (us.get("sectors") or []):
        put(r.get("name"), r.get("d1"))
    for r in (usi.get("sectors") or []):
        put(r.get("name"), r.get("ret"))
    for r in (us.get("megacaps") or []):
        put(r.get("name"), r.get("d1"))
    for grp in ("megacaps", "top", "bottom", "featured", "turnover_top"):
        for r in (kr.get(grp) or []) + (usi.get(grp) or []):
            put(r.get("name"), r.get("ret"))
    return book


def direction_errors(md, f, min_abs=0.5):
    """AI 문장에서 '이름 + 방향어'가 한 절에 같이 있는데 부호가 반대인 것. 방향어가 둘 다 있는 절은 판단 안 함.
    2026-11-24 — '반도체 업종이 시장 약세를 이끌었으나'(필라델피아 반도체 +14%)가 그대로 발행됐다."""
    import re
    book = _direction_book(f)
    names = sorted(book, key=len, reverse=True)
    body = "\n".join(_ai_section(md, s) for s in ("한 줄 요약", "해설")) or (md or "")
    out = []
    for cl in re.split(r"[.\n,;·]|(?:으나|지만|반면|했고|하며|면서)", body):
        up, dn = any(w in cl for w in _UP), any(w in cl for w in _DN)
        if up == dn:
            continue
        hit = None
        for n in names:
            if n in cl:
                hit = n
                break
        if not hit:
            continue
        v = book[hit]
        if abs(v) >= min_abs and ((up and v < 0) or (dn and v > 0)):
            out.append(f"'{cl.strip()[:40]}' — {hit} 실제 {v:+.1f}%")
    return out


def _ai_section(md, title):
    import re
    m = re.search(rf"^##\s*{re.escape(title)}[^\n]*\n(.*?)(?=^##\s|\Z|^※)", md or "", re.S | re.M)
    return m.group(1).strip() if m else ""


def compose(ai_md, f):
    """AI 문장(한 줄 요약·체크포인트) + 숫자 템플릿 본문. 숫자는 전부 template 이 facts 에서 찍는다."""
    body = template(f).splitlines()
    body = [ln for ln in body[1:] if not ln.startswith("※")]          # 제목·꼬리 줄은 새로
    head = "## " + _TITLE.get(f["kind"], "시황")
    one, chk, why = _ai_section(ai_md, "한 줄 요약"), _ai_section(ai_md, "체크포인트"), _ai_section(ai_md, "해설")
    out = [head, ""]
    if one:
        out += ["## 한 줄 요약", one, ""]
    if why:
        out += ["## 해설", why, ""]
    out += ["## 숫자"] + body
    if chk:
        out += ["", "## 체크포인트", chk]
    out += ["", f"※ 문장 AI · 숫자 자동 · 투자 권유 아님 · {f['generated']} KST"]
    return "\n".join(out)


def main(kind, telegram=False):
    f = facts(kind)
    if kind == "kr":   # 휴장일: 코스피 마지막 확정 봉이 오늘이 아니면 발행하지 않는다(어제 리포트를 오늘 것처럼 덮지 않게)
        from datetime import timezone as _tz, timedelta as _td
        today = (datetime.now(_tz.utc) + _td(hours=9)).date().isoformat()
        ks = next((x for x in f["indices"] if x.get("sym") == "^KS11"), {})
        if ks.get("date") != today:
            print(f"⏭️ 한국 장 마감 리포트 생략 — 코스피 마지막 봉 {ks.get('date')} ≠ 오늘 {today}(휴장 또는 시세 지연)")
            return
        # 2026-11-24 종가 확정 검사 — 장중 스냅샷이면 미룬다(Cloudflare 가 15분 뒤 다시 깨운다). 마지막 시도(16:25 KST~)는
        #   종목 칸을 비우고 지수·수급만으로 발행 — '틀린 종가'보다 '빈칸'이 낫다.
        cc = (f.get("quality") or {}).get("close_check") or {}
        if not cc.get("ok", True):
            kst = datetime.now(_tz.utc) + _td(hours=9)
            msg = f"대형주 가중 {cc.get('big_w')}% vs 코스피 {cc.get('kospi')}% (차 {cc.get('gap')}%p > {cc.get('tol')})"
            if (kst.hour, kst.minute) < (16, 25):
                print(f"⏸️ 한국 리포트 보류 — 종목 시세가 종가가 아니다: {msg}")
                return
            print(f"⚠️ 마지막 시도 — 종목 칸 비우고 발행: {msg}")
            f["stocks"] = {}
            f["quality"]["stocks_dropped"] = True
    # 2026-11-24 발행판 덮어쓰기 금지 — 06:10 에 보낸 판을 15:01 daily-refresh 가 다른 모델로 다시 써 '받은 것 ≠ 사이트'가 됐다.
    old = (_j("results/market_report.json") or {}).get(f"latest_{kind}") or {}
    key0 = {"daily": "^GSPC", "kr": "^KS11"}.get(kind)
    d_new = next((x.get("date") for x in f["indices"] if x.get("sym") == key0 and x.get("date")), None)
    if (old.get("date") == d_new and not str(old.get("engine", "")).startswith("template")
            and not os.environ.get("REPORT_FORCE")):
        print(f"⏭️ {kind} {d_new} 은 이미 발행됨({old.get('generated')} · {old.get('engine')}) — 덮어쓰지 않는다(REPORT_FORCE=1 로 강제)")
        return
    md, engine = render(f)
    if os.environ.get("MR_PREVIEW"):   # 2026-11-24 미리보기 — 발행·저장 없이 출력만(차니 확인용)
        q = f.get("quality") or {}
        out = f"<!-- engine={engine} · close_check={q.get('close_check')} · anomalies={f.get('anomalies')} -->\n" + md
        open(f"preview_{kind}.md", "w", encoding="utf-8").write(out)
        ks = {"daily": "^GSPC", "kr": "^KS11"}.get(kind)
        d0 = next((x.get("date") for x in f["indices"] if x.get("sym") == ks), None)
        json.dump(dict(kind=kind, date=d0, generated=f["generated"], engine=engine, markdown=md, facts=f),
                  open(f"preview_{kind}.json", "w", encoding="utf-8"), ensure_ascii=False, default=str)
        print(out)
        return
    # 리포트 날짜 = 그 리포트가 다루는 장의 날짜(실행일이 아니다). 일요일 실행이 금요일 미국 장을 '새 리포트'로
    #   다시 내보내지 않게 — 봇은 이 날짜로 중복 발송을 막는다(2026-10-21).
    key = {"daily": "^GSPC", "kr": "^KS11"}.get(kind)
    d0 = next((x.get("date") for x in f["indices"] if x.get("sym") == key and x.get("date")), None)
    rec = dict(kind=kind, date=d0 or date.today().isoformat(), generated=f["generated"], engine=engine,
               markdown=md, facts=f)
    db = _j("results/market_report.json") or {}
    db[f"latest_{kind}"] = rec
    hist = [h for h in db.get("history", []) if not (h["kind"] == kind and h["date"] == rec["date"])]
    db["history"] = ([dict(kind=kind, date=rec["date"], engine=engine, markdown=md)] + hist)[:60]
    json.dump(db, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"✅ {kind} 리포트 ({engine}) → {OUT}\n")
    print(md[:1500])
    if telegram:
        try:
            import config
            from telegram_notifier import send_message
            if config.TELEGRAM_ENABLED:
                send_message(config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT_ID,
                             f"📰 {'일간' if kind=='daily' else '주간'} 시황 ({rec['date']})\n\n" + md[:3800])
        except Exception as e:
            print("텔레그램 실패:", e)


if __name__ == "__main__":
    a = sys.argv[1:]
    main("weekly" if "weekly" in a else "kr" if "kr" in a else "daily", telegram="--telegram" in a)


CHAT_PROMPT = """너는 이 대시보드의 시황 도우미다. 아래 [자료]만 근거로 한국어로 짧고 정확하게 답한다.
- 자료에 없는 숫자·뉴스·전망은 지어내지 않는다. 없으면 "자료에 없습니다"라고 말하고 어느 탭에서 볼 수 있는지 안내한다.
- 매수·매도 추천을 하지 않는다. 판단 근거(숫자)만 정리한다.
- 숫자를 인용할 때는 기준일을 같이 적는다. 같은 숫자가 여러 리포트에 있으면 날짜가 가장 최신인 것을 쓴다(한국은 '한국 장 마감').
[자료]
{ctx}
[질문]
{q}"""


def chat_context(extra_rows=None, max_chars=12000):
    """챗봇 자료(2026-11-12 수정). 예전엔 latest_* 를 통째로 이어 붙여 12,000자에서 잘랐는데, 일간+주간이 이미
    12,600자라 한국 장 마감(latest_kr — 테마·수급·업종)이 통째로 잘려 챗봇이 본 적이 없었다.
    → 최신 한국 장 마감을 맨 앞에, 히트맵(2.2만 자) 같은 큰 목록은 빼고, 리포트마다 상한을 둔다."""
    db = _j("results/market_report.json") or {}
    # 2026-11-23: internals_kr(22만 자 — periods·heatmap·업종 구성종목)가 stocks 밖에 붙으면서 다시 themes_top 이
    #   6,000자 밖으로 밀려 잘렸다 → stocks.* 와 internals_* 모두 같은 규칙으로 줄이고, 업종은 구성종목을 뺀다.
    drop = {"heatmap", "turnover_top", "limit_up", "breadth_hist", "breadth_hist_w", "breadth_hist_m", "periods"}
    first = ("themes_top", "themes_bottom", "new_high_52w", "breadth_all", "top", "bottom")

    def _thin(m):
        for k in drop:
            m.pop(k, None)
        if isinstance(m.get("sectors"), list):
            m["sectors"] = [{k: s.get(k) for k in ("name", "n", "ret", "lead", "lead_ret")}
                            for s in m["sectors"] if isinstance(s, dict)]
        head = {k: m.pop(k) for k in first if k in m}
        return {**head, **m}                        # 잘려도 테마·신고가가 앞에 남게

    def _slim(v):
        f = json.loads(json.dumps(v.get("facts") or {}, ensure_ascii=False))
        st = f.get("stocks") or {}
        for mk, m in list(st.items()):
            if isinstance(m, dict):
                st[mk] = _thin(m)
        for k in [k for k in f if k.startswith("internals")]:
            if isinstance(f[k], dict):
                f[k] = _thin(f[k])
        f = {**{k: f.pop(k) for k in [k for k in f if k.startswith("internals")]}, **f}
        return {"date": v.get("date"), "facts": f}

    order = [("latest_kr", "한국 장 마감(가장 최신 한국 숫자)", 6000), ("latest_daily", "일간 — 미국 마감", 4000),
             ("latest_weekly", "주간", 2000)]
    parts = []
    if extra_rows:
        parts.append('"관련 종목": ' + json.dumps(extra_rows, ensure_ascii=False)[:1500])
    for k, lab, cap in order:
        v = db.get(k)
        if isinstance(v, dict):
            parts.append(json.dumps({lab: _slim(v)}, ensure_ascii=False)[:cap])
    return "\n".join(parts)[:max_chars]


def answer(q, key=None, extra_rows=None):
    return ask_gemini(CHAT_PROMPT.format(ctx=chat_context(extra_rows), q=q), key=key)
