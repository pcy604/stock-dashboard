# -*- coding: utf-8 -*-
"""
leaders_ab.py — 주도주 규칙 L(대형) · S(소형) 발행

왜 규칙⑥을 대체하는가 (2026-08-18):
  시총 데이터를 고치고(us_marketcap.csv 27개월 방치 → SEC 공시 주식수) 유니버스를
  재구축한 뒤 규칙⑥을 다시 재니 **2022년 이후 CAGR 3.8%** 였다(SPY 13.2%).
  앞 구간 33.8% 로 좋아 보였던 건 look-ahead 오염과 국면 운이었다.

  규칙⑥이 놓치는 것이 구조적이었다. `시총 $2B+ & OPM>0` 조건은
  NVDA(2022-10) · TSLA(2019-08) · CVNA(2023-05) · AXTI(2025-05) 의 **대시세 출발
  시점을 전부 탈락**시킨다. 그 시점 시총은 $0.07B~$282B 로 4천 배 차이였고
  8종목 중 7종목이 그때 재무가 최악이었다(NVDA OPM 38.9%→7.4%, AXTI −53.1%).
  하나의 필터로 둘 다 잡을 수 없어 **대형/소형으로 쪼갠다.**

무엇이 실제로 작동했나 (637,269 주차-종목, 기저 +100%/1년 = 5.17%):
    주간 +20% 급등 & 거래량 **전주 대비** < 1.5배   → 27.4% (5.3배)  ← 최강
    52주 고점대비 −60~−90%                        → 19.5% (3.8배)
    RS13 > 1.5 (규칙⑥)                          → 16.1% (3.1배)
  ⚠️ 거래량은 20주 평균이 아니라 **전주 대비**로 봐야 보인다. 20주 평균으로 보면
     대시세 출발점의 거래량이 0.86배(조용함)로 나와 아무 신호도 안 잡힌다.
     그리고 방향이 직관과 반대다 — 거래량이 **터질 때가 아니라 안 터질 때**가 좋다.
     같은 급등에서 거래량 3배+ 는 13.4%, 거래량 감소는 30.4% 였다.

재무 조건을 왜 대형에만 거는가:
  흑자전환·OPM급개선은 **평균**은 크게 올리지만 중앙값·승률은 기저 이하다(꼬리형).
  영업익 8분기 신고점은 반대로 **중앙값·승률**이 전 구간 꾸준히 우위다(안정형).
  대형은 안정형 축(8Q신고점 or OPM개선)을 얹어 승률을 사고, 소형은 재무 조건 없이
  꼬리만 산다 — 소형 대시세는 출발 시점에 전부 적자였기 때문이다.

측정 (2018-06~2026-08, 편도 0.1%, 진입가 = 신호 주차 종가):
  ⚠️ 2026-08-22 L 에 눌림목 4분할 진입을 채택하면서 L 성적이 바뀌었다(아래는 반영분).
    L 단독 6칸  : 앞 14.7% / 뒤 22.1% / 전체 18.3%   MDD −27.2%   ← 분할 진입
    S 단독 10칸 : 앞 33.6% / 뒤 20.7% / 전체 23.3%   MDD −49.4%   ← 일괄
    L+S 50:50  : 앞 25.0% / 뒤 21.4% / **전체 21.0%**  MDD −35.3%
    SPY        : 앞 18.3% / 뒤 13.2% /     15.1%       MDD −31.8%
  참고 — L 을 일괄로 두면 전체 24.9% / MDD −39.8% 다. 분할은 CAGR 6.6%p 를 내고
  MDD 12.6%p 를 사는 **보험**이지 수익 규칙이 아니다. 아래 '분할 진입' 절 참조.
  진입을 1주 늦춰도 18.4%, 2주 늦춰도 15.1% — 금요일 종가 체결에만 성립하는
  미시구조 착시가 아니다.

⚠️ 남은 한계 (화면에도 같이 띄운다)
  · 생존 편향 — 유니버스가 '오늘 상장된 종목'이라 상장폐지 회사가 없다. 낙관적이다.
  · L 은 평균 3.5종만 보유한다. 6칸→7칸에서 뒤 구간이 28.4%→11.0% 로 꺾인다.
    한두 종목이 결과를 좌우한다는 뜻이고, 실전 재현성이 낮을 수 있다.
  · MDD −38% 는 SPY(−31.8%)보다 크다.
  · **NVDA·TSLA 를 한 주도 못 잡는다. 고치려고 재봤고, 못 고쳤다.**
    원인은 거래량이 아니라 급등 문턱이다. 시총이 크면 주간 +20% 자체가 안 나온다
    ($50B+ 구간에서 +15%↑ 주는 표본 60개 미만). 기저율만 보면 문턱을 시총별로
    낮추는 게 맞아 보인다 — +100%/1년 확률의 기저 대비 배수가 그래야 유지된다:
        $2~10B  · +20%↑ & vol<1.5 → 23.5% (기저 4.08% 의 5.8배)
        $10~50B · +15%↑ & vol<1.5 → 12.2% (기저 2.40% 의 5.1배)
        $50B+   · +10%↑ & vol<1.5 →  8.9% (기저 1.92% 의 4.6배)
    이 계단 문턱을 쓰면 NVDA 23 주차 · TSLA 36 주차가 잡힌다(재무조건까지 12·13).
    그런데 백테스트하면 전부 나빠진다 (전체 CAGR / MDD):
        현행 20% & vol<1.5      25.4% / −39.8%   ← 최고
        vol<2.0 로 완화         23.8% / −46.0%
        거래량 조건 제거        13.3% / −48.4%
        계단 20/15/10           16.2% / −52.2%
        계단 20/15/10 & vol<2.0 21.5% / −36.6%
    확률 배수는 포트폴리오 수익이 아니다. 대형주는 (a) +100% 가도 상방이 소형보다
    작고 (b) 후보가 2~3배 늘어 6칸을 대박 아닌 종목이 먼저 차지한다.
    대형 전용 별도 규칙도 안 된다. $50B+ · +10% · 3칸 이 전체 27.5% 로 튀지만
    시총컷 3 × 문턱 3 × 칸수 3 격자에서 이웃 셀이 전부 8~20% 인 고립 봉우리이고,
    평균 보유가 1.8~2.7 종이다. 한두 종목 운을 규칙이라 부르는 것에 가깝다.
    → 미감지는 버그가 아니라 받아들인 트레이드오프다. 뒤집으려면 반증이 필요하다.
      (반증 조건: 대형 대시세 표본이 NVDA·TSLA·AVGO 밖으로 늘어나거나,
       $50B+ · +10% 가 격자에서 이웃 셀과 함께 올라오면 다시 연다.)
  · 시총(marcap) 시계열은 0.66% 가 오염돼 있다 — 액면분할 주차에 내재주식수가
    튄다(NVDA 는 $78B~$26,970B 로 기록된다). 경계가 $2B 하나인 현행 L/S 는
    영향이 작지만, 계단 문턱처럼 경계를 늘리면 이 오염이 그대로 커진다.

청산·비중·랭킹은 왜 이 값인가 (2026-08-22 측정, 상세는 HISTORY.md 5기)
  · 트레일 −30% 는 격자 최고가 아니다. −32%(30.8%)·−35%(30.5%)가 더 높다.
    그런데 진입을 1주만 늦추면 −30%(24.5%)가 −35%(23.4%)를 이긴다. 뒤집히는
    우위는 안 쓴다.
  · 청산 방식 자체는 트레일링이 맞다. MA20 이탈 7.1%(MDD −76.2%), 26주 상한
    11.0%, 52주 상한 11.3%, 무청산 −0.5%(MDD −87.2%). 대박은 1년 넘게 들고
    가야 하고, 그렇다고 안 팔면 죽는다.
  · 피라미딩은 넣지 않는다. 1/2+1/2, 1/3×3 전부 CAGR 을 깎는다(20.5~22.3%).
    MDD 는 −29~−35% 로 좋아진다 — 위험을 줄이고 싶으면 그때 쓸 카드다.
  · 슬롯은 그 주 상승률 내림차순으로 채운다. PSR 낮은 순이 35.0% 로 더 높고
    진입 지연 검증까지 통과했지만, 후보가 6칸을 넘긴 16주를 열어보니 우위가
    2020-03-23·2020-04-06 두 주에서 전부 나왔다. 11주 중 7주 승 = 동전던지기다.
  · RS13 높은 순은 11.7%(MDD −67.5%). 규칙⑥ 폐기와 같은 방향의 세 번째 증거다.

신호 반복 횟수는 왜 안 넣었나 (2026-08-22)
  · "N번 이상 신호 난 종목만" 은 L 과 S 가 정반대다.
        L 6칸  현행 25.4 → 2번째+ 9.7 → 3번째+ −3.7    (기저율도 3·4번째가 최악)
        S 7칸  현행 27.8 → 2번째+ 27.4 → 3번째+ 37.3   (임계 4회에선 27.0)
    대형주에서 신호 반복은 나쁜 징후이고, 소형에선 좋은 징후로 보인다.
  · S 3번째+ 는 지연·플라시보·슬롯 대조를 전부 통과한 유일한 후보였다.
    플라시보(같은 개수를 무작위로 남기기 20회) 중앙값 17.0% 대비 37.3%, p=0.00.
    2020 을 빼도 28.5%(현행 −5.1%). '덜 사서 좋아진 것'이 아니다.
  · **그럼에도 안 넣는다.** 임계값 격자가 1:27.8 2:27.4 3:37.3 4:27.0 5:35.3
    6:25.0 으로 지그재그다. 반복에 정보가 있다는 것까지는 맞지만 '3회'는 우연이고,
    반복 효과 전체는 현행과 겹친다. 그리고 3번째+ 는 생존 편향의 증폭기다 —
    "3번 신호 낼 때까지 살아남은 종목"만 고르는데 유니버스에 죽은 회사가 없다.
  · 다시 열 조건: 임계 2~5회가 함께 올라오거나, 상장폐지 종목을 유니버스에
    넣은 뒤에도 3번째+ 우위가 남으면.

$2B 경계는 왜 이 값인가 (2026-08-22) — 이름이 오해를 부른다
  · $2B 는 미국 기준 스몰캡이다. "대형 주도주"라는 이름과 달리 L 은 대형주
    규칙이 아니다. 경계를 올리면 죽는다: $5B 18.3 · $10B 19.8 · $50B 1.1%
    (후보 27건). 대형주는 주간 +20% 자체가 안 나오기 때문이다.
  · 내리는 것도 안 된다. $0.5B 는 32.6% 로 최고지만 1주 지연에 23.4% 로
    반토막 난다(미시구조 착시). $2B 만 정시 25.4 / 1주 24.5 로 안정적이다.
  · **S 쪽 상한은 사실상 아무 일도 안 한다.** $1B~$50B 전부 22~23%, 상한을
    없애도 21.7% 다. 신호를 상승률 순으로 담는데 소형주가 상위를 독식한다.
  · 그러니 $2B 의 진짜 역할은 시총 구분이 아니라 **재무조건을 걸 것인가의
    분기점**이다. 상한 없이 재무조건을 걸면 20.9% 로 떨어진다 — 소형 대시세는
    출발 시점에 전부 적자였다.
  · "왜 $2B 냐"에 답하려면 (2026-08-22 측정):
      재무조건은 **개별 신호의 중앙값은 모든 시총에서 깎는다**
      ($1~2B −20.7%p · $2~5B −34.2%p · $10~30B −19.3%p).
      그런데 포트폴리오는 반대다 — $2B+ 재무O 25.4% vs 재무X 16.0%,
      뒤 구간(2022~)은 28.4% vs 8.8%. $5B+ 는 32.2% vs −8.7% 다.
      재무 없는 급등은 분산이 커서 −30% 트레일에 자주 걸리고, **2022년 이후
      전멸한다**(유동성 장세 전용이었다).
      → $2B 는 "재무 실적을 요구할 수 있는 가장 낮은 시총"이다. 그 아래는
        전부 적자라 요구할 수 없고, 그 위는 요구할 대상이 부족하다($5B+ 후보
        229건 → 6칸 중 4.5칸).
      → 다만 **'정확히 2'에는 근거가 없다.** $1.5B 나 $2.5B 가 아니어야 할
        이유는 없고 경계 근처는 완만하다. 답할 수 있는 건 "왜 0.5 도 10 도
        아닌가"까지다.

시총 배가 속도는 왜 안 쓰나 (2026-08-22)
  사다리 $1B→2→4→8→16→32→64B 에서 직전 배가 소요주로 다음을 예측해봤다.
  · 속도 지속성 상관 +0.10~0.17 — 사실상 없다.
  · 다음 단계 도달률이 단조롭지 않다(역 U자): 10주 25.3% · 44주 27.2% ·
    100주 31.7% · 186주 15.6%.
  · **급하게 배가한 종목이 1년 뒤 가장 나쁘다**(중앙값 −10.3%, Q3 는 +9.6%).
  · 급등 신호와 결합하면 느린 쪽이 이긴다 — L 빠름 −37.7% vs 느림 +16.3%,
    S 빠름 +1.7% vs 느림 +53.7%. L·S 일관.
  · 그런데 백테스트는 전부 현행 이하다. L 17.1 / 24.9 / 22.7% (현행 25.4),
    S 13.0 / 17.0 / 20.3% (현행 23.5). 기저율이 포트폴리오로 안 이어진
    일곱 번째 사례다.

'사상 첫 시총 XX 돌파'를 왜 안 쓰나 (2026-08-22)
  기저 +100% 7.1% 대비 첫 $1B 3.7% · $10B 2.5% · $100B 2.9% — 전부 기저의
  0.35~0.56배다. 시총 돌파의 98.8% 는 급등이 아니라 야금야금 넘는 것이라서다.
  백테스트 −1.0~13.0%, L0 와 합치면 4.8% 로 망친다. 52주 신고가 계열의
  다섯 번째 기각이고 리프트(0.4~0.7)까지 일관된다. 덧붙여 데이터가 2018-06
  부터라 "사상 첫"이 실제로는 "2018-06 이후 첫"이다.

분할 진입 — 왜 넣었나, 그리고 무엇을 포기했나 (2026-08-22 채택)
  L 에만 눌림목 4분할을 쓴다. 신호 주에 슬롯의 1/4 만 사고, 2회차부터는
  ① 진입 후 고점 대비 −5~10% 눌리고 ② 직전 매수가를 넘고 ③ 20주선 위일 때만
  1/4 씩 추가한다. 못 채운 몫은 현금으로 남고, **그 현금이 MDD 를 낮추는 실체다**
  (현재 가상 장부: L 6/6칸인데 현금 36.8%).

  측정 (정시 / 1주지연 / 2주지연):
    일괄          24.9% / 24.9% / 19.7%   MDD −39.8 / −34.3 / −40.7
    눌림목 4분할   18.3% / 18.4% / 15.1%   MDD −27.2 / −31.9 / −29.4   ← 채택
    추세 4분할    21.2% / 19.7% / 16.1%   MDD −29.0 / −32.9 / −31.2
  · CAGR 은 일괄이 세 시점 전부 이긴다. MDD 는 분할이 세 시점 전부 이긴다.
  · 회복력(CAGR/MDD)은 정시엔 추세4분할 0.73 최고인데 1주 지연에 일괄 0.72 로
    뒤집혀 결론이 안 난다. 즉 **어느 축을 볼 것인가가 선택이지 데이터가 정해주지 않는다.**
  · 2026-06 손실이 '한 번에 실은 것'에서 왔으므로 MDD 축을 택했다.
  · **S 에는 안 쓴다.** 분할이 CAGR 만 깎고(23.3% → 12.4~20.9%) MDD 는 그대로였다
    (−49.4% → −50.1%). 소형 대시세는 초기 폭발을 놓치면 끝이라서다.
  · 이전에 잰 '피라미딩'(2026-08-22 오전)은 **추세형**(+25%·+50% 오를 때 추가)이었다.
    설계도(260731)의 눌림목형은 그때 안 재봤다 — 다시 재서 채택한 것이다.

⚠️ 워크포워드 — 위 성적은 전부 인샘플이다 (2026-08-22)
  주차별 코호트 표(같은 주 걸린 전 종목의 이후 1·4·13주)는 **공시이지 검증이 아니다.**
  파라미터를 고른 것이 바로 그 8년이라, 같은 데이터로 채점하면 잘 나오는 게 당연하다.
  증거: 2026-08-22 에 기각한 개선안 7건이 전부 이 코호트 검사를 통과했다.

  TRAIN 3년 → TEST 1년 워크포워드 (파라미터를 TRAIN 에서 새로 고름):
    분할          뽑힌 파라미터        TRAIN    TEST    현행고정   SPY
    18-06~21-05  +20% vol<1.2 tr25   38.2%  −26.9%   −13.2%  −2.0%
    19-06~22-05  +20% vol<1.2 tr25   34.4%   −6.8%   −29.7%  11.9%
    20-06~23-05  +15% vol<2.0 tr35   30.8%   −5.1%    15.2%  25.1%
    21-06~24-05  +20% vol<2.0 tr35   27.1%  −11.2%   −33.4%  12.1%
    22-06~25-05  +15% vol<1.2 tr25   48.7%  +73.3%    50.0%  28.4%
    TEST 에서 SPY 를 이긴 횟수: 워크포워드 1/5 · **현행 고정도 1/5**
  → 파라미터를 고르는 행위가 아웃오브샘플에서 아무 정보도 주지 않았다.
  → 단, TEST 가 1년이라 표본이 얇다(L 은 연간 신호 60여 건, 6칸을 채우기도 빠듯).
    1년 단위로는 아무 말도 못 한다는 뜻이기도 하다 — 그런데 실전 단위가 1년이다.

  구간을 길게 잘라보면 L 과 S 가 갈린다:
                                   L 6칸    S 10칸    SPY
    전체 2018-06~2026-08            25.4%    23.5%   15.1%
    최근 15개월 제외 ~2025-05         20.2%    17.1%   13.2%
    뒤 구간에서 최근 제외 22-01~25-05   21.0%     5.8%    8.7%   ← S 가 SPY 에 진다
    최근 15개월만 2025-06~           32.4%    98.1%   25.8%
  **L 은 어느 구간을 잘라도 SPY 를 상회한다. S 는 최근 15개월 의존이 심하다.**

  진짜 아웃오브샘플은 규칙 확정일(2026-08-18) 이후 주차뿐이다. 그때부터 세라.

⚠️ 이 규칙을 튜닝할 사람에게 — 실효 표본은 두 자릿수다
  428주 중 신호가 있는 주는 149주이고, 슬롯 경쟁이 벌어진 주는 **16주**,
  그중 1년 성과를 잴 수 있는 건 11주다. 격자를 돌리면 언제나 그럴듯한 봉우리가
  나오지만 대부분 열 몇 번의 판단이 만든 것이다. 개선안은 세 단계를 다 통과해야
  한다: ① 격자에서 높다 ② 진입 1·2주 지연에도 남는다 ③ 우위를 만든 주차를
  열어봤을 때 특정 국면 한두 주가 아니다. 2026-08-22 기준 통과한 개선안은 없다.

CLI
  python leaders_ab.py            # 백테스트 + 발행
  python leaders_ab.py publish    # 같음
"""
import os, sys, json, sqlite3
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "market.db")
VOL = os.path.join(BASE, "data", "_volwk.parquet")
OUT = os.path.join(BASE, "results", "leaders_ab.json")
VER = "v1"
FEE = 0.001

