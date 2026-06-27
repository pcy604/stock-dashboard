# ─────────────────────────────────────────
#  스크리너 설정 — 여기만 수정하면 됩니다
# ─────────────────────────────────────────

# 분석할 시장
USE_US_MARKET = True
USE_KR_MARKET = True

# 미국 종목 유니버스 ("TOP_N" / "SP500" / "NASDAQ100" / "CUSTOM")
US_UNIVERSE   = "TOP_N"      # TOP_N: 시총 상위 N개
US_TOP_N      = 2000         # 상위 몇 개 (TOP_N 모드)
US_CUSTOM_SYMBOLS = ["TSLA", "NVDA", "SATL", "IONQ", "MSTR", "SMR"]

# 한국 종목 유니버스 ("MARCAP" / "KOSPI200" / "KOSDAQ150" / "CUSTOM")
KR_UNIVERSE   = "MARCAP"             # MARCAP: 시총 기준 필터
KR_MIN_MARCAP = 300_000_000_000      # 3000억원
KR_CUSTOM_SYMBOLS = ["000660", "005930", "373220"]  # SK하이닉스, 삼성전자, LG엔솔

# 타임프레임
USE_WEEKLY  = True
USE_MONTHLY = True

# 신호 임계값
VOLUME_EXPLOSION_RATIO = 2.5
MA5_RIDE_MIN_DAYS = 5
CUP_MAX_DISTANCE_PCT = 12.0

# 실적 데이터 (미국 종목만)
USE_EARNINGS = True

# 텔레그램 (토큰은 코드에 두지 않고 data/.telegram_token 파일에서 읽음)
import os
def _secret(fname, fallback=""):
    _p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", fname)
    try:
        if os.path.exists(_p):
            return open(_p, encoding="utf-8").read().strip()
    except Exception:
        pass
    return os.environ.get(fname.lstrip(".").upper(), fallback)

TELEGRAM_ENABLED  = True
TELEGRAM_TOKEN    = _secret(".telegram_token")
TELEGRAM_CHAT_ID  = _secret(".telegram_chat", "5064831796")

# ── 구루 유튜브 요약 (guru_youtube.py) ──────────────────────────────
# Gemini API 키: data/.gemini_key 파일 또는 환경변수 GEMINI_KEY
GEMINI_KEY = _secret(".gemini_key")

# 구루 다이제스트 전송 대상. 채널(@username 또는 -100…숫자ID) 지정 시 거기로 브로드캐스트,
# 비우면 개인 챗(TELEGRAM_CHAT_ID)으로. data/.guru_chat 또는 환경변수 GURU_CHAT.
GURU_BROADCAST_CHAT = _secret(".guru_chat")

# 요약 출력 언어. 예: "한국어", "English", "日本語". 영상 원어와 무관하게 이 언어로 출력.
GURU_OUTPUT_LANG = "한국어"

# 분석할 채널. 'id'=채널ID(UC...) 또는 핸들(@xxx). 채널별 제목필터(선택):
#   include: 제목에 이 단어 중 하나라도 있어야 분석 (비우면 전체)
#   exclude: 제목에 이 단어가 있으면 제외
# 투자 무관 영상은 Gemini가 relevant=false로 판단해 다이제스트에서 자동 제외됨.
# ★ 순서 = 분석 우선순위. 알짜(체슬리·오종태) 먼저 → 무료 할당량 소진 전에 처리.
#   삼프로는 다작이라 마지막(남은 할당량으로). 자막없는 긴 라이브(영상분석=비쌈)가
#   할당량 부족(429)으로 밀리던 문제 대응.
GURU_CHANNELS = [
    {"name": "체슬리TV", "id": "UCXST0Hq6CAmG0dmo3jgrlEw"},          # 박세익 체슬리투자자문 (알짜 라이브)
    {"name": "오종태의투자병법", "id": "UCSVtOfGvhtz2QosSIM_3WoQ"},   # 오종태 이사
    # 유안타증권: 유동원 본부장 영상이 이름으로 제목이 안 달려 키워드 불가 →
    #   마케팅(광고·릴스·CF·홍보)만 exclude로 거르고 분석영상은 relevant 필터로 정리
    {"name": "유안타증권", "id": "UCGHG_gTZ780LicZmc-WUVPQ",
     "exclude": ["릴스", "쇼츠", "shorts", "예고", "CF", "광고", "보이스피싱",
                 "프렌즈", "원픽", "습관", "낭독", "월드컵", "이벤트", "안내"]},
    {"name": "삼프로TV", "id": "UChlv4GSd7OQl3js-jkLOnFA",          # 다작 → 마지막
     "exclude": ["쇼츠", "shorts", "예고", "다시보기", "라이브 다시"]},
]

# 출력
OUTPUT_CSV = True
OUTPUT_DIR = "results"
MIN_SIGNALS_TO_SHOW = 2
