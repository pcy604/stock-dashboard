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
from datetime import datetime, date

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
BASE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(BASE, "results", "market_report.json")
INDICES = [("^KS11", "코스피"), ("^KQ11", "코스닥"), ("^GSPC", "S&P500"), ("^IXIC", "나스닥"),
           ("^SOX", "필라델피아 반도체"), ("^VIX", "VIX"), ("KRW=X", "원/달러"), ("^TNX", "미국 10년물(%)")]
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.0-flash"]


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


# 2026-10-21: 10-21 일간 리포트가 한국 09:26(장중)에 만들어져 코스피 장중 값이 '종가'로 찍혔다(실제 그날 +4%대).
#   장이 아직 열려 있는 시장의 '오늘 봉'은 미완성이라 버린다 — 언제 돌려도 마지막 확정 종가만 쓴다.
_SESSION = {"KR": ("Asia/Seoul", 15, 45), "US": ("America/New_York", 16, 15)}   # 마감 + 15분 여유
_MKT_OF = {"^KS11": "KR", "^KQ11": "KR", "^GSPC": "US", "^IXIC": "US", "^SOX": "US", "^VIX": "US", "^TNX": "US"}


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
                           above_200d=bool(c > s.iloc[-200:].mean()) if len(s) >= 200 else None)
            out.append(row)
        except Exception as e:
            out.append(dict(name=name, sym=sym, error=str(e)[:60]))
    return out


def us_extra_facts():
    pairs = US_ASSETS + US_SECTORS + US_MEGA
    df = _download([s for s, _ in pairs])
    q = {x["sym"]: x for x in quote_facts(pairs, df, short=True)}
    pick = lambda L: [q[s] for s, _ in L if "close" in q.get(s, {})]
    sec = sorted(pick(US_SECTORS), key=lambda x: -x["d1"])
    return dict(assets=pick(US_ASSETS), sectors=sec, megacaps=pick(US_MEGA))


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
                            above_200d=bool(c > s.iloc[-200:].mean()) if len(s) >= 200 else None))
        except Exception as e:
            out.append(dict(name=name, sym=sym, error=str(e)[:60]))
    return out


