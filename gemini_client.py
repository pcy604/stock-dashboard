# -*- coding: utf-8 -*-
"""
Gemini 클라이언트 — 접속과 재시도만 담당한다 (2026-09-07 분리)

왜 별도 파일인가
  원래 이 두 함수는 guru_youtube.py 안에 있었고, segment_analysis.py 가
  `import guru_youtube as G` 로 빌려 쓰고 있었다. 구루 유튜브 요약 기능을
  폐기(buza-bot 으로 이관)하면서 그 파일을 지우면 **대시보드의 사업부문 분석이
  같이 죽는다** — 대시보드가 segment_analysis 를 부르기 때문이다.
  요약 기능과 무관한 이 부분만 떼어 남긴다.

  ⚠️ Gemini 무료 등급은 모델당 하루 20건이다. 실제로 구루 요약이
     429 RESOURCE_EXHAUSTED 로 12일간 멈춰 있었다(2026-08-26~09-07).
     사업부문 분석도 같은 한도를 쓰므로, 하루에 몇 종목 이상 조회하면
     같은 오류를 만난다. _generate 의 재시도는 일시적 과부하용이지
     일일 한도 초과를 뚫지는 못한다.

사용
  import gemini_client as G
  resp = G.generate(G.client(), [prompt, text])
"""
import time

import config

MODEL = 'gemini-2.5-flash'

# 일시적 과부하로 보고 재시도할 신호들. 429 는 분당 한도면 뚫리지만
# 일일 한도면 재시도해도 소용없다 — 그때는 4회 시도 후 그대로 올린다.
_TRANSIENT = ('503', 'UNAVAILABLE', 'overloaded', 'high demand',
              '429', 'RESOURCE_EXHAUSTED', 'deadline', 'timeout')


def client():
    from google import genai
    key = getattr(config, 'GEMINI_KEY', '') or ''
    if not key:
        raise RuntimeError('GEMINI_KEY 미설정 (data/.gemini_key 또는 환경변수 GEMINI_KEY)')
    return genai.Client(api_key=key)


def generate(cl, contents, retries: int = 4, model: str = MODEL):
    """일시적 과부하(503/429 등)는 백오프 재시도 후에만 실패로 처리."""
    last = None
    for i in range(retries):
        try:
            return cl.models.generate_content(model=model, contents=contents)
        except Exception as e:
            last = e
            transient = any(k.lower() in str(e).lower() for k in _TRANSIENT)
            if not transient or i == retries - 1:
                raise
            wait = 5 * (i + 1)
            print(f'    [Gemini 일시오류 재시도 {i+1}/{retries}] '
                  f'{type(e).__name__} → {wait}s 대기')
            time.sleep(wait)
    raise last


# guru_youtube.py 시절의 이름. 기존 호출부 호환용이며 새 코드는 위를 쓴다.
_gemini_client = client
_generate = generate
