# -*- coding: utf-8 -*-
"""🛰️ 플랫폼 상시 감시 — 이 제품이 올라타 있는 남의 땅을 계속 본다 (2026-11-22 신설)

왜 필요한가
  산출물 신선도(data_freshness·check_freshness_ci)는 **우리 파이프라인**이 도는지를 본다.
  그런데 이 제품은 남의 플랫폼 위에 서 있다 — Streamlit Cloud 가 요금제를 바꾸거나,
  SEC 가 User-Agent 규정을 조이거나, DART 가 키당 한도를 내리거나, Supabase 무료 티어가
  일시정지 규칙을 바꾸면 **우리 코드는 그대로인데 제품이 멈춘다.**
  그런 변화는 산출물이 낡기 **전에** 문서에서 먼저 보인다.

세 층 (01_현황 설계)
  L1 매일 상태      — 지금 살아 있나. 쓸 수 있나. 한도 안인가.           → results/platform_status.json
  L2 주 1회 규정 diff — 약관·한도·요금 문서가 바뀌었나(바뀐 '줄'을 보여준다). → results/platform_docs.json
  L3 분기 재평가     — 계속 여기 있어야 하나(비용·종속·단일 실패점·대안).   → results/platform_review_<날짜>.md

이 설계가 깨지는 지점 — 먼저 적는다
  ① **L2 는 오경보 기계가 되기 쉽다.** 약관 페이지에는 공지 배너·실험 마크업·토큰이 섞여
     매주 해시가 바뀐다. 매주 "바뀌었다"가 오면 사람이 보지 않게 되고, 그때부터 감시는 0 이다.
     → 원문 해시를 쓰지 않는다. HTML 을 눈에 보이는 텍스트로 깎고, 바뀐 **줄**을 뽑고,
       그 줄에 KEYWORDS(한도·요금·금지·중단 같은 말)가 들어 있을 때만 '주의'로 올린다.
       나머지는 '문구 변경'으로 기록만 한다. 바뀐 줄은 파일에 남겨 사람이 눈으로 본다.
  ② **프로브가 봇 차단에 걸린다.** 네이버·토스처럼 자동 접근을 막는 곳을 매일 두드리면
     차단당해 멀쩡한 플랫폼을 '죽었다'고 보고한다 → 그런 곳은 kind='indirect',
     **우리 산출물의 신선도로 간접 판정**한다(그 플랫폼이 막히면 산출물이 먼저 낡는다).
  ③ **한 번 실패 ≠ 고장.** 외부 장애·일시적 타임아웃이 우리 빨간불이 되면 역시 무시된다.
     → 연속 실패 횟수(streak)를 파일에 누적하고, FAIL_STREAK 회 연속일 때만 경보로 본다.
  ④ 이 파일은 **감시만** 한다. 자동으로 플랫폼을 바꾸거나 요금제를 건드리지 않는다.

CLI
  python tools/platform_watch.py --l1            # 매일. 연속 실패가 쌓이면 exit 1
  python tools/platform_watch.py --l1 --warn     # 보고만 (exit 0)
  python tools/platform_watch.py --l2            # 주 1회. 주의급 변경이 있으면 exit 1
  python tools/platform_watch.py --l3            # 분기. 재평가 체크리스트를 파일로 낸다
  python tools/platform_watch.py --show          # 등록된 플랫폼 표만 출력(네트워크 안 씀)
"""
import datetime as dt
import difflib
import hashlib
import html
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "results")
STATUS = os.path.join(OUT, "platform_status.json")
DOCS = os.path.join(OUT, "platform_docs.json")

UA = "stock-dashboard platform-watch (+https://github.com/pcy604/stock-dashboard)"
TIMEOUT = 20
FAIL_STREAK = 3            # 이만큼 연속 실패해야 경보 — 외부 일시 장애로 빨간불을 켜지 않는다
MIN_DOC_LINES = 20         # 이보다 짧게 읽히면 JS 렌더로 보고 기준선을 저장하지 않는다(감시하는 척 금지)
MAX_LINE = 300             # 저장하는 줄의 길이 상한 — 약관 한 문장이 수천 자인 곳이 있다