def stock_facts(kind):
    p = _j("results/perf_latest.json")
    st = p.get("stocks", [])
    key = "ret_1w" if kind == "daily" else "ret_4w"
    res = {"perf_date": p.get("date")}
    for m, cap in (("KR", 1e12), ("US", 1e10)):
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
    ck, cu = _j("results/canslim_latest.json"), _j("results/canslim_us_latest.json")
    acc = _j("results/leaders_accel.json")
    ta = _j("results/turnaround_latest.json")
    return dict(
        market_direction={"KR": ck.get("market_dir"), "US": cu.get("market_dir")},
        canslim_candidates={"KR": len(ck.get("stocks", [])), "US": len(cu.get("stocks", []))},
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
    big = df[(df["Marcap"] >= 1e12) & df["_r"].notna()].sort_values("_r")
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
                lead = g.sort_values("Marcap", ascending=False).iloc[0]
                sectors.append(dict(name=_sec_short(sec), n=len(g), ret=_r((g["_r"] * w).sum(), 1),
                                    lead=lead["Name"], lead_ret=_r(lead["_r"], 1)))
        sectors.sort(key=lambda x: -x["ret"])
    except Exception as e:
        print("  업종 집계 생략:", str(e)[:80])
    return {"KR": dict(universe=len(big), basis="d1", asof=today,
                       top=[row(r) for _, r in big[::-1].head(6).iterrows()],
                       bottom=[row(r) for _, r in big.head(6).iterrows()],
                       breadth_up=round((big["_r"] > 0).mean() * 100) if len(big) else None,
                       breadth_all=breadth, turnover_tn=turnover, megacaps=mega, sectors=sectors)}


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


def facts(kind):
    if kind == "kr":
        sg = signal_facts()
        return dict(kind=kind, generated=datetime.now().strftime("%Y-%m-%d %H:%M"), verdict={},
                    indices=[x for x in index_facts() if x.get("sym") in KR_INDICES], stocks=kr_today_facts(),
                    signals=dict(market_direction={"KR": sg["market_direction"].get("KR")}))
    f = dict(kind=kind, generated=datetime.now().strftime("%Y-%m-%d %H:%M"), verdict=verdict_facts(),
             indices=index_facts(), stocks=stock_facts(kind), signals=signal_facts())
    if kind == "daily":
        try:
            f["us"] = us_extra_facts()
        except Exception as e:
            print("  미국 자산·업종·대장주 생략:", str(e)[:100])
    return f


# 2026-10-21: AI 는 '문장'만 쓴다 — 표·숫자 나열은 template() 가 facts 에서 그대로 찍는다.
#   예전엔 AI 가 표까지 다시 썼고, 상승 비율 27%·67% 를 9.1%·9.5% 로 옮겨 적었다. 문장 안 숫자도 unbacked_pcts 로 검사.
PROMPT = """너는 개인투자자용 시황 리포트를 쓰는 애널리스트다. 아래 JSON 은 {span} 시장 데이터다.
규칙:
- **JSON 에 있는 숫자와 이름만 쓴다.** 뉴스·이벤트·원인·전망을 지어내지 않는다. 원인을 모르면 '데이터상 원인 불명'.
- 숫자는 꼭 필요할 때만, JSON 값 그대로(소수 1자리 %). 표는 쓰지 않는다(표는 따로 붙는다).
- 한국어, 마크다운. 아래 두 절만 쓴다:
  ## 한 줄 요약   (한두 문장 — 지수 방향 + 무엇이 끌었나(업종·대장주) + 시장 폭. 숫자는 소수 1자리)
  ## 체크포인트   (데이터에서 보이는 것 3가지, 번호 목록 — 예측 금지, '확인할 것'만.
                  표 숫자를 그대로 되풀이하지 말고 서로 다른 데이터를 연결해 읽는다:
                  지수 vs 시장 폭(상승/하락 종목 수), 업종 vs 대장주, 1일 vs 5일·1개월, 자산(달러·금리·유가) vs 주식)
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
    for m in models:                      # 무료 한도는 모델별로 따로다 — 막히면 다음 모델
        try:
            r = cl.models.generate_content(model=m, contents=prompt)
            if (r.text or "").strip():
                return r.text.strip(), m
        except Exception as e:
            last = e
    raise RuntimeError(f"Gemini 실패: {str(last)[:120]}")


_TITLE = {"daily": "일간 시황", "weekly": "주간 시황", "kr": "한국 장 마감 시황"}
_BASIS = {"d1": "오늘", "ret_1w": "1주", "ret_4w": "4주"}


def template(f):
    """AI 없이도 발행되는 숫자 리포트."""
    v = f.get("verdict") or {}
    L = [f"## {_TITLE.get(f['kind'], '시황')} — 숫자 요약", ""]
    if v:
        t = v.get("target_core_sat_cash") or [None] * 3
        L += [("⚠️ **코어 스위치 전환** · " if v.get("changed") else "") +
              f"**이번 주 판정** — 코어 {'ON' if v.get('core_on') else 'OFF'} (S&P500 200일선 {v.get('core_gap_200d', 0):+.1f}%) · "
              f"목표 코어 {t[0]} / 위성 {t[1]} / 현금 {t[2]} · 국면 {v.get('phase_ref') or '-'}(참고) · 욕심 경고 {v.get('greed_warn_n', '-')}/3(참고)", ""]
    L += ["| 지수 | 종가 | 1일 | 5일 | 1개월 | 52주고 대비 |", "|---|---|---|---|---|---|"]
    for x in f["indices"]:
        if "close" in x:
            L.append(f"| {x['name']} | {x['close']:,} | {x['d1']:+.1f}% | {x['d5']:+.1f}% | {x['m1']:+.1f}% | {x['from_52w_high']:+.1f}% |")
    for m in ("KR", "US"):
        s = f["stocks"].get(m) or {}
        if not s:
            continue
        L += ["", f"**{m}** ({_BASIS.get(s['basis'], s['basis'])} 수익률, 대형주 {s['universe']}종 · 상승 비율 {s['breadth_up']}%)",
              "강세: " + ", ".join(f"{t['name']} {t['ret']:+.1f}%" for t in s["top"]),
              "약세: " + ", ".join(f"{t['name']} {t['ret']:+.1f}%" for t in s["bottom"])]
        if "near_52w" in s:
            L.append(f"52주 신고가 근접 {s['near_52w']}종 · 이번 주 경신 {s['new_high']}종")
    kr = (f.get("stocks") or {}).get("KR") or {}
    if kr.get("breadth_all"):
        b, t = kr["breadth_all"], kr.get("turnover_tn") or {}
        L += ["", f"**시장 폭** 상승 {b['up']:,} · 하락 {b['down']:,} · 보합 {b['flat']:,} · 상한가 {b['limit_up']} · 하한가 {b['limit_down']}"
              + (" · 거래대금 " + " · ".join(f"{k} {v:,.1f}조" for k, v in t.items()) if t else "")]
    if kr.get("megacaps"):
        L.append("**시총 상위 10** " + ", ".join(f"{r['name']} {r['ret']:+.1f}%" for r in kr["megacaps"]))
    if kr.get("sectors"):
        sc = kr["sectors"]
        L.append("**업종(시총가중)** 강세 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[:3])
                 + " · 약세 " + ", ".join(f"{r['name']} {r['ret']:+.1f}%({r['lead']})" for r in sc[::-1][:3]))
    us = f.get("us") or {}
    if us.get("assets"):
        L += ["", "**자산** " + ", ".join(f"{a['name']} {a['d1']:+.1f}%" for a in us["assets"])]
    if us.get("sectors"):
        sc = us["sectors"]
        L.append("**업종(섹터 ETF)** 강세 " + ", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in sc[:3])
                 + " · 약세 " + ", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in sc[::-1][:3]))
    if us.get("megacaps"):
        L.append("**대장주** " + ", ".join(f"{r['name']} {r['d1']:+.1f}%" for r in us["megacaps"]))
    sg = f["signals"]
    md_ = sg.get("market_direction") or {}
    L += ["", "CANSLIM 시장방향 " + " · ".join(f"{m} {md_[m]}" for m in ("KR", "US") if md_.get(m))]
    if "accel_new" in sg:
        L.append(f"이익가속 신규({sg.get('accel_week')}): " + (", ".join(c['sym'] for c in sg['accel_new']) or "없음"))
    L += ["", f"※ 자동 생성(숫자 템플릿) · 투자 권유 아님 · {f['generated']}"]
    return "\n".join(L)


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


def render(f):
    asof = next((x.get("date") for x in f["indices"] if x.get("date")), f["generated"][:10])
    span = {"daily": "전일 미국 장(한국 지수는 오후 한국 리포트가 다루니 언급하지 말 것)", "weekly": "지난 1주",
            "kr": "오늘 한국 장(마감 기준)"}.get(f["kind"], "최근")
    try:
        txt, model = ask_gemini(PROMPT.format(span=span, asof=asof,
                                              facts=json.dumps(f, ensure_ascii=False)))
    except Exception as e:
        print("  Gemini 생략 →", str(e)[:120])
        return template(f), "template"
    bad = unbacked_pcts(txt, f)
    if bad:   # 틀린 숫자가 하나라도 있으면 AI 글을 버리고 숫자 템플릿으로 — 사실만 쓰는 리포트다
        print(f"  ⚠️ AI 글에 근거 없는 숫자 {len(bad)}개 → 숫자 템플릿: {', '.join(bad[:8])}")
        return template(f), f"template(ai_unbacked:{len(bad)})"
    return compose(txt, f), f"gemini:{model}"


def _ai_section(md, title):
    import re
    m = re.search(rf"^##\s*{re.escape(title)}[^\n]*\n(.*?)(?=^##\s|\Z|^※)", md or "", re.S | re.M)
    return m.group(1).strip() if m else ""


def compose(ai_md, f):
    """AI 문장(한 줄 요약·체크포인트) + 숫자 템플릿 본문. 숫자는 전부 template 이 facts 에서 찍는다."""
    body = template(f).splitlines()
    body = [ln for ln in body[1:] if not ln.startswith("※")]          # 제목·꼬리 줄은 새로
    head = "## " + _TITLE.get(f["kind"], "시황")
    one, chk = _ai_section(ai_md, "한 줄 요약"), _ai_section(ai_md, "체크포인트")
    out = [head, ""]
    if one:
        out += ["## 한 줄 요약", one, ""]
    out += ["## 숫자"] + body
    if chk:
        out += ["", "## 체크포인트", chk]
    out += ["", f"※ 문장 AI · 숫자 자동 · 투자 권유 아님 · {f['generated']}"]
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
    md, engine = render(f)
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
- 숫자를 인용할 때는 기준일을 같이 적는다.
[자료]
{ctx}
[질문]
{q}"""


def chat_context(extra_rows=None, max_chars=12000):
    db = _j("results/market_report.json") or {}
    ctx = {k: {"date": v.get("date"), "facts": v.get("facts")} for k, v in db.items()
           if k.startswith("latest_") and isinstance(v, dict)}
    if extra_rows:
        ctx["관련 종목"] = extra_rows
    t = json.dumps(ctx, ensure_ascii=False)
    return t[:max_chars]


def answer(q, key=None, extra_rows=None):
    return ask_gemini(CHAT_PROMPT.format(ctx=chat_context(extra_rows), q=q), key=key)