# ── 규칙 ────────────────────────────────────────────────────────────
SURGE_RET, SURGE_VOL = 20.0, 1.5
RULES = {
    "L": dict(name="대형 주도주",
              slots=6, trail=0.30, mc_lo=2e9, mc_hi=None, fund=True,
              text="시총 $2B+ · 주간 +20%↑ · 거래량 전주비 <1.5배 · "
                   "(영업익 8분기 신고점 OR OPM 전분기比 +5%p↑)",
              exit="진입 후 주봉 종가 고점 대비 −30% → 그 주 종가 전량. 재신호 시 재진입",
              # 2026-08-22 채택 — 눌림목 4분할. **수익 규칙이 아니라 보험이다.**
              #   측정(정시/1주지연/2주지연): 일괄 24.9/24.9/19.7% · 눌림목4분할 18.3/18.4/15.1%
              #   MDD                      : 일괄 −39.8/−34.3/−40.7% · 분할 −27.2/−31.9/−29.4%
              #   → CAGR 6.6%p 를 내고 MDD 12.6%p 를 산다. MDD 우위는 세 시점 전부 일관.
              #   2026-06 손실이 '한 번에 실은 것'에서 왔으므로 그 대가를 치르기로 했다.
              tranche=dict(k=4, lo=0.05, hi=0.10),
              tranche_text="1/4 씩 4회. 2회차부터는 진입 후 고점 대비 −5~10% 눌리고, "
                           "직전 매수가를 넘고, 20주선 위일 때만 추가"),
    "S": dict(name="소형 대시세",
              slots=10, trail=0.40, mc_lo=None, mc_hi=2e9, fund=False,
              text="시총 $2B 미만 · 주간 +20%↑ · 거래량 전주비 <1.5배 · 재무 조건 없음",
              exit="진입 후 주봉 종가 고점 대비 −40% → 그 주 종가 전량. 재신호 시 재진입",
              # S 는 일괄이다. 분할이 CAGR 만 깎고(23.3% → 12.4~20.9%) MDD 는 그대로였다
              #   (−49.4% → −50.1%). 소형 대시세는 초기 폭발을 놓치면 끝이라서다.
              tranche=None, tranche_text="일괄 진입 (분할은 측정상 손해만 봤다)"),
}
MIN_ADV = 5e6            # 일평균 거래대금 $5M — 못 사는 신호는 백테스트에 넣지 않는다
SEGMENTS = [("앞 구간 2018-06~2021-12", "2018-06-01", "2021-12-31"),
            ("뒤 구간 2022-01~2026-08", "2022-01-01", "2026-12-31"),
            ("전체", "2018-06-01", "2026-12-31")]


