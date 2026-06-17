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

# 출력
OUTPUT_CSV = True
OUTPUT_DIR = "results"
MIN_SIGNALS_TO_SHOW = 2