#   L2 에서 '주의'로 올릴 말. 이 말이 **바뀐 줄 안에** 있을 때만 사람을 부른다.
KEYWORDS = [
    "rate limit", "requests per", "per second", "per minute", "per day", "quota", "throttl",
    "limit", "cap ", "price", "pricing", "fee", "billing", "charge", "paid", "free tier",
    "deprecat", "sunset", "discontinu", "retire", "end of life", "breaking change",
    "prohibit", "forbid", "must not", "not permitted", "terminate", "suspend", "ban ",
    "user-agent", "api key", "authentication required", "unauthorized",
    "한도", "제한", "요금", "과금", "유료", "무료", "중단", "종료", "폐지", "금지", "정지",
]

# ──────────────────────────────────────────────────────────────────────────────
# 플랫폼 레지스트리
#   kind    : 'probe'    — 공개 엔드포인트를 직접 두드려 본다
#             'indirect' — 자동 접근을 막는 곳. 우리 산출물 신선도로 간접 판정한다
#             'manual'   — 프로브 수단이 없다(로그인·사람 확인). L3 에서만 다룬다
#   auth    : (환경변수, URL 틀) — 그 비밀값이 **있을 때만** 쓴다. 200 이 아니면 'authfail'.
#             ⚠️ 왜 필요한가: 키 없이 두드리면 403/404 도 '살아 있음'으로 세야 한다(서버는 멀쩡하니까).
#                그러면 **"우리 자격이 끊겼다"를 영원히 못 본다** — SEC 가 User-Agent 규정을 조여
#                403 을 주기 시작해도, FRED 키가 폐기돼도 초록불이다. 비밀값이 있는 플랫폼은
#                '도달 가능'이 아니라 '우리가 쓸 수 있음'까지 재야 감시다.
#   breaks  : 죽으면 제품의 무엇이 멈추나 (경보를 읽는 사람이 바로 판단하게)
#   fallback: 지금 당장 쓸 수 있는 대체 수단. 없으면 '없음' 이라고 적는다 — 그게 단일 실패점이다
#   docs    : L2 가 볼 규정 문서. 한도·요금·금지가 적힌 페이지만.
#   review  : L3 분기 재평가에서 물을 것
# ──────────────────────────────────────────────────────────────────────────────
PLATFORMS = [
    dict(name="SEC EDGAR", kind="probe", used_for="미국 공시·분기재무·주식수·재무상태표",
         probe="https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json",
         auth=("SEC_CONTACT", "https://data.sec.gov/api/xbrl/companyconcept/CIK0000320193/us-gaap/Assets.json"),
         breaks="미국 전 종목 재무·시총·PER·PBR·주도주 신호",
         fallback="없음 (유료 데이터 벤더로 갈아타야 함)",
         docs=["https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data"],
         doc_ua="SEC_CONTACT",   # sec.gov 은 연락처 없는 UA 를 403 으로 막는다
         review="User-Agent·초당 요청 규정 변화 · 429 발생률 · 유료 대안 비용"),
    dict(name="DART (금융감독원)", kind="probe", used_for="한국 공시·분기재무·제출일",
         probe="https://opendart.fss.or.kr/api/list.json?crtfc_key=TEST&bgn_de=20260101&end_de=20260102",
         auth=("DART_KEY", "https://opendart.fss.or.kr/api/list.json?crtfc_key={key}&bgn_de=20260101&end_de=20260102&page_count=1"),
         breaks="한국 분기재무 전체 → 한국 백테스트 패널·흑자전환·이익가속",
         fallback="네이버 재무(비공식·구조 변경 위험)",
         docs=["https://opendart.fss.or.kr/intro/main.do"],
         review="키당 일 한도(현 20,000건) · 과거 소급 제공 범위 · 비공식 소스 의존도"),
    dict(name="FRED (St. Louis Fed)", kind="probe", used_for="매크로 장기 시계열",
         probe="https://api.stlouisfed.org/fred/releases?api_key=TEST&file_type=json",
         auth=("FRED_KEY", "https://api.stlouisfed.org/fred/releases?api_key={key}&file_type=json&limit=1"),
         breaks="🌍 매크로 탭 · 국면 판정 입력",
         fallback="World Bank·yfinance 일부 대체 가능",
         docs=["https://fred.stlouisfed.org/docs/api/terms_of_use.html"],
         review="API 키 정책 · 재배포 조건"),
    dict(name="GitHub (Actions·Release·raw)", kind="probe",
         used_for="전 파이프라인 실행 · 퀀트 패널 릴리스 · marcap 원본",
         probe="https://api.github.com/rate_limit",
         breaks="전부. 수집·발행·봇·패널이 모두 Actions 에서 돈다",
         fallback="없음 (고정 IP 서버로 이전해야 함 — 11-22 보류 중)",
         docs=["https://docs.github.com/en/billing/concepts/product-billing/github-actions",
               "https://docs.github.com/en/actions/reference/limits"],
         review="무료 분 한도 소진율 · 캐시 10GB 한도 · 저장소 pack 크기 추이"),
    dict(name="Streamlit Community Cloud", kind="probe", used_for="대시보드 호스팅(제품 본체)",
         probe="https://share.streamlit.io/",
         breaks="사용자가 보는 화면 전부",
         fallback="없음 (자체 호스팅 이전 필요)",
         docs=["https://streamlit.io/cloud", "https://docs.streamlit.io/deploy/streamlit-community-cloud"],
         review="무료 앱 수·자원 한도 · 비활성 일시정지 규칙 · 유료 전환 시점"),
    dict(name="Supabase", kind="probe", used_for="전략 저장소·VOC·사용 로그·이미지 버킷",
         probe="https://supabase.com/",
         breaks="퀀트 전략 저장·공개 게시판·VOC 접수·유입 집계",
         fallback="없음 (화면은 떠도 저장 기능이 죽는다)",
         docs=["https://supabase.com/pricing"],
         review="무료 티어 비활성 일시정지(현 1주) · DB 용량 · Storage 용량 · 월 활성 사용자"),
    dict(name="Telegram Bot API", kind="probe", used_for="봇 발행·실패 경보·딥리포트 배달",
         probe="https://api.telegram.org/",
         auth=("TELEGRAM_TOKEN", "https://api.telegram.org/bot{key}/getMe"),
         breaks="봇 알림·실패 경보 전달(경보가 안 오면 고장을 모른다)",
         fallback="GitHub Actions 실패 메일",
         docs=["https://core.telegram.org/bots/faq"],
         review="초당 전송 한도 · 대량 발송 정책 · 봇 정지 사유"),
    dict(name="Yahoo Finance (yfinance)", kind="probe", used_for="일봉·주봉 가격 전반",
         probe="https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d",
         breaks="가격 시계열 → 스크리너·백테스트·주도주 전부",
         fallback="FinanceDataReader·pykrx(한국) · 미국은 사실상 없음",
         docs=["https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html"],
         review="비공식 API 차단 추이 · 429 발생률 · 유료 대안(polygon 등) 비용"),
    dict(name="Google Gemini", kind="probe", used_for="AI 챗봇·요약·해설",
         probe="https://generativelanguage.googleapis.com/v1beta/models",
         auth=("GEMINI_KEY", "https://generativelanguage.googleapis.com/v1beta/models?key={key}"),
         breaks="💬 챗봇·AI 해설(제품은 돌고 설명만 사라진다)",
         fallback="Groq (이미 예비로 배선돼 있다)",
         docs=["https://ai.google.dev/pricing"],
         review="무료 티어 분당·일 한도 · 모델 폐지 일정 · 예비(Groq) 실제 작동 확인"),
    # ── 자동 접근을 막는 곳 — 직접 두드리지 않는다(②) ───────────────────────
    dict(name="네이버 금융", kind="indirect", used_for="한국 컨센서스·분기재무 보조",
         indirect=["results/consensus_q.json", "data/kr_fundamentals_q.parquet"],
         breaks="한국 컨센서스 추세·일부 재무 보조 값",
         fallback="DART (공식, 단 컨센서스는 없음)",
         docs=[],
         review="비공식 스크래핑 의존 — 구조 변경 시 복구 시간 · 공식 대안 유무"),
    dict(name="토스증권", kind="indirect", used_for="실전 잔고 동기화·주문",
         indirect=["live/plan_latest.json"],
         breaks="실전 원장·주문 봇 (허용 IP 때문에 노트북 전용 — 고정 IP 보류 중)",
         fallback="없음 (수동 입력)",
         docs=[],
         review="허용 IP 정책 · 고정 IP 서버 도입 여부(11-22 보류) · 결행률 추이"),
    # ── 프로브 수단 없음 — L3 에서만 ────────────────────────────────────────
    dict(name="Meta (Threads·Instagram)", kind="manual", used_for="stock_studian 소셜 발행",
         breaks="소셜 발행 자동화(콘텐츠 큐는 남는다)",
         fallback="수동 게시",
         docs=["https://developers.facebook.com/docs/threads/overview"],
         review="앱 토큰 발급 상태(사용자 몫) · 게시 한도 · 심사 정책"),
    dict(name="X (Twitter) API", kind="manual", used_for="stock_studian 소셜 발행",
         breaks="소셜 발행 자동화",
         fallback="수동 게시",
         docs=["https://developer.x.com/en/docs/x-api"],
         review="무료 티어 월 게시 한도 · 요금 변화"),
]