# ── 데이터 ──────────────────────────────────────────────────────────
def load():
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    d = pd.read_sql(f"""SELECT as_of,sym,name,close,ret_1w,adv_20d,marcap,period_end,
                               op_income,opm,rs_13w,rs_26w,dist_52w,per,psr,rev_yoy,ma20
                        FROM factor_weekly WHERE factor_ver='{VER}'""", c)
    c.close()
    d["as_of"] = pd.to_datetime(d.as_of)

    # 재무 플래그는 분기 패널에서 만든다(period_end 기준 = 그 주차에 알 수 있던 값)
    q = (d.dropna(subset=["period_end"]).drop_duplicates(["sym", "period_end"])
           [["sym", "period_end", "op_income", "opm"]]
           .sort_values(["sym", "period_end"]))
    g = q.groupby("sym")
    hi8 = g.op_income.transform(lambda s: s.shift(1).rolling(8, min_periods=4).max())
    q["F_HI8"] = ((q.op_income > 0) & (q.op_income > hi8)).astype(int)
    q["F_OPM"] = ((q.opm - g.opm.shift(1)) >= 5).astype(int)
    d = d.merge(q[["sym", "period_end", "F_HI8", "F_OPM"]],
                on=["sym", "period_end"], how="left")

    # 거래량 전주 대비. ⚠️ 20주 평균(vol_x_20w)이 아니다 — 그걸로는 안 보인다.
    v = pd.read_parquet(VOL)
    v["as_of"] = pd.to_datetime(v.as_of)
    v = v.sort_values(["sym", "as_of"])
    v["vw"] = v.groupby("sym").vol_wk.transform(lambda s: s / s.shift(1))
    return d.merge(v[["as_of", "sym", "vw"]], on=["as_of", "sym"], how="left")


