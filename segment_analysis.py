"""
segment_analysis.py — 사업부문별 매출 구조 분석 (App Economy Insights 스타일)
─────────────────────────────────────────────────────────────────
"이 회사가 어느 사업으로 돈을 버는가"를 사업보고서에서 뽑아 구조화한다.
소스: DART 사업보고서 원문(business_text) → Gemini 2.5 Flash 구조화 추출 → JSON 캐시.

⚠️ 공시의 한계(중요·정직하게):
  · 사업부문별 '매출' 비중 → 대부분 공시됨 ✓
  · 사업부문별 '영업이익' 비중 → K-IFRS 부문정보로 자주 공시됨 ✓ (있으면 추출)
  · 사업부문별 '매출원가/매출총이익' → 대부분 공시 안 됨 ✗
    (기업은 부문 매출·영업이익까지만 주고 부문별 원가는 잘 안 나눔)
    → 사용자 요청의 '매출총이익 비중'은 공시가 없으면 '-'로 둠(추정하지 않음).
  · Gemini 추출이라 원본 표와 대조 권장 → 화면에 출처·보고서일 명시, 원문 링크 제공.

캐시: results/segments/{sym}.json  (30일 TTL — 사업보고서는 분기~연 단위 갱신)
"""
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

import re
import json
from pathlib import Path
from datetime import datetime

CACHE_DIR = Path('results/segments')

_PROMPT = """당신은 재무 애널리스트다. 아래는 한국 기업의 DART 사업보고서 '사업의 내용' 원문(표 태그가 제거돼 텍스트로 뭉개진 상태)이다.
이 회사의 '사업부문별 매출 구조'를 추출해 JSON으로만 답하라. 원문에 실제로 있는 숫자만 쓰고, 없으면 null. 절대 지어내지 말 것.

추출 항목:
- segments: 사업부문 배열. 각 항목:
  - name: 부문명 (예: "DX부문", "반도체")
  - products: 주요 제품/서비스 (짧게)
  - revenue: 해당 부문 매출액 (원 단위 숫자, 없으면 null)
  - revenue_pct: 전체 대비 매출 비중 % (원문에 있으면, 없으면 null)
  - op_income: 부문 영업이익 (원 단위, 공시됐으면, 없으면 null)
- total_revenue: 전체 매출액 (원, 없으면 null)
- period: 기준 회계기간 (예: "2025" 또는 "2025.12")
- currency: "KRW"
- has_segment_gross_profit: 사업부문별 매출총이익/매출원가가 원문에 분리 공시돼 있으면 true, 아니면 false
- note: 한 줄 특이사항 (예: "부문 영업이익 미공시", 없으면 "")

JSON만 출력. 마크다운 코드블록 없이."""


def _cache_path(sym):
    return CACHE_DIR / f"{sym}.json"


def load_cached(sym, max_age_days=30):
    p = _cache_path(sym)
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text(encoding='utf-8'))
        gen = datetime.fromisoformat(d.get('_generated', '2000-01-01'))
        if (datetime.now() - gen).days > max_age_days:
            return None
        return d
    except Exception:
        return None


def analyze_kr(sym, force=False):
    """KR 종목 사업부문 분석. 캐시 우선. 반환 dict 또는 None."""
    if not force:
        c = load_cached(sym)
        if c:
            return c
    try:
        import dart_client
        import guru_youtube as G           # Gemini 클라이언트·재시도 재사용
        cc = dart_client.corp_map().get(sym)
        if not cc:
            return None
        txt = dart_client.business_text(cc, max_chars=120000)
        if not txt:
            return None
        # 세그먼트 표는 '사업의 내용' 앞부분에 몰려 있음 → 앞 60k만 (토큰 절약)
        head = txt[:60000]
        client = G._gemini_client()
        resp = G._generate(client, [_PROMPT, "\n\n[사업보고서 원문]\n" + head])
        raw = resp.text if hasattr(resp, 'text') else str(resp)
        data = _parse_json(raw)
        if not data or not data.get('segments'):
            return None
        # 비중 보정: revenue만 있고 pct 없으면 계산
        segs = [s for s in data['segments'] if s.get('name')]
        tot = data.get('total_revenue') or sum((s.get('revenue') or 0) for s in segs) or None
        for s in segs:
            if s.get('revenue_pct') is None and s.get('revenue') and tot:
                s['revenue_pct'] = round(s['revenue'] / tot * 100, 1)
        data['segments'] = segs
        data['total_revenue'] = tot
        data['sym'] = sym
        data['source'] = txt[:txt.find(']') + 1] if txt.startswith('[') else 'DART 사업보고서'
        data['_generated'] = datetime.now().isoformat(timespec='seconds')
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(sym).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return data
    except Exception as e:
        return {'_error': str(e)[:200]}


def _parse_json(text: str) -> dict | None:
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t, flags=re.IGNORECASE).strip()
    for cand in (t, (re.search(r'\{.*\}', t, flags=re.DOTALL) or [None])[0]):
        if not cand:
            continue
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


if __name__ == '__main__':
    sym = sys.argv[1] if len(sys.argv) > 1 else '005930'
    d = analyze_kr(sym, force='--force' in sys.argv)
    if not d or d.get('_error'):
        print('실패:', d)
    else:
        print(f"[{d.get('period')}] {sym} · 전체매출 {d.get('total_revenue')}")
        for s in d['segments']:
            print(f"  {s['name']}: 매출 {s.get('revenue')} ({s.get('revenue_pct')}%) "
                  f"영업익 {s.get('op_income')} · {s.get('products', '')[:30]}")
        print('부문별 매출총이익 공시:', d.get('has_segment_gross_profit'), '·', d.get('note'))
