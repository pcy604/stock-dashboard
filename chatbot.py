# -*- coding: utf-8 -*-
"""사이트 AI 챗봇(2026-11-15) — 무료 AI(Gemini 2.5 Flash-Lite → Flash, 막히면 Groq)로 '이 사이트 숫자'만 근거로 답한다.

원칙
- 근거 = 사이트 산출물(JSON)만: 시황 리포트 facts · 매크로 판정 · 실전 규칙 지수 게이트 · 질문에 나온 종목의 스냅샷(7블록)·기간 수익률.
  뉴스·전망·외부 지식으로 숫자를 지어내지 않는다. 자료에 없으면 '자료에 없음 + 어느 탭에서 보는지'.
- 매수·매도 추천 금지(공개 사이트 — 투자 자문 아님). 판단 근거 숫자만.
- 무료 한도: 세션당 15문항. 모델 순서 = 무료 한도 넓은 것부터.
화면은 dashboard 가 그리고, 여기는 자료 조립·모델 호출만(테스트 가능하게 streamlit 비의존).
"""
from __future__ import annotations

import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
MODELS = ["gemini-2.5-flash-lite", "gemini-2.5-flash"]     # 무료 한도는 모델별 — Lite 가 넓다
GROQ_MODEL = "llama-3.3-70b-versatile"
SESSION_LIMIT = 15

PROMPT = """너는 'STOCK DASHBOARD' 사이트의 AI 도우미다. 아래 [자료]만 근거로 한국어로 답한다.
규칙
1. 자료에 없는 숫자·뉴스·전망·회사 정보는 지어내지 않는다. 없으면 "사이트 자료에 없습니다"라고 쓰고, 볼 수 있는 탭을 [탭 안내]에서 골라 알려 준다.
2. 매수·매도·비중 추천을 하지 않는다("사라/팔아라/담아라" 금지). 대신 판단에 쓰는 숫자와 사이트 규칙이 무엇을 말하는지만 정리한다.
3. 숫자를 쓸 때는 기준일을 괄호로 붙인다. 같은 숫자가 여러 곳에 있으면 날짜가 최신인 것.
4. 말투: 증권사 리포트체(명사형 종결, 예: "~상승", "~확인 필요"). 5줄 이내, 핵심 먼저. 필요하면 글머리표.
5. 사이트 규칙(실전 v1.9)은 '이 사이트가 쓰는 규칙'으로 설명한다 — 사용자에게 따르라고 권하지 않는다.
[탭 안내]
{tabs}
[자료]
{ctx}
[대화]
{hist}
[질문]
{q}"""

TABS = ("🏠 종합: 이번 주 시장 신호(한국 주봉 5주선)·글로벌 마켓·오닐 추세·오늘의 시장(한·미 시장 폭·업종·테마·신고가)·시황 리포트 | "
        "🌍 매크로: 경기 국면·돈의 흐름·한국 수급·신용 | 🧭 종목 발굴: 실전 규칙 후보·52주 신고가·상승 상위·시총 상위·CANSLIM | "
        "🔍 종목 분석: 종목 코드 입력 → 결론·펀더멘탈·히스토리·수급·깨지는 조건 | 🛡️ 내 포트폴리오: 보유 종목 점검(로그인)")


def _j(p):
    try:
        return json.load(open(os.path.join(BASE, p), encoding="utf-8"))
    except Exception:
        return {}


def _find_syms(q: str, limit=3) -> list[dict]:
    """질문 속 종목 — 이름(2자+) 또는 코드·티커. perf_latest 기준."""
    qn = q.replace(" ", "").casefold()
    _STOP = {"AI", "US", "KR", "ETF", "PER", "PBR", "RS", "EPS", "ROE", "MDD", "VIX", "FOMC", "CPI", "GDP", "PEG"}
    toks = {t for t in re.findall(r"[A-Za-z]{1,5}|\d{6}", q) if t.upper() not in _STOP}
    out = []
    for x in (_j("results/perf_latest.json").get("stocks") or []):
        n = str(x.get("name") or "").replace(" ", "").casefold()
        s = str(x.get("sym") or "")
        if (len(n) >= 2 and n in qn) or (s and (s in toks or s.upper() in {t.upper() for t in toks if len(t) >= 2})):
            out.append(x)
            if len(out) >= limit:
                break
    return out


