# 📱 폰·공유용 배포 가이드 (Streamlit Cloud · Private)

매번 터미널 돌리는 거 끝. PC 꺼져 있어도 `https://내앱.streamlit.app` 주소로
폰에서 열리고, 링크만 주면 남도 본다. 코드는 Private이라 안 보인다.

준비는 끝났다(키 분리·requirements·테마 완료). 아래 순서만 따라오면 된다.

---

## 한눈에 — 구조

```
[집 PC 또는 GitHub Actions]  →  데이터 생성(스크리너·페이퍼)  →  results/*.json
                                                                     │ git push
[GitHub Private Repo]  ──────────────────────────────────────────────┤
                                                                     │ 자동 배포
[Streamlit Cloud]  →  https://내앱.streamlit.app  →  폰·공유          ┘
```

대시보드는 `results/*.json`을 읽기만 한다. 그 JSON을 누가 만들어 올리느냐의 문제.
- **1단계(지금)**: 집 PC에서 만들어 `git push` → 클라우드 자동 반영 (가장 단순)
- **2단계(나중)**: GitHub Actions가 매일 자동 생성·커밋 (PC 불필요) — `.github/workflows/` 참고

---

## STEP 1 — GitHub 계정 & 저장소 (형이 직접)

1. https://github.com 가입(이미 있으면 패스)
2. 우상단 **+ → New repository**
3. 이름 예: `stock-dashboard` · **Private 선택** · 나머지 기본값 → Create

> 계정 생성·로그인은 보안상 형이 직접 해야 한다. 비밀번호는 내가 대신 못 넣는다.

---

## STEP 2 — 코드 올리기 (터미널 한 번)

이 폴더에서:

```bash
cd C:\Users\lg\Desktop\stock_screener
git init
git add .
git commit -m "stock dashboard 초기 배포"
git branch -M main
git remote add origin https://github.com/<내아이디>/stock-dashboard.git
git push -u origin main
```

> `.gitignore`가 텔레그램 토큰·FRED 키·캐시를 자동 제외한다. **키는 안 올라간다.**
> `results/*.json`(대시보드가 읽는 데이터)은 올라간다 — 의도된 것.

---

## STEP 3 — Streamlit Cloud 연결

1. https://share.streamlit.io 접속 → **GitHub로 로그인** (Authorize)
2. **New app** → 방금 만든 `stock-dashboard` repo 선택
3. Main file path: `dashboard.py` → **Deploy**
4. 1~2분 뒤 `https://<앱이름>.streamlit.app` 주소 발급 → **이게 폰·공유 주소다**

---

## STEP 4 — 키 넣기 (Secrets)

배포된 앱 → 우하단 **⋮ → Settings → Secrets** 에 아래 붙여넣기:

```toml
FRED_KEY = "7c2403fc4ee8a087ed80776a259b9273"
```
(텔레그램·Finnhub도 쓰면 `.streamlit/secrets.toml.example` 형식대로 추가)

저장하면 앱이 자동 재시작. 매크로 탭 데이터가 채워지면 성공.

---

## STEP 5 — 이후 갱신 루틴

집 PC에서 데이터 새로 만들 때마다:
```bash
python weekly_run.py      # 스크리너 + 페이퍼 트레이딩 자동 기록
git add results/*.json data/portfolio.json
git commit -m "데이터 갱신"
git push
```
push하면 클라우드가 **자동으로** 새 데이터 반영. 폰에서 새로고침만 하면 끝.

> 이것도 귀찮아지면 → `.github/workflows/daily-refresh.yml` 활성화(2단계)로
> 매일 자동 생성·커밋·배포까지 무인화 가능.

---

## 자주 묻는 것

- **PC 꺼도 되나?** 됨. 대시보드 호스팅은 클라우드가 한다. PC는 데이터 만들 때만.
- **남이 내 코드 보나?** 못 본다(Private). 대시보드 화면만 본다.
- **무료인가?** Streamlit Community Cloud 무료. (앱 1개 + private repo 연결 무료)
- **느린가?** 무료 티어는 잠들었다 깨는 데 수십 초. 자주 보면 안 잔다.
- **데이터 생성도 클라우드서?** 무거운 백테스트는 비권장. 생성은 PC/Actions, 호스팅만 클라우드.
