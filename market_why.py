"""시황의 '왜' — 그날 가장 큰 움직임에 붙일 뉴스 제목과 출처(2026-11-24 차니: "이유 붙이면 당연히 좋죠").

원칙
- **요약하지 않는다.** 뉴스 제목을 그대로, 언론사 이름과 함께 붙인다. 지어낼 여지를 없앤다.
- 리포트 날짜 기준 36시간 안에 나온 기사만. 못 찾으면 비운다(빈칸이 틀린 이유보다 낫다).
- 출처: Google News RSS(한국어). 해외 서버(GitHub Actions)에서 닿는다.
"""
import html
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

import requests

_JUNK = re.compile(r"\[포토\]|\[사진\]|\[영상\]|광고|이벤트|무료|리딩방|급등주 추천|특징주 TOP|오늘의 운세|\[공시\]|코인|비트코인 시세")
_UA = {"User-Agent": "Mozilla/5.0 (market-report)"}


def _rss(q: str, hours=36, timeout=12) -> list:
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:2d")
           + "&hl=ko&gl=KR&ceid=KR:ko")
    r = requests.get(url, headers=_UA, timeout=timeout)
    r.raise_for_status()
    now = datetime.now(timezone.utc)
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        t = html.unescape(it.findtext("title") or "").strip()
        src = (it.findtext("source") or "").strip()
        if src and t.endswith(" - " + src):
            t = t[: -len(" - " + src)].strip()
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            continue
        if now - dt > timedelta(hours=hours) or _JUNK.search(t) or len(t) < 12:
            continue
        out.append(dict(title=t, source=src or "-", url=it.findtext("link"), date=dt.astimezone(timezone(timedelta(hours=9))).strftime("%m-%d %H:%M")))
    return out


_UPW = ("급등", "상승", "강세", "랠리", "반등", "치솟", "↑")
_DNW = ("급락", "하락", "약세", "폭락", "추락", "↓")


# 2026-11-26 차니: "'왜'에 대한 얘기가 전혀 없음 — PCE 예상 상회로 나스닥 -4%까지 갔다가 살아 돌아왔는데"
#   '뉴욕증시 혼조 마감' 같은 결과 기사보다 원인 단어가 든 제목을 먼저 고른다.
_CAUSE = re.compile(r"PCE|CPI|PPI|물가|고용|실업|금리|연준|Fed|파월|FOMC|국채|관세|실적|가이던스|전망|우려|기대|쇼크|예상|"
                    r"반발|매수세|저가|반등|낙폭|회복|장중|급반등|만회|지정학|전쟁|협상|규제")


def _pick(items, must=(), sign=None, prefer=None):
    if prefer is not None:
        hit = _pick([it for it in items if prefer.search(it["title"])], must, sign)
        if hit:
            return hit
    """제목에 must 단어 중 하나가 들어간 첫 기사. sign(+1/-1)이 있으면 제목 방향이 반대인 기사는 버린다.
    2026-11-25 — 엔비디아 -5.9% 날에 전날 '31% 급등' 기사가 붙었다(날짜 창 36시간 + 방향 무검사)."""
    for it in items:
        if must and not any(m in it["title"] for m in must):
            continue
        if sign:
            up, dn = any(w in it["title"] for w in _UPW), any(w in it["title"] for w in _DNW)
            if (sign > 0 and dn and not up) or (sign < 0 and up and not dn):
                continue
        return it
    return None


def find(targets: list) -> list:
    """targets = [(라벨, 검색어, 제목에 있어야 할 단어들, 시간 창(h), 방향 ±1|None)] → [{label, title, source, url, date}]."""
    out = []
    seen = set()
    for label, q, must, hours, sign in targets:
        try:
            items = [x for x in _rss(q, hours=hours) if x["title"] not in seen]
            it = _pick(items, must, sign, prefer=_CAUSE)
        except Exception as e:
            print(f"  이유 뉴스 실패({q}):", str(e)[:80])
            it = None
        if it:
            seen.add(it["title"])
            out.append(dict(label=label, **it))
        time.sleep(0.5)
    return out