def assert_vol_fresh(M):
    """마지막 주차의 vw 가 통째로 비어 있으면 신호가 구조적으로 0이 된다.
       2026-08-22: _volwk.parquet 가 한 주 밀린 채 발행돼 '신호 0종'이 떴고
       사이클은 성공(EXIT=0)을 보고했다. 그런 발행은 아예 막는다."""
    last = M["close"].index.max()
    n = int(M["vw"].loc[last].notna().sum())
    if n < 50:
        raise SystemExit(
            f"[중단] {last:%Y-%m-%d} 주차의 거래량 전주비(vw)가 {n}종밖에 없다. "
            "data/_volwk.parquet 가 밀렸다는 뜻이고, 이대로 발행하면 "
            "'신호 0종'이라는 가짜 결과가 화면에 뜬다. "
            "→ python volwk_build.py 를 먼저 돌려라.")
    return n


def matrices(d, cols):
    return {k: d.pivot_table(index="as_of", columns="sym", values=k).sort_index()
            for k in cols}


def gate_of(M, key):
    r = RULES[key]
    g = ((M["ret_1w"] >= SURGE_RET) & (M["vw"] < SURGE_VOL) & (M["adv_20d"] >= MIN_ADV))
    if r["mc_lo"]:
        g &= M["marcap"] >= r["mc_lo"]
    if r["mc_hi"]:
        g &= M["marcap"] < r["mc_hi"]
    if r["fund"]:
        g &= (M["F_HI8"] == 1) | (M["F_OPM"] == 1)
    return g.fillna(False)


