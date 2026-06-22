# 🎙️ 구루 인사이트 셋업 가이드

체슬라TV·삼프로TV 영상을 매일 자동 요약 → 텔레그램 전송 + 대시보드 "🎙️ 구루 인사이트" 탭 표시.

## 구조
```
RSS(신규영상 감지) → 자막 추출 → Gemini 분석 → results/guru_insights.json
                                          ├→ 텔레그램 다이제스트
                                          └→ Streamlit 대시보드 탭
자막 실패 시 → Gemini가 영상 URL을 직접 분석(음성)으로 자동 폴백
```

## 1. Gemini API 키 발급 (무료)
1. https://aistudio.google.com/apikey 접속 → "Create API key"
2. 발급된 키 복사

## 2. 로컬 설정
```bash
# 키 저장 (커밋 안 됨 — .gitignore 등록 완료)
echo "발급받은키" > data/.gemini_key

pip install -r requirements.txt
```

## 3. 체슬라TV 채널 확정 ⚠️
`config.py` 의 `GURU_CHANNELS` 에서 체슬라TV는 placeholder(`@cheslatv`) 상태.
실제 채널 페이지를 열고 **채널 URL** 을 확인해서 교체:
- `youtube.com/channel/UCxxxx...` 형태면 → `"id": "UCxxxx..."`
- `youtube.com/@핸들` 형태면 → `"id": "@핸들"` (러너에서 자동 해석)
- 가장 확실한 건 UC id. 채널 페이지 우클릭 → 소스보기 → `"channelId":"UC...` 검색.

## 4. 로컬 테스트
```bash
python guru_youtube.py
```
→ `results/guru_insights.json` 생성 + 텔레그램 도착 확인.

## 5. GitHub Actions 자동화 (PC 꺼져도 동작)
repo → Settings → Secrets and variables → Actions → New secret:
- `GEMINI_API_KEY` = 발급받은 키  **(필수)**
- `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID` = 이미 등록돼 있으면 생략

워크플로우 `.github/workflows/guru-digest.yml` 가 매일 **07:00 KST** 자동 실행.
Actions 탭 → guru-digest → "Run workflow" 로 수동 테스트도 가능.

## 조정 포인트 (guru_youtube.py 상단)
| 변수 | 의미 | 기본값 |
|---|---|---|
| `LOOKBACK_HOURS` | 최근 N시간 내 영상만 | 28 |
| `MAX_PER_CHANNEL` | 채널당 1회 최대 분석 수 | 5 |
| `TITLE_INCLUDE` | 제목에 이 단어 포함된 것만 (비우면 전체) | [] |
| `TITLE_EXCLUDE` | 제목에 이 단어 들면 제외 | 쇼츠/예고/다시보기 |
| `GEMINI_MODEL` | 분석 모델 | gemini-2.5-flash |

> 삼프로TV는 하루 영상이 매우 많음. 특정 코너만 받고 싶으면 `TITLE_INCLUDE`에
> 예: `['모닝브리핑', '월스트리트']` 처럼 키워드를 넣어 필터링 권장.

## 비용/주의
- **자막 경로**가 기본 — 2시간 영상도 텍스트라 토큰값 저렴.
- 자막이 막히거나 없으면 **영상 직접 분석**으로 폴백. 무료 티어는 긴 영상에 제한이
  있을 수 있으니, 다작 채널은 `TITLE_INCLUDE`로 핵심 코너만 거르는 걸 추천.
- GitHub Actions 클라우드 IP는 유튜브 자막이 막히는 경우가 있음 → 그때 영상폴백 작동.