def headlines(f: dict, n=8) -> list:
    """해설용 기사 제목 묶음 — 그날 시장 기사 여러 개(원인 단어 든 것 먼저). 2026-11-26 '재료 설명이 없다'(차니)."""
    q, hours = ("뉴욕증시", 12) if f.get("kind") != "kr" else ("코스피", 9)
    out, seen = [], set()
    for qq in (q + " 마감", q + " 장중", q + " 이유"):
        try:
            for it in _rss(qq, hours=hours):
                if it["title"] not in seen:
                    seen.add(it["title"])
                    out.append(it)
        except Exception as e:
            print(f"  해설용 기사 실패({qq}):", str(e)[:60])
        time.sleep(0.4)
    out.sort(key=lambda it: not _CAUSE.search(it["title"]))
    return out[:n]


def targets_for(f: dict) -> list:
    """리포트 사실에서 '이유를 붙일 대상'을 고른다 — 지수 하나 + 가장 큰 움직임 1~2개."""
    kind = f.get("kind")
    T = []
    if kind == "kr":
        ks = next((x for x in f.get("indices") or [] if x.get("sym") == "^KS11"), {})
        if ks.get("d1") is not None:
            T.append(("코스피", "코스피 마감", ("코스피",), 9, 1 if ks["d1"] > 0 else -1))   # 한국 장 09~15:30 → 07시 이후 기사
            if ks.get("lo_pct") is not None and (ks["d1"] - ks["lo_pct"] >= 1.5 or ks.get("hi_pct", 0) - ks["d1"] >= 1.5):
                T.append(("장중 흐름", "코스피 장중", ("코스피", "장중"), 9, None))
        kr = (f.get("stocks") or {}).get("KR") or {}
        th = (kr.get("themes_top") or [{}])[0]
        if th.get("name") and abs(th.get("ret") or 0) >= 3:
            lead = (th.get("lead") or [{}])[0].get("name")
            T.append((f"{th['name']} 테마", f"{lead or th['name']} 주가", tuple(x for x in (lead, th["name"].split("/")[0]) if x),
                      9, 1 if th["ret"] > 0 else -1))
    else:
        # 미국 장 = KST 23:30~06:00 → 발행(06:10) 기준 12시간 안 기사만. 지수는 혼조가 흔해 방향 검사 안 함
        T.append(("뉴욕증시", "뉴욕증시 마감", ("뉴욕증시", "다우", "나스닥", "S&P"), 12, None))
        # 장중에 크게 흔들린 날은 그 이유를 한 번 더 — '장중' 기사
        nq = next((x for x in f.get("indices") or [] if x.get("sym") == "^IXIC"), {})
        if nq.get("lo_pct") is not None and nq.get("d1") is not None and (nq["d1"] - nq["lo_pct"] >= 1.5 or nq.get("hi_pct", 0) - nq["d1"] >= 1.5):
            T.append(("장중 흐름", "뉴욕증시 장중 나스닥", ("나스닥", "뉴욕증시", "장중"), 12, None))
        mc = (f.get("us") or {}).get("megacaps") or []
        big = max(mc, key=lambda r: abs(r.get("d1") or 0), default=None)
        if big and abs(big.get("d1") or 0) >= 5:
            T.append((big["name"], f"{big['name']} 주가", (big["name"],), 12, 1 if big["d1"] > 0 else -1))
    return T


if __name__ == "__main__":
    import json, sys
    f = json.load(open("results/market_report.json", encoding="utf-8"))[f"latest_{sys.argv[1] if len(sys.argv) > 1 else 'kr'}"]["facts"]
    print(json.dumps(find(targets_for(f)), ensure_ascii=False, indent=1))
