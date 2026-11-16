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
   단, 사이트의 지표·판정·기능이 '무엇이고 어떻게 계산되는지'는 [사이트 사전]에 모두 있다 — 이런 질문에 "자료에 없음"이라고 답하지 않는다.
   종목의 지표 값을 설명할 때는 [사이트 사전]의 정의 + [지금 보는 종목]의 값을 함께 쓴다(예: RS 95 = 그 시장 종목 중 상위 5%).
2. 매수·매도·비중 추천을 하지 않는다("사라/팔아라/담아라" 금지). 대신 판단에 쓰는 숫자와 사이트 규칙이 무엇을 말하는지만 정리한다.
3. 숫자를 쓸 때는 기준일을 괄호로 붙인다. 같은 숫자가 여러 곳에 있으면 날짜가 최신인 것.
4. 말투: 증권사 리포트체(명사형 종결, 예: "~상승", "~확인 필요"). 5줄 이내, 핵심 먼저. 필요하면 글머리표.
5. 사이트 규칙(실전 v1.9)은 '이 사이트가 쓰는 규칙'으로 설명한다 — 사용자에게 따르라고 권하지 않는다.
[탭 안내]
{tabs}
[사이트 사전]
{gloss}
[지금 보는 종목]
{page}
[자료]
{ctx}
[대화]
{hist}
[질문]
{q}"""

TABS = ("🏠 종합: 이번 주 시장 신호(한국 주봉 5주선)·글로벌 마켓·오닐 추세·오늘의 시장(한·미 시장 폭·업종·테마·신고가)·시황 리포트 | "
        "🌍 매크로: 경기 국면·돈의 흐름·한국 수급·신용 | 🧭 종목 발굴: 실전 규칙 후보·52주 신고가·상승 상위·시총 상위·CANSLIM | "
        "🔍 종목 분석: 종목 코드 입력 → 결론(4축 카드 + 매도 점검)·펀더멘탈·밸류에이션·히스토리·수급·업종 | 🛡️ 내 포트폴리오: 보유 종목 점검(로그인)")


# 2026-11-16 — 사이트 사전: 화면의 모든 지표·판정·기능의 정의(차니: '사이트 지표조차 설명 못 하는 챗봇은 필요 없다').
#   숫자 규칙은 정본(manual.rule · common_metrics.COLS)에서 읽어 화면과 어긋나지 않게 한다.
GLOSSARY_STATIC = """[종목 분석 — 결론]
- 결론 4축 카드: 펀더멘탈·밸류에이션·히스토리·수급. 카드 값 = 판정, 선 = 지나온 흐름(점선 = 컨센서스 추정), 카드 아래 = 근거 숫자. 카드를 누르면 해당 섹션으로 이동.
- 펀더멘탈 판정: 개선(내년 추정치 90일 상향 + 상향 건수 ≥ 하향 건수) / 엇갈림(신호 혼재, 또는 경기순환 기업의 이익률이 자기 역사 상위 20% = 이익 사이클 천장권) / 악화(내년 추정치 90일 −3% 이하 또는 하향 > 상향). 선 = 최근 4분기 합(TTM) 영업이익(미국은 순이익) 분기별 경로 + 올해·내년 컨센서스.
- 밸류에이션 판정: 저평가(PEG<1 · 자기 밴드 하위 25% · 업종 대비 0.8배 이하 중 우세) / 중립 / 고평가(PEG>2 · 밴드 상위 75% · 업종 대비 1.25배 이상 우세) / 판정 보류(경기순환 기업 — 이익 천장에서 P/E 가 낮아 보이는 함정, P/B·밴드 병행). 선 = 월말 P/E(적자면 P/S) 최근 5년.
- 히스토리 판정: 상승 추세(52주 고점 대비 −10% 이내 + 200일선 위) / 조정 / 하락 추세(고점 대비 −20% 이하 또는 200일선 아래). 선 = 주봉 종가 1년, 점선 = 200일 이동평균.
- 수급 판정: 강함(업종 온도 상위 30% + 종목 강세) / 보통(둘 중 하나) / 약함(둘 다 아님). 종목 강세 = RS 80 이상이면서 52주 고점 대비 −20% 이내. 선 = 종목 ÷ 지수(코스피·S&P500) 주봉 1년(시작 = 100).
- 업종 온도: 같은 업종(한국 = 네이버 테마·업종 또는 표준산업분류, 미국 = 세부 산업) 종목들의 RS 중앙값을 업종끼리 순위 매긴 것. 상위 30% = 뜨거운 업종.
- 매도 점검(실전 규칙): ① RS 70 아래(주도주 이탈 매도) ② 52주 고점 −20%(보유 중이면 보유 중 고점 기준 손절선) ③ 컨센서스 하향 전환 ④ 소속 지수 주봉 5주선 이탈(신규 매수 중지). 해당 개수만 보여 주며 매수·매도 권유가 아님.
- 보유 리스크 8개(근거 펼침): 밸류 부담(밴드 상위 20%) · 적자(TTM 순이익 ≤ 0) · 마진 악화(영업이익률 1년 새 −3%p 이하) · 부채 부담(부채비율 200% 이상) · 추정치 하향(올해 EPS 컨센서스 30일 −3% 이하) · 고변동성(연환산 60% 이상) · 사업 집중(한 부문 매출 80% 이상) · 잠재 희석(CB·BW 전환 가능 물량 5% 이상).
- 데이터 점검: 화면 숫자의 신뢰도(최신 분기 공시 반영 여부 · 현재가 · 주가 최신 · 시총 = 주가×주식수 · 컨센서스 애널리스트 3명 이상 · PER·매출 교차검증 · 부문 합계 검산). 종목 리스크가 아니다.
- 린치 유형: 고성장 · 대형 우량 · 저성장 · 경기순환 · 턴어라운드 등 — 매출 성장률·이익 상태·시총·경기순환 여부로 분류.
[지표 정의]
- RS(상대강도): 0.4×3개월 + 0.2×6개월 + 0.2×9개월 + 0.2×12개월 수익률을 같은 시장(한국/미국) 종목 안에서 백분위로 바꾼 값. 99 = 최상위, RS 95 = 상위 5%. 백테스트와 같은 식.
- 백분위(예: P/E 92 백분위): 조회 기간 중 지금보다 낮았던 기간의 비율. 92 = 과거 92% 기간보다 비쌈.
- TTM: 최근 4개 분기 합. 12MF: 앞으로 12개월 컨센서스(올해E·내년E를 남은 기간으로 가중).
- PEG = PER(12MF) ÷ EPS 성장률(%). 1 미만이면 성장 대비 싸다는 해석.
- 멀티플 밴드: 월말 시총 ÷ 그 시점 공시 TTM 이익(P/E) · 매출(P/S) · 자본(P/B)의 역사 분포. 10·25·50·75·90 분위선, 환산주가 = 최근 TTM 이 유지된다는 가정에서 그 분위 멀티플의 주가.
- 52주 고점 대비(%): 현재가 ÷ 52주 최고가 − 1. 매출·영업이익 YoY: 최근 분기 ÷ 전년 같은 분기 − 1. OPM = 영업이익 ÷ 매출.
- 상승·하락 사이클: 종가가 직전 꼭짓점에서 '구간 판정 기준'(기본 30%) 이상 되돌리면 방향 전환으로 보는 지그재그 구간. 진행 중 구간을 과거 같은 방향 구간의 중앙값(기간·폭)과 비교.
- 낙폭 매수 백테스트: 고점 대비 −X% 를 처음 깬 다음 날 종가(또는 −X% 밑에서 다시 위로 올라선 다음 날 종가)에 사서 1·3·6·12개월 보유했을 때의 수익률. 하락 회차마다 1번, 수수료 미반영.
- 월별 계절성: 같은 달의 월간 수익률 평균·승률(그 달이 오른 해의 비율)·t값(|t|≥2 면 우연이 아닐 가능성).
- 외국인·기관(한국): 최근 20거래일 순매매 금액(주식수 × 종가 근사)과 외국인 보유율 추이.
- 잠재 희석: 전환사채·신주인수권부사채·교환사채가 주식으로 바뀔 수 있는 물량 ÷ 발행주식수."""


def glossary() -> str:
    """사이트 사전 — 고정 정의 + 실전 규칙(정본 숫자) + 탭 기능(manual.CAPS) + 표 공통 열(common_metrics.COLS)."""
    parts = [GLOSSARY_STATIC]
    try:
        import manual as _M
        c = _M.ctx()
        parts.append("[실전 규칙 v1.9]\n" + "\n".join(f"- {a}: {_M._f(b, c)} — {_M._f(d, c)}" for a, b, d in _M.RULE_ROWS))
        parts.append("[탭 기능]\n" + "\n".join(f"- {t} ({s}): " + " · ".join(x for x, _ in items) for t, s, _, items in _M.caps()))
    except Exception:
        pass
    try:
        import common_metrics as _CM
        parts.append("[종목 표 공통 열]\n" + "\n".join(f"- {k}({u}): {d}" for k, (u, d, _) in _CM.COLS.items() if d))
    except Exception:
        pass
    return "\n".join(parts)[:9000]


def snap_text(s: dict) -> str:
    """지금 보는 종목(대시보드 종목 분석 스냅샷) → 챗봇 자료 한 덩어리."""
    if not s:
        return ""
    vd = s.get("verdict") or {}
    lines = [f"{s.get('name')} ({s.get('sym')}, {s.get('market')}) 기준일 {s.get('asof')} · 유형 {(s.get('type') or {}).get('label')}",
             f"결론: {vd.get('head')}"]
    lines += [f"- 결론 {c.get('label')}: {c.get('value')} ({c.get('sub')})" for c in vd.get("cards") or []]
    if s.get("halt"):
        lines.append(f"- 매도 점검: {s['halt'].get('value')} ({s['halt'].get('sub')})")
    for k, b in (s.get("blocks") or {}).items():
        for c in (b.get("cards") or [])[:4]:
            lines.append(f"- [{k}] {c.get('label')}: {c.get('value')} ({c.get('sub')})")
        for r in (b.get("detail") or [])[:20]:
            lines.append(f"  · {r.get('grp', '')} {r.get('name')}: {r.get('state')} — {r.get('detail', '')}")
    return "\n".join(str(x) for x in lines)[:4000]


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
    ("/market (/시황)", "장 마감 시황 요약 — /market kr · /market us"),
    ("/signal (/신호)", "신규 진입 가능 여부 — 코스피·코스닥 주봉이 5주 이동평균 위인지"),
    ("/dashboard 종목 (/분석)", "종목 분석 결론 — 예: /dashboard 삼성전자 · /dashboard NVDA"),
    ("/terms (/안내)", "이용 안내 · 면책 고지"),
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
    if cmd in ("/market", "/시황"):
        return _cmd_market(arg)
    if cmd in ("/signal", "/신호", "/게이트"):
        return _cmd_signal()
    if cmd in ("/dashboard", "/분석", "/report"):
        return _cmd_dashboard(arg)
    if cmd in ("/terms", "/안내", "/면책"):
        return TERMS
    return "**사이트 명령어** (AI 질문 한도 미차감)\n" + "\n".join(f"- `{c}` — {d}" for c, d in COMMANDS)


def ask(q: str, history: list[tuple[str, str]] | None = None, gemini_key: str = "", groq_key: str = "",
        page_ctx: str = "") -> tuple[str, str]:
    """(답, 모델) — 실패하면 RuntimeError. 대화는 최근 3턴만 넘긴다(토큰 절약)."""
    hist = "\n".join(f"{'사용자' if r == 'user' else 'AI'}: {m[:400]}" for r, m in (history or [])[-6:]) or "(없음)"
    prompt = PROMPT.format(tabs=TABS, gloss=glossary(), page=page_ctx or "(종목 분석 화면에서 조회한 종목 없음)",
                           ctx=context(q), hist=hist, q=q.strip()[:500])
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
