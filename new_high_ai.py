# -*- coding: utf-8 -*-
"""
52주 신고가 종목의 공통점 — AI 요약 (2026-10-19 사용자 요청)

화면 버튼과 매일 06시 자동 생성이 같은 코드를 쓴다.
  · 자동: daily-refresh 가 최신 주의 요약을 results/new_high_ai.json 에 저장 → 화면은 누르지 않아도 보인다.
    (버튼만 있으면 찾기도 어렵고, 서버에 키가 없으면 눌러야 오류가 보였다 — 10-20 '요약이 없다'.)
  · 버튼: 다른 주를 고르면 그 자리에서 생성(같은 주·같은 묶음은 하루 캐시).

규칙: 표에 있는 숫자·업종만 근거로. 원인 추정은 '~로 보인다'. 매수 추천 금지.

CLI: python new_high_ai.py        # 최신 주(전체 시장) 요약 → results/new_high_ai.json
"""
import json
import os
import time
from datetime import datetime

OUT = 'results/new_high_ai.json'


def sector_map():
    out = {}
    try:
        out.update(json.load(open('data/sectors.json', encoding='utf-8')))
    except Exception:
        pass
    try:
        import pandas as pd
        d = pd.read_csv('data/us_domicile.csv', usecols=['sym', 'sic_desc'])
        out.update({str(a): b for a, b in zip(d.sym, d.sic_desc) if isinstance(b, str)})
    except Exception:
        pass
    return out


def week_items(stocks, week, mkt='전체'):
    """그 주 신고가 경신 종목 [(종목 dict, 그 주 종가)] — 시총 큰 순(달러 환산 근사)."""
    out = []
    for x in stocks:
        if mkt != '전체' and x.get('market') != mkt:
            continue
        for d, c in x.get('nh') or []:
            if d == week:
                out.append((x, c))
    fx = 1400.0
    out.sort(key=lambda t: -((t[0].get('marcap') or 0) / (fx if t[0].get('market') == 'KR' else 1)))
    return out


def payload(items, secs=None, c_growth=None, limit=80):
    """AI 에 넘길 표 — 업종 분포 + 종목별 한 줄."""
    import collections
    secs = secs or sector_map()
    c_growth = c_growth or {}
    cnt = collections.Counter(secs.get(x.get('sym'), '기타·미분류') for x, _ in items)
    lines = []
    for x, _c in items[:limit]:
        kr = x.get('market') == 'KR'
        cap = (x.get('marcap') or 0) / (1e8 if kr else 1e9)
        lines.append(f"{x.get('name')}({x.get('sym')}, {'KR' if kr else 'US'}) | 업종 {secs.get(x.get('sym'), '-')} | "
                     f"시총 {cap:,.0f}{'억원' if kr else '$B'} | 12주 {(x.get('ret_12w') or 0):+.0f}% | "
                     f"연속경신 {x.get('nh_streak') or 0}주 | 분기실적 {c_growth.get(x.get('sym'), '-')}"
                     f"{' | 상장 1년 미만' if x.get('young') else ''}")
    return "업종 분포: " + ", ".join(f"{k} {v}" for k, v in cnt.most_common(10)) + "\n\n" + "\n".join(lines)


def prompt(week, mkt, body):
    return (
        f"너는 20년차 한국 증권사 주식 전략가다. 아래는 {week} 주에 52주 신고가를 새로 쓴 "
        f"{'한국·미국' if mkt == '전체' else mkt} 종목 목록이다(시총 큰 순, 업종·12주 상승률·연속 경신 주수·분기 실적 포함).\n"
        "펀드매니저 아침 회의용으로 **공통점**을 한국어로 짧게 정리하라.\n\n"
        "형식:\n"
        "**한 줄 요약**: 이번 주 신고가의 성격을 한 문장으로.\n"
        "**테마·업종 묶음** (3~5개 불릿): 어떤 업종·밸류체인이 몰렸는지, 묶음마다 대표 종목명 2~4개를 반드시 괄호로.\n"
        "**질적 특징** (2~3개 불릿): 대형/중소형, 실적이 받치는지(분기 실적 열), 연속 경신(추세 지속) vs 첫 돌파, 신규 상장 비중.\n"
        "**주의할 점** (1~2개 불릿): 과열·단일 이벤트 의존 등 이 목록에서 보이는 위험.\n\n"
        "규칙: 목록에 있는 사실만으로 말하라. 목록에 없는 뉴스·원인을 지어내지 마라 — 원인을 추정할 때는 "
        "'~로 보인다'로 표시. 매수 추천 금지. 일반론 금지. 15줄 이내.\n\n" + body)


def generate(week, mkt, body, key=None):
    """(text, ok). 키가 없거나 실패하면 ok=False 와 사유 문구."""
    key = key or os.environ.get('GEMINI_KEY', '')
    if not key:
        try:
            import config
            key = getattr(config, 'GEMINI_KEY', '') or ''
        except Exception:
            key = ''
    if not key:
        return "(Gemini 키 미설정 — GEMINI_KEY 가 있어야 AI 요약이 됩니다)", False
    try:
        from google import genai
        cl = genai.Client(api_key=key)
        last = None
        for m in ('gemini-2.5-flash', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'):
            try:
                r = cl.models.generate_content(model=m, contents=prompt(week, mkt, body))
                t = (r.text or '').strip()
                if t:
                    return t, True
            except Exception as e:
                last = e
                time.sleep(3)
        return f"(AI 요약 실패 — Gemini 혼잡 또는 하루 한도. [{str(last)[:80]}])", False
    except Exception as e:
        return f"(AI 요약 실패: {str(e)[:80]})", False


def main():
    d = json.load(open('results/perf_latest.json', encoding='utf-8'))
    st = d.get('stocks', [])
    weeks = sorted({w for x in st for w, _ in (x.get('nh') or [])})
    if not weeks:
        print("::warning title=신고가 AI 요약::주간 이력(nh)이 없다 — 건너뜀")
        return
    cg = {}
    for f in ('results/canslim_latest.json', 'results/canslim_us_latest.json'):
        try:
            for x in json.load(open(f, encoding='utf-8')).get('stocks', []):
                v = x.get('c_growth_pct')
                cg[x['sym']] = v if isinstance(v, str) else (f"{v:+.0f}%" if v is not None else '-')
        except Exception:
            pass
    secs = sector_map()
    try:
        old = json.load(open(OUT, encoding='utf-8'))
    except Exception:
        old = {}
    out = {'generated': datetime.now().strftime('%Y-%m-%d %H:%M'), 'weeks': old.get('weeks', {})}
    # 최신 주(진행 중일 수 있음)와 직전 완결 주 — 둘 다 만들어 둔다(월요일 아침엔 최신 주가 거의 비어 있다)
    for w in weeks[-2:]:
        items = week_items(st, w)
        if not items:
            continue
        text, ok = generate(w, '전체', payload(items, secs, cg))
        print(f"{w}: {len(items)}종 → {'성공' if ok else '실패'}")
        if ok:
            out['weeks'][w] = {'n': len(items), 'text': text, 'generated': out['generated']}
        else:
            print(f"::warning title=신고가 AI 요약 실패::{w} {text}")
    out['weeks'] = dict(sorted(out['weeks'].items())[-12:])        # 최근 12주만 보관
    json.dump(out, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)


if __name__ == '__main__':
    main()
