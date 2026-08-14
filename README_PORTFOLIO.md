# 💼 보유종목 영구 저장 켜기 (1회 설정, 3분)

## 왜 필요한가

Streamlit Cloud 컨테이너의 디스크는 **휘발성**이다. 웹에서 보유종목을 추가하면
"저장됐습니다"가 뜨지만 서버가 재시작되면 사라진다. 포트폴리오를
**트랙레코드(자기 증명 지표)** 로 쓰려면 기록이 남아야 한다.

이 저장소는 이미 `results/*.json` 을 깃에 커밋해 데이터를 유지하고 있다.
보유종목도 같은 방식 — **깃 저장소를 DB로** 쓴다.

## 설정 (형이 직접 해야 하는 부분)

> 토큰은 자격증명이라 제가 대신 만들 수 없습니다. 아래 3단계는 직접 해주세요.

### 1) GitHub 토큰 발급

1. https://github.com/settings/personal-access-tokens/new (Fine-grained)
2. **Repository access** → Only select repositories → `pcy604/stock-dashboard`
3. **Permissions** → Repository permissions → **Contents: Read and write**
4. Expiration은 원하는 만큼 (만료되면 다시 발급해 교체하면 됨)
5. Generate token → 값 복사 (이 화면을 벗어나면 다시 못 봄)

### 2) Streamlit Secrets 에 등록

Streamlit Cloud → 앱 → **Settings → Secrets** 에 아래를 붙여넣고 Save:

```toml
GITHUB_TOKEN = "여기에_복사한_토큰"
GITHUB_REPO  = "pcy604/stock-dashboard"
```

### 3) 확인

앱을 새로고침하고 **💼 포트폴리오 → ➕ 종목 추가** 를 열면 상단 문구가 바뀐다.

| 상태 | 문구 |
|---|---|
| 설정 전 | 🔴 임시 저장 — 서버 재시작 시 사라짐 |
| 설정 후 | 🟢 영구 저장 켜짐 — 저장 위치 `pcy604/stock-dashboard · data/portfolio.json` |

종목을 하나 추가하면 저장소에 `portfolio: … 추가 YYYY-MM-DD HH:MM` 커밋이 생긴다.

## 동작 방식

- **읽기**: 토큰이 있으면 저장소를 진실로 본다 → 집 PC에서 넣은 종목이 폰에서도 보인다
- **쓰기**: 로컬에 먼저 쓰고(즉시 반영) 저장소에 커밋한다
- **토큰이 없거나 실패하면**: 로컬에만 저장하고 **그 사실을 화면에 표시한다**
  (조용히 실패해서 "저장된 줄 알았는데 없어지는" 상황을 만들지 않는다)

## 주의

- 토큰은 `contents:write` 만 주면 된다. 그 이상 권한은 필요 없다.
- 이 저장소가 **Public 이면 보유종목이 공개된다.** 비공개로 두거나, 공개 저장소라면
  이 기능을 켜지 말 것.
- 동시에 두 기기에서 저장하면 나중 것이 409로 거부된다(덮어쓰기 방지) —
  새로고침 후 다시 시도하라는 안내가 뜬다.
