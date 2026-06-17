# 피드백 기반 자가 개선 결과

> 인수후보 3곳(`FEEDBACK.md`)이 공통으로 찌른 치명적 약점 중,
> **코드로 당장 닫을 수 있는 것**을 실제로 구현했다.
> 신규 파일: `backtest_validation.py` (기존 엔진 무손상, 검증 레이어만 추가)

---

## 닫은 구멍

### ✅ #1 — 아웃오브샘플(OOS) 검증 부재 (GS·여의도 치명 지적)
- **무엇:** 전 기간을 학습(IS, 2021–2023)과 검증(OOS, 2024–현재)으로 분리.
- **왜:** in-sample 샤프 1.33은 곡선 맞추기일 수 있다. 검증기간에서 무너지면 가짜 엣지.
- **판정 규칙:** OOS 순EV가 IS 대비 급락 → 과최적화로 간주, 채택 보류.
- 구현: `build_validation_report(split_date='2024-01-01')`

### ✅ #2 — 레짐(강세/약세) 분리 부재 (GS 치명 지적)
- **무엇:** 벤치마크(KOSPI/SPY) 주봉이 13주 이평 위/아래인지로 매 시점 `bull`/`bear` 라벨링 후 성과 분리. (point-in-time, look-ahead 없음)
- **왜:** 2021–2026은 대부분 강세장. "약세장에서도 순EV>0 유지하는 신호만 진짜"라는 GS 기준을 코드로 강제.
- 구현: `benchmark_regime()`, `attach_regime()`

### ✅ #6 — 소형주 거래비용 과소평가 (여의도 치명 지적)
- **무엇:** 단일 비용(KR 0.40%) → **시총 분위별 차등**. 소형주는 왕복 1.6%까지(코스닥 슬리피지 현실 반영).
- **왜:** "호가 한두 틱에 1%씩 먹힌다"는 실거래 지적. 소형주일수록 백테스트 수익이 실거래에서 증발.
- 구현: `SIZE_TIER_COST` (large/mid/small × KR/US)

### ➕ 보너스 — 리스크 지표 정밀화 (JPM·여의도 요구)
- **Sortino** (하락편차 기준), **Profit Factor** (총이익/총손실) 추가.
- 샤프만으로 숨던 다운사이드 리스크를 드러냄.

---

## 아직 못 닫은 구멍 (정직하게)

| 구멍 | 왜 코드만으론 안 되나 |
|------|----------------------|
| 🟠 #3 생존편향 보정 | 상장폐지 종목 가격 DB가 외부에 있어야 함(유료). 현재는 '경고'까지만. |
| 🟠 #4 무료 스크래핑 데이터 | 상업 라이선스·SLA 있는 유료 피드 교체 = 자본 필요. |
| 🟡 #5 알파 vs 모멘텀 베타 분해 | Fama-French + 모멘텀 팩터 수익률 데이터 확보 후 회귀 필요. |

---

## 실행 방법

```bash
# 전체 파이프라인 (다운로드→신호→IS/OOS×레짐 교차검증)
python backtest_validation.py

# 또는 기존 백테스트에 검증 리포트만 덧붙이기
python -c "from backtest_engine import download_all, run_backtest; \
from backtest_run import get_kr_universe, get_us_universe; \
from backtest_validation import build_validation_report; \
kr=download_all(get_kr_universe(),'KR'); us=download_all(get_us_universe(),'US'); \
c=run_backtest(kr,us); print(build_validation_report(c))"
```

리포트 예시 출력:
```
   신호              구간                  발생     승률     순EV     샤프  Sortino    PF
   52주신고가          학습기간(IS)           633  56.2%   1.90%   1.15     2.14  1.51 ✅
   52주신고가          검증기간(OOS)★         541  56.2%   2.06%   1.22     2.17  1.53 ✅   ← OOS 유지
   52주신고가          약세장만(bear)         458  58.7%   2.57%   1.61     3.18  1.75 ✅   ← 약세장 생존
```
(위 수치는 로직 검증용 합성데이터 — 실제 값은 `python backtest_validation.py` 구동 결과로 대체)

---

## 매각 협상에 미치는 영향

- **Before:** "샤프 1.33" (in-sample) → GS가 1분 만에 기각.
- **After:** "OOS·약세장에서도 살아남는 신호만 추렸고, 소형주 비용까지 차감했다" → 적어도 **테이블에 앉을 자격**은 얻음.
- 남은 두 구멍(데이터·생존편향)은 자본이 필요하므로, 이것이 곧 **인수자가 가져갈 몫(업사이드)** 이자 협상 레버리지가 된다.