# ── 시뮬레이션 ──────────────────────────────────────────────────────
def sim(M, gate, N, trail, a, b, keep_pos=False, tranche=None):
    """주 1회 빈 슬롯만 채우고, 진입 후 주봉 종가 고점 대비 −trail 에서 그 주 종가 청산.

    tranche=dict(k, lo, hi) 를 주면 **눌림목 분할 진입**을 한다(2026-08-22 채택, L 전용).
      · 신호 주에 슬롯의 1/k 만 산다
      · 2회차부터는 세 조건을 동시에 만족할 때만 1/k 씩 추가한다
          ① 진입 후 고점 대비 낙폭이 lo~hi 사이   ② 직전 매수가보다 위
          ③ 20주 이동평균 위
      · 못 채운 몫은 현금으로 남는다 — 그게 MDD 를 낮추는 실체다.
    """
    px, ma = M["close"], M.get("ma20")
    dates = px.index[(px.index >= a) & (px.index <= b)]
    cash, pos, eq, nh = 1.0, {}, [], []
    W = 1.0 / N
    k = (tranche or {}).get("k", 1)
    lo, hi = (tranche or {}).get("lo", 0), (tranche or {}).get("hi", 0)
    for t in dates:
        p = px.loc[t]
        mrow = ma.loc[t] if ma is not None else None
        for s in list(pos):
            v = p.get(s)
            if v is None or v != v:
                continue
            pos[s]["peak"] = max(pos[s]["peak"], v)
            if v <= pos[s]["peak"] * (1 - trail):
                cash += pos[s]["sh"] * v * (1 - FEE)
                del pos[s]
        # ⚠️ p.get(s, 기본값)은 키가 없을 때만 기본값을 쓴다. 상장폐지로 값이 NaN 이면
        #    NaN 이 그대로 나와 그 뒤 자산곡선 전체가 NaN 이 된다(2026-08-18 SKYT).
        val = cash + sum(o["sh"] * (v if (v := p.get(s)) == v and v is not None
                                    else o["last"]) for s, o in pos.items())
        # ── 눌림목 추가 매수 (2~k 회차) ──────────────────────
        if tranche:
            for s_, o in pos.items():
                if o["step"] >= k:
                    continue
                v = p.get(s_)
                if v != v or v is None:
                    continue
                dd = 1 - v / o["peak"]                     # 진입 후 고점 대비 낙폭
                mv = mrow.get(s_) if mrow is not None else None
                if (lo <= dd <= hi) and v > o["lastbuy"]                         and mv == mv and mv is not None and v > mv:
                    amt = min(val * W / k, cash)
                    if amt > 0:
                        cash -= amt
                        o["sh"] += amt / v * (1 - FEE)
                        o["lastbuy"] = v
                        o["step"] += 1

        if len(pos) < N:
            gg = gate.loc[t]
            rk = M["ret_1w"].loc[t]
            cand = [s for s in gg[gg].index
                    if s not in pos and p.get(s) == p.get(s) and (p.get(s) or 0) > 0]
            cand.sort(key=lambda s: -(rk.get(s) if rk.get(s) == rk.get(s) else -9e9))
            for s in cand[:N - len(pos)]:
                amt = min(val * W / k, cash)          # 분할이면 1/k 만
                if amt <= 0:
                    break
                cash -= amt
                pos[s] = dict(sh=amt / p[s] * (1 - FEE), peak=p[s], last=p[s],
                              entry=float(p[s]), ed=str(t.date()), wk=0,
                              lastbuy=float(p[s]), step=1, ksteps=k,
                              w0=float(amt / val * 100))   # 진입 당시 비중
        for s, o in pos.items():
            v = p.get(s)
            if v == v and v is not None:
                o["last"] = v
            o["wk"] = o.get("wk", 0) + 1
        eq.append((t, cash + sum(o["sh"] * o["last"] for o in pos.values())))
        nh.append(len(pos))
    e = pd.Series(dict(eq))
    if keep_pos:
        return e, float(np.mean(nh)), pos, cash
    return e, float(np.mean(nh))


