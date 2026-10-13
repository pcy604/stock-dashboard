"""토스증권 Open API 실주문 — P2 단계에서 구현한다. 지금은 자리만 있다.

확인된 사양(2026-10, 원칙 v1 §8):
  · OAuth2 Client Credentials — POST https://openapi.tossinvest.com/oauth2/token
  · 계좌 헤더 X-Tossinvest-Account (GET /api/v1/accounts 의 accountSeq)
  · 주문 POST /api/v1/orders {symbol, side, orderType(LIMIT|MARKET), price, quantity|orderAmount(미국만),
          timeInForce, clientOrderId}
  · 사전 확인 GET /api/v1/buying-power · /api/v1/sellable-quantity
  · 요청 한도: 주문 초당 6건(국내 09:00~09:10 3건) · 계좌 초당 1건
  · 모의투자 없음 → broker_paper 로 P1 을 대신한다
  · ⚑ 해외 거주자(폴란드) 이용 가능 여부 미확인
"""


class TossBroker:
    def __init__(self, *a, **k):
        raise NotImplementedError("P2(소액 실전) 단계에서 구현 — 지금은 broker_paper 를 쓴다")
