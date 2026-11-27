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
MAX_WF_IDLE_DAYS = 14      # 예정 워크플로의 마지막 성공이 이보다 오래면 경보(R3)

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
    #   ⚠️ kind='project' — supabase.com 이 200 인 것은 **우리 프로젝트가 살아 있다는 뜻이 아니다.**
    #      무료 티어는 7일 조용하면 프로젝트를 일시정지한다(R4) → REST 엔드포인트를 직접 두드린다.
    dict(name="Supabase", kind="project", used_for="전략 저장소·VOC·사용 로그·이미지 버킷",
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
# 리스크 레지스터 R1~R12 (01_현황 11-22) — **어느 검사가 이걸 보고 있나**를 같이 적는다.
#   왜 여기 두나: 레지스터를 문서에만 두면 '감시하기로 했다'와 '감시한다'가 갈라진다.
#   L1 이 매일 이 표를 찍으므로, 감시가 없는 항목은 매일 눈에 보인다.
#   watch: 'l1:<검사>' | 'l2' | 'l3' | 'test' | 'none'(사람 판단·해결됨)
# ──────────────────────────────────────────────────────────────────────────────
RISKS = [
    dict(id="R1", what="토스 봇 노트북 의존", watch="l1:indirect",
         note="⏸ 보류(11-22) — 대가 = 거래일 10일 중 1일 전체 결행"),
    dict(id="R2", what="Streamlit 12h 재시작", watch="none", note="✅ 해결"),
    dict(id="R3", what="GitHub 60일 무활동 → 크론 중단", watch="l1:workflows",
         note="워크플로 state 와 마지막 성공 시각을 본다"),
    dict(id="R4", what="Supabase 7일 무활동 → 일시정지", watch="l1:supabase",
         note="프로젝트 REST 엔드포인트. 비밀값 SUPABASE_URL·SUPABASE_KEY 필요"),
    dict(id="R5", what="출처 차단(Yahoo·네이버)", watch="l1:probe", note="프로브 + L2 약관 diff"),
    dict(id="R6", what="Gemini·유튜브 한도", watch="l1:quota", note="429 를 자격 거부와 따로 센다"),
    dict(id="R7", what="텔레그램 전송 한도", watch="l1:probe", note="getMe + L2 FAQ diff"),
    dict(id="R8", what="공개 이메일", watch="none", note="✅ 코드에서 제거(이력엔 남음)"),
    dict(id="R9", what="투자 조언 규제", watch="l3", note="사람 판단 — 분기 재평가 항목"),
    dict(id="R10", what="무료 한도 소진", watch="l2", note="요금 문서 diff + L3 소진율"),
    dict(id="R11", what="틀린 숫자 발행", watch="test", note="known_answers · 리포트 감사"),
    dict(id="R12", what="자동 게시 제재", watch="l2",
         note="⚠️ Meta·X 정책 문서가 JS 렌더라 L2 가 못 읽는다 — 부분 감시"),
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


def _api(url, token=None):
    """JSON 을 받는다. (ok, 코드, dict|None)"""
    h = {"User-Agent": UA, "Accept": "application/vnd.github+json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=TIMEOUT) as r:
            return True, r.status, json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        return False, e.code, None
    except Exception as e:
        return False, type(e).__name__, None


def workflows():
    """R3 — **크론이 아직 도나.**

    GitHub 은 저장소가 60일 조용하면 예정된 워크플로를 끈다(`state='disabled_inactivity'`).
    그러면 수집·발행·봇이 전부 멈추는데 **실패 메일조차 오지 않는다** — 돌지 않으니까.
    '경보가 없다 = 괜찮다' 가 되는 가장 나쁜 고장이라 상태를 직접 읽는다.

    두 가지를 본다: ① 워크플로가 active 인가 ② schedule 트리거가 있는데 마지막 성공이
    MAX_WF_IDLE_DAYS 넘게 전인가. 반환 (rows, 문제 목록, 사유).
    """
    repo = os.environ.get("GITHUB_REPOSITORY") or "pcy604/stock-dashboard"
    tok = (os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or "").strip()
    ok, code, j = _api(f"https://api.github.com/repos/{repo}/actions/workflows?per_page=100", tok)
    if not ok or not j:
        return [], [], f"워크플로 목록을 못 받았다({code}) — 토큰이 없거나 한도"
    wfs = {w["id"]: w for w in j.get("workflows", []) if not str(w.get("path", "")).startswith(".github/workflows/_")}
    #   성공한 실행을 한 번에 받아 워크플로별 최신만 남긴다(워크플로마다 호출하면 30번이다).
    #   ⚠️ 이 창은 최근 200건뿐이다 — 매일 도는 잡이 많으면 **며칠치밖에 안 들어온다.**
    #      여기 없는 워크플로를 '성공 기록 없음'으로 처리하면 월 1회·분기 1회 잡이 전부
    #      오경보가 된다(11-22 실측: world-mcap 이 월 1회라 바로 걸렸다).
    #      → 창에 없는 것만 워크플로별로 한 번 더 묻는다(토큰이 있으면 시간당 5,000건이라 넉넉하다).
    last = {}
    for page in (1, 2):
        ok2, _, r2 = _api(f"https://api.github.com/repos/{repo}/actions/runs"
                          f"?status=success&per_page=100&page={page}", tok)
        if not ok2 or not r2:
            break
        for run in r2.get("workflow_runs", []):
            wid, t = run.get("workflow_id"), run.get("updated_at") or run.get("created_at")
            if wid and t and (wid not in last or t > last[wid]):
                last[wid] = t
    #   ⚠️ 연속 실패가 쌓이면 포기한다. 한도 소진(403)·장애면 워크플로 수만큼 타임아웃을
    #      먹어 L1 이 잡 제한시간을 넘긴다(11-23 실측: 테스트가 7초 → 8분이 됐다).
    miss = 0
    for wid in wfs:
        if wid in last:
            continue
        if miss >= 3:
            return [], [], f"워크플로별 조회가 연속 실패 — 한도 소진이나 장애로 보인다(토큰 {'있음' if tok else '없음'})"
        ok3, _, r3 = _api(f"https://api.github.com/repos/{repo}/actions/workflows/{wid}"
                          f"/runs?status=success&per_page=1", tok)
        runs = (r3 or {}).get("workflow_runs") or []
        if not ok3:
            miss += 1
            continue
        miss = 0
        if runs:
            last[wid] = runs[0].get("updated_at") or runs[0].get("created_at")

    today = dt.datetime.now(dt.timezone.utc)
    self_wf = (os.environ.get("GITHUB_WORKFLOW") or "").strip()
    rows, bad = [], []
    for wid, w in sorted(wfs.items(), key=lambda kv: kv[1]["name"]):
        state = w.get("state") or "?"
        t = last.get(wid)
        age = None if not t else (today - dt.datetime.fromisoformat(t.replace("Z", "+00:00"))).days
        f = os.path.join(BASE, w.get("path", ""))
        txt = open(f, encoding="utf-8", errors="replace").read() if os.path.exists(f) else ""
        sched = "schedule:" in txt
        tol = _cron_tolerance(txt)                 # 주기에 맞는 허용 일수(월 1회를 3일로 재면 안 된다)
        why = ""
        if state != "active":
            why = f"state={state}"                 # ← R3 직격(disabled_inactivity)
        elif sched and w["name"] != self_wf:
            #   성공 기록이 아예 없는데 파일이 방금 생겼으면 '새 워크플로'다 — 아직 돌 차례가 안 왔다.
            #   (이 가드가 없으면 platform-watch 가 스스로를 영원히 신고하고, 그 경보 때문에
            #    잡이 실패해 성공 기록이 안 생겨 **자기 봉인**에 걸린다.)
            if age is None:
                if _file_age_days(w.get("path", "")) > tol:
                    why = f"예정 워크플로인데 성공 기록이 한 번도 없다 (파일은 {_file_age_days(w.get('path', ''))}일 전)"
            elif age > tol:
                why = f"예정 워크플로인데 마지막 성공이 {age}일 전 (허용 {tol}일)"
        rows.append(dict(name=w["name"], state=state, sched=sched, last=t, age=age, tol=tol, why=why))
        if why:
            bad.append((w["name"], why))
    return rows, bad, ""


def _dow_days(dow):
    """cron 요일 필드가 주당 몇 번 터지나. '*'=7 · '1-5'=5 · '1,4'=2 · '6'=1."""
    if dow == "*":
        return 7
    n = 0
    for part in dow.split(","):
        part = part.split("/")[0]
        if "-" in part:
            try:
                a, b = (int(x) % 7 for x in part.split("-")[:2])
                n += (b - a) % 7 + 1
            except ValueError:
                n += 1
        else:
            n += 1
    return max(min(n, 7), 1)


def _cron_tolerance(yml_text):
    """cron 식에서 주기를 읽어 허용 일수를 정한다.

    ⚠️ 두 방향으로 다 틀릴 수 있다 — 11-22 에 둘 다 실측했다:
      · 월 1회 잡(world-mcap)을 매일 기준으로 재면 **매일 오경보**가 된다.
      · 평일 잡(daily-refresh, `* * 0-4`)을 '주 1회'로 뭉개면 **예정 실행 4회 연속 실패를
        17일간 못 본다** — 실제로 11-17부터 그 상태였고 산출물은 최신이라 아무도 몰랐다.
    그래서 요일 필드가 주당 몇 번 터지는지까지 센다.
    """
    crons = re.findall(r"cron:\s*['\"]([^'\"]+)['\"]", yml_text)
    tol = 0
    for c in crons:
        f = c.split()
        if len(f) < 5:
            continue
        dom, mon, dow = f[2], f[3], f[4]
        if mon != "*":
            t = 120                     # 분기·연 1회
        elif dom != "*":
            t = 45                      # 월 1회
        else:
            d = _dow_days(dow)
            #   주 5회 이상 = 사실상 매일 → 주말 + 한 번 건너뛰기까지만 봐 준다
            t = 4 if d >= 5 else (8 if d >= 2 else 17)
        tol = max(tol, t)
    return tol or MAX_WF_IDLE_DAYS


def _file_age_days(rel):
    """그 워크플로 파일이 저장소에 들어온 지 며칠 됐나(git 기준). 못 알면 크게 돌려
    '새 파일'로 봐 주지 않는다 — 모른다고 경보를 끄면 감시가 사라진다."""
    import subprocess
    try:
        out = subprocess.run(["git", "log", "--diff-filter=A", "--format=%cI", "-1", "--", rel],
                             cwd=BASE, capture_output=True, text=True, timeout=20)
        t = (out.stdout or "").strip().splitlines()
        if not t:
            return 10_000
        return (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(t[0])).days
    except Exception:
        return 10_000


def supabase():
    """R4 — Supabase 무료 티어는 7일 조용하면 프로젝트를 일시정지한다.

    supabase.com 홈페이지가 200 인 것은 **우리 프로젝트가 살아 있다는 뜻이 전혀 아니다.**
    프로젝트의 REST 엔드포인트를 직접 두드려야 한다. 비밀값이 Actions 에 없으면 그 사실을 말한다
    (조용히 통과시키면 '감시한다'고 적어 둔 것이 거짓이 된다)."""
    url = (os.environ.get("SUPABASE_URL") or "").strip().rstrip("/")
    key = (os.environ.get("SUPABASE_KEY") or "").strip()
    if not (url and key):
        return "unchecked", ("비밀값 SUPABASE_URL·SUPABASE_KEY 가 없다 — 차니가 GitHub Secrets 에 "
                             "넣어야 R4(7일 일시정지)를 실제로 감시할 수 있다")
    base = url
    for suf in ("/rest/v1", "/rest"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    #   2026-11-27 — '/rest/v1/'(스키마 목록)는 Supabase 새 키 체계에서 anon·publishable 키를 401 로 막는다.
    #   그래서 앱은 멀쩡히 쓰는데(usage_events 24h 98건) 감시만 11-23부터 매일 '자격 거부'였다.
    #   /auth/v1/health 는 유효한 키면 어떤 종류든 200, 틀린 키는 401, 일시정지는 5xx — R4 목적 그대로.
    req = urllib.request.Request(base + "/auth/v1/health", headers={"User-Agent": UA, "apikey": key,
                                                              "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return "ok", f"프로젝트 REST HTTP {r.status}"
    except urllib.error.HTTPError as e:
        #   401/403 = 키 문제, 404 = 경로, 5xx·타임아웃 = 일시정지 의심
        if e.code in (200, 400, 404):
            return "ok", f"프로젝트 REST HTTP {e.code} (응답함)"
        return ("authfail" if e.code in (401, 403) else "down"), f"프로젝트 REST HTTP {e.code}"
    except Exception as e:
        return "down", f"프로젝트 REST {type(e).__name__} — 일시정지 의심"


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
    if code == 429:
        #   R6 — 한도 소진. 자격 거부와 섞으면 대응이 갈린다(기다리기 vs 키 재발급)
        return "quota", f"HTTP 429 — 한도 소진({env})"
    if code in (401, 403):
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
        elif p["kind"] == "project":
            state, why = supabase()          # R4 — 홈페이지 200 은 우리 프로젝트와 무관하다
            if state == "unchecked":
                rows[name] = dict(kind=p["kind"], state="reachable", why=why, streak=0, checked=today,
                                  breaks=p["breaks"], fallback=p["fallback"])
                continue
        else:
            rows[name] = dict(kind=p["kind"], state="manual", why="프로브 수단 없음 — L3 에서 본다",
                              streak=0, checked=today)
            continue
        #   'authfail'(우리 자격이 끊겼다)과 'down'(서버가 안 뜬다)만 연속 실패로 센다.
        #   'reachable' 은 "비밀값이 없어 못 재 봤다" 이므로 실패로 세지 않는다 — 안 그러면
        #   비밀값이 없는 로컬 실행이 매번 빨간불이 되어 경보가 쓰레기가 된다.
        streak = int(was.get("streak") or 0) + 1 if state in ("down", "authfail", "quota") else 0
        rows[name] = dict(kind=p["kind"], state=state, why=why, streak=streak, checked=today,
                          breaks=p["breaks"], fallback=p["fallback"])
        #   자격 거부는 일시 장애가 아니다 — 1회로 바로 올린다. 서버 미응답만 streak 를 기다린다.
        #   자격 거부·한도 소진은 일시 장애가 아니다 — 1회로 바로 올린다.
        if state in ("authfail", "quota") or streak >= FAIL_STREAK:
            alarms.append((name, state, streak, why, p["breaks"], p["fallback"]))
    print("── 플랫폼 ──")
    for name, r in sorted(rows.items()):
        mark = {"ok": "OK  ", "reachable": "REACH", "authfail": "AUTH", "quota": "QUOTA",
                "down": "DOWN", "manual": "--  "}.get(r["state"], r["state"])
        extra = f"  연속실패 {r['streak']}회" if r["streak"] else ""
        print(f"  [{mark:<5s}] {name:<30s} {r['why']}{extra}")
    unchecked = [n for n, r in rows.items() if r["state"] in ("reachable", "manual")]
    if unchecked:
        print(f"  못 재 본 것 {len(unchecked)}개(비밀값 없음·프로브 없음): {', '.join(unchecked)}")

    # ── R3: 크론이 아직 도나 ──────────────────────────────────────────────
    wf_rows, wf_bad, wf_err = workflows()
    print("\n── 워크플로 (R3 · 60일 무활동이면 GitHub 이 끈다) ──")
    if wf_err:
        print(f"  {wf_err}")
    else:
        print(f"  {len(wf_rows)}개 중 active {sum(1 for w in wf_rows if w['state'] == 'active')} · "
              f"예정 {sum(1 for w in wf_rows if w['sched'])} · 문제 {len(wf_bad)}")
        for w in wf_rows:
            if w["why"]:
                print(f"  [BAD ] {w['name']:<28s} {w['why']}")
    for n_, why_ in wf_bad:
        alarms.append((f"워크플로 {n_}", "workflow", 0, why_,
                       "그 워크플로의 산출물 전부", "없음 — 직접 켜거나 수동 실행"))

    # ── 신선도 요약 — 01_현황 명세: L1 에 '일간+주간 신선도' 포함 ────────────
    print("\n── 산출물 신선도 (일간+주간) ──")
    fr = F.statuses()
    fr_bad = [r for r in fr if r["state"] != "ok"]
    print(f"  등록 {len(fr)}개 중 최신 {len(fr) - len(fr_bad)} · 문제 {len(fr_bad)}")
    for r in fr_bad:
        print(f"  [{r['state'].upper():<7s}] {r['path']:<44s} {r['note'] or ''}")
    #   ⚠️ 여기서는 경보로 올리지 않는다 — 각 워크플로의 check_freshness_ci 게이트가 이미
    #      그 잡을 실패시킨다. 두 곳에서 울리면 같은 고장에 메일이 두 번 온다. L1 은 '한 장에
    #      다 보이게' 하는 역할이고, 판정은 산출물을 만든 잡이 한다.

    _save(STATUS, dict(asof=today, fail_streak_alarm=FAIL_STREAK, platforms=rows,
                       workflows=dict(total=len(wf_rows), bad=[n_ for n_, _ in wf_bad], error=wf_err),
                       freshness=dict(total=len(fr), bad=[r["path"] for r in fr_bad]),
                       risks=risk_table(rows, wf_bad, wf_err)))

    print("\n── 리스크 레지스터 ──")
    for r in risk_table(rows, wf_bad, wf_err):
        print(f"  {r['id']:<4s} [{r['cover']:<9s}] {r['what']:<28s} {r['note']}")

    if not alarms:
        pend = [n for n, r in rows.items() if r["state"] == "down"]
        print("\n경보 없음" + (f" (1~{FAIL_STREAK - 1}회 실패 관찰 중: {', '.join(pend)})" if pend else ""))
        return 0
    print("\n경보:")
    for name, state, streak, why, breaks, fb in alarms:
        head = {"authfail": "자격 거부", "quota": "한도 소진",
                "workflow": "실행되지 않음"}.get(state, f"{streak}회 연속 실패")
        print(f"  ::error::{name} {head} ({why}) — 멈추는 것: {breaks} / 대체: {fb}")
    return 0 if warn_only else 1


def risk_table(rows, wf_bad, wf_err):
    """리스크 레지스터 R1~R12 에 '지금 그 감시가 실제로 돌았나'를 붙여 돌려준다.
    cover: 'ok' · 'alarm' · 'unchecked'(감시가 못 돌았다) · 'human'(사람 판단) · 'closed'(해결)."""
    def _state_of(name):
        return (rows.get(name) or {}).get("state")
    out = []
    for r in RISKS:
        w, cover, note = r["watch"], "ok", r["note"]
        if w == "none":
            cover = "closed"
        elif w == "l3":
            cover = "human"
        elif w == "test":
            cover = "ok"
        elif w == "l2":
            cover = "ok"
        elif w == "l1:workflows":
            cover = "unchecked" if wf_err else ("alarm" if wf_bad else "ok")
            if wf_err:
                note = wf_err
        elif w == "l1:supabase":
            s = _state_of("Supabase")
            cover = {"ok": "ok", "reachable": "unchecked"}.get(s, "alarm")
            if cover == "unchecked":
                note = (rows.get("Supabase") or {}).get("why") or note
        elif w == "l1:quota":
            cover = "alarm" if _state_of("Google Gemini") == "quota" else (
                "unchecked" if _state_of("Google Gemini") == "reachable" else "ok")
        elif w == "l1:indirect":
            cover = "alarm" if _state_of("토스증권") == "down" else "ok"
        elif w == "l1:probe":
            bad = [n for n in ("Yahoo Finance (yfinance)", "네이버 금융", "Telegram Bot API")
                   if _state_of(n) in ("down", "authfail", "quota")]
            cover = "alarm" if bad else "ok"
        out.append(dict(id=r["id"], what=r["what"], watch=w, cover=cover, note=note))
    return out


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
