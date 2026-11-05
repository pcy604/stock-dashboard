# 프로젝트 스킬 (2026-11-06 도입)

이 저장소를 연 Claude Code 세션은 아래 스킬을 자동으로 읽고, 각 SKILL.md 의 description 에 맞는 상황에서 스스로 쓴다.
외부 원본을 그대로 가져왔다 — 고칠 때는 원본을 다시 받아 덮어쓰고 여기 커밋을 갱신한다(직접 수정 금지, 드리프트 방지).
stock-dashboard 와 buza-bot 에 같은 사본이 있다.

| 스킬 | 언제 쓰나 (우리 프로젝트) | 원본 · 라이선스 |
|---|---|---|
| verification-before-completion | "완료·고쳤다·통과" 라고 말하기 전 — 실화면·전 경우 실측 (예: 표 정렬은 모든 열 × 오름·내림) | obra/superpowers@22f0b46 · MIT |
| systematic-debugging | 버그·실패·이상 동작 — 추정 말고 로그로 원인 확정 후 수정 | 〃 |
| writing-plans | 여러 단계 작업을 코드 손대기 전에 계획 | 〃 |
| webapp-testing | 대시보드 헤드리스 실측(Playwright) | anthropics/skills@ca45fc4 · Apache-2.0 |
| impeccable | 탭 UI 점검·다듬기(audit·critique·polish). **launcher 스크립트는 뺐다**(외부 바이너리 내려받기) → 스킬 자체의 'Launcher unavailable' 경로로 동작 | pbakaus/impeccable@04a0b67 · Apache-2.0 |
| earnings-preview · earnings-analysis · thesis-tracker | 실적 발표 전후 리포트 · 실전 보유 종목 투자 논리 추적 (buza-bot 심층 리포트 구조 참고) | anthropics/financial-services-plugins@6056506 · Apache-2.0 |
| comps-analysis · dcf-model | 종목분석 동종 비교·밸류에이션 | 〃 |
| onboarding · pricing · launch | 봇·대시보드 사용자 확대·수익화 단계 (evals 폴더 제외) | coreyhaines31/marketingskills@88c79f6 · MIT |

주의: 금융 스킬은 기관 리서치용 형식(엑셀·8~12쪽)이 기본이다. 공개 화면·봇에는 '사실 전달만'(유사투자자문 규제) 원칙이 우선한다.