def live_book(M, gate, key, nm):
    """지금 규칙대로 샀다면 어떤 포지션을 들고 있는가 — 실계좌와 대조할 기준선.

    2026-08-22: 보유 종목을 사람이 입력하는 방식은 3개월간 한 번도 채워지지 않았다.
    그래서 입력을 요구하지 않고, **규칙이 만든 가상 장부**를 대신 보여준다.
    이건 규율 엔진이 아니라 기준선이다 — 형의 실제 집중·레버리지는 못 막는다.
    다만 '지금 규칙대로면 무엇을 몇 % 들고 얼마가 현금인가'는 눈으로 대조할 수 있다.
    """
    r = RULES[key]
    a, b = SEGMENTS[2][1], SEGMENTS[2][2]
    _, _, pos, cash = sim(M, gate, r["slots"], r["trail"], a, b, keep_pos=True,
                          tranche=r.get("tranche"))
    px = M["close"]
    val = cash + sum(o["sh"] * o["last"] for o in pos.values())
    rows = []
    for s, o in pos.items():
        cur = o["last"]
        dd = cur / o["peak"] - 1                      # 고점 대비 현재 낙폭
        room = (1 - r["trail"]) * o["peak"] / cur - 1  # 청산선까지 남은 거리
        rows.append(dict(
            sym=s, name=(nm.get(s) or s)[:24], ed=o["ed"], wk=int(o.get("wk", 0)),
            entry=_r(o["entry"]), cur=_r(cur),
            ret=_r((cur / o["entry"] - 1) * 100, 1),
            peak=_r(o["peak"]), dd=_r(dd * 100, 1),
            stop=_r(o["peak"] * (1 - r["trail"])),
            room=_r(room * 100, 1),
            w=_r(o["sh"] * cur / val * 100, 1), w0=_r(o.get("w0"), 1),
            step=int(o.get("step", 1)), ksteps=int(o.get("ksteps", 1))))
    rows.sort(key=lambda x: -(x["w"] or 0))
    return dict(slots=r["slots"], filled=len(pos),
                cash_pct=_r(cash / val * 100, 1), positions=rows)