def _snap(sym: str) -> dict:
    """종목 스냅샷(대시보드 종목 분석 7블록 정본) — 카드 첫 줄만."""
    s = _j(f"results/snap/{sym}.json")
    if not s:
        return {}
    blocks = {}
    for k, b in (s.get("blocks") or {}).items():
        blocks[k] = [f"{c.get('label')}: {c.get('value')} ({c.get('sub')})" for c in (b.get("cards") or [])[:3]]
    return {"기준일": s.get("asof"), "유형": (s.get("type") or {}).get("label"), "결론": s.get("verdict"), "블록": blocks}


def context(q: str) -> str:
    """자료 조립 — 상한 14,000자. 종목 질문이면 종목 자료를 맨 앞에."""
    parts = []
    for x in _find_syms(q):
        row = {k: v for k, v in x.items() if not isinstance(v, (list, dict))}
        sn = _snap(str(x.get("sym")))
        parts.append(json.dumps({"종목": row, "스냅샷": sn or "스냅샷 없음 — 🔍 종목 분석 탭에서 직접 조회"},
                                ensure_ascii=False)[:3000])
    pl = _j("live/plan_latest.json")
    gate = {k: {kk: v.get(kk) for kk in ("last", "ma200", "date")} | {"종가>5주선": (v.get("last") or 0) > (v.get("ma200") or 0)}
            for k, v in (pl.get("index") or {}).items() if isinstance(v, dict)}
    if gate:
        parts.append(json.dumps({"실전 규칙 v1.9 지수 게이트(주봉 5주선 — 종가가 위면 그 시장 신규 매수 가능)": gate},
                                ensure_ascii=False))
    m = _j("results/macro.json")
    if m:
        parts.append(json.dumps({"매크로(기준일 " + str(m.get("asof")) + ")": {k: m.get(k) for k in ("phase", "greed", "flow", "econ", "core")}},
                                ensure_ascii=False, default=str)[:2500])
    try:
        import market_report as _MR
        parts.append(_MR.chat_context(max_chars=9000))
    except Exception:
        pass
    return "\n".join(parts)[:14000]


def _groq(prompt: str, key: str) -> str:
    import requests
    r = requests.post("https://api.groq.com/openai/v1/chat/completions", timeout=40,
                      headers={"Authorization": f"Bearer {key}"},
                      json={"model": GROQ_MODEL, "temperature": 0.2,
                            "messages": [{"role": "user", "content": prompt}]})
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"].strip()




# ── 사이트 명령(2026-11-16) — 부자알람 봇 명령 중 사이트 자료만으로 즉시 답할 수 있는 것. AI 호출·질문 한도 없음.
COMMANDS = [
    ("/market", "장 마감 시황 요약 — /market kr · /market us"),
    ("/signal", "실전 규칙 지수 게이트(코스피·코스닥 주봉 5주선)"),
    ("/dashboard 종목", "종목 분석 결론 — 예: /dashboard 삼성전자 · /dashboard NVDA"),
    ("/terms", "이용 안내 · 면책"),
    ("/help", "명령어 목록"),
]
TERMS = ("정보 제공 도구이며 투자 권유가 아님. 수치는 사이트 산출물 기준이며 지연·오류 가능. "
         "백테스트 수치는 과거 성적이며 실현 수익이 아님. 운영자는 화면에 나온 종목을 보유하고 있을 수 있음.")


def _md_section(md: str, title: str) -> str:
    m = re.search(rf"##\s*{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)", md or "", flags=re.S)
    return (m.group(1).strip() if m else "")


def _cmd_market(arg: str) -> str:
    rep = _j("results/market_report.json")
    key = "latest_daily" if arg.lower() in ("us", "미국") else "latest_kr"
    r = rep.get(key) or rep.get("latest_kr") or {}
    if not r:
        return "시황 리포트 없음 — 🏠 종합 탭 확인."
    md = r.get("markdown") or ""
    one = _md_section(md, "한 줄 요약")
    rule = next((ln for ln in md.splitlines() if ln.startswith("**실전 규칙")), "")
    head = "한국 장 마감 시황" if key == "latest_kr" else "미국 일간 시황"
    return f"**{head}** ({r.get('date')})\n\n{one}\n\n{rule}".strip() + "\n\n전문: 🏠 종합 → 시황 리포트"


