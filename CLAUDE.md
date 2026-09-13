# stock_screener 작업 규칙

## 배포 — 커밋은 배포가 아니다

**Streamlit Cloud 는 `origin/main` 에서 배포된다. 푸시하지 않으면 화면은 계속 옛날 코드다.**
로컬만 고쳐놓고 "반영했다"고 말한 사고가 반복됐다(2026-08-25 · 커밋 7개 미푸시).

- `.git/hooks/post-commit` 이 커밋 후 **자동으로 `git push origin main`** 한다(2026-09-13 설치).
- hook 은 git 추적 대상이 아니다 — **clone 하거나 다른 PC 에서 작업하면 사라진다.** 그때는 수동 푸시.
- 푸시 실패 시 hook 이 경고를 찍는다. 무시하지 말 것(대개 CI 자동커밋이 앞선 경우 →
  `git pull --rebase && git push`).
- 화면 바뀐 걸 보고해야 할 때는 **`git log origin/main..HEAD` 가 비었는지 먼저 확인**한다.

## 현행 규칙

- 주도주 진입 = **이익 가속**(`leaders_accel.py`). **L/S · 규칙⑥ · A/B/R6 는 전부 폐기**됐다.
  화면·문서에 그 이름이 보이면 잔재다.
- 청산: 이긴 종목에 트레일을 걸면 폭에 상관없이 손해. 단 **최소보유 바닥을 깔면 구제된다.**
- 폐기된 모듈에 의존하지 말 것 — `leaders_accel_exit.py` 는 대청소(42c4bbb)로 import 가 깨져 있다.

## 개발 환경

- 진짜 python: `C:\Users\lg\AppData\Local\Python\bin\python.exe` (`python`/`py` 는 스텁, exit 49).
- 커밋 안 한 로컬 변경은 daily-refresh CI 자동커밋에 덮여 사라진다.

## 검증

- 대시보드는 **`streamlit.testing.v1.AppTest` 헤드리스 실행**으로 확인한다.
  ⚠️ `guard()` 가 예외를 삼키므로 **`at.exception` 은 0으로 보인다.** 반드시
  **`at.error` 와 백틱으로 시작하는 caption**(삼켜진 예외 텍스트)을 같이 볼 것.
- plotly 레이아웃을 바꾸면 `fig.write_image(...)` (kaleido) 로 PNG 를 만들어 눈으로 본다.
  임베디드 브라우저는 이 앱을 렌더하지 못한다.
- plotly x 축에 **Timestamp 리스트를 넘기지 말 것** — DatetimeIndex 로 넘긴다(직렬화가 깨진다).

## 데이터 원칙

없는 데이터를 있는 척하지 않는다. 추정 불가 항목은 `-`, 소스 한계는 화면 캡션에 명시.
성적이 나쁜 신호를 화면에서 지우지 않는다.