# ──────────────────────────────────────────────────────────────────────────────
# 공통
# ──────────────────────────────────────────────────────────────────────────────
def _load(path, default):
    try:
        return json.loads(open(path, encoding="utf-8").read())
    except Exception:
        return default


def _save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    #   newline="\n" — Windows 로컬과 CI(리눅스)가 같은 바이트를 내게. 안 그러면 CRLF/LF 만
    #   달라도 파일이 '바뀐' 것으로 보여 쓸데없는 커밋이 생긴다.
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1, sort_keys=True)


def _get(url, want_text=False, ua=None):
    """(ok, 코드 또는 사유, 본문). 401/403/429 는 '살아 있지만 우리 자격이 막힘'으로 따로 센다."""
    req = urllib.request.Request(url, headers={"User-Agent": ua or UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read(400_000) if want_text else b""
            return True, r.status, body.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        #   키 없이 두드리는 프로브는 400/401/403 이 **정상 응답**이다(서버가 살아 있다는 뜻).
        #   429 는 한도, 5xx 는 장애로 가른다.
        alive = e.code in (400, 401, 403, 404)
        return alive, e.code, ""
    except Exception as e:
        return False, f"{type(e).__name__}", ""


def _text_lines(raw):
    """HTML → 눈에 보이는 텍스트 줄. script·style·주석·태그를 걷고 공백을 정규화한다.
    (원문 해시를 쓰면 배너·토큰 때문에 매주 바뀐다 — ① 참조)"""
    s = re.sub(r"(?is)<(script|style|noscript|svg)\b.*?</\1>", " ", raw)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"(?s)<[^>]+>", "\n", s)
    s = html.unescape(s)
    out = []
    for ln in s.splitlines():
        ln = re.sub(r"\s+", " ", ln).strip()
        if len(ln) >= 3:
            out.append(ln)
    return out


def _noteworthy(lines):
    """주의어가 든 줄만. 저장·출력용이라 줄 길이를 자른다(약관 한 문장이 2,000자인 곳이 있다)."""
    low = [l.lower() for l in lines]
    return [lines[i][:MAX_LINE] for i, l in enumerate(low) if any(k in l for k in KEYWORDS)]


def _probe(p):
    """(state, why). state: 'ok'(인증된 200) · 'reachable'(비밀값 없음 — 서버만 살아 있음)
    · 'authfail'(비밀값은 있는데 거부) · 'down'.

    ⚠️ 'reachable' 은 **초록불이 아니다.** 비밀값이 러너에 없다는 뜻이고, 그 플랫폼은
    "우리가 쓸 수 있나"를 재지 못한 상태다. 경보로 올리지는 않지만(로컬 실행에서 매번 울리면
    의미가 없다) 상태 파일에 그대로 남겨 L3 에서 '감시 못 한 플랫폼'으로 세게 한다."""
    if not p.get("auth"):
        #   비밀값이 필요 없는 플랫폼 — 공개 엔드포인트가 200 이면 그게 '쓸 수 있음'이다
        ok, code, _ = _get(p["probe"])
        if code == 200:
            return "ok", "HTTP 200"
        return ("reachable" if ok else "down"), f"HTTP {code}"
    env, url = p["auth"]
    key = (os.environ.get(env) or "").strip()
    if not key:
        ok, code, _ = _get(p["probe"])
        return ("reachable" if ok else "down"), f"HTTP {code} (비밀값 {env} 없음 — 도달만 확인)"
    #   SEC 는 키가 아니라 연락처를 User-Agent 에 실어야 한다 — 같은 틀로 다루되 전달 방식만 다르다.
    if env == "SEC_CONTACT":
        ok, code, _ = _get(url, ua=key)
    else:
        ok, code, _ = _get(url.format(key=urllib.parse.quote(key, safe="")))
    if code == 200:
        return "ok", "HTTP 200 (인증 확인)"
    if code in (401, 403, 429):
        return "authfail", f"HTTP {code} — 비밀값은 있는데 거부됐다({env})"
    return ("reachable" if ok else "down"), f"HTTP {code}"


# ──────────────────────────────────────────────────────────────────────────────
# L1 — 매일 상태
# ──────────────────────────────────────────────────────────────────────────────
def l1(warn_only=False):
    prev = _load(STATUS, {}).get("platforms", {})
    today = dt.date.today().isoformat()
    rows, alarms = {}, []
    import data_freshness as F                     # indirect 판정에 쓴다
    for p in PLATFORMS:
        name = p["name"]
        was = prev.get(name, {})
        if p["kind"] == "probe":
            state, why = _probe(p)
        elif p["kind"] == "indirect":
            st = F.statuses(only=set(p["indirect"]))
            bad = [r for r in st if r["state"] != "ok"]
            state = "ok" if not bad else "down"
            why = "산출물 최신" if not bad else "산출물 " + " · ".join(
                f"{r['path']}: {r['note'] or r['state']}" for r in bad)
        else:
            rows[name] = dict(kind=p["kind"], state="manual", why="프로브 수단 없음 — L3 에서 본다",
                              streak=0, checked=today)
            continue
        #   'authfail'(우리 자격이 끊겼다)과 'down'(서버가 안 뜬다)만 연속 실패로 센다.
        #   'reachable' 은 "비밀값이 없어 못 재 봤다" 이므로 실패로 세지 않는다 — 안 그러면
        #   비밀값이 없는 로컬 실행이 매번 빨간불이 되어 경보가 쓰레기가 된다.
        streak = int(was.get("streak") or 0) + 1 if state in ("down", "authfail") else 0
        rows[name] = dict(kind=p["kind"], state=state, why=why, streak=streak, checked=today,
                          breaks=p["breaks"], fallback=p["fallback"])
        #   자격 거부는 일시 장애가 아니다 — 1회로 바로 올린다. 서버 미응답만 streak 를 기다린다.
        if state == "authfail" or streak >= FAIL_STREAK:
            alarms.append((name, state, streak, why, p["breaks"], p["fallback"]))
    _save(STATUS, dict(asof=today, fail_streak_alarm=FAIL_STREAK, platforms=rows))

    for name, r in sorted(rows.items()):
        mark = {"ok": "OK  ", "reachable": "REACH", "authfail": "AUTH", "down": "DOWN",
                "manual": "--  "}[r["state"]]
        extra = f"  연속실패 {r['streak']}회" if r["streak"] else ""
        print(f"  [{mark:<5s}] {name:<30s} {r['why']}{extra}")
    unchecked = [n for n, r in rows.items() if r["state"] in ("reachable", "manual")]
    if unchecked:
        print(f"\n못 재 본 플랫폼 {len(unchecked)}개(비밀값 없음·프로브 없음): {', '.join(unchecked)}")
    if not alarms:
        pend = [n for n, r in rows.items() if r["state"] == "down"]
        print("경보 없음" + (f" (1~{FAIL_STREAK - 1}회 실패 관찰 중: {', '.join(pend)})" if pend else ""))
        return 0
    print("\n경보:")
    for name, state, streak, why, breaks, fb in alarms:
        head = "자격 거부" if state == "authfail" else f"{streak}회 연속 실패"
        print(f"  ::error::{name} {head} ({why}) — 멈추는 것: {breaks} / 대체: {fb}")
    return 0 if warn_only else 1


# ──────────────────────────────────────────────────────────────────────────────
# L2 — 주 1회 규정 문서 diff
# ──────────────────────────────────────────────────────────────────────────────
def l2(warn_only=False):
    store = _load(DOCS, {})
    docs = store.get("docs", {})
    today = dt.date.today().isoformat()
    changed, attention, failed, unreadable = [], [], [], []
    for p in PLATFORMS:
        for url in p.get("docs") or []:
            ok, code, body = _get(url, want_text=True,
                                  ua=(os.environ.get(p.get("doc_ua") or "") or None))
            if not body:
                failed.append((p["name"], url, code))
                continue
            lines = _text_lines(body)
            #   ⚠️ JS 로 본문을 그리는 문서(Gemini 요금·Meta 개요)는 정적 HTML 에 1~2줄만 들어 있다.
            #      그 1줄을 기준선으로 저장하면 **영원히 '변경 없음'**이 되어 감시하는 척만 한다.
            #      그래서 저장하지 않고 '감시 불가'로 부른다 — 사람이 다른 URL 을 찾거나 손으로 봐야 한다.
            if len(lines) < MIN_DOC_LINES:
                unreadable.append((p["name"], url, f"본문 {len(lines)}줄 — JS 렌더로 보인다"))
                print(f"  [JS? ] {p['name']:<28s} {url}  본문 {len(lines)}줄 → 감시 불가")
                continue
            # ⚠️ 본문 전체를 저장하면 이 파일이 400KB 가 되고, 주마다 커밋되어 저장소를 불린다
            #    (us_shares.csv 가 pack 220MB 중 88MB 를 먹던 것과 같은 실수). 그래서 두 개만 둔다:
            #      ① 전문 해시 — '뭐라도 바뀌었나'는 이걸로 안다(32자)
            #      ② 주의어가 든 줄만 — 실제로 비교해야 하는 줄은 한도·요금·금지 문장뿐이다
            #    대가: 주의어가 **없는** 문장의 변경은 '바뀌었다'까지만 알고 어디가 바뀐지는 모른다.
            #    그건 어차피 기록만 하던 급이라 바꿀 가치가 있다고 봤다.
            key_lines = _noteworthy(lines)
            digest = hashlib.sha1("\n".join(lines).encode("utf-8")).hexdigest()[:16]
            old = docs.get(url, {})
            if not old.get("sha"):
                docs[url] = dict(platform=p["name"], sha=digest, key_lines=key_lines,
                                 n_lines=len(lines), first_seen=today, last_change=today)
                print(f"  [NEW ] {p['name']:<28s} {url}  (본문 {len(lines)}줄 · 주의어 줄 {len(key_lines)}개 기준선)")
                continue
            if old["sha"] == digest:
                print(f"  [SAME] {p['name']:<28s} {url}")
                continue
            diff = [d for d in difflib.unified_diff(old.get("key_lines") or [], key_lines, lineterm="", n=0)
                    if d[:1] in "+-" and d[:3] not in ("+++", "---")]
            docs[url].update(sha=digest, key_lines=key_lines, n_lines=len(lines),
                             last_change=today, last_diff=diff[:120])
            if diff:
                attention.append((p["name"], url, [d for d in diff][:10], p["breaks"], p["fallback"]))
                print(f"  [⚠️  ] {p['name']:<28s} {url}  한도·요금·금지 줄 {len(diff)}개 변경")
            else:
                changed.append((p["name"], url, old.get("n_lines"), len(lines)))
                print(f"  [문구] {p['name']:<28s} {url}  본문은 바뀌었으나 한도·요금 줄은 그대로 "
                      f"({old.get('n_lines')}→{len(lines)}줄)")
    #   ⚠️ asof 를 넣지 않는다. 넣으면 문서가 하나도 안 바뀐 주에도 파일이 달라져 **매주 커밋**되고
    #      저장소가 234KB × 52회/년 으로 불어난다. 날짜는 문서별 first_seen·last_change 에 이미 있다.
    _save(DOCS, dict(docs=docs))

    if failed or unreadable:
        print("\n⚠️ 감시가 비어 있는 문서 — 여기는 규정이 바뀌어도 모른다:")
        for n, u, c in failed:
            print(f"  ::warning::{n}: {u} → 못 받았다({c}). URL 이 이전됐거나 UA 가 차단됐다")
        for n, u, c in unreadable:
            print(f"  ::warning::{n}: {u} → {c}. 정적 HTML 로 읽히는 다른 URL 을 찾거나 L3 에서 손으로 본다")
    if changed:
        print(f"\n문구만 바뀐 문서 {len(changed)}개 — 기록만 한다(results/platform_docs.json 의 last_diff).")
    if not attention:
        print("\n한도·요금·금지 관련 변경 없음")
        return 0
    print("\n⚠️ 한도·요금·금지 관련 문구가 바뀌었다 — 눈으로 확인할 것:")
    for name, url, hits, breaks, fb in attention:
        print(f"  ::warning::{name} — {url}")
        print(f"      멈추는 것: {breaks} / 대체: {fb}")
        for h in hits:
            print(f"      · {h[:160]}")
    return 0 if warn_only else 1


# ──────────────────────────────────────────────────────────────────────────────
# L3 — 분기 재평가
# ──────────────────────────────────────────────────────────────────────────────
def l3():
    today = dt.date.today().isoformat()
    st = _load(STATUS, {}).get("platforms", {})
    docs = _load(DOCS, {}).get("docs", {})
    path = os.path.join(BASE, "docs", "research", f"{today}_플랫폼_재평가.md")
    spof = [p for p in PLATFORMS if (p.get("fallback") or "").startswith("없음")]
    L = [f"# 플랫폼 분기 재평가 — {today}", "",
         "L1(매일 상태)·L2(주 1회 규정 diff)가 모은 것을 놓고 **계속 여기 있어야 하나**를 묻는다.",
         "이 파일은 틀을 만들어 주기만 한다 — 판단은 사람이 적는다.", "",
         f"## 단일 실패점 {len(spof)}개 — 대체 수단이 '없음'으로 등록된 것", ""]
    L += ["| 플랫폼 | 쓰는 곳 | 죽으면 멈추는 것 |", "|---|---|---|"]
    L += [f"| {p['name']} | {p['used_for']} | {p['breaks']} |" for p in spof]
    L += ["", "## 전체 플랫폼", "",
          "| 플랫폼 | 종류 | 쓰는 곳 | 최근 L1 | 대체 | 분기마다 물을 것 |", "|---|---|---|---|---|---|"]
    for p in PLATFORMS:
        s = st.get(p["name"], {})
        cur = f"{s.get('state', '-')}" + (f" (연속실패 {s['streak']})" if s.get("streak") else "")
        L.append(f"| {p['name']} | {p['kind']} | {p['used_for']} | {cur} | "
                 f"{p.get('fallback', '-')} | {p.get('review', '-')} |")
    L += ["", "## 지난 분기에 규정이 바뀐 문서", ""]
    recent = sorted(((v.get("last_change") or "", u, v.get("platform")) for u, v in docs.items()), reverse=True)
    if recent:
        L += ["| 바뀐 날 | 플랫폼 | 문서 |", "|---|---|---|"]
        L += [f"| {d} | {pl} | {u} |" for d, u, pl in recent[:20]]
    else:
        L.append("아직 L2 기준선만 있다(첫 실행). 다음 분기부터 채워진다.")
    L += ["", "## 적어 넣을 것 (사람)", "",
          "- [ ] 비용: 지난 분기 실제 지출 · 무료 한도 소진율(%) · 다음 분기 예상",
          "- [ ] 종속: 이 플랫폼을 떠나는 데 걸릴 시간(일) — 추정이 아니라 한 번이라도 재 본 값으로",
          "- [ ] 단일 실패점: 위 표의 '없음'을 하나라도 줄였는가. 못 줄였으면 왜",
          "- [ ] 사고: 지난 분기 L1 경보 건수와 그때 제품이 실제로 멈춘 시간",
          "- [ ] 결정: 유지 / 이전 준비 / 즉시 이전 — 각 플랫폼마다 한 줄",
          ""]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write("\n".join(L) + "\n")
    print(f"재평가 틀 작성: {os.path.relpath(path, BASE)}")
    print(f"  단일 실패점 {len(spof)}개: {', '.join(p['name'] for p in spof)}")
    return 0


def show():
    print(f"{'플랫폼':<30s} {'종류':<9s} {'대체':<40s} 쓰는 곳")
    for p in PLATFORMS:
        print(f"{p['name']:<30s} {p['kind']:<9s} {(p.get('fallback') or '-')[:38]:<40s} {p['used_for']}")
    print(f"\n총 {len(PLATFORMS)}개 · 프로브 {sum(1 for p in PLATFORMS if p['kind'] == 'probe')}"
          f" · 간접 {sum(1 for p in PLATFORMS if p['kind'] == 'indirect')}"
          f" · 수동 {sum(1 for p in PLATFORMS if p['kind'] == 'manual')}"
          f" · 감시 문서 {sum(len(p.get('docs') or []) for p in PLATFORMS)}개")
    return 0


def main():
    sys.path.insert(0, BASE)
    warn = "--warn" in sys.argv
    if "--show" in sys.argv:
        return show()
    if "--l1" in sys.argv:
        return l1(warn)
    if "--l2" in sys.argv:
        return l2(warn)
    if "--l3" in sys.argv:
        return l3()
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