def _cmd_signal() -> str:
    pl = _j("live/plan_latest.json")
    rows = []
    for k, v in (pl.get("index") or {}).items():
        if not isinstance(v, dict) or v.get("last") is None or v.get("ma200") is None:
            continue
        ok = v["last"] > v["ma200"]
        gap = (v["last"] / v["ma200"] - 1) * 100 if v["ma200"] else 0
        nm = {"KR": "코스피", "KQ": "코스닥", "US": "S&P500(참고 · 한국 규칙 미적용)"}.get(k, k)
        rows.append(f"- {nm}: 종가 {v['last']:,.2f} · 5주선 {v['ma200']:,.2f} ({gap:+.1f}%) → {'상회' if ok else '하회'}"
                    + ("" if k == "US" else f" · 신규 진입 {'가능' if ok else '중지'}"))
    if not rows:
        return "지수 게이트 자료 없음 — 🏠 종합 탭 확인."
    return f"**실전 규칙 v1.9 지수 게이트** (계획표 {pl.get('made') or '-'})\n" + "\n".join(rows)


def _cmd_dashboard(arg: str) -> str:
    if not arg:
        return "종목을 함께 입력 — 예: /dashboard 삼성전자 · /dashboard 005930 · /dashboard NVDA"
    hit = _find_syms(arg, limit=1)
    if not hit:
        return f"'{arg}' 종목을 찾지 못함 — 🔍 종목 분석 탭에서 코드로 조회."
    x = hit[0]
    sym, name = str(x.get("sym")), x.get("name") or ""
    s = _j(f"results/snap/{sym}.json")
    v = (s.get("verdict") or {}) if s else {}
    if not v:
        return f"**{name} ({sym})** — 스냅샷 없음. 🔍 종목 분석 탭에서 실시간 조회: [열기](?sym={sym})"
    lines = [f"**{name} ({sym})** — {v.get('head', '')} · 유형 {v.get('type_chip') or '-'} (기준 {s.get('asof')})"]
    lines += [f"- {c.get('label')}: {c.get('value')} — {c.get('sub')}" for c in (v.get("cards") or [])[:4]]
    lines.append(f"\n상세: [🔍 종목 분석에서 열기](?sym={sym})")
    return "\n".join(lines)


def command(q: str) -> str | None:
    """'/' 로 시작하면 사이트 명령으로 처리(AI 미사용). 모르는 명령이면 목록을 돌려준다."""
    q = (q or "").strip()
    if not q.startswith("/"):
        return None
    cmd, _, arg = q.partition(" ")
    cmd, arg = cmd.lower(), arg.strip()
    if cmd == "/market":
        return _cmd_market(arg)
    if cmd in ("/signal", "/신호"):
        return _cmd_signal()
    if cmd in ("/dashboard", "/분석", "/report"):
        return _cmd_dashboard(arg)
    if cmd == "/terms":
        return TERMS
    return "**사이트 명령어** (AI 질문 한도 미차감)\n" + "\n".join(f"- `{c}` — {d}" for c, d in COMMANDS)


def ask(q: str, history: list[tuple[str, str]] | None = None, gemini_key: str = "", groq_key: str = "") -> tuple[str, str]:
    """(답, 모델) — 실패하면 RuntimeError. 대화는 최근 3턴만 넘긴다(토큰 절약)."""
    hist = "\n".join(f"{'사용자' if r == 'user' else 'AI'}: {m[:400]}" for r, m in (history or [])[-6:]) or "(없음)"
    prompt = PROMPT.format(tabs=TABS, ctx=context(q), hist=hist, q=q.strip()[:500])
    last = None
    if gemini_key:
        try:
            from google import genai
            cl = genai.Client(api_key=gemini_key)
            for m in MODELS:
                try:
                    r = cl.models.generate_content(model=m, contents=prompt)
                    if (r.text or "").strip():
                        return r.text.strip(), m
                except Exception as e:
                    last = e
        except Exception as e:
            last = e
    if groq_key:
        try:
            return _groq(prompt, groq_key), GROQ_MODEL
        except Exception as e:
            last = e
    raise RuntimeError(str(last)[:160] if last else "AI 키 없음")