def stat(e):
    y = (e.index[-1] - e.index[0]).days / 365.25
    mdd = (e / e.cummax() - 1).min() * 100
    cagr = (e.iloc[-1] ** (1 / y) - 1) * 100
    return dict(cagr=round(float(cagr), 1), mdd=round(float(mdd), 1),
                total=round(float((e.iloc[-1] - 1) * 100), 0),
                recover=round(float(cagr / abs(mdd)), 2) if mdd else None)


def spy_stat(a, b):
    p = os.path.join(BASE, "data", "leaders_cache", "px_SPY.csv")
    s = pd.read_csv(p, index_col=0, parse_dates=True).Close
    s = s[(s.index >= a) & (s.index <= b)]
    return stat(s / s.iloc[0])


# ── 발행 ────────────────────────────────────────────────────────────
def build():
    d = load()
    M = matrices(d, ["close", "ret_1w", "adv_20d", "marcap", "vw", "F_HI8", "F_OPM",
                     "ma20"])   # ma20 = 눌림목 분할 진입 판정용(20주선 위에서만 추가)
    _nv = assert_vol_fresh(M)   # 거래량 패널이 밀렸으면 여기서 죽는다(가짜 0 방지)
    print(f"거래량 패널 확인 — 마지막 주차 vw {_nv:,}종")
    gates = {k: gate_of(M, k) for k in RULES}

    print("백테스트 —", flush=True)
    bt, eq = {}, {}
    for k, r in RULES.items():
        bt[k] = {}
        for lab, a, b in SEGMENTS:
            e, held = sim(M, gates[k], r["slots"], r["trail"], a, b,
                          tranche=r.get("tranche"))
            eq[(k, lab)] = e
            bt[k][lab] = {**stat(e), "held": round(held, 1), "slots": r["slots"]}
            print(f"  {k} {lab:<22} CAGR {bt[k][lab]['cagr']:>6.1f}% "
                  f"MDD {bt[k][lab]['mdd']:>6.1f}%  보유 {held:.1f}/{r['slots']}", flush=True)
    bt["MIX"] = {}
    for lab, a, b in SEGMENTS:
        e = 0.5 * eq[("L", lab)] + 0.5 * eq[("S", lab)]
        bt["MIX"][lab] = stat(e)
        print(f"  L+S 50:50 {lab:<16} CAGR {bt['MIX'][lab]['cagr']:>6.1f}% "
              f"MDD {bt['MIX'][lab]['mdd']:>6.1f}%", flush=True)
    bt["SPY"] = {lab: spy_stat(a, b) for lab, a, b in SEGMENTS}

    # 지금 규칙대로면 무엇을 들고 있나 — 실계좌와 눈으로 대조할 기준선
    _nm0 = d.drop_duplicates("sym").set_index("sym")["name"].to_dict()
    book = {k: live_book(M, gates[k], k, _nm0) for k in RULES}
    for k, bk in book.items():
        print(f"  {k} 장부 — {bk['filled']}/{bk['slots']}칸 · 현금 {bk['cash_pct']}%",
              flush=True)

    # ── 주차별 신호 이력 (대시보드 주차별 조회용) ──
    last = M["close"].index.max()
    nm = d.drop_duplicates("sym").set_index("sym")["name"].to_dict()
    weeks, cands = {}, {}
    fwd = {h: (M["close"].shift(-h) / M["close"] - 1) for h in (1, 4, 13, 26, 52)}
    for k in RULES:
        g = gates[k]
        # 신호 서수 — 그 규칙 안에서 이 종목이 몇 번째로 낸 신호인가.
        # 연속일 필요 없고 보유 중 재신호도 센다. 규칙에는 안 쓰고 화면에만 띄운다
        # (2026-08-22 측정: S 3번째+ 는 통계는 통과했으나 임계 격자가 지그재그였다.
        #  실전 신호로 표본을 쌓아 형이 직접 판단할 재료로만 제공한다.)
        ordn = g.cumsum().where(g)
        for t in g.index:
            hit = g.loc[t]
            syms = list(hit[hit].index)
            if not syms:
                continue
            rows = []
            for s in syms:
                rows.append(dict(
                    r=k, sym=s, name=(nm.get(s) or s)[:24],
                    close=_r(M["close"].loc[t].get(s)),
                    up=_r(M["ret_1w"].loc[t].get(s), 1),
                    vw=_r(M["vw"].loc[t].get(s), 2),
                    mc=_r((M["marcap"].loc[t].get(s) or np.nan) / 1e9, 2),
                    n=int(ordn.loc[t].get(s) or 0),
                    **{f"f{h}": _r((fwd[h].loc[t].get(s) or np.nan) * 100, 1)
                       for h in (1, 4, 13, 26, 52)}))
            rows.sort(key=lambda x: -(x["up"] or 0))
            weeks.setdefault(str(t.date()), []).extend(rows)
        hit = g.loc[last]
        cands[k] = [x for x in weeks.get(str(last.date()), []) if x["r"] == k]

    # 거래량 패널(_volwk.parquet)은 저장소에 없다(1.6M행). 그런데 이게 밀리면
    # vw 가 NaN 이 되어 **가짜 '신호 0종'**이 뜨므로 반드시 감시해야 한다.
    # 파일을 직접 등록하면 러너에 파일이 없어 스모크가 깨진다(2026-08-22 CI 실패).
    # 그래서 기준일을 **발행물 안에 실어** 배포된 화면에서도 보이게 한다.
    _vwrows = M["vw"].notna().any(axis=1)
    vol_asof = (str(M["vw"].index[_vwrows][-1].date()) if bool(_vwrows.any()) else None)

    out = dict(
        generated=str(pd.Timestamp.today().date()), vol_asof=vol_asof,
        signal_week=str(last.date()),
        universe=int(M["close"].loc[last].notna().sum()),
        rules={k: {"name": v["name"], "text": v["text"], "exit": v["exit"],
                   "tranche": v.get("tranche"), "tranche_text": v.get("tranche_text"),
                   "slots": v["slots"], "trail": int(v["trail"] * 100)}
               for k, v in RULES.items()},
        backtest=bt, candidates=cands, weeks=weeks, book=book,
        caveats=[
            "생존 편향 — 유니버스가 '오늘 상장된 종목'이라 상장폐지 회사가 빠져 있다. 실제는 더 나쁘다.",
            "L은 평균 3.5종만 보유한다. 칸을 6→7로 늘리면 뒤 구간이 28.4%→11.0%로 꺾인다 — 한두 종목이 결과를 좌우한다.",
            "MDD −38%는 SPY(−31.8%)보다 크다. 수익 +9.4%p를 낙폭 6%p로 사는 거래다.",
            "여러 조합 중 고른 결과다. 칸 수·진입 지연에서 고원을 확인했지만 선택 편향은 남는다.",
        ])
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"→ {OUT}  ({os.path.getsize(OUT)/1e6:.2f} MB · 주차 {len(weeks)} · "
          f"이번 주 L {len(cands['L'])}종 / S {len(cands['S'])}종)")


def _r(v, n=2):
    try:
        return None if v is None or v != v else round(float(v), n)
    except Exception:
        return None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    build()
